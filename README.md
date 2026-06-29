# Next.js + FastAPI Realtime Collab

A realtime cursor-presence board with a Next.js App Router frontend and a FastAPI WebSocket backend. The two services run together through Vercel Services: Next.js owns `/`, and FastAPI is mounted under `/server`.

## What It Demonstrates

- A browser collaboration surface in `frontend/app/collab-canvas.tsx`
- Local visitor identity with session-scoped name and color preferences
- Throttled cursor updates from the client, smoothed remote cursors with `perfect-cursors`
- FastAPI WebSocket presence at `/ws`, exposed as `/server/ws` by Vercel Services
- Optional Redis-backed presence storage and pub/sub for multi-instance deployments
- In-memory presence fallback for quick local development

## Project Structure

```text
frontend/                         Next.js App Router frontend
frontend/app/page.tsx             Home route that renders the collaboration board
frontend/app/collab-canvas.tsx    Client-side realtime board UI
backend/                          FastAPI service
backend/app/main.py               FastAPI app entrypoint
backend/app/api/routes/items.py   Sample REST routes under /api/v1
backend/app/api/routes/collaboration.py
                                  WebSocket, presence store, Redis pub/sub
vercel.json                       Vercel Services definitions and public rewrites
```

The frontend defaults to `/server`, so the board connects to `/server/ws` in the combined Vercel Services setup. Set `NEXT_PUBLIC_WS_URL` only for split-server development.

## Local Setup

Install the workspace dependencies from the repository root:

```bash
pnpm install
```

Install the backend dependencies:

```bash
cd backend
uv sync
cd ..
```

Redis is optional. To use it locally, copy the example environment file and point `REDIS_URL` at your Redis instance:

```bash
cp .env.example .env.local
```

Without `REDIS_URL`, FastAPI uses an in-memory presence store. That is enough for one local backend process, but it does not share state across backend instances.

## Run Both Services

Start the Next.js and FastAPI services together from the repository root:

```bash
vercel dev -L
```

Open `http://localhost:3000` in multiple tabs or browsers. Each tab gets a visitor identity, can change its name and cursor color, and broadcasts cursor movement to the others.

## Run Separate Local Servers

Run FastAPI on port `5001`:

```bash
cd backend
REDIS_URL=redis://localhost:6379/0 uv run uvicorn app.main:app --reload --port 5001
```

Omit `REDIS_URL=...` if you want the in-memory store.

In another terminal, run Next.js and point the browser client at the standalone backend:

```bash
NEXT_PUBLIC_WS_URL=http://localhost:5001 pnpm --dir frontend dev
```

The client appends `/ws` to `NEXT_PUBLIC_WS_URL` and converts `http` or `https` to the matching WebSocket protocol. Leave `NEXT_PUBLIC_WS_URL` unset when using `vercel dev -L`; the browser uses the same-origin `/server` route.

## Realtime Flow

1. `frontend/app/page.tsx` renders the client component from `frontend/app/collab-canvas.tsx`.
2. The board creates or restores a visitor from `sessionStorage`.
3. The browser opens a WebSocket with `id`, `name`, and `color` query parameters.
4. FastAPI accepts the socket, stores the participant, and sends a `snapshot` message.
5. Name and color changes send `hello` messages. Pointer movement sends throttled `cursor` messages.
6. FastAPI broadcasts `presence`, `cursor`, and `leave` messages to other clients.
7. When Redis is enabled, presence is stored in Redis and events are shared through pub/sub so separate backend instances stay in sync.

## WebSocket Messages

Client-to-server messages:

| Message | Purpose |
| --- | --- |
| `{ "type": "hello", "name": "...", "color": "#1e9df5" }` | Update the participant profile after connection or UI edits |
| `{ "type": "cursor", "x": 0.42, "y": 0.68 }` | Broadcast normalized cursor coordinates |

Server-to-client messages:

| Message | Purpose |
| --- | --- |
| `snapshot` | Initial participant list plus the active state store label |
| `presence` | A participant joined or changed profile data |
| `cursor` | A participant moved their cursor |
| `leave` | A participant disconnected |

## Useful Endpoints

When running through Vercel Services:

| Path | Description |
| --- | --- |
| `/` | Next.js collaboration board |
| `/server/ws` | FastAPI WebSocket endpoint |
| `/server/api/presence` | Presence snapshot and active state store |
| `/server/api/v1/items/` | Sample REST endpoint from the FastAPI starter |
| `/server/docs` | FastAPI Swagger UI |

When running FastAPI by itself, remove the `/server` prefix.

## Scripts

| Command | Description |
| --- | --- |
| `pnpm --dir frontend dev` | Start only the Next.js dev server |
| `vercel dev -L` | Start the Vercel Services dev environment |
| `pnpm build` | Build the Next.js app |
| `pnpm --dir frontend start` | Start the built Next.js app |
| `pnpm lint` | Run ESLint |

## Deploying

Set the Vercel project Framework Preset to **Services**. `vercel.json` defines two services and exposes them with top-level rewrites. The FastAPI app strips the public `/server` prefix for both HTTP and WebSocket requests before route matching.

| Service | Root | Public route | Framework |
| --- | --- | --- | --- |
| `web` | `frontend/` | `/(.*)` | `nextjs` |
| `api` | `backend/` | `/server/(.*)` | `fastapi` |

Add `REDIS_URL` in Vercel Environment Variables for shared presence across instances. Keep it server-side; do not prefix it with `NEXT_PUBLIC_`. Without Redis, presence is process-local and can fragment when the backend scales horizontally.
