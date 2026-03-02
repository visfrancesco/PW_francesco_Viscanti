#!/usr/bin/env python3
"""
Orchestrator HTTP API per i simulatori della Tenuta Ferrante.

Gestisce i simulatori come sottoprocessi e espone un'API REST
per avviarli/fermarli dalla dashboard. Il bridge InfluxDB si avvia
automaticamente al boot e non è controllabile dalla UI.

Endpoints:
    GET  /status              — stato dei simulatori controllabili
    POST /start/{name}        — avvia un simulatore
    POST /stop/{name}         — ferma un simulatore
    POST /start-all           — avvia tutti i controllabili
    POST /stop-all            — ferma tutti i controllabili
    GET  /parcelle-config     — legge config scenari per-parcella
    POST /parcelle-config     — toggle scenario per singola parcella
"""

import json
import subprocess
import sys
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import PARCELLE_IDS, SIM_CONFIG_PATH

# Simulatori controllabili dalla dashboard
SIMULATORS = {
    "microclima":     {"cmd": [sys.executable, "-u", "sensore_microclima.py"]},
    "suolo":          {"cmd": [sys.executable, "-u", "sensore_suolo.py"]},
    "elettrovalvola": {"cmd": [sys.executable, "-u", "elettrovalvola.py"]},
}

# Bridge: si avvia automaticamente, non esposto in /status
BRIDGE_CMD = [sys.executable, "-u", "bridge_influxdb.py"]

processes: dict[str, subprocess.Popen | None] = {name: None for name in SIMULATORS}
bridge_proc: subprocess.Popen | None = None

# Struttura config per-parcella: { simulator: { scenario: { parcella_id: bool } } }
DEFAULT_SIM_CONFIG = {
    "microclima": {"gelata": {pid: False for pid in PARCELLE_IDS}},
    "suolo":      {"stress": {pid: False for pid in PARCELLE_IDS}},
}


def init_sim_config():
    """Crea il file config con valori default se non esiste."""
    try:
        with open(SIM_CONFIG_PATH) as f:
            json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        write_sim_config(DEFAULT_SIM_CONFIG)


def read_sim_config() -> dict:
    try:
        with open(SIM_CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return DEFAULT_SIM_CONFIG


def write_sim_config(config: dict):
    with open(SIM_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def start_bridge():
    global bridge_proc
    if bridge_proc is not None and bridge_proc.poll() is None:
        return
    bridge_proc = subprocess.Popen(BRIDGE_CMD, stdout=None, stderr=subprocess.STDOUT)
    print(f"[orchestrator] Bridge avviato (PID {bridge_proc.pid})")


def stop_bridge():
    global bridge_proc
    if bridge_proc is None or bridge_proc.poll() is not None:
        bridge_proc = None
        return
    bridge_proc.terminate()
    try:
        bridge_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        bridge_proc.kill()
    bridge_proc = None


def is_running(name: str) -> bool:
    proc = processes.get(name)
    return proc is not None and proc.poll() is None


def start(name: str) -> dict:
    if name not in SIMULATORS:
        return {"error": f"simulatore sconosciuto: {name}"}
    if is_running(name):
        return {"name": name, "status": "already_running"}
    proc = subprocess.Popen(
        SIMULATORS[name]["cmd"],
        stdout=None,
        stderr=subprocess.STDOUT,
    )
    processes[name] = proc
    return {"name": name, "status": "started", "pid": proc.pid}


def stop(name: str) -> dict:
    if name not in SIMULATORS:
        return {"error": f"simulatore sconosciuto: {name}"}
    proc = processes.get(name)
    if proc is None or proc.poll() is not None:
        processes[name] = None
        return {"name": name, "status": "already_stopped"}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    processes[name] = None
    return {"name": name, "status": "stopped"}


def get_status() -> list[dict]:
    result = []
    for name in SIMULATORS:
        running = is_running(name)
        pid = processes[name].pid if running else None
        result.append({"name": name, "running": running, "pid": pid})
    return result


class Handler(BaseHTTPRequestHandler):
    def _respond(self, code: int, body: dict | list):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/status":
            self._respond(200, get_status())
        elif self.path == "/parcelle-config":
            self._respond(200, read_sim_config())
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/start-all":
            results = [start(name) for name in SIMULATORS]
            self._respond(200, results)
        elif self.path == "/stop-all":
            results = [stop(name) for name in SIMULATORS]
            self._respond(200, results)
        elif self.path.startswith("/start/"):
            name = self.path[len("/start/"):]
            self._respond(200, start(name))
        elif self.path.startswith("/stop/"):
            name = self.path[len("/stop/"):]
            self._respond(200, stop(name))
        elif self.path == "/parcelle-config":
            body = self._read_body()
            simulator = body.get("simulator")
            parcella = body.get("parcella")
            enabled = body.get("enabled", False)
            config = read_sim_config()
            if simulator in config:
                for scenario in config[simulator]:
                    if parcella in config[simulator][scenario]:
                        config[simulator][scenario][parcella] = bool(enabled)
            write_sim_config(config)
            self._respond(200, config)
        else:
            self._respond(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[orchestrator] {args[0]}")


def main():
    init_sim_config()
    start_bridge()

    for name in SIMULATORS:
        result = start(name)
        print(f"[orchestrator] {name}: {result['status']}")

    server = HTTPServer(("0.0.0.0", 9000), Handler)
    print("[orchestrator] API in ascolto su :9000")

    def shutdown(signum, frame):
        print("\n[orchestrator] Arresto simulatori...")
        for name in SIMULATORS:
            stop(name)
        stop_bridge()
        server.shutdown()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
