"""
app/api/v1/admin_router.py — Administrator/Manager-facing endpoints.

Prefix: /api/v1/admin
Tags:   admin
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.audit import write_audit_log
from app.middleware.rbac_middleware import UserContext, require_permission
from app.repositories.auth_repo import AuthRepository
from app.schemas.auth import (
    AuditLogListResponse,
    AuditLogResponse,
    InviteCreateRequest,
    InviteResponse,
    OrganizationResponse,
    OrganizationSettingsUpdate,
    RoleResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.auth_service import AuthService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


async def _get_redis(request: Request):
    """Pull the Redis client from app state."""
    return request.app.state.redis


# ── USERS MANAGEMENT ──────────────────────────────────────────────────────────

@router.get(
    "/users",
    response_model=List[UserResponse],
    summary="List all users in the organization",
    status_code=status.HTTP_200_OK,
)
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("users", "read"))],
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    """List users belonging to the current user's organization."""
    repo = AuthRepository(db)
    users = await repo.get_users_by_org(
        org_id=current_user.org_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter
    )
    return [UserResponse.model_validate(u) for u in users]


@router.post(
    "/users/invite",
    response_model=UserResponse,
    summary="Invite a new user to the organization",
    status_code=status.HTTP_201_CREATED,
)
async def invite_user(
    body: UserCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("users", "write"))],
):
    """Create an invite for a new user and return a pending user object."""
    invite = await AuthService.create_invite(
        org_id=current_user.org_id,
        inviter_id=current_user.user_id,
        email=body.email,
        role_id=body.role_id,
        warehouse_id=body.warehouse_id,
        db=db,
    )
    # Get the newly created user (pending state)
    repo = AuthRepository(db)
    user = await repo.get_user_by_email(body.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User creation failed during invitation flow."
        )
    return UserResponse.model_validate(user)


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Get user details by ID",
    status_code=status.HTTP_200_OK,
)
async def get_user_details(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("users", "read"))],
):
    """Get details of a specific user in the organization."""
    repo = AuthRepository(db)
    user = await repo.get_user_by_id(user_id)
    if not user or user.org_id != current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or access denied."
        )
    return UserResponse.model_validate(user)


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Update user details",
    status_code=status.HTTP_200_OK,
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("users", "write"))],
):
    """Update profile details or status of a user."""
    repo = AuthRepository(db)
    user = await repo.get_user_by_id(user_id)
    if not user or user.org_id != current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or access denied."
        )

    updated_user = await repo.update_user(
        user_id=user_id,
        display_name=body.display_name if body.display_name else user.display_name,
        status=body.status if body.status else user.status
    )
    return UserResponse.model_validate(updated_user)


@router.put(
    "/users/{user_id}/role",
    response_model=UserResponse,
    summary="Change user role assignment",
    status_code=status.HTTP_200_OK,
)
async def update_user_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    warehouse_id: Optional[uuid.UUID] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = Depends(get_db),
    current_user: UserContext = Depends(require_permission("users", "write")),
):
    """Change the role of a user, potentially restricted to a specific warehouse."""
    repo = AuthRepository(db)
    user = await repo.get_user_by_id(user_id)
    if not user or user.org_id != current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or access denied."
        )

    # Validate the role exists in the org
    role = await repo.get_role_by_id(role_id)
    if not role or role.org_id != current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role selected."
        )

    # Revoke existing roles and assign the new one
    await repo.remove_role(user_id, role_id)
    await repo.assign_role(
        user_id=user_id,
        role_id=role_id,
        warehouse_id=warehouse_id,
        assigned_by=current_user.user_id
    )

    # Force invalidate sessions for security
    await repo.revoke_all_user_sessions(user_id, reason="ROLE_CHANGE")
    
    refreshed_user = await repo.get_user_by_id(user_id)
    return UserResponse.model_validate(refreshed_user)


@router.delete(
    "/users/{user_id}/sessions",
    response_model=MessageResponse,
    summary="Force logout all sessions for a user",
    status_code=status.HTTP_200_OK,
)
async def force_logout_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("users", "write"))],
):
    """Revoke all active sessions for a user."""
    repo = AuthRepository(db)
    user = await repo.get_user_by_id(user_id)
    if not user or user.org_id != current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or access denied."
        )

    count = await repo.revoke_all_user_sessions(user_id, reason="ADMIN_REVOKE")
    return MessageResponse(message=f"Successfully terminated {count} active sessions.")


# ── INVITES MANAGEMENT ────────────────────────────────────────────────────────

@router.get(
    "/invites",
    response_model=List[InviteResponse],
    summary="List all pending invitations",
    status_code=status.HTTP_200_OK,
)
async def list_invites(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("users", "read"))],
):
    """Retrieve all pending user invitations."""
    repo = AuthRepository(db)
    invites = await repo.list_pending_invites(org_id=current_user.org_id)
    return invites


# ── COMPLIANCE AUDIT LOGS ─────────────────────────────────────────────────────

@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="Query compliance audit logs",
    status_code=status.HTTP_200_OK,
)
async def get_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("compliance", "read"))],
    actor_id: Optional[uuid.UUID] = None,
    event_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50,
):
    """Search/filter compliance audit logs for the organization."""
    repo = AuthRepository(db)
    logs, total = await repo.get_audit_logs(
        org_id=current_user.org_id,
        actor_id=actor_id,
        event_type=event_type,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit
    )
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=(skip // limit) + 1,
        limit=limit
    )


# ── ORG ROLES ─────────────────────────────────────────────────────────────────

@router.get(
    "/roles",
    response_model=List[RoleResponse],
    summary="List roles in the organization",
    status_code=status.HTTP_200_OK,
)
async def list_roles(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("users", "read"))],
):
    """Get the list of roles configured in the organization."""
    repo = AuthRepository(db)
    roles = await repo.get_roles_for_org(org_id=current_user.org_id)
    return [RoleResponse.model_validate(r) for r in roles]


# ── ORG SETTINGS ──────────────────────────────────────────────────────────────

@router.get(
    "/settings",
    response_model=OrganizationResponse,
    summary="Get organization settings",
    status_code=status.HTTP_200_OK,
)
async def get_org_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("settings", "read"))],
):
    """Get the organization's tenant configuration and security policies."""
    repo = AuthRepository(db)
    org = await repo.get_org_by_id(current_user.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization settings not found."
        )
    return OrganizationResponse.model_validate(org)


@router.put(
    "/settings",
    response_model=OrganizationResponse,
    summary="Update organization settings",
    status_code=status.HTTP_200_OK,
)
async def update_org_settings(
    body: OrganizationSettingsUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserContext, Depends(require_permission("settings", "write"))],
):
    """Update tenant configuration, timeout hours, data retention, or MFA policies."""
    repo = AuthRepository(db)
    org = await repo.get_org_by_id(current_user.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization settings not found."
        )

    # Perform updates
    org.name = body.name if body.name is not None else org.name
    org.mfa_policy = body.mfa_policy if body.mfa_policy is not None else org.mfa_policy
    org.sso_enabled = body.sso_enabled if body.sso_enabled is not None else org.sso_enabled
    org.sso_provider = body.sso_provider if body.sso_provider is not None else org.sso_provider
    org.sso_metadata_url = body.sso_metadata_url if body.sso_metadata_url is not None else org.sso_metadata_url
    org.session_timeout_hours = body.session_timeout_hours if body.session_timeout_hours is not None else org.session_timeout_hours
    org.data_retention_days = body.data_retention_days if body.data_retention_days is not None else org.data_retention_days

    db.add(org)
    await db.commit()
    await db.refresh(org)

    # Log audit event
    await write_audit_log(
        db=db,
        event_type="ORG_SETTINGS_UPDATED",
        org_id=current_user.org_id,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role,
        resource_type="ORGANIZATION",
        resource_id=org.id,
        after_state={"mfa_policy": org.mfa_policy, "sso_enabled": org.sso_enabled, "session_timeout_hours": org.session_timeout_hours}
    )

    return OrganizationResponse.model_validate(org)
