"""
redis_state.py
==============
Thin wrapper around Redis for shared simulation state.

Provides get/set/publish operations that the orchestrator uses in place of
the in-memory dict. Falls back silently to a local dict if Redis is not
reachable — so the orchestrator works unchanged in environments without Redis.

Key layout:
  sim:state          → JSON blob of the full shared_state dict
  sim:technique_fitness → Hash  {technique_name: float}
  sim:round_history  → List of JSON-encoded round result objects (RPUSH)
  sim:log            → List of JSON-encoded log entries (LPUSH, capped)
  sim:run_meta       → Hash  {run_id, started_at, topic, status}

Pub/Sub channel:
  sim:events         → broadcasts every state update (type + compact payload)

Usage:
  from redis_state import StateStore
  store = StateStore()          # connects to Redis or falls back
  store.set_fitness("Hook tool", 0.82)
  store.publish("state", {...})
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

REDIS_URL   = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
LOG_CAP     = 200   # max log entries kept in Redis
HISTORY_CAP = 20    # max round_history entries kept in Redis

try:
    import redis as _redis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class _FallbackClient:
    """In-process dict that mimics just enough of the redis.Redis API."""

    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._lists: Dict[str, List] = {}
        self._hashes: Dict[str, Dict] = {}
        self._subs: List = []
        log.warning("Redis not available — using in-memory fallback (state lost on restart)")

    def ping(self): return True
    def set(self, key, value, ex=None): self._store[key] = value
    def get(self, key): return self._store.get(key)
    def delete(self, *keys):
        for k in keys: self._store.pop(k, None)

    def hset(self, name, key=None, value=None, mapping=None):
        if name not in self._hashes: self._hashes[name] = {}
        if mapping:
            self._hashes[name].update(mapping)
        elif key is not None:
            self._hashes[name][key] = value

    def hget(self, name, key):
        return self._hashes.get(name, {}).get(key)

    def hgetall(self, name):
        return dict(self._hashes.get(name, {}))

    def lpush(self, name, *values):
        if name not in self._lists: self._lists[name] = []
        for v in values: self._lists[name].insert(0, v)

    def rpush(self, name, *values):
        if name not in self._lists: self._lists[name] = []
        for v in values: self._lists[name].append(v)

    def lrange(self, name, start, end):
        lst = self._lists.get(name, [])
        if end == -1: return lst[start:]
        return lst[start:end + 1]

    def ltrim(self, name, start, end):
        lst = self._lists.get(name, [])
        if end == -1:
            self._lists[name] = lst[start:]
        else:
            self._lists[name] = lst[start:end + 1]

    def llen(self, name):
        return len(self._lists.get(name, []))

    def publish(self, channel, message): pass   # no-op in fallback

    def pipeline(self):
        return _FallbackPipeline(self)


class _FallbackPipeline:
    def __init__(self, client):
        self._client = client
        self._cmds = []

    def __enter__(self): return self
    def __exit__(self, *_): pass

    def lpush(self, *a, **kw): self._cmds.append(("lpush", a, kw)); return self
    def ltrim(self, *a, **kw): self._cmds.append(("ltrim", a, kw)); return self
    def rpush(self, *a, **kw): self._cmds.append(("rpush", a, kw)); return self
    def set(self, *a, **kw):   self._cmds.append(("set", a, kw));   return self
    def hset(self, *a, **kw):  self._cmds.append(("hset", a, kw));  return self

    def execute(self):
        for cmd, args, kwargs in self._cmds:
            getattr(self._client, cmd)(*args, **kwargs)
        self._cmds = []
        return []


class StateStore:
    """
    Provides a clean interface over Redis (or the in-memory fallback).

    The orchestrator calls this instead of touching shared_state directly.
    On startup it either connects to Redis or silently degrades.
    """

    def __init__(self):
        self.run_id = str(uuid.uuid4())[:8]
        self._r = self._connect()
        self._fallback = isinstance(self._r, _FallbackClient)
        if not self._fallback:
            log.info(f"Connected to Redis at {REDIS_URL}")

    def _connect(self):
        if not _REDIS_AVAILABLE:
            return _FallbackClient()
        try:
            import redis
            client = redis.from_url(REDIS_URL, socket_connect_timeout=2, decode_responses=True)
            client.ping()
            return client
        except Exception as e:
            log.warning(f"Redis connection failed ({e}) — falling back to in-memory store")
            return _FallbackClient()

    @property
    def using_redis(self) -> bool:
        return not self._fallback

    # ── full state blob ────────────────────────────────────────────────────────

    def save_state(self, state: dict):
        """Serialise the full shared_state dict to Redis."""
        self._r.set("sim:state", json.dumps(state))

    def load_state(self) -> Optional[dict]:
        raw = self._r.get("sim:state")
        if raw:
            return json.loads(raw)
        return None

    # ── technique fitness (hash) ───────────────────────────────────────────────

    def set_fitness(self, technique: str, score: float):
        self._r.hset("sim:technique_fitness", key=technique, value=str(round(score, 4)))

    def set_all_fitness(self, fitness: Dict[str, float]):
        self._r.hset("sim:technique_fitness", mapping={k: str(round(v, 4)) for k, v in fitness.items()})

    def get_all_fitness(self) -> Dict[str, float]:
        raw = self._r.hgetall("sim:technique_fitness")
        return {k: float(v) for k, v in raw.items()} if raw else {}

    # ── round history (list, capped) ──────────────────────────────────────────

    def append_round(self, round_data: dict):
        pipe = self._r.pipeline()
        pipe.rpush("sim:round_history", json.dumps(round_data))
        pipe.ltrim("sim:round_history", -HISTORY_CAP, -1)
        pipe.execute()

    def get_round_history(self, last_n: int = 3) -> List[dict]:
        raw = self._r.lrange("sim:round_history", -last_n, -1)
        return [json.loads(r) for r in raw] if raw else []

    def get_all_rounds(self) -> List[dict]:
        raw = self._r.lrange("sim:round_history", 0, -1)
        return [json.loads(r) for r in raw] if raw else []

    # ── event log (list, capped) ──────────────────────────────────────────────

    def push_log(self, entry: dict):
        pipe = self._r.pipeline()
        pipe.lpush("sim:log", json.dumps(entry))
        pipe.ltrim("sim:log", 0, LOG_CAP - 1)
        pipe.execute()

    def get_log(self, n: int = 30) -> List[dict]:
        raw = self._r.lrange("sim:log", 0, n - 1)
        return [json.loads(r) for r in raw] if raw else []

    # ── run metadata ──────────────────────────────────────────────────────────

    def set_run_meta(self, topic: str, status: str):
        self._r.hset("sim:run_meta", mapping={
            "run_id":     self.run_id,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topic":      topic,
            "status":     status,
        })

    def update_run_status(self, status: str):
        self._r.hset("sim:run_meta", key="status", value=status)

    def get_run_meta(self) -> dict:
        return self._r.hgetall("sim:run_meta") or {}

    # ── pub/sub broadcast ─────────────────────────────────────────────────────

    def publish(self, event_type: str, payload: dict):
        """Publish to the sim:events channel (no-op in fallback mode)."""
        msg = json.dumps({"type": event_type, "ts": time.time(), "data": payload})
        self._r.publish("sim:events", msg)

    # ── reset ─────────────────────────────────────────────────────────────────

    def reset(self, base_fitness: Dict[str, float]):
        """Clear all simulation keys and reinitialise fitness."""
        for key in ["sim:state", "sim:round_history", "sim:log", "sim:run_meta"]:
            self._r.delete(key)
        self.set_all_fitness(base_fitness)
        self.run_id = str(uuid.uuid4())[:8]
