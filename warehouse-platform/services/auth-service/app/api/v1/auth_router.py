"""
app/api/v1/auth_router.py — User-facing authentication endpoints.

Prefix: /api/v1/auth
Tags:   auth
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, hash_token
from app.database import get_db
from app.middleware.rbac_middleware import UserContext, get_current_user
from app.repositories.auth_repo import AuthRepository
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    InviteAcceptRequest,
    LoginRequest,
    LoginResponse,
    MFAEnableRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    MessageResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    ResetPasswordRequest,
    SessionResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.auth_service import AuthService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, honouring X-Forwarded-For from proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _get_redis(request: Request):
    """Pull the Redis client from app state."""
    return request.app.state.redis


# ── POST /login ────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate with email + password",
    status_code=status.HTTP_200_OK,
)
async def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Authenticate a user.

    Returns an access token and (rotated) refresh token on success.
    Returns `requires_mfa: true` with a challenge token when MFA is enabled.
    """
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    redis = await _get_redis(request)

    result = await AuthService.login(
        email=body.email,
        password=body.password,
        ip=ip,
        user_agent=user_agent,
        device_fingerprint=body.device_fingerprint,
        db=db,
        redis=redis,
    )
    return LoginResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        user=result["user"],
        requires_mfa=result.get("requires_mfa", False),
        mfa_challenge_token=result.get("mfa_challenge_token"),
    )


# ── POST /logout ───────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke current session",
    status_code=status.HTTP_200_OK,
)
async def logout(
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Revoke the current session. The access token will remain valid until its natural expiry."""
    await AuthService.logout(session_id=user.session_id, user=user, db=db)
    return MessageResponse(message="Logged out successfully")


# ── POST /refresh ──────────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    summary="Rotate refresh token and get new access token",
    status_code=status.HTTP_200_OK,
)
async def refresh_tokens(
    body: TokenRefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Exchange a valid refresh token for a new access token.
    Implements refresh token rotation — the old token is revoked.
    """
    redis = await _get_redis(request)
    result = await AuthService.refresh_tokens(
        raw_refresh_token=body.refresh_token,
        db=db,
        redis=redis,
    )
    return TokenRefreshResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        refresh_token=result["refresh_token"],
    )


# ── POST /mfa/verify ───────────────────────────────────────────────────────────

@router.post(
    "/mfa/verify",
    response_model=LoginResponse,
    summary="Complete MFA challenge after login",
    status_code=status.HTTP_200_OK,
)
async def verify_mfa(
    body: MFAVerifyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Verify a TOTP code against an active MFA challenge.
    Returns full tokens on success.
    """
    if not body.challenge_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="challenge_token is required for MFA verification",
        )
    redis = await _get_redis(request)
    result = await AuthService.verify_mfa(
        challenge_token=body.challenge_token,
        totp_code=body.code,
        db=db,
        redis=redis,
    )
    return LoginResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        user=result["user"],
    )


# ── POST /forgot-password ──────────────────────────────────────────────────────

@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset email",
    status_code=status.HTTP_200_OK,
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Send a password reset link to the given email.
    Always returns 200 to prevent email enumeration.
    """
    await AuthService.forgot_password(email=body.email, db=db)
    return MessageResponse(
        message="If that email is registered, a reset link has been sent."
    )


# ── POST /reset-password ───────────────────────────────────────────────────────

@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password using one-time token",
    status_code=status.HTTP_200_OK,
)
async def reset_password(
    body: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Complete a password reset. Invalidates all existing sessions after success.
    """
    await AuthService.reset_password(
        raw_token=body.token,
        new_password=body.new_password,
        db=db,
    )
    return MessageResponse(message="Password reset successfully. Please log in again.")


# ── POST /accept-invite ────────────────────────────────────────────────────────

@router.post(
    "/accept-invite",
    response_model=UserResponse,
    summary="Register via invite token",
    status_code=status.HTTP_201_CREATED,
)
async def accept_invite(
    body: InviteAcceptRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Accept an invitation and create a new user account.
    """
    return await AuthService.accept_invite(
        raw_token=body.token,
        display_name=body.display_name,
        password=body.password,
        db=db,
    )


# ── GET /me ────────────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
    status_code=status.HTTP_200_OK,
)
async def get_me(
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the full user profile for the currently authenticated user."""
    repo = AuthRepository(db)
    db_user = await repo.get_user_by_id(user.user_id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(db_user)


# ── PUT /me ────────────────────────────────────────────────────────────────────

@router.put(
    "/me",
    response_model=UserResponse,
    summary="Update own profile",
    status_code=status.HTTP_200_OK,
)
async def update_me(
    body: UserUpdateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update the current user's display_name or avatar_url."""
    repo = AuthRepository(db)
    update_data: dict = {}
    if body.display_name is not None:
        update_data["display_name"] = body.display_name
    if body.avatar_url is not None:
        update_data["avatar_url"] = body.avatar_url

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    updated = await repo.update_user(user.user_id, **update_data)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(updated)


# ── POST /me/change-password ───────────────────────────────────────────────────

@router.post(
    "/me/change-password",
    response_model=MessageResponse,
    summary="Change own password",
    status_code=status.HTTP_200_OK,
)
async def change_password(
    body: ChangePasswordRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Change the current user's password. Requires the current password."""
    await AuthService.change_password(
        user_id=user.user_id,
        org_id=user.org_id,
        current_password=body.current_password,
        new_password=body.new_password,
        db=db,
    )
    return MessageResponse(message="Password changed successfully")


# ── GET /me/sessions ───────────────────────────────────────────────────────────

@router.get(
    "/me/sessions",
    response_model=list[SessionResponse],
    summary="List my active sessions",
    status_code=status.HTTP_200_OK,
)
async def list_my_sessions(
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all non-revoked sessions for the current user."""
    repo = AuthRepository(db)
    sessions = await repo.list_user_sessions(user.user_id)
    return [
        SessionResponse(
            **{
                "id": s.id,
                "device_fingerprint": s.device_fingerprint,
                "user_agent": s.user_agent,
                "ip_address": s.ip_address,
                "created_at": s.created_at,
                "last_used_at": s.last_used_at,
                "expires_at": s.expires_at,
                "is_revoked": s.is_revoked,
                "is_current": s.id == user.session_id,
            }
        )
        for s in sessions
    ]


# ── DELETE /me/sessions/{id} ───────────────────────────────────────────────────

@router.delete(
    "/me/sessions/{session_id}",
    response_model=MessageResponse,
    summary="Revoke a specific session",
    status_code=status.HTTP_200_OK,
)
async def revoke_my_session(
    session_id: uuid.UUID,
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Revoke a specific session belonging to the current user."""
    repo = AuthRepository(db)
    session = await repo.get_session_by_id(session_id)
    if not session or session.user_id != user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await repo.revoke_session(session_id, "user_revoked")
    return MessageResponse(message="Session revoked successfully")


# ── GET /me/mfa/setup ──────────────────────────────────────────────────────────

@router.get(
    "/me/mfa/setup",
    response_model=MFASetupResponse,
    summary="Initiate MFA setup (TOTP)",
    status_code=status.HTTP_200_OK,
)
async def setup_mfa(
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Generate a TOTP secret and QR code for MFA enrollment.
    MFA is not active until confirmed via POST /me/mfa/enable.
    """
    return await AuthService.setup_mfa(user_id=user.user_id, db=db)


# ── POST /me/mfa/enable ────────────────────────────────────────────────────────

@router.post(
    "/me/mfa/enable",
    response_model=MessageResponse,
    summary="Confirm and enable MFA",
    status_code=status.HTTP_200_OK,
)
async def enable_mfa(
    body: MFAEnableRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Verify the first TOTP code to confirm MFA setup and enable it.
    """
    await AuthService.enable_mfa(user_id=user.user_id, totp_code=body.code, db=db)
    return MessageResponse(message="MFA enabled successfully")


# ── DELETE /me/mfa ────────────────────────────────────────────────────────────

@router.delete(
    "/me/mfa",
    response_model=MessageResponse,
    summary="Disable MFA",
    status_code=status.HTTP_200_OK,
)
async def disable_mfa(
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Disable MFA for the current user."""
    await AuthService.disable_mfa(user_id=user.user_id, org_id=user.org_id, db=db)
    return MessageResponse(message="MFA disabled successfully")


# ── GET /me/notifications ─────────────────────────────────────────────────────

@router.get(
    "/me/notifications",
    response_model=list[NotificationPreferenceResponse],
    summary="Get notification preferences",
    status_code=status.HTTP_200_OK,
)
async def get_notification_prefs(
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all notification preference settings for the current user."""
    repo = AuthRepository(db)
    prefs = await repo.get_notification_prefs(user.user_id)
    return [NotificationPreferenceResponse.model_validate(p) for p in prefs]


# ── PUT /me/notifications/{category}/{channel} ────────────────────────────────

@router.put(
    "/me/notifications/{category}/{channel}",
    response_model=NotificationPreferenceResponse,
    summary="Update a notification preference",
    status_code=status.HTTP_200_OK,
)
async def update_notification_pref(
    category: str,
    channel: str,
    body: NotificationPreferenceUpdate,
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Upsert a notification preference for a category + channel combination.

    Valid categories: INVENTORY_ALERT, MISSION, ROBOT, SYSTEM, SECURITY
    Valid channels:   EMAIL, IN_APP, PUSH
    """
    valid_categories = {"INVENTORY_ALERT", "MISSION", "ROBOT", "SYSTEM", "SECURITY"}
    valid_channels = {"EMAIL", "IN_APP", "PUSH"}

    if category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid category. Must be one of: {', '.join(sorted(valid_categories))}",
        )
    if channel not in valid_channels:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid channel. Must be one of: {', '.join(sorted(valid_channels))}",
        )

    repo = AuthRepository(db)
    update_data = body.model_dump(exclude_none=True)
    pref = await repo.upsert_notification_pref(
        user_id=user.user_id,
        category=category,
        channel=channel,
        **update_data,
    )
    return NotificationPreferenceResponse.model_validate(pref)
