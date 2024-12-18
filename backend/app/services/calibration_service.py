"""Reviewer calibration: gold-standard assessments, pre/post
phases, feedback generation, pass/fail against configurable
thresholds, and progress tracking over time.

Calibration measures *accuracy against expert-approved reference
labels* — it is distinct from inter-rater agreement and from
severity/leniency bias. The analytics layer keeps these separate.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.analytics import stats as st
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import CalibrationAttempt, CalibrationSession, EvaluationTask
from app.schemas import CalibrationAttemptOut


class CalibrationService:
    def __init__(self, db: Session):
        self.db = db

    def create_session(
        self,
        project_id: str,
        name: str,
        description: str | None,
        task_ids: list[str],
        pass_kappa: float,
        pass_accuracy: float,
        created_by: str,
    ) -> CalibrationSession:
        tasks = (
            self.db.query(EvaluationTask)
            .filter(EvaluationTask.id.in_(task_ids))
            .filter(EvaluationTask.gold_label_json.isnot(None))
            .all()
        )
        if len(tasks) < 2:
            raise ValidationError(
                "Calibration requires at least 2 tasks with expert-approved "
                "gold labels. Set gold labels first."
            )
        session = CalibrationSession(
            project_id=project_id,
            name=name,
            description=description,
            created_by=created_by,
            pass_threshold_kappa=pass_kappa,
            pass_threshold_accuracy=pass_accuracy,
            status="active",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def list_sessions(self, project_id: str) -> list[CalibrationSession]:
        return (
            self.db.query(CalibrationSession)
            .filter(CalibrationSession.project_id == project_id)
            .order_by(CalibrationSession.created_at.desc())
            .all()
        )

    def run_assessment(
        self,
        session_id: str,
        reviewer_id: str,
        phase: str,
        item_scores: dict[str, dict[str, Any]],
    ) -> CalibrationAttempt:
        """Record a calibration assessment.

        ``item_scores`` maps task_id -> {category: value} as rated by
        the reviewer. Gold answers come from the task's approved
        reference label. Metrics: kappa vs gold (nominal) or MAE
        (numerical), accuracy on modal labels.
        """
        if phase not in {"pre", "post"}:
            raise ValidationError("phase must be 'pre' or 'post'")
        session = self.db.query(CalibrationSession).filter(CalibrationSession.id == session_id).first()
        if session is None:
            raise NotFoundError("Calibration session not found.")
        existing = (
            self.db.query(CalibrationAttempt)
            .filter(
                CalibrationAttempt.session_id == session_id,
                CalibrationAttempt.reviewer_id == reviewer_id,
                CalibrationAttempt.phase == phase,
            )
            .first()
        )
        if existing is not None:
            raise ConflictError(
                f"A {phase}-calibration attempt already exists for this reviewer. "
                "Contact the session administrator."
            )

        gold_scores, reviewer_scores = [], []
        feedback: list[dict[str, Any]] = []
        for task_id, scores in item_scores.items():
            task = self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
            if task is None or not task.gold_label_json:
                continue
            gold = task.gold_label_json.get("scores", {})
            for key, gold_v in gold.items():
                rv = scores.get(key)
                if rv is None:
                    continue
                gold_scores.append(gold_v)
                reviewer_scores.append(rv)
                if str(gold_v) != str(rv):
                    feedback.append(
                        {
                            "task_id": task_id,
                            "category": key,
                            "your_score": rv,
                            "gold_score": gold_v,
                            "guidance": (
                                "Review the anchor definitions for this "
                                "category; your score diverges from the "
                                "expert-approved reference."
                            ),
                        }
                    )

        # Choose metrics by data type
        kappa_val = None
        mae_val = None
        accuracy_val = None
        if gold_scores and all(isinstance(v, int | float) for v in gold_scores):
            # treat as numeric: MAE + exact accuracy
            mae_val, _ = st.mean_absolute_difference(gold_scores, reviewer_scores)
            accuracy_val, _ = st.accuracy(gold_scores, reviewer_scores)
        else:
            kappa_val, _ = st.cohen_kappa(gold_scores, reviewer_scores)
            accuracy_val, _ = st.accuracy(gold_scores, reviewer_scores)

        passed = None
        if accuracy_val is not None:
            passed = accuracy_val >= session.pass_threshold_accuracy and (
                kappa_val is None or kappa_val >= session.pass_threshold_kappa
            )

        attempt = CalibrationAttempt(
            session_id=session_id,
            reviewer_id=reviewer_id,
            phase=phase,
            item_scores_json=item_scores,
            gold_scores_json={
                tid: (
                    self.db.query(EvaluationTask).filter(EvaluationTask.id == tid).first().gold_label_json
                    or {}
                ).get("scores")
                for tid in item_scores
            },
            kappa=kappa_val,
            accuracy=accuracy_val,
            mae=mae_val,
            passed=passed,
            feedback_json={"items": feedback},
        )
        self.db.add(attempt)
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def reviewer_progress(self, session_id: str, reviewer_id: str) -> dict[str, Any]:
        attempts = (
            self.db.query(CalibrationAttempt)
            .filter(
                CalibrationAttempt.session_id == session_id,
                CalibrationAttempt.reviewer_id == reviewer_id,
            )
            .order_by(CalibrationAttempt.completed_at.asc())
            .all()
        )
        pre = next((a for a in attempts if a.phase == "pre"), None)
        post = next((a for a in attempts if a.phase == "post"), None)
        return {
            "pre": _attempt_out(pre),
            "post": _attempt_out(post),
            "improved": (
                (post.accuracy or 0) - (pre.accuracy or 0)
                if pre and post and pre.accuracy is not None and post.accuracy is not None
                else None
            ),
        }


def _attempt_out(a: CalibrationAttempt | None) -> CalibrationAttemptOut | None:
    return CalibrationAttemptOut.model_validate(a) if a else None
