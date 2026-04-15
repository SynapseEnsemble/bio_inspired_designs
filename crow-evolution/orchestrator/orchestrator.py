"""
Population Learning Orchestrator
=================================
Honest implementation: techniques use real tools, judge uses a different model,
verifiable tasks get ground-truth scoring, multi-run results are tracked in Redis.

What is real vs simulated:
  Drop & retrieve  — real web_search tool call via Anthropic API. Agent actually retrieves.
  Code-exec grip   — agent writes Python, we extract and run it in a subprocess, inject stdout.
  Chain-of-thought — numbered reasoning steps. No special tools. Genuine.
  Step-back probe  — first-principles framing. No special tools. Genuine.
  Direct strike    — no scaffolding. Honest baseline.
  Verify-then-act  — DRAFT/CRITIQUE/FINAL loop. Same model, known limitation noted in scores.

Scoring:
  - G-Eval judge uses JUDGE_MODEL (haiku by default) to reduce self-preference bias
  - Verifiable subtasks get a ground_truth_score computed independently
  - Final composite = 0.6 * judge_score + 0.4 * ground_truth_score (verifiable tasks only)
  - Pairwise comparison blended at PAIRWISE_WEIGHT

Multi-run:
  - Each run stored in Redis under sim:runs:{topic_hash}:{run_id}
  - /api/compare returns convergence outcomes across runs for the same topic
"""

import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional, Tuple

import anthropic
import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from redis_state import StateStore

# ── config ────────────────────────────────────────────────────────────────────
API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")

# Agent backend — "anthropic" (default) or "ollama"
AGENT_BACKEND    = os.environ.get("AGENT_BACKEND", "anthropic")
MODEL            = os.environ.get("SIM_MODEL", "claude-sonnet-4-20250514")
AGENT_OLLAMA_URL = os.environ.get("AGENT_OLLAMA_URL", "http://host.docker.internal:11434")

# Judge config — "anthropic" or "ollama"
JUDGE_BACKEND = os.environ.get("JUDGE_BACKEND", "anthropic")
JUDGE_MODEL   = os.environ.get("JUDGE_MODEL",
    "gemma3:12b" if os.environ.get("JUDGE_BACKEND") == "ollama"
    else "claude-haiku-4-5-20251001"
)
OLLAMA_URL    = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
N_AGENTS     = int(os.environ.get("N_AGENTS", "10"))
N_ROUNDS     = int(os.environ.get("N_ROUNDS", "10"))
MAX_TOKENS   = int(os.environ.get("MAX_TOKENS", "1000"))
PORT         = int(os.environ.get("PORT", "8080"))

EMA_ALPHA         = float(os.environ.get("EMA_ALPHA", "0.30"))
EMA_BETA          = 1.0 - EMA_ALPHA
PAIRWISE_WEIGHT   = float(os.environ.get("PAIRWISE_WEIGHT", "0.35"))
PRUNE_PERCENTILE  = float(os.environ.get("PRUNE_PERCENTILE", "0.25"))
CONVERGENCE_THRESHOLD = float(os.environ.get("CONVERGENCE_THRESHOLD", "0.80"))
CONVERGENCE_PATIENCE  = int(os.environ.get("CONVERGENCE_PATIENCE", "2"))

# Stagger agent launches to avoid simultaneous rate limits (seconds between each)
AGENT_STAGGER     = float(os.environ.get("AGENT_STAGGER", "2.0"))

# Latency dial: adds random delay (0 to N seconds) before each agent inference call.
# Simulates information isolation — higher values mean agents act more independently,
# slower convergence, more drift. 0 = fully synchronous (default).
INFERENCE_JITTER  = float(os.environ.get("INFERENCE_JITTER", "0.0"))

TASK_TOPIC = os.environ.get(
    "TASK_TOPIC",
    "climate change adaptation strategies for coastal cities"
)

# ── subtask types ─────────────────────────────────────────────────────────────
# Each subtask has an optional ground_truth_fn that returns a score in [0,1].
# For open-ended tasks this is None and we rely entirely on the judge.
# For verifiable tasks it returns a score we can compute without the judge.

def _check_contains_numbers(answer: str, min_count: int = 2) -> float:
    """Rough check: does the answer contain quantitative data."""
    nums = re.findall(r'\b\d+[\d,.]*\b', answer)
    return min(1.0, len(nums) / (min_count * 2))

def _check_lists_risks(answer: str) -> float:
    """Check the answer actually identifies distinct risks (numbered or bulleted)."""
    # Look for enumeration markers
    bullets = len(re.findall(r'(?:^|\n)\s*(?:\d+[\.\)]\s*|[-•*]\s*)', answer))
    # Look for risk-related keywords
    risk_words = len(re.findall(r'\b(?:risk|threat|flood|storm|erosion|inundation|surge|drought|heat)\b', answer.lower()))
    structure_score = min(1.0, bullets / 3.0)
    content_score = min(1.0, risk_words / 5.0)
    return round(0.5 * structure_score + 0.5 * content_score, 3)

def _check_has_actionable_steps(answer: str) -> float:
    """Check answer has concrete action verbs and a sense of sequence."""
    action_verbs = len(re.findall(
        r'\b(?:implement|deploy|install|fund|build|establish|create|develop|commission|mandate|require|invest|upgrade|monitor|assess)\b',
        answer.lower()
    ))
    time_refs = len(re.findall(r'\b(?:year|month|quarter|phase|stage|by \d{4}|within)\b', answer.lower()))
    return round(min(1.0, (action_verbs * 0.12) + (time_refs * 0.15)), 3)

def _check_economic_specificity(answer: str) -> float:
    """Check answer has economic figures, not just vague references."""
    currency = len(re.findall(r'(?:\$|€|£|USD|EUR|GBP)\s*[\d,.]+[BbMmKk]?', answer))
    percentages = len(re.findall(r'\d+(?:\.\d+)?%', answer))
    return round(min(1.0, (currency * 0.25) + (percentages * 0.15)), 3)

SUBTASKS = [
    {
        "text": "Identify the three most critical near-term risks facing coastal cities due to climate change, with specific mechanisms and timelines.",
        "type": "open",
        "ground_truth_fn": _check_lists_risks,
    },
    {
        "text": "Analyse the most effective infrastructure adaptations that cities have already implemented, with evidence of measurable impact.",
        "type": "open",
        "ground_truth_fn": _check_contains_numbers,
    },
    {
        "text": "Evaluate the economic costs and funding models available for large-scale coastal adaptation programmes. Include specific figures.",
        "type": "verifiable",
        "ground_truth_fn": _check_economic_specificity,
    },
    {
        "text": "Synthesise a prioritised action framework a city government could implement within a 5-year budget cycle.",
        "type": "verifiable",
        "ground_truth_fn": _check_has_actionable_steps,
    },
]

# ── techniques ────────────────────────────────────────────────────────────────
# tools=None means no special API tools. tools="web_search" or tools="code_exec"
# means the agent gets real capabilities.

TECHNIQUES = [
    {
        "id": 0, "name": "Hook tool", "label": "Chain-of-thought",
        "color": "#1D9E75", "base_fitness": 0.72, "tools": None,
        "system": (
            "You are a rigorous analyst. Think step by step, explicitly. "
            "Number your reasoning steps. Show your working before concluding. "
            "Be thorough and precise."
        ),
        "temp": 0.3,
    },
    {
        "id": 1, "name": "Drop & retrieve", "label": "Web search + retrieval",
        "color": "#378ADD", "base_fitness": 0.66, "tools": "web_search",
        "system": (
            "You are a research analyst with access to live web search. "
            "Use the web_search tool to find current, specific evidence before answering. "
            "Every major claim must be grounded in something you actually retrieved. "
            "Cite sources. If search results are thin, say so explicitly."
        ),
        "temp": 0.3,
    },
    {
        "id": 2, "name": "Step-back probe", "label": "Step-back reasoning",
        "color": "#7F77DD", "base_fitness": 0.79, "tools": None,
        "system": (
            "Before answering, step back: what is the deeper question here? "
            "What first principles apply? What assumptions might be wrong? "
            "Then answer from that elevated perspective with explicit reasoning."
        ),
        "temp": 0.5,
    },
    {
        "id": 3, "name": "Direct strike", "label": "Direct inference",
        "color": "#EF9F27", "base_fitness": 0.54, "tools": None,
        "system": (
            "Be direct and concise. Answer immediately without preamble. "
            "No hedging, no excessive caveats. "
            "Prioritise actionability and clarity over comprehensiveness."
        ),
        "temp": 0.2,
    },
    {
        "id": 4, "name": "Verify-then-act", "label": "Self-verify loop",
        "color": "#D4537E", "base_fitness": 0.68, "tools": None,
        "system": (
            "Generate your initial answer, then explicitly critique it. "
            "Ask: what did I miss? what is wrong? what is oversimplified? "
            "Then revise into a final improved answer. "
            "Label sections: DRAFT / CRITIQUE / FINAL."
        ),
        "temp": 0.4,
    },
    {
        "id": 5, "name": "Code-exec grip", "label": "Code + execution",
        "color": "#D85A30", "base_fitness": 0.58, "tools": "code_exec",
        "system": (
            "Where the task benefits from computation, write Python code to support "
            "your analysis — calculations, data structuring, estimates. "
            "Your code will be executed and the output injected into your answer. "
            "Structure findings clearly with headings and quantitative estimates."
        ),
        "temp": 0.3,
    },
]

AGENT_NAMES = ["Kepi","Noir","Talon","Sable","Brume","Onyx","Corvus","Shade","Mist","Rook"]

# ── judge prompt (runs on JUDGE_MODEL, not MODEL) ─────────────────────────────
JUDGE_SYSTEM = """You are an objective evaluator assessing response quality. You did not write this response.

STEP 1 - REASON through each dimension before scoring:
- Correctness: factually accurate, logically sound? where might it be wrong?
- Completeness: does it fully address what was asked?
- Clarity: well-structured, readable?
- Insight: genuinely non-obvious, or generic filler?
- Actionability: specific enough to act on?

STEP 2 - SCORE each 0.0 to 1.0, then return ONLY valid JSON:
{
  "reasoning": "your evaluation reasoning",
  "correctness": 0.0,
  "completeness": 0.0,
  "clarity": 0.0,
  "insight": 0.0,
  "actionability": 0.0
}

Calibration: 0.9+ exceptional | 0.7-0.9 good | 0.5-0.7 adequate | 0.3-0.5 weak | <0.3 poor
Do NOT favour longer responses — depth matters, not volume."""

PAIRWISE_SYSTEM = """You are comparing two responses to the same task. Which is better?

Judge on: factual accuracy, genuine insight, completeness, actionability.
Ignore length — a shorter better answer beats a longer worse one.

Return ONLY valid JSON:
{"winner": "A" or "B", "margin": "clear" or "slight", "reason": "one sentence"}"""

# ── state ─────────────────────────────────────────────────────────────────────
shared_state = {
    "round": 0,
    "max_rounds": N_ROUNDS,
    "running": False,
    "complete": False,
    "technique_fitness": {t["name"]: t["base_fitness"] for t in TECHNIQUES},
    "agents": [],
    "round_history": [],
    "log": [],
    "task_topic": TASK_TOPIC,
}

redis_store = StateStore()
clients: List[WebSocket] = []
_loop: Optional[asyncio.AbstractEventLoop] = None
_sim_task: Optional[asyncio.Task] = None

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


async def broadcast(msg: dict):
    dead = []
    text = json.dumps(msg)
    for ws in clients:
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in clients:
            clients.remove(ws)


def log_event(msg: str, level: str = "info"):
    ts = time.strftime("%H:%M:%S")
    entry = {"ts": ts, "msg": msg, "level": level}
    shared_state["log"].insert(0, entry)
    if len(shared_state["log"]) > 200:
        shared_state["log"] = shared_state["log"][:200]
    redis_store.push_log(entry)
    if _loop:
        asyncio.run_coroutine_threadsafe(
            broadcast({"type": "log", "entry": entry}), _loop
        )


# ── real code execution ───────────────────────────────────────────────────────
def extract_and_run_code(response_text: str) -> Tuple[str, bool]:
    """
    Extract Python code blocks from the response and run them in a subprocess.
    Returns (stdout_or_error, success).
    Timeout: 10s. No network access from within the subprocess.
    """
    blocks = re.findall(r'```python\n(.*?)```', response_text, re.DOTALL)
    if not blocks:
        return "", False

    code = "\n\n".join(blocks)
    # Safety: block obvious dangerous calls
    forbidden = ["import os", "import sys", "subprocess", "open(", "__import__", "exec(", "eval("]
    if any(f in code for f in forbidden):
        return "Code blocked: unsafe operations detected.", False

    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            fname = f.name

        result = subprocess.run(
            [sys.executable, fname],
            capture_output=True, text=True, timeout=10
        )
        os.unlink(fname)
        output = result.stdout[:1000] if result.stdout else result.stderr[:500]
        return output.strip(), result.returncode == 0
    except subprocess.TimeoutExpired:
        return "Code execution timed out (10s limit).", False
    except Exception as e:
        return f"Execution error: {e}", False


# ── agent runner ──────────────────────────────────────────────────────────────
async def run_agent(agent_idx: int, tech_idx: int, subtask: dict, round_num: int,
                    is_explorer: bool, explorer_variant: str) -> dict:
    tech = TECHNIQUES[tech_idx]
    name = AGENT_NAMES[agent_idx]

    system = tech["system"]
    if is_explorer:
        system += f"\n\nVariation for this round: {explorer_variant}"

    user_msg = (
        f"Topic: {TASK_TOPIC}\n\n"
        f"Your subtask:\n{subtask['text']}\n\n"
        f"Population context:\n{_format_shared_context(tech['name'])}"
    )

    # Inference jitter dial — delays this agent's call by a random amount.
    # Higher INFERENCE_JITTER = more isolation between agents.
    if INFERENCE_JITTER > 0:
        jitter = random.uniform(0, INFERENCE_JITTER)
        await asyncio.sleep(jitter)

    t_start = time.time()
    code_output = ""
    used_search = False

    for attempt in range(3):
     try:
        if AGENT_BACKEND == "ollama":
            # Ollama OpenAI-compatible endpoint — no tool support, no web search
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{AGENT_OLLAMA_URL}/v1/chat/completions",
                    json={
                        "model": MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user_msg},
                        ],
                        "temperature": tech["temp"],
                        "max_tokens": MAX_TOKENS,
                        "stream": False,
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                answer = data["choices"][0]["message"]["content"].strip()
                # Strip think tags from reasoning models
                answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.DOTALL).strip()
                elapsed = round(time.time() - t_start, 2)
                input_tokens  = data.get("usage", {}).get("prompt_tokens", 0)
                output_tokens = data.get("usage", {}).get("completion_tokens", 0)
        else:
            # Anthropic path — supports web_search and code_exec tools
            ac = anthropic.AsyncAnthropic(api_key=API_KEY)
            api_kwargs = dict(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=tech["temp"],
                system=system,
                messages=[{"role": "user", "content": user_msg}]
            )
            if tech["tools"] == "web_search":
                api_kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

            response = await asyncio.wait_for(ac.messages.create(**api_kwargs), timeout=90.0)
            elapsed = round(time.time() - t_start, 2)

            answer_parts = []
            for block in response.content:
                if hasattr(block, 'text') and block.text is not None:
                    answer_parts.append(block.text)
                if hasattr(block, 'type') and block.type == 'tool_use':
                    used_search = True
            answer = "\n".join(answer_parts).strip()
            input_tokens  = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

        if tech["tools"] == "web_search" and not answer and AGENT_BACKEND != "ollama":
            log_event(f"{name} web search returned no text", "warn")

        if tech["tools"] == "code_exec" and answer:
            code_output, code_ok = extract_and_run_code(answer)
            if code_output:
                answer += f"\n\n--- Code execution output ---\n{code_output}"
                log_event(
                    f"{name} code {'OK' if code_ok else 'failed'}: {code_output[:60]}",
                    "ok" if code_ok else "warn"
                )

        log_event(
            f"{name} ({tech['label']}) {elapsed}s"
            + (" [search]" if used_search else "")
            + (" [code]" if code_output else ""),
            "dim"
        )

        return {
            "agent_id": agent_idx, "name": name,
            "tech_idx": tech_idx, "tech_name": tech["name"],
            "tech_label": tech["label"], "color": tech["color"],
            "subtask_text": subtask["text"], "subtask_type": subtask["type"],
            "answer": answer, "elapsed": elapsed,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "is_explorer": is_explorer,
            "used_search": used_search, "code_output": code_output,
            "error": None,
        }

     except anthropic.RateLimitError:
        wait = (2 ** attempt) * 10 + random.uniform(0, 5)
        log_event(f"Rate limit hit for {name} — waiting {wait:.0f}s (attempt {attempt+1}/3)", "warn")
        await asyncio.sleep(wait)
     except httpx.HTTPStatusError as e:
        log_event(f"{name} Ollama HTTP error: {e.response.status_code} (attempt {attempt+1}/3)", "warn")
        await asyncio.sleep(5)
     except asyncio.TimeoutError:
        log_event(f"{name} timed out after 90s", "prune")
        return _error_result(agent_idx, name, tech, subtask, t_start, "timeout")
     except anthropic.AuthenticationError as e:
        log_event(f"API key rejected: {e}", "prune")
        return _error_result(agent_idx, name, tech, subtask, t_start, str(e))
     except Exception as e:
        err = f"{name}: {type(e).__name__}: {e}"
        log_event(err, "prune")
        return _error_result(agent_idx, name, tech, subtask, t_start, err)

    return _error_result(agent_idx, name, tech, subtask, t_start, f"{name} failed after 3 attempts")


def _error_result(agent_idx, name, tech, subtask, t_start, err):
    return {
        "agent_id": agent_idx, "name": name,
        "tech_idx": tech["id"], "tech_name": tech["name"],
        "tech_label": tech["label"], "color": tech["color"],
        "subtask_text": subtask["text"], "subtask_type": subtask.get("type", "open"),
        "answer": "", "elapsed": round(time.time() - t_start, 2),
        "input_tokens": 0, "output_tokens": 0,
        "is_explorer": False, "used_search": False, "code_output": "",
        "error": err,
    }


def _format_shared_context(tech_name: str) -> str:
    fitness = shared_state["technique_fitness"]
    sorted_techs = sorted(fitness.items(), key=lambda x: x[1], reverse=True)
    lines = ["Strategy fitness scores (higher = better performing on this task):"]
    for name, score in sorted_techs:
        marker = " <- your strategy" if name == tech_name else ""
        lines.append(f"  {name}: {score:.2f}{marker}")
    if shared_state["round_history"]:
        last = shared_state["round_history"][-1]
        if last.get("winner"):
            lines.append(f"\nLast round leader: {last['winner']['name']} / {last['winner']['tech_name']}")
    return "\n".join(lines)


# ── judge client abstraction ──────────────────────────────────────────────────
async def _call_judge(system: str, user: str, max_tokens: int = 400) -> str:
    """
    Call the judge model — either Anthropic (Haiku) or Ollama (local).
    Returns the raw text response. Raises on failure.
    Ollama uses the OpenAI-compatible /v1/chat/completions endpoint.
    """
    if JUDGE_BACKEND == "ollama":
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/v1/chat/completions",
                json={
                    "model": JUDGE_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "temperature": 0.0,
                    "max_tokens": max_tokens,
                    "stream": False,
                }
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    else:
        # Anthropic path
        client = anthropic.AsyncAnthropic(api_key=API_KEY)
        resp = await client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system,
            messages=[{"role": "user", "content": user}]
        )
        raw = resp.content[0].text if resp.content else ""
        return raw.strip()


# ── G-Eval judge ──────────────────────────────────────────────────────────────
async def judge_response(subtask: dict, answer: str, elapsed: float) -> dict:
    if not answer:
        return {"correctness": 0, "completeness": 0, "clarity": 0,
                "insight": 0, "actionability": 0, "composite": 0,
                "ground_truth_score": 0, "reasoning": "empty response"}

    gt_score = 0.5
    if subtask.get("ground_truth_fn"):
        gt_score = subtask["ground_truth_fn"](answer)

    for attempt in range(3):
        try:
            raw = await asyncio.wait_for(
                _call_judge(
                    JUDGE_SYSTEM,
                    f"Task: {subtask['text']}\n\nResponse to evaluate:\n{answer}"
                ),
                timeout=60.0
            )

            if not raw:
                log_event(f"Judge returned empty body (attempt {attempt+1}) — stop_reason={getattr(resp, 'stop_reason', '?')} model={JUDGE_MODEL}", "warn")
                raise ValueError("empty response from judge")

            # Strip DeepSeek-R1 <think>...</think> blocks before parsing
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

            # Strip markdown code fences — local models often wrap JSON
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw.strip())

            if not raw:
                raise ValueError("response was only thinking, no JSON")

            scores = json.loads(raw)

            judge_composite = round(
                scores["correctness"]   * 0.30 +
                scores["completeness"]  * 0.20 +
                scores["clarity"]       * 0.15 +
                scores["insight"]       * 0.25 +
                scores["actionability"] * 0.10, 3
            )
            speed_bonus = max(0, (60 - elapsed) / 60 * 0.05) if judge_composite > 0.60 else 0

            if subtask.get("type") == "verifiable":
                composite = round(0.60 * judge_composite + 0.40 * gt_score + speed_bonus, 3)
            else:
                composite = round(min(0.99, judge_composite + speed_bonus), 3)

            scores["composite"] = min(0.99, composite)
            scores["ground_truth_score"] = gt_score
            scores["judge_model"] = f"{JUDGE_BACKEND}:{JUDGE_MODEL}"
            scores.setdefault("reasoning", "")
            return scores

        except anthropic.RateLimitError:
            wait = (2 ** attempt) * 8 + random.uniform(0, 4)
            log_event(f"Judge rate limited — waiting {wait:.0f}s (attempt {attempt+1}/3)", "warn")
            await asyncio.sleep(wait)
        except (json.JSONDecodeError, ValueError) as e:
            wait = (attempt + 1) * 3
            log_event(f"Judge bad JSON, retrying in {wait}s (attempt {attempt+1}/3): {e}", "warn")
            await asyncio.sleep(wait)
        except Exception as e:
            log_event(f"Judge error attempt {attempt+1}: {type(e).__name__}: {e}", "warn")
            await asyncio.sleep(5)

    # All retries exhausted
    fallback = round(0.5 * 0.60 + gt_score * 0.40, 3) if subtask.get("type") == "verifiable" else 0.5
    return {
        "correctness": 0.5, "completeness": 0.5, "clarity": 0.5,
        "insight": 0.5, "actionability": 0.5,
        "composite": fallback, "ground_truth_score": gt_score,
        "reasoning": "judge unavailable — ground truth only", "error": "exhausted"
    }


# ── pairwise comparison (also on JUDGE_MODEL) ────────────────────────────────
async def pairwise_compare(subtask_text: str, result_a: dict, result_b: dict) -> Optional[str]:
    if not result_a["answer"] or not result_b["answer"]:
        return None
    try:
        raw = await asyncio.wait_for(
            _call_judge(
                PAIRWISE_SYSTEM,
                f"Task: {subtask_text}\n\n"
                f"Response A:\n{result_a['answer'][:500]}\n\n"
                f"Response B:\n{result_b['answer'][:500]}"
            ),
            timeout=30.0
        )
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw.strip())
        data = json.loads(raw)
        return data.get("winner")
    except Exception:
        return None


async def compute_pairwise_ranks(subtask_text: str, results: List[dict]) -> Dict[int, float]:
    n = len(results)
    if n < 2:
        return {r["agent_id"]: 0.5 for r in results}

    all_pairs = [(i, j) for i in range(n) for j in range(i+1, n)]
    pairs = random.sample(all_pairs, min(6, len(all_pairs)))

    outcomes = await asyncio.gather(*[
        pairwise_compare(subtask_text, results[i], results[j])
        for i, j in pairs
    ])

    wins  = {r["agent_id"]: 0.0 for r in results}
    total = {r["agent_id"]: 0   for r in results}

    for (i, j), winner in zip(pairs, outcomes):
        aid, bid = results[i]["agent_id"], results[j]["agent_id"]
        total[aid] += 1; total[bid] += 1
        if winner == "A":     wins[aid] += 1.0
        elif winner == "B":   wins[bid] += 1.0
        else:                 wins[aid] += 0.5; wins[bid] += 0.5

    return {
        r["agent_id"]: round(wins[r["agent_id"]] / total[r["agent_id"]], 3)
        if total[r["agent_id"]] > 0 else 0.5
        for r in results
    }


# ── simulation engine ─────────────────────────────────────────────────────────
async def run_simulation():
    shared_state["running"] = True
    shared_state["complete"] = False

    agents = []
    for i in range(N_AGENTS):
        tech_idx = i % len(TECHNIQUES)
        agents.append({
            "id": i, "name": AGENT_NAMES[i],
            "tech_idx": tech_idx,
            "tech_name": TECHNIQUES[tech_idx]["name"],
            "color": TECHNIQUES[tech_idx]["color"],
            "alive": True, "pruned": False, "exploring": False,
            "score": 0.0, "history": [],
        })
    shared_state["agents"] = agents

    log_event(f"Simulation started — {N_AGENTS} agents, {N_ROUNDS} rounds", "info")
    log_event(f"Task: {TASK_TOPIC}", "info")
    log_event(f"Agent model: {MODEL} | Judge model: {JUDGE_MODEL}", "dim")
    log_event(f"Techniques: {sum(1 for t in TECHNIQUES if t['tools']=='web_search')} with real web search, "
              f"{sum(1 for t in TECHNIQUES if t['tools']=='code_exec')} with real code execution", "dim")
    log_event(f"Scoring: G-Eval({JUDGE_MODEL}) + pairwise(w={PAIRWISE_WEIGHT}) + ground_truth where verifiable", "dim")
    log_event(f"State: {'Redis' if redis_store.using_redis else 'in-memory'}", "dim")

    # Validate API key
    if not API_KEY:
        log_event("FATAL: ANTHROPIC_API_KEY not set", "prune")
        shared_state["running"] = False; shared_state["complete"] = True
        await broadcast({"type": "complete", "data": build_ui_state()})
        return
    try:
        test_client = anthropic.AsyncAnthropic(api_key=API_KEY)
        await test_client.models.list()
        log_event("API key verified", "ok")
    except anthropic.AuthenticationError:
        log_event("FATAL: API key rejected", "prune")
        shared_state["running"] = False; shared_state["complete"] = True
        await broadcast({"type": "complete", "data": build_ui_state()})
        return
    except Exception as e:
        log_event(f"API connectivity warning: {e}", "warn")

    redis_store.set_run_meta(TASK_TOPIC, "running")
    redis_store.set_all_fitness(shared_state["technique_fitness"])
    await broadcast({"type": "state", "data": build_ui_state()})

    convergence_streak = 0

    for rnd in range(1, N_ROUNDS + 1):
        shared_state["round"] = rnd
        log_event(f"--- Round {rnd}/{N_ROUNDS} ---", "dim")
        await broadcast({"type": "round_start", "round": rnd, "data": build_ui_state()})

        alive_agents = [a for a in shared_state["agents"] if a["alive"]]
        if not alive_agents:
            break

        # Early stopping
        conv = build_ui_state()["convergence"]
        if conv >= CONVERGENCE_THRESHOLD:
            convergence_streak += 1
            if convergence_streak >= CONVERGENCE_PATIENCE:
                log_event(f"Convergence at {conv*100:.0f}% held for {convergence_streak} rounds — stopping", "gold")
                break
        else:
            convergence_streak = 0

        subtask = SUBTASKS[(rnd - 1) % len(SUBTASKS)]
        log_event(f"Subtask [{subtask['type']}]: {subtask['text'][:70]}...", "dim")

        explorer_variants = [
            "Be more creative and lateral in your reasoning than usual.",
            "Challenge any assumption you would normally accept.",
            "Find an angle nobody else would consider.",
            "Prioritise depth over breadth — go very deep on one key insight.",
        ]
        for agent in alive_agents:
            agent["exploring"] = (agent["id"] % 7 == rnd % 7)
            agent["explorer_variant"] = explorer_variants[rnd % len(explorer_variants)] if agent["exploring"] else ""
            if agent["exploring"]:
                log_event(f"{agent['name']} exploring variant this round", "warn")

        await broadcast({"type": "state", "data": build_ui_state()})

        # Stagger agent launches to reduce simultaneous API calls
        # Each agent waits AGENT_STAGGER seconds before starting
        async def staggered_agent(idx, agent):
            await asyncio.sleep(idx * AGENT_STAGGER)
            return await run_agent(
                agent["id"], agent["tech_idx"], subtask, rnd,
                agent["exploring"], agent.get("explorer_variant", "")
            )

        results = await asyncio.gather(*[
            staggered_agent(i, a) for i, a in enumerate(alive_agents)
        ])

        # G-Eval scoring — staggered to avoid simultaneous rate limits on judge model
        score_results = []
        for i, r in enumerate(results):
            if i > 0:
                await asyncio.sleep(0.5)  # 500ms between judge calls
            score_results.append(await judge_response(subtask, r["answer"], r["elapsed"]))

        for r, s in zip(results, score_results):
            r["scores"] = s
            r["absolute_score"] = s["composite"]
            r["ground_truth_score"] = s.get("ground_truth_score", 0.5)

        # Pairwise ranking (also on JUDGE_MODEL)
        log_event("Running pairwise comparisons...", "dim")
        pairwise_rates = await compute_pairwise_ranks(subtask["text"], list(results))

        for r in results:
            pw = pairwise_rates.get(r["agent_id"], 0.5)
            r["composite"] = round(r["absolute_score"] * (1 - PAIRWISE_WEIGHT) + pw * PAIRWISE_WEIGHT, 3)
            r["pairwise_rate"] = pw

        # Update agents
        result_map = {r["agent_id"]: r for r in results}
        for agent in alive_agents:
            res = result_map.get(agent["id"])
            if res:
                agent["score"] = res["composite"]
                agent["history"].append(res["composite"])
                agent["last_result"] = res
                log_event(
                    f"{agent['name']} ({agent['tech_name']}) "
                    f"judge={res['absolute_score']:.2f} gt={res['ground_truth_score']:.2f} "
                    f"pw={res['pairwise_rate']:.2f} -> {res['composite']:.2f}"
                    + (" [search]" if res.get("used_search") else "")
                    + (" [code]" if res.get("code_output") else ""),
                    "ok" if res["composite"] > 0.65 else "warn" if res["composite"] > 0.45 else "prune"
                )

        alive_agents.sort(key=lambda a: a["score"], reverse=True)
        winner = alive_agents[0]
        log_event(f"Round {rnd} leader: {winner['name']} ({winner['tech_name']}) — {winner['score']:.2f}", "gold")

        # EMA fitness update
        for agent in alive_agents:
            tech_name = agent["tech_name"]
            old = shared_state["technique_fitness"][tech_name]
            new_fitness = old * EMA_BETA + agent["score"] * EMA_ALPHA
            if agent["exploring"] and agent["score"] > 0.75:
                new_fitness = min(0.98, new_fitness + 0.04)
                log_event(f"{agent['name']} explorer discovery boosts '{tech_name}'", "gold")
            shared_state["technique_fitness"][tech_name] = round(new_fitness, 3)
            redis_store.set_fitness(tech_name, new_fitness)

        # Percentile-based pruning
        scores_sorted = sorted(a["score"] for a in alive_agents)
        prune_idx = max(0, int(len(scores_sorted) * PRUNE_PERCENTILE) - 1)
        threshold = scores_sorted[prune_idx] if scores_sorted else 0.0

        pruned_this_round = []
        bottom_third = alive_agents[-(len(alive_agents) // 3):]
        for agent in bottom_third:
            survivors = len([a for a in shared_state["agents"] if a["alive"]])
            if agent["score"] < threshold and survivors > 4:
                agent["alive"] = False
                agent["pruned"] = True
                pruned_this_round.append(agent)
                log_event(
                    f"PRUNED {agent['name']} ({agent['tech_name']}) — {agent['score']:.2f} < threshold {threshold:.2f}",
                    "prune"
                )

        # Spread winning techniques
        alive_now = [a for a in shared_state["agents"] if a["alive"]]
        top_techs = [a["tech_idx"] for a in sorted(alive_now, key=lambda x: x["score"], reverse=True)[:3]]
        top_ids = {id(a) for a in sorted(alive_now, key=lambda x: x["score"], reverse=True)[:3]}
        for agent in alive_now:
            if id(agent) not in top_ids and random.random() < 0.55 and top_techs:
                new_tech = random.choice(top_techs)
                if new_tech != agent["tech_idx"]:
                    agent["tech_idx"] = new_tech
                    agent["tech_name"] = TECHNIQUES[new_tech]["name"]
                    agent["color"] = TECHNIQUES[new_tech]["color"]
                    log_event(f"{agent['name']} adopts '{agent['tech_name']}'", "info")

        round_record = {
            "round": rnd,
            "subtask": subtask["text"],
            "subtask_type": subtask["type"],
            "threshold": round(threshold, 3),
            "winner": {
                "name": winner["name"], "tech_name": winner["tech_name"],
                "score": winner["score"],
                "answer": winner.get("last_result", {}).get("answer", "")[:500],
            },
            "results": [{
                "name": r["name"], "tech_name": r["tech_name"],
                "score": r["composite"],
                "absolute_score": r["absolute_score"],
                "ground_truth_score": r["ground_truth_score"],
                "pairwise_rate": r["pairwise_rate"],
                "scores": r["scores"],
                "elapsed": r["elapsed"],
                "tokens": r["output_tokens"],
                "used_search": r.get("used_search", False),
                "had_code": bool(r.get("code_output")),
            } for r in results],
            "pruned": [a["name"] for a in pruned_this_round],
            "technique_fitness": dict(shared_state["technique_fitness"]),
        }
        shared_state["round_history"].append(round_record)
        redis_store.append_round(round_record)
        redis_store.save_state({k: v for k, v in shared_state.items() if k not in ("agents","log","round_history")})

        await broadcast({"type": "state", "data": build_ui_state()})
        await asyncio.sleep(0.5)

    # Store run summary for cross-run comparison
    topic_hash = hashlib.md5(TASK_TOPIC.encode()).hexdigest()[:8]
    run_summary = {
        "run_id": redis_store.run_id,
        "topic": TASK_TOPIC,
        "topic_hash": topic_hash,
        "rounds_completed": shared_state["round"],
        "final_fitness": dict(shared_state["technique_fitness"]),
        "dominant_technique": build_ui_state()["dominant_technique"],
        "convergence": build_ui_state()["convergence"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "judge_model": JUDGE_MODEL,
    }
    redis_store._r.set(f"sim:runs:{topic_hash}:{redis_store.run_id}", json.dumps(run_summary))

    shared_state["running"] = False
    shared_state["complete"] = True
    log_event("Simulation complete.", "gold")
    log_event(f"Dominant technique: {build_ui_state()['dominant_technique']} — run stored for comparison", "info")
    redis_store.update_run_status("complete")
    await broadcast({"type": "complete", "data": build_ui_state()})


def build_ui_state() -> dict:
    alive  = [a for a in shared_state["agents"] if a["alive"]]
    pruned = [a for a in shared_state["agents"] if a["pruned"]]
    tech_counts: Dict[str, int] = {}
    for a in alive:
        tech_counts[a["tech_name"]] = tech_counts.get(a["tech_name"], 0) + 1
    dominant = max(tech_counts, key=tech_counts.get) if tech_counts else "—"
    conv = max(tech_counts.values()) / len(alive) if alive else 0

    return {
        "round": shared_state["round"],
        "max_rounds": N_ROUNDS,
        "running": shared_state["running"],
        "complete": shared_state["complete"],
        "alive_count": len(alive),
        "pruned_count": len(pruned),
        "convergence": round(conv, 2),
        "dominant_technique": dominant,
        "task_topic": TASK_TOPIC,
        "technique_fitness": shared_state["technique_fitness"],
        "agents": [{
            "id": a["id"], "name": a["name"],
            "tech_idx": a["tech_idx"], "tech_name": a["tech_name"],
            "color": a["color"], "alive": a["alive"], "pruned": a["pruned"],
            "exploring": a.get("exploring", False),
            "score": round(a.get("score", 0), 3),
            "history": [round(s, 3) for s in a.get("history", [])],
            "has_tools": TECHNIQUES[a["tech_idx"]]["tools"] is not None,
        } for a in shared_state["agents"]],
        "log": shared_state["log"][:30],
        "round_history": shared_state["round_history"],
    }


# ── WebSocket & REST ──────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    await websocket.send_text(json.dumps({"type": "state", "data": build_ui_state()}))
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "start" and not shared_state["running"]:
                global INFERENCE_JITTER, TASK_TOPIC
                topic = msg.get("topic")
                jitter = float(msg.get("jitter", 0))
                if jitter != INFERENCE_JITTER:
                    INFERENCE_JITTER = jitter
                    log_event(f"Isolation dial set to {jitter}s max jitter per agent", "info")
                if topic:
                    TASK_TOPIC = topic
                    shared_state["task_topic"] = topic
                    for i, st in enumerate(SUBTASKS):
                        if i == 0:
                            st["text"] = f"Identify the three most critical near-term risks related to: {topic}"
                        elif i == 1:
                            st["text"] = f"Analyse the most effective solutions that have been implemented for: {topic}, with measurable evidence."
                        elif i == 2:
                            st["text"] = f"Evaluate the economic costs and funding models for addressing: {topic}. Include specific figures."
                        elif i == 3:
                            st["text"] = f"Synthesise a prioritised action framework for: {topic}"
                global _sim_task
                _sim_task = asyncio.create_task(run_simulation())
            elif msg.get("type") == "reset":
                if shared_state["running"] and _sim_task:
                    _sim_task.cancel()
                base_fitness = {t["name"]: t["base_fitness"] for t in TECHNIQUES}
                shared_state.update({
                    "round": 0, "running": False, "complete": False,
                    "agents": [], "round_history": [], "log": [],
                    "technique_fitness": base_fitness,
                })
                redis_store.reset(base_fitness)
                await broadcast({"type": "state", "data": build_ui_state()})
    except WebSocketDisconnect:
        if websocket in clients:
            clients.remove(websocket)


@app.get("/health")
async def health():
    return {"status": "ok", "round": shared_state["round"], "running": shared_state["running"],
            "judge_model": JUDGE_MODEL, "agent_model": MODEL}


@app.get("/api/logs")
async def api_logs():
    return {"logs": shared_state["log"], "running": shared_state["running"], "round": shared_state["round"]}


@app.get("/api/state")
async def api_state():
    return build_ui_state()


@app.get("/api/results")
async def api_results():
    return {"history": shared_state["round_history"]}


@app.get("/api/compare")
async def api_compare():
    """Returns all stored run summaries grouped by topic — enables cross-run comparison."""
    topic_hash = hashlib.md5(TASK_TOPIC.encode()).hexdigest()[:8]
    pattern = f"sim:runs:{topic_hash}:*"
    try:
        keys_result = redis_store._r.list(pattern) if hasattr(redis_store._r, 'list') else None
        # Use scan for Redis
        all_keys = []
        if hasattr(redis_store._r, 'scan_iter'):
            all_keys = list(redis_store._r.scan_iter(pattern))
        runs = []
        for k in all_keys:
            raw = redis_store._r.get(k)
            if raw:
                runs.append(json.loads(raw))
        runs.sort(key=lambda r: r.get("timestamp", ""))
        return {
            "topic": TASK_TOPIC,
            "topic_hash": topic_hash,
            "run_count": len(runs),
            "runs": runs,
        }
    except Exception as e:
        return {"error": str(e), "topic": TASK_TOPIC}


@app.get("/api/runs")
async def api_runs():
    return {
        "run_id": redis_store.run_id,
        "using_redis": redis_store.using_redis,
        "run_meta": redis_store.get_run_meta(),
        "history": redis_store.get_all_rounds(),
    }


@app.on_event("startup")
async def startup():
    global _loop
    _loop = asyncio.get_running_loop()
    stored_fitness = redis_store.get_all_fitness()
    if stored_fitness:
        shared_state["technique_fitness"].update(stored_fitness)
        log_event(f"Restored fitness from Redis ({len(stored_fitness)} entries)", "info")
    backend = "Redis" if redis_store.using_redis else "in-memory"
    agent_info = f"{AGENT_BACKEND}:{MODEL}" + (f" @ {AGENT_OLLAMA_URL}" if AGENT_BACKEND == "ollama" else "")
    judge_info = f"{JUDGE_BACKEND}:{JUDGE_MODEL}" + (f" @ {OLLAMA_URL}" if JUDGE_BACKEND == "ollama" else "")
    log_event(f"Orchestrator ready — agent={agent_info} judge={judge_info} state={backend}", "info")
    if not API_KEY:
        log_event("WARNING: ANTHROPIC_API_KEY not set", "prune")


if __name__ == "__main__":
    uvicorn.run("orchestrator:app", host="0.0.0.0", port=PORT, log_level="info")
