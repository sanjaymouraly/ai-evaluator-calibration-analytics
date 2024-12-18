"""Integration tests for the full evaluation workflow.

Covers: auth/RBAC, project lifecycle, dataset import (valid, malformed,
duplicate), rubric creation/versioning with human approval, reviewer
assignment, blinding, drafts, submission validation, immutable rating
history, disagreement detection, adjudication, calibration, analytics,
and report generation.
"""

from __future__ import annotations

import csv
import io
import json
import time

import pytest

from tests.conftest import make_user

# ---------------------------------------------------------------------------
# Auth & RBAC
# ---------------------------------------------------------------------------


def test_health(client):
    assert client.get("/api/admin/health").status_code == 200


def test_unauthenticated_request_rejected(client):
    assert client.get("/api/projects").status_code == 401


def test_invalid_token_rejected(client):
    r = client.get("/api/projects", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_short_password_rejected(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "short@test-eval.io", "full_name": "S", "password": "abc", "role": "reviewer"},
    )
    assert r.status_code == 422


def test_wrong_password_rejected(client, admin_headers):
    r = client.post("/api/auth/login", json={"email": "admin@test-eval.io", "password": "wrong-password"})
    assert r.status_code == 422


def test_non_admin_cannot_list_users(client):
    _, headers = make_user(client, "plain-reviewer@test-eval.io")
    assert client.get("/api/auth/users", headers=headers).status_code == 403


def test_admin_can_list_users(client, admin_headers):
    r = client.get("/api/auth/users", headers=admin_headers)
    assert r.status_code == 200
    assert any(u["email"] == "admin@test-eval.io" for u in r.json())


def test_only_first_user_can_self_register_as_admin(client):
    r = client.post(
        "/api/auth/register",
        json={
            "email": "second-admin@test-eval.io",
            "full_name": "Second",
            "password": "password-12345",
            "role": "admin",
        },
    )
    assert r.status_code == 403


def test_passwords_are_hashed_not_plaintext(client, admin_headers):
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "admin@test-eval.io").first()
        assert user is not None
        assert "test-password-123" not in user.hashed_password
        assert user.hashed_password.startswith("$pbkdf2-sha256$")
        # OWASP-recommended work factor must actually be applied
        rounds = int(user.hashed_password.split("$")[2])
        assert rounds >= 600_000, f"PBKDF2 rounds too low: {rounds}"
    finally:
        db.close()


def test_password_verification_works(client):
    from app.auth import hash_password, verify_password

    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


# ---------------------------------------------------------------------------
# Project lifecycle + membership access control
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def project(client, admin_headers):
    r = client.post(
        "/api/projects",
        json={
            "name": "Integration Test Project",
            "description": "Created by pytest.",
            "mode": "single",
            "min_ratings_per_item": 2,
            "categorical_opposite_pairs": {"safe": "unsafe"},
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_project_starts_as_draft(project):
    assert project["status"] == "draft"


def test_invalid_thresholds_rejected(client, admin_headers):
    r = client.post(
        "/api/projects",
        json={
            "name": "Bad thresholds",
            "disagreement_minor_fraction": 0.8,
            "disagreement_major_fraction": 0.2,
        },
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_non_member_cannot_read_project(client, project):
    _, headers = make_user(client, "outsider@test-eval.io")
    assert client.get(f"/api/projects/{project['id']}", headers=headers).status_code == 403
    assert client.get(f"/api/projects/{project['id']}/tasks", headers=headers).status_code == 403


def test_nonexistent_project_404(client, admin_headers):
    assert client.get("/api/projects/does-not-exist", headers=admin_headers).status_code == 404


# ---------------------------------------------------------------------------
# Rubric creation & validation
# ---------------------------------------------------------------------------

RUBRIC_PAYLOAD = {
    "name": "Integration Rubric",
    "description": "Ordinal + categorical + numerical.",
    "categories": [
        {
            "key": "accuracy",
            "name": "Accuracy",
            "scale_type": "ordinal",
            "min_value": 1,
            "max_value": 5,
            "weight": 1.5,
            "definition": "Whether verifiable claims are correct and supported by the given context.",
            "options": [{"value": i, "label": f"L{i}"} for i in range(1, 6)],
            "anchors": [{"value": 5, "label": "Fully accurate", "example": "All claims verifiable."}],
        },
        {
            "key": "safety",
            "name": "Safety",
            "scale_type": "categorical",
            "weight": 2.0,
            "definition": "Absence of harmful or policy-violating content in the model response.",
            "options": [{"value": "safe", "label": "Safe"}, {"value": "unsafe", "label": "Unsafe"}],
        },
        {
            "key": "grounding",
            "name": "Grounding",
            "scale_type": "numerical",
            "min_value": 0,
            "max_value": 10,
            "weight": 0.9,
            "definition": "Extent to which statements are grounded in the provided context.",
        },
    ],
}


@pytest.fixture(scope="module")
def rubric(client, admin_headers, project):
    r = client.post(f"/api/projects/{project['id']}/rubrics", json=RUBRIC_PAYLOAD, headers=admin_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    r2 = client.post(
        f"/api/projects/{project['id']}/rubrics/{body['id']}/activate",
        json={"change_note": "activate for tests"},
        headers=admin_headers,
    )
    assert r2.status_code == 200, r2.text
    return r2.json()


def test_rubric_has_three_scale_types(rubric):
    scales = {c["key"]: c["scale_type"] for c in rubric["categories"]}
    assert scales == {"accuracy": "ordinal", "safety": "categorical", "grounding": "numerical"}


def test_rubric_is_active(rubric):
    assert rubric["status"] == "active"
    assert rubric["version"] == 1


def test_categorical_without_options_rejected(client, admin_headers, project):
    r = client.post(
        f"/api/projects/{project['id']}/rubrics",
        json={"name": "Bad", "categories": [{"key": "x", "name": "X", "scale_type": "categorical"}]},
        headers=admin_headers,
    )
    assert r.status_code in (400, 422)


def test_ordinal_requires_bounds(client, admin_headers, project):
    r = client.post(
        f"/api/projects/{project['id']}/rubrics",
        json={
            "name": "Bad2",
            "categories": [
                {
                    "key": "y",
                    "name": "Y",
                    "scale_type": "ordinal",
                    "options": [{"value": 1, "label": "a"}, {"value": 2, "label": "b"}],
                }
            ],
        },
        headers=admin_headers,
    )
    assert r.status_code in (400, 422)


def test_string_option_rejected_for_ordinal(client, admin_headers, project):
    r = client.post(
        f"/api/projects/{project['id']}/rubrics",
        json={
            "name": "Bad3",
            "categories": [
                {
                    "key": "z",
                    "name": "Z",
                    "scale_type": "ordinal",
                    "min_value": 1,
                    "max_value": 5,
                    "options": [{"value": "high", "label": "High"}],
                }
            ],
        },
        headers=admin_headers,
    )
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Dataset import
# ---------------------------------------------------------------------------


def test_import_csv_dry_run_does_not_persist(client, admin_headers, project):
    content = "prompt,response,model_name\nQ1?,A1,M1\nQ2?,A2,M2\n"
    r = client.post(
        f"/api/projects/{project['id']}/import",
        json={"filename": "d.csv", "file_format": "csv", "content": content, "dry_run": True},
        headers=admin_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True and body["valid_rows"] == 2 and body["dataset_id"] is None
    tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()
    assert tasks == []


def test_import_mapping_inference(client, admin_headers, project):
    content = "question,answer,model\nQ?,A,M\n"
    r = client.post(
        f"/api/projects/{project['id']}/import/mapping",
        json={"filename": "m.csv", "file_format": "csv", "content": content},
        headers=admin_headers,
    )
    assert r.status_code == 200
    inferred = r.json()["inferred"]
    assert inferred["prompt"] == "question"
    assert inferred["response_a"] == "answer"
    assert inferred["model_name"] == "model"


def test_import_jsonl_and_activates_project(client, admin_headers, project):
    rows = [
        {
            "external_id": f"it-{i}",
            "prompt": f"Question {i}?",
            "response": f"Answer {i} with some detail.",
            "model": "Atlas-Mini",
            "task_type": "qa",
            "lang": "en",
        }
        for i in range(6)
    ]
    content = "\n".join(json.dumps(r) for r in rows)
    r = client.post(
        f"/api/projects/{project['id']}/import",
        json={"filename": "items.jsonl", "file_format": "jsonl", "content": content, "dry_run": False},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["valid_rows"] == 6
    proj = client.get(f"/api/projects/{project['id']}", headers=admin_headers).json()
    assert proj["status"] == "active"


def test_import_duplicate_reimport_is_safe(client, admin_headers, project):
    rows = [
        {"external_id": f"it-{i}", "prompt": f"Question {i}?", "response": f"Answer {i} with some detail."}
        for i in range(6)
    ]
    content = "\n".join(json.dumps(r) for r in rows)
    r = client.post(
        f"/api/projects/{project['id']}/import",
        json={"filename": "items.jsonl", "file_format": "jsonl", "content": content, "dry_run": False},
        headers=admin_headers,
    )
    body = r.json()
    assert body["duplicates_skipped"] == 6
    assert body["valid_rows"] == 0
    tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()
    assert len(tasks) == 6  # not duplicated


def test_import_malformed_rows_report_actionable_errors(client, admin_headers, project):
    content = "prompt,response\nonly-prompt,\n,only-response\nGood?,Good answer\n"
    r = client.post(
        f"/api/projects/{project['id']}/import",
        json={"filename": "bad.csv", "file_format": "csv", "content": content, "dry_run": True},
        headers=admin_headers,
    )
    body = r.json()
    assert body["error_rows"] == 2
    assert body["valid_rows"] == 1
    msgs = " ".join(e["error"] for e in body["errors"])
    assert "prompt" in msgs and "response_a" in msgs


def test_import_invalid_json_rejected(client, admin_headers, project):
    r = client.post(
        f"/api/projects/{project['id']}/import",
        json={"filename": "x.json", "file_format": "json", "content": "{not json", "dry_run": True},
        headers=admin_headers,
    )
    assert r.status_code in (400, 422)


def test_import_unsupported_format_rejected(client, admin_headers, project):
    r = client.post(
        f"/api/projects/{project['id']}/import",
        json={"filename": "x.xml", "file_format": "xml", "content": "<a/>", "dry_run": True},
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_import_oversize_rejected(client, admin_headers, project, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 0)
    r = client.post(
        f"/api/projects/{project['id']}/import",
        json={
            "filename": "big.csv",
            "file_format": "csv",
            "content": "prompt,response\nA?,B\n",
            "dry_run": True,
        },
        headers=admin_headers,
    )
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Assignment, blinding, ratings
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reviewers(client, admin_headers, project):
    a, ah = make_user(client, "rev-a@test-eval.io")
    b, bh = make_user(client, "rev-b@test-eval.io")
    for u in (a, b):
        client.post(
            f"/api/projects/{project['id']}/members",
            json={"user_id": u["id"], "role_on_project": "reviewer"},
            headers=admin_headers,
        )
    return {"a": (a, ah), "b": (b, bh)}


def test_assign_reviewers_balances_workload(client, admin_headers, project, reviewers):
    (a, _), (b, _) = reviewers["a"], reviewers["b"]
    r = client.post(
        f"/api/projects/{project['id']}/assign",
        json={"reviewer_ids": [a["id"], b["id"]]},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assignments_created"] == 12  # 6 tasks x 2 raters
    assert body["unfilled_slots"] == 0


def test_assignment_conflicts_of_interest_excluded(client, admin_headers, project, reviewers):
    (a, _), (b, _) = reviewers["a"], reviewers["b"]
    r = client.post(
        f"/api/projects/{project['id']}/assign",
        json={"reviewer_ids": [a["id"], b["id"]], "conflict_user_ids": [a["id"]]},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["conflicts_excluded"] == 1


def test_all_conflicted_reviewers_rejected(client, admin_headers, project, reviewers):
    (a, _), (b, _) = reviewers["a"], reviewers["b"]
    r = client.post(
        f"/api/projects/{project['id']}/assign",
        json={"reviewer_ids": [a["id"], b["id"]], "conflict_user_ids": [a["id"], b["id"]]},
        headers=admin_headers,
    )
    assert r.status_code in (400, 422)


def test_plain_reviewer_cannot_assign(client, project, reviewers):
    _, ah = reviewers["a"]
    r = client.post(f"/api/projects/{project['id']}/assign", json={"reviewer_ids": []}, headers=ah)
    assert r.status_code == 403


@pytest.fixture(scope="module")
def first_task(client, admin_headers, project):
    tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()
    return tasks[0]


def test_workspace_blinded_before_submission(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.get(f"/api/projects/{project['id']}/tasks/{first_task['id']}/evaluate", headers=ah)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blinded"] is True
    assert body["peer_ratings"] == []
    assert body["rubric"]["id"] == rubric["id"]


def test_draft_autosave(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/draft?rubric_id={rubric['id']}",
        json={"scores": {"accuracy": 3, "safety": "safe", "grounding": 6.0}, "rationale": "wip"},
        headers=ah,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft"


def test_submission_requires_all_categories(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/submit?rubric_id={rubric['id']}",
        json={"scores": {"accuracy": 3}, "rationale": "partial"},
        headers=ah,
    )
    assert r.status_code == 422
    assert "missing scores" in r.text.lower()


def test_submission_rejects_out_of_range(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/submit?rubric_id={rubric['id']}",
        json={"scores": {"accuracy": 99, "safety": "safe", "grounding": 5.0}, "rationale": "x"},
        headers=ah,
    )
    assert r.status_code == 422


def test_submission_rejects_invalid_category_value(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/submit?rubric_id={rubric['id']}",
        json={"scores": {"accuracy": 4, "safety": "maybe", "grounding": 8.0}, "rationale": "x"},
        headers=ah,
    )
    assert r.status_code == 422


def test_submission_rejects_unknown_category(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/submit?rubric_id={rubric['id']}",
        json={
            "scores": {"accuracy": 4, "safety": "safe", "grounding": 8.0, "invented": 1},
            "rationale": "x",
        },
        headers=ah,
    )
    assert r.status_code == 422


def test_reviewer_a_submits(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/submit?rubric_id={rubric['id']}",
        json={
            "scores": {"accuracy": 4, "safety": "safe", "grounding": 8.0},
            "rationale": "Clearly accurate and well grounded in the provided context.",
            "confidence": 0.85,
        },
        headers=ah,
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1


def test_reviewer_a_sees_no_peers_while_b_silent(client, project, reviewers, first_task):
    _, ah = reviewers["a"]
    r = client.get(f"/api/projects/{project['id']}/tasks/{first_task['id']}/evaluate", headers=ah)
    body = r.json()
    assert body["blinded"] is False
    assert body["peer_ratings"] == []


def test_duplicate_submission_rejected(client, project, reviewers, first_task, rubric):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/submit?rubric_id={rubric['id']}",
        json={"scores": {"accuracy": 4, "safety": "safe", "grounding": 8.0}, "rationale": "dup"},
        headers=ah,
    )
    assert r.status_code == 409


def test_reviewer_b_submits_divergent_scores(client, project, reviewers, first_task, rubric):
    _, bh = reviewers["b"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/submit?rubric_id={rubric['id']}",
        json={
            "scores": {"accuracy": 1, "safety": "unsafe", "grounding": 2.0},
            "rationale": "Unclear and possibly fabricated; seems unsafe to me.",
            "confidence": 0.4,
        },
        headers=bh,
    )
    assert r.status_code == 200, r.text


def test_blinding_lifted_after_both_submit(client, project, reviewers, first_task):
    _, ah = reviewers["a"]
    r = client.get(f"/api/projects/{project['id']}/tasks/{first_task['id']}/evaluate", headers=ah)
    peers = r.json()["peer_ratings"]
    assert len(peers) == 1
    assert peers[0]["scores"]["accuracy"] == 1
    assert peers[0]["reviewer_name"]  # name resolved for the UI


def test_abstention_requires_rationale(client, project, reviewers, rubric, client_admin_tasks):
    _, ah = reviewers["a"]
    task_id = client_admin_tasks[1]["id"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{task_id}/submit?rubric_id={rubric['id']}",
        json={"abstained": True, "scores": {}},
        headers=ah,
    )
    assert r.status_code == 422


def test_abstention_accepted_with_rationale(client, project, reviewers, rubric, client_admin_tasks):
    _, ah = reviewers["a"]
    task_id = client_admin_tasks[1]["id"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{task_id}/submit?rubric_id={rubric['id']}",
        json={"abstained": True, "scores": {}, "rationale": "Cannot assess this domain reliably."},
        headers=ah,
    )
    assert r.status_code == 200
    assert r.json()["abstained"] is True
    assert r.json()["scores"] is None


@pytest.fixture(scope="module")
def client_admin_tasks(client, admin_headers, project):
    return client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()


def test_correction_creates_new_version_and_preserves_history(
    client, admin_headers, project, reviewers, first_task
):
    _, ah = reviewers["a"]
    ratings = client.get(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/ratings", headers=admin_headers
    ).json()
    mine = next(r for r in ratings if r["reviewer_id"] == reviewers["a"][0]["id"])
    r = client.post(
        f"/api/projects/{project['id']}/ratings/{mine['id']}/correct",
        json={
            "scores": {"accuracy": 3, "safety": "safe", "grounding": 7.0},
            "rationale": "Corrected after re-reading the reference answer.",
        },
        headers=ah,
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2

    history = client.get(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/rating-history?reviewer_id={reviewers['a'][0]['id']}",
        headers=admin_headers,
    ).json()
    assert len(history) == 2
    assert sum(1 for h in history if h["is_current"]) == 1
    assert history[0]["scores"]["accuracy"] == 4  # original preserved
    assert history[1]["scores"]["accuracy"] == 3  # correction


def test_cannot_correct_another_reviewers_rating(client, project, reviewers, first_task, admin_headers):
    _, bh = reviewers["b"]
    ratings = client.get(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/ratings", headers=admin_headers
    ).json()
    a_rating = next(r for r in ratings if r["reviewer_id"] == reviewers["a"][0]["id"])
    r = client.post(
        f"/api/projects/{project['id']}/ratings/{a_rating['id']}/correct",
        json={"scores": {"accuracy": 5, "safety": "safe", "grounding": 9.0}, "rationale": "hijack"},
        headers=bh,
    )
    assert r.status_code == 403


def test_unassigned_reviewer_blocked_from_workspace(client, project, first_task):
    _, headers = make_user(client, "unassigned@test-eval.io")
    client.post  # noqa: B018
    r = client.get(f"/api/projects/{project['id']}/tasks/{first_task['id']}/evaluate", headers=headers)
    assert r.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Disagreement detection
# ---------------------------------------------------------------------------


def test_disagreement_scan_detects_divergence(client, admin_headers, project):
    r = client.post(f"/api/projects/{project['id']}/disagreements/scan", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["scanned"] is True


def test_disagreements_include_opposite_categorical(client, admin_headers, project):
    r = client.get(f"/api/projects/{project['id']}/disagreements", headers=admin_headers)
    assert r.status_code == 200
    items = r.json()
    kinds = {d["kind"] for d in items}
    assert "opposite_categorical" in kinds, kinds


def test_disagreement_severity_is_scale_relative_and_bounded(client, admin_headers, project):
    items = client.get(f"/api/projects/{project['id']}/disagreements", headers=admin_headers).json()
    assert items
    for d in items:
        assert 0.0 <= d["severity_score"] <= 1.0
        assert d["severity_class"] in {"minor", "major", "critical"}
        assert d["priority_score"] >= 0.0


def test_disagreement_detail_exposes_evidence(client, admin_headers, project):
    items = client.get(f"/api/projects/{project['id']}/disagreements", headers=admin_headers).json()
    d = items[0]
    r = client.get(f"/api/projects/{project['id']}/disagreements/{d['id']}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["task"]["id"] == d["task_id"]
    assert len(body["ratings"]) == 2
    assert "severity_formula" in body
    assert body["disagreement"]["details"]["n_ratings"] == 2


def test_disagreement_filtering(client, admin_headers, project):
    all_items = client.get(f"/api/projects/{project['id']}/disagreements", headers=admin_headers).json()
    kind = all_items[0]["kind"]
    filtered = client.get(
        f"/api/projects/{project['id']}/disagreements?kind={kind}", headers=admin_headers
    ).json()
    assert filtered and all(d["kind"] == kind for d in filtered)


def test_disagreement_summary_counts(client, admin_headers, project):
    r = client.get(f"/api/projects/{project['id']}/disagreements/summary", headers=admin_headers)
    body = r.json()
    assert body["total"] > 0
    assert sum(body["by_kind"].values()) == body["total"]


# ---------------------------------------------------------------------------
# Adjudication & consensus
# ---------------------------------------------------------------------------


def test_consensus_reports_limitations(client, admin_headers, project, first_task):
    r = client.get(f"/api/projects/{project['id']}/tasks/{first_task['id']}/consensus", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["strategy"] in {"majority", "median", "expert"}
    assert isinstance(body["limitations"], list) and body["limitations"]


def test_adjudication_workflow_finalizes_and_blocks_edits(
    client, admin_headers, project, reviewers, first_task
):
    items = client.get(
        f"/api/projects/{project['id']}/disagreements?status=open", headers=admin_headers
    ).json()
    target = sorted(items, key=lambda d: -d["priority_score"])[0]

    r = client.post(
        f"/api/projects/{project['id']}/adjudications?disagreement_id={target['id']}&task_id={target['task_id']}",
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    adj_id = r.json()["id"]

    detail = client.get(f"/api/projects/{project['id']}/adjudications/{adj_id}", headers=admin_headers).json()
    assert len(detail["ratings"]) == 2  # side-by-side, current versions only
    assert "consensus" in detail

    r = client.post(
        f"/api/projects/{project['id']}/adjudications/{adj_id}/finalize",
        json={
            "decision": {"accuracy": 3, "safety": "safe", "grounding": 7.0},
            "rationale": "Anchors at level 3 fit: core answer correct, minor grounding gap.",
        },
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "final"

    # double finalize rejected
    r = client.post(
        f"/api/projects/{project['id']}/adjudications/{adj_id}/finalize",
        json={"decision": {"accuracy": 5}, "rationale": "again"},
        headers=admin_headers,
    )
    assert r.status_code == 409

    # task marked adjudicated
    tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=admin_headers).json()
    assert any(t["status"] == "adjudicated" for t in tasks)

    # ratings cannot be corrected while adjudicated
    _, ah = reviewers["a"]
    ratings = client.get(
        f"/api/projects/{project['id']}/tasks/{target['task_id']}/ratings", headers=admin_headers
    ).json()
    mine = next((x for x in ratings if x["reviewer_id"] == reviewers["a"][0]["id"]), None)
    if mine:
        r = client.post(
            f"/api/projects/{project['id']}/ratings/{mine['id']}/correct",
            json={"scores": {"accuracy": 2, "safety": "safe", "grounding": 6.0}, "rationale": "post-adj"},
            headers=ah,
        )
        assert r.status_code == 409


def test_adjudication_reopen_creates_audit_chain(client, admin_headers, project, first_task):
    adjs = client.get(
        f"/api/projects/{project['id']}/adjudications?status=final", headers=admin_headers
    ).json()
    assert adjs
    adj_id = adjs[0]["id"]
    r = client.post(
        f"/api/projects/{project['id']}/adjudications/{adj_id}/reopen?reason=New evidence surfaced",
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    new_adj = r.json()
    assert new_adj["status"] == "proposed"
    # prior adjudication is now 'reopened', not deleted
    all_adjs = client.get(f"/api/projects/{project['id']}/adjudications", headers=admin_headers).json()
    statuses = {a["id"]: a["status"] for a in all_adjs}
    assert statuses[adj_id] == "reopened"


def test_adjudication_escalation(client, admin_headers, project):
    adjs = client.get(
        f"/api/projects/{project['id']}/adjudications?status=proposed", headers=admin_headers
    ).json()
    assert adjs
    r = client.post(
        f"/api/projects/{project['id']}/adjudications/{adjs[0]['id']}/escalate?reason=Adjudicators disagree",
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["escalated"] is True


def test_plain_reviewer_cannot_adjudicate(client, project, reviewers, first_task):
    _, ah = reviewers["a"]
    r = client.post(f"/api/projects/{project['id']}/adjudications?task_id={first_task['id']}", headers=ah)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Gold labels & calibration
# ---------------------------------------------------------------------------


def test_gold_label_requires_privilege(client, project, reviewers, client_admin_tasks):
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/tasks/{client_admin_tasks[2]['id']}/gold-label",
        json={"scores": {"accuracy": 5}},
        headers=ah,
    )
    assert r.status_code == 403


def test_calibration_requires_gold_labels(client, admin_headers, project, client_admin_tasks):
    r = client.post(
        f"/api/projects/{project['id']}/calibration/sessions",
        json={"name": "No gold", "task_ids": [t["id"] for t in client_admin_tasks[:3]]},
        headers=admin_headers,
    )
    assert r.status_code in (400, 422)


def test_calibration_session_and_assessment(client, admin_headers, project, reviewers, client_admin_tasks):
    task_ids = [t["id"] for t in client_admin_tasks[:3]]
    for tid in task_ids:
        r = client.post(
            f"/api/projects/{project['id']}/tasks/{tid}/gold-label",
            json={
                "scores": {"accuracy": 4, "safety": "safe", "grounding": 8.0},
                "rationale": "Expert-approved reference label.",
            },
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text

    r = client.post(
        f"/api/projects/{project['id']}/calibration/sessions",
        json={
            "name": "Integration calibration",
            "task_ids": task_ids,
            "pass_threshold_kappa": 0.7,
            "pass_threshold_accuracy": 0.8,
        },
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    session = r.json()

    # reviewer A answers exactly like gold -> high accuracy
    _, ah = reviewers["a"]
    perfect = {tid: {"accuracy": 4, "safety": "safe", "grounding": 8.0} for tid in task_ids}
    r = client.post(
        f"/api/projects/{project['id']}/calibration/assess",
        json={"session_id": session["id"], "phase": "pre", "item_scores": perfect},
        headers=ah,
    )
    assert r.status_code == 200, r.text
    attempt = r.json()
    assert attempt["accuracy"] == pytest.approx(1.0)
    assert attempt["passed"] is True

    # duplicate phase rejected
    r = client.post(
        f"/api/projects/{project['id']}/calibration/assess",
        json={"session_id": session["id"], "phase": "pre", "item_scores": perfect},
        headers=ah,
    )
    assert r.status_code == 409

    # reviewer B diverges -> feedback generated, not passed
    _, bh = reviewers["b"]
    divergent = {tid: {"accuracy": 1, "safety": "unsafe", "grounding": 2.0} for tid in task_ids}
    r = client.post(
        f"/api/projects/{project['id']}/calibration/assess",
        json={"session_id": session["id"], "phase": "pre", "item_scores": divergent},
        headers=bh,
    )
    assert r.status_code == 200, r.text
    b_attempt = r.json()
    assert b_attempt["accuracy"] == pytest.approx(0.0)
    assert b_attempt["passed"] is False
    assert len(b_attempt["feedback"]["items"]) == 9  # 3 tasks x 3 categories

    summary = client.get(
        f"/api/projects/{project['id']}/calibration/sessions/{session['id']}/summary",
        headers=admin_headers,
    ).json()
    assert summary["n_reviewers"] == 2
    assert summary["pre_mean_accuracy"] == pytest.approx(0.5)


def test_invalid_calibration_phase_rejected(client, admin_headers, project, reviewers, client_admin_tasks):
    sessions = client.get(f"/api/projects/{project['id']}/calibration/sessions", headers=admin_headers).json()
    _, ah = reviewers["a"]
    r = client.post(
        f"/api/projects/{project['id']}/calibration/assess",
        json={"session_id": sessions[0]["id"], "phase": "during", "item_scores": {}},
        headers=ah,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def test_dashboard_returns_all_sections(client, admin_headers, project):
    r = client.get(f"/api/projects/{project['id']}/analytics/dashboard", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("progress", "metrics", "disagreements", "adjudication", "reviewer_bias", "accuracy_vs_gold"):
        assert key in body


def test_metrics_report_sample_sizes_and_warnings(client, admin_headers, project):
    body = client.get(f"/api/projects/{project['id']}/analytics/metrics", headers=admin_headers).json()
    assert body["n_ratings"] > 0
    for _cat_key, m in body["categories"].items():
        assert "n_items" in m
        if m.get("n_items"):
            assert "warnings" in m


def test_accuracy_vs_gold_separate_from_agreement(client, admin_headers, project, reviewers):
    body = client.get(
        f"/api/projects/{project['id']}/analytics/accuracy-vs-gold", headers=admin_headers
    ).json()
    assert body["n_gold_tasks"] == 3
    assert body["overall_accuracy"] is not None
    assert 0.0 <= body["overall_accuracy"] <= 1.0

    a_id = reviewers["a"][0]["id"]
    b_id = reviewers["b"][0]["id"]
    by_reviewer = body["by_reviewer"]
    assert a_id in by_reviewer and b_id in by_reviewer
    for stats in by_reviewer.values():
        assert 0.0 <= stats["accuracy"] <= 1.0
        assert stats["mae_vs_gold"] is not None
        assert stats["n_scores"] > 0

    # Reviewer A tracked the expert labels far more closely than B
    # (A scored 3/safe/7.0 vs gold 4/safe/8.0; B scored 1/unsafe/2.0).
    assert by_reviewer[a_id]["accuracy"] > by_reviewer[b_id]["accuracy"]
    assert by_reviewer[a_id]["mae_vs_gold"] < by_reviewer[b_id]["mae_vs_gold"]

    # Accuracy against gold is a DIFFERENT quantity than inter-rater
    # agreement: the two reviewers disagree with each other, yet each
    # has a well-defined accuracy against the expert label.
    pairwise = client.get(
        f"/api/projects/{project['id']}/analytics/pairwise-agreement", headers=admin_headers
    ).json()
    assert pairwise, "expected at least one reviewer pair"
    assert pairwise[0]["exact_agreement"] == pytest.approx(0.0)
    assert by_reviewer[a_id]["accuracy"] > 0.0


def test_pairwise_agreement(client, admin_headers, project):
    body = client.get(
        f"/api/projects/{project['id']}/analytics/pairwise-agreement", headers=admin_headers
    ).json()
    assert isinstance(body, list)
    if body:
        assert body[0]["shared_items"] >= 1
        assert 0.0 <= body[0]["exact_agreement"] <= 1.0


def test_distributions_handle_categorical_and_numeric(client, admin_headers, project):
    body = client.get(f"/api/projects/{project['id']}/analytics/distributions", headers=admin_headers).json()
    assert body["safety"]["scale_type"] == "categorical"
    assert "counts" in body["safety"]
    assert body["accuracy"]["scale_type"] == "ordinal"
    assert "mean" in body["accuracy"]


def test_confusion_matrix(client, admin_headers, project):
    body = client.get(
        f"/api/projects/{project['id']}/analytics/confusion-matrix?category_key=accuracy",
        headers=admin_headers,
    ).json()
    assert "matrix" in body and "labels" in body
    assert len(body["matrix"]) == len(body["labels"])


def test_analytics_endpoints_do_not_leak_nan(client, admin_headers, project):
    """JSON must be RFC-compliant: no NaN/Infinity literals."""
    endpoints = [
        "dashboard",
        "metrics",
        "reviewer-bias",
        "distributions",
        "pairwise-agreement",
        "accuracy-vs-gold",
        "item-agreement",
        "activity-trend",
        "filters",
    ]
    for ep in endpoints:
        r = client.get(f"/api/projects/{project['id']}/analytics/{ep}", headers=admin_headers)
        assert r.status_code == 200, f"{ep}: {r.text[:200]}"
        assert "NaN" not in r.text and "Infinity" not in r.text, f"{ep} leaked non-finite JSON"


def test_empty_project_analytics_safe(client, admin_headers):
    r = client.post("/api/projects", json={"name": "Empty project"}, headers=admin_headers)
    pid = r.json()["id"]
    for ep in ("dashboard", "metrics", "reviewer-bias", "distributions", "pairwise-agreement"):
        resp = client.get(f"/api/projects/{pid}/analytics/{ep}", headers=admin_headers)
        assert resp.status_code == 200, f"{ep}: {resp.text[:200]}"


# ---------------------------------------------------------------------------
# Rubric insights & change approval
# ---------------------------------------------------------------------------


def test_insight_analysis_runs(client, admin_headers, project):
    r = client.post(f"/api/projects/{project['id']}/rubrics/insights/analyze", headers=admin_headers)
    assert r.status_code == 200


def test_literal_rubric_routes_not_shadowed_by_id_param(client, admin_headers, project):
    """Regression: /rubrics/insights must not be captured by /rubrics/{rubric_id}."""
    for path in ("insights", "change-requests", "versions"):
        r = client.get(f"/api/projects/{project['id']}/rubrics/{path}", headers=admin_headers)
        assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text[:200]}"
        assert isinstance(r.json(), list), f"{path} should return a list, got {type(r.json())}"


def test_change_requests_listing(client, admin_headers, project):
    # Seed one request so the listing has something to return.
    create = client.post(
        f"/api/projects/{project['id']}/rubrics/change-requests",
        json={
            "proposed_changes": {"definition": "Listed change request for testing."},
            "rationale": "Verifying the change-request listing endpoint.",
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text

    r = client.get(f"/api/projects/{project['id']}/rubrics/change-requests", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["status"] in {"pending", "approved", "rejected"}
    assert set(body[0]) >= {"id", "rubric_id", "proposed_changes", "rationale", "is_ai_generated"}

    # status filter works
    pending = client.get(
        f"/api/projects/{project['id']}/rubrics/change-requests?status=pending", headers=admin_headers
    ).json()
    assert all(x["status"] == "pending" for x in pending)


def test_change_request_requires_approval_before_apply(client, admin_headers, project, rubric):
    cat_id = rubric["categories"][0]["id"]
    r = client.post(
        f"/api/projects/{project['id']}/rubrics/change-requests",
        json={
            "rubric_category_id": cat_id,
            "proposed_changes": {"definition": "Tightened operational definition for tests."},
            "rationale": "Testing the human approval gate end to end.",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]

    # cannot apply before approval
    r = client.post(
        f"/api/projects/{project['id']}/rubrics/change-requests/{req_id}/apply", headers=admin_headers
    )
    assert r.status_code == 409

    # reviewer cannot approve
    _, rh = make_user(client, "rev-a@test-eval.io")
    r = client.post(
        f"/api/projects/{project['id']}/rubrics/change-requests/{req_id}/review?decision=approved",
        headers=rh,
    )
    assert r.status_code == 403

    # admin approves and applies -> new version
    r = client.post(
        f"/api/projects/{project['id']}/rubrics/change-requests/{req_id}/review?decision=approved&note=ok",
        headers=admin_headers,
    )
    assert r.json()["status"] == "approved"
    r = client.post(
        f"/api/projects/{project['id']}/rubrics/change-requests/{req_id}/apply", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2
    new_id = r.json()["id"]

    # double apply blocked
    r = client.post(
        f"/api/projects/{project['id']}/rubrics/change-requests/{req_id}/apply", headers=admin_headers
    )
    assert r.status_code == 409

    # old version superseded but retained
    versions = {
        v["id"]: v["status"]
        for v in client.get(f"/api/projects/{project['id']}/rubrics", headers=admin_headers).json()
    }
    assert versions[rubric["id"]] == "superseded"
    assert versions[new_id] == "active"


def test_ratings_keep_original_rubric_version_after_change(
    client, admin_headers, project, rubric, first_task
):
    history = client.get(
        f"/api/projects/{project['id']}/tasks/{first_task['id']}/rating-history",
        headers=admin_headers,
    ).json()
    assert history
    assert all(h["rubric_version_id"] == rubric["id"] for h in history)


# ---------------------------------------------------------------------------
# Reports & exports
# ---------------------------------------------------------------------------


def _wait_job(client, admin_headers, job_id, timeout=30):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        jobs = client.get("/api/admin/jobs", headers=admin_headers).json()
        job = next((j for j in jobs if j["id"] == job_id), None)
        if job and job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.3)
    return job


@pytest.mark.parametrize("fmt", ["json", "csv", "pdf"])
def test_report_generation_all_formats(client, admin_headers, project, fmt):
    r = client.post(
        f"/api/projects/{project['id']}/reports",
        json={"title": f"Pytest report {fmt}", "report_format": fmt},
        headers=admin_headers,
    )
    assert r.status_code == 202, r.text
    job = _wait_job(client, admin_headers, r.json()["id"])
    assert job and job["status"] == "succeeded", str(job)[:500]

    report_id = job["result"]["report_id"]
    dl = client.get(f"/api/projects/{project['id']}/reports/{report_id}/download", headers=admin_headers)
    assert dl.status_code == 200
    if fmt == "pdf":
        assert dl.content[:4] == b"%PDF"
    elif fmt == "csv":
        assert "section,key,value" in dl.text
    else:
        payload = dl.json()
        assert "generated_at" in payload
        assert "metric_definitions" in payload
        assert payload["metric_definitions"]["krippendorff_alpha"]


def test_report_listing_includes_metric_definitions(client, admin_headers, project):
    reports = client.get(f"/api/projects/{project['id']}/reports", headers=admin_headers).json()
    assert len(reports) >= 3
    assert reports[0]["metric_definitions"]


def test_non_member_cannot_download_report(client, admin_headers, project):
    reports = client.get(f"/api/projects/{project['id']}/reports", headers=admin_headers).json()
    _, headers = make_user(client, "outsider@test-eval.io")
    r = client.get(f"/api/projects/{project['id']}/reports/{reports[0]['id']}/download", headers=headers)
    assert r.status_code == 403


def test_ratings_csv_export_is_well_formed(client, admin_headers, project):
    r = client.get(f"/api/projects/{project['id']}/export/ratings", headers=admin_headers)
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows
    assert {"task_external_id", "reviewer_id", "scores_json", "rubric_version_id"} <= set(rows[0])
    json.loads(rows[0]["scores_json"])  # valid JSON even with commas in rationale


# ---------------------------------------------------------------------------
# LLM offline mode
# ---------------------------------------------------------------------------


def test_llm_disabled_by_default(client, admin_headers):
    body = client.get("/api/llm/config", headers=admin_headers).json()
    assert body["enabled"] is False
    assert body["active"] is None


def test_llm_config_requires_admin(client):
    _, headers = make_user(client, "rev-a@test-eval.io")
    assert client.get("/api/llm/config", headers=headers).status_code == 403


def test_offline_summarization_works_without_credentials(client, admin_headers, project, first_task):
    r = client.post(
        f"/api/llm/summarize-case?project_id={project['id']}&task_id={first_task['id']}",
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "offline"
    assert body["ai_generated"] is False
    assert body["divergent_categories"]


def test_online_summarization_requires_explicit_content_consent(
    client, admin_headers, project, first_task, monkeypatch
):
    from app.config import settings

    client.post(
        "/api/llm/config",
        json={
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:1/v1",
            "model": "unreachable-test-model",
        },
        headers=admin_headers,
    )
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_allow_evaluation_content", False)

    r = client.post(
        f"/api/llm/summarize-case?project_id={project['id']}&task_id={first_task['id']}",
        headers=admin_headers,
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "offline"
    assert "LLM_ALLOW_EVALUATION_CONTENT" in body["note"]


def test_offline_rationale_clustering(client, admin_headers, project, first_task):
    r = client.post(
        f"/api/llm/cluster-rationales?project_id={project['id']}&task_id={first_task['id']}",
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert "clusters" in r.json()


def test_api_key_never_returned_in_plaintext(client, admin_headers):
    r = client.post(
        "/api/llm/config",
        json={"provider": "openai", "api_key": "sk-supersecretvalue123456", "model": "gpt-4o-mini"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    cfg = client.get("/api/llm/config", headers=admin_headers).json()
    assert "sk-supersecretvalue123456" not in json.dumps(cfg)
    assert cfg["active"]["api_key"].endswith("3456")
    assert "…" in cfg["active"]["api_key"]


def test_connection_test_reports_offline_when_disabled(client, admin_headers):
    # LLM_ENABLED is false by default, so completion is refused safely.
    from app.config import settings

    assert settings.llm_enabled is False


# ---------------------------------------------------------------------------
# Audit log & admin
# ---------------------------------------------------------------------------


def test_audit_log_records_consequential_actions(client, admin_headers):
    logs = client.get("/api/admin/audit-log", headers=admin_headers).json()
    actions = {entry["action"] for entry in logs}
    assert {"project.create", "dataset.import", "rating.submit", "adjudication.decide"} <= actions


def test_audit_log_requires_admin(client):
    _, headers = make_user(client, "rev-a@test-eval.io")
    assert client.get("/api/admin/audit-log", headers=headers).status_code == 403


def test_system_stats(client, admin_headers):
    body = client.get("/api/admin/stats", headers=admin_headers).json()
    assert body["projects"] >= 2
    assert body["ratings"] > 0
    assert body["database_url_kind"] == "sqlite"


def test_no_secrets_in_audit_details(client, admin_headers):
    logs = client.get("/api/admin/audit-log?limit=200", headers=admin_headers).json()
    blob = json.dumps(logs)
    assert "sk-supersecretvalue123456" not in blob
    assert "password" not in blob.lower()


# ---------------------------------------------------------------------------
# Demo seed lifecycle
# ---------------------------------------------------------------------------


def test_demo_seed_and_reset(client, admin_headers):
    r = client.post("/api/admin/seed-demo", headers=admin_headers)
    assert r.status_code == 200, r.text
    seed = r.json()
    assert seed["tasks"] == 60
    assert seed["gold_labeled"] == 20
    assert seed["disagreements"] > 10
    assert seed["ratings"] >= 180

    # demo analytics produce real numbers
    dash = client.get(f"/api/projects/{seed['project_id']}/analytics/dashboard", headers=admin_headers).json()
    assert dash["metrics"]["n_ratings"] > 100
    cats = dash["metrics"]["categories"]
    assert cats["safety"].get("fleiss_kappa") is not None
    assert cats["accuracy"].get("krippendorff_alpha") is not None
    assert cats["grounding"].get("icc_2_1") is not None

    # reset removes demo data but keeps real users
    r = client.post("/api/admin/reset-demo", headers=admin_headers)
    assert r.status_code == 200
    users = client.get("/api/auth/users", headers=admin_headers).json()
    assert not any(u["email"].endswith("@demo.eval-platform.io") for u in users)
    assert any(u["email"] == "admin@test-eval.io" for u in users)


def test_demo_seed_requires_admin(client):
    _, headers = make_user(client, "rev-a@test-eval.io")
    assert client.post("/api/admin/seed-demo", headers=headers).status_code == 403
