"""
Demo Pod App v2
================
Minimal HTTP service representing a pod in the murmuration mesh.
On startup, registers with the controller to receive a JIT Vault credential.
Exposes /health /healthz /ready /status /infect endpoints.
"""

import json
import os
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

POD_NAME       = os.environ.get("POD_NAME",       "unknown")
POD_IP         = os.environ.get("POD_IP",         "0.0.0.0")
CONTROLLER_URL = os.environ.get("CONTROLLER_URL",
    "http://murmuration-controller.murmuration-system.svc.cluster.local:8080")
STATE_FILE     = "/etc/pod-state/state"
PORT           = int(os.environ.get("PORT", "8080"))

start_time     = time.time()
request_count  = 0
_state_override = None
_jit_token      = None   # Vault token received on registration


def read_state() -> str:
    if _state_override:
        return _state_override
    try:
        with open(STATE_FILE) as f:
            return f.read().strip().strip('"') or "healthy"
    except Exception:
        return "healthy"


def register_with_controller():
    """Call controller /register on startup to obtain a JIT Vault credential."""
    global _jit_token
    time.sleep(4)   # give controller time to start
    for attempt in range(10):
        try:
            body = json.dumps({"pod": POD_NAME, "ip": POD_IP}).encode()
            req  = urllib.request.Request(
                f"{CONTROLLER_URL}/register",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
                _jit_token = data.get("token")
                ttl = data.get("ttl", "unknown")
                print(f"[{POD_NAME}] JIT credential obtained (TTL: {ttl})")
                return
        except urllib.error.URLError as e:
            print(f"[{POD_NAME}] Registration attempt {attempt+1}/10 failed: {e.reason}")
            time.sleep(6)
        except Exception as e:
            print(f"[{POD_NAME}] Registration error: {e}")
            time.sleep(6)
    print(f"[{POD_NAME}] Could not register with controller after 10 attempts")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global request_count
        request_count += 1
        state = read_state()

        if self.path in ("/health", "/healthz"):
            code = 503 if state in ("infected", "isolated", "forensic") else 200
            self.send_json(code, {"status": "healthy" if code == 200 else "unhealthy",
                                  "state": state, "pod": POD_NAME})

        elif self.path == "/ready":
            code = 503 if state in ("isolated", "forensic") else 200
            self.send_json(code, {"ready": code == 200, "state": state})

        elif self.path == "/status":
            self.send_json(200, {
                "pod":           POD_NAME,
                "ip":            POD_IP,
                "state":         state,
                "uptime_s":      round(time.time() - start_time),
                "requests":      request_count,
                "has_jit_token": _jit_token is not None,
            })
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        global _state_override
        if self.path == "/infect":
            _state_override = "infected"
            self.send_json(200, {"ok": True, "pod": POD_NAME, "state": "infected"})
            print(f"[{POD_NAME}] Infected via /infect endpoint")
        elif self.path == "/heal":
            _state_override = None
            self.send_json(200, {"ok": True, "pod": POD_NAME, "state": "healing"})
        else:
            self.send_json(404, {"error": "not found"})


def main():
    # Register with controller in background thread
    threading.Thread(target=register_with_controller, daemon=True).start()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[{POD_NAME}] Demo app v2 listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
