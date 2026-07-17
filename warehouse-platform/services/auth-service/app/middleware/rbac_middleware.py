"""
app/middleware/rbac_middleware.py — JWT-based authentication & RBAC FastAPI dependencies.

Provides:
  - UserContext: Pydantic model representing the decoded token context
  - get_current_user: Dependency that decodes JWT and returns UserContext
  - require_permission: Factory dependency that checks resource:action in token
  - require_role: Factory dependency that checks role membership
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.security import verify_access_token

log = structlog.get_logger(__name__)

# ── Bearer scheme ──────────────────────────────────────────────────────────────
_bearer_scheme = HTTPBearer(auto_error=False)


# ── UserContext ────────────────────────────────────────────────────────────────

class UserContext(BaseModel):
    """Typed representation of the JWT payload for a logged-in user."""

    user_id: uuid.UUID
    email: str
    role: str
    org_id: uuid.UUID
    session_id: uuid.UUID
    permissions: list[str]

    @classmethod
    def from_jwt_payload(cls, payload: dict) -> "UserContext":
        """
        Build a UserContext from the decoded JWT payload dict.
        Raises HTTPException 401 if any required claim is missing.
        """
        try:
            return cls(
                user_id=uuid.UUID(payload["sub"]),
                email=payload["email"],
                role=payload.get("role", "NONE"),
                org_id=uuid.UUID(payload["org_id"]),
                session_id=uuid.UUID(payload["session_id"]),
                permissions=payload.get("permissions", []),
            )
        except (KeyError, ValueError) as exc:
            log.warning("jwt.malformed_payload", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is malformed",
                headers={"WWW-Authenticate": "Bearer"},
            )


# ── Core dependency ────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(_bearer_scheme),
    ]
) -> UserContext:
    """
    FastAPI dependency. Extracts and validates the JWT Bearer token,
    returning a fully typed UserContext.

    Raises:
        HTTPException 401 if no token or token is invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Include 'Authorization: Bearer <token>' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_access_token(credentials.credentials)
    return UserContext.from_jwt_payload(payload)


# ── Permission dependency factory ─────────────────────────────────────────────

def require_permission(resource: str, action: str):
    """
    FastAPI dependency factory.

    Usage:
        @router.get("/path", dependencies=[Depends(require_permission("inventory", "read"))])

    Or as a typed dependency:
        async def endpoint(user: Annotated[UserContext, Depends(require_permission("inventory", "read"))]):
            ...

    Args:
        resource: The resource name (e.g., "inventory", "user", "mission")
        action:   The action name  (e.g., "read", "create", "delete")

    Returns:
        A FastAPI dependency that yields UserContext or raises 401/403.
    """
    required_permission = f"{resource}:{action}"

    async def _check(
        user: Annotated[UserContext, Depends(get_current_user)]
    ) -> UserContext:
        if required_permission not in user.permissions:
            log.warning(
                "rbac.permission_denied",
                user_id=str(user.user_id),
                required=required_permission,
                user_permissions=user.permissions,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: requires '{required_permission}'",
            )
        return user

    return _check


# ── Role dependency factory ────────────────────────────────────────────────────

def require_role(*roles: str):
    """
    FastAPI dependency factory.

    Validates that the current user's role is one of the specified roles.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("ENTERPRISE_ADMIN", "WAREHOUSE_MANAGER"))])

    Args:
        *roles: Acceptable role names.

    Returns:
        A FastAPI dependency that yields UserContext or raises 401/403.
    """
    accepted_roles = set(roles)

    async def _check(
        user: Annotated[UserContext, Depends(get_current_user)]
    ) -> UserContext:
        if user.role not in accepted_roles:
            log.warning(
                "rbac.role_denied",
                user_id=str(user.user_id),
                user_role=user.role,
                required_roles=list(accepted_roles),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role. Required one of: {', '.join(sorted(accepted_roles))}",
            )
        return user

    return _check


# ── Optional auth dependency ───────────────────────────────────────────────────

async def get_optional_user(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(_bearer_scheme),
    ]
) -> Optional[UserContext]:
    """
    Like get_current_user but returns None instead of raising 401 when no
    token is present. Useful for endpoints that behave differently for
    authenticated vs anonymous users.
    """
    if not credentials:
        return None
    try:
        payload = verify_access_token(credentials.credentials)
        return UserContext.from_jwt_payload(payload)
    except HTTPException:
        return None
