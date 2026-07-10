"""FastAPI application: REST endpoints plus the /ws/solve streaming socket.

Streaming architecture
----------------------
The solvers are synchronous CPU-bound code, so each solve runs in a worker
thread. Events cross into asyncio through ``loop.call_soon_threadsafe`` onto an
``asyncio.Queue``; the socket handler drains that queue, coalescing bursts of
progress events (SA can improve thousands of times per second early on) down to
roughly 30 frames/second — enough for a smooth animation, without flooding the
client. Improvement and tick events carry the full incumbent routes, so the map
can redraw from any single frame; dropping intermediate frames loses nothing.
"""

from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .osrm import OSRMError
from .scenarios import SCENARIOS
from .schemas import DoneEvent, ErrorEvent, ProgressEvent, SolveRequest, SolveResult
from .service import run_solver_streaming

FRAME_INTERVAL_S = 0.03

app = FastAPI(title="OptiRoute PH API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev tool; lock down if ever deployed for real
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return [
        {
            "key": key,
            "name": sc["name"],
            "description": sc["description"],
            "problem": sc["problem"].model_dump(),
        }
        for key, sc in SCENARIOS.items()
    ]


@app.post("/api/solve")
def solve_sync(request: SolveRequest) -> SolveResult:
    """Blocking solve without streaming (used by benchmarks and as a fallback).

    Declared ``def`` (not ``async``) so FastAPI runs it in its threadpool and the
    event loop stays responsive.
    """
    try:
        return run_solver_streaming(request.problem, request.params, emit=lambda _: None)
    except OSRMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.websocket("/ws/solve")
async def ws_solve(ws: WebSocket) -> None:
    await ws.accept()
    try:
        raw = await ws.receive_json()
        request = SolveRequest.model_validate(raw)
    except (ValidationError, ValueError) as exc:
        await ws.send_text(ErrorEvent(message=f"invalid solve request: {exc}").model_dump_json())
        await ws.close()
        return
    except WebSocketDisconnect:
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_flag = threading.Event()

    def emit(event: ProgressEvent) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work() -> None:
        try:
            result = run_solver_streaming(request.problem, request.params, emit, stop_flag.is_set)
            loop.call_soon_threadsafe(queue.put_nowait, DoneEvent(result=result))
        except OSRMError as exc:
            loop.call_soon_threadsafe(queue.put_nowait, ErrorEvent(message=str(exc)))
        except Exception as exc:  # surface anything else to the client, too
            loop.call_soon_threadsafe(queue.put_nowait, ErrorEvent(message=f"solver error: {exc}"))

    worker = threading.Thread(target=work, daemon=True)
    worker.start()

    async def watch_client() -> None:
        """Set the stop flag on an explicit cancel message or a disconnect.

        Unparseable frames (bad JSON, binary) are IGNORED, not treated as a
        cancel — a stray frame must not silently truncate a solve.
        """
        while True:
            try:
                msg = await ws.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                stop_flag.set()
                return
            except Exception:
                continue
            if isinstance(msg, dict) and msg.get("type") == "cancel":
                stop_flag.set()
                return

    watcher = asyncio.create_task(watch_client())
    try:
        while True:
            event = await queue.get()
            # Coalesce queued-up progress bursts: keep only the newest, but never
            # skip past a done/error event.
            while isinstance(event, ProgressEvent) and not queue.empty():
                nxt = queue.get_nowait()
                if isinstance(nxt, ProgressEvent):
                    event = nxt
                else:
                    await ws.send_text(event.model_dump_json())
                    event = nxt
                    break
            await ws.send_text(event.model_dump_json())
            if isinstance(event, (DoneEvent, ErrorEvent)):
                break
            await asyncio.sleep(FRAME_INTERVAL_S)
    except (WebSocketDisconnect, RuntimeError):
        stop_flag.set()
    finally:
        watcher.cancel()
        try:
            await ws.close()
        except Exception:
            pass
