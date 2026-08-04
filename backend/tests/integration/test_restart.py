"""R-AUT-02: Co-direct never persists across an app restart. There is no
save/load path for autonomy anywhere in this codebase — a fresh AppState
(the only way autonomy is ever represented) always starts at OBSERVE."""
from codirector.api.state import AppState
from codirector.core.autonomy import AutonomyLevel
from codirector.policy.catalog import ActionCatalog
from tests.unit.test_policy import PERSONA

CATALOG = ActionCatalog.model_validate({"version": 1, "actions": []})


def test_codirect_not_persisted():
    first_process = AppState(persona=PERSONA, catalog=CATALOG)
    first_process.set_autonomy(AutonomyLevel.CO_DIRECT)
    assert first_process.autonomy == AutonomyLevel.CO_DIRECT

    # Simulated restart: a new process constructs a new AppState from the
    # same on-disk config. Nothing about the prior instance's in-memory
    # autonomy value is read back.
    second_process = AppState(persona=PERSONA, catalog=CATALOG)
    assert second_process.autonomy == AutonomyLevel.OBSERVE
