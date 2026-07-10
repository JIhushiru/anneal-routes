#!/usr/bin/env python3
"""Run OptiRoute PH locally with one command: FastAPI backend + Vite frontend.

    python run.py                     # backend on :8000 (or next free), UI on :5173
    python run.py --api-port 8001 --web-port 5200

First run bootstraps everything it needs: creates backend/.venv and installs
requirements, runs npm install for the frontend. Ctrl+C stops both services
(during startup, press it twice — a single stray console event is ignored).

Default ports fall back to the next free one automatically (port 8000 is a
popular squat); a port you pass explicitly must be free or the launcher exits.

This is the no-Docker path; `docker compose up` remains the containerized one.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
WINDOWS = os.name == "nt"
VENV_PYTHON = BACKEND / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")

# 0xC000013A = STATUS_CONTROL_C_EXIT — a normal Ctrl+C death on Windows.
_CTRL_C_EXIT = 3221225786

_stop = threading.Event()
_phase = "starting"
_interrupts = 0


def info(msg: str) -> None:
    print(f"[run] {msg}", flush=True)


def _handle_interrupt(signum: int, frame: object) -> None:
    """Stop on interrupt — but survive a single stray console event at startup.

    Windows consoles can deliver a spurious ctrl event to a freshly started
    process; treating the first interrupt during startup as noise (with a
    visible note) keeps the launcher alive while still letting a real
    double Ctrl+C abort.
    """
    global _interrupts
    _interrupts += 1
    if _phase == "starting" and _interrupts == 1:
        info("interrupt received during startup — ignoring once (press Ctrl+C again to abort)")
        return
    _stop.set()


def run_step(cmd: list[str], cwd: Path, what: str) -> None:
    info(what)
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        sys.exit(f"[run] FAILED ({result.returncode}): {what}")


def npm_path() -> str:
    npm = shutil.which("npm.cmd" if WINDOWS else "npm") or shutil.which("npm")
    if not npm:
        sys.exit("[run] npm not found — install Node.js 20+ first")
    return npm


def ensure_backend() -> None:
    if not VENV_PYTHON.exists():
        run_step([sys.executable, "-m", "venv", ".venv"], BACKEND, "creating backend/.venv")
        run_step(
            [str(VENV_PYTHON), "-m", "pip", "install", "-q", "-r", "requirements.txt"],
            BACKEND,
            "installing backend dependencies (one-time, a few minutes — OR-Tools is big)",
        )


def ensure_frontend() -> None:
    if not (FRONTEND / "node_modules").exists():
        run_step([npm_path(), "install", "--no-audit", "--no-fund"], FRONTEND, "npm install (one-time)")


def port_busy(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


def pick_port(requested: int | None, default: int, what: str) -> int:
    """Explicit port: must be free. Default port: fall back to the next free one."""
    if requested is not None:
        if port_busy(requested):
            sys.exit(
                f"[run] port {requested} is already in use ({what}) — is another instance "
                "still running? Stop it (or pass a different port) and retry."
            )
        return requested
    for candidate in range(default, default + 20):
        if not port_busy(candidate):
            if candidate != default:
                info(f"port {default} is taken — using {candidate} for the {what}")
            return candidate
    sys.exit(f"[run] no free port found for the {what} in {default}-{default + 19}")


def spawn(cmd: list[str], cwd: Path, tag: str, env: dict[str, str] | None = None) -> subprocess.Popen:
    """Start a child process whose output is streamed with a [tag] prefix."""
    kwargs: dict = {}
    if WINDOWS:
        # Own process group: console ctrl events never hit the children
        # directly — shutdown is always orchestrated by this launcher.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True  # own group, so we can kill the tree
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **kwargs,
    )

    def pump() -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                print(f"[{tag}] {line.rstrip()}", flush=True)
        except (OSError, ValueError):
            pass  # our stdout/pipe went away mid-shutdown — nothing to do

    threading.Thread(target=pump, daemon=True).start()
    return proc


def kill_tree(proc: subprocess.Popen) -> None:
    """Terminate a child and everything it spawned (npm forks node, etc.)."""
    if proc.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def wait_for_api(api: subprocess.Popen, port: int, timeout_s: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout_s
    url = f"http://localhost:{port}/api/health"
    while time.monotonic() < deadline and not _stop.is_set():
        if api.poll() is not None:
            info(f"backend exited during startup (code {api.returncode}) — see [api] output above")
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(1.0)
    return False


def main() -> None:
    global _phase
    parser = argparse.ArgumentParser(description="Run the OptiRoute PH backend + frontend together")
    parser.add_argument("--api-port", type=int, default=None, help="backend port (default: 8000 or next free)")
    parser.add_argument("--web-port", type=int, default=None, help="frontend port (default: 5173 or next free)")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_interrupt)
    if WINDOWS and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_interrupt)

    ensure_backend()
    ensure_frontend()
    api_port = pick_port(args.api_port, 8000, "backend API")
    web_port = pick_port(args.web_port, 5173, "frontend")

    procs: list[tuple[str, subprocess.Popen]] = []
    exit_code = 0
    try:
        api = spawn(
            [
                str(VENV_PYTHON), "-m", "uvicorn", "app.main:app",
                "--port", str(api_port), "--log-level", "info",
            ],
            BACKEND,
            "api",
        )
        procs.append(("backend", api))

        if not wait_for_api(api, api_port):
            if not _stop.is_set():
                info("backend did not become healthy — aborting")
            raise SystemExit(1)
        info(f"backend ready -> http://localhost:{api_port}")

        # vite.config.ts reads BACKEND_URL at startup, so the /api and /ws
        # proxies follow whichever port the backend actually landed on.
        web = spawn(
            [npm_path(), "run", "dev", "--", "--port", str(web_port), "--strictPort"],
            FRONTEND,
            "web",
            env={"BACKEND_URL": f"http://localhost:{api_port}"},
        )
        procs.append(("frontend", web))

        info(f"frontend starting -> http://localhost:{web_port}  (Ctrl+C stops both)")
        _phase = "running"

        # Babysit: stop on interrupt, or when either service dies take the
        # other down with it rather than leaving a half-running stack.
        stopping = False
        while not stopping:
            if _stop.is_set():
                info("interrupt received — stopping…")
                break
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    if code in (0, _CTRL_C_EXIT):
                        info(f"{name} stopped — shutting down the rest")
                    else:
                        info(f"{name} exited with code {code} — shutting down the rest")
                        exit_code = code
                    stopping = True
                    break
            time.sleep(0.5)
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else 1
    finally:
        for _name, proc in reversed(procs):
            kill_tree(proc)
        info("all services stopped")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
