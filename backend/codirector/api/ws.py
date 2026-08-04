"""Live event stream — build spec v1.0 §5.11/D-6. On connect the UI gets a
full snapshot, then a message per subsequent state change via
AppState.broadcast(). The client->server direction is unused (control
actions go through the REST routes) except as a keepalive ping.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from codirector.api.state import AppState

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    state: AppState = websocket.app.state.codirector
    await websocket.accept()
    state.register_websocket(websocket)
    try:
        await websocket.send_json(state.snapshot())
        while True:
            await websocket.receive_text()  # keepalive / ignored control channel
    except WebSocketDisconnect:
        pass
    finally:
        state.unregister_websocket(websocket)


@router.websocket("/ws/overlay")
async def ws_overlay_endpoint(websocket: WebSocket):
    """Feeds frontend/public/overlay.html only — R-SAF-06's bounded public
    surface, kept on its own endpoint/list rather than sharing /ws with the
    control center."""
    state: AppState = websocket.app.state.codirector
    await websocket.accept()
    state.register_overlay_websocket(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.unregister_overlay_websocket(websocket)
