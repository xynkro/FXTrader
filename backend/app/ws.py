"""WebSocket endpoint that pushes engine status snapshots every 2s."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .trader import engine


router = APIRouter()


@router.websocket("/ws")
async def ws_status(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            payload = engine.status().model_dump(mode="json")
            await ws.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    except Exception:
        await ws.close()
