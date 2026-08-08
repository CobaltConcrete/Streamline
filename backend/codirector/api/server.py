"""FastAPI app factory — build spec v1.0 D-1/D-5/D-6. Serves REST config +
the live WS event stream on 127.0.0.1; the React control center (built to
frontend/dist) is served as static files from the same origin so the whole
thing opens as one desktop browser window with no CORS to configure.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from codirector.adapters.reasoning.http import create_reasoning_provider
from codirector.adapters.twitch.client import create_twitch_adapter
from codirector.api.routes import router as api_router
from codirector.api.runtime import LiveChatRuntime
from codirector.api.state import AppState
from codirector.api.ws import router as ws_router
from codirector.config.loader import load_app_config, load_persona
from codirector.core.chat_filter import ChatCommentFilter
from codirector.core.clustering import Clusterer
from codirector.policy.catalog import load_catalog

# server.py -> api -> codirector -> backend -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def create_app(
    persona_path: Path | None = None,
    catalog_path: Path | None = None,
    *,
    enable_live_runtime: bool = False,
) -> FastAPI:
    persona = load_persona(persona_path or CONFIG_DIR / "personas" / "conversational.yaml")
    catalog = load_catalog(catalog_path or CONFIG_DIR / "action_catalog.yaml")
    config = load_app_config(CONFIG_DIR / "app.yaml")
    state = AppState(persona=persona, catalog=catalog)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = None
        if enable_live_runtime:
            try:
                runtime = LiveChatRuntime(
                    state=state,
                    twitch=create_twitch_adapter(config.twitch.channel),
                    reasoning=create_reasoning_provider(config.reasoning),
                    clusterer=Clusterer(cluster_ttl_s=config.pipeline.rolling_window_s),
                    chat_filter=ChatCommentFilter(
                        min_recognized_words=config.pipeline.chat_filter_min_recognized_words
                    ),
                    max_representative_texts=(
                        config.pipeline.chat_batch_max_representative_texts
                    ),
                    max_wait_s=config.pipeline.chat_batch_max_wait_s,
                )
                await runtime.start()
                app.state.live_runtime = runtime
            except Exception as exc:  # noqa: BLE001 - keep local dashboard available
                state.health["twitch"].status = "down"
                state.health["twitch"].detail = f"startup failed: {exc}"
                state.health["reasoning"].status = "down"
                state.health["reasoning"].detail = "runtime not started"
        yield
        if runtime is not None:
            await runtime.stop()

    app = FastAPI(title="AI Stream Co-Director", lifespan=lifespan)
    app.state.codirector = state
    app.include_router(api_router)
    app.include_router(ws_router)

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    return app


app = create_app(enable_live_runtime=True)


def main() -> None:
    import uvicorn

    # 127.0.0.1 only — D-1's "no game-process injection" pairing: the control
    # surface never listens beyond loopback.
    uvicorn.run(app, host="127.0.0.1", port=8756)


if __name__ == "__main__":
    main()
