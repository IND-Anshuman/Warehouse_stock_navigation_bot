"""
app/core/security.py — Cryptographic utilities for auth-service.

Covers:
  - Password hashing/verification (bcrypt via passlib)
  - Password strength validation
  - JWT creation and verification (HS256)
  - Refresh token generation (256-bit secure random)
  - Invite / reset token generation and hashing (SHA-256)
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

log = structlog.get_logger(__name__)

# ── Bcrypt context ─────────────────────────────────────────────────────────────
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


# ── Password utilities ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt (cost factor 12)."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        return False


def is_password_strong(password: str) -> tuple[bool, str]:
    """
    Validate password strength.

    Rules:
    - Minimum 12 characters
    - At least 1 uppercase letter (A-Z)
    - At least 1 digit (0-9)
    - At least 1 special character

    Returns:
        (True, "") if strong
        (False, "<error_message>") if weak
    """
    import re

    if len(password) < 12:
        return False, "Password must be at least 12 characters long"

    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"

    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one digit"

    special_chars = r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]"
    if not re.search(special_chars, password):
        return False, "Password must contain at least one special character (!@#$%^&*...)"

    return True, ""


# ── JWT utilities ──────────────────────────────────────────────────────────────

def create_access_token(payload: dict[str, Any], expires_minutes: int | None = None) -> str:
    """
    Create a signed JWT access token.

    Adds standard claims:
      - exp: expiry timestamp
      - iat: issued-at timestamp
      - jti: unique JWT ID (UUID4)

    Args:
        payload: Claims to embed (sub, email, role, org_id, permissions …)
        expires_minutes: Token TTL in minutes (defaults to settings value)

    Returns:
        Signed JWT string.
    """
    if expires_minutes is None:
        expires_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES

    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)

    to_encode: dict[str, Any] = {
        **payload,
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token() -> str:
    """
    Generate a cryptographically-secure 256-bit refresh token.

    Returns:
        64-character lowercase hex string (32 bytes → 64 hex chars).
    """
    return secrets.token_hex(32)  # 32 bytes = 256 bits


def verify_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Args:
        token: Raw JWT string from Authorization header.

    Returns:
        Decoded payload dict.

    Raises:
        HTTPException 401 on any validation failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
        return payload
    except ExpiredSignatureError:
        log.warning("jwt.expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        log.warning("jwt.invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Invite & reset token utilities ────────────────────────────────────────────

def generate_secure_token() -> tuple[str, str]:
    """
    Generate a URL-safe secure token suitable for invite / password-reset links.

    Returns:
        (raw_token, sha256_hex_hash)
        - raw_token is sent in the email link (never stored)
        - sha256_hex_hash is stored in the DB for lookup
    """
    raw = secrets.token_urlsafe(32)  # 32 bytes → ~43 base64url chars
    hashed = hash_token(raw)
    return raw, hashed


def hash_token(raw: str) -> str:
    """
    Compute the SHA-256 hex digest of a raw token string.
    Used for DB storage — never store raw invite/reset tokens.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_token_hash(raw: str, stored_hash: str) -> bool:
    """
    Constant-time comparison of raw token against its stored SHA-256 hash.

    Returns:
        True if they match, False otherwise.
    """
    computed = hash_token(raw)
    return secrets.compare_digest(computed.encode(), stored_hash.encode())
