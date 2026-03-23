from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.routes_auth import router as auth_router
from app.routes_ops import router as ops_router
from app.routes_requester import router as requester_router
from shared.config import get_settings
from shared.db import ping_database
from shared.logging import log_web_event
from shared.workspace import verify_workspace_contract_paths


def create_app() -> FastAPI:
    app = FastAPI(title="Stage 1 AI Triage MVP")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    app.include_router(auth_router)
    app.include_router(requester_router)
    app.include_router(ops_router)

    @app.middleware("http")
    async def structured_request_logging(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log_web_event(
                "request_failed",
                level="error",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
            )
            raise

        log_web_event(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        try:
            settings = get_settings()
            settings.validate_contracts()
            ping_database(settings)
            verify_workspace_contract_paths(settings)
        except Exception as exc:
            log_web_event("readiness_failed", level="error", error=str(exc))
            return JSONResponse({"status": "not_ready", "error": str(exc)}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app


app = create_app()
