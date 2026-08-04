"""Synthetic chat harness — build spec v1.0 §8.3. Generates chat (and
optionally support events) into the pipeline at a configurable rate, for
demoing clustering/scoring/queue behaviour when the real stream has too few
viewers to exercise them (§7 M7's stated reason this exists at all).

R-TST-01: refuses to run when app.yaml's `environment` is "production" —
this is a demo/rehearsal tool, never a production data source.
Every event it produces is tagged (display_name prefixed "harness:") so the
audit log can tell synthetic activity apart from real chat at a glance.
"""
import argparse
import asyncio
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codirector.config.loader import load_app_config
from codirector.core.events import ChatMessageEvent, SupportEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

SYNTHETIC_PREFIX = "harness:"

_SAMPLE_MESSAGES = [
    "what keyboard do you use", "LOL", "poggers", "gg", "clip that",
    "what's your setup", "nice play", "kekw", "first time here", "monkaS",
]


def _refuse_if_production() -> None:
    cfg = load_app_config(CONFIG_DIR / "app.yaml")
    if cfg.environment == "production":
        raise SystemExit("chat_harness refuses to run: app.yaml environment == production (R-TST-01)")


def make_synthetic_chat_event(now: float, user_index: int) -> ChatMessageEvent:
    user_id = f"harness_user_{user_index}"
    return ChatMessageEvent(
        event_id=f"{SYNTHETIC_PREFIX}{uuid.uuid4()}",
        event_time=now,
        ingest_time=now,
        wall_time=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        trust="viewer",
        user_id=user_id,
        display_name=f"{SYNTHETIC_PREFIX}{user_id}",
        text=random.choice(_SAMPLE_MESSAGES),
    )


def make_synthetic_raid(now: float, viewers: int = 50) -> SupportEvent:
    return SupportEvent(
        event_id=f"{SYNTHETIC_PREFIX}{uuid.uuid4()}",
        event_time=now,
        ingest_time=now,
        wall_time=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        trust="platform_verified",
        type="support.raid",
        user_id="harness_raider",
        display_name=f"{SYNTHETIC_PREFIX}raider",
        message=None,
        amount=viewers,
    )


async def run(rate_per_min: int, duration_s: float) -> None:
    _refuse_if_production()
    interval_s = 60.0 / rate_per_min
    start = time.monotonic()
    count = 0
    print(f"chat_harness: injecting ~{rate_per_min} synthetic events/min for {duration_s:.0f}s "
          f"(all tagged {SYNTHETIC_PREFIX!r})")
    while time.monotonic() - start < duration_s:
        now = time.monotonic()
        event = make_synthetic_chat_event(now, user_index=count % 200)
        print(f"  [{now - start:6.1f}s] {event.display_name}: {event.text}")
        count += 1
        await asyncio.sleep(interval_s)
    print(f"chat_harness: done, injected {count} synthetic events")


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic chat harness (§8.3) — demo/rehearsal only")
    parser.add_argument("--rate", type=int, default=60, help="synthetic events per minute")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to run")
    parser.add_argument("--raid", action="store_true", help="fire one synthetic raid and exit")
    args = parser.parse_args()

    _refuse_if_production()
    if args.raid:
        event = make_synthetic_raid(now=time.monotonic())
        print(f"synthetic raid: {event.display_name} brought {event.amount} viewers")
        return

    asyncio.run(run(args.rate, args.duration))


if __name__ == "__main__":
    main()
