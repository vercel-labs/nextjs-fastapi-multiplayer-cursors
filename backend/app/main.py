from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.main import api_router
from app.api.routes.collaboration import router as collaboration_router
from app.core.config import settings


class ServicePrefixMiddleware:
    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = prefix
        self.prefix_bytes = prefix.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(f"{self.prefix}/"):
                stripped_path = path[len(self.prefix) :] or "/"
                scope = {
                    **scope,
                    "path": stripped_path,
                    "root_path": f"{scope.get('root_path', '')}{self.prefix}",
                }

                raw_path = scope.get("raw_path")
                if isinstance(raw_path, bytes) and raw_path.startswith(self.prefix_bytes):
                    scope["raw_path"] = raw_path[len(self.prefix_bytes) :] or b"/"

        await self.app(scope, receive, send)


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_NAME,
    version=settings.VERSION,
)
app.add_middleware(ServicePrefixMiddleware, prefix="/server")

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(collaboration_router)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request, "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=5001, reload=True)
