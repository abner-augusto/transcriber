import asyncio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from database import get_db
from models import Meeting
from jobs import subscribe

router = APIRouter()


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_websocket(websocket: WebSocket, meeting_id: str, db: Session = Depends(get_db)):
    # Validate meeting exists before accepting connection
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        await websocket.close(code=4004, reason="Meeting not found")
        return

    await websocket.accept()

    try:
        # Forward the configured progress stream without knowing its transport.
        async def relay():
            async for event in subscribe(meeting_id):
                await websocket.send_json(event)

        relay_task = asyncio.create_task(relay())

        # Keep connection alive, listen for client messages
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send ping to keep alive
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if "relay_task" in locals():
            relay_task.cancel()
