"""App factory: CORS, routers under /api, /health, SPA static serving."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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


def create_app() -> FastAPI:
    settings = Settings.load()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await init_db(application.state.engine)
        yield
        await application.state.engine.dispose()

    app = FastAPI(title="JobSquad", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = make_engine(settings.db_path)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.broker = ActivityBroker()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
