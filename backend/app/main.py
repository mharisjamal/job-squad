"""App factory: CORS, routers under /api, /health, SPA static serving."""

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .activity import ActivityBroker
from .config import Settings
from .db import init_db, make_engine, make_sessionmaker
from .routers import (
    activity,
    applications,
    auth,
    comments,
    companies,
    export,
    groups,
    portals,
    stats,
)

_ROUTERS = (
    auth.router,
    groups.router,
    companies.router,
    applications.router,
    portals.router,
    comments.router,
    activity.router,
    stats.router,
    export.router,
)

MAX_REQUEST_BODY_BYTES = 1_000_000

_ACCESS_TOKEN_RE = re.compile(r"(access_token=)[^\s&\"']+")


class AccessTokenRedactionFilter(logging.Filter):
    """Scrub access_token values out of uvicorn access-log lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _ACCESS_TOKEN_RE.sub(r"\1***", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _ACCESS_TOKEN_RE.sub(r"\1***", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


_REDACTION_FILTER = AccessTokenRedactionFilter()


def create_app() -> FastAPI:
    settings = Settings.load()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await init_db(application.state.engine)
        yield
        await application.state.engine.dispose()

    app = FastAPI(title="JobSquad", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = make_engine(settings.db_path, settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.broker = ActivityBroker()

    access_logger = logging.getLogger("uvicorn.access")
    if _REDACTION_FILTER not in access_logger.filters:
        access_logger.addFilter(_REDACTION_FILTER)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    {"detail": "Request body too large"}, status_code=413
                )
        return await call_next(request)

    for router in _ROUTERS:
        app.include_router(router, prefix="/api")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    dist_dir = settings.repo_root / "frontend" / "dist"
    if (dist_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path == "health" or full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index = dist_dir / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend build not found")
        if full_path:
            candidate = dist_dir / full_path
            try:
                resolved = candidate.resolve()
                if resolved.is_file() and resolved.is_relative_to(dist_dir.resolve()):
                    return FileResponse(resolved)
            except OSError:
                pass
        return FileResponse(index)

    return app


app = create_app()
