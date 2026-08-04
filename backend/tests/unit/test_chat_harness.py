"""R-TST-01: the synthetic chat harness refuses to run when
app.yaml's environment is production, and every event it produces is tagged
so it's distinguishable from real chat."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import chat_harness

from codirector.config.models import AppConfig


def _config(environment: str) -> AppConfig:
    return AppConfig.model_validate(
        {"twitch": {"channel": "x"}, "environment": environment}
    )


def test_refuses_in_production():
    with (
        patch("chat_harness.load_app_config", return_value=_config("production")),
        pytest.raises(SystemExit),
    ):
        chat_harness._refuse_if_production()


def test_allows_in_development():
    with patch("chat_harness.load_app_config", return_value=_config("development")):
        chat_harness._refuse_if_production()  # does not raise


def test_synthetic_events_are_tagged():
    event = chat_harness.make_synthetic_chat_event(now=0.0, user_index=1)
    assert event.event_id.startswith(chat_harness.SYNTHETIC_PREFIX)
    assert event.display_name.startswith(chat_harness.SYNTHETIC_PREFIX)

    raid = chat_harness.make_synthetic_raid(now=0.0)
    assert raid.event_id.startswith(chat_harness.SYNTHETIC_PREFIX)
    assert raid.display_name.startswith(chat_harness.SYNTHETIC_PREFIX)
