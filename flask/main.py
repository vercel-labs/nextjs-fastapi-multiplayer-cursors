from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from collaboration import router as collaboration_router
from items import router as items_router


app = FastAPI()
app.include_router(items_router)
app.include_router(collaboration_router)


@app.get("/", response_class=HTMLResponse)
async def read_root():
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Realtime Collab API</title>
      </head>
      <body>
        <main>
          <h1>Realtime Collab API</h1>
          <p>Use <code>/ws</code> for cursor presence and <code>/api/presence</code> for the current state snapshot.</p>
        </main>
      </body>
    </html>
    """


application = app
