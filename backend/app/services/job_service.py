"""Lightweight DB-backed background job queue.

A single worker thread polls the jobs table; jobs run in the
same process (no Redis/Celery dependency) which is appropriate
for a single-instance deployment. Each job opens its own DB
session.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Job

_HANDLERS: dict[str, Callable[[Session, dict], Any]] = {}
_shutdown = threading.Event()
_worker: threading.Thread | None = None


def register_handler(job_type: str, handler: Callable[[Session, dict], Any]):
    _HANDLERS[job_type] = handler


def enqueue(db: Session, job_type: str, payload: dict, created_by: str | None = None) -> Job:
    job = Job(job_type=job_type, payload_json=payload, created_by=created_by)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def list_jobs(db: Session, limit: int = 50) -> list[Job]:
    return db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()


def _worker_loop():
    while not _shutdown.is_set():
        db = SessionLocal()
        try:
            job = None
            try:
                job = db.query(Job).filter(Job.status == "queued").order_by(Job.created_at.asc()).first()
            except Exception:  # noqa: BLE001 - table may not exist yet
                db.rollback()
                time.sleep(1.0)
                continue
            if job is None:
                time.sleep(1.0)
                continue
            job.status = "running"
            job.started_at = _utcnow()
            db.commit()
            handler = _HANDLERS.get(job.job_type)
            if handler is None:
                job.status = "failed"
                job.error_message = f"No handler registered for {job.job_type}"
            else:
                try:
                    result = handler(db, job.payload_json or {})
                    job.status = "succeeded"
                    job.result_json = result
                except Exception as exc:  # noqa: BLE001
                    job.status = "failed"
                    job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}"
            job.finished_at = _utcnow()
            db.commit()
        finally:
            db.close()


def _utcnow():
    return dt.datetime.now(dt.UTC)


def start_worker():
    global _worker
    if _worker is not None and _worker.is_alive():
        return _worker
    _worker = threading.Thread(target=_worker_loop, daemon=True, name="job-worker")
    _worker.start()
    return _worker


def stop_worker():
    _shutdown.set()
