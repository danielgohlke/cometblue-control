"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .. import database as db, scheduler, config
from .routes import devices, temperatures, schedules, holidays, profiles, discovery, history, settings

log = logging.getLogger(__name__)

_UI_DIR = Path(__file__).parent.parent.parent / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cfg = config.get()
    await db.init_db()
    scheduler.init(
        poll_interval=cfg.get("poll_interval", 300),
        adapter=cfg.get("bluetooth", {}).get("adapter"),
    )
    log.info("CometBlue Control started")
    yield
    # Shutdown
    scheduler.shutdown()
    log.info("CometBlue Control stopped")


def create_app() -> FastAPI:
    cfg = config.get()

    app = FastAPI(
        title="CometBlue Control",
        description="REST API for CometBlue BLE radiator thermostats",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(devices.router)
    app.include_router(temperatures.router)
    app.include_router(schedules.router)
    app.include_router(holidays.router)
    app.include_router(profiles.router)
    app.include_router(discovery.router)
    app.include_router(history.router)
    app.include_router(settings.router)

    # System status
    @app.get("/api/status", tags=["system"])
    async def system_status():
        cfg = config.get()
        devices_list = await db.list_devices()
        auto_poll = await db.get_setting("auto_poll", "true") == "true"
        return {
            "status": "ok",
            "devices": len(devices_list),
            "poll_interval": cfg.get("poll_interval", 300),
            "next_poll": scheduler.get_next_run(),
            "auto_poll": auto_poll,
        }

    # Serve Web UI if present
    if _UI_DIR.exists() and (cfg.get("ui", {}).get("enabled", True)):
        @app.get("/", include_in_schema=False)
        async def serve_ui():
            return FileResponse(_UI_DIR / "index.html")

        @app.get("/{path:path}", include_in_schema=False)
        async def serve_ui_paths(path: str):
            file = _UI_DIR / path
            if file.exists() and file.is_file():
                return FileResponse(file)
            return FileResponse(_UI_DIR / "index.html")

    return app
