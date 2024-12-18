"""Audit logging for consequential actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog

CONSEQUENTIAL_ACTIONS = {
    "user.register",
    "user.login",
    "user.role_change",
    "user.deactivate",
    "project.create",
    "project.update",
    "project.status_change",
    "project.delete",
    "dataset.import",
    "rubric.create",
    "rubric.version",
    "rubric.change_approved",
    "rubric.change_rejected",
    "rating.submit",
    "rating.corrected",
    "rating.reopen",
    "adjudication.decide",
    "adjudication.escalate",
    "adjudication.reopen",
    "calibration.session_create",
    "calibration.attempt",
    "report.generate",
    "ai_provider.save",
    "llm.invocation",
    "membership.grant",
    "membership.revoke",
}


def log_action(
    db: Session,
    user_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=details,
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
