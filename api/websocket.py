import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from jobs import sessions, subscribe
from models import Meeting

router = APIRouter()


def _meeting_exists(meeting_id: str) -> bool:
    # A short-lived session: the socket may stay open for hours.
    with sessions()() as db:
        return db.get(Meeting, meeting_id) is not None


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_websocket(websocket: WebSocket, meeting_id: str):
    if not _meeting_exists(meeting_id):
        await websocket.close(code=4004, reason="Meeting not found")
        return

    await websocket.accept()

    # Forward the configured progress stream without knowing its transport.
    async def relay():
        async for event in subscribe(meeting_id):
            await websocket.send_json(event)

    relay_task = asyncio.create_task(relay())
    try:
        # Keep the connection alive and listen for client messages.
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        relay_task.cancel()
