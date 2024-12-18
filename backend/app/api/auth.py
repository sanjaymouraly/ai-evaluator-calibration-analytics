"""Auth endpoints: register, login, refresh, me; admin user management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import (
    get_current_user,
    rate_limit_auth,
    require_admin,
)
from app.db import get_db
from app.models import User
from app.schemas import TokenPair, UserLogin, UserOut, UserRegister, UserRoleUpdate
from app.services import audit_service
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=TokenPair, dependencies=[Depends(rate_limit_auth)])
def register(data: UserRegister, request: Request, db: Session = Depends(get_db)):
    svc = AuthService(db)
    user, tokens = svc.register(data)
    audit_service.log_action(db, user.id, "user.register", "user", user.id, ip_address=_client_ip(request))
    return tokens


@router.post("/login", response_model=TokenPair, dependencies=[Depends(rate_limit_auth)])
def login(data: UserLogin, request: Request, db: Session = Depends(get_db)):
    svc = AuthService(db)
    user, tokens = svc.login(data.email, data.password)
    audit_service.log_action(db, user.id, "user.login", "user", user.id, ip_address=_client_ip(request))
    return tokens


@router.post("/refresh", response_model=TokenPair, dependencies=[Depends(rate_limit_auth)])
def refresh(refresh_token: str, db: Session = Depends(get_db)):
    from app.auth import decode_token

    payload = decode_token(refresh_token, expected_type="refresh")
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if user is None:
        from app.exceptions import ValidationError

        raise ValidationError("Invalid refresh token.")
    return AuthService(db)._tokens(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(q: str | None = None, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return AuthService(db).list_users(q=q)


@router.patch("/users/{user_id}/role", response_model=UserOut)
def change_role(
    user_id: str, data: UserRoleUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)
):
    user = AuthService(db).change_role(user_id, data, actor.id)
    audit_service.log_action(db, actor.id, "user.role_change", "user", user_id, {"role": data.role})
    return user


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate(user_id: str, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = AuthService(db).deactivate(user_id, actor.id)
    audit_service.log_action(db, actor.id, "user.deactivate", "user", user_id)
    return user
