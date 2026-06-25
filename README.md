# Next.js + Flask Realtime Collab

This is a realtime collaboration demo with a [Next.js](https://nextjs.org) frontend and a Flask websocket backend.

## Getting Started

Run both Vercel Services locally:

```bash
pnpm dev:services
```

Or run the services separately:

```bash
cd flask
uv sync
uv run flask --app main run --debug --port 5001
```

```bash
NEXT_PUBLIC_API_URL=http://localhost:5001 pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) in two browser tabs and move your cursor across the board.

## Realtime API

The Flask service exposes:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/server/ws` | WebSocket endpoint used by the Next.js client |
| `GET` | `/server/api/presence` | Current in-memory presence snapshot |

Presence is stored in process memory for now. Move `participants`, `clients`, and `broadcast` coordination in `flask/collaboration.py` to Redis when you need durable state across function instances and deployments.

## Deploying on Vercel

This repo uses `experimentalServices` in `vercel.json`:

- `web` serves the Next.js app at `/`
- `api` serves Flask at `/server`

Set the Vercel project Framework Preset to **Services** before deploying.
