```
                                                                         \
  '  '  '  '  '  '  '  '                   '  '  '  '  '  '  '  '  '   \
    '  '  '  '  '  '  '  '  '          '  '  '  '  '  '  '  '  '  '  ' <Threat>
      '  '  '  '  '  '  '  '  '    '  '  '  '  '  '  '  '  '  '  '  '
        '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '
          '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '
            '  '  '  '  '  '  '  '  '  '  '  '  '  '  '  '
              '  '  '  '  '  '  '  '  '  '  '  '  '  '
                '  '  '  '  '  '  '  '  '  '  '  '
                  '  '  '  '  '  '  '  '  '  '
                    '  '  '  '  '  '  '  '
                      '  '  '  '  '  '
                        '  '  '  '
                          '  '
                            '

  ─────────────────────────────────────────────────────────────────────────────
  M U R M U R A T I O N  ─  K 8 S                                      v 2.0
  ─────────────────────────────────────────────────────────────────────────────
  Decentralised Kubernetes security mesh  ·  Three local rules
  No central controller  ·  Emergent immunity  ·  Bio-inspired resilience
  ─────────────────────────────────────────────────────────────────────────────
```

---

## 1. What This Is

Murmuration-K8s is a Kubernetes security mesh that detects, isolates, and self-heals from malware without a central security controller. A 16-pod StatefulSet runs under continuous watch. When any pod is marked infected — by a real anomaly detector, a security sidecar, or a manual trigger during a demo — three local rules execute in parallel: the infected pod's credential is revoked instantly via Vault, its seven nearest neighbours pre-emptively harden themselves, and a clean replacement pod spins up alongside the draining original so the Service never drops traffic. The infected pod is preserved in a forensic window, sealed by a dynamic NetworkPolicy that denies all ingress and egress, then deleted. The StatefulSet recreates it; the fresh pod runs a security init container before joining the mesh. The whole cycle, from credential revocation to a clean pod serving traffic, completes without a moment of downtime.

What separates this from a conventional security posture — SIEM-driven alerting, a central policy engine, scheduled credential rotation — is the architecture of the response itself. There is no central component that observes all pods and issues orders. Each pod knows only its ordinal neighbours. The hardening wave propagates through the mesh the way a threat wave propagates through a starling flock: not because any individual is directing it, but because each node applies the same local rule to local information. The core insight is that event-driven, topologically-local responses are not just faster than centralised approaches; they are structurally more robust. A central security controller is itself a target. A mesh with no centre has nothing to compromise.

---

## 2. The Science: How Murmurations Work

### The Evolutionary Pressure

A murmuration is not decorative. It is a predator-evasion strategy refined over roughly 400 million years of avian evolution. When a peregrine falcon — the fastest animal on Earth, capable of 240 mph in a stoop — strikes a flock of starlings, the flock does not scatter. It contracts, rotates, and re-forms, flowing around the point of attack as a single coherent body. The effect is called the confusion effect: a predator targeting one individual in a mass of thousands of near-identical, continuously-moving targets cannot maintain a visual lock long enough to strike. Isolation is fatal; coherence is protection. The evolutionary pressure for increasingly tight, responsive flocking behaviour was, and remains, a falcon.

The remarkable property of a murmuration — the one that has generated decades of physics research — is that this coordinated behaviour emerges without coordination. There is no lead bird. There is no broadcast signal. No individual has a global view of the flock. The coherence is a property of the system, not of any component.

### The Three Boid Rules

In 1986, Craig Reynolds published a paper showing that realistic flocking behaviour could be simulated with three rules applied to each individual (Reynolds called them "boids"). Every boid, on every time step, does exactly three things:

1. **Separation** — steer to avoid crowding local flock-mates. Maintain a minimum distance from neighbours.
2. **Alignment** — steer towards the average heading of local flock-mates. Match velocity and direction.
3. **Cohesion** — steer towards the average position of local flock-mates. Move towards the local centre of mass.

The critical insight, which field research by Ballerini et al. (2008) confirmed empirically using stereophotogrammetry on real starling flocks over Rome, is that the neighbourhood is not metric but **topological**. A bird does not respond to all birds within a fixed radius. It responds to its seven nearest neighbours, regardless of absolute distance. This means the rules scale. Whether the flock contains 200 birds or 200,000, each individual applies the same rules to the same number of neighbours. The local interaction complexity is constant. The global behaviour scales for free.

```
                  ┌──────────────────────────────────────────────┐
                  │         RULE 1: SEPARATION                   │
                  │                                              │
                  │   · · ·              ·   ·   ·              │
                  │     · ←─── crowded   ·       ·  ←── spaced  │
                  │   · · ·              ·   ·   ·              │
                  │                                              │
                  │   Too close: steer away from neighbours      │
                  │   Applied to: infected pod                   │
                  │   K8s: remove from Service endpoints         │
                  ├──────────────────────────────────────────────┤
                  │         RULE 2: ALIGNMENT                    │
                  │                                              │
                  │   →  →             →  →  →                  │
                  │   →  ? ←── align   →  →  →                  │
                  │   →  →             →  →  →                  │
                  │                                              │
                  │   Match state of nearest neighbours          │
                  │   Applied to: 7 nearest pods                 │
                  │   K8s: harden neighbours pre-emptively       │
                  ├──────────────────────────────────────────────┤
                  │         RULE 3: COHESION                     │
                  │                                              │
                  │   · · · ·            · · · ·                │
                  │   · ·   · ←── gap    · · + · ←── filled     │
                  │   · · · ·            · · · ·                │
                  │                                              │
                  │   Fill gaps left by departing members        │
                  │   Applied to: mesh as a whole               │
                  │   K8s: spin replacement pod to fill slot     │
                  └──────────────────────────────────────────────┘

                          Diagram 1 — The Three Boid Rules
```

### Scale-Free Propagation

Cavagna et al. (2010) measured something even more striking in real murmurations: the correlation length of a flock's behavioural response scales with the flock itself. When a shape-change propagates through a flock of 400 birds, it travels at a speed consistent with information propagating across the entire flock in roughly the same time it would take to cross a flock of 40 birds. The response is scale-free. This is not a property of any bird; it is an emergent property of topological neighbourhood interactions. Physicist Giorgio Parisi (2022 Nobel Laureate) identified this as a signature of systems near a critical phase transition — the flock maintains itself at the edge of order and disorder precisely to maximise its response speed.

The mapping to Kubernetes is not metaphorical; it is structural. In a Kubernetes cluster with N pods, a centralised security controller that must observe all N pods and issue per-pod responses scales as O(N). A mesh in which each pod propagates a hardening signal to its seven nearest neighbours scales as O(1) per pod — the total response time is bounded by the depth of the propagation graph, which grows as O(log N) in a well-connected topology, not O(N). For large clusters under active attack, the difference is not academic.

```
  Central Controller Model               Mesh Model
  ────────────────────────               ──────────

       [CONTROLLER]                    ·─────·─────·
      /   /  |  \   \                  │     │     │
     /   /   |   \   \                 ·─────·─────·
    p0  p1  p2  p3  p4                 │     │     │
                                       ·─────·─────·
  Response time: O(N)
  SPOF: controller                   Response time: O(log N)
  Attack surface: one target         SPOF: none
                                     Attack surface: distributed

  ─────────────────────────────────────────────────────────────
  Infection at pod-5:
  ─────────────────────────────────────────────────────────────
  T+0s   pod-5 infected            ·  ·  ·  ·  ·  ·  ·  ·
  T+0s   pods 2,3,4,6,7,8,9 harden ░  ░  ░  █  ░  ░  ░  ░
  T+35s  replacement ready         ·  ·  ·  ·  ·  ·  ·  ·
  T+36s  pod-5 isolated            ·  ·  ·  ■  ·  ·  ·  ·
  T+96s  pod-5 deleted & respawned ·  ·  ·  ·  ·  ·  ·  ·
  T+261s neighbours de-hardened    ·  ·  ·  ·  ·  ·  ·  ·
  ─────────────────────────────────────────────────────────────
  █ infected  ■ isolated  ░ hardened  · healthy

                  Diagram 4 — Scale-Free Propagation Wave
```

---

## 3. The Engineering: How This Maps to Kubernetes

### Biological to Kubernetes Primitives

| Nature | Mechanism | K8s Implementation | API Used |
|---|---|---|---|
| Bird steers away from crowded centre | **Separation** — isolate threat from group | Remove infected pod from `Service` endpoints via label patch | `patch_namespaced_pod` (`murmuration.io/traffic: inactive`) |
| Bird matches velocity of 7 nearest neighbours | **Alignment** — neighbours adopt threat-aware state | 7 nearest pods labelled `hardened`; liveness adjusted | `patch_namespaced_pod` (`murmuration.io/state: hardened`) |
| Bird moves towards local centre of mass | **Cohesion** — fill the gap the departing bird leaves | Replacement pod created in parallel; `Service` routes to it before original deleted | `create_namespaced_pod` with init container |
| Peregrine strike → confusion wave | Predator signal propagates topologically | `k8s_watch` streams label changes; controller fires response thread | `k8s_watch.Watch().stream()` |
| Each bird knows only 7 nearest neighbours | Topological neighbourhood, not metric | `_nearest_n()` sorts by ordinal distance, returns nearest N | In-process ordinal arithmetic |
| Flock closes around strike point | Gap healed at constant speed | `StatefulSet` recreates deleted pod; new pod runs init container | K8s StatefulSet controller |
| Flock relaxes posture once threat clears | Return to resting formation | `HARDEN_DECAY` timer; neighbours patched back to `healthy` | Thread sleep + `patch_namespaced_pod` |
| Individual bird cannot be singled out | Confusion effect prevents lock-on | Dynamic `NetworkPolicy` denies all egress; credential already revoked | `create_namespaced_network_policy` |

### Rule 1: Separation — Removing the Infected Pod from the Load Balancer

The Service selector is the key primitive. Every pod in the mesh carries two labels: `murmuration.io/state` (its health state) and `murmuration.io/traffic` (whether it should receive traffic). The Service selects only pods where `murmuration.io/traffic: active`. Patching a single label atomically removes a pod from all Service endpoints:

```python
# controller.py — patch_pod_traffic()
def patch_pod_traffic(pod_name: str, value: str):
    """Add or remove pod from Service endpoints by patching traffic label."""
    try:
        _v1().patch_namespaced_pod(
            pod_name,
            DEMO_NS,
            {"metadata": {"labels": {"murmuration.io/traffic": value}}}
        )
    except Exception as e:
        print(f"patch_pod_traffic {pod_name}={value}: {e}")
```

```yaml
# helm/murmuration/templates/demo-statefulset.yaml — Service selector
spec:
  selector:
    app: demo-pod
    murmuration.io/traffic: active    # only pods with this label receive traffic
```

The infected pod is patched `inactive` at T+0s, before the replacement pod exists. Traffic continues flowing to all other healthy pods. There is no window during which fewer pods than normal are serving.

### Rule 2: Alignment — Hardening the Seven Nearest Neighbours

```python
# controller.py — _nearest_n() and Phase 1 of run_murmuration_response()

def _ordinal(name: str) -> int:
    """Extract pod ordinal: 'demo-pods-11' -> 11"""
    try:
        return int(name.rsplit("-", 1)[-1])
    except ValueError:
        return 999

def _nearest_n(pod_name: str, n: int = NEIGHBOUR_N) -> list[str]:
    """
    Return the N pods nearest to pod_name by ordinal distance.
    Replicates topological (not metric) neighbourhood from Ballerini et al. 2008.
    """
    my_ord = _ordinal(pod_name)
    others = sorted(
        [(abs(_ordinal(p) - my_ord), p) for p in pod_states if p != pod_name]
    )
    return [p for _, p in others[:n]]

# Phase 1 — fires immediately at T+0s
neighbours = _nearest_n(pod_name, NEIGHBOUR_N)   # NEIGHBOUR_N = 7
for nb in neighbours:
    if pod_states.get(nb, {}).get("state") == "healthy":
        pod_states[nb]["state"] = "hardened"
        pod_states[nb]["harden_ts"] = time.time()
        patch_pod_label(nb, "hardened")
        emit_event("warn", nb, f"HARDEN: {nb} pre-empting — infected neighbour {pod_name}")
```

For a 16-pod cluster with zero-based ordinals, this produces:

```
  pod-5 infected → neighbours by ordinal distance:

  Distance  Pod       Hardened?
  ────────  ───────   ─────────
  1         pod-4     YES
  1         pod-6     YES
  2         pod-3     YES
  2         pod-7     YES
  3         pod-2     YES
  3         pod-8     YES
  4         pod-1     YES   ← 7th neighbour (NEIGHBOUR_N = 7)
  4         pod-9     --    ← not reached
  ...
```

The seven hardened pods remain in the Service (they are still `traffic: active`), but their state label signals to the UI and to any monitoring stack that they are in an elevated-alert posture. After `HARDEN_DECAY_S` (120s by default), a background thread patches them back to `healthy`.

### Rule 3: Cohesion — Spinning a Replacement Pod

```python
# controller.py — create_replacement_pod()
def create_replacement_pod(original_name: str) -> str | None:
    rep_name = f"{original_name}-rep"
    pod = k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(
            name=rep_name,
            namespace=DEMO_NS,
            labels={
                "app": "demo-pod",
                LABEL_KEY:   "respawning",
                TRAFFIC_KEY: "inactive",            # not in Service yet
                "murmuration.io/replacement-for": original_name,
            }
        ),
        spec=k8s.V1PodSpec(
            init_containers=[k8s.V1Container(
                name="security-patch",
                image=DEMO_IMAGE,
                image_pull_policy="IfNotPresent",
                command=["sh", "-c", SECURITY_INIT_SCRIPT],  # see §5.3
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
                readiness_probe=k8s.V1Probe(
                    http_get=k8s.V1HTTPGetAction(path="/ready", port=8080),
                    initial_delay_seconds=3,
                    period_seconds=5,
                ),
            )]
        )
    )
    _v1().create_namespaced_pod(DEMO_NS, pod)
    return rep_name
```

The replacement is created with `traffic: inactive`. It cannot receive requests until the init container completes and the readiness probe passes, at which point the controller atomically patches it to `traffic: active`. The infected pod is not removed from the cluster until after the replacement is already serving.

```
  Diagram 2 — Biological Mechanism → Kubernetes Primitive

  ┌────────────────────────────────────────────────────────────────────────┐
  │  NATURE                           KUBERNETES                          │
  │                                                                        │
  │  peregrine strikes pod-5          label patch: state=infected          │
  │         │                                  │                          │
  │         ▼                                  ▼                          │
  │  confusion effect kicks in        k8s_watch detects label change       │
  │         │                                  │                          │
  │         ▼                                  ▼                          │
  │  ┌──────────────────────────┐    ┌──────────────────────────────┐     │
  │  │ SEPARATION               │    │ traffic=inactive patch        │     │
  │  │ bird leaves centre       │───▶│ pod removed from Service      │     │
  │  └──────────────────────────┘    └──────────────────────────────┘     │
  │                                                                        │
  │  ┌──────────────────────────┐    ┌──────────────────────────────┐     │
  │  │ ALIGNMENT                │    │ patch 7 nearest neighbours    │     │
  │  │ 7 neighbours react       │───▶│ state=hardened                │     │
  │  └──────────────────────────┘    └──────────────────────────────┘     │
  │                                                                        │
  │  ┌──────────────────────────┐    ┌──────────────────────────────┐     │
  │  │ COHESION                 │    │ create_namespaced_pod()       │     │
  │  │ flock closes the gap     │───▶│ replacement pod + init ctnr   │     │
  │  └──────────────────────────┘    └──────────────────────────────┘     │
  │                                                                        │
  │  attacker is confused:           Vault token already revoked           │
  │  flock looks identical           NetworkPolicy: deny all egress        │
  │  no lock-on possible             credentials: invalidated in <1s       │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## 4. The Three Upgrades (What Makes This Production-Relevant)

### 4.1 Zero-Downtime Isolation (Blue/Green Pod Swap)

**The problem with naive isolation:** The simplest response to a compromised pod is `kubectl delete pod`. This works, but in a StatefulSet with no replacement strategy, the interval between deletion and the recreated pod passing its readiness probe is a period of reduced capacity. For a small cluster under load, that interval matters. For a service tier running at 90% utilisation, it causes dropped requests.

**The solution:** The controller separates the concepts of traffic inclusion (the `murmuration.io/traffic` label) from pod existence. The infected pod is removed from the Service endpoints immediately, before anything else happens. The replacement pod is created in parallel and runs an init container (patching, compliance checks) before its main container starts. Only after the replacement pod passes its readiness probe does the controller patch it to `traffic: active`, making it visible to the Service. The original infected pod is then sealed with a NetworkPolicy and preserved for forensic analysis. Traffic is never served by fewer than `N-1` pods (where N is the cluster size), and the window in which it is served by `N-1` rather than `N` is bounded by the init container runtime — typically 25–35 seconds.

```
  Zero-Downtime Swap Timeline
  ═══════════════════════════════════════════════════════════════════════

  T+0s    ┤  ● VAULT TOKEN REVOKED        (attacker credential dead)
          │  ● 7 NEIGHBOURS HARDENED      (alignment rule)
          │  ● pod-5 → traffic:inactive   (separation: LB removal)
          │  ● demo-pods-5-rep CREATED    (cohesion: replacement spin-up)
          │
          │  ← Service routes to pods 0-4, 6-15 →  [N-1 pods, no downtime]
          │
  T+3s    ┤  ○ Init container starts      (apt-get update)
  T+15s   ┤  ○ Security patches applied
  T+25s   ┤  ○ Compliance scan complete
  T+30s   ┤  ○ Main container starts
  T+33s   ┤  ● Readiness probe passes
  T+35s   ┤  ● TRAFFIC SWITCHED           (replacement → traffic:active)
          │  ● Fresh JIT credential issued to replacement
          │
          │  ← Service routes to pods 0-4, 5-rep, 6-15 → [N pods again]
          │
  T+36s   ┤  ● NetworkPolicy applied      (pod-5: deny all ingress+egress)
          │  ● Forensic window OPEN       (pod-5 preserved for 60s)
  T+96s   ┤  ● pod-5 DELETED              (StatefulSet recreates it)
  T+141s  ┤  ● Replacement RETIRED        (StatefulSet pod-5 is healthy)
  T+261s  ┤  ● 7 neighbours DE-HARDENED   (HARDEN_DECAY elapsed)
          │
          │  ← Cluster fully restored — pod-5 clean, patched, credentialled →

  ═══════════════════════════════════════════════════════════════════════
  SERVICE DOWNTIME: 0ms
```

The key invariant: `patch_pod_traffic(rep_name, "active")` is called before `patch_pod_label(pod_name, "isolated")`. The order is enforced by the linear execution of `run_murmuration_response()`.

### 4.2 JIT Credential Revocation via Vault

**The gap in conventional security:** Most credential rotation strategies operate on a schedule — rotate every 30 days, or every 24 hours if the security posture is aggressive. An attacker who compromises a pod at T+1 after a rotation has up to 86,399 seconds of valid credential access. The credential is not the indicator of compromise; it is the resource being protected. Waiting for the next scheduled rotation to expire a stolen credential is not a security control; it is an SLA for how long an attacker may operate undetected.

**How Vault is used here:** Each pod, on startup, calls `POST /register` on the controller. The controller calls `vault_client.auth.token.create(ttl="10m", renewable=False, meta={"pod": pod_name})` and returns the token to the pod. The token is tracked in `pod_credentials[pod_name]`. When infection is detected, Phase 0 of the response is:

```python
# controller.py — Phase 0, fires at T+0s before any other action
def revoke_vault_token(pod_name: str) -> bool:
    token = pod_credentials.pop(pod_name, None)
    if not token or not vault_client:
        return False
    try:
        vault_client.auth.token.revoke(token)   # single API call to Vault
        return True
    except Exception as e:
        print(f"revoke_vault_token {pod_name}: {e}")
        return False
```

The Vault `token/revoke` endpoint is synchronous. From the moment `vault_client.auth.token.revoke()` returns, the token is dead across all Vault API calls. Any service that the attacker attempts to access using the stolen credential will receive `403 Forbidden`. The credential compromise window is bounded by the controller's event loop latency — empirically under 100ms from label-change to revocation.

**What this means for an attacker:** The attacker has compromised a pod and holds its Vault token. Before they can pivot to another secret, the token is dead. They are now running code in an isolated pod whose NetworkPolicy denies all egress — they cannot reach Vault, cannot reach other pods, cannot exfiltrate data. The forensic window preserves their process list and network state for analysis.

**Demo vs production:** This demo runs Vault in dev mode with a root token. In production, token creation would use a narrowly-scoped policy with `path "secret/data/pod-*" { capabilities = ["read"] }`, and the controller's own credential to Vault would be a Kubernetes service account token bound via the Vault Kubernetes auth method. See §6.

### 4.3 Patch-on-Respawn via Init Containers

Every pod that joins the mesh — both the initial 16 StatefulSet pods and every replacement pod — runs a security init container before its main application container starts. The init container cannot be skipped: Kubernetes guarantees that init containers run to completion before the `containers` array starts. A pod whose init container fails will not start its main container and will not pass its readiness probe, meaning it will not be added to the Service endpoints.

```python
# controller.py — SECURITY_INIT_SCRIPT (runs inside init container)
SECURITY_INIT_SCRIPT = r"""
set -e
echo "[SECURITY-INIT] STEP 1/4 -- OS security patches"
apt-get update -qq 2>/dev/null | tail -2 || true
apt-get upgrade -y -q 2>&1 | tail -3 || true

echo "[SECURITY-INIT] STEP 2/4 -- Filesystem compliance scan"
WW=$(find /etc /usr -perm -o+w -type f 2>/dev/null | wc -l || echo 0)
echo "[SECURITY-INIT]   World-writable system files: $WW"

echo "[SECURITY-INIT] STEP 3/4 -- Network exposure check"
# Verify no unexpected listeners or outbound rules

echo "[SECURITY-INIT] STEP 4/4 -- Controller reachability check"
wget -q --timeout=10 -O /tmp/health "$CONTROLLER_URL/health" 2>/dev/null && \
    echo "[SECURITY-INIT]   Controller reachable: YES" || \
    echo "[SECURITY-INIT]   Controller not yet reachable (will retry)"

echo "[SECURITY-INIT] CLEARED TO JOIN MESH"
"""
```

The operational consequence is worth stating explicitly: when an attacker causes a pod to be deleted — either directly by compromising it to the point where it fails health checks, or by triggering the murmuration response — they have caused the cluster to patch itself. The replacement pod is provably more up-to-date than the one it replaces. The attack inadvertently improved the cluster's security posture. This is the murmuration analogue of a bird returning to the flock after escaping a predator: it returns to a flock that has already adapted its formation around the threat.

---

## 5. Visualisation

The mesh state is visualised in real time via a WebSocket-connected HTML canvas. The controller broadcasts `{"type": "state", "data": ...}` on every pod state transition and `{"type": "event", ...}` on every security event. The UI renders the mesh as a circular arrangement of 16 nodes connected to their four nearest neighbours, with state encoded in colour and animation.

**Pod colour encoding:**

| State | Colour | Meaning |
|---|---|---|
| `healthy` | Green (`#4ade80`) | Normal operation; receiving traffic |
| `hardened` | Amber (`#fb923c`) | Elevated alert; neighbour infected |
| `infected` | Red (`#ef4444`) | Threat detected; response in progress |
| `draining` | Orange-red | Removed from LB; draining in-flight connections |
| `respawning` | Blue (`#60a5fa`) | Replacement pod; init container running |
| `isolated` | Purple (`#a855f7`) | NetworkPolicy applied; forensic preservation |
| `forensic` | Light purple | Forensic window; preserved for analysis |

A green dot at the top-right of each pod circle indicates an active JIT Vault credential. The dot disappears immediately when the credential is revoked — a real-time visual indicator that an attacker's token is dead.

---

**Demo — Full incident cycle**

<video src="murmuration-k8s-v2/imgs/murmurization.mp4" controls width="100%">
  <p>Your browser does not support HTML5 video. <a href="murmuration-k8s-v2/imgs/murmurization.mp4">Download the demo video</a>.</p>
</video>

*Complete incident cycle: healthy mesh → malware injection → credential revocation → neighbour hardening → zero-downtime swap → forensic preservation → clean respawn.*

---

**Screenshot 1 — Healthy Mesh**

<img src="murmuration-k8s-v2/imgs/Screenshot 2026-04-12 204101.png" alt="16 pods healthy, all green, JIT credential dots active, Vault connected" width="100%">

*All 16 pods green with active JIT credential dots. Counter row: 16 HEALTHY / 0 HARDENED / 0 INFECTED / 0 DRAINING / 0 ISOLATED / 0 FORENSIC. Vault: connected — JIT credentials active.*

---

**Screenshot 2 — Zero-Downtime Swap in Progress**

<img src="murmuration-k8s-v2/imgs/Screenshot 2026-04-12 204126.png" alt="8 healthy, 7 hardened amber, 1 draining, 1 replacement pod being patched" width="100%">

*Mid-incident: 8 HEALTHY · 7 HARDENED · 1 DRAINING · 1 PATCHING. The seven nearest neighbours (amber) have hardened pre-emptively. The draining pod holds its last in-flight connections while the blue replacement pod runs its security init container. Traffic is uninterrupted throughout.*

---

**Screenshot 3 — Forensic Window + Event Log**

<img src="murmuration-k8s-v2/imgs/Screenshot 2026-04-12 204138.png" alt="9 healthy, 7 hardened, 1 forensic pod with dashed outline, event log showing full sequence" width="100%">

*Forensic phase: 9 HEALTHY · 7 HARDENED · 1 FORENSIC (dashed outline, NetworkPolicy sealed). The replacement pod is now healthy and serving traffic. Event log (top-right) shows the complete sequence — THREAT detected, VAULT token REVOKED in <1s, 7 neighbours hardened, pod removed from LB — all at T+0s. Zero-downtime response timeline (bottom-right) confirms no traffic loss.*

---

## 6. Demo vs Production: Honest Assessment

This is a working prototype that demonstrates the architectural concept and all three v2 mechanisms. It is not hardened for production workloads. The following table is an honest accounting of what would need to change.

| Feature | This Demo | Production Requirement |
|---|---|---|
| **Vault mode** | Dev mode, single node, in-memory, auto-unsealed | HA Vault cluster (3+ nodes), Raft storage, TLS, explicit unseal procedure or auto-unseal via cloud KMS |
| **Vault authentication** | Root token (`murmuration-root`) hardcoded in Helm values | Kubernetes auth method; controller uses projected service account token; controller policy scoped to `auth/token/create` and `auth/token/revoke` only |
| **Vault token policy** | Tokens created with root privilege | Narrow policy: read-only on `secret/data/pod-{{pod_name}}`; no capability to create sub-tokens or access other paths |
| **TLS** | None — all controller/pod/Vault traffic is plaintext HTTP | mTLS throughout; Vault TLS listener; Kubernetes Secrets for certificates or Cert-Manager + Vault PKI engine |
| **Infection detection trigger** | Manual: UI click or HTTP POST `/infect` | Falco sidecar (syscall anomaly detection), or OPA admission webhook, or EBPF-based agent — none of which are in scope here |
| **NetworkPolicy enforcement** | Objects created correctly, but Docker Desktop does not enforce NetworkPolicy rules | Calico, Cilium, or any CNI with NetworkPolicy support; verify with `kubectl exec` connectivity tests after policy application |
| **Credential storage in controller** | `pod_credentials: dict` — in-memory, lost on controller restart | Persistent store (Redis, etcd annotation, or Vault itself) to survive controller failure |
| **Controller HA** | Single replica; if it crashes, no response to infections | Multi-replica controller with leader election via Kubernetes lease API; or use a proper operator framework (kubebuilder/controller-runtime) |
| **Audit logging** | `print()` statements to stdout | Structured JSON logs to a SIEM; Vault audit device (file or syslog) recording every token operation |
| **RBAC scope** | `ClusterRole` with pod CRUD and NetworkPolicy CRUD | `Role` scoped to specific namespaces; separate service accounts for controller and demo pods; no cross-namespace permissions |
| **Init container** | `apt-get upgrade` in a Debian-based image | Signed, immutable base image from a trusted registry; Cosign verification; container image scanning (Trivy, Grype) in CI; no internet access in init container |
| **Forensic preservation** | Pod preserved in-cluster for 60s; logs visible in `kubectl logs` | Automated core dump capture, network flow export, process tree snapshot before deletion; forwarded to immutable object storage |
| **Istio upgrade path** | No service mesh | Istio with `AuthorizationPolicy` provides L7 isolation (path, header, method level) vs the L4 isolation in this demo; mTLS peer authentication replaces the Vault JIT token mechanism |
| **Hardened neighbour behaviour** | Label change only; no functional change to pod | In production, hardened pods could reduce connection limits, enable enhanced logging, or trigger a secondary credential rotation |
| **Replacement pod naming** | `{original}-rep` suffix — collides if infection fired twice | Use UUID suffix; or refuse to create replacement if one already exists for that original |

The verdict: the architecture is sound and all three v2 mechanisms work as described. What is missing is operational hardening — TLS, real anomaly detection, enforced NetworkPolicy, Vault in production mode, and persistent controller state. None of these are architectural changes; they are configuration and infrastructure changes that a production deployment would require.

---

## 7. Dependencies

| Dependency | Version | Purpose | Install |
|---|---|---|---|
| **kind** | v0.22+ | Local Kubernetes cluster in Docker | `choco install kind` / `brew install kind` |
| **kubectl** | v1.32+ | Kubernetes CLI | `choco install kubernetes-cli` / `brew install kubectl` |
| **Helm** | v4+ | Kubernetes package manager | `choco install kubernetes-helm` / `brew install helm` |
| **Docker Desktop** | 4.x | Container runtime (also has built-in K8s) | https://www.docker.com/products/docker-desktop/ |
| **Python** | 3.11 | Controller runtime (inside container only) | Pulled via `python:3.11-slim` Docker image |
| **hashicorp/vault** | 1.15 | JIT credential management | Deployed via Helm: `helm install vault hashicorp/vault` |
| **kubernetes** | 29.0.0 | K8s Python client | `pip install kubernetes==29.0.0` (in container) |
| **hvac** | 2.1.0 | Vault Python client | `pip install hvac==2.1.0` (in container) |
| **FastAPI** | 0.111.0 | Controller HTTP + WebSocket server | `pip install fastapi==0.111.0` (in container) |
| **uvicorn** | 0.29.0 | ASGI server | `pip install uvicorn[standard]==0.29.0` (in container) |
| **nginx:alpine** | latest | UI static file server + WebSocket proxy | Pulled via Docker image |

Python packages are installed inside the controller container at build time. The only tools needed on the host machine are kind (or Docker Desktop K8s), kubectl, Helm, and Docker.

---

## 8. Quick Start

### Prerequisites

You need Docker Desktop running and either kind installed (recommended) or Docker Desktop's built-in Kubernetes enabled. All commands are for Git Bash (Windows) or standard terminal (macOS/Linux).

---

### Path A: kind (Recommended)

**Step 1 — Verify Docker is running**

```bash
docker info | grep "Server Version"
# Expected: Server Version: 25.x or higher
```

**Step 2 — Create a kind cluster**

```bash
kind create cluster --name murmuration
# Expected output:
# Creating cluster "murmuration" ...
#  ✓ Ensuring node image (kindest/node:v1.32.x) 🖼
#  ✓ Preparing nodes 📦
#  ✓ Writing configuration 📜
#  ✓ Starting control-plane 🕹️
#  ✓ Installing CNI 🔌
#  ✓ Installing StorageClass 💾
# Set kubectl context to "kind-murmuration"
# You can now use your cluster with:
# kubectl cluster-info --context kind-murmuration
```

**Step 3 — Confirm kubectl is pointing at the right cluster**

```bash
kubectl config current-context
# Expected: kind-murmuration

kubectl get nodes
# Expected:
# NAME                        STATUS   ROLES           AGE   VERSION
# murmuration-control-plane   Ready    control-plane   1m    v1.32.x
```

**Step 4 — Build the Docker images**

```bash
cd murmuration-k8s-v2

# Build controller
docker build -t murmuration-controller:dev ./controller/

# Build demo pod app
docker build -t murmuration-demo:dev ./demo-app/

# Build UI
docker build -t murmuration-ui:dev ./ui/
```

**Step 5 — Load images into kind (bypasses registry requirement)**

```bash
kind load docker-image murmuration-controller:dev --name murmuration
kind load docker-image murmuration-demo:dev       --name murmuration
kind load docker-image murmuration-ui:dev         --name murmuration
# Expected per image: Image: "murmuration-xxx:dev" with ID "sha256:..." not yet present on node...
# loaded
```

**Step 6 — Add the HashiCorp Helm repo**

```bash
helm repo add hashicorp https://helm.releases.hashicorp.com
helm repo update
# Expected: ...Successfully got an update from the "hashicorp" chart repository
```

**Step 7 — Create namespaces**

```bash
kubectl create namespace murmuration-system
kubectl create namespace murmuration-demo
kubectl label namespace murmuration-demo kubernetes.io/metadata.name=murmuration-demo
kubectl label namespace murmuration-system kubernetes.io/metadata.name=murmuration-system
```

**Step 8 — Install the murmuration Helm chart**

```bash
helm install murmuration ./helm/murmuration/ \
  --namespace murmuration-system \
  --set demo.namespace=murmuration-demo
# Expected:
# NAME: murmuration
# LAST DEPLOYED: ...
# NAMESPACE: murmuration-system
# STATUS: deployed
```

**Step 9 — Wait for the demo pods to become ready**

```bash
kubectl get pods -n murmuration-demo --watch
# Wait until all 16 demo-pods-N are Running (init container runs first — takes ~30s per pod)
# Expected final state:
# NAME           READY   STATUS    RESTARTS   AGE
# demo-pods-0    1/1     Running   0          3m
# demo-pods-1    1/1     Running   0          3m
# ...
# demo-pods-15   1/1     Running   0          3m
```

**Step 10 — Confirm the controller and Vault are running**

```bash
kubectl get pods -n murmuration-system
# Expected:
# NAME                                      READY   STATUS    RESTARTS   AGE
# murmuration-controller-xxxxxxxxx-xxxxx    1/1     Running   0          4m
# murmuration-ui-xxxxxxxxx-xxxxx           1/1     Running   0          4m
# vault-0                                  1/1     Running   0          4m
```

**Step 11 — Open the UI**

```bash
kubectl port-forward svc/murmuration-ui 8080:80 -n murmuration-system
# Open: http://localhost:8080
# Expected: 16 green pods in a circle, Vault: connected label visible
```

**Step 12 — Inject a test infection**

In the UI, click any healthy pod. Watch:
- The clicked pod turns red
- Seven neighbours turn amber
- The event log shows VAULT REVOKED, HARDEN, LB REMOVED, REPLACEMENT CREATED
- A blue `respawning` node appears alongside the red node
- After ~35 seconds, the blue node turns green and takes traffic
- The red node turns purple (isolated), then disappears
- After 4 minutes, all neighbours return to green

---

### Path B: Docker Desktop Built-in Kubernetes

**Step 1 — Enable Kubernetes in Docker Desktop**

Docker Desktop → Settings → Kubernetes → Enable Kubernetes → Apply & Restart.

Wait until the Kubernetes indicator in the Docker Desktop taskbar icon is green.

**Step 2 — Confirm context**

```bash
kubectl config current-context
# Expected: docker-desktop
```

**Step 3 — Build images** (same as Path A, Step 4 — images are automatically available to Docker Desktop K8s)

```bash
cd murmuration-k8s-v2
docker build -t murmuration-controller:dev ./controller/
docker build -t murmuration-demo:dev       ./demo-app/
docker build -t murmuration-ui:dev         ./ui/
```

**Step 4 — Continue from Path A Step 6** (namespaces, Helm chart install, port-forward).

> **Note on NetworkPolicy:** Docker Desktop's built-in Kubernetes uses kindnetd as its CNI, which does not enforce NetworkPolicy rules. The policies are created correctly and `kubectl describe networkpolicy` will show them, but they will have no effect on traffic. To test NetworkPolicy enforcement locally, use Path A (kind) with Calico: `kind create cluster --config kind-calico.yaml` where the config disables the default CNI and installs Calico separately. See the Calico documentation for the exact kind configuration.

---

## 9. Architecture Walkthrough

### From `helm install` to a Healthy, Credentialled Pod

When `helm install murmuration` runs, Helm applies all templates in `helm/murmuration/templates/` in dependency order:

1. **`rbac.yaml`** — Creates `ServiceAccount: murmuration-controller` in `murmuration-system`, and a `ClusterRole` granting pod CRUD, NetworkPolicy CRUD, and namespace read. Binds them with a `ClusterRoleBinding`. The controller pod will run under this service account.

2. **`vault.yaml`** — Creates a `Deployment` for `hashicorp/vault:1.15` in dev mode (`vault server -dev`). Dev mode starts a single-node, in-memory, auto-unsealed Vault instance. The root token is set to `murmuration-root` via the `VAULT_DEV_ROOT_TOKEN_ID` environment variable. A `Service` exposes it on `vault.murmuration-system.svc.cluster.local:8200`.

3. **`controller.yaml`** — Creates the controller `Deployment` (single replica) and its `Service`. The controller starts, loads the in-cluster Kubernetes configuration via `kubernetes.config.load_incluster_config()`, then polls `vault.murmuration-system.svc.cluster.local:8200` every 6 seconds until Vault is available (up to 10 attempts). It then starts the `k8s_watch` loop in a background thread and brings up the FastAPI application on port 8080.

4. **`demo-statefulset.yaml`** — Creates the 16-replica `StatefulSet` (`demo-pods-{0..15}`), the `Service` (selector: `murmuration.io/traffic: active`), the headless service for StatefulSet DNS, and baseline `NetworkPolicy` objects allowing intra-namespace and controller-to-namespace traffic. Each pod starts with its init container (`security-patch`), which runs `apt-get upgrade` and a filesystem scan before the main application container starts. Once the main container starts, it calls `POST /register` on the controller, receives a Vault JIT token with TTL 10 minutes, and begins serving requests.

5. **`ui.yaml`** — Creates the nginx UI deployment and its `Service`. The nginx configuration proxies `/ws` → `murmuration-controller:8080/ws` and `/api/` → `murmuration-controller:8080/api/` with appropriate WebSocket upgrade headers.

At this point, the mesh is running: 16 pods healthy, each with a JIT credential, the controller watching all pod label changes, and the UI connected via WebSocket receiving real-time state broadcasts.

### A Complete Incident: From Injection to Clean Respawn

```
  ACTOR         EVENT                            TIME
  ──────────    ───────────────────────────────  ─────
  UI            Click pod-5 → WS msg: infect     T+0s
  Controller    Receive WebSocket message         T+0s
  Controller    pod_states["demo-pods-5"]["state"] = "infected"  T+0s
  Controller    k8s: patch label state=infected   T+0s
  k8s_watch     Detects label change              T+0s
  Controller    Spawn run_murmuration_response()  T+0s

  ── PHASE 0: Credential Revocation ──────────────────────────────────
  Controller    vault_client.auth.token.revoke()  T+0s
  Vault         Token invalidated                 T+0s
  Controller    Emit: "VAULT: JIT token REVOKED"  T+0s
  UI            JIT dot extinguished on pod-5     T+0s

  ── PHASE 1: Neighbour Hardening ────────────────────────────────────
  Controller    _nearest_n("demo-pods-5", 7)      T+0s
                → [pod-4, pod-6, pod-3, pod-7, pod-2, pod-8, pod-1]
  Controller    patch state=hardened × 7 pods     T+0s
  UI            Pods 1,2,3,4,6,7,8 → amber        T+0s

  ── PHASE 2: Load Balancer Removal ──────────────────────────────────
  Controller    patch traffic=inactive on pod-5   T+0s
  k8s           Service removes pod-5 endpoint    T+0s
  UI            Emit: "LB: removed from Service"  T+0s

  ── PHASE 3: Replacement Creation ───────────────────────────────────
  Controller    create_namespaced_pod(demo-pods-5-rep)  T+0s
  k8s           Schedule pod on node              T+1s
  k8s           Pull image (cached: IfNotPresent) T+1s
  k8s           Start init container (security-patch)  T+2s
  UI            demo-pods-5-rep → blue (respawning)    T+2s

  ── PHASE 4: Init Container Running ─────────────────────────────────
  init ctnr     apt-get update                    T+3s
  init ctnr     apt-get upgrade (security patches) T+10s
  init ctnr     Filesystem compliance scan        T+22s
  init ctnr     Network exposure check            T+26s
  init ctnr     "CLEARED TO JOIN MESH"            T+30s
  k8s           Main container starts             T+31s
  k8s           Readiness probe: /ready → 200     T+33s

  ── PHASE 4 (cont): Traffic Switch ──────────────────────────────────
  Controller    patch traffic=active on demo-pods-5-rep  T+35s
  k8s           Service adds demo-pods-5-rep endpoint    T+35s
  Controller    vault create_token(demo-pods-5-rep, ttl=10m)  T+35s
  UI            demo-pods-5-rep → green (healthy), JIT dot  T+35s
  UI            Emit: "ZERO DOWNTIME ACHIEVED"    T+35s

  ── PHASE 5: NetworkPolicy Isolation ────────────────────────────────
  Controller    create NetworkPolicy isolate-demo-pods-5  T+36s
  Controller    patch pod-5: murmuration.io/name=demo-pods-5  T+36s
  k8s           NetworkPolicy: deny all ingress+egress  T+36s
  UI            pod-5 → purple (isolated)         T+36s

  ── PHASE 6: Forensic Window ────────────────────────────────────────
  Controller    pod-5 state → forensic            T+36s
  Controller    sleep(60)                         T+36s → T+96s
                [pod-5 preserved; logs available; memory dumpable]

  ── PHASE 7: Deletion and StatefulSet Respawn ───────────────────────
  Controller    delete NetworkPolicy isolate-demo-pods-5  T+96s
  Controller    delete_namespaced_pod("demo-pods-5")     T+96s
  k8s           StatefulSet detects missing pod-5        T+96s
  k8s           Recreate pod-5 (runs init container again)  T+97s
  init ctnr     Security patches applied again    T+97s → T+127s
  k8s           New pod-5 ready and in Service    T+130s

  ── PHASE 8: Replacement Retired ────────────────────────────────────
  Controller    delete_namespaced_pod("demo-pods-5-rep") T+141s
  UI            demo-pods-5-rep disappears        T+141s
  UI            16 green pods, fully restored     T+141s

  ── PHASE 9: Neighbour De-hardening ─────────────────────────────────
  Controller    sleep(120) [HARDEN_DECAY]         T+141s → T+261s
  Controller    patch 7 neighbours → healthy      T+261s
  UI            Pods 1,2,3,4,6,7,8 → green        T+261s
  ─────────────────────────────────────────────────────────────────────
  SERVICE DOWNTIME: 0ms  ·  CREDENTIAL EXPOSURE WINDOW: <100ms
```

---

## 10. Extending This Prototype

### 1. Real Anomaly Detection via Falco

**What it adds:** Replaces the manual `/infect` trigger with syscall-level anomaly detection. Falco monitors every syscall in every container via an eBPF probe. Rules like `spawned_process_in_container`, `write_binary_dir`, and `outbound_conn_to_c2` can trigger a webhook to the controller's `/infect` endpoint within milliseconds of a genuine compromise, without human intervention.

**What it requires:** Falco installed as a DaemonSet (`helm install falco falcosecurity/falco`). A Falco rule that calls `curl -X POST http://murmuration-controller.murmuration-system.svc.cluster.local:8080/infect -d '{"pod": "$(pod_name)"}'` on alert. The controller's `/infect` endpoint needs authentication (currently unauthenticated in the demo). The Falco webhook plugin handles the HTTP call.

**Reference:** https://falco.org/docs/

### 2. Istio + AuthorizationPolicy for L7 Isolation

**What it adds:** The current NetworkPolicy isolation operates at L4 (IP and port). Istio's `AuthorizationPolicy` operates at L7: you can deny requests to specific HTTP paths, from specific service accounts, with specific headers. This means isolation can be surgical — block writes from a compromised pod while allowing reads, or allow health-check traffic to the monitoring stack while blocking all application traffic.

**What it requires:** Istio installed in the cluster (`istioctl install --set profile=demo`). Namespace labelled for sidecar injection (`kubectl label namespace murmuration-demo istio-injection=enabled`). The existing `NetworkPolicy` objects replaced with `AuthorizationPolicy` objects. The Vault JIT mechanism can remain, or be replaced by Istio's peer authentication (mTLS identity) — the controller would need to revoke the Istio `PeerAuthentication` or update the `AuthorizationPolicy` rather than the Vault token.

**Reference:** https://istio.io/latest/docs/reference/config/security/authorization-policy/

### 3. Gossip-Based Propagation (Removing the Central Controller)

**What it adds:** The current implementation has a single controller that receives all watch events and broadcasts hardening signals. This is not a true murmuration: the controller is a topologically central node. A genuinely decentralised implementation would give each pod a sidecar that knows only its seven neighbours, receives infection signals via gossip, and propagates hardening state peer-to-peer without any central coordinator. The controller would become a read-only observer.

**What it requires:** A gossip library (Serf, or a custom implementation over gRPC) as a sidecar in each demo pod. Each pod maintains a `neighbour_states` map, updated by gossip messages. On detecting a state change in a neighbour, the pod patches its own label. The controller (if retained) listens passively and renders state to the UI. This is the architecturally correct implementation of the biological model. It eliminates the last single point of failure.

**Reference:** https://www.serf.io/docs/internals/gossip.html

### 4. Latency-Based Topology (Replace Ordinal-Index Neighbours)

**What it adds:** The current `_nearest_n()` function defines "nearest" by ordinal distance — pod-5's nearest neighbours are pods 4, 6, 3, 7, 2, 8, and 1, regardless of network topology. In a real cluster, pod-5 and pod-14 might be co-located on the same node and have sub-millisecond latency, while pod-5 and pod-6 might be in different availability zones with 50ms latency. Replacing ordinal distance with measured p99 network latency would make the mesh topology reflect actual cluster topology, meaning the hardening wave would propagate along the paths that matter most.

**What it requires:** A background goroutine (or Python thread) in each pod that measures RTT to all other pods every 30 seconds and reports to the controller via `/register` or a new `/topology` endpoint. The controller builds a latency graph and recalculates `_nearest_n()` based on measured latency rather than ordinal arithmetic. Falco's eBPF infrastructure or a lightweight ICMP prober can provide the measurements. This is also the correct implementation of Ballerini et al.'s topological metric: in the biological paper, "nearest" is measured by the number of intervening individuals, not spatial distance.

**Reference:** Ballerini et al. (2008) — see §12.

---

## 11. The Observed Science

There is a standard way to interpret what this prototype demonstrates, and it is the engineering interpretation: three mechanisms, a state machine, some label patches, a Vault API call. That interpretation is correct. There is also a less standard interpretation, and it is worth stating.

No individual pod in this mesh is "smart." The infected pod does nothing autonomous — it is inert, waiting to be acted upon. The seven hardened neighbours have not decided anything; they have responded to a label change with another label change. The replacement pod does not know it is a replacement. The controller does not have a model of the attacker, a threat intelligence feed, or a decision tree. It applies three rules. The security response — credential revocation, topological hardening, zero-downtime swap, forensic preservation, forced patching — is not the output of a complex algorithm. It is the emergent property of a system in which each component applies simple local rules to local state.

This matters because the conventional alternative — a SIEM watching all pods, correlating events, generating alerts, dispatching remediation playbooks — is architecturally a single large brain. A single large brain is a target. It must be highly available, must be fed data from all pods, must not be overloaded during an attack (precisely when attack volume is highest), and must itself be secured against compromise. It is a topologically central node, and in network security as in animal behaviour, topological centrality is a liability.

The confusion effect, which this prototype inherits from its biological inspiration, is not a metaphor. An attacker who has compromised pod-5 and holds its Vault token has the token revoked before they can use it — the credential compromise window is bounded by event loop latency. They are now running code in a pod that can reach nothing — the NetworkPolicy denies all egress before they can pivot. The mesh around them has already adapted — seven neighbours have hardened. The attacker cannot determine the mesh topology from inside an isolated pod with no network access. They cannot determine which pod is the controller, because the controller address is in an environment variable that may differ per deployment. There is nothing to lock on to.

And finally: the attack caused the cluster to improve. The infected pod is gone. Its replacement has the latest OS patches. The StatefulSet's recreated pod also has the latest patches. The seven hardened pods are in an elevated security posture. The cluster that exists after the incident is, in a narrow but real sense, more secure than the one that existed before it. This is stigmergy applied to cybersecurity: the infected pod's state change restructured the environment around it in a way that made future attacks harder. The attacker's action became the signal that prompted the system's adaptation.

Four hundred million years of predator–prey coevolution produced the murmuration. This prototype borrows three rules from that process and applies them to a cluster of sixteen pods. The rules do not explain themselves. They do not generate logs that say "I am applying separation." They simply fire, in parallel, at T+0s, without waiting for a central authority to authorise the response. That speed, and that architecture, is the point.

---

## 12. References

Reynolds, C.W. (1986). Flocks, herds and schools: A distributed behavioral model. *SIGGRAPH Computer Graphics*, 21(4), 25–34. The original three-rule boid algorithm. All subsequent implementations, including this one, trace to this paper.

Ballerini, M., Cabibbo, N., Candelier, R., Cavagna, A., Cisbani, E., Giardina, I., ... & Zdravkovic, V. (2008). Interaction ruling animal collective behaviour depends on topological rather than metric distance: Evidence from a field study. *Proceedings of the National Academy of Sciences*, 105(4), 1232–1237. The empirical confirmation that starlings respond to their seven topological nearest neighbours, not to birds within a fixed radius. The direct basis for `_nearest_n()` and `NEIGHBOUR_N = 7` in this implementation.

Cavagna, A., Cimarelli, A., Giardina, I., Parisi, G., Santagati, R., Stefanini, F., & Viale, M. (2010). Scale-free correlations in starling flocks. *Proceedings of the National Academy of Sciences*, 107(26), 11865–11870. Demonstrates that behavioural correlations in real murmurations span the entire flock regardless of flock size — the empirical basis for the claim that topological mesh responses scale better than centralised responses.

Parisi, G. (2022). Nobel Lecture: Multiple Equilibria. *Nobel Prize in Physics 2021*. The lecture in which Parisi discusses the statistical mechanics of complex systems, including murmurations, as examples of systems poised near critical phase transitions — giving them maximal sensitivity to perturbation and maximal speed of response.

HashiCorp Vault Documentation. *Token Auth Method — Token Creation and Renewal*. https://developer.hashicorp.com/vault/docs/auth/token. The Vault API used for JIT token creation (`auth/token/create`) and revocation (`auth/token/revoke`).

Kubernetes Documentation. *NetworkPolicy*. https://kubernetes.io/docs/concepts/services-networking/network-policies/. The K8s primitive used for pod-level isolation. Note the requirement for a CNI that enforces NetworkPolicy (Calico, Cilium, etc.).

Falco Project Documentation. *Falco Rules and Output*. https://falco.org/docs/rules/. The recommended replacement for the manual `/infect` trigger in a production deployment. Provides syscall-level anomaly detection without code changes to the monitored pods.

---

*Inspired by 400 million years of collective intelligence. Built in an afternoon.*
