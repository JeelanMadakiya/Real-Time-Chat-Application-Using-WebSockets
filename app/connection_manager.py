import json
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, username: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[username].add(websocket)

    def disconnect(self, username: str, websocket: WebSocket) -> None:
        self.active_connections[username].discard(websocket)
        if not self.active_connections[username]:
            self.active_connections.pop(username, None)

    def is_online(self, username: str) -> bool:
        return username in self.active_connections

    async def send_to_user(self, username: str, payload: dict) -> None:
        data = json.dumps(payload, default=str)
        dead_connections = []
        for websocket in self.active_connections.get(username, set()):
            try:
                await websocket.send_text(data)
            except RuntimeError:
                dead_connections.append(websocket)
        for websocket in dead_connections:
            self.active_connections[username].discard(websocket)

    async def broadcast_users(self, usernames: list[str], payload: dict) -> None:
        for username in usernames:
            await self.send_to_user(username, payload)


manager = ConnectionManager()
