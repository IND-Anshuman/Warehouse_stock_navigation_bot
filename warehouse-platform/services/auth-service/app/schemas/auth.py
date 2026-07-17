"""
app/schemas/auth.py — Pydantic v2 request/response schemas for auth-service.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Organization ───────────────────────────────────────────────────────────────

class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    logo_url: Optional[str] = None
    industry: Optional[str] = None
    mfa_policy: str = Field(default="OPTIONAL", pattern=r"^(OPTIONAL|REQUIRED)$")
    session_timeout_hours: int = Field(default=8, ge=1, le=168)
    data_retention_days: int = Field(default=730, ge=30, le=3650)


class OrganizationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    logo_url: Optional[str]
    industry: Optional[str]
    mfa_policy: str
    sso_enabled: bool
    sso_provider: Optional[str]
    session_timeout_hours: int
    data_retention_days: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationSettingsUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    logo_url: Optional[str] = None
    industry: Optional[str] = None
    mfa_policy: Optional[str] = Field(default=None, pattern=r"^(OPTIONAL|REQUIRED)$")
    sso_enabled: Optional[bool] = None
    sso_provider: Optional[str] = None
    sso_metadata_url: Optional[str] = None
    session_timeout_hours: Optional[int] = Field(default=None, ge=1, le=168)
    data_retention_days: Optional[int] = Field(default=None, ge=30, le=3650)


# ── User ───────────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    display_name: str
    avatar_url: Optional[str]
    status: str
    mfa_enabled: bool
    failed_login_attempts: int
    locked_until: Optional[datetime]
    last_login_at: Optional[datetime]
    last_login_ip: Optional[str]
    password_changed_at: datetime
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]


class UserCreateRequest(BaseModel):
    """Admin endpoint: manually create a user (no password — they must accept invite)."""
    email: EmailStr
    display_name: str = Field(..., min_length=2, max_length=255)
    role_id: uuid.UUID
    warehouse_id: Optional[uuid.UUID] = None


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    avatar_url: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern=r"^(ACTIVE|SUSPENDED|PENDING)$")


class UserRoleUpdateRequest(BaseModel):
    role_id: uuid.UUID
    warehouse_id: Optional[uuid.UUID] = None


# ── Authentication ─────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    device_fingerprint: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserResponse
    requires_mfa: bool = False
    mfa_challenge_token: Optional[str] = None


class TokenRefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str  # rotated refresh token


# ── MFA ────────────────────────────────────────────────────────────────────────

class MFASetupResponse(BaseModel):
    secret: str
    qr_code_url: str
    backup_codes: list[str]


class MFAVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)
    challenge_token: Optional[str] = None  # Required when called during login flow


class MFAEnableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, description="Current TOTP code to confirm setup")


# ── Invite ─────────────────────────────────────────────────────────────────────

class InviteCreateRequest(BaseModel):
    invited_email: EmailStr
    role_id: uuid.UUID
    warehouse_id: Optional[uuid.UUID] = None


class InviteResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    inviter_user_id: uuid.UUID
    invited_email: str
    role_id: uuid.UUID
    warehouse_id: Optional[uuid.UUID]
    status: str
    expires_at: datetime
    accepted_at: Optional[datetime]
    created_at: datetime


class InviteAcceptRequest(BaseModel):
    token: str = Field(..., min_length=10)
    display_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=12)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        import re
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character")
        return v


# ── Password ───────────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=12)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        import re
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        import re
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @model_validator(mode="after")
    def passwords_differ(self) -> "ChangePasswordRequest":
        if self.current_password == self.new_password:
            raise ValueError("New password must differ from the current password")
        return self


# ── Session ────────────────────────────────────────────────────────────────────

class SessionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    device_fingerprint: Optional[str]
    user_agent: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    is_revoked: bool
    is_current: bool = False  # injected at API layer


# ── Roles & Permissions ────────────────────────────────────────────────────────

class PermissionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    resource: str
    action: str
    description: Optional[str]


class RoleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    display_name: str
    description: Optional[str]
    is_system_role: bool
    created_at: datetime
    permissions: list[PermissionResponse] = []


# ── Audit Log ──────────────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    warehouse_id: Optional[uuid.UUID]
    actor_user_id: Optional[uuid.UUID]
    actor_role: Optional[str]
    actor_ip: Optional[str]
    event_type: str
    resource_type: Optional[str]
    resource_id: Optional[uuid.UUID]
    before_state: Optional[dict[str, Any]]
    after_state: Optional[dict[str, Any]]
    outcome: str
    metadata: Optional[dict[str, Any]]
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Notification Preferences ───────────────────────────────────────────────────

class NotificationPreferenceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    category: str
    channel: str
    enabled: bool
    frequency: str
    quiet_hours_start: Optional[time]
    quiet_hours_end: Optional[time]


class NotificationPreferenceUpdate(BaseModel):
    enabled: Optional[bool] = None
    frequency: Optional[str] = Field(default=None, pattern=r"^(IMMEDIATE|HOURLY_DIGEST|DAILY_DIGEST)$")
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None


# ── Generic responses ──────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
