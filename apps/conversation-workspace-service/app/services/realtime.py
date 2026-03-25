from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConversationRealtimeManager:
    def __init__(self) -> None:
        self._connections: dict[tuple[int, str], list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, *, family_id: int, conversation_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[(family_id, conversation_id)].append(websocket)

    async def disconnect(self, *, family_id: int, conversation_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            bucket = self._connections.get((family_id, conversation_id), [])
            if websocket in bucket:
                bucket.remove(websocket)
            if not bucket and (family_id, conversation_id) in self._connections:
                del self._connections[(family_id, conversation_id)]

    async def broadcast(self, *, family_id: int, conversation_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._connections.get((family_id, conversation_id), []))
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(family_id=family_id, conversation_id=conversation_id, websocket=websocket)


realtime_manager = ConversationRealtimeManager()
