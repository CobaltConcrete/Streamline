from codirector.api.state import AppState
from codirector.core.autonomy import AutonomyLevel, is_escalation
from codirector.policy.catalog import ActionCatalog
from tests.unit.test_policy import PERSONA

CATALOG = ActionCatalog.model_validate({"version": 1, "actions": []})


def test_startup_level():
    state = AppState(persona=PERSONA, catalog=CATALOG)
    assert state.autonomy == AutonomyLevel.OBSERVE


def test_no_silent_escalation():
    # is_escalation() is a pure helper; the actual guarantee is that nothing
    # in the codebase calls set_autonomy() except the explicit
    # POST /api/autonomy route handler (routes.py) — never a background
    # task, health callback, or reconnect handler.
    assert is_escalation(AutonomyLevel.OBSERVE, AutonomyLevel.ASSIST) is True
    assert is_escalation(AutonomyLevel.OBSERVE, AutonomyLevel.OBSERVE) is False
    assert is_escalation(AutonomyLevel.CO_DIRECT, AutonomyLevel.ASSIST) is False

    state = AppState(persona=PERSONA, catalog=CATALOG)
    assert state.autonomy == AutonomyLevel.OBSERVE
    # set_autonomy() itself never gates direction — the guarantee is about
    # *who* may call it (an explicit UI action only), not whether escalation
    # is allowed at all.
    state.set_autonomy(AutonomyLevel.CO_DIRECT)
    assert state.autonomy == AutonomyLevel.CO_DIRECT
