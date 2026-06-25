# Python Realtime API

This service hosts the realtime collaboration WebSocket and presence snapshot endpoints for the Next.js app.

## Project Structure

```
├── main.py              # FastAPI app and entry point
├── collaboration.py     # WebSocket presence state and Redis pub/sub
├── items.py             # Sample API routes
├── templates/
│   └── index.html       # Landing page template
├── public/
│   └── favicon.ico
├── pyproject.toml
└── README.md
```

## Getting Started

Install the required dependencies using [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Running Locally

```bash
REDIS_URL=redis://localhost:6379/0 uvicorn main:app --reload --port 5001
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Landing page |
| `GET` | `/api/data` | List sample items |
| `GET` | `/api/items/<item_id>` | Get item by ID |
| `GET` | `/api/presence` | Current presence snapshot and active state store |
| `GET` | `/ws` | WebSocket endpoint for cursor presence |

## Redis

Set `REDIS_URL` for Redis-backed presence state and pub/sub. Without it, the app falls back to process memory.

For Vercel Services, add `REDIS_URL` at the project level in Vercel Environment Variables. The Python service receives the same project env vars as the Next.js service.

## Deploying to Vercel

Deploy your project to Vercel with the following command:

```bash
npm install -g vercel
vercel --prod
```

Or `git push` to your repository with our [git integration](https://vercel.com/docs/deployments/git).

To view the source code for this template, [visit the example repository](https://github.com/vercel/vercel/tree/main/examples/flask).
