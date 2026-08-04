"""FastAPI app factory — build spec v1.0 D-1/D-5/D-6. Serves REST config +
the live WS event stream on 127.0.0.1; the React control center (built to
frontend/dist) is served as static files from the same origin so the whole
thing opens as one desktop browser window with no CORS to configure.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from codirector.api.routes import router as api_router
from codirector.api.state import AppState
from codirector.api.ws import router as ws_router
from codirector.config.loader import load_persona
from codirector.policy.catalog import load_catalog

# server.py -> api -> codirector -> backend -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def create_app(persona_path: Path | None = None, catalog_path: Path | None = None) -> FastAPI:
    persona = load_persona(persona_path or CONFIG_DIR / "personas" / "conversational.yaml")
    catalog = load_catalog(catalog_path or CONFIG_DIR / "action_catalog.yaml")

    app = FastAPI(title="AI Stream Co-Director")
    app.state.codirector = AppState(persona=persona, catalog=catalog)
    app.include_router(api_router)
    app.include_router(ws_router)

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    # 127.0.0.1 only — D-1's "no game-process injection" pairing: the control
    # surface never listens beyond loopback.
    uvicorn.run(app, host="127.0.0.1", port=8756)


if __name__ == "__main__":
    main()
