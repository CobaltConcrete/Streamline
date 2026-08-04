"""M1 exit criterion: a CLI command that executes one allowlisted overlay
update through the full PolicyEngine -> OBSOrchestrator path, and shows an
unlisted action being rejected with its rule ID.

Usage:
    python -m codirector.cli --mock demo-action
    python -m codirector.cli demo-action   # requires a live OBS on 127.0.0.1:4455

--mock swaps in MockOBSProvider so this is runnable without a live OBS Studio
instance (e.g. in this sandboxed dev environment, which has no OBS install).
The code path through PolicyEngine/OBSOrchestrator is identical either way —
only the provider differs.
"""
import argparse
import asyncio
import os
import time
from pathlib import Path

from codirector.adapters.obs.client import OBSAdapter
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.config.loader import (
    get_obs_password,
    get_twitch_token,
    load_app_config,
    load_environment,
)
from codirector.core.autonomy import AutonomyLevel
from codirector.core.clustering import Clusterer, eligible_clusters
from codirector.core.events import ChatMessageEvent
from codirector.core.models import Cluster
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import KnownOBSTargets, load_catalog, resolve_targets
from codirector.policy.engine import PolicyEngine

# cli.py -> codirector -> backend -> repository root
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


async def _build_provider(use_mock: bool):
    if use_mock:
        provider = MockOBSProvider(scenes=["Gameplay", "BRB"], program_scene="Gameplay")
        await provider.connect()
        return provider
    cfg = load_app_config(CONFIG_DIR / "app.yaml")
    provider = OBSAdapter(host=cfg.obs.host, port=cfg.obs.port, password=get_obs_password())
    await provider.connect()
    return provider


async def demo_action(use_mock: bool) -> None:
    provider = await _build_provider(use_mock)
    catalog = load_catalog(CONFIG_DIR / "action_catalog.yaml")

    state = await provider.get_state()
    known = KnownOBSTargets(scenes=set(state.scenes), inputs=set(provider.list_inputs()))
    warnings = resolve_targets(catalog, known)
    for w in warnings:
        print(f"[warn] {w}")

    orchestrator = OBSOrchestrator(provider)
    engine = PolicyEngine(orchestrator)
    persona = _default_persona()
    cluster = Cluster(
        cluster_id="demo-cluster",
        kind="question",
        representative_text="This is a demo overlay message from the M1 CLI.",
        member_event_ids=["e1"],
        unique_user_ids={"u1", "u2", "u3"},
        first_seen=0.0,
        last_seen=0.0,
        novelty=0.8,
    )
    now = time.monotonic()

    print("\n--- Attempt 1: allowlisted action (show_question_overlay) ---")
    decision = await engine.evaluate(
        raw_proposal={
            "cluster_id": "demo-cluster",
            "decision_type": "SURFACE",
            "action_id": "show_question_overlay",
            "parameters": {},
            "representative_text": cluster.representative_text,
            "response_angle": "demo",
            "relevance": 0.9,
            "rationale": "CLI demo of an allowlisted overlay action",
        },
        cluster=cluster,
        persona=persona,
        autonomy=AutonomyLevel.CO_DIRECT,
        catalog=catalog,
        live_obs_state={"program_scene": state.program_scene},
        now=now,
        score=0.9,
        score_breakdown={"relevance": 0.9},
        expires_at=now + 20,
        expected_pre_state={"program_scene": state.program_scene},
        correlation_id="cli-demo-1",
    )
    print(f"policy_result={decision.policy_result} rule_id={decision.policy_rule_id}")
    if decision.decision_id in engine.execution_results:
        print(f"execution={engine.execution_results[decision.decision_id]}")

    print("\n--- Attempt 2: action not in the catalog (must be rejected) ---")
    decision2 = await engine.evaluate(
        raw_proposal={
            "cluster_id": "demo-cluster",
            "decision_type": "SURFACE",
            "action_id": "start_stream",  # never catalogued — high-risk, §9
            "parameters": {},
            "representative_text": cluster.representative_text,
            "response_angle": "demo",
            "relevance": 0.9,
            "rationale": "CLI demo of a rejected, non-catalogued action",
        },
        cluster=cluster,
        persona=persona,
        autonomy=AutonomyLevel.CO_DIRECT,
        catalog=catalog,
        live_obs_state={"program_scene": state.program_scene},
        now=now,
        score=0.9,
        score_breakdown={"relevance": 0.9},
        expires_at=now + 20,
        expected_pre_state={"program_scene": state.program_scene},
        correlation_id="cli-demo-2",
    )
    print(f"policy_result={decision2.policy_result} rule_id={decision2.policy_rule_id}")
    assert decision2.policy_result == "rejected" and decision2.policy_rule_id == "2"
    print("\nOK: unlisted action correctly rejected with rule_id=2 (action_exists).")


def _default_persona():
    from codirector.config.loader import load_persona

    return load_persona(CONFIG_DIR / "personas" / "conversational.yaml")


def demo_clustering() -> None:
    """M2 exit criterion: "Live chat produces correct clusters printed to
    console at 2000 events/min." Replays tests/fixtures/chat_burst_2000.json
    (one minute of chat at that load) through the Clusterer and reports
    timing plus the resulting cluster breakdown."""
    import json

    raw = json.loads((FIXTURES_DIR / "chat_burst_2000.json").read_text(encoding="utf-8"))
    events = [ChatMessageEvent.model_validate(e) for e in raw]

    clusterer = Clusterer()
    start = time.perf_counter()
    for event in events:
        clusterer.add_message(event, now=event.event_time)
    elapsed = time.perf_counter() - start

    clusters = clusterer.clusters()
    print(f"Processed {len(events)} chat events (2000/min load) in {elapsed * 1000:.1f} ms")
    print(f"Collapsed into {len(clusters)} clusters; {len(eligible_clusters(clusters))} eligible for surfacing")
    for c in sorted(clusters, key=lambda c: -len(c.unique_user_ids))[:5]:
        print(f"  [{len(c.unique_user_ids)} users] {c.kind}: {c.representative_text!r}")


def check_config() -> None:
    """Report integration readiness without printing any credential value."""
    from urllib.parse import urlsplit

    from codirector.adapters.reasoning.http import MissingAIProviderError, resolve_ai_provider

    load_environment(CONFIG_DIR)
    config = load_app_config(CONFIG_DIR / "app.yaml")
    print("Integration configuration (secret values are never displayed)")
    try:
        settings = resolve_ai_provider(requested=config.reasoning.provider)
        endpoint_host = urlsplit(settings.endpoint).netloc
        print(f"  AI: ready ({settings.name}, model={settings.model}, host={endpoint_host})")
    except MissingAIProviderError as exc:
        print(f"  AI: not ready ({exc})")

    token_ready = bool(get_twitch_token())
    channel_ready = bool(config.twitch.channel and config.twitch.channel != "your_channel")
    print(
        f"  Twitch: {'ready' if token_ready and channel_ready else 'not ready'} "
        f"(channel={config.twitch.channel!r}, user_token={'set' if token_ready else 'missing'})"
    )
    client_id_ready = bool(os.getenv("TWITCH_CLIENT_ID", "").strip())
    refresh_ready = bool(os.getenv("TWITCH_REFRESH_TOKEN", "").strip())
    print(
        "  Twitch OAuth renewal metadata: "
        f"client_id={'set' if client_id_ready else 'missing'}, "
        f"refresh_token={'set' if refresh_ready else 'missing'}"
    )
    print(f"  OBS WebSocket password: {'set' if get_obs_password() else 'missing'}")


async def listen_twitch() -> None:
    """Read Twitch chat and print schema-validated AI proposals.

    This is deliberately read-only: it has no Twitch write scope/path and does
    not touch OBS. It is the smallest real integration smoke test for the
    .env-backed Twitch + AI provider path while the full app runtime remains a
    separate milestone.
    """
    from codirector.adapters.base import ReasoningPrompt
    from codirector.adapters.reasoning.http import create_reasoning_provider
    from codirector.adapters.twitch.client import create_twitch_adapter
    from codirector.core.events import SupportEvent

    config = load_app_config(CONFIG_DIR / "app.yaml")
    reasoning = create_reasoning_provider(config.reasoning)
    twitch = create_twitch_adapter(config.twitch.channel)
    clusterer = Clusterer(cluster_ttl_s=config.pipeline.rolling_window_s)
    persona = _default_persona().model_dump()
    analyzed_clusters: set[str] = set()

    await twitch.connect()
    print(
        f"Listening to #{config.twitch.channel} with "
        f"{getattr(reasoning, 'settings', None).name if hasattr(reasoning, 'settings') else config.reasoning.provider}. "
        "Press Ctrl+C to stop."
    )
    try:
        async for event in twitch.events():
            now = time.monotonic()
            if isinstance(event, SupportEvent):
                cluster = clusterer.add_support_event(event, now)
            else:
                cluster = clusterer.add_message(event, now)
                if len(cluster.unique_user_ids) < 3:
                    continue
            if cluster.cluster_id in analyzed_clusters:
                continue
            analyzed_clusters.add(cluster.cluster_id)
            prompt = ReasoningPrompt(
                session_summary="",
                cluster_context=[
                    {
                        "cluster_id": cluster.cluster_id,
                        "kind": cluster.kind,
                        "unique_user_count": len(cluster.unique_user_ids),
                        "representative_text": cluster.representative_text,
                    }
                ],
                persona=persona,
            )
            response = await reasoning.propose(prompt)
            for proposal in response.proposals:
                print(proposal.model_dump_json())
    finally:
        await twitch.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Stream Co-Director demo CLI")
    parser.add_argument("--mock", action="store_true", help="use MockOBSProvider instead of a live OBS connection")
    parser.add_argument(
        "command",
        choices=["demo-action", "demo-clustering", "check-config", "listen-twitch"],
    )
    args = parser.parse_args()

    if args.command == "demo-action":
        asyncio.run(demo_action(args.mock))
    elif args.command == "demo-clustering":
        demo_clustering()
    elif args.command == "check-config":
        check_config()
    elif args.command == "listen-twitch":
        try:
            asyncio.run(listen_twitch())
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    main()
