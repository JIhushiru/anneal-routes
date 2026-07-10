"""API surface: REST endpoints and the WebSocket streaming protocol end-to-end."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import Problem, SolveResult

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_scenarios_are_valid_problems():
    payload = client.get("/api/scenarios").json()
    keys = {s["key"] for s in payload}
    assert keys == {"metro-manila", "laguna", "random-50"}
    for sc in payload:
        problem = Problem.model_validate(sc["problem"])
        assert len(problem.stops) in (15, 25, 50)


def _laguna_request(algorithm: str, iterations: int = 8_000) -> dict:
    problem = client.get("/api/scenarios").json()[1]["problem"]
    return {
        "type": "solve",
        "problem": problem,
        "params": {
            "algorithm": algorithm,
            "time_limit_s": 10,
            "sa": {"iterations": iterations, "seed": 11},
        },
    }


def test_sync_solve_nearest_neighbor():
    resp = client.post("/api/solve", json=_laguna_request("nn"))
    assert resp.status_code == 200
    result = SolveResult.model_validate(resp.json())
    assert result.total_distance_km > 0
    visited = sorted(sid for r in result.routes for sid in r.stop_ids)
    assert visited == list(range(1, 16))


def test_websocket_sa_streams_progress_then_done():
    with client.websocket_connect("/ws/solve") as ws:
        ws.send_json(_laguna_request("sa"))
        progress_seen = 0
        temperatures = []
        while True:
            msg = ws.receive_json()
            assert msg["type"] in ("progress", "done", "error")
            assert msg["type"] != "error", msg
            if msg["type"] == "progress":
                progress_seen += 1
                assert msg["routes"], "progress frames must carry incumbent routes"
                if msg["temperature"] is not None:
                    temperatures.append(msg["temperature"])
            else:
                result = SolveResult.model_validate(msg["result"])
                break
        assert progress_seen >= 1
        assert temperatures and temperatures[-1] < temperatures[0]  # cooling visible on the wire
        assert result.feasible
        assert result.iterations is not None and result.iterations > 0


def test_websocket_rejects_malformed_request():
    with client.websocket_connect("/ws/solve") as ws:
        ws.send_json({"type": "solve", "problem": {"nope": True}, "params": {}})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "invalid solve request" in msg["message"]
