"""Deterministic synthetic dataset generator.

Creates a realistic AI-evaluation scenario: a team assessing
three LLM assistants on customer-support and creative tasks
with a six-category rubric. Reviewers have distinct,
documentable scoring tendencies; the data deliberately
exhibits boundary confusion, categorical opposition,
severity gaps, rationale conflicts, and drift so that every
analytics workflow is exercisable.

Seeded with a fixed RNG → reproducible. Reset removes only
demo-owned data (emails @demo.eval-platform.io) and never touches
real user accounts.
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Adjudication,
    AdjudicationVote,
    Assignment,
    AuditLog,
    CalibrationAttempt,
    CalibrationSession,
    Dataset,
    Disagreement,
    EvaluationTask,
    Project,
    ProjectMember,
    Rating,
    Rubric,
    RubricCategory,
    RubricChangeRequest,
    RubricInsight,
    User,
)
from app.services.calibration_service import CalibrationService
from app.services.detection_service import DetectionService
from app.services.insight_service import InsightService

DEMO_DOMAIN = "@demo.eval-platform.io"

RUBRIC_SPEC = {
    "name": "Response Quality Rubric v1",
    "description": "Core response-quality rubric for support and creative tasks.",
    "categories": [
        {
            "key": "accuracy",
            "name": "Factual Accuracy",
            "definition": "Whether all verifiable claims in the response are correct and supported by the prompt context or widely-known facts.",
            "guidance": "Discount answers that contain plausible but unverified specifics.",
            "weight": 1.5,
            "scale_type": "ordinal",
            "min_value": 1,
            "max_value": 5,
            "options": [
                {"value": 1, "label": "Mostly false"},
                {"value": 2, "label": "Several errors"},
                {"value": 3, "label": "Mostly correct"},
                {"value": 4, "label": "Correct with minor issues"},
                {"value": 5, "label": "Fully accurate"},
            ],
            "anchors": [
                {
                    "value": 5,
                    "label": "Fully accurate",
                    "example": "All claims verifiable against the reference.",
                },
                {"value": 3, "label": "Mostly correct", "example": "Core answer right; one minor slip."},
                {"value": 1, "label": "Mostly false", "example": "Central claim is wrong or fabricated."},
            ],
            "examples": [
                {"score": 5, "text": "Cites the correct version number and matching features."},
                {"score": 2, "text": "Confuses pricing tiers and gives a wrong date."},
            ],
        },
        {
            "key": "completeness",
            "name": "Completeness",
            "definition": "The degree to which the response addresses every part of the user's request.",
            "guidance": "Check numbered sub-questions individually.",
            "weight": 1.2,
            "scale_type": "ordinal",
            "min_value": 1,
            "max_value": 5,
            "options": [
                {"value": 1, "label": "Ignores most of the request"},
                {"value": 2, "label": "Misses key parts"},
                {"value": 3, "label": "Adequate coverage"},
                {"value": 4, "label": "Thorough"},
                {"value": 5, "label": "Exhaustive"},
            ],
            "anchors": [
                {"value": 5, "label": "Exhaustive", "example": "Every sub-question answered with detail."},
            ],
            "examples": [],
        },
        {
            "key": "tone",
            "name": "Tone & Professionalism",
            "definition": "Appropriateness, courtesy, and consistency of tone for the intended audience.",
            "guidance": "Casual tone is acceptable for creative tasks, not for escalations.",
            "weight": 0.8,
            "scale_type": "ordinal",
            "min_value": 1,
            "max_value": 5,
            "options": [
                {"value": 1, "label": "Unprofessional"},
                {"value": 2, "label": "Inconsistent"},
                {"value": 3, "label": "Neutral"},
                {"value": 4, "label": "Appropriate"},
                {"value": 5, "label": "Excellent"},
            ],
            "anchors": [],
            "examples": [],
        },
        {
            "key": "helpfulness",
            "name": "Helpfulness",
            "definition": "How likely the response is to resolve the user's underlying problem without further clarification.",
            "guidance": None,
            "weight": 1.0,
            "scale_type": "ordinal",
            "min_value": 1,
            "max_value": 5,
            "options": [
                {"value": 1, "label": "Not helpful"},
                {"value": 2, "label": "Slightly helpful"},
                {"value": 3, "label": "Somewhat helpful"},
                {"value": 4, "label": "Helpful"},
                {"value": 5, "label": "Immediately actionable"},
            ],
            "anchors": [
                {
                    "value": 5,
                    "label": "Immediately actionable",
                    "example": "User can execute the steps verbatim.",
                },
            ],
            "examples": [],
        },
        {
            "key": "safety",
            "name": "Safety & Policy",
            "definition": "Absence of harmful, biased, or policy-violating content.",
            "guidance": "When unsure between safe and borderline, choose borderline and flag for adjudication.",
            "weight": 2.0,
            "scale_type": "categorical",
            "min_value": None,
            "max_value": None,
            "options": [
                {"value": "safe", "label": "Safe"},
                {"value": "borderline", "label": "Borderline"},
                {"value": "unsafe", "label": "Unsafe"},
            ],
            "anchors": [
                {"value": "safe", "label": "Safe", "example": "No policy concerns."},
                {"value": "unsafe", "label": "Unsafe", "example": "Contains disallowed content."},
            ],
            "examples": [],
        },
        {
            "key": "grounding",
            "name": "Grounding (0–10)",
            "definition": "Extent to which statements are grounded in the provided context rather than invented.",
            "guidance": None,
            "weight": 0.9,
            "scale_type": "numerical",
            "min_value": 0,
            "max_value": 10,
            "options": None,
            "anchors": [
                {"value": 10, "label": "Fully grounded", "example": "Every claim traceable to context."},
                {"value": 0, "label": "Pure fabrication", "example": "No claim supported by context."},
            ],
            "examples": [],
        },
    ],
}

# --- Reviewer personas with distinct, realistic tendencies ---
REVIEWERS = [
    # (name, email, severity_shift, noise, boundary_tendency)
    ("Alice Nguyen", "alice@demo.eval-platform.io", 0.0, 0.35, 0.05),
    ("Bob Martinez", "bob@demo.eval-platform.io", -0.8, 0.45, 0.10),  # severe
    ("Carol Okafor", "carol@demo.eval-platform.io", 0.7, 0.40, 0.10),  # lenient
    ("Dave Kim", "dave@demo.eval-platform.io", 0.1, 0.9, 0.35),  # noisy + boundary confused
    ("Elena Petrova", "elena@demo.eval-platform.io", -0.15, 0.30, 0.05),  # senior / near-gold
]

PROMPTS_SUPPORT = [
    "My order #{{n}} arrived damaged. What are my options?",
    "How do I reset two-factor authentication on my account?",
    "The app crashes when I upload files larger than 10MB. Help?",
    "Can I change my subscription from monthly to annual mid-cycle?",
    "I was charged twice for invoice #{{n}}. Refund?",
    "How do I export my data before deleting my account?",
]
PROMPTS_CREATIVE = [
    "Write a short poem about a lighthouse keeper in winter.",
    "Draft a product description for a ceramic coffee mug.",
    "Write a bedtime story for a 7-year-old about a brave mouse.",
    "Compose a haiku about remote work.",
]
MODELS = [
    ("Atlas-Mini", "2024.11"),
    ("Nova-Pro", "2025.02"),
    ("Helix-7B", "2025.06"),
]
LANGUAGES = ["en", "en", "en", "es"]
TASK_TYPES = ["customer_support", "customer_support", "creative_writing"]


def build_demo_data(db: Session, admin_id: str) -> dict[str, Any]:
    """Generate (or regenerate) the full demo scenario.

    Returns counts of created entities.
    """
    reset_demo_data(db, commit=False)

    rng = random.Random(20240917)
    now = dt.datetime.now(dt.UTC)

    # ---- users ----
    from app.auth import hash_password

    users: dict[str, User] = {}
    for name, email, *_ in REVIEWERS:
        role = "senior_reviewer" if name.startswith("Elena") else "reviewer"
        u = User(
            email=email,
            full_name=name,
            hashed_password=hash_password("demo-pass-123"),
            role=role,
        )
        db.add(u)
        users[email] = u
    # one adjudicator
    adjudicator = User(
        email="judge@demo.eval-platform.io",
        full_name="Priya Sharma",
        hashed_password=hash_password("demo-pass-123"),
        role="adjudicator",
    )
    db.add(adjudicator)
    db.flush()

    # ---- project ----
    owner = users["elena@demo.eval-platform.io"]
    project = Project(
        name="Demo: LLM Support Assistant — Q3 Evaluation",
        description=(
            "Synthetic demonstration project: three models evaluated on "
            "support and creative tasks with a 6-category rubric, 5 "
            "reviewers, deliberate disagreement patterns, gold labels, "
            "and adjudicated cases."
        ),
        owner_id=owner.id,
        status="active",
        mode="single",
        min_ratings_per_item=3,
        disagreement_minor_fraction=0.25,
        disagreement_major_fraction=0.5,
        categorical_opposite_pairs={"safe": "unsafe", "unsafe": "safe"},
        consensus_strategy="expert",
    )
    db.add(project)
    db.flush()

    for email, member in [(e, "lead" if e.startswith("elena") else "reviewer") for e in users]:
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=users[email].id,
                role_on_project=member,
                assigned_by=admin_id,
            )
        )
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=adjudicator.id,
            role_on_project="adjudicator",
            assigned_by=admin_id,
        )
    )

    # ---- rubric ----
    rubric = Rubric(
        project_id=project.id,
        name=RUBRIC_SPEC["name"],
        description=RUBRIC_SPEC["description"],
        version=1,
        status="active",
        created_by=admin_id,
        approved_by=admin_id,
        approved_at=now,
        effective_from=now,
        change_note="Initial approved version",
    )
    db.add(rubric)
    db.flush()
    for i, cat_spec in enumerate(RUBRIC_SPEC["categories"]):
        payload = dict(cat_spec)
        payload["options_json"] = payload.pop("options", None)
        payload["anchors_json"] = payload.pop("anchors", None)
        payload["examples_json"] = payload.pop("examples", None)
        db.add(
            RubricCategory(
                rubric_id=rubric.id,
                item_order=i,
                **payload,
            )
        )
    db.flush()

    # ---- dataset + tasks ----
    dataset = Dataset(
        project_id=project.id,
        name="Synthetic Q3 evaluation set (60 items)",
        source_file_name="synthetic_q3_eval.csv",
        source_format="csv",
        created_by=admin_id,
    )
    db.add(dataset)
    db.flush()

    tasks: list[EvaluationTask] = []
    for i in range(60):
        task_type = rng.choice(TASK_TYPES)
        model_name, model_version = rng.choice(MODELS)
        language = rng.choice(LANGUAGES)
        if task_type == "customer_support":
            prompt_template = rng.choice(PROMPTS_SUPPORT)
            prompt = prompt_template.replace("{{n}}", str(1000 + i))
        else:
            prompt = rng.choice(PROMPTS_CREATIVE)
        quality = rng.gauss(0.6, 0.25)  # latent response quality 0..1
        quality = min(max(quality, 0.05), 0.98)
        response_a = _gen_response(task_type, quality, rng, i)
        tasks.append(
            EvaluationTask(
                project_id=project.id,
                dataset_id=dataset.id,
                external_id=f"demo-{i:04d}",
                mode="single",
                prompt=prompt,
                response_a=response_a,
                reference_answer=_gen_reference(task_type),
                model_name=model_name,
                model_version=model_version,
                language=language,
                task_type=task_type,
                metadata_json={"synthetic": True, "seed": 20240917},
            )
        )
    db.add_all(tasks)
    db.flush()

    # ---- gold labels (20 items: first 20) ----
    gold_task_ids: dict[str, dict[str, Any]] = {}
    for task in tasks[:20]:
        quality = rng.gauss(0.6, 0.25)
        quality = min(max(quality, 0.05), 0.98)
        gold = {
            "accuracy": _clamp_int(round(1 + quality * 4), 1, 5),
            "completeness": _clamp_int(round(1 + quality * 4 + rng.gauss(0, 0.3)), 1, 5),
            "tone": _clamp_int(round(3 + quality * 2 + rng.gauss(0, 0.4)), 1, 5),
            "helpfulness": _clamp_int(round(1 + quality * 4 + rng.gauss(0, 0.3)), 1, 5),
            "safety": "unsafe" if quality < 0.18 else ("borderline" if quality < 0.35 else "safe"),
            "grounding": round(min(10, max(0, quality * 10 + rng.gauss(0, 0.8))), 1),
        }
        task.gold_label_json = {"scores": gold, "rationale": "Expert-approved reference label."}
        task.gold_approved_by = admin_id
        task.gold_approved_at = now
        gold_task_ids[task.id] = gold

    # ---- assignments + ratings ----
    reviewer_list = list(users.values())

    for task in tasks:
        # 3 reviewers per task, round-robin with overlap
        idx = int(task.external_id.split("-")[1])
        chosen = [
            reviewer_list[idx % len(reviewer_list)],
            reviewer_list[(idx + 1) % len(reviewer_list)],
            reviewer_list[(idx + 3) % len(reviewer_list)],
        ]
        for reviewer in chosen:
            db.add(
                Assignment(
                    task_id=task.id,
                    reviewer_id=reviewer.id,
                    blinded=True,
                )
            )
        # ratings
        task_idx = int(task.external_id.split("-")[1])
        quality = min(max(0.6 + rng.gauss(0, 0.22), 0.05), 0.98)
        for reviewer in chosen:
            email = reviewer.email
            name = reviewer.full_name
            shift, noise, boundary = _persona(name)
            scores = {}
            drift = _drift_for(name, task_idx)
            for cat in RUBRIC_SPEC["categories"]:
                if cat["scale_type"] in ("ordinal", "numerical"):
                    base = 1 + quality * 4
                else:
                    base = "safe" if quality >= 0.35 else ("borderline" if quality >= 0.18 else "unsafe")
                if cat["key"] == "safety":
                    # deliberate categorical disagreement zone
                    if 0.30 <= quality <= 0.42:
                        base = "borderline"
                    if quality < 0.20:
                        base = rng.choice(["unsafe", "borderline"])
                if cat["scale_type"] in ("ordinal", "numerical"):
                    val = base + shift + drift + rng.gauss(0, noise)
                    if boundary and rng.random() < boundary:
                        val += rng.choice([-1, 1])
                    if cat["scale_type"] == "ordinal":
                        scores[cat["key"]] = _clamp_int(round(val), 1, 5)
                    else:
                        scores[cat["key"]] = round(min(10, max(0, val * 2)), 1)
                else:
                    scores[cat["key"]] = base
            rationale = _gen_rationale(name, quality, rng, scores)
            rating = Rating(
                task_id=task.id,
                reviewer_id=reviewer.id,
                rubric_version_id=rubric.id,
                version=1,
                is_current=True,
                status="submitted",
                scores_json=scores,
                rationale=rationale,
                evidence=(f"Reviewed against rubric v1; response length " f"{len(task.response_a)} chars."),
                confidence=round(min(0.99, max(0.3, 0.9 - noise)), 2),
                abstained=False,
                submitted_at=now - dt.timedelta(days=(60 - task_idx) / 4),
            )
            db.add(rating)
            a = (
                db.query(Assignment)
                .filter(Assignment.task_id == task.id)
                .filter(Assignment.reviewer_id == reviewer.id)
                .first()
            )
            if a:
                a.status = "completed"
                a.completed_at = rating.submitted_at
        # a couple of abstentions for realism (from a 4th reviewer
        # who is NOT among the three assigned — keeps the unique
        # constraint intact)
        if task_idx in (7, 23, 41):
            chosen_ids = {r.id for r in chosen}
            abstainer = next((r for r in reviewer_list if r.id not in chosen_ids), None)
            if abstainer is not None:
                db.add(
                    Rating(
                        task_id=task.id,
                        reviewer_id=abstainer.id,
                        rubric_version_id=rubric.id,
                        version=1,
                        is_current=True,
                        status="submitted",
                        scores_json=None,
                        rationale=("Abstained: response was in a language " "I cannot reliably assess."),
                        evidence=None,
                        confidence=None,
                        abstained=True,
                        submitted_at=now - dt.timedelta(days=2),
                    )
                )

    db.flush()

    # ---- reconcile task statuses with submitted ratings ----
    # A task is "completed" once it has min_ratings_per_item submitted
    # ratings; anything with partial coverage is "in_progress". Without
    # this pass the seeded tasks would all read "pending" despite being
    # fully rated, making progress metrics misleading.
    submitted_counts: dict[str, int] = {}
    for task_id, count in (
        db.query(Rating.task_id, func.count(Rating.id))
        .filter(Rating.status == "submitted")
        .group_by(Rating.task_id)
        .all()
    ):
        submitted_counts[task_id] = count
    for task in tasks:
        have = submitted_counts.get(task.id, 0)
        task.status = (
            "completed"
            if have >= project.min_ratings_per_item
            else ("in_progress" if have > 0 else "pending")
        )
    db.flush()

    # ---- disagreement detection ----
    DetectionService(db).scan_project(project.id)

    # ---- adjudication of the top 2 disagreements ----
    disagreements = (
        db.query(Disagreement)
        .filter(Disagreement.project_id == project.id)
        .order_by(Disagreement.priority_score.desc())
        .limit(2)
        .all()
    )
    for dg in disagreements:
        adj = Adjudication(
            disagreement_id=dg.id,
            task_id=dg.task_id,
            adjudicator_id=adjudicator.id,
            strategy="expert",
            decision_json={
                "accuracy": 4,
                "completeness": 4,
                "tone": 4,
                "helpfulness": 4,
                "safety": "safe",
                "grounding": 8.0,
            },
            rationale=(
                "Adjudicated against rubric v1 anchors: core claims verified "
                "against the reference answer; minor completeness gap does not "
                "warrant a score below the anchor example for level 4."
            ),
            status="final",
        )
        db.add(adj)
        dg.status = "resolved"
        task = db.query(EvaluationTask).filter(EvaluationTask.id == dg.task_id).first()
        if task is not None:
            task.status = "adjudicated"

    # ---- calibration session ----
    cal = CalibrationSession(
        project_id=project.id,
        name="Q3 baseline calibration",
        description="Pre-calibration assessment against expert gold labels (20 items).",
        created_by=admin_id,
        pass_threshold_kappa=0.7,
        pass_threshold_accuracy=0.8,
        status="completed",
    )
    db.add(cal)
    db.flush()

    cal_svc = CalibrationService(db)
    for reviewer in reviewer_list:
        item_scores = {}
        for task in tasks[:20]:
            gold = gold_task_ids.get(task.id)
            if not gold:
                continue
            shift, noise, boundary = _persona(reviewer.full_name)
            scores = {}
            for cat in RUBRIC_SPEC["categories"]:
                g = gold[cat["key"]]
                if cat["scale_type"] in ("ordinal", "numerical"):
                    val = g + shift + rng.gauss(0, noise)
                    if cat["scale_type"] == "ordinal":
                        scores[cat["key"]] = _clamp_int(round(val), 1, 5)
                    else:
                        scores[cat["key"]] = round(min(10, max(0, val * 2)), 1)
                else:
                    scores[cat["key"]] = g
            item_scores[task.id] = scores
        cal_svc.run_assessment(cal.id, reviewer.id, "pre", item_scores)

    # ---- rubric insights ----
    InsightService(db).analyze_project(project.id)

    # ---- one pending AI-suggested rubric change request ----
    tone_cat = (
        db.query(RubricCategory)
        .filter(RubricCategory.rubric_id == rubric.id)
        .filter(RubricCategory.key == "tone")
        .first()
    )
    if tone_cat is not None:
        db.add(
            RubricChangeRequest(
                rubric_id=rubric.id,
                rubric_category_id=tone_cat.id,
                proposed_changes_json={
                    "definition": (
                        "Appropriateness, courtesy, and consistency of tone "
                        "for the intended audience. Score 3 when tone is "
                        "acceptable but inconsistent across turns; score 4 "
                        "when consistently appropriate; score 5 only when the "
                        "tone demonstrably de-escalates or builds rapport."
                    ),
                    "anchors": [
                        {"value": 3, "label": "Neutral", "example": "Polite but flat; no rapport-building."},
                        {
                            "value": 4,
                            "label": "Appropriate",
                            "example": "Warm, consistent, audience-matched.",
                        },
                    ],
                },
                evidence_json={
                    "trigger": "boundary_confusion between tone 3 and 4 in 40%+ of disagreements",
                    "note": "Draft wording generated by offline heuristics; requires human approval.",
                },
                rationale=(
                    "Boundary confusion between scores 3 and 4 is the most "
                    "frequent disagreement driver. Sharpen the definition and "
                    "add worked anchors at the 3/4 boundary."
                ),
                requested_by=admin_id,
                source="ai_suggested",
                is_ai_generated=True,
            )
        )

    db.commit()

    return {
        "project_id": project.id,
        "users": len(users) + 1,
        "tasks": len(tasks),
        "ratings": db.query(Rating).filter(Rating.task_id.in_([t.id for t in tasks])).count(),
        "disagreements": db.query(Disagreement).filter(Disagreement.project_id == project.id).count(),
        "gold_labeled": len(gold_task_ids),
    }


# ---------------------------------------------------------------------------


def _persona(name: str) -> tuple[float, float, float]:
    for n, _e, shift, noise, boundary in REVIEWERS:
        if name.startswith(n.split()[0]):
            return shift, noise, boundary
    return 0.0, 0.4, 0.05


def _drift_for(name: str, task_idx: int) -> float:
    """Dave's scoring drifts more severe over time (fatigue)."""
    if name.startswith("Dave"):
        return -0.15 * (task_idx / 60.0)
    return 0.0


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _gen_response(task_type: str, quality: float, rng: random.Random, idx: int) -> str:
    if task_type == "customer_support":
        if quality > 0.7:
            return (
                f"Case #{idx}: I'm sorry the order arrived damaged. I can "
                "arrange a replacement shipped today at no cost, or a full "
                "refund within 3–5 business days. To proceed, please confirm "
                "the item SKU and upload a photo of the packaging. I've also "
                "credited your account 15% for the inconvenience."
            )
        if quality > 0.4:
            return (
                f"Case #{idx}: Sorry about the damaged item. You can return "
                "it for a refund. Please contact our support line during "
                "business hours and mention your order number. We will "
                "review the issue and get back to you soon."
            )
        return (
            f"Case #{idx}: Your order is fine. Damaged items are rare. "
            "Please try again later or visit our FAQ page for more details. "
            "We appreciate your patience and understanding."
        )
    # creative
    if quality > 0.7:
        return (
            "The keeper winds the lamp against the coming storm, / each "
            "glass pane a patient star. / Below, the sea writes its long "
            "letters in salt, / and the light answers: here, here, here. / "
            "Winter sharpens every edge, / yet the beam stays soft for "
            "ships that remember home."
        )
    if quality > 0.4:
        return (
            "A lighthouse keeper lives near the sea. In winter it is cold "
            "and windy. The keeper keeps the light on so ships are safe. "
            "Sometimes the keeper feels lonely but likes the quiet."
        )
    return (
        "The lighthouse man is there. He turns on the light. Ships see "
        "the light. It is winter. There is snow maybe. The man is brave. "
        "The end."
    )


def _gen_reference(task_type: str) -> str:
    if task_type == "customer_support":
        return (
            "Expert reference: acknowledge the issue, offer replacement OR "
            "refund, request order details/photo, set expectations on "
            "timeline, and apply a goodwill gesture."
        )
    return "Expert reference: a short poem with consistent imagery, meter, " "and an emotional arc."


def _gen_rationale(name: str, quality: float, rng: random.Random, scores: dict) -> str:
    first = name.split()[0]
    if first == "Bob":
        return (
            "Clearly below the level-4 anchor: the response misses "
            "verification steps and the goodwill gesture is vague. "
            "The claim about timelines is unsupported."
        )
    if first == "Carol":
        return (
            "Obviously solid work; the empathy line is exactly what good "
            "support looks like. Minor phrasing issues only."
        )
    if first == "Dave":
        if rng.random() < 0.5:
            return "Seems okay overall but the tone feels maybe inconsistent in places, unclear if fully professional."
        return "Clearly professional and helpful; the steps are precise and complete."
    return (
        "Response addresses the request with accurate, verifiable steps; "
        "one minor gap in escalation guidance."
    )


# ---------------------------------------------------------------------------


def reset_demo_data(db: Session, commit: bool = True) -> int:
    """Remove all demo-owned data (email-domain marker).

    Deletes in strict FK-safe order so demo data can be reset
    without touching real user accounts or their projects.
    """
    demo_users = db.query(User).filter(User.email.like(f"%{DEMO_DOMAIN}")).all()
    if not demo_users:
        return 0
    ids = {u.id for u in demo_users}
    project_ids = [p.id for p in db.query(Project).filter(Project.owner_id.in_(ids)).all()]

    def _delete(model, condition):
        if condition is not None:
            db.query(model).filter(condition).delete(synchronize_session=False)

    if project_ids:
        # votes -> adjudications -> disagreements
        _delete(
            AdjudicationVote.__table__,  # type: ignore[arg-type]
            None,
        )
        adj_ids = [
            a.id
            for a in db.query(Adjudication)
            .join(EvaluationTask, Adjudication.task_id == EvaluationTask.id)
            .filter(EvaluationTask.project_id.in_(project_ids))
        ]
        if adj_ids:
            db.query(AdjudicationVote).filter(AdjudicationVote.adjudication_id.in_(adj_ids)).delete(
                synchronize_session=False
            )
            db.query(Adjudication).filter(Adjudication.id.in_(adj_ids)).delete(synchronize_session=False)
        _delete(
            Disagreement,
            Disagreement.project_id.in_(project_ids),
        )
        _delete(
            CalibrationAttempt,
            CalibrationAttempt.session_id.in_(
                db.query(CalibrationSession.id).filter(CalibrationSession.project_id.in_(project_ids))
            ),
        )
        _delete(
            CalibrationSession,
            CalibrationSession.project_id.in_(project_ids),
        )
        _delete(
            RubricChangeRequest,
            RubricChangeRequest.rubric_id.in_(db.query(Rubric.id).filter(Rubric.project_id.in_(project_ids))),
        )
        _delete(
            RubricInsight,
            RubricInsight.project_id.in_(project_ids),
        )
        _delete(
            Rating,
            Rating.task_id.in_(
                db.query(EvaluationTask.id).filter(EvaluationTask.project_id.in_(project_ids))
            ),
        )
        _delete(
            Assignment,
            Assignment.task_id.in_(
                db.query(EvaluationTask.id).filter(EvaluationTask.project_id.in_(project_ids))
            ),
        )
        _delete(EvaluationTask, EvaluationTask.project_id.in_(project_ids))
        _delete(Dataset, Dataset.project_id.in_(project_ids))
        _delete(
            RubricCategory,
            RubricCategory.rubric_id.in_(db.query(Rubric.id).filter(Rubric.project_id.in_(project_ids))),
        )
        _delete(Rubric, Rubric.project_id.in_(project_ids))
        _delete(ProjectMember, ProjectMember.project_id.in_(project_ids))
        _delete(Project, Project.id.in_(project_ids))

    # Audit entries written BY demo accounts (e.g. their logins) must go
    # first, otherwise the user delete violates the FK constraint.
    _delete(AuditLog, AuditLog.user_id.in_(ids))
    _delete(User, User.id.in_(ids))
    if commit:
        db.commit()
    return len(demo_users)
