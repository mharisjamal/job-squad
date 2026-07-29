"""JobSquad launcher.

One command brings up the whole stack:

1. checks that uv and npm are installed
2. installs backend dependencies (uv sync)
3. installs frontend dependencies (npm install, first run only)
4. builds the React frontend (npm run build)
5. starts the FastAPI server, which serves the API and the built app on
   one port (default 8100), prints local + LAN URLs, and opens the app
   in your default browser

Set JOBSQUAD_DEV=1 to skip the build and also run the Vite dev server
(hot reload) on port 3100. Set JOBSQUAD_PORT to change the API port.
Ctrl+C stops everything.

Standard library only. Windows-first, works on macOS/Linux too.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

DEFAULT_PORT = 8100      # API + built SPA (override with JOBSQUAD_PORT)
DEV_PORT = 3100          # Vite dev server (JOBSQUAD_DEV=1)
HEALTH_TIMEOUT_S = 60    # max wait for the API to answer /health
STOP_GRACE_S = 10        # max wait for children to exit during shutdown
IS_WINDOWS = os.name == "nt"


def fail(message: str) -> NoReturn:
    print(f"\nERROR: {message}", flush=True)
    sys.exit(1)


def preflight() -> tuple[str, str]:
    """Verify uv and npm are on PATH; return their executable paths."""
    uv = shutil.which("uv")
    npm = shutil.which("npm")  # resolves to npm.cmd on Windows
    missing = []
    if uv is None:
        missing.append("uv  (Python package manager) - install from https://astral.sh/uv")
    if npm is None:
        missing.append("npm (comes with Node.js)    - install from https://nodejs.org")
    if missing:
        print("JobSquad cannot start; required tools are missing:", flush=True)
        for item in missing:
            print(f"  - {item}", flush=True)
        sys.exit(1)
    return uv, npm


def child_env() -> dict[str, str]:
    """Environment for children; keeps uv's heavy caches off C: when D: exists."""
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    if IS_WINDOWS and Path("D:\\").exists():
        env.setdefault("UV_CACHE_DIR", r"D:\uv")
        env.setdefault("UV_PYTHON_INSTALL_DIR", r"D:\uv\python")
    return env


def api_port() -> int:
    raw = os.environ.get("JOBSQUAD_PORT", str(DEFAULT_PORT))
    try:
        return int(raw)
    except ValueError:
        fail(f"JOBSQUAD_PORT must be a number, got {raw!r}")


def lan_ip() -> str:
    """Best-effort LAN IP via the UDP-connect trick (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _pump_output(prefix: str, proc: subprocess.Popen[str]) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{prefix}] {line.rstrip()}", flush=True)


def start_child(
    cmd: list[str], cwd: Path, env: dict[str, str], prefix: str
) -> subprocess.Popen[str]:
    """Start a child process and stream its output prefixed with [prefix]."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    threading.Thread(target=_pump_output, args=(prefix, proc), daemon=True).start()
    return proc


def run_step(
    label: str, cmd: list[str], cwd: Path, env: dict[str, str], prefix: str
) -> int:
    """Run a blocking setup step, streaming its output; return the exit code."""
    print(f"\n=== {label} ===", flush=True)
    return start_child(cmd, cwd, env, prefix).wait()


def stop_children(procs: list[subprocess.Popen[str]]) -> None:
    """Kill children and everything they spawned (npm -> node, uv -> uvicorn)."""
    running = [proc for proc in procs if proc.poll() is None]
    for proc in running:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
    for proc in running:
        try:
            proc.wait(timeout=STOP_GRACE_S)
        except subprocess.TimeoutExpired:
            proc.kill()


def wait_for_health(port: int, api: subprocess.Popen[str]) -> bool:
    """Poll /health until the API answers, the API dies, or the timeout passes."""
    url = f"http://localhost:{port}/health"
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        if api.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def print_summary(app_port: int, backend_port: int, dev_mode: bool) -> None:
    lines = ["JobSquad is starting"]
    if dev_mode:
        lines.append(f"Dev mode: Vite hot reload on port {app_port}, API on port {backend_port}")
    lines += [
        "",
        f"Local:    http://localhost:{app_port}",
        f"Network:  http://{lan_ip()}:{app_port}",
        "",
        "Friends on the same Wi-Fi can open the Network URL.",
        "Windows Firewall may ask to allow Python or Node: allow it.",
        "Press Ctrl+C to stop.",
    ]
    inner = max(len(line) for line in lines) + 4
    print("\n+" + "-" * inner + "+", flush=True)
    for line in lines:
        print(f"|  {line.ljust(inner - 4)}  |", flush=True)
    print("+" + "-" * inner + "+\n", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("JobSquad launcher", flush=True)

    for directory in (BACKEND_DIR, FRONTEND_DIR):
        if not directory.is_dir():
            fail(f"missing folder {directory}; run.py must sit next to backend/ and frontend/")

    uv, npm = preflight()
    env = child_env()
    port = api_port()
    dev_mode = os.environ.get("JOBSQUAD_DEV", "").strip() == "1"

    if run_step("Installing backend dependencies (uv sync)", [uv, "sync"], BACKEND_DIR, env, "api") != 0:
        fail("uv sync failed in backend/; fix the error above and rerun")

    if not (FRONTEND_DIR / "node_modules").is_dir():
        if run_step("Installing frontend dependencies (npm install)", [npm, "install"], FRONTEND_DIR, env, "web") != 0:
            fail("npm install failed in frontend/; fix the error above and rerun")

    if not dev_mode:
        if run_step("Building frontend (npm run build)", [npm, "run", "build"], FRONTEND_DIR, env, "web") != 0:
            print(f"\nWARNING: frontend build failed; falling back to dev mode (Vite on port {DEV_PORT})", flush=True)
            dev_mode = True

    print("\n=== Starting servers ===", flush=True)
    procs: list[subprocess.Popen[str]] = []
    api = start_child(
        [uv, "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port)],
        BACKEND_DIR,
        env,
        "api",
    )
    procs.append(api)
    web: subprocess.Popen[str] | None = None
    if dev_mode:
        web = start_child([npm, "run", "dev"], FRONTEND_DIR, env, "web")
        procs.append(web)

    app_port = DEV_PORT if dev_mode else port
    app_url = f"http://localhost:{app_port}"
    print_summary(app_port, port, dev_mode)

    try:
        if wait_for_health(port, api):
            print(f"API is up; opening {app_url} in your browser", flush=True)
            webbrowser.open(app_url)
        elif api.poll() is None:
            print(f"WARNING: no answer from /health after {HEALTH_TIMEOUT_S}s; not opening the browser", flush=True)
        while True:
            time.sleep(1)
            if api.poll() is not None:
                print(f"\nERROR: the API exited unexpectedly (code {api.returncode}); stopping everything", flush=True)
                stop_children(procs)
                return 1
            if web is not None and web.poll() is not None:
                print(f"\nERROR: the Vite dev server exited unexpectedly (code {web.returncode}); stopping everything", flush=True)
                stop_children(procs)
                return 1
    except KeyboardInterrupt:
        print("\nShutting down JobSquad", flush=True)
        stop_children(procs)
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Ctrl+C during an install/build step: children share the console
        # and receive the same signal, so they stop on their own.
        print("\nInterrupted", flush=True)
        sys.exit(0)
