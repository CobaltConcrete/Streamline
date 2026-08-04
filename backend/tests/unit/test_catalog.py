import pytest
from pydantic import ValidationError

from codirector.policy.catalog import ActionCatalog, KnownOBSTargets, resolve_targets

VALID_CATALOG = {
    "version": 1,
    "actions": [
        {
            "id": "show_question_overlay",
            "type": "overlay_text",
            "risk": "low",
            "target": {"input_name": "AI_Question_Text"},
            "limits": {"max_length": 120, "duration_ms": 8000, "cooldown_s": 45, "max_per_session": 30},
            "reversible": True,
        }
    ],
}


def test_unknown_action_type_rejected():
    bad = {
        "version": 1,
        "actions": [
            {
                "id": "delete_everything",
                "type": "delete_source",  # not in ActionType — must refuse to load
                "risk": "low",
                "target": {"input_name": "x"},
                "limits": {"cooldown_s": 1, "max_per_session": 1},
            }
        ],
    }
    with pytest.raises(ValidationError):
        ActionCatalog.model_validate(bad)


def test_unresolvable_target_disables_action():
    catalog = ActionCatalog.model_validate(VALID_CATALOG)
    # OBS has no input named AI_Question_Text.
    known = KnownOBSTargets(scenes={"Gameplay"}, inputs={"SomeOtherInput"})
    warnings = resolve_targets(catalog, known)

    action = catalog.get("show_question_overlay")
    assert action.enabled is False
    assert action.disabled_reason is not None
    assert len(warnings) == 1
    assert "show_question_overlay" in warnings[0]


def test_resolvable_target_stays_enabled():
    catalog = ActionCatalog.model_validate(VALID_CATALOG)
    known = KnownOBSTargets(scenes={"Gameplay"}, inputs={"AI_Question_Text"})
    warnings = resolve_targets(catalog, known)

    action = catalog.get("show_question_overlay")
    assert action.enabled is True
    assert warnings == []
