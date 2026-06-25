from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from flask import Blueprint, jsonify, request
from flask_sock import Sock


bp = Blueprint("collaboration", __name__)


@dataclass
class Participant:
    id: str
    name: str
    color: str
    x: float
    y: float
    updated_at: float


clients: dict[str, Any] = {}
participants: dict[str, Participant] = {}
state_lock = Lock()


def register_socket(sock: Sock) -> None:
    @sock.route("/ws")
    def websocket(ws):
        participant_id = clean_text(request.args.get("id"), fallback=f"user-{time.time_ns()}")
        name = clean_text(request.args.get("name"), fallback="Visitor")
        color = clean_color(request.args.get("color"), fallback="#2563eb")

        participant = Participant(
            id=participant_id,
            name=name,
            color=color,
            x=0.5,
            y=0.5,
            updated_at=time.time(),
        )

        with state_lock:
            clients[participant_id] = ws
            participants[participant_id] = participant
            snapshot = [serialize_user(user) for user in participants.values()]

        send_json(
            ws,
            {
                "type": "snapshot",
                "selfId": participant_id,
                "users": snapshot,
            },
        )
        broadcast({"type": "presence", "user": serialize_user(participant)}, skip_id=participant_id)

        try:
            while True:
                raw_message = ws.receive()
                if raw_message is None:
                    break

                message = parse_message(raw_message)
                if not message:
                    continue

                if message.get("type") == "hello":
                    updated = update_participant(
                        participant_id,
                        name=clean_text(message.get("name"), fallback=name),
                        color=clean_color(message.get("color"), fallback=color),
                    )
                    broadcast({"type": "presence", "user": serialize_user(updated)})

                if message.get("type") == "cursor":
                    updated = update_participant(
                        participant_id,
                        x=clamp_float(message.get("x"), fallback=participant.x),
                        y=clamp_float(message.get("y"), fallback=participant.y),
                    )
                    broadcast({"type": "cursor", "user": serialize_user(updated)}, skip_id=participant_id)
        finally:
            with state_lock:
                clients.pop(participant_id, None)
                participants.pop(participant_id, None)

            broadcast({"type": "leave", "id": participant_id})


@bp.get("/api/presence")
def presence_snapshot():
    with state_lock:
        users = [serialize_user(user) for user in participants.values()]

    return jsonify({"users": users, "total": len(users)})


def update_participant(participant_id: str, **updates: Any) -> Participant:
    with state_lock:
        participant = participants[participant_id]

        for key, value in updates.items():
            if value is not None:
                setattr(participant, key, value)

        participant.updated_at = time.time()
        participants[participant_id] = participant
        return participant


def broadcast(payload: dict[str, Any], skip_id: str | None = None) -> None:
    stale_client_ids: list[str] = []
    message = json.dumps(payload)

    with state_lock:
        active_clients = list(clients.items())

    for participant_id, ws in active_clients:
        if participant_id == skip_id:
            continue

        try:
            ws.send(message)
        except Exception:
            stale_client_ids.append(participant_id)

    if stale_client_ids:
        with state_lock:
            for participant_id in stale_client_ids:
                clients.pop(participant_id, None)
                participants.pop(participant_id, None)


def send_json(ws: Any, payload: dict[str, Any]) -> None:
    ws.send(json.dumps(payload))


def parse_message(raw_message: str | bytes) -> dict[str, Any] | None:
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8")

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
