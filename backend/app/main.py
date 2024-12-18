"""FastAPI application factory for the AI Evaluator Calibration &
Disagreement Analytics platform.

Wires together:
- DB session management
- Authentication & RBAC
- Structured logging
- Centralized exception handling
- Background job worker
- All API routers
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import init_db
from app.exceptions import AppError, safe_error
from app.json_response import SafeJSONResponse
from app.logging_config import setup_logging
from app.services import job_service


def create_app() -> FastAPI:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        if settings.environment.lower() == "production" and settings.jwt_secret_key in (
            "",
            "change-me-in-production-use-openssl-rand-hex-32",
        ):
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a strong random value in production "
                "(generate one with: openssl rand -hex 32)."
            )
        init_db()
        job_service.start_worker()
        logging.getLogger(__name__).info(
            "Application started; DB=%s, LLM enabled=%s",
            settings.database_url,
            settings.llm_enabled,
        )
        yield
        # shutdown
        job_service.stop_worker()
        logging.getLogger(__name__).info("Application shut down.")

    app = FastAPI(
        title="AI Evaluator Calibration & Disagreement Analytics",
        description=(
            "Measure reviewer consistency, detect scoring disagreements, "
            "calibrate human evaluators, adjudicate disputes, and improve "
            "annotation quality over time."
        ),
        version=settings.app_version,
        lifespan=lifespan,
        default_response_class=SafeJSONResponse,
    )

    # ---- CORS ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- centralized exception handling ----
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.public_message, "details": exc.details},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception):
        logging.getLogger(__name__).exception("Unhandled error: %s", exc)
        msg, status = safe_error(exc)
        return JSONResponse(status_code=status, content={"detail": msg})

    # ---- routers ----
    from app.api import (
        adjudication,
        admin,
        analytics,
        auth,
        calibration,
        data,
        disagreements,
        evaluation,
        llm,
        projects,
        reports,
        rubrics,
    )

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(projects.router)
    app.include_router(data.router)
    app.include_router(rubrics.router)
    app.include_router(evaluation.router)
    app.include_router(disagreements.router)
    app.include_router(adjudication.router)
    app.include_router(calibration.router)
    app.include_router(analytics.router)
    app.include_router(reports.router)
    app.include_router(llm.router)

    # ---- OpenAPI metadata ----
    app.openapi_tags = [
        {"name": "auth", "description": "Authentication & user management"},
        {"name": "projects", "description": "Project CRUD & membership"},
        {"name": "data", "description": "Dataset import & task management"},
        {"name": "rubrics", "description": "Rubric CRUD, versions, change approval"},
        {"name": "evaluation", "description": "Reviewer assignments & blinded rating"},
        {"name": "disagreements", "description": "Disagreement detection & prioritization"},
        {"name": "adjudication", "description": "Consensus & adjudication workflows"},
        {"name": "calibration", "description": "Gold-standard reviewer calibration"},
        {"name": "analytics", "description": "Agreement, bias, reliability, trends"},
        {"name": "reports", "description": "CSV/JSON/PDF report generation & exports"},
        {"name": "ai-assistance", "description": "Optional LLM assistance (offline-capable)"},
        {"name": "admin", "description": "Health, seed, audit, system stats"},
    ]

    return app


app = create_app()
