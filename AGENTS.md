<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Project Guide

This template is a realtime cursor-presence app: a Next.js App Router frontend at `/` and a FastAPI WebSocket backend mounted at `/server` through Vercel Services.

## Stack

- [Next.js 16 App Router](https://nextjs.org/docs/app), [React 19](https://react.dev), [TypeScript](https://www.typescriptlang.org/docs/), and [Tailwind CSS](https://tailwindcss.com/docs)
- [FastAPI](https://fastapi.tiangolo.com), [Uvicorn](https://www.uvicorn.org), and the [Redis asyncio client](https://redis.readthedocs.io)
- [Vercel CLI](https://vercel.com/docs/cli) and [Vercel FastAPI deployments](https://vercel.com/docs/frameworks/backend/fastapi)
- [pnpm](https://pnpm.io) and [uv](https://docs.astral.sh/uv) for dependency management
- [`perfect-cursors`](https://github.com/steveruizok/perfect-cursors) for remote cursor interpolation

## Important Files

- `frontend/app/page.tsx` renders the board.
- `frontend/app/collab-canvas.tsx` owns client identity, WebSocket connection, cursor sending, and UI.
- `backend/app/api/routes/collaboration.py` owns `/ws`, `/api/presence`, in-memory presence, and optional Redis pub/sub.
- `vercel.json` maps `web` from `frontend/` to `/` and `api` from `backend/` to `/server`.
- `README.md` is the human-facing setup and deployment guide.

## Working Rules

- Read the relevant local Next.js docs in `node_modules/next/dist/docs/` before changing App Router, config, or client/server boundary code.
- Prefer Vercel Services for local development and deployment because it matches the production routing contract: Next.js at `/`, FastAPI at `/server`.
- Keep `REDIS_URL` server-side. Do not expose it with `NEXT_PUBLIC_`.
- The browser defaults to `/server/ws`; only set `NEXT_PUBLIC_WS_URL` for the less common split-server workflow.
- Preserve the WebSocket message shapes documented in `README.md` unless updating the guide and backend/frontend together.
- Prefer focused changes and run `pnpm lint` after TypeScript or React edits.

## Local Commands

```bash
pnpm install
cd backend && uv sync && cd ..
vercel dev -L
```

Use split servers only when debugging one service in isolation:

```bash
cd backend && uv run uvicorn app.main:app --reload --port 5001
NEXT_PUBLIC_WS_URL=http://localhost:5001 pnpm --dir frontend dev
```
