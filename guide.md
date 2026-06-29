# Build a real-time collaboration board with Next.js and FastAPI
Last updated June 29, 2026
By Anshuman Bhardwaj

---

Build a collaborative canvas where every visitor can see who else is present, watch remote cursors move in real time, and keep presence consistent when the backend runs on more than one Vercel Function instance. It runs a Next.js App Router frontend from `frontend/`, a FastAPI WebSocket service from `backend/`, deploys as a single Vercel project with Services, and uses Redis when the app needs shared state across instances.

In this guide, you'll start with the Next.js and FastAPI template, add a browser collaboration board, wire the board to a WebSocket endpoint, then make the realtime layer production-ready with Redis-backed snapshots and pub/sub.

## Quick start with an AI coding agent

AI Assistance

I want to build a real-time cursor collaboration board with a Next.js App Router frontend and a FastAPI WebSocket backend. Use this repository as the source of truth. Read `README.md`, `frontend/app/collab-canvas.tsx`, `backend/app/api/routes/collaboration.py`, and `vercel.json`, then implement a session-scoped cursor presence board with WebSocket reconnects, optional Redis-backed presence snapshots, Redis pub/sub fanout, and a Vercel Services deployment.

Show more

### Vercel plugin

Turn your agent into a Vercel expert with the [Vercel plugin](https://vercel.com/docs/agent-resources/vercel-plugin). The plugin is optional; it is not required to use this template or follow this guide.

Terminal

```bash
npx plugins add vercel/vercel-plugin
```

## Prerequisites

* Node.js 22 or later
* Python 3.12 or later
* [pnpm](https://pnpm.io/)
* [uv](https://docs.astral.sh/uv/) for Python dependency management
* [Vercel CLI](https://vercel.com/docs/cli) for local Services development and deployment
* A Redis database, such as Upstash Redis, for multi-instance presence

## How it works

The app has two services that ship as one Vercel project:

* The `web` service uses `frontend/` as its root and renders the collaboration board at `/`.
* The `api` service uses `backend/` as its root and accepts WebSocket connections through `/server/ws`.
* The browser creates a per-tab participant, connects to the socket, and sends cursor coordinates as the pointer moves.
* FastAPI stores the latest participant state and broadcasts `presence`, `cursor`, and `leave` messages.
* Redis keeps snapshots consistent across instances and carries pub/sub events between FastAPI processes.

The final app uses these paths:

* `/` for the Next.js collaboration board
* `/server/ws` for the FastAPI WebSocket endpoint
* `/server/api/presence` for the current presence snapshot
* `/server/docs` for the FastAPI Swagger UI

The code excerpts in this guide focus on the moving pieces for realtime collaboration. For the surrounding UI, validation helpers, and cleanup paths, each section calls out what the full source file also contains.

## Project structure

The repository root is a small workspace that holds the Services config and shared commands. The actual frontend package lives in `frontend/`, and the FastAPI package lives in `backend/`.

```text
frontend/                         Next.js App Router frontend
frontend/app/page.tsx             Home route that renders the collaboration board
frontend/app/collab-canvas.tsx    Client-side realtime board UI
frontend/package.json             Next.js, React, Tailwind, and lint scripts
backend/                          FastAPI service
backend/app/main.py               FastAPI app entrypoint
backend/app/api/routes/collaboration.py
                                  WebSocket, presence store, Redis pub/sub
package.json                      Workspace helper scripts
pnpm-workspace.yaml               pnpm workspace definition
vercel.json                       Vercel Services definitions and public rewrites
```

The root `package.json` intentionally has only workspace-level commands. Run Next.js-only commands with `pnpm --dir frontend ...`, or use the root helper scripts for the common build, lint, and Services workflows.

## Steps

### 1. Configure Vercel Services

Vercel Services lets the Next.js app and the FastAPI backend deploy together while keeping each service in its natural framework. The `web` service owns `/`; the `api` service receives public traffic from `/server/(.*)`.

vercel.json

```json
{
  "services": {
    "web": {
      "root": "frontend/",
      "framework": "nextjs"
    },
    "api": {
      "root": "backend/",
      "entrypoint": "app.main:app",
      "framework": "fastapi"
    }
  },
  "rewrites": [
    { "source": "/server/(.*)", "destination": { "service": "api" } },
    { "source": "/(.*)", "destination": { "service": "web" } }
  ]
}
```

The FastAPI app declares its WebSocket route as `/ws`, and the top-level `/server/(.*)` rewrite sends browser traffic to the `api` service. Keeping both services on one origin avoids CORS setup and lets the browser use a relative WebSocket base URL in production.

The service configuration uses only service-supported keys: `root`, `framework`, and `entrypoint`. Do not put `maxDuration` directly on a service object. If a deployment needs function runtime settings, place them under the service-scoped `functions` object instead.

The public rewrite sends requests to the service with the `/server` prefix still present, so the FastAPI app strips that prefix before route matching. That lets the backend remain natural when run by itself while still serving `/server/ws` and `/server/api/...` through Services.

backend/app/main.py

```python
class ServicePrefixMiddleware:
    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = prefix
        self.prefix_bytes = prefix.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(f"{self.prefix}/"):
                scope = {
                    **scope,
                    "path": path[len(self.prefix) :] or "/",
                    "root_path": f"{scope.get('root_path', '')}{self.prefix}",
                }

                raw_path = scope.get("raw_path")
                if isinstance(raw_path, bytes) and raw_path.startswith(self.prefix_bytes):
                    scope["raw_path"] = raw_path[len(self.prefix_bytes) :] or b"/"

        await self.app(scope, receive, send)


app.add_middleware(ServicePrefixMiddleware, prefix="/server")
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(collaboration_router)
```

The backend's own routes stay short: the versioned API router serves `/api/v1`, and the collaboration router serves `/ws`. Through Services, those become `/server/api/v1` and `/server/ws`.

### 2. Render the board from the App Router

The App Router page stays intentionally small. It renders the collaboration board and leaves browser-specific behavior to the Client Component.

frontend/app/page.tsx

```tsx
import { CollabCanvas } from "./collab-canvas";

export default function Home() {
  return <CollabCanvas />;
}
```

`CollabCanvas` is marked with `"use client"` because it uses state, effects, `WebSocket`, `sessionStorage`, `ResizeObserver`, and pointer events.

frontend/app/collab-canvas.tsx

```tsx
"use client";

import { PerfectCursor } from "perfect-cursors";
import {
  type PointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
```

The root layout handles metadata and fonts with `next/font`, so the realtime component can stay focused on socket state and rendering.

frontend/app/layout.tsx

```tsx
export const metadata: Metadata = {
  title: "Realtime Collab Board",
  description: "A Next.js and FastAPI websocket collaboration demo.",
};
```

For brevity, this guide does not inline every part of the App Router shell. The full files also include:

* `frontend/app/layout.tsx`: Geist Sans and Geist Mono setup, the root `<html>` element, and the shared body classes.
* `frontend/app/globals.css`: Tailwind CSS import, font variables, and global body colors.
* `frontend/app/page.tsx`: the single public route that renders the board.

### 3. Create a per-tab visitor

Each browser tab gets a visitor id, name, and cursor color. The app stores that identity in `sessionStorage`, which means a reload keeps the same cursor while a second tab behaves like a separate collaborator.

frontend/app/collab-canvas.tsx

```tsx
const colors = [
  "#1e9df5",
  "#7b61ff",
  "#22c079",
  "#fb6e6e",
  "#f5a623",
  "#ff4fa3",
  "#14b8c4",
  "#5566ff",
];
const names = ["Mira", "Kai", "Rin", "Avery", "Noor", "Sol", "Ira", "Jules"];
const sessionUserKey = "collab-session-user";
```

The first render uses a placeholder user. A browser-only effect then creates or restores the real session user.

frontend/app/collab-canvas.tsx

```tsx
useEffect(() => {
  const timer = window.setTimeout(() => {
    setSelf(createLocalUser());
    setIsReady(true);
  }, 0);

  return () => window.clearTimeout(timer);
}, []);
```

`createLocalUser` restores a saved tab identity when it can, otherwise it creates a fresh one:

frontend/app/collab-canvas.tsx

```tsx
function createLocalUser(): PresenceUser {
  const savedUser = sessionStorage.getItem(sessionUserKey);
  if (savedUser) {
    try {
      const parsedUser = JSON.parse(savedUser) as Partial<PresenceUser>;
      if (parsedUser.id && parsedUser.name && parsedUser.color) {
        return {
          id: parsedUser.id,
          name: parsedUser.name,
          color: parsedUser.color,
          x: 0.5,
          y: 0.5,
          updatedAt: Date.now() / 1000,
        };
      }
    } catch {
      sessionStorage.removeItem(sessionUserKey);
    }
  }

  const randomIndex = Math.floor(Math.random() * names.length);
  return {
    id: crypto.randomUUID(),
    name: names[randomIndex],
    color: colors[randomIndex % colors.length],
    x: 0.5,
    y: 0.5,
    updatedAt: Date.now() / 1000,
  };
}
```

After the visitor is ready, the app writes the stable identity back to `sessionStorage` whenever the name or color changes.

frontend/app/collab-canvas.tsx

```tsx
useEffect(() => {
  if (!isReady) {
    return;
  }

  sessionStorage.setItem(
    sessionUserKey,
    JSON.stringify({ id: self.id, name: self.name, color: self.color }),
  );
}, [isReady, self.id, self.name, self.color]);
```

For brevity, this guide does not inline every identity helper. The full file also includes:

* `defaultUser`, which gives React a stable placeholder before `sessionStorage` is available.
* `updateName`, which trims names to 28 characters before updating local state.
* `updateColor`, which changes the local cursor color and triggers the socket effect with the latest profile.

### 4. Open and maintain the WebSocket connection

The browser connects to `/server/ws` by default. When the frontend and backend run as separate local servers, `NEXT_PUBLIC_WS_URL` can point directly at FastAPI.

frontend/app/collab-canvas.tsx

```tsx
function createWebSocketUrl(user: Pick<PresenceUser, "id" | "name" | "color">) {
  const baseUrl = process.env.NEXT_PUBLIC_WS_URL ?? "/server";
  const url = new URL(
    `${baseUrl.replace(/\/$/, "")}/ws`,
    window.location.origin,
  );

  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("id", user.id);
  url.searchParams.set("name", user.name);
  url.searchParams.set("color", user.color);

  return url.toString();
}
```

The connection effect opens the socket after the visitor identity is ready. On open, it sends a `hello` message with the current name and color. On close, it reconnects with a capped backoff.

frontend/app/collab-canvas.tsx

```tsx
useEffect(() => {
  if (!isReady) {
    return;
  }

  let cancelled = false;

  const connect = () => {
    const ws = new WebSocket(
      createWebSocketUrl({ id: selfId, name: selfName, color: selfColor }),
    );
    socketRef.current = ws;
    setConnectionState("connecting");

    ws.addEventListener("open", () => {
      reconnectDelayRef.current = 800;
      setConnectionState("open");
      ws.send(
        JSON.stringify({ type: "hello", name: selfName, color: selfColor }),
      );
    });

    ws.addEventListener("close", () => {
      setConnectionState("closed");

      if (cancelled) {
        return;
      }

      reconnectTimerRef.current = setTimeout(
        connect,
        reconnectDelayRef.current,
      );
      reconnectDelayRef.current = Math.min(
        reconnectDelayRef.current * 1.6,
        8000,
      );
    });
  };

  connect();
}, [isReady, selfId, selfName, selfColor]);
```

The full effect also parses incoming socket messages, reduces them into the user map, clears reconnect timers on unmount, clears pending cursor timers, and closes the socket when the component leaves the page.

### 5. Send cursor movement without flooding the backend

The board sends normalized cursor coordinates between `0` and `1`. That makes cursor positions independent of each visitor's screen size.

frontend/app/collab-canvas.tsx

```tsx
const sendCursor = (event: PointerEvent<HTMLDivElement>) => {
  const board = boardRef.current;
  const socket = socketRef.current;

  if (!board || !socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }

  const rect = board.getBoundingClientRect();
  const x = clamp((event.clientX - rect.left) / rect.width);
  const y = clamp((event.clientY - rect.top) / rect.height);

  scheduleCursorSend(x, y);
};
```

Cursor messages are throttled to one send every `80ms`. The client still updates its own state before sending so the local cursor feels immediate.

frontend/app/collab-canvas.tsx

```tsx
const cursorSendIntervalMs = 80;

const flushCursor = () => {
  cursorSendTimerRef.current = null;

  const pendingCursor = pendingCursorRef.current;
  const socket = socketRef.current;

  if (!pendingCursor || !socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }

  pendingCursorRef.current = null;
  lastSentAtRef.current = Date.now();

  const nextSelf = {
    ...selfRef.current,
    ...pendingCursor,
    updatedAt: Date.now() / 1000,
  };
  setSelf(nextSelf);
  setUsers((currentUsers) => ({ ...currentUsers, [nextSelf.id]: nextSelf }));
  socket.send(
    JSON.stringify({
      type: "cursor",
      x: pendingCursor.x,
      y: pendingCursor.y,
    }),
  );
};
```

`scheduleCursorSend` keeps the most recent pointer position in a ref and flushes it when the throttle window allows another send.

### 6. Render remote cursors smoothly

The server sends cursor snapshots as discrete points. The client uses `perfect-cursors` to animate each remote cursor between those points.

frontend/app/collab-canvas.tsx

```tsx
function RemoteCursor({
  boardSize,
  user,
}: {
  boardSize: BoardSize;
  user: PresenceUser;
}) {
  const cursorRef = useRef<HTMLDivElement | null>(null);
  const perfectCursorRef = useRef<PerfectCursor | null>(null);
  const { height, width } = boardSize;
  const { x, y } = user;
  const [initialPoint] = useState(() => [x * width, y * height]);

  const moveCursor = useCallback((point: number[]) => {
    const cursor = cursorRef.current;
    if (!cursor) {
      return;
    }

    cursor.style.transform = getCursorTransform(point);
  }, []);

  useEffect(() => {
    const perfectCursor = new PerfectCursor(moveCursor);
    perfectCursorRef.current = perfectCursor;
    perfectCursor.addPoint(initialPoint);

    return () => {
      perfectCursor.dispose();
      perfectCursorRef.current = null;
    };
  }, [initialPoint, moveCursor]);

  useEffect(() => {
    perfectCursorRef.current?.addPoint([x * width, y * height]);
  }, [height, width, x, y]);
}
```

The sidebar is just a view of the current user map. The current visitor is shown first, and remote visitors are sorted by name.

frontend/app/collab-canvas.tsx

```tsx
const otherUsers = useMemo(
  () =>
    Object.values(users)
      .filter((user) => user.id !== selfId)
      .sort((a, b) => a.name.localeCompare(b.name)),
  [selfId, users],
);
```

For brevity, this guide does not inline every part of the board UI. The full file also includes:

* The board header, status badge, name input, and color swatches.
* The grid canvas and static prototype cards that make cursor movement easy to see.
* `PresenceRow`, which renders each visitor in the sidebar.
* `ResizeObserver` state so remote cursor coordinates scale with the actual board size.
* `statusLabel` and `statusClassName`, which turn socket state into compact UI.

### 7. Accept WebSocket connections in FastAPI

The FastAPI route accepts the socket, creates a participant from query parameters, stores that participant, sends an initial snapshot, and announces the join.

backend/app/api/routes/collaboration.py

```python
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
```

The initial `snapshot` gives the new client a complete roster. Then `presence` tells everyone else that this participant joined.

backend/app/api/routes/collaboration.py

```python
await websocket.send_json(
    {
        "type": "snapshot",
        "selfId": participant.id,
        "users": await presence_store.snapshot(),
        "stateStore": presence_store.label,
    }
)
await announce({"type": "presence", "user": serialize_user(participant)}, skip_id=participant.id)
```

Full snapshots make reconnects simple. A reconnecting client does not need to replay missed events; it can replace local state from the latest snapshot.

### 8. Keep the socket protocol small

The browser sends two message types:

* `hello` updates the participant's name and color.
* `cursor` updates the participant's normalized pointer position.

backend/app/api/routes/collaboration.py

```python
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
```

The client receives four message types:

* `snapshot` replaces the local user map.
* `presence` adds or updates a participant.
* `cursor` updates a participant's coordinates.
* `leave` removes a participant.

frontend/app/collab-canvas.tsx

```tsx
function reducePresence(
  currentUsers: Record<string, PresenceUser>,
  message: SocketMessage,
  selfId: string,
) {
  if (message.type === "snapshot") {
    return Object.fromEntries(message.users.map((user) => [user.id, user]));
  }

  if (message.type === "presence" || message.type === "cursor") {
    return { ...currentUsers, [message.user.id]: message.user };
  }

  if (message.type === "leave" && message.id !== selfId) {
    const nextUsers = { ...currentUsers };
    delete nextUsers[message.id];
    return nextUsers;
  }

  return currentUsers;
}
```

On disconnect, the backend removes the socket, cancels any delayed cursor persistence task, deletes the participant from the store, and broadcasts a `leave` event.

backend/app/api/routes/collaboration.py

```python
finally:
    async with clients_lock:
        clients.pop(participant.id, None)

    await cancel_cursor_snapshot(participant.id)
    await presence_store.remove(participant.id)
    await announce({"type": "leave", "id": participant.id})
```

For brevity, this guide does not inline every protocol helper. The full files also include:

* `parseSocketMessage`, which ignores invalid client-side JSON frames.
* `parse_message`, which accepts Redis byte payloads and WebSocket text frames.
* `clean_text`, `clean_color`, and `clamp_float`, which keep untrusted socket input bounded.
* `serialize_user`, which converts Python `updated_at` into the frontend's `updatedAt`.

### 9. Start with an in-memory presence store

The memory store makes local development quick because it does not require Redis. It is enough when one FastAPI process holds all connected sockets.

backend/app/api/routes/collaboration.py

```python
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
```

The memory store uses the same interface as Redis, so the WebSocket route does not need to know which persistence backend is active.

backend/app/api/routes/collaboration.py

```python
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
```

The store factory chooses Redis when `REDIS_URL` exists and falls back to memory otherwise.

backend/app/api/routes/collaboration.py

```python
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
```

### 10. Add Redis-backed snapshots

Redis stores the latest participant payloads in a hash and their last activity timestamps in a sorted set.

backend/app/api/routes/collaboration.py

```python
PRESENCE_HASH_KEY = "collab:presence:users"
PRESENCE_ACTIVITY_KEY = "collab:presence:activity"
STALE_AFTER_SECONDS = 120
```

Writing a participant updates both structures and adds expirations so old demo state cannot live forever.

backend/app/api/routes/collaboration.py

```python
async def upsert(self, participant: Participant) -> None:
    payload = json.dumps(serialize_user(participant))
    pipe = self.redis.pipeline()
    pipe.hset(PRESENCE_HASH_KEY, participant.id, payload)
    pipe.zadd(PRESENCE_ACTIVITY_KEY, {participant.id: participant.updated_at})
    pipe.expire(PRESENCE_HASH_KEY, STALE_AFTER_SECONDS * 4)
    pipe.expire(PRESENCE_ACTIVITY_KEY, STALE_AFTER_SECONDS * 4)
    await pipe.execute()
```

Reading a snapshot first removes stale ids, then returns the current roster.

backend/app/api/routes/collaboration.py

```python
async def snapshot(self) -> list[dict[str, Any]]:
    await self.prune_stale()
    return [json.loads(user) for user in await self.redis.hvals(PRESENCE_HASH_KEY)]
```

Clean leaves remove the user from both Redis structures:

backend/app/api/routes/collaboration.py

```python
async def remove(self, participant_id: str) -> None:
    pipe = self.redis.pipeline()
    pipe.hdel(PRESENCE_HASH_KEY, participant_id)
    pipe.zrem(PRESENCE_ACTIVITY_KEY, participant_id)
    await pipe.execute()
```

Cursor movement is high-volume, so the backend publishes cursor events immediately but writes cursor snapshots to Redis on a small delay.

backend/app/api/routes/collaboration.py

```python
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
```

This gives reconnecting clients a recent cursor position without turning every pointer frame into a Redis write.

### 11. Add Redis pub/sub for cross-instance fanout

Redis storage gives every instance the same snapshot, but it does not push live messages to sockets held by another instance. Pub/sub handles that fanout.

backend/app/api/routes/collaboration.py

```python
PRESENCE_CHANNEL = "collab:presence:events"
INSTANCE_ID = uuid.uuid4().hex
```

Every published event includes the origin instance id:

backend/app/api/routes/collaboration.py

```python
async def publish(self, event: dict[str, Any]) -> None:
    await self.redis.publish(PRESENCE_CHANNEL, json.dumps({"origin": INSTANCE_ID, "event": event}))
```

Each Redis-backed instance subscribes to the shared channel and ignores events it published itself.

backend/app/api/routes/collaboration.py

```python
async for message in pubsub.listen():
    payload = parse_message(message.get("data"))
    if not payload or payload.get("origin") == INSTANCE_ID:
        continue

    event = payload.get("event")
    if isinstance(event, dict):
        await on_event(event)
```

The broadcast path is the same whether an event came from the local socket or a remote Redis message:

backend/app/api/routes/collaboration.py

```python
async def announce(payload: dict[str, Any], skip_id: str | None = None) -> None:
    await broadcast(payload, skip_id=skip_id)
    await (await get_store()).publish(payload)


async def handle_remote_event(payload: dict[str, Any]) -> None:
    await broadcast(payload)
```

The sequence is:

1. A user moves their cursor.
2. The FastAPI instance sends the cursor event to its own connected clients.
3. The instance publishes the cursor event to Redis.
4. Other FastAPI instances receive the pub/sub event.
5. Each instance broadcasts the event to its own connected clients.

For brevity, this guide does not inline every Redis detail from `backend/app/api/routes/collaboration.py`. The full file also includes:

* TLS CA configuration for `rediss://` Redis URLs through `certifi`.
* A listener lock so only one pub/sub task starts per process.
* A reconnect loop for Redis pub/sub failures.
* `schedule_background`, which logs async task failures instead of dropping them silently.
* Stale-client cleanup when a WebSocket send fails during `broadcast`.

### 12. Run locally

Install workspace dependencies from the repository root. pnpm reads `pnpm-workspace.yaml`, keeps the root as a command wrapper, and installs the Next.js package in `frontend/`.

Terminal

```bash
pnpm install
```

Install backend dependencies from `backend/`:

Terminal

```bash
cd backend
uv sync
cd ..
```

For the default local workflow, run both services through Vercel CLI from the repository root:

Terminal

```bash
vercel dev -L
```

Open `http://localhost:3000` in two browser tabs. Vercel CLI starts the `web` service from `frontend/`, starts the `api` service from `backend/`, and routes `/server/(.*)` to FastAPI.

Move your cursor across the board.

You should see:

* Each tab appears in the visitor list.
* Remote cursors move smoothly across the board.
* Changing a name or color updates the other tab.
* Closing a tab removes that participant.

You can also run the services separately when you want to debug one side in isolation. Start FastAPI on port `5001`:

Terminal

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 5001
```

Then start Next.js from the repository root and point it at the standalone backend. The `--dir frontend` flag matters because the Next.js package no longer lives at the repository root.

Terminal

```bash
NEXT_PUBLIC_WS_URL=http://localhost:5001 pnpm --dir frontend dev
```

Redis is optional locally. To use it, copy the example environment file and point `REDIS_URL` at your Redis instance:

Terminal

```bash
cp .env.example .env.local
```

Without `REDIS_URL`, FastAPI uses the in-memory store. That is enough for one local backend process, but it does not share state across backend instances.

Use these commands as quick health checks after changing the project:

Terminal

```bash
pnpm lint
pnpm build
python -m compileall backend/app
```

### 13. Deploy and test live

Set the Vercel project Framework Preset to Services. Deploy from the repository root so Vercel can read `vercel.json`, `pnpm-workspace.yaml`, `frontend/package.json`, and `backend/pyproject.toml`.

`vercel.json` defines the two services Vercel needs:

| Service | Root | Public route | Framework |
| --- | --- | --- | --- |
| `web` | `frontend/` | `/(.*)` | `nextjs` |
| `api` | `backend/` | `/server/(.*)` | `fastapi` |

Add `REDIS_URL` in Vercel Environment Variables for shared presence across instances. Keep it server-side; do not prefix it with `NEXT_PUBLIC_`.

The browser does not need a public API environment variable in the combined Services deployment. It connects to the same-origin `/server/ws` route by default. Set `NEXT_PUBLIC_WS_URL` only when running split local servers.

Deploy the project:

Terminal

```bash
vercel --prod
```

Open the production URL on two devices. The browser should connect over `wss://` to the same origin, and both devices should share one presence roster.

## Troubleshooting

### The socket will not connect locally

Cause: The frontend is trying to connect to `/server/ws`, but the FastAPI service is not mounted there, or separate local services are running without `NEXT_PUBLIC_WS_URL`.

Fix: Use `vercel dev -L` for a same-origin local setup. If running services separately, start FastAPI on port `5001`, then start Next.js with `NEXT_PUBLIC_WS_URL=http://localhost:5001 pnpm --dir frontend dev`.

### The web service is detected but localhost never loads

Cause: The Next.js app now lives in `frontend/`, so root-level Next.js commands or stale dependency metadata can leave Vercel CLI waiting on the wrong package install.

Fix: Run `pnpm install` from the repository root so the workspace lockfile has a `frontend` importer. Confirm `vercel.json` has `"root": "frontend/"` for the `web` service. For split-server debugging, start Next.js with `pnpm --dir frontend dev`, not `pnpm dev`.

### Presence works in one tab but not across instances

Cause: The app is using the in-memory store, so each FastAPI instance only sees its own connected clients.

Fix: Set `REDIS_URL` for the Vercel project and redeploy. Confirm `/server/api/presence` returns `"stateStore": "redis"`.

### A closed tab stays visible for a while

Cause: The socket may not have closed cleanly, or the tab's last activity timestamp has not gone stale.

Fix: This is expected for unclean disconnects. The Redis store prunes participants whose activity score is older than `STALE_AFTER_SECONDS`.

### Remote cursors jump instead of gliding

Cause: The remote cursor component is receiving sparse points, or `perfect-cursors` is not installed.

Fix: Confirm `perfect-cursors` is in `package.json` and that cursor messages are sent at a reasonable interval. The template sends at most one cursor message every `80ms`.

### Name or color changes do not reach other clients

Cause: The client did not send a `hello` message after opening the socket, or the server rejected invalid values.

Fix: Send `{ "type": "hello", "name": "...", "color": "#2563eb" }` after the socket opens. Colors must be seven-character hex values such as `#2563eb`.

### `/server/api/presence` returns memory in production

Cause: `REDIS_URL` is missing from the Vercel project environment, or the deployment was not restarted after the variable was added.

Fix: Add `REDIS_URL` to the project, redeploy, then check `/server/api/presence` again.

## Related resources

* [Vercel Services](https://vercel.com/docs/services)
* [WebSockets on Vercel Functions](https://vercel.com/docs/functions/websockets)
* [Next.js App Router](https://nextjs.org/docs/app)
* [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
* [Upstash for Vercel](https://vercel.com/marketplace/upstash)
* [redis-py asyncio examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html)
* [Redis pub/sub](https://redis.io/docs/latest/develop/interact/pubsub/)
* [Redis hashes](https://redis.io/docs/latest/develop/data-types/hashes/)
* [Redis sorted sets](https://redis.io/docs/latest/develop/data-types/sorted-sets/)
* [perfect-cursors](https://github.com/steveruizok/perfect-cursors)

## FAQ

### Do I need Redis locally?

No. The in-memory store is enough for one local FastAPI process. Redis is needed when presence must be shared across multiple FastAPI instances, devices, or deployed environments.

### Why put the user id in session storage?

`sessionStorage` is scoped to a browser tab and survives reloads. That makes local testing natural: two tabs look like two collaborators, while a reload keeps the same cursor identity.

### Why use normalized cursor coordinates?

Normalized coordinates let every client render the cursor relative to its own board size. A cursor at `{ "x": 0.5, "y": 0.5 }` appears in the center no matter how large the viewer's screen is.

### Why publish cursor events before writing every cursor to Redis?

Cursor events need low latency, but cursor snapshots only need to be recent enough for reconnects. Pub/sub carries the live event immediately, while the throttled Redis write keeps the shared snapshot fresh without writing every pointer frame.

### Can this support rooms or documents?

Yes. Add a room or document id to the WebSocket URL, include it in Redis keys and pub/sub channels, and only broadcast events to clients connected to the same room.

### Can the board require authentication?

Yes. Validate a cookie, session, or token before accepting the socket into the active client map. If the user is not allowed to join, close the socket before writing presence state.
