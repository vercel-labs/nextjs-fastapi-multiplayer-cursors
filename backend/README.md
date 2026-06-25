# FastAPI Realtime Collaboration Backend

This service started from Vercel's [FastAPI](https://fastapi.tiangolo.com/) starter:

```bash
vc init fastapi backend
```

It now exposes the WebSocket and presence endpoints used by the Next.js collaboration board.

## Project Structure

This example follows the [larger applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/) pattern from the FastAPI docs:

```
app/
├── __init__.py
├── main.py              # FastAPI application entry point
├── templates/
│   └── index.html       # Landing page template
├── api/
│   ├── __init__.py
│   ├── main.py          # API router assembly
│   ├── deps.py          # Shared dependencies
│   └── routes/
│       ├── __init__.py
│       └── items.py     # Item endpoints
└── core/
    ├── __init__.py
    └── config.py        # Application settings
```

## Getting Started

Install the required dependencies using [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Running Locally

```bash
uv sync
REDIS_URL=redis://localhost:6379/0 uv run uvicorn app.main:app --reload --port 5001
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Landing page |
| `GET` | `/ws` | Collaboration WebSocket endpoint |
| `GET` | `/api/presence` | Current presence snapshot and active state store |
| `GET` | `/api/v1/items/` | List sample items |
| `GET` | `/api/v1/items/{item_id}` | Get item by ID |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |

## Deploying to Vercel

In this repository, the backend deploys as part of the root Vercel Services project. From the repository root:

```bash
vercel --prod
```
