from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from flask import Blueprint, jsonify, request
from flask_sock import Sock
from redis import Redis


bp = Blueprint("collaboration", __name__)

PRESENCE_HASH_KEY = "collab:presence:users"
PRESENCE_ACTIVITY_KEY = "collab:presence:activity"
PRESENCE_CHANNEL = "collab:presence:events"
STALE_AFTER_SECONDS = 120
INSTANCE_ID = uuid.uuid4().hex


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

    def snapshot(self) -> list[dict[str, Any]]:
        ...

    def upsert(self, participant: Participant) -> None:
        ...

    def remove(self, participant_id: str) -> None:
        ...

    def publish(self, event: dict[str, Any]) -> None:
        ...

    def start_listener(self, on_event: Any) -> None:
        ...


class InMemoryPresenceStore:
    label = "memory"

    def __init__(self) -> None:
        self.participants: dict[str, Participant] = {}
        self.lock = threading.Lock()

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            self.prune_stale()
            return [serialize_user(user) for user in self.participants.values()]

    def upsert(self, participant: Participant) -> None:
        with self.lock:
            self.participants[participant.id] = participant

    def remove(self, participant_id: str) -> None:
        with self.lock:
            self.participants.pop(participant_id, None)

    def publish(self, event: dict[str, Any]) -> None:
        return None

    def start_listener(self, on_event: Any) -> None:
        return None

    def prune_stale(self) -> None:
        cutoff = time.time() - STALE_AFTER_SECONDS
        stale_ids = [user_id for user_id, user in self.participants.items() if user.updated_at < cutoff]
        for user_id in stale_ids:
            self.participants.pop(user_id, None)


class RedisPresenceStore:
    label = "redis"

    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.redis.ping()
        self.listener_lock = threading.Lock()
        self.listener_started = False

    def snapshot(self) -> list[dict[str, Any]]:
        self.prune_stale()
        return [json.loads(user) for user in self.redis.hvals(PRESENCE_HASH_KEY)]

    def upsert(self, participant: Participant) -> None:
        payload = json.dumps(serialize_user(participant))
        pipe = self.redis.pipeline()
        pipe.hset(PRESENCE_HASH_KEY, participant.id, payload)
        pipe.zadd(PRESENCE_ACTIVITY_KEY, {participant.id: participant.updated_at})
        pipe.expire(PRESENCE_HASH_KEY, STALE_AFTER_SECONDS * 4)
        pipe.expire(PRESENCE_ACTIVITY_KEY, STALE_AFTER_SECONDS * 4)
        pipe.execute()

    def remove(self, participant_id: str) -> None:
        pipe = self.redis.pipeline()
        pipe.hdel(PRESENCE_HASH_KEY, participant_id)
        pipe.zrem(PRESENCE_ACTIVITY_KEY, participant_id)
        pipe.execute()

    def publish(self, event: dict[str, Any]) -> None:
        self.redis.publish(PRESENCE_CHANNEL, json.dumps({"origin": INSTANCE_ID, "event": event}))

    def start_listener(self, on_event: Any) -> None:
        with self.listener_lock:
            if self.listener_started:
                return

            self.listener_started = True
            thread = threading.Thread(target=self.listen, args=(on_event,), daemon=True)
            thread.start()

    def listen(self, on_event: Any) -> None:
        while True:
            try:
                pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(PRESENCE_CHANNEL)

                for message in pubsub.listen():
                    payload = parse_message(message.get("data"))
                    if not payload or payload.get("origin") == INSTANCE_ID:
                        continue

                    event = payload.get("event")
                    if isinstance(event, dict):
                        on_event(event)
            except Exception:
                time.sleep(1)

    def prune_stale(self) -> None:
        cutoff = time.time() - STALE_AFTER_SECONDS
        stale_ids = self.redis.zrangebyscore(PRESENCE_ACTIVITY_KEY, "-inf", cutoff)
        if not stale_ids:
            return

        pipe = self.redis.pipeline()
        pipe.hdel(PRESENCE_HASH_KEY, *stale_ids)
        pipe.zrem(PRESENCE_ACTIVITY_KEY, *stale_ids)
        pipe.execute()


clients: dict[str, Any] = {}
clients_lock = threading.Lock()
store: PresenceStore | None = None
store_lock = threading.Lock()


def register_socket(sock: Sock) -> None:
    get_store().start_listener(handle_remote_event)

    @sock.route("/ws")
    def websocket(ws):
        presence_store = get_store()
        participant = Participant(
            id=clean_text(request.args.get("id"), fallback=f"user-{time.time_ns()}"),
            name=clean_text(request.args.get("name"), fallback="Visitor"),
            color=clean_color(request.args.get("color"), fallback="#2563eb"),
            x=0.5,
            y=0.5,
            updated_at=time.time(),
        )

        with clients_lock:
            clients[participant.id] = ws

        presence_store.upsert(participant)
        send_json(
            ws,
            {
                "type": "snapshot",
                "selfId": participant.id,
                "users": presence_store.snapshot(),
                "stateStore": presence_store.label,
            },
        )
        announce({"type": "presence", "user": serialize_user(participant)}, skip_id=participant.id)

        try:
            while True:
                raw_message = ws.receive()
                if raw_message is None:
                    break

                message = parse_message(raw_message)
                if not message:
                    continue

                if message.get("type") == "hello":
                    participant.name = clean_text(message.get("name"), fallback=participant.name)
                    participant.color = clean_color(message.get("color"), fallback=participant.color)
                    participant.updated_at = time.time()
                    presence_store.upsert(participant)
                    announce({"type": "presence", "user": serialize_user(participant)})

                if message.get("type") == "cursor":
                    participant.x = clamp_float(message.get("x"), fallback=participant.x)
                    participant.y = clamp_float(message.get("y"), fallback=participant.y)
                    participant.updated_at = time.time()
                    presence_store.upsert(participant)
                    announce({"type": "cursor", "user": serialize_user(participant)}, skip_id=participant.id)
        finally:
            with clients_lock:
                clients.pop(participant.id, None)

            presence_store.remove(participant.id)
            announce({"type": "leave", "id": participant.id})


@bp.get("/api/presence")
def presence_snapshot():
    presence_store = get_store()
    users = presence_store.snapshot()

    return jsonify({"stateStore": presence_store.label, "users": users, "total": len(users)})


def get_store() -> PresenceStore:
    global store

    with store_lock:
        if store is not None:
            return store

        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            store = RedisPresenceStore(redis_url)
        else:
            store = InMemoryPresenceStore()

        return store


def announce(payload: dict[str, Any], skip_id: str | None = None) -> None:
    broadcast(payload, skip_id=skip_id)
    get_store().publish(payload)


def handle_remote_event(payload: dict[str, Any]) -> None:
    broadcast(payload)


def broadcast(payload: dict[str, Any], skip_id: str | None = None) -> None:
    stale_client_ids: list[str] = []
    message = json.dumps(payload)

    with clients_lock:
        active_clients = list(clients.items())

    for participant_id, ws in active_clients:
        if participant_id == skip_id:
            continue

        try:
            ws.send(message)
        except Exception:
            stale_client_ids.append(participant_id)

    if stale_client_ids:
        with clients_lock:
            for participant_id in stale_client_ids:
                clients.pop(participant_id, None)


def send_json(ws: Any, payload: dict[str, Any]) -> None:
    ws.send(json.dumps(payload))


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
