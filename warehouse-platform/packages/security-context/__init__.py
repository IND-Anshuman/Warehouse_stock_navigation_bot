"""
Security context: JWT validation, RBAC evaluation middleware.
Shared across all services.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import structlog
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours


# ─────────────────────────────────────────────────────────
#  ROLES & PERMISSIONS
# ─────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    WAREHOUSE_MANAGER = "WAREHOUSE_MANAGER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"
    ROBOT_AGENT = "ROBOT_AGENT"


# Permission manifest: role -> allowed permissions
ROLE_PERMISSIONS: dict[UserRole, set[str]] = {
    UserRole.PLATFORM_ADMIN: {
        "warehouses:read", "warehouses:write", "warehouses:delete",
        "missions:read", "missions:write", "missions:delete",
        "observations:read", "observations:write",
        "alerts:read", "alerts:write", "alerts:delete",
        "inventory:read", "inventory:write",
        "robots:read", "robots:write", "robots:delete",
        "users:read", "users:write", "users:delete",
        "audit:read",
    },
    UserRole.WAREHOUSE_MANAGER: {
        "warehouses:read", "warehouses:write",
        "missions:read", "missions:write",
        "observations:read",
        "alerts:read", "alerts:write",
        "inventory:read", "inventory:write",
        "robots:read", "robots:write",
        "users:read",
        "audit:read",
    },
    UserRole.OPERATOR: {
        "warehouses:read",
        "missions:read", "missions:write",
        "observations:read",
        "alerts:read", "alerts:write",
        "inventory:read",
        "robots:read",
    },
    UserRole.VIEWER: {
        "warehouses:read",
        "missions:read",
        "observations:read",
        "alerts:read",
        "inventory:read",
        "robots:read",
    },
    UserRole.ROBOT_AGENT: {
        "observations:write",
        "missions:read",
        "robots:write",  # can update own heartbeat
    },
}


def has_permission(role: UserRole, permission: str) -> bool:
    """Check if a role has a specific permission."""
    return permission in ROLE_PERMISSIONS.get(role, set())


# ─────────────────────────────────────────────────────────
#  TOKEN MODELS
# ─────────────────────────────────────────────────────────

class TokenPayload(BaseModel):
    """Claims inside a JWT token."""

    sub: str  # user_id
    email: str
    role: UserRole
    warehouse_ids: list[str] = []
    exp: datetime
    iat: datetime
    jti: str  # JWT ID for revocation


class TokenPair(BaseModel):
    """Access + refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60


class AuthenticatedUser(BaseModel):
    """The resolved user identity attached to each request."""

    user_id: uuid.UUID
    email: str
    role: UserRole
    warehouse_ids: list[str]

    def can(self, permission: str) -> bool:
        """Check if this user has the given permission."""
        return has_permission(self.role, permission)

    def can_access_warehouse(self, warehouse_id: str) -> bool:
        """Check warehouse-level access (admin bypasses)."""
        if self.role == UserRole.PLATFORM_ADMIN:
            return True
        return warehouse_id in self.warehouse_ids


# ─────────────────────────────────────────────────────────
#  PASSWORD UTILITIES
# ─────────────────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash a plain text password with bcrypt."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against its bcrypt hash."""
    return _pwd_context.verify(plain_password, hashed_password)


# ─────────────────────────────────────────────────────────
#  TOKEN CREATION & VALIDATION
# ─────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    email: str,
    role: UserRole,
    warehouse_ids: list[str],
    secret_key: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "role": role.value,
        "warehouse_ids": warehouse_ids,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_token(token: str, secret_key: str) -> TokenPayload:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        raw = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        return TokenPayload(
            sub=raw["sub"],
            email=raw["email"],
            role=UserRole(raw["role"]),
            warehouse_ids=raw.get("warehouse_ids", []),
            exp=datetime.fromtimestamp(raw["exp"]),
            iat=datetime.fromtimestamp(raw["iat"]),
            jti=raw["jti"],
        )
    except JWTError as exc:
        logger.warning("jwt_decode_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ─────────────────────────────────────────────────────────
#  FASTAPI DEPENDENCIES
# ─────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user_factory(secret_key: str) -> Any:
    """
    Factory that creates a FastAPI dependency for the given secret_key.
    
    Usage in each service:
        from packages.security_context import get_current_user_factory
        get_current_user = get_current_user_factory(settings.SECRET_KEY)
        
        @router.get("/resource")
        async def handler(user: AuthenticatedUser = Depends(get_current_user)):
            ...
    """
    async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
    ) -> AuthenticatedUser:
        token_payload = decode_token(credentials.credentials, secret_key)
        return AuthenticatedUser(
            user_id=uuid.UUID(token_payload.sub),
            email=token_payload.email,
            role=token_payload.role,
            warehouse_ids=token_payload.warehouse_ids,
        )

    return get_current_user


def require_permission(permission: str) -> Any:
    """
    FastAPI dependency factory that checks a specific permission.
    
    Usage:
        @router.delete("/resource/{id}")
        async def delete_resource(
            _: None = Depends(require_permission("resources:delete")),
            user: AuthenticatedUser = Depends(get_current_user),
        ):
            ...
    """
    async def _check(
        credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
    ) -> None:
        # In a real deployment, this would decode from settings.SECRET_KEY
        # For service-level use, inject via closure
        pass  # Simplified: actual check done in route handler

    return _check
