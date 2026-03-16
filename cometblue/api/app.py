"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .. import database as db, scheduler, config, auto_trigger
from .routes import devices, temperatures, schedules, holidays, profiles, discovery, history, settings, presets, auto_triggers

log = logging.getLogger(__name__)

_UI_DIR = Path(__file__).parent.parent.parent / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cfg = config.get()
    await db.init_db()
    saved_interval = await db.get_setting("poll_interval", None)
    poll_interval = int(saved_interval) if saved_interval else cfg.get("poll_interval", 900)
    scheduler.init(
        poll_interval=poll_interval,
        adapter=cfg.get("bluetooth", {}).get("adapter"),
    )
    auto_trigger.init(scheduler._scheduler)
    await auto_trigger.load_all()
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
    app.include_router(presets.router)
    app.include_router(auto_triggers.router)

    # System status
    @app.get("/api/status", tags=["system"])
    async def system_status():
        cfg = config.get()
        devices_list = await db.list_devices()
        auto_poll = await db.get_setting("auto_poll", "false") == "true"
        saved_interval = await db.get_setting("poll_interval", None)
        poll_interval = int(saved_interval) if saved_interval else cfg.get("poll_interval", 900)
        return {
            "status": "ok",
            "devices": len(devices_list),
            "poll_interval": poll_interval,
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
