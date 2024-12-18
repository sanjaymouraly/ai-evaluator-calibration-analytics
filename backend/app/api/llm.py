"""Optional AI-assistance endpoints.

The platform is fully functional without any provider.
When configured, outputs are always labelled AI-generated and
never override human decisions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.config import settings
from app.db import get_db
from app.llm.providers import (
    LLMClient,
    LLMError,
    ProviderConfig,
    cluster_explanations,
    summarize_disagreement_case,
)
from app.models import User
from app.schemas import LLMUsageOut
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/llm", tags=["ai-assistance"])


class ProviderSaveRequest(BaseModel):
    provider: str
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    label: str | None = None


@router.get("/config")
def get_llm_config(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    cfg = ProviderConfig(db).mask()
    return {
        "enabled": settings.llm_enabled,
        "active": cfg,
        "allow_evaluation_content": settings.llm_allow_evaluation_content,
        "available_providers": [
            "openai",
            "anthropic",
            "openrouter",
            "openai_compatible",
            "ollama",
            "offline",
        ],
    }


@router.post("/config")
def save_llm_config(
    data: ProviderSaveRequest, user: User = Depends(require_admin), db: Session = Depends(get_db)
):
    # owner_id must be a real user (FK); attribute the credential to the
    # admin who configured it so it can be audited and revoked.
    ProviderConfig(db, owner_id=user.id).save(
        provider=data.provider,
        api_key=data.api_key,
        base_url=data.base_url,
        model=data.model,
        label=data.label,
        activate=True,
    )
    return {"ok": True, "provider": data.provider, "model": data.model}


@router.get("/test")
def test_llm(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    cfg = ProviderConfig(db).get_active()
    client = LLMClient(db, cfg or {})
    return client.test_connection()


@router.post("/usage")
def toggle_usage(enabled: bool, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    settings.llm_enabled = enabled
    return {"llm_enabled": settings.llm_enabled}


@router.post("/summarize-case")
def summarize_case(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ProjectService(db).get(project_id, user)  # permission check
    from app.models import EvaluationTask, Rating

    task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
    ratings = db.query(Rating).filter(Rating.task_id == task_id, Rating.status == "submitted").all()
    rationales = {r.reviewer_id: r.rationale or "" for r in ratings}
    offline = summarize_disagreement_case(
        task.prompt,
        task.response_a,
        [{"reviewer_id": r.reviewer_id, "scores": r.scores_json} for r in ratings],
        rationales,
    )
    cfg = ProviderConfig(db).get_active()
    if cfg is None or not settings.llm_enabled:
        return {**offline, "mode": "offline"}
    if not settings.llm_allow_evaluation_content:
        return {
            **offline,
            "mode": "offline",
            "note": (
                "Offline deterministic summary: live AI is enabled but "
                "LLM_ALLOW_EVALUATION_CONTENT is false, so no evaluation "
                "content was sent to the provider."
            ),
        }
    client = LLMClient(db, cfg)
    try:
        prompt = (
            f"Summarize the disagreement neutrally. Scores: "
            f"{offline['divergent_categories']}. Do not invent facts."
        )
        result = client.complete(prompt, max_tokens=300)
        return {
            **offline,
            "mode": "online",
            "ai_summary": result.text,
            "ai_generated": True,
        }
    except LLMError as exc:
        return {**offline, "mode": "offline_fallback", "error": str(exc)}


@router.post("/cluster-rationales")
def cluster_rationales(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ProjectService(db).get(project_id, user)
    from app.models import Rating

    rationales = [
        r.rationale
        for r in db.query(Rating).filter(Rating.task_id == task_id, Rating.status == "submitted").all()
        if r.rationale
    ]
    return {"clusters": cluster_explanations(rationales), "method": "keyword_signature_offline"}


@router.post("/suggest-rubric")
def suggest_rubric_wording(
    project_id: str,
    category_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.llm.providers import suggest_rubric_wording as offline_suggest

    ProjectService(db).get(project_id, user)
    from app.models import Rubric, RubricCategory

    rubric = db.query(Rubric).filter(Rubric.project_id == project_id, Rubric.status == "active").first()
    cat = None
    if rubric:
        cat = (
            db.query(RubricCategory)
            .filter(RubricCategory.rubric_id == rubric.id)
            .filter(RubricCategory.key == category_key)
            .first()
        )
    result = offline_suggest(category_key, cat.definition if cat else None)
    cfg = ProviderConfig(db).get_active()
    if cfg and settings.llm_enabled and settings.llm_allow_evaluation_content:
        client = LLMClient(db, cfg)
        try:
            prompt = (
                f"Suggest clearer rubric wording for category '{category_key}' "
                f"with current definition: {cat.definition if cat else '(none)'}. "
                "Return 2 sentences of improved operational definition."
            )
            llm = client.complete(prompt, max_tokens=200)
            result["ai_suggestion"] = llm.text
            result["ai_generated"] = True
        except LLMError:
            result["ai_generated"] = False
    return result


@router.get("/usage-logs", response_model=list[LLMUsageOut])
def usage_logs(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import LLMUsageLog

    return db.query(LLMUsageLog).order_by(LLMUsageLog.created_at.desc()).limit(100).all()
