import asyncio
import json
from collections.abc import Awaitable, Callable

import redis.asyncio as redis

from app.config import get_settings


class RedisBus:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client: redis.Redis | None = None
        self.pubsub = None
        self.listener_task: asyncio.Task | None = None
        self.available = False

    async def connect(self) -> None:
        try:
            self.client = redis.from_url(self.settings.redis_url, decode_responses=True)
            await self.client.ping()
            self.pubsub = self.client.pubsub()
            await self.pubsub.subscribe("chat-events")
            self.available = True
        except Exception:
            self.available = False

    async def publish(self, payload: dict) -> None:
        if not self.available or self.client is None:
            return
        await self.client.publish("chat-events", json.dumps(payload, default=str))

    async def listen(self, handler: Callable[[dict], Awaitable[None]]) -> None:
        if not self.available or self.pubsub is None:
            return
        async for message in self.pubsub.listen():
            if message["type"] != "message":
                continue
            await handler(json.loads(message["data"]))

    async def close(self) -> None:
        if self.listener_task:
            self.listener_task.cancel()
        if self.pubsub:
            await self.pubsub.unsubscribe("chat-events")
            await self.pubsub.close()
        if self.client:
            await self.client.aclose()


redis_bus = RedisBus()
