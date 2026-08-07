import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import twitch_oauth


def test_authorization_url_requests_read_only_chat_and_real_state():
    url = twitch_oauth.build_authorization_url(
        "client-id", "https://localhost:3000/", "random-state"
    )
    query = parse_qs(urlsplit(url).query)

    assert query == {
        "response_type": ["code"],
        "client_id": ["client-id"],
        "redirect_uri": ["https://localhost:3000/"],
        "scope": ["chat:read"],
        "state": ["random-state"],
        "force_verify": ["true"],
    }


def test_callback_code_is_extracted_only_when_redirect_and_state_match():
    code = twitch_oauth.extract_authorization_code(
        "https://localhost:3000/?code=one-time-code&state=expected",
        expected_state="expected",
        redirect_uri="https://localhost:3000/",
    )
    assert code == "one-time-code"


@pytest.mark.parametrize(
    ("callback", "message"),
    [
        ("https://localhost:3000/?code=x&state=wrong", "state mismatch"),
        ("https://localhost:4000/?code=x&state=expected", "does not match"),
        (
            "https://localhost:3000/?error=access_denied&state=expected",
            "denied authorization",
        ),
    ],
)
def test_invalid_callbacks_fail_closed(callback, message):
    with pytest.raises(twitch_oauth.TwitchOAuthError, match=message):
        twitch_oauth.extract_authorization_code(
            callback,
            expected_state="expected",
            redirect_uri="https://localhost:3000/",
        )


def test_store_tokens_updates_only_token_entries(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TWITCH_CLIENT_ID=public-id\n"
        "TWITCH_CLIENT_SECRET=private-secret\n"
        "TWITCH_USER_ACCESS_TOKEN=old\n"
        "TWITCH_REFRESH_TOKEN=old-refresh\n",
        encoding="utf-8",
    )

    twitch_oauth.store_tokens(
        env_file,
        {"access_token": "new-access", "refresh_token": "new-refresh"},
    )

    values = dotenv_values(env_file)
    assert values == {
        "TWITCH_CLIENT_ID": "public-id",
        "TWITCH_CLIENT_SECRET": "private-secret",
        "TWITCH_USER_ACCESS_TOKEN": "new-access",
        "TWITCH_REFRESH_TOKEN": "new-refresh",
    }
