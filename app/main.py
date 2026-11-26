"""FastAPI app: JSON API + the built React frontend, scheduler started on boot."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, scheduler, settings
from .api import router
from .runner import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    manager.recover_after_restart()          # runs interrupted by a restart are marked "stopped"
    task = asyncio.create_task(scheduler.loop(manager))
    yield
    task.cancel()
    await manager.stop()


app = FastAPI(title="Agency Roles", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    # Cookie auth + this custom header on every state-changing call blocks cross-site form posts.
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-requested-with") != "fetch":
            return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


app.include_router(router)

if settings.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=settings.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve the React app for every non-API route (client-side routing)."""
        target = (settings.WEB_DIST / path).resolve()
        if path and target.is_file() and settings.WEB_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(settings.WEB_DIST / "index.html")
