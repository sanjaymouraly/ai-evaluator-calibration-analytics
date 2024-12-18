"""End-to-end API smoke test — exercises the full evaluation workflow."""

import json
import os
import sys

import httpx

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE, timeout=30)

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def main():
    print("== 1. Health & auth bootstrap ==")
    r = client.get("/api/admin/health")
    check("health", r.status_code == 200, r.text)

    admin_email = "root-admin@eval-platform.io"
    r = client.post("/api/auth/register", json={
        "email": admin_email, "full_name": "Platform Admin",
        "password": "admin-password-123", "role": "admin",
    })
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={
            "email": admin_email, "password": "admin-password-123"})
    check("register/login admin", r.status_code == 200, r.text)
    admin_token = r.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    r = client.get("/api/auth/me", headers=admin_headers)
    check("me endpoint", r.json()["role"] == "admin", r.text)

    # non-admin cannot list users
    r = client.post("/api/auth/register", json={
        "email": "random-user@x.com", "full_name": "Random",
        "password": "randompass1", "role": "reviewer"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={
            "email": "random-user@x.com", "password": "randompass1"})
    rnd_token = r.json()["access_token"]
    r = client.get("/api/auth/users", headers={"Authorization": f"Bearer {rnd_token}"})
    check("RBAC: non-admin blocked from /users", r.status_code == 403, r.text)

    print("== 2. Seed demo data ==")
    r = client.post("/api/admin/seed-demo", headers=admin_headers)
    check("seed demo", r.status_code == 200, r.text)
    seed = r.json()
    print(f"    -> {seed}")
    check("seed created 60 tasks", seed["tasks"] == 60, str(seed))
    check("seed detected disagreements", seed["disagreements"] > 10, str(seed))
    check("seed gold labels", seed["gold_labeled"] == 20, str(seed))

    print("== 3. Project & analytics ==")
    r = client.get("/api/projects", headers=admin_headers)
    projects = r.json()
    demo = [p for p in projects if p["name"].startswith("Demo:")]
    check("demo project listed", len(demo) == 1, r.text)
    project = demo[0]
    pid = project["id"]

    r = client.get(f"/api/projects/{pid}/analytics/dashboard", headers=admin_headers)
    dash = r.json()
    check("dashboard metrics", dash["metrics"]["n_ratings"] > 100, json.dumps(dash["metrics"])[:200])
    check("dashboard disagreements", dash["disagreements"]["total"] > 0)

    r = client.get(f"/api/projects/{pid}/analytics/metrics", headers=admin_headers)
    metrics = r.json()
    cats = metrics["categories"]
    check("categorical fleiss computed", "safety" in cats and cats["safety"].get("fleiss_kappa") is not None, json.dumps(cats.get("safety", {})))
    check("ordinal alpha computed", "accuracy" in cats and cats["accuracy"].get("krippendorff_alpha") is not None, json.dumps(cats.get("accuracy", {})))
    check("numerical ICC computed", "grounding" in cats and cats["grounding"].get("icc_2_1") is not None, json.dumps(cats.get("grounding", {})))

    print("== 4. Disagreements & adjudication ==")
    r = client.get(f"/api/projects/{pid}/disagreements", headers=admin_headers)
    dis = r.json()
    check("disagreements listed", len(dis) > 0)
    dg = dis[0]
    check("severity in 0..1", 0 <= dg["severity_score"] <= 1, str(dg["severity_score"]))
    check("priority present", dg["priority_score"] > 0)

    r = client.get(f"/api/projects/{pid}/disagreements/{dg['id']}", headers=admin_headers)
    detail = r.json()
    check("disagreement drill-down", detail["task"] is not None and len(detail["ratings"]) >= 2)
    check("severity formula present", "severity_formula" in detail)

    # create adjudication on an unresolved disagreement
    open_dgs = [d for d in dis if d["status"] == "open"]
    if open_dgs:
        target = open_dgs[0]
        r = client.post(
            f"/api/projects/{pid}/adjudications?disagreement_id={target['id']}&task_id={target['task_id']}",
            headers=admin_headers,
        )
        check("adjudication created", r.status_code == 201, r.text)
        adj_id = r.json()["id"]
        r = client.post(
            f"/api/projects/{pid}/adjudications/{adj_id}/finalize",
            json={"decision": {"accuracy": 4, "safety": "safe"}, "rationale": "Verified against reference answer; level-4 anchor fits."},
            headers=admin_headers,
        )
        check("adjudication finalized", r.status_code == 200 and r.json()["status"] == "final", r.text)
        # reopen
        r = client.post(
            f"/api/projects/{pid}/adjudications/{adj_id}/reopen?reason=New evidence submitted",
            headers=admin_headers,
        )
        check("adjudication reopen chain", r.status_code == 200, r.text)

    print("== 5. Fresh project: create -> import -> rubric -> assign -> rate ==")
    # 5a. create project
    r = client.post("/api/projects", json={
        "name": "Smoke Test Project", "description": "Built via API in the smoke test.",
        "mode": "single", "min_ratings_per_item": 2,
        "categorical_opposite_pairs": {"safe": "unsafe"},
    }, headers=admin_headers)
    check("project created", r.status_code == 201 and r.json()["status"] == "draft", r.text)
    fpid = r.json()["id"]

    # 5b. create rubric (categorical + ordinal + numerical)
    r = client.post(f"/api/projects/{fpid}/rubrics", json={
        "name": "Smoke Rubric", "description": "Three scale types.",
        "categories": [
            {"key": "accuracy", "name": "Accuracy", "scale_type": "ordinal",
             "min_value": 1, "max_value": 5, "weight": 1.5,
             "definition": "Whether verifiable claims are correct and supported by the prompt context provided.",
             "options": [{"value": i, "label": f"L{i}"} for i in range(1, 6)],
             "anchors": [{"value": 5, "label": "Fully accurate", "example": "All claims verifiable."}]},
            {"key": "safety", "name": "Safety", "scale_type": "categorical", "weight": 2.0,
             "definition": "Absence of harmful or policy-violating content in the response.",
             "options": [{"value": "safe", "label": "Safe"}, {"value": "unsafe", "label": "Unsafe"}]},
            {"key": "grounding", "name": "Grounding", "scale_type": "numerical",
             "min_value": 0, "max_value": 10, "weight": 0.9,
             "definition": "Extent to which statements are grounded in the provided context rather than invented.",
             "anchors": [{"value": 10, "label": "Fully grounded", "example": "Every claim traceable."}]},
        ],
    }, headers=admin_headers)
    check("rubric created", r.status_code == 201, r.text)
    frubric_id = r.json()["id"]
    frubric_cats = {c["key"]: c for c in r.json()["categories"]}
    check("rubric has 3 categories", len(frubric_cats) == 3, str(list(frubric_cats)))

    r = client.post(f"/api/projects/{fpid}/rubrics/{frubric_id}/activate", json={"change_note": "activate"}, headers=admin_headers)
    check("rubric activated", r.status_code == 200 and r.json()["status"] == "active", r.text)

    # invalid rubric rejected (categorical without options)
    r = client.post(f"/api/projects/{fpid}/rubrics", json={
        "name": "Bad Rubric",
        "categories": [{"key": "x", "name": "X", "scale_type": "categorical"}],
    }, headers=admin_headers)
    check("rubric validation rejects missing options", r.status_code in (400, 422), r.text[:200])

    # 5c. import tasks via JSONL
    jsonl = "\n".join([
        json.dumps({"external_id": f"smoke-{i}", "prompt": f"Question {i}?",
                    "response": f"Answer {i} with detail.", "model": "Atlas-Mini",
                    "task_type": "qa", "lang": "en"})
        for i in range(6)
    ])
    r = client.post(f"/api/projects/{fpid}/import", json={
        "filename": "smoke.jsonl", "file_format": "jsonl", "content": jsonl, "dry_run": False,
    }, headers=admin_headers)
    check("JSONL import", r.status_code == 200 and r.json()["valid_rows"] == 6, r.text[:300])

    r = client.get(f"/api/projects/{fpid}/tasks", headers=admin_headers)
    ftasks = r.json()
    check("tasks listed", len(ftasks) == 6, str(len(ftasks)))
    check("project auto-activated on import",
          client.get(f"/api/projects/{fpid}", headers=admin_headers).json()["status"] == "active")

    # 5d. create a second reviewer and add both as members
    r = client.post("/api/auth/register", json={
        "email": "smoke-rev-a@example.com", "full_name": "Smoke Rev A",
        "password": "smoke-pass-123", "role": "reviewer"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": "smoke-rev-a@example.com", "password": "smoke-pass-123"})
    rev_a = r.json()["access_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {rev_a}"})
    rev_a_id = r.json()["id"]

    r = client.post("/api/auth/register", json={
        "email": "smoke-rev-b@example.com", "full_name": "Smoke Rev B",
        "password": "smoke-pass-123", "role": "reviewer"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": "smoke-rev-b@example.com", "password": "smoke-pass-123"})
    rev_b = r.json()["access_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {rev_b}"})
    rev_b_id = r.json()["id"]
    rev_a_headers = {"Authorization": f"Bearer {rev_a}"}
    rev_b_headers = {"Authorization": f"Bearer {rev_b}"}

    for uid in (rev_a_id, rev_b_id):
        r = client.post(f"/api/projects/{fpid}/members", json={"user_id": uid, "role_on_project": "reviewer"}, headers=admin_headers)
        check(f"member added {uid[:6]}", r.status_code in (201, 409), r.text[:150])

    # 5e. access control: non-member cannot see the project
    r = client.post("/api/auth/register", json={
        "email": "smoke-outsider@example.com", "full_name": "Outsider",
        "password": "smoke-pass-123", "role": "reviewer"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": "smoke-outsider@example.com", "password": "smoke-pass-123"})
    outsider_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get(f"/api/projects/{fpid}", headers=outsider_headers)
    check("non-member blocked from project", r.status_code == 403, r.text[:150])
    r = client.get(f"/api/projects/{fpid}/tasks", headers=outsider_headers)
    check("non-member blocked from tasks", r.status_code == 403, r.text[:150])

    # 5f. assign reviewers
    r = client.post(f"/api/projects/{fpid}/assign", json={
        "reviewer_ids": [rev_a_id, rev_b_id]}, headers=admin_headers)
    check("assignment created", r.status_code == 200 and r.json()["assignments_created"] == 12, r.text[:250])

    # 5g. unassigned reviewer cannot open workspace
    ftask = ftasks[0]
    r = client.get(f"/api/projects/{fpid}/tasks/{ftask['id']}/evaluate", headers=outsider_headers)
    check("unassigned reviewer blocked from workspace", r.status_code in (403, 404), r.text[:150])

    # 5h. BLINDING: reviewer A sees no peer ratings before submitting
    r = client.get(f"/api/projects/{fpid}/tasks/{ftask['id']}/evaluate", headers=rev_a_headers)
    ws = r.json()
    check("workspace loads", r.status_code == 200 and "task" in ws, r.text[:250])
    check("workspace blinded before submit", ws.get("blinded") is True and ws.get("peer_ratings") == [], str(ws.get("blinded")))

    # 5i. draft autosave
    r = client.post(f"/api/projects/{fpid}/tasks/{ftask['id']}/draft?rubric_id={frubric_id}", json={
        "scores": {"accuracy": 3, "safety": "safe", "grounding": 6.0},
        "rationale": "Draft in progress"}, headers=rev_a_headers)
    check("draft autosaved", r.status_code == 200 and r.json()["status"] == "draft", r.text[:200])

    # 5j. incomplete submission rejected
    r = client.post(f"/api/projects/{fpid}/tasks/{ftask['id']}/submit?rubric_id={frubric_id}", json={
        "scores": {"accuracy": 3}, "rationale": "incomplete"}, headers=rev_a_headers)
    check("incomplete scores rejected", r.status_code == 422, r.text[:200])

    # 5k. out-of-range score rejected
    r = client.post(f"/api/projects/{fpid}/tasks/{ftask['id']}/submit?rubric_id={frubric_id}", json={
        "scores": {"accuracy": 9, "safety": "safe", "grounding": 6.0}, "rationale": "bad"}, headers=rev_a_headers)
    check("out-of-range score rejected", r.status_code == 422, r.text[:200])

    # 5l. invalid categorical value rejected
    r = client.post(f"/api/projects/{fpid}/tasks/{ftask['id']}/submit?rubric_id={frubric_id}", json={
        "scores": {"accuracy": 3, "safety": "maybe", "grounding": 6.0}, "rationale": "bad cat"}, headers=rev_a_headers)
    check("invalid categorical value rejected", r.status_code == 422, r.text[:200])

    # 5m. valid submission
    r = client.post(f"/api/projects/{fpid}/tasks/{ftask['id']}/submit?rubric_id={frubric_id}", json={
        "scores": {"accuracy": 4, "safety": "safe", "grounding": 8.0},
        "rationale": "Clearly accurate and well grounded in the provided context.",
        "confidence": 0.85}, headers=rev_a_headers)
    check("reviewer A submitted", r.status_code == 200, r.text[:250])
    rating_a_id = r.json()["id"]

    # 5n. still blinded to B (B has not submitted); A sees own but no peers
    r = client.get(f"/api/projects/{fpid}/tasks/{ftask['id']}/evaluate", headers=rev_a_headers)
    ws = r.json()
    check("A unblinded after own submit", ws.get("blinded") is False)
    check("A sees no peer ratings yet (B silent)", ws.get("peer_ratings") == [], str(ws.get("peer_ratings"))[:150])

    # 5o. B submits a DELIBERATELY DIFFERENT score -> disagreement
    r = client.post(f"/api/projects/{fpid}/tasks/{ftask['id']}/submit?rubric_id={frubric_id}", json={
        "scores": {"accuracy": 1, "safety": "unsafe", "grounding": 2.0},
        "rationale": "Unclear and possibly fabricated; seems unsafe to me.",
        "confidence": 0.4}, headers=rev_b_headers)
    check("reviewer B submitted", r.status_code == 200, r.text[:250])

    # 5p. duplicate submission rejected (never silently overwritten)
    r = client.post(f"/api/projects/{fpid}/tasks/{ftask['id']}/submit?rubric_id={frubric_id}", json={
        "scores": {"accuracy": 4, "safety": "safe", "grounding": 8.0}, "rationale": "dup"}, headers=rev_a_headers)
    check("duplicate submission rejected (409)", r.status_code == 409, r.text[:200])

    # 5q. now A sees B's rating
    r = client.get(f"/api/projects/{fpid}/tasks/{ftask['id']}/evaluate", headers=rev_a_headers)
    peers = r.json()["peer_ratings"]
    check("A now sees B's rating", len(peers) == 1 and peers[0]["scores"]["accuracy"] == 1, str(peers)[:200])

    # 5r. abstention requires rationale
    abstain_task = ftasks[1]
    r = client.post(f"/api/projects/{fpid}/tasks/{abstain_task['id']}/submit?rubric_id={frubric_id}", json={
        "abstained": True, "scores": {}}, headers=rev_a_headers)
    check("abstention without rationale rejected", r.status_code == 422, r.text[:200])
    r = client.post(f"/api/projects/{fpid}/tasks/{abstain_task['id']}/submit?rubric_id={frubric_id}", json={
        "abstained": True, "scores": {}, "rationale": "Cannot assess this domain reliably."}, headers=rev_a_headers)
    check("abstention accepted with rationale", r.status_code == 200 and r.json()["abstained"] is True, r.text[:200])

    # 5s. correction creates a NEW version (history preserved)
    r = client.post(f"/api/projects/{fpid}/ratings/{rating_a_id}/correct", json={
        "scores": {"accuracy": 3, "safety": "safe", "grounding": 7.0},
        "rationale": "Corrected after re-reading the reference answer.", "confidence": 0.9}, headers=rev_a_headers)
    check("correction accepted", r.status_code == 200 and r.json()["version"] == 2, r.text[:250])
    r = client.get(f"/api/projects/{fpid}/tasks/{ftask['id']}/rating-history?reviewer_id={rev_a_id}", headers=admin_headers)
    hist = r.json()
    check("rating history keeps both versions", len(hist) == 2, str([h.get("version") for h in hist])[:200])
    check("only latest is current", sum(1 for h in hist if h.get("is_current")) == 1, str(hist)[:200])

    # 5t. another reviewer cannot correct A's rating
    r = client.post(f"/api/projects/{fpid}/ratings/{rating_a_id}/correct", json={
        "scores": {"accuracy": 5, "safety": "safe", "grounding": 9.0}, "rationale": "hijack attempt"}, headers=rev_b_headers)
    check("cannot correct another reviewer's rating", r.status_code == 403, r.text[:200])

    # 5u. disagreement detection on the fresh project
    r = client.post(f"/api/projects/{fpid}/disagreements/scan", headers=admin_headers)
    check("disagreement scan on fresh project", r.status_code == 200, r.text[:200])
    r = client.get(f"/api/projects/{fpid}/disagreements", headers=admin_headers)
    fdis = r.json()
    check("disagreements detected on fresh project", len(fdis) >= 2, str(len(fdis)))
    kinds = {d["kind"] for d in fdis}
    check("opposite categorical detected", "opposite_categorical" in kinds, str(kinds))
    check("major score gap detected", "major_score_gap" in kinds or "expert_mismatch" in kinds, str(kinds))

    # 5v. adjudicate the fresh disagreement end-to-end
    target = sorted(fdis, key=lambda d: -d["priority_score"])[0]
    r = client.post(f"/api/projects/{fpid}/adjudications?disagreement_id={target['id']}&task_id={target['task_id']}", headers=admin_headers)
    check("adjudication created (fresh)", r.status_code == 201, r.text[:200])
    fadj = r.json()["id"]
    r = client.get(f"/api/projects/{fpid}/adjudications/{fadj}", headers=admin_headers)
    check("adjudication workspace shows side-by-side ratings", len(r.json()["ratings"]) == 2, r.text[:200])
    check("consensus computed with limitations", "limitations" in r.json()["consensus"], r.text[:200])
    r = client.post(f"/api/projects/{fpid}/adjudications/{fadj}/finalize", json={
        "decision": {"accuracy": 3, "safety": "safe", "grounding": 7.0},
        "rationale": "Anchors at level 3 fit: core answer correct, minor grounding gap."}, headers=admin_headers)
    check("adjudication finalized (fresh)", r.status_code == 200 and r.json()["status"] == "final", r.text[:200])
    r = client.get(f"/api/projects/{fpid}/tasks", headers=admin_headers)
    check("task marked adjudicated", any(t["status"] == "adjudicated" for t in r.json()), str([t["status"] for t in r.json()]))

    # 5w. ratings cannot be corrected after adjudication (must reopen first)
    r = client.post(f"/api/projects/{fpid}/ratings/{rating_a_id}/correct", json={
        "scores": {"accuracy": 2, "safety": "safe", "grounding": 6.0}, "rationale": "post-adjudication edit"}, headers=rev_a_headers)
    check("post-adjudication correction blocked", r.status_code == 409, r.text[:200])

    # 5x. gold label + calibration on the fresh project
    gold_task = ftasks[2]
    r = client.post(f"/api/projects/{fpid}/tasks/{gold_task['id']}/gold-label", json={
        "scores": {"accuracy": 5, "safety": "safe", "grounding": 9.5},
        "rationale": "Expert-approved reference."}, headers=admin_headers)
    check("gold label set", r.status_code == 200, r.text[:200])

    # non-privileged reviewer cannot set gold labels
    r = client.post(f"/api/projects/{fpid}/tasks/{ftasks[3]['id']}/gold-label", json={
        "scores": {"accuracy": 1}}, headers=rev_a_headers)
    check("reviewer cannot set gold label", r.status_code == 403, r.text[:200])

    # 5y. analytics on partially completed project must not crash
    r = client.get(f"/api/projects/{fpid}/analytics/dashboard", headers=admin_headers)
    check("analytics on partial project", r.status_code == 200, r.text[:200])
    r = client.get(f"/api/projects/{fpid}/analytics/metrics", headers=admin_headers)
    check("metrics on partial project", r.status_code == 200, r.text[:200])
    r = client.get(f"/api/projects/{fpid}/analytics/pairwise-agreement", headers=admin_headers)
    check("pairwise agreement on partial project", r.status_code == 200, r.text[:200])
    r = client.get(f"/api/projects/{fpid}/analytics/reviewer-bias", headers=admin_headers)
    check("reviewer bias on partial project", r.status_code == 200, r.text[:200])
    r = client.get(f"/api/projects/{fpid}/analytics/confusion-matrix?category_key=accuracy", headers=admin_headers)
    check("confusion matrix", r.status_code == 200, r.text[:200])

    print("== 6. Import pipeline ==")
    csv_content = "prompt,response,model_name\nQ1?,A1 text,Atlas-Mini\nQ2?,A2 text,Nova-Pro\n"
    r = client.post(f"/api/projects/{fpid}/import", json={
        "filename": "sample.csv", "file_format": "csv", "content": csv_content, "dry_run": True,
    }, headers=admin_headers)
    check("import dry-run", r.status_code == 200 and r.json()["dry_run"] is True, r.text)
    r = client.post(f"/api/projects/{fpid}/import", json={
        "filename": "sample.csv", "file_format": "csv", "content": csv_content, "dry_run": False,
    }, headers=admin_headers)
    check("import execute", r.status_code == 200 and r.json()["valid_rows"] == 2, r.text)

    # malformed import gives actionable errors
    bad_csv = "prompt\nonly-prompt-no-response\n"
    r = client.post(f"/api/projects/{fpid}/import", json={
        "filename": "bad.csv", "file_format": "csv", "content": bad_csv, "dry_run": True,
    }, headers=admin_headers)
    body = r.json()
    check("import validation errors surfaced", body["error_rows"] == 1 and any("response_a" in e["error"] for e in body["errors"]), r.text)

    # duplicate re-import is safe
    r = client.post(f"/api/projects/{fpid}/import", json={
        "filename": "sample.csv", "file_format": "csv", "content": csv_content, "dry_run": False,
    }, headers=admin_headers)
    check("duplicate re-import skipped", r.json()["duplicates_skipped"] == 2 and r.json()["valid_rows"] == 0, r.text)

    print("== 7. Rubric change workflow (human approval gate) ==")
    r = client.get(f"/api/projects/{pid}/rubrics", headers=admin_headers)
    rubrics = r.json()
    check("demo rubric listed", len(rubrics) >= 1, r.text[:200])
    demo_rubric = next((x for x in rubrics if x["status"] == "active"), rubrics[0])
    rubric_id = demo_rubric["id"]
    demo_cat_id = demo_rubric["categories"][0]["id"]

    # capture a rating's rubric_version_id before the change
    import csv as _csv
    import io as _io

    def _rubric_versions_from_export(text):
        rows = list(_csv.DictReader(_io.StringIO(text)))
        return {row["rubric_version_id"] for row in rows[:6] if row.get("rubric_version_id")}

    r = client.get(f"/api/projects/{pid}/export/ratings", headers=admin_headers)
    pre_versions = _rubric_versions_from_export(r.text)

    # pending change request cannot be applied before approval
    r = client.post(f"/api/projects/{pid}/rubrics/change-requests", json={
        "rubric_category_id": demo_cat_id,
        "proposed_changes": {"definition": "Tightened operational definition for testing."},
        "rationale": "Testing the human approval gate end to end.",
    }, headers=admin_headers)
    check("change request created", r.status_code == 201, r.text[:200])
    req_id = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/rubrics/change-requests/{req_id}/apply", headers=admin_headers)
    check("unapproved change cannot be applied", r.status_code == 409, r.text[:200])

    # a plain reviewer cannot approve rubric changes
    r = client.post(f"/api/projects/{pid}/rubrics/change-requests/{req_id}/review?decision=approved",
                    headers={"Authorization": f"Bearer {rev_a}"})
    check("reviewer cannot approve rubric change", r.status_code == 403, r.text[:200])

    r = client.post(f"/api/projects/{pid}/rubrics/change-requests/{req_id}/review?decision=approved&note=Approved", headers=admin_headers)
    check("change request approved by admin", r.json()["status"] == "approved", r.text[:200])
    r = client.post(f"/api/projects/{pid}/rubrics/change-requests/{req_id}/apply", headers=admin_headers)
    check("new rubric version applied", r.status_code == 200 and r.json()["version"] == demo_rubric["version"] + 1, r.text[:250])
    new_version_id = r.json()["id"]

    # double-apply blocked
    r = client.post(f"/api/projects/{pid}/rubrics/change-requests/{req_id}/apply", headers=admin_headers)
    check("double-apply blocked", r.status_code == 409, r.text[:200])

    # old version superseded, still present (history preserved)
    r = client.get(f"/api/projects/{pid}/rubrics", headers=admin_headers)
    statuses = {x["id"]: x["status"] for x in r.json()}
    check("old rubric version superseded, not deleted", statuses.get(rubric_id) == "superseded", str(statuses))
    check("new rubric version active", statuses.get(new_version_id) == "active", str(statuses))

    # existing ratings still point at their original rubric version
    r = client.get(f"/api/projects/{pid}/export/ratings", headers=admin_headers)
    post_versions = _rubric_versions_from_export(r.text)
    check("existing ratings keep original rubric version", pre_versions == post_versions and rubric_id in pre_versions,
          f"{pre_versions} vs {post_versions}")

    print("== 8. Calibration ==")
    r = client.get(f"/api/projects/{pid}/calibration/sessions", headers=admin_headers)
    sessions = r.json()
    check("calibration session seeded", len(sessions) >= 1, r.text)
    if sessions:
        r = client.get(f"/api/projects/{pid}/calibration/sessions/{sessions[0]['id']}/summary", headers=admin_headers)
        summary = r.json()
        check("calibration summary has reviewers", summary["n_reviewers"] >= 3, json.dumps(summary)[:200])

    print("== 9. Reports & exports (CSV / JSON / PDF) ==")
    import time

    def _wait_job(job_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = client.get("/api/admin/jobs", headers=admin_headers)
            job = next((j for j in r.json() if j["id"] == job_id), None)
            if job and job["status"] in ("succeeded", "failed"):
                return job
            time.sleep(0.4)
        return job

    report_ids = {}
    for fmt in ("json", "csv", "pdf"):
        r = client.post(f"/api/projects/{pid}/reports", json={
            "title": f"Smoke Report {fmt.upper()}", "report_format": fmt,
        }, headers=admin_headers)
        check(f"{fmt} report job enqueued", r.status_code == 202, r.text[:200])
        job = _wait_job(r.json()["id"])
        ok = job and job["status"] == "succeeded"
        check(f"{fmt} report generated", bool(ok), str(job)[:400] if not ok else "")
        if ok:
            report_ids[fmt] = job["result"]["report_id"]

    # reports are listed with provenance
    r = client.get(f"/api/projects/{pid}/reports", headers=admin_headers)
    reports = r.json()
    check("reports listed", len(reports) >= 3, str(len(reports)))
    check("report has metric definitions", bool(reports[0].get("metric_definitions")), str(reports[0])[:200])

    # downloads return the right content types
    if "pdf" in report_ids:
        r = client.get(f"/api/projects/{pid}/reports/{report_ids['pdf']}/download", headers=admin_headers)
        check("PDF download", r.status_code == 200 and r.content[:4] == b"%PDF", str(r.status_code) + r.content[:20].hex())
    if "csv" in report_ids:
        r = client.get(f"/api/projects/{pid}/reports/{report_ids['csv']}/download", headers=admin_headers)
        check("CSV download", r.status_code == 200 and "section,key,value" in r.text, r.text[:150])
    if "json" in report_ids:
        r = client.get(f"/api/projects/{pid}/reports/{report_ids['json']}/download", headers=admin_headers)
        payload = r.json()
        check("JSON download has provenance", "generated_at" in payload and "metric_definitions" in payload, str(list(payload))[:200])
        check("JSON report includes sample sizes",
              any("n_items" in v for v in payload["dashboard"]["metrics"].get("categories", {}).values()),
              str(payload["dashboard"]["metrics"])[:200])

    # non-member cannot download reports
    r = client.get(f"/api/projects/{pid}/reports/{list(report_ids.values())[0]}/download", headers=outsider_headers)
    check("non-member blocked from report download", r.status_code == 403, r.text[:150])

    r = client.get(f"/api/projects/{pid}/export/ratings", headers=admin_headers)
    check("ratings CSV export", r.status_code == 200 and "task_external_id" in r.text, r.text[:200])

    print("== 10. Rubric insights ==")
    r = client.post(f"/api/projects/{pid}/rubrics/insights/analyze", headers=admin_headers)
    check("insight analysis", r.status_code == 200 and r.json()["analyzed"] > 0, r.text)
    r = client.get(f"/api/projects/{pid}/rubrics/insights", headers=admin_headers)
    insights = r.json()
    check("insights present", len(insights) > 0)

    print("== 11. LLM offline mode ==")
    r = client.get("/api/llm/config", headers=admin_headers)
    cfg = r.json()
    check("LLM config (offline by default)", cfg["enabled"] is False, json.dumps(cfg))
    r = client.post(f"/api/llm/summarize-case?project_id={pid}&task_id={dis[0]['task_id']}", headers=admin_headers)
    check("offline case summarization works", r.status_code == 200 and r.json()["mode"] == "offline", r.text[:200])

    print("== 12. Demo reset safety ==")
    r = client.post("/api/admin/reset-demo", headers=admin_headers)
    check("demo reset", r.status_code == 200, r.text)
    r = client.get("/api/auth/users", headers=admin_headers)
    demo_left = [u for u in r.json() if u["email"].endswith("@demo.eval-platform.io")]
    check("demo users removed", len(demo_left) == 0, str(demo_left))
    r = client.get("/api/auth/users", headers=admin_headers)
    check("real admin survives reset", any(u["email"] == admin_email for u in r.json()))

    print()
    print(f"==== RESULTS: {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
