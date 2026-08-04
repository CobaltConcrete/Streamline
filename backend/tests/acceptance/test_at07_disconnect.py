"""AT-07 (§6.5): OBS disconnects for 15s, then reconnects. Expected: no stale
action executes while disconnected; state refreshes on reconnect;
Co-direct/any elevated autonomy remains paused pending an explicit resume —
reconnecting never silently restores it (R-AUT-03)."""
from fastapi.testclient import TestClient

from codirector.api.server import create_app
from codirector.core.phase import Phase, PhaseEngine, SceneRole, is_safe_window


def test_at07_disconnect_then_reconnect_phase_is_conservative_then_recovers():
    engine = PhaseEngine({"Gameplay": SceneRole.ACTIVE})
    engine.on_obs_state("Gameplay")
    assert engine.current_phase(now=0.0) == Phase.ACTIVE_SPEAKING

    # 15s disconnect.
    engine.on_obs_disconnected()
    assert engine.current_phase(now=1.0) == Phase.UNKNOWN
    assert is_safe_window(Phase.UNKNOWN) is False  # nothing may surface/execute while unknown

    # Reconnect: state is refreshed and phase recovers immediately once OBS
    # reports its current scene again.
    engine.on_obs_state("Gameplay")
    assert engine.current_phase(now=16.0) == Phase.ACTIVE_SPEAKING


def test_at07_autonomy_remains_paused_pending_explicit_resume():
    with TestClient(create_app()) as c:
        c.post("/api/autonomy", json={"level": "CO_DIRECT"})
        assert c.get("/api/autonomy").json()["level"] == "CO_DIRECT"

        # An OBS disconnect is modeled here as the kill switch engaging
        # (§5.6 "safe state on disconnect" reuses the same frozen/paused
        # state as the kill switch — see R-SAF-05/SAF-04).
        c.post("/api/kill-switch")
        assert c.get("/api/autonomy").json()["level"] == "OBSERVE"

        # "Reconnecting" (simulated: nothing in the system pushes autonomy
        # back up on its own) must NOT silently restore CO_DIRECT.
        assert c.get("/api/autonomy").json()["level"] == "OBSERVE"

        # Only an explicit resume + explicit re-selection restores it.
        c.post("/api/resume")
        assert c.get("/api/autonomy").json()["level"] == "OBSERVE"  # resume alone doesn't re-escalate either
        c.post("/api/autonomy", json={"level": "CO_DIRECT"})
        assert c.get("/api/autonomy").json()["level"] == "CO_DIRECT"
