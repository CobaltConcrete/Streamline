"""Load non-secret YAML plus git-ignored environment credentials."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from codirector.config.models import AppConfig, PersonaConfig

_OBS_KEYRING_SERVICE = "codirector-obs"
_TWITCH_KEYRING_SERVICE = "codirector-twitch"


def load_environment(start: str | Path | None = None) -> Path | None:
    """Load the nearest project .env without overriding process variables."""
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate, override=False)
            return candidate
    return None


def load_app_config(path: str | Path) -> AppConfig:
    load_environment(Path(path))
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    twitch_channel = os.getenv("TWITCH_CHANNEL", "").strip()
    if twitch_channel:
        data.setdefault("twitch", {})["channel"] = twitch_channel.lstrip("#")
    ai_provider = os.getenv("AI_PROVIDER", "").strip().lower()
    if ai_provider:
        data.setdefault("reasoning", {})["provider"] = ai_provider
    timeout = os.getenv("AI_REQUEST_TIMEOUT_S", "").strip()
    if timeout:
        data.setdefault("reasoning", {})["timeout_s"] = float(timeout)
    return AppConfig.model_validate(data)


def load_persona(path: str | Path) -> PersonaConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return PersonaConfig.model_validate(data)


def get_obs_password() -> str | None:
    load_environment()
    from_env = os.getenv("OBS_WEBSOCKET_PASSWORD", "").strip()
    if from_env:
        return from_env
    import keyring

    return keyring.get_password(_OBS_KEYRING_SERVICE, "password")


def get_twitch_token() -> str | None:
    load_environment()
    from_env = os.getenv("TWITCH_USER_ACCESS_TOKEN", "").strip()
    if from_env:
        return from_env.removeprefix("oauth:")
    import keyring

    return keyring.get_password(_TWITCH_KEYRING_SERVICE, "oauth_token")
