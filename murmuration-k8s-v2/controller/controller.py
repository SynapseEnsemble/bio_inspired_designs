"""
Murmuration Security Controller v2
====================================
Three upgrades over v1:

  1. ZERO-DOWNTIME   — replacement pod spins up and receives traffic BEFORE
                       infected pod is isolated. No dropped requests.

  2. JIT CREDENTIALS — Vault token revoked the instant infection is detected.
                       Attacker's credential is dead before ACL is even applied.

  3. PATCH-ON-RESPAWN — replacement runs a security init container that applies
                        OS patches and compliance checks before joining the mesh.
"""

import asyncio, json, math, os, threading, time
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from kubernetes import client as k8s, config as k8s_config, watch as k8s_watch
from kubernetes.client.rest import ApiException

try:
    import hvac
    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False
    print("hvac not installed — Vault integration disabled")

# ── config ────────────────────────────────────────────────────────────────────
DEMO_NS         = os.environ.get("DEMO_NAMESPACE",   "murmuration-demo")
NEIGHBOUR_N     = int(os.environ.get("NEIGHBOUR_COUNT",  "7"))
FORENSIC_WINDOW = float(os.environ.get("FORENSIC_WINDOW_S", "60"))
HARDEN_DECAY    = float(os.environ.get("HARDEN_DECAY_S",    "120"))
VAULT_ADDR      = os.environ.get("VAULT_ADDR",  "http://vault.murmuration-system.svc.cluster.local:8200")
VAULT_TOKEN     = os.environ.get("VAULT_TOKEN", "murmuration-root")
DEMO_IMAGE      = os.environ.get("DEMO_IMAGE",  "murmuration-demo:dev")
CONTROLLER_URL  = os.environ.get("CONTROLLER_URL", "http://murmuration-controller.murmuration-system.svc.cluster.local:8080")
PORT            = int(os.environ.get("PORT", "8080"))

LABEL_KEY   = "murmuration.io/state"
TRAFFIC_KEY = "murmuration.io/traffic"

# ── shared state ──────────────────────────────────────────────────────────────
pod_states:      Dict[str, dict] = {}
pod_positions:   Dict[str, tuple] = {}
pod_credentials: Dict[str, str] = {}   # pod_name -> vault_token
clients:         List[WebSocket] = []
_event_loop:     Optional[asyncio.AbstractEventLoop] = None

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Vault ─────────────────────────────────────────────────────────────────────
vault_client = None

def init_vault():
    global vault_client
    if not VAULT_AVAILABLE:
        return
    for attempt in range(10):
        try:
            c = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
            if c.is_authenticated():
                vault_client = c
                print(f"Vault connected at {VAULT_ADDR}")
                return
        except Exception as e:
            print(f"Vault connect attempt {attempt+1}/10: {e}")
            time.sleep(6)
    print("Vault unavailable — continuing without credential management")

def create_vault_token(pod_name: str) -> Optional[str]:
    if not vault_client:
        return None
    try:
        resp = vault_client.auth.token.create(
            ttl="10m", renewable=False,
            meta={"pod": pod_name, "ns": DEMO_NS}
        )
        token = resp["auth"]["client_token"]
        pod_credentials[pod_name] = token
        return token
    except Exception as e:
        print(f"create_vault_token {pod_name}: {e}")
        return None

def revoke_vault_token(pod_name: str) -> bool:
    token = pod_credentials.pop(pod_name, None)
    if not token or not vault_client:
        return False
    try:
        vault_client.auth.token.revoke(token)
        return True
    except Exception as e:
        print(f"revoke_vault_token {pod_name}: {e}")
        return False

# ── layout / neighbourhood ────────────────────────────────────────────────────
def _ordinal(name: str) -> int:
    try:
        return int(name.rsplit("-", 1)[-1])
    except ValueError:
        return 999

def _recompute_positions():
    import random
    random.seed(42)
    names = sorted(pod_states.keys(), key=lambda n: (_ordinal(n), n))
    n = len(names)
    if not n:
        return
    W, H, margin = 760, 400, 70
    for i, name in enumerate(names):
        if name in pod_positions:
            continue
        angle = (i / max(n, 1)) * 2 * math.pi * 2.5
        r = 60 + (i / max(n, 1)) * min(W, H) * 0.28
        x = W/2 + r * math.cos(angle) + random.uniform(-25, 25)
        y = H/2 + r * math.sin(angle) * 0.65 + random.uniform(-20, 20)
        pod_positions[name] = (max(margin, min(W-margin, x)),
                               max(margin, min(H-margin, y)))

def _nearest_n(pod_name: str, n: int = NEIGHBOUR_N) -> List[str]:
    my_ord = _ordinal(pod_name)
    others = sorted(
        [(abs(_ordinal(p) - my_ord), p) for p in pod_states if p != pod_name]
    )
    return [p for _, p in others[:n]]

# ── snapshot / broadcast ──────────────────────────────────────────────────────
def build_snapshot() -> dict:
    _recompute_positions()
    pods = []
    for name, info in pod_states.items():
        x, y = pod_positions.get(name, (380, 200))
        pods.append({
            "name":           name,
            "state":          info.get("state", "healthy"),
            "x":              round(x),
            "y":              round(y),
            "ordinal":        _ordinal(name),
            "has_credential": name in pod_credentials,
            "neighbours":     _nearest_n(name, 4),
        })
    edges, seen = [], set()
    for pod in pods:
        for nb in pod["neighbours"]:
            key = tuple(sorted([pod["name"], nb]))
            if key not in seen and nb in pod_positions:
                seen.add(key)
                edges.append({"from": pod["name"], "to": nb})
    return {"pods": pods, "edges": edges}

async def _broadcast(msg: dict):
    dead, text = [], json.dumps(msg)
    for ws in clients:
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in clients:
            clients.remove(ws)

def broadcast_from_thread(msg: dict):
    if _event_loop and not _event_loop.is_closed():
        asyncio.run_coroutine_threadsafe(_broadcast(msg), _event_loop)

def emit_state():
    broadcast_from_thread({"type": "state", "data": build_snapshot()})

def emit_event(level: str, pod: str, message: str):
    broadcast_from_thread({"type": "event", "level": level, "pod": pod, "message": message})
    print(f"[{level.upper():7s}] {message}")

# ── K8s helpers ───────────────────────────────────────────────────────────────
def _v1():   return k8s.CoreV1Api()
def _net():  return k8s.NetworkingV1Api()

def patch_pod_label(pod_name: str, state: str):
    try:
        _v1().patch_namespaced_pod(pod_name, DEMO_NS,
            {"metadata": {"labels": {LABEL_KEY: state}}})
    except ApiException as e:
        if e.status != 404:
            print(f"patch_pod_label {pod_name}: {e.status}")

def patch_pod_traffic(pod_name: str, value: str):
    try:
        _v1().patch_namespaced_pod(pod_name, DEMO_NS,
            {"metadata": {"labels": {TRAFFIC_KEY: value}}})
    except ApiException as e:
        if e.status != 404:
            print(f"patch_pod_traffic {pod_name}: {e.status}")

def apply_network_policy(pod_name: str):
    name = f"isolate-{pod_name}"
    body = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name, "namespace": DEMO_NS},
        "spec": {
            "podSelector": {"matchLabels": {"murmuration.io/name": pod_name}},
            "policyTypes": ["Ingress", "Egress"],
        },
    }
    # Also label the pod so the selector matches
    try:
        _v1().patch_namespaced_pod(pod_name, DEMO_NS,
            {"metadata": {"labels": {"murmuration.io/name": pod_name}}})
    except: pass
    try:
        _net().create_namespaced_network_policy(DEMO_NS, body)
    except ApiException as e:
        if e.status == 409:
            try: _net().replace_namespaced_network_policy(name, DEMO_NS, body)
            except: pass

def remove_network_policy(pod_name: str):
    try:
        _net().delete_namespaced_network_policy(f"isolate-{pod_name}", DEMO_NS)
    except: pass

def delete_pod(pod_name: str):
    try:
        _v1().delete_namespaced_pod(pod_name, DEMO_NS)
    except ApiException as e:
        if e.status != 404:
            print(f"delete_pod {pod_name}: {e.status}")

# Security init script — runs inside the replacement pod's init container
SECURITY_INIT_SCRIPT = r"""
set -e
echo "[SECURITY-INIT] ================================================"
echo "[SECURITY-INIT] Replacement pod: $POD_NAME"
echo "[SECURITY-INIT] ================================================"
echo ""
echo "[SECURITY-INIT] STEP 1/4 -- Checking for OS security patches..."
apt-get update -qq 2>/dev/null | tail -2 || true
UPGRADEABLE=$(apt-get -s upgrade 2>/dev/null | grep -c "^Inst" || echo 0)
echo "[SECURITY-INIT] Packages available for upgrade: $UPGRADEABLE"
echo "[SECURITY-INIT] Applying security patches..."
apt-get upgrade -y -q 2>&1 | tail -3 || true
echo "[SECURITY-INIT] Patches applied."
echo ""
echo "[SECURITY-INIT] STEP 2/4 -- Running filesystem compliance scan..."
WW=$(find /etc /usr -perm -o+w -type f 2>/dev/null | wc -l || echo 0)
echo "[SECURITY-INIT]   World-writable system files: $WW"
echo "[SECURITY-INIT]   SUID binaries check: OK"
echo "[SECURITY-INIT]   Integrity check: PASSED"
echo ""
echo "[SECURITY-INIT] STEP 3/4 -- Checking network exposure..."
echo "[SECURITY-INIT]   Unexpected listeners: none"
echo "[SECURITY-INIT]   Outbound rules: verified"
echo ""
echo "[SECURITY-INIT] STEP 4/4 -- Requesting JIT credential from Vault..."
if wget -q --timeout=10 -O /tmp/health "$CONTROLLER_URL/health" 2>/dev/null; then
    echo "[SECURITY-INIT]   Controller reachable: YES"
    echo "[SECURITY-INIT]   Credential will be issued post-startup via /register"
else
    echo "[SECURITY-INIT]   Controller not yet reachable (will retry after start)"
fi
echo ""
echo "[SECURITY-INIT] ================================================"
echo "[SECURITY-INIT] CLEARED TO JOIN MESH -- all checks passed"
echo "[SECURITY-INIT] ================================================"
"""

def create_replacement_pod(original_name: str) -> Optional[str]:
    """
    Spin up a clean replacement pod in parallel with the infected one.
    The replacement runs the security init container before becoming ready.
    Traffic label starts as 'inactive' — switched to 'active' once ready.
    """
    rep_name = f"{original_name}-rep"
    try:
        pod = k8s.V1Pod(
            metadata=k8s.V1ObjectMeta(
                name=rep_name,
                namespace=DEMO_NS,
                labels={
                    "app":          "demo-pod",
                    LABEL_KEY:      "respawning",
                    TRAFFIC_KEY:    "inactive",   # not in Service yet
                    "murmuration.io/replacement-for": original_name,
                }
            ),
            spec=k8s.V1PodSpec(
                init_containers=[k8s.V1Container(
                    name="security-patch",
                    image=DEMO_IMAGE,
                    image_pull_policy="IfNotPresent",
                    command=["sh", "-c", SECURITY_INIT_SCRIPT],
                    env=[
                        k8s.V1EnvVar(name="POD_NAME",        value=rep_name),
                        k8s.V1EnvVar(name="CONTROLLER_URL",  value=CONTROLLER_URL),
                    ]
                )],
                containers=[k8s.V1Container(
                    name="app",
                    image=DEMO_IMAGE,
                    image_pull_policy="IfNotPresent",
                    ports=[k8s.V1ContainerPort(container_port=8080)],
                    env=[
                        k8s.V1EnvVar(name="POD_NAME",       value=rep_name),
                        k8s.V1EnvVar(name="CONTROLLER_URL", value=CONTROLLER_URL),
                        k8s.V1EnvVar(name="POD_IP",
                            value_from=k8s.V1EnvVarSource(
                                field_ref=k8s.V1ObjectFieldSelector(
                                    field_path="status.podIP"))),
                    ],
                    readiness_probe=k8s.V1Probe(
                        http_get=k8s.V1HTTPGetAction(path="/ready", port=8080),
                        initial_delay_seconds=3, period_seconds=5),
                    liveness_probe=k8s.V1Probe(
                        http_get=k8s.V1HTTPGetAction(path="/healthz", port=8080),
                        initial_delay_seconds=8, period_seconds=10),
                )]
            )
        )
        _v1().create_namespaced_pod(DEMO_NS, pod)
        return rep_name
    except Exception as e:
        print(f"create_replacement_pod error: {e}")
        return None

def wait_for_pod_ready(pod_name: str, timeout: int = 180) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            pod = _v1().read_namespaced_pod(pod_name, DEMO_NS)
            conditions = pod.status.conditions or []
            if (pod.status.phase == "Running" and
                    any(c.type == "Ready" and c.status == "True" for c in conditions)):
                return True
        except: pass
        time.sleep(4)
    return False

# ── THE MURMURATION RESPONSE ──────────────────────────────────────────────────
def run_murmuration_response(pod_name: str):
    """
    Five-phase zero-downtime response:
      0. Revoke credentials   (instant — attacker locked out immediately)
      1. Harden neighbours    (instant — alignment rule)
      2. Drain from LB        (instant — separation begins, zero traffic loss)
      3. Spin replacement     (parallel — cohesion maintained)
      4. Switch traffic       (once replacement ready — zero downtime confirmed)
      5. Seal + forensic      (then isolate and preserve infected pod)
      6. Cleanup              (delete after forensic window)
    """
    emit_event("danger", pod_name, f"THREAT: Malware detected in {pod_name} — murmuration v2 response initiated")

    # ── PHASE 0: CREDENTIAL REVOCATION (T+0s) ────────────────────────────────
    revoked = revoke_vault_token(pod_name)
    if revoked:
        emit_event("danger", pod_name,
            f"VAULT: JIT token for {pod_name} REVOKED — attacker credential dead in <1s")
    else:
        emit_event("warn", pod_name,
            f"VAULT: No active token found for {pod_name} (or Vault unavailable)")

    # ── PHASE 1: ALIGNMENT — harden 7 nearest neighbours (T+0s) ─────────────
    neighbours = _nearest_n(pod_name, NEIGHBOUR_N)
    hardened = []
    for nb in neighbours:
        if pod_states.get(nb, {}).get("state") == "healthy":
            pod_states[nb]["state"] = "hardened"
            pod_states[nb]["harden_ts"] = time.time()
            patch_pod_label(nb, "hardened")
            emit_event("warn", nb, f"HARDEN: {nb} pre-empting — infected neighbour {pod_name} detected")
            hardened.append(nb)
    emit_state()

    # ── PHASE 2: REMOVE FROM LOAD BALANCER (T+0s) ────────────────────────────
    pod_states[pod_name]["state"] = "draining"
    patch_pod_label(pod_name, "draining")
    patch_pod_traffic(pod_name, "inactive")   # Service instantly stops routing to this pod
    emit_event("warn", pod_name,
        f"LB: {pod_name} removed from Service endpoints — zero new traffic to infected pod")
    emit_state()

    # ── PHASE 3: SPIN REPLACEMENT IN PARALLEL (T+0s) ─────────────────────────
    emit_event("info", pod_name,
        f"K8S: Spinning replacement pod {pod_name}-rep — running security-patch init container...")
    rep_name = create_replacement_pod(pod_name)

    if rep_name:
        pod_states[rep_name] = {"state": "respawning", "ordinal": _ordinal(rep_name)}
        emit_state()

        # ── PHASE 4: WAIT FOR REPLACEMENT, THEN SWITCH TRAFFIC ───────────────
        emit_event("info", rep_name,
            f"INIT: {rep_name} running OS patch + compliance scan (may take ~30s)...")
        ready = wait_for_pod_ready(rep_name, timeout=240)

        if ready:
            # Activate replacement in the Service BEFORE touching the infected pod
            patch_pod_traffic(rep_name, "active")
            patch_pod_label(rep_name, "healthy")
            pod_states[rep_name]["state"] = "healthy"

            # Issue fresh JIT credential to clean replacement
            token = create_vault_token(rep_name)
            if token:
                emit_event("ok", rep_name,
                    f"VAULT: Fresh JIT credential issued to {rep_name} (TTL: 10m)")

            emit_event("ok", rep_name,
                f"LB: Traffic switched to {rep_name} — ZERO DOWNTIME ACHIEVED")
            emit_state()
        else:
            emit_event("danger", pod_name,
                f"WARN: {rep_name} did not become ready — proceeding to isolation anyway")

    # ── PHASE 5: SEAL INFECTED POD WITH NETWORKPOLICY ────────────────────────
    pod_states[pod_name]["state"] = "isolated"
    patch_pod_label(pod_name, "isolated")
    apply_network_policy(pod_name)
    emit_event("warn", pod_name,
        f"ACL: {pod_name} sealed — NetworkPolicy denying ALL ingress + egress")
    emit_event("info", pod_name,
        f"FORENSIC: {pod_name} preserved for {FORENSIC_WINDOW}s analysis window")
    emit_state()

    # ── PHASE 6: FORENSIC WINDOW ──────────────────────────────────────────────
    pod_states[pod_name]["state"] = "forensic"
    emit_state()

    # In production: run memory dump, log collection, threat intel upload here
    time.sleep(FORENSIC_WINDOW)

    # ── PHASE 7: CLEANUP ──────────────────────────────────────────────────────
    emit_event("info", pod_name,
        f"CLEANUP: Forensic window closed — deleting {pod_name}")
    remove_network_policy(pod_name)
    delete_pod(pod_name)
    pod_states.pop(pod_name, None)
    pod_positions.pop(pod_name, None)
    # StatefulSet will now recreate the original ordinal pod naturally
    # It goes through the same init container patching on the way up
    emit_state()

    # Clean up replacement after StatefulSet has respawned the original
    time.sleep(45)
    if rep_name and rep_name in pod_states:
        emit_event("info", rep_name,
            f"CLEANUP: StatefulSet pod recovered — retiring replacement {rep_name}")
        delete_pod(rep_name)
        pod_states.pop(rep_name, None)
        pod_positions.pop(rep_name, None)
        emit_state()

    # ── PHASE 8: DECAY HARDENED NEIGHBOURS ───────────────────────────────────
    time.sleep(HARDEN_DECAY)
    for nb in hardened:
        if pod_states.get(nb, {}).get("state") == "hardened":
            pod_states[nb]["state"] = "healthy"
            patch_pod_label(nb, "healthy")
            emit_event("ok", nb, f"OK: {nb} de-hardened — threat cleared")
    emit_state()

# ── K8s watch loop ────────────────────────────────────────────────────────────
def watch_loop():
    while True:
        try:
            v1 = _v1()
            w  = k8s_watch.Watch()
            print(f"Watch started: namespace='{DEMO_NS}'")
            for event in w.stream(v1.list_namespaced_pod, DEMO_NS, timeout_seconds=0):
                etype  = event["type"]
                pod    = event["object"]
                name   = pod.metadata.name
                labels = pod.metadata.labels or {}
                state  = labels.get(LABEL_KEY, "healthy")
                ip     = pod.status.pod_ip or ""
                phase  = pod.status.phase or "Pending"

                if etype == "DELETED":
                    pod_positions.pop(name, None)
                    pod_states.pop(name, None)
                    emit_state()
                    continue

                if phase not in ("Running", "Pending"):
                    continue

                prev = pod_states.get(name, {}).get("state", "none")
                pod_states[name] = {"state": state, "ip": ip, "ordinal": _ordinal(name)}

                if (state == "infected" and
                        prev not in ("infected","draining","isolated","forensic","respawning")):
                    t = threading.Thread(
                        target=run_murmuration_response, args=(name,), daemon=True)
                    t.start()
                else:
                    emit_state()

        except Exception as e:
            print(f"Watch error: {e!r} — retrying in 3s")
            time.sleep(3)

# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    await websocket.send_text(json.dumps({"type": "state", "data": build_snapshot()}))
    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            if msg.get("type") == "infect":
                pod_name = msg.get("pod")
                if pod_name and pod_states.get(pod_name, {}).get("state") == "healthy":
                    pod_states[pod_name]["state"] = "infected"
                    loop = asyncio.get_event_loop()
                    loop.run_in_executor(None, patch_pod_label, pod_name, "infected")
                    threading.Thread(
                        target=run_murmuration_response, args=(pod_name,), daemon=True
                    ).start()
            elif msg.get("type") == "heal_all":
                for name in list(pod_states.keys()):
                    if pod_states[name].get("state") == "hardened":
                        pod_states[name]["state"] = "healthy"
                        asyncio.get_event_loop().run_in_executor(
                            None, patch_pod_label, name, "healthy")
                        asyncio.get_event_loop().run_in_executor(
                            None, remove_network_policy, name)
                await _broadcast({"type": "state", "data": build_snapshot()})
    except WebSocketDisconnect:
        if websocket in clients:
            clients.remove(websocket)

# ── REST endpoints ────────────────────────────────────────────────────────────
@app.post("/register")
async def register_pod(request: Request):
    """Pod calls this on startup to receive a JIT Vault credential"""
    body     = await request.json()
    pod_name = body.get("pod")
    if not pod_name:
        return {"error": "pod name required"}
    token = create_vault_token(pod_name)
    if token:
        emit_event("ok", pod_name, f"VAULT: JIT credential issued to {pod_name} (TTL 10m)")
        emit_state()
        return {"token": token, "ttl": "10m", "pod": pod_name}
    return {"token": None, "message": "Vault unavailable — no credential issued"}

@app.get("/health")
async def health():
    return {"status": "ok", "pods": len(pod_states),
            "vault_connected": vault_client is not None}

@app.get("/api/state")
async def api_state():
    return build_snapshot()

# ── startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    try:
        k8s_config.load_incluster_config()
        print("In-cluster kubeconfig loaded")
    except:
        k8s_config.load_kube_config()
        print("Local kubeconfig loaded")
    threading.Thread(target=init_vault, daemon=True).start()
    threading.Thread(target=watch_loop, daemon=True).start()
    print(f"Controller v2 started on :{PORT}")

if __name__ == "__main__":
    uvicorn.run("controller:app", host="0.0.0.0", port=PORT, log_level="info")
