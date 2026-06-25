# Next.js + FastAPI Realtime Collab

This is a realtime collaboration demo with a [Next.js](https://nextjs.org) frontend and a FastAPI websocket backend.

## Getting Started

The FastAPI service lives in `backend/`, matching the directory created by:

```bash
vc init fastapi backend
```

Run both Vercel Services locally:

```bash
pnpm dev:services
```

Or run the services separately:

```bash
cd backend
uv sync
REDIS_URL=redis://localhost:6379/0 uv run uvicorn app.main:app --reload --port 5001
```

```bash
NEXT_PUBLIC_WS_URL=http://localhost:5001 pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) in two browser tabs and move your cursor across the board.

## Realtime API

The FastAPI service exposes:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/server/ws` | FastAPI WebSocket endpoint used by the Next.js client |
| `GET` | `/server/api/presence` | Current presence snapshot and active state store |

## Redis State

The FastAPI service uses Redis when `REDIS_URL` is present. Presence snapshots are stored in Redis and cursor/presence/leave events are published over Redis pub/sub so multiple FastAPI instances can relay updates to their connected websocket clients.

The websocket lives in the FastAPI service at `/server/ws`.

If `REDIS_URL` is not set, the FastAPI service falls back to in-memory state for local demos.

For local Vercel Services development, put the secret in the root `.env.local` file:

```bash
REDIS_URL=redis://localhost:6379/0
```

For deployed Vercel environments, add `REDIS_URL` in the project-level Environment Variables settings and scope it to Development, Preview, and Production as needed. Do not prefix it with `NEXT_PUBLIC_`; the FastAPI service reads it server-side.

## Deploying on Vercel

This repo uses `experimentalServices` in `vercel.json`:

- `web` serves the Next.js app at `/`
- `api` serves the FastAPI service at `/server`

Set the Vercel project Framework Preset to **Services** before deploying.
