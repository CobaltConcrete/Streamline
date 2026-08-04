"""AT-09 (§6.5)/R-SAF-06: the overlay text field receives
`<img src=x onerror=alert(1)>`. Expected: rendered as literal text, no
script execution, no CSP violation (because no script is ever present to
violate it with).

Two independent facts make this true structurally, not by content-filtering:
1. frontend/public/overlay.html (the OBS Browser Source) only ever assigns
   to `.textContent`, never `.innerHTML`/`eval`/`document.write`, and ships a
   `default-src 'none'` CSP — checked here as a static-source assertion.
2. The `overlay_text` action type in this catalog targets a native OBS text
   source via set_input_text (obsws-python's set_input_settings), which OBS
   renders as plain text directly — there is no HTML/DOM anywhere in that
   path for a payload to be interpreted by.
"""
from pathlib import Path

from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.models import Decision, Proposal
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import ActionCatalog

OVERLAY_HTML = Path(__file__).resolve().parents[3] / "frontend" / "public" / "overlay.html"
OVERLAY_JS = Path(__file__).resolve().parents[3] / "frontend" / "public" / "overlay.js"

CATALOG = ActionCatalog.model_validate(
    {
        "version": 1,
        "actions": [
            {
                "id": "show_question_overlay", "type": "overlay_text", "risk": "low",
                "target": {"input_name": "AI_Question_Text"},
                "limits": {"max_length": 120, "duration_ms": 8000, "cooldown_s": 45, "max_per_session": 30},
                "reversible": True,
            }
        ],
    }
)


def test_overlay_html_never_parses_content_as_markup():
    source = OVERLAY_HTML.read_text(encoding="utf-8") + OVERLAY_JS.read_text(encoding="utf-8")
    assert "innerHTML" not in source
    assert "document.write" not in source
    assert "eval(" not in source
    assert ".textContent" in source
    assert "default-src 'none'" in source
    assert "script-src 'self'" in source
    assert "<script>" not in OVERLAY_HTML.read_text(encoding="utf-8")


async def test_xss_payload_passed_through_as_literal_text_not_html():
    provider = MockOBSProvider()
    orchestrator = OBSOrchestrator(provider)
    action = CATALOG.get("show_question_overlay")

    payload = "<img src=x onerror=alert(1)>"
    proposal = Proposal(
        cluster_id="c1", decision_type="SURFACE", action_id="show_question_overlay",
        parameters={}, representative_text=payload, response_angle="angle",
        relevance=0.9, rationale="rationale",
    )
    decision = Decision(
        decision_id="d1", correlation_id="corr-1", proposal=proposal,
        score=0.9, score_breakdown={}, created_at=0.0, expires_at=100.0, expected_pre_state={},
        policy_result="allowed",
    )

    result = await orchestrator.execute(decision, action)
    assert result.status == "executed"
    # The exact payload string reaches OBS's native text-setting call,
    # completely unmodified — because there's no HTML parser downstream to
    # neutralize it against; OBS draws it as characters, not markup.
    assert provider.input_text["AI_Question_Text"] == payload
    assert provider.set_input_text_calls == [("AI_Question_Text", payload)]
