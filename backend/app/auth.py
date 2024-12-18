"""Authentication utilities: password hashing, JWT, rate limiting, RBAC helpers."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.exceptions import ForbiddenError, UnauthorizedError
from app.models import Project, ProjectMember, User

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
    # OWASP-recommended work factor for PBKDF2-HMAC-SHA256. Configurable
    # via PASSWORD_HASH_ITERATIONS; existing hashes keep their own round
    # count (passlib reads it from the hash) and can be rehashed on login.
    pbkdf2_sha256__rounds=settings.password_hash_iterations,
)

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": int(time.time()) + settings.access_token_expire_minutes * 60,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": int(time.time()) + settings.refresh_token_expire_days * 86400,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token. Please sign in again.") from exc
    if payload.get("type") != expected_type:
        raise UnauthorizedError("Invalid token type.")
    return payload


# --- In-memory sliding-window rate limiter for sensitive endpoints ---
class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            self._hits[key] = [t for t in self._hits[key] if now - t < self.window]
            if len(self._hits[key]) >= self.max_requests:
                return False
            self._hits[key].append(now)
            return True


auth_rate_limiter = RateLimiter(settings.rate_limit_per_minute)


# --- FastAPI dependencies ---
def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required.")
    token = credentials.credentials
    payload = decode_token(token)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or deactivated.")
    return user


def rate_limit_auth(request: Request) -> None:
    """Rate limit for credential-handling endpoints only.

    Keyed by client IP so an attacker cannot brute-force passwords.
    Ordinary authenticated API traffic is deliberately NOT throttled
    here — dashboards legitimately issue many requests per minute.
    """
    forwarded = request.headers.get("x-forwarded-for")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    if not auth_rate_limiter.check(f"auth:{ip}"):
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts. Please wait a minute and try again.",
        )


def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles and "admin" not in roles:
            raise ForbiddenError(f"Requires one of roles: {', '.join(roles)}")
        return user

    return checker


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ForbiddenError("Administrator role required.")
    return user


def get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        from app.exceptions import NotFoundError

        raise NotFoundError(f"Project {project_id} not found.")
    return project


def require_project_access(
    db: Session, project: Project, user: User, require_membership: bool = True
) -> None:
    if user.role == "admin":
        return
    if project.owner_id == user.id:
        return
    if not require_membership:
        return
    member = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    if member is None:
        raise ForbiddenError("You do not have access to this project.")


def require_project_role(db: Session, project: Project, user: User, *roles: str) -> ProjectMember | None:
    """Return membership row if user has one of the given project roles."""
    if user.role == "admin":
        return None
    if project.owner_id == user.id:
        return None  # owner implicitly has all project roles
    member = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    if member is None or member.role_on_project not in roles:
        raise ForbiddenError(
            f"Requires project role: {', '.join(roles)} (you are "
            f"{member.role_on_project if member else 'not a member'})."
        )
    return member
