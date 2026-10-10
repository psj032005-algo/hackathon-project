"""Password, signed-token, and store ownership helpers."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if __package__:
    from . import config as _config  # noqa: F401 - loads the local backend environment
    from .database import get_connection
else:
    import config as _config  # noqa: F401 - loads the local backend environment
    from database import get_connection


JWT_ALGORITHM = "HS256"
JWT_DEFAULT_ISSUER = "launch-store-backend"
JWT_DEFAULT_TTL_MINUTES = 30
JWT_MINIMUM_SECRET_BYTES = 32
AUTH_CONFIGURATION_DETAIL = (
    "Authentication is not configured. Set JWT_SECRET to a cryptographically random "
    "value of at least 32 bytes in backend/.env or the backend process environment, "
    "then restart the backend."
)
PASSWORD_MINIMUM_LENGTH = 12
PASSWORD_MAXIMUM_LENGTH = 128

password_hasher = PasswordHasher(type=Type.ID)
bearer_scheme = HTTPBearer(auto_error=False)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
STORE_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AuthConfigurationError(Exception):
    """Raised when auth cannot safely sign or validate tokens."""


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("Enter a valid email address")
    return normalized


def validate_password(password: str) -> str:
    if not PASSWORD_MINIMUM_LENGTH <= len(password) <= PASSWORD_MAXIMUM_LENGTH:
        raise ValueError(
            f"Password must be between {PASSWORD_MINIMUM_LENGTH} and "
            f"{PASSWORD_MAXIMUM_LENGTH} characters"
        )
    return password


def validate_store_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if len(normalized) > 80 or not STORE_SLUG_PATTERN.fullmatch(normalized):
        raise ValueError("Store slug must use lowercase letters, numbers, and hyphens")
    return normalized


def hash_password(password: str) -> str:
    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _jwt_configuration() -> tuple[str, str, int]:
    secret = os.environ.get("JWT_SECRET", "")
    if (
        secret != secret.strip()
        or len(secret.encode("utf-8")) < JWT_MINIMUM_SECRET_BYTES
        or len(set(secret)) < 16
    ):
        raise AuthConfigurationError(
            "JWT_SECRET must be a non-padded value of at least 32 bytes with adequate "
            "randomness; generate it with a cryptographically secure random generator"
        )

    issuer = os.environ.get("JWT_ISSUER", JWT_DEFAULT_ISSUER).strip()
    if not issuer:
        raise AuthConfigurationError("JWT_ISSUER must not be empty")

    try:
        ttl_minutes = int(
            os.environ.get("JWT_ACCESS_TOKEN_MINUTES", str(JWT_DEFAULT_TTL_MINUTES))
        )
    except ValueError as error:
        raise AuthConfigurationError("JWT token lifetime configuration is invalid") from error
    if not 1 <= ttl_minutes <= 1440:
        raise AuthConfigurationError("JWT token lifetime must be between 1 and 1440 minutes")

    return secret, issuer, ttl_minutes


def validate_jwt_configuration() -> None:
    """Fail closed before any account is created or a token is issued."""
    _jwt_configuration()


def create_access_token(user_id: int) -> str:
    secret, issuer, ttl_minutes = _jwt_configuration()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iss": issuer,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
        "token_type": "access",
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        secret, issuer, _ = _jwt_configuration()
    except AuthConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_CONFIGURATION_DETAIL,
        ) from error

    try:
        payload = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=[JWT_ALGORITHM],
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "sub", "token_type"]},
        )
        if payload.get("token_type") != "access":
            raise _unauthorized()
        user_id = int(payload["sub"])
        if user_id < 1:
            raise _unauthorized()
    except (jwt.InvalidTokenError, TypeError, ValueError, KeyError) as error:
        raise _unauthorized() from error

    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if user is None:
        raise _unauthorized()
    return dict(user)


def require_store_owner(
    slug: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Resolve a private store only when the bearer user owns it."""
    with get_connection() as connection:
        store = connection.execute(
            """
            SELECT id, slug, name, description, logo_url, is_published
            FROM stores
            WHERE slug = ? AND owner_user_id = ?
            """,
            (slug, current_user["id"]),
        ).fetchone()
    if store is None:
        # Same response for a nonexistent store and another owner's store.
        raise HTTPException(status_code=404, detail="Store not found")
    result = dict(store)
    result["is_published"] = bool(result["is_published"])
    return result
