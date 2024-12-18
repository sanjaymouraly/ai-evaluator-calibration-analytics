"""Pytest fixtures.

Environment variables are set BEFORE importing the app so the engine
and settings bind to an isolated test database.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

_TEST_DIR = pathlib.Path(tempfile.mkdtemp(prefix="evalplatform-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR / 'test.db'}"
os.environ["JWT_SECRET_KEY"] = "pytest-only-secret-key-0123456789abcdef"
os.environ["REPORTS_DIR"] = str(_TEST_DIR / "reports")
os.environ["ENVIRONMENT"] = "test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    """Register (or log in) the session admin and return auth headers."""
    payload = {
        "email": "admin@test-eval.io",
        "full_name": "Test Admin",
        "password": "test-password-123",
        "role": "admin",
    }
    r = client.post("/api/auth/register", json=payload)
    if r.status_code == 409:
        r = client.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_id(client, admin_headers):
    return client.get("/api/auth/me", headers=admin_headers).json()["id"]


def make_user(client, email: str, password: str = "user-password-123", role: str = "reviewer"):
    """Create (or log in) a user; returns (user_dict, headers)."""
    r = client.post(
        "/api/auth/register",
        json={"email": email, "full_name": email.split("@")[0].title(), "password": password, "role": role},
    )
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    user = client.get("/api/auth/me", headers=headers).json()
    return user, headers
