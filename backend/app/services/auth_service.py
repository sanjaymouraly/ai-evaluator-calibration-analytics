"""Authentication and user management service."""

from __future__ import annotations

import datetime as dt
import re

from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import User
from app.schemas import TokenPair, UserRegister, UserRoleUpdate

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def register(self, data: UserRegister) -> tuple[User, TokenPair]:
        existing = self.db.query(User).filter(User.email == data.email).first()
        if existing:
            raise ConflictError("An account with this email already exists.")
        # First user may self-register as admin (empty-db bootstrap);
        # otherwise admin assignment is privileged.
        if data.role == "admin" and self.db.query(User).count() > 0:
            raise ForbiddenError(
                "Only the first account may self-register as admin. "
                "Ask an administrator to promote your account."
            )
        user = User(
            email=data.email,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            role=data.role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user, self._tokens(user)

    def login(self, email: str, password: str) -> tuple[User, TokenPair]:
        user = self.db.query(User).filter(User.email == email.lower()).first()
        if user is None or not verify_password(password, user.hashed_password):
            raise ValidationError("Invalid email or password.")
        if not user.is_active:
            raise ForbiddenError("Account deactivated. Contact an administrator.")
        user.last_login_at = dt.datetime.now(dt.UTC)
        self.db.commit()
        return user, self._tokens(user)

    def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, expected_type="refresh")
        user = self.db.query(User).filter(User.id == payload["sub"]).first()
        if user is None or not user.is_active:
            raise ValidationError("Invalid refresh token.")
        return self._tokens(user)

    def _tokens(self, user: User) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(user.id, user.role),
            refresh_token=create_refresh_token(user.id),
        )

    # -- admin operations --
    def list_users(self, q: str | None = None, limit: int = 50, offset: int = 0):
        query = self.db.query(User)
        if q:
            query = query.filter(User.email.ilike(f"%{q}%"))
        return query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

    def change_role(self, user_id: str, data: UserRoleUpdate, actor_id: str) -> User:
        if user_id == actor_id:
            raise ForbiddenError("You cannot change your own role.")
        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise NotFoundError("User not found.")
        if data.role not in {"admin", "adjudicator", "senior_reviewer", "reviewer"}:
            raise ValidationError("Invalid role.")
        user.role = data.role
        self.db.commit()
        self.db.refresh(user)
        return user

    def deactivate(self, user_id: str, actor_id: str) -> User:
        if user_id == actor_id:
            raise ForbiddenError("You cannot deactivate yourself.")
        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise NotFoundError("User not found.")
        user.is_active = False
        self.db.commit()
        self.db.refresh(user)
        return user
