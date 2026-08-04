from fastapi.testclient import TestClient

from codirector.api.server import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_autonomy_starts_at_observe():
    with _client() as c:
        resp = c.get("/api/autonomy")
        assert resp.status_code == 200
        assert resp.json()["level"] == "OBSERVE"  # R-AUT-01


def test_set_autonomy():
    with _client() as c:
        resp = c.post("/api/autonomy", json={"level": "CO_DIRECT"})
        assert resp.status_code == 200
        assert resp.json()["level"] == "CO_DIRECT"


def test_kill_switch_forces_observe_and_blocks_autonomy_change():
    with _client() as c:
        c.post("/api/autonomy", json={"level": "CO_DIRECT"})
        resp = c.post("/api/kill-switch")
        assert resp.status_code == 200
        assert resp.json() == {
            "kill_switch_engaged": True,
            "autonomy": "OBSERVE",
            "cleared_pending": 0,
        }

        blocked = c.post("/api/autonomy", json={"level": "CO_DIRECT"})
        assert blocked.status_code == 409

        c.post("/api/resume")
        allowed = c.post("/api/autonomy", json={"level": "CO_DIRECT"})
        assert allowed.status_code == 200


def test_queue_endpoints_404_for_unknown_decision():
    with _client() as c:
        for action in ("accept", "dismiss", "snooze", "pin"):
            resp = c.post(f"/api/queue/does-not-exist/{action}")
            assert resp.status_code == 404


def test_catalog_and_persona_endpoints():
    with _client() as c:
        catalog = c.get("/api/catalog").json()
        assert catalog["version"] == 1
        assert any(a["id"] == "show_question_overlay" for a in catalog["actions"])

        persona = c.get("/api/persona").json()
        assert persona["name"] == "conversational"


def test_websocket_snapshot():
    with _client() as c, c.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "snapshot"
        assert data["autonomy"] == "OBSERVE"
        assert "queue" in data
        assert "health" in data
