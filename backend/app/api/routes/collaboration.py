from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import certifi
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis


router = APIRouter()
logger = logging.getLogger(__name__)

PRESENCE_HASH_KEY = "collab:presence:users"
PRESENCE_ACTIVITY_KEY = "collab:presence:activity"
PRESENCE_CHANNEL = "collab:presence:events"
STALE_AFTER_SECONDS = 120
INSTANCE_ID = uuid.uuid4().hex
CURSOR_SNAPSHOT_INTERVAL_SECONDS = 0.75


@dataclass
class Participant:
    id: str
    name: str
    color: str
    x: float
    y: float
    updated_at: float


class PresenceStore(Protocol):
    label: str

    async def snapshot(self) -> list[dict[str, Any]]:
        ...

    async def upsert(self, participant: Participant) -> None:
        ...

    async def remove(self, participant_id: str) -> None:
        ...

    async def publish(self, event: dict[str, Any]) -> None:
        ...

    async def start_listener(self, on_event: Any) -> None:
        ...


class InMemoryPresenceStore:
    label = "memory"

    def __init__(self) -> None:
        self.participants: dict[str, Participant] = {}
        self.lock = asyncio.Lock()

    async def snapshot(self) -> list[dict[str, Any]]:
        async with self.lock:
            self.prune_stale()
            return [serialize_user(user) for user in self.participants.values()]

    async def upsert(self, participant: Participant) -> None:
        async with self.lock:
            self.participants[participant.id] = participant

    async def remove(self, participant_id: str) -> None:
        async with self.lock:
            self.participants.pop(participant_id, None)

    async def publish(self, event: dict[str, Any]) -> None:
        return None

    async def start_listener(self, on_event: Any) -> None:
        return None

    def prune_stale(self) -> None:
        cutoff = time.time() - STALE_AFTER_SECONDS
        stale_ids = [user_id for user_id, user in self.participants.items() if user.updated_at < cutoff]
        for user_id in stale_ids:
            self.participants.pop(user_id, None)


class RedisPresenceStore:
    label = "redis"

    def __init__(self, redis_url: str) -> None:
        kwargs: dict[str, Any] = {"decode_responses": True}
        if redis_url.startswith("rediss://"):
            kwargs["ssl_ca_certs"] = certifi.where()

        self.redis = Redis.from_url(redis_url, **kwargs)
        self.listener_lock = asyncio.Lock()
        self.listener_started = False

    async def connect(self) -> None:
        await self.redis.ping()

    async def snapshot(self) -> list[dict[str, Any]]:
        await self.prune_stale()
        return [json.loads(user) for user in await self.redis.hvals(PRESENCE_HASH_KEY)]

    async def upsert(self, participant: Participant) -> None:
        payload = json.dumps(serialize_user(participant))
        pipe = self.redis.pipeline()
        pipe.hset(PRESENCE_HASH_KEY, participant.id, payload)
        pipe.zadd(PRESENCE_ACTIVITY_KEY, {participant.id: participant.updated_at})
        pipe.expire(PRESENCE_HASH_KEY, STALE_AFTER_SECONDS * 4)
        pipe.expire(PRESENCE_ACTIVITY_KEY, STALE_AFTER_SECONDS * 4)
        await pipe.execute()

    async def remove(self, participant_id: str) -> None:
        pipe = self.redis.pipeline()
        pipe.hdel(PRESENCE_HASH_KEY, participant_id)
        pipe.zrem(PRESENCE_ACTIVITY_KEY, participant_id)
        await pipe.execute()

    async def publish(self, event: dict[str, Any]) -> None:
        await self.redis.publish(PRESENCE_CHANNEL, json.dumps({"origin": INSTANCE_ID, "event": event}))

    async def start_listener(self, on_event: Any) -> None:
        async with self.listener_lock:
            if self.listener_started:
                return

            self.listener_started = True
            asyncio.create_task(self.listen(on_event))

    async def listen(self, on_event: Any) -> None:
        while True:
            try:
                pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe(PRESENCE_CHANNEL)

                async for message in pubsub.listen():
                    payload = parse_message(message.get("data"))
                    if not payload or payload.get("origin") == INSTANCE_ID:
                        continue

                    event = payload.get("event")
                    if isinstance(event, dict):
                        await on_event(event)
            except Exception:
                logger.exception("Redis pub/sub listener failed; reconnecting")
                await asyncio.sleep(1)

    async def prune_stale(self) -> None:
        cutoff = time.time() - STALE_AFTER_SECONDS
        stale_ids = await self.redis.zrangebyscore(PRESENCE_ACTIVITY_KEY, "-inf", cutoff)
        if not stale_ids:
            return

        pipe = self.redis.pipeline()
        pipe.hdel(PRESENCE_HASH_KEY, *stale_ids)
        pipe.zrem(PRESENCE_ACTIVITY_KEY, *stale_ids)
        await pipe.execute()


clients: dict[str, WebSocket] = {}
clients_lock = asyncio.Lock()
cursor_snapshot_tasks: dict[str, asyncio.Task[None]] = {}
cursor_snapshot_lock = asyncio.Lock()
store: PresenceStore | None = None
store_lock = asyncio.Lock()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    presence_store = await get_store()
    await presence_store.start_listener(handle_remote_event)

    participant = Participant(
        id=clean_text(websocket.query_params.get("id"), fallback=f"user-{time.time_ns()}"),
        name=clean_text(websocket.query_params.get("name"), fallback="Visitor"),
        color=clean_color(websocket.query_params.get("color"), fallback="#2563eb"),
        x=0.5,
        y=0.5,
        updated_at=time.time(),
    )

    async with clients_lock:
        clients[participant.id] = websocket

    await presence_store.upsert(participant)

    try:
        await websocket.send_json(
            {
                "type": "snapshot",
                "selfId": participant.id,
                "users": await presence_store.snapshot(),
                "stateStore": presence_store.label,
            }
        )
        await announce({"type": "presence", "user": serialize_user(participant)}, skip_id=participant.id)

        while True:
            message = parse_message(await websocket.receive_text())
            if not message:
                continue

            if message.get("type") == "hello":
                participant.name = clean_text(message.get("name"), fallback=participant.name)
                participant.color = clean_color(message.get("color"), fallback=participant.color)
                participant.updated_at = time.time()
                await presence_store.upsert(participant)
                await announce({"type": "presence", "user": serialize_user(participant)})

            if message.get("type") == "cursor":
                participant.x = clamp_float(message.get("x"), fallback=participant.x)
                participant.y = clamp_float(message.get("y"), fallback=participant.y)
                participant.updated_at = time.time()
                await announce_realtime(
                    presence_store,
                    {"type": "cursor", "user": serialize_user(participant)},
                    skip_id=participant.id,
                )
                await schedule_cursor_snapshot(presence_store, participant)
    except WebSocketDisconnect:
        pass
    finally:
        async with clients_lock:
            clients.pop(participant.id, None)

        await cancel_cursor_snapshot(participant.id)
        await presence_store.remove(participant.id)
        await announce({"type": "leave", "id": participant.id})


@router.get("/api/presence")
async def presence_snapshot():
    presence_store = await get_store()
    users = await presence_store.snapshot()

    return {"stateStore": presence_store.label, "users": users, "total": len(users)}


async def get_store() -> PresenceStore:
    global store

    async with store_lock:
        if store is not None:
            return store

        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            redis_store = RedisPresenceStore(redis_url)
            await redis_store.connect()
            store = redis_store
        else:
            store = InMemoryPresenceStore()

        logger.info("Collaboration persistence backend: %s", store.label)
        return store


async def announce(payload: dict[str, Any], skip_id: str | None = None) -> None:
    await broadcast(payload, skip_id=skip_id)
    await (await get_store()).publish(payload)


async def announce_realtime(presence_store: PresenceStore, payload: dict[str, Any], skip_id: str | None = None) -> None:
    await broadcast(payload, skip_id=skip_id)
    schedule_background(presence_store.publish(payload), "publish realtime cursor event")


async def handle_remote_event(payload: dict[str, Any]) -> None:
    await broadcast(payload)


async def broadcast(payload: dict[str, Any], skip_id: str | None = None) -> None:
    stale_client_ids: list[str] = []

    async with clients_lock:
        active_clients = list(clients.items())

    for participant_id, websocket in active_clients:
        if participant_id == skip_id:
            continue

        try:
            await websocket.send_json(payload)
        except Exception:
            stale_client_ids.append(participant_id)

    if stale_client_ids:
        async with clients_lock:
            for participant_id in stale_client_ids:
                clients.pop(participant_id, None)


async def schedule_cursor_snapshot(presence_store: PresenceStore, participant: Participant) -> None:
    if presence_store.label == "memory":
        return

    async with cursor_snapshot_lock:
        task = cursor_snapshot_tasks.get(participant.id)
        if task and not task.done():
            return

        cursor_snapshot_tasks[participant.id] = schedule_background(
            persist_cursor_snapshot(presence_store, participant),
            "persist throttled cursor snapshot",
        )


async def persist_cursor_snapshot(presence_store: PresenceStore, participant: Participant) -> None:
    try:
        await asyncio.sleep(CURSOR_SNAPSHOT_INTERVAL_SECONDS)
        await presence_store.upsert(participant)
    finally:
        current_task = asyncio.current_task()
        async with cursor_snapshot_lock:
            if cursor_snapshot_tasks.get(participant.id) is current_task:
                cursor_snapshot_tasks.pop(participant.id, None)


async def cancel_cursor_snapshot(participant_id: str) -> None:
    async with cursor_snapshot_lock:
        task = cursor_snapshot_tasks.pop(participant_id, None)

    if task:
        task.cancel()


def schedule_background(coro: Any, description: str) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)

    def log_error(completed_task: asyncio.Task[None]) -> None:
        if completed_task.cancelled():
            return

        error = completed_task.exception()
        if error:
            logger.error(
                "Background collaboration task failed: %s",
                description,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(log_error)
    return task


def parse_message(raw_message: Any) -> dict[str, Any] | None:
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8")

    if not isinstance(raw_message, str):
        return None

    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError:
        return None

    return message if isinstance(message, dict) else None


def serialize_user(participant: Participant) -> dict[str, Any]:
    payload = asdict(participant)
    payload["updatedAt"] = payload.pop("updated_at")
    return payload


def clean_text(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback

    cleaned = value.strip()[:40]
    return cleaned or fallback


def clean_color(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback

    value = value.strip()
    is_hex = len(value) == 7 and value.startswith("#")
    if is_hex and all(char in "0123456789abcdefABCDEF" for char in value[1:]):
        return value

    return fallback


def clamp_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback

    return min(max(number, 0), 1)
