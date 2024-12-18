"""Centralized application exceptions with safe, non-leaking messages."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error. `public_message` is safe to show to clients."""

    status_code = 400

    def __init__(self, message: str, public_message: str | None = None, **details: Any):
        super().__init__(message)
        self.public_message = public_message or message
        self.details = details


class NotFoundError(AppError):
    status_code = 404


class ForbiddenError(AppError):
    status_code = 403


class UnauthorizedError(AppError):
    status_code = 401


class ValidationError(AppError):
    status_code = 422


class ConflictError(AppError):
    status_code = 409


class RateLimitError(AppError):
    status_code = 429


def safe_error(exc: Exception) -> tuple[str, int]:
    """Map unexpected exceptions to a generic safe message + status code."""
    if isinstance(exc, AppError):
        return exc.public_message, exc.status_code
    return "An unexpected internal error occurred. Check server logs for details.", 500
