"""Interactive Twitch OAuth helper for the local Streamline installation.

The registered redirect uses HTTPS, but the app intentionally does not run a
local TLS callback server. After Twitch redirects, the browser may report that
localhost refused the connection; the callback URL in its address bar still
contains the short-lived authorization code. This helper validates that URL,
exchanges the code, and stores the resulting tokens in the git-ignored .env.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from dotenv import dotenv_values, set_key

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_REDIRECT_URI = "https://localhost:3000/"
AUTHORIZE_ENDPOINT = "https://id.twitch.tv/oauth2/authorize"
TOKEN_ENDPOINT = "https://id.twitch.tv/oauth2/token"
REQUIRED_SCOPE = "chat:read"


class TwitchOAuthError(RuntimeError):
    """Raised when Twitch OAuth input or output is invalid."""


def build_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": REQUIRED_SCOPE,
            "state": state,
            "force_verify": "true",
        }
    )
    return f"{AUTHORIZE_ENDPOINT}?{query}"


def _callback_location(url: str) -> tuple[str, str, int | None, str]:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") or "/"
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port, path


def extract_authorization_code(
    callback_url: str, *, expected_state: str, redirect_uri: str
) -> str:
    callback_url = callback_url.strip()
    if not callback_url:
        raise TwitchOAuthError("no callback URL was provided")
    if _callback_location(callback_url) != _callback_location(redirect_uri):
        raise TwitchOAuthError(
            f"callback does not match the configured redirect URI {redirect_uri!r}"
        )

    callback = urlsplit(callback_url)
    values = parse_qs(callback.query)
    if values.get("error"):
        detail = values.get("error_description", values["error"])[0]
        raise TwitchOAuthError(f"Twitch denied authorization: {detail}")
    if values.get("state", [None])[0] != expected_state:
        raise TwitchOAuthError("OAuth state mismatch; discard this callback and try again")

    code = values.get("code", [None])[0]
    if not code:
        raise TwitchOAuthError("callback URL does not contain an authorization code")
    return code


def exchange_authorization_code(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> dict[str, Any]:
    body = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Streamline-CoDirector/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            detail = error_payload.get("message") or error_payload.get("error")
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = None
        raise TwitchOAuthError(
            f"Twitch token exchange failed with HTTP {exc.code}"
            + (f": {detail}" if detail else "")
        ) from exc
    except urllib.error.URLError as exc:
        raise TwitchOAuthError(f"could not reach Twitch: {exc.reason}") from exc

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    scopes = payload.get("scope", [])
    if not isinstance(access_token, str) or not access_token:
        raise TwitchOAuthError("Twitch response did not contain an access token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise TwitchOAuthError("Twitch response did not contain a refresh token")
    if REQUIRED_SCOPE not in scopes:
        raise TwitchOAuthError(f"Twitch token is missing required scope {REQUIRED_SCOPE!r}")
    return payload


def store_tokens(env_file: Path, payload: dict[str, Any]) -> None:
    # python-dotenv updates only these entries and preserves the rest of .env.
    set_key(str(env_file), "TWITCH_USER_ACCESS_TOKEN", payload["access_token"], quote_mode="always")
    set_key(str(env_file), "TWITCH_REFRESH_TOKEN", payload["refresh_token"], quote_mode="always")


def _required_setting(settings: dict[str, Any], name: str) -> str:
    value = settings.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TwitchOAuthError(f"set {name} in the project .env before running this helper")
    return value.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Authorize Twitch chat access and update the project .env."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="dotenv file to read and update (default: repository-root .env)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="print the authorization URL without opening a browser",
    )
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="validate and print the authorization code without exchanging it",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> None:
    env_file = args.env_file.resolve()
    if not env_file.is_file():
        raise TwitchOAuthError(f"environment file not found: {env_file}")

    settings = dict(dotenv_values(env_file))
    client_id = _required_setting(settings, "TWITCH_CLIENT_ID")
    redirect_uri = str(settings.get("TWITCH_REDIRECT_URI") or DEFAULT_REDIRECT_URI).strip()
    state = secrets.token_urlsafe(32)
    authorization_url = build_authorization_url(client_id, redirect_uri, state)

    print(f"Using redirect URI: {redirect_uri}")
    print("Opening Twitch authorization in your default browser...")
    if args.no_open or not webbrowser.open_new_tab(authorization_url):
        print(f"Open this URL manually:\n{authorization_url}")
    print(
        "\nAfter authorizing, localhost may refuse to connect. "
        "Copy the FULL URL from the browser address bar."
    )
    callback_url = input("Paste the callback URL here: ")
    code = extract_authorization_code(
        callback_url, expected_state=state, redirect_uri=redirect_uri
    )
    print(f"Authorization code received: {code}")

    if args.code_only:
        print("Code-only mode: the short-lived code was not exchanged.")
        return

    client_secret = _required_setting(settings, "TWITCH_CLIENT_SECRET")
    payload = exchange_authorization_code(
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
    )
    store_tokens(env_file, payload)
    print(
        "OAuth succeeded. TWITCH_USER_ACCESS_TOKEN and TWITCH_REFRESH_TOKEN "
        f"were updated in {env_file}. Token values were not displayed."
    )


def main() -> None:
    try:
        run(parse_args())
    except (TwitchOAuthError, KeyboardInterrupt) as exc:
        message = str(exc) if str(exc) else "cancelled"
        print(f"Twitch OAuth failed: {message}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
