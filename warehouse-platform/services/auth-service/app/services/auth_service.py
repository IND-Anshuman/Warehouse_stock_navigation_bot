"""
app/services/auth_service.py — Business logic layer for auth-service.

Orchestrates repositories, security utilities, rate limiting, audit logging,
email dispatch, and MFA. All methods are fully implemented.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pyotp
import qrcode
import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import AuditEventType, write_audit_log
from app.core.rate_limiter import (
    check_rate_limit,
    increment_login_failures,
    reset_login_attempts,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_secure_token,
    hash_password,
    hash_token,
    is_password_strong,
    verify_password,
)
from app.models.auth import InviteToken, User
from app.repositories.auth_repo import AuthRepository
from app.schemas.auth import (
    InviteCreateRequest,
    LoginResponse,
    MFASetupResponse,
    OrganizationCreate,
    TokenRefreshResponse,
    UserResponse,
)

log = structlog.get_logger(__name__)


# ── Email helpers ──────────────────────────────────────────────────────────────

async def _send_email(to: str, subject: str, body: str) -> None:
    """
    Send an email using SMTP. Falls back to structured logging when SMTP is
    not configured (development mode).
    """
    if not settings.SMTP_HOST or settings.SMTP_HOST in ("localhost", ""):
        log.info(
            "email.dev_mode",
            to=to,
            subject=subject,
            body_preview=body[:200],
        )
        return
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        part = MIMEText(body, "html")
        msg.attach(part)

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_TLS:
                server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [to], msg.as_string())
        log.info("email.sent", to=to, subject=subject)
    except Exception as exc:
        log.error("email.send_failed", to=to, subject=subject, error=str(exc))


def _build_user_token_payload(user: User, permissions: list[str], session_id: uuid.UUID) -> dict[str, Any]:
    """Construct the JWT payload for an authenticated user."""
    # Get first role name from user_roles (loaded separately)
    return {
        "sub": str(user.id),
        "email": user.email,
        "org_id": str(user.org_id),
        "session_id": str(session_id),
        "permissions": permissions,
    }


# ── Auth Service ───────────────────────────────────────────────────────────────

class AuthService:

    # ── Login ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def login(
        email: str,
        password: str,
        ip: str,
        user_agent: str,
        device_fingerprint: Optional[str],
        db: AsyncSession,
        redis,
    ) -> dict[str, Any]:
        """
        Authenticate a user with email + password.

        Returns either a full LoginResponse payload or a dict with
        requires_mfa=True + mfa_challenge_token when MFA is required.

        Steps:
          1. IP-based rate limit check (20 req/60 s)
          2. Lookup user by email; verify account status
          3. Check account lockout
          4. Verify password; handle failures
          5. Reset failure counter on success
          6. MFA gate
          7. Build tokens and session
          8. Audit log
        """
        repo = AuthRepository(db)

        # 1. Rate limit by IP
        allowed = await check_rate_limit(
            redis,
            key=f"login_ip:{ip}",
            max_requests=settings.RATE_LIMIT_LOGIN_REQUESTS,
            window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please try again later.",
            )

        # 2. Lookup user
        user = await repo.get_user_by_email(email)
        if not user:
            # Timing-safe: always hash even on miss
            hash_password("dummy-to-prevent-timing")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if user.status in ("SUSPENDED", "DELETED"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account is {user.status.lower()}. Contact your administrator.",
            )

        # 3. Check lockout
        now = datetime.now(tz=timezone.utc)
        if user.locked_until and user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds() / 60)
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account is locked. Try again in {remaining} minutes.",
            )

        # 4. Verify password
        if not user.password_hash or not verify_password(password, user.password_hash):
            new_count = await increment_login_failures(redis, email, settings.LOCKOUT_MINUTES)
            should_lock = new_count >= settings.MAX_FAILED_LOGINS
            lockout_until = (
                datetime.now(tz=timezone.utc) + timedelta(minutes=settings.LOCKOUT_MINUTES)
                if should_lock
                else None
            )
            await repo.increment_failed_logins(user.id, lockout_until)
            if should_lock:
                await write_audit_log(
                    db,
                    event_type=AuditEventType.ACCOUNT_LOCKED,
                    org_id=user.org_id,
                    actor_user_id=user.id,
                    actor_ip=ip,
                    outcome="SUCCESS",
                    metadata={"reason": "max_failed_logins", "locked_until": str(lockout_until)},
                )
            await write_audit_log(
                db,
                event_type=AuditEventType.USER_LOGIN_FAILURE,
                org_id=user.org_id,
                actor_user_id=user.id,
                actor_ip=ip,
                outcome="FAILURE",
                metadata={"attempts": new_count},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # 5. Reset failure counter
        await reset_login_attempts(redis, email)
        await repo.reset_failed_logins(user.id)

        # 6. MFA gate
        if user.mfa_enabled and user.mfa_secret:
            # Store pending auth context in Redis for 5 minutes
            challenge_id = str(uuid.uuid4())
            challenge_key = f"mfa_challenge:{challenge_id}"
            challenge_data = json.dumps({
                "user_id": str(user.id),
                "ip": ip,
                "user_agent": user_agent,
                "device_fingerprint": device_fingerprint,
            })
            await redis.setex(challenge_key, 300, challenge_data)
            return {
                "requires_mfa": True,
                "mfa_challenge_token": challenge_id,
                "access_token": "",
                "token_type": "bearer",
                "expires_in": 0,
                "user": UserResponse.model_validate(user),
            }

        # 7. Issue tokens and create session
        return await AuthService._issue_tokens_and_session(
            user=user, ip=ip, user_agent=user_agent,
            device_fingerprint=device_fingerprint, db=db, repo=repo,
        )

    # ── MFA Verify ─────────────────────────────────────────────────────────────

    @staticmethod
    async def verify_mfa(
        challenge_token: str,
        totp_code: str,
        db: AsyncSession,
        redis,
    ) -> dict[str, Any]:
        """Validate a TOTP code against a pending MFA challenge and issue tokens."""
        challenge_key = f"mfa_challenge:{challenge_token}"
        raw = await redis.get(challenge_key)
        if not raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="MFA challenge expired or invalid",
            )

        challenge: dict = json.loads(raw)
        user_id = uuid.UUID(challenge["user_id"])
        ip: str = challenge.get("ip", "")
        user_agent: str = challenge.get("user_agent", "")
        device_fp: Optional[str] = challenge.get("device_fingerprint")

        repo = AuthRepository(db)
        user = await repo.get_user_by_id(user_id)
        if not user or not user.mfa_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid MFA challenge",
            )

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(totp_code, valid_window=1):
            await write_audit_log(
                db,
                event_type=AuditEventType.MFA_CHALLENGE_FAILED,
                org_id=user.org_id,
                actor_user_id=user.id,
                actor_ip=ip,
                outcome="FAILURE",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid MFA code",
            )

        # Consume challenge
        await redis.delete(challenge_key)

        return await AuthService._issue_tokens_and_session(
            user=user, ip=ip, user_agent=user_agent,
            device_fingerprint=device_fp, db=db, repo=repo,
        )

    # ── Shared token issuance ──────────────────────────────────────────────────

    @staticmethod
    async def _issue_tokens_and_session(
        user: User,
        ip: str,
        user_agent: str,
        device_fingerprint: Optional[str],
        db: AsyncSession,
        repo: AuthRepository,
    ) -> dict[str, Any]:
        """Create refresh token, session record, and access token. Write audit log."""
        permissions = await repo.get_user_permissions(user.id)
        user_roles = await repo.get_user_roles(user.id)
        primary_role = user_roles[0].role.name if user_roles else "NONE"

        raw_refresh = create_refresh_token()
        refresh_hash = hash_token(raw_refresh)
        expires_at = datetime.now(tz=timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        session = await repo.create_session(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=expires_at,
            device_fp=device_fingerprint,
            user_agent=user_agent,
            ip=ip,
        )

        payload = _build_user_token_payload(user, permissions, session.id)
        payload["role"] = primary_role
        access_token = create_access_token(payload)

        await repo.update_last_login(user.id, ip)

        await write_audit_log(
            db,
            event_type=AuditEventType.USER_LOGIN_SUCCESS,
            org_id=user.org_id,
            actor_user_id=user.id,
            actor_role=primary_role,
            actor_ip=ip,
            resource_type="session",
            resource_id=session.id,
            outcome="SUCCESS",
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "refresh_token": raw_refresh,
            "requires_mfa": False,
            "user": UserResponse.model_validate(user),
        }

    # ── Refresh tokens ─────────────────────────────────────────────────────────

    @staticmethod
    async def refresh_tokens(
        raw_refresh_token: str,
        db: AsyncSession,
        redis,
    ) -> dict[str, Any]:
        """
        Rotate the refresh token:
          - Lookup session by hashed refresh token
          - Validate not revoked, not expired, user still active
          - Revoke old session, create new session + new access token
        """
        repo = AuthRepository(db)
        token_hash = hash_token(raw_refresh_token)
        session = await repo.get_session_by_token_hash(token_hash)

        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        if session.is_revoked:
            # Possible token reuse attack — revoke all sessions for safety
            await repo.revoke_all_user_sessions(session.user_id, "refresh_token_reuse")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token already used. All sessions have been revoked.",
            )
        now = datetime.now(tz=timezone.utc)
        if session.expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has expired",
            )

        user = await repo.get_user_by_id(session.user_id)
        if not user or user.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is not active",
            )

        # Revoke old session
        await repo.revoke_session(session.id, "token_rotation")

        # Issue new refresh token + session
        permissions = await repo.get_user_permissions(user.id)
        user_roles = await repo.get_user_roles(user.id)
        primary_role = user_roles[0].role.name if user_roles else "NONE"

        new_raw_refresh = create_refresh_token()
        new_hash = hash_token(new_raw_refresh)
        new_expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        new_session = await repo.create_session(
            user_id=user.id,
            token_hash=new_hash,
            expires_at=new_expires,
            device_fp=session.device_fingerprint,
            user_agent=session.user_agent,
            ip=session.ip_address,
        )

        payload = _build_user_token_payload(user, permissions, new_session.id)
        payload["role"] = primary_role
        access_token = create_access_token(payload)

        await write_audit_log(
            db,
            event_type=AuditEventType.TOKEN_REFRESHED,
            org_id=user.org_id,
            actor_user_id=user.id,
            actor_role=primary_role,
            outcome="SUCCESS",
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "refresh_token": new_raw_refresh,
        }

    # ── Logout ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def logout(
        session_id: uuid.UUID,
        user: Any,  # UserContext
        db: AsyncSession,
    ) -> None:
        """Revoke the current session and write audit log."""
        repo = AuthRepository(db)
        await repo.revoke_session(session_id, "user_logout")
        await write_audit_log(
            db,
            event_type=AuditEventType.USER_LOGOUT,
            org_id=user.org_id,
            actor_user_id=user.user_id,
            actor_role=user.role,
            resource_type="session",
            resource_id=session_id,
            outcome="SUCCESS",
        )

    # ── Accept Invite ──────────────────────────────────────────────────────────

    @staticmethod
    async def accept_invite(
        raw_token: str,
        display_name: str,
        password: str,
        db: AsyncSession,
    ) -> UserResponse:
        """
        Register a new user via an invite token.

        Steps:
          1. Hash token → lookup InviteToken
          2. Validate status == PENDING and not expired
          3. Validate password strength
          4. Create User
          5. Assign role from invite
          6. Mark invite ACCEPTED
          7. Write audit log
        """
        repo = AuthRepository(db)
        token_hash = hash_token(raw_token)
        invite = await repo.get_invite_by_token_hash(token_hash)

        if not invite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invite token not found or already used",
            )
        if invite.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invite is {invite.status.lower()}",
            )
        if invite.expires_at < datetime.now(tz=timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite token has expired",
            )

        # Validate password
        ok, msg = is_password_strong(password)
        if not ok:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)

        # Check email not already registered in org
        existing = await repo.get_user_by_email(invite.invited_email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            )

        user = await repo.create_user(
            org_id=invite.org_id,
            email=invite.invited_email,
            display_name=display_name,
            password_hash=hash_password(password),
            status="ACTIVE",
        )

        await repo.assign_role(
            user_id=user.id,
            role_id=invite.role_id,
            warehouse_id=invite.warehouse_id,
            assigned_by=invite.inviter_user_id,
        )

        await repo.accept_invite(invite.id)

        await write_audit_log(
            db,
            event_type=AuditEventType.USER_CREATED,
            org_id=user.org_id,
            actor_user_id=invite.inviter_user_id,
            resource_type="user",
            resource_id=user.id,
            after_state={"email": user.email, "display_name": user.display_name},
            outcome="SUCCESS",
            metadata={"via": "invite", "invite_id": str(invite.id)},
        )

        return UserResponse.model_validate(user)

    # ── Forgot Password ────────────────────────────────────────────────────────

    @staticmethod
    async def forgot_password(email: str, db: AsyncSession) -> None:
        """
        Initiate a password reset flow.
        Always returns 200 even if email not found (prevents enumeration).
        """
        repo = AuthRepository(db)
        user = await repo.get_user_by_email(email)
        if not user or user.status not in ("ACTIVE", "PENDING"):
            log.info("password_reset.email_not_found", email=email)
            return  # Silent — do not reveal whether email exists

        raw_token, token_hash = generate_secure_token()
        expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=settings.RESET_TOKEN_EXPIRE_HOURS)

        await repo.create_password_reset(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
        await _send_email(
            to=email,
            subject="Password Reset Request — Warehouse Platform",
            body=(
                f"<p>Hello {user.display_name},</p>"
                f"<p>Click the link below to reset your password. "
                f"This link expires in {settings.RESET_TOKEN_EXPIRE_HOURS} hour(s).</p>"
                f"<p><a href='{reset_url}'>{reset_url}</a></p>"
                f"<p>If you did not request this, ignore this email.</p>"
            ),
        )

        await write_audit_log(
            db,
            event_type=AuditEventType.PASSWORD_RESET_REQUESTED,
            org_id=user.org_id,
            actor_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            outcome="SUCCESS",
        )

    # ── Reset Password ─────────────────────────────────────────────────────────

    @staticmethod
    async def reset_password(
        raw_token: str,
        new_password: str,
        db: AsyncSession,
    ) -> None:
        """
        Complete a password reset using a one-time token.

        Steps:
          1. Hash token → lookup PasswordReset
          2. Validate not expired, not already used
          3. Validate password strength
          4. Update password_hash
          5. Mark reset used
          6. Revoke all sessions (force re-login)
          7. Audit log
        """
        repo = AuthRepository(db)
        token_hash = hash_token(raw_token)
        reset = await repo.get_reset_by_token_hash(token_hash)

        if not reset:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            )
        if reset.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset token has already been used",
            )
        if reset.expires_at < datetime.now(tz=timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset token has expired",
            )

        ok, msg = is_password_strong(new_password)
        if not ok:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)

        user = reset.user
        await repo.update_user(
            user.id,
            password_hash=hash_password(new_password),
            password_changed_at=datetime.now(tz=timezone.utc),
        )
        await repo.use_password_reset(reset.id)
        revoked_count = await repo.revoke_all_user_sessions(user.id, "password_reset")

        await write_audit_log(
            db,
            event_type=AuditEventType.PASSWORD_RESET_COMPLETED,
            org_id=user.org_id,
            actor_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            outcome="SUCCESS",
            metadata={"sessions_revoked": revoked_count},
        )

    # ── Change Password ────────────────────────────────────────────────────────

    @staticmethod
    async def change_password(
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        current_password: str,
        new_password: str,
        db: AsyncSession,
    ) -> None:
        """Authenticated user changes their own password."""
        repo = AuthRepository(db)
        user = await repo.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if not user.password_hash or not verify_password(current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )

        ok, msg = is_password_strong(new_password)
        if not ok:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)

        await repo.update_user(
            user_id,
            password_hash=hash_password(new_password),
            password_changed_at=datetime.now(tz=timezone.utc),
        )

        await write_audit_log(
            db,
            event_type=AuditEventType.PASSWORD_CHANGED,
            org_id=org_id,
            actor_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            outcome="SUCCESS",
        )

    # ── Create Invite ──────────────────────────────────────────────────────────

    @staticmethod
    async def create_invite(
        org_id: uuid.UUID,
        inviter_id: uuid.UUID,
        invited_email: str,
        role_id: uuid.UUID,
        warehouse_id: Optional[uuid.UUID],
        db: AsyncSession,
    ) -> InviteToken:
        """
        Send an invite to a new user.

        Raises 409 if the email is already registered in the org.
        """
        repo = AuthRepository(db)

        existing = await repo.get_user_by_email(invited_email)
        if existing and existing.org_id == org_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists in the organization",
            )

        role = await repo.get_role_by_id(role_id)
        if not role or role.org_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found in this organization",
            )

        raw_token, token_hash = generate_secure_token()
        expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=settings.INVITE_TOKEN_EXPIRE_HOURS)

        invite = await repo.create_invite(
            org_id=org_id,
            inviter_id=inviter_id,
            email=invited_email,
            role_id=role_id,
            warehouse_id=warehouse_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        invite_url = f"{settings.FRONTEND_URL}/accept-invite?token={raw_token}"
        await _send_email(
            to=invited_email,
            subject="You're invited to Warehouse Platform",
            body=(
                f"<p>You have been invited to join the Warehouse Intelligence Platform.</p>"
                f"<p>Click the link below to accept your invitation (expires in "
                f"{settings.INVITE_TOKEN_EXPIRE_HOURS} hours):</p>"
                f"<p><a href='{invite_url}'>{invite_url}</a></p>"
            ),
        )

        inviter = await repo.get_user_by_id(inviter_id)
        inviter_role = None
        if inviter:
            inviter_roles = await repo.get_user_roles(inviter.id)
            inviter_role = inviter_roles[0].role.name if inviter_roles else None

        await write_audit_log(
            db,
            event_type=AuditEventType.USER_INVITED,
            org_id=org_id,
            actor_user_id=inviter_id,
            actor_role=inviter_role,
            resource_type="invite",
            resource_id=invite.id,
            after_state={"invited_email": invited_email, "role_id": str(role_id)},
            outcome="SUCCESS",
        )

        return invite

    # ── MFA Setup ──────────────────────────────────────────────────────────────

    @staticmethod
    async def setup_mfa(user_id: uuid.UUID, db: AsyncSession) -> MFASetupResponse:
        """
        Generate a new TOTP secret for a user and return setup data.
        Does NOT enable MFA — user must verify with a valid code first.
        """
        repo = AuthRepository(db)
        user = await repo.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user.email,
            issuer_name="Warehouse Intelligence Platform",
        )

        # Generate QR code as data URI
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        import base64
        qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        # Store secret temporarily (not yet enabled — pending verification)
        await repo.update_user(user_id, mfa_secret=secret)

        # Generate backup codes
        backup_codes = [pyotp.random_base32()[:8] for _ in range(8)]

        return MFASetupResponse(
            secret=secret,
            qr_code_url=qr_data_uri,
            backup_codes=backup_codes,
        )

    @staticmethod
    async def enable_mfa(user_id: uuid.UUID, totp_code: str, db: AsyncSession) -> None:
        """Confirm MFA setup by verifying the first TOTP code, then set mfa_enabled=True."""
        repo = AuthRepository(db)
        user = await repo.get_user_by_id(user_id)
        if not user or not user.mfa_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MFA setup not initiated. Call /me/mfa/setup first.",
            )

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(totp_code, valid_window=1):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid TOTP code. MFA not enabled.",
            )

        await repo.update_user(user_id, mfa_enabled=True)
        await write_audit_log(
            db,
            event_type=AuditEventType.MFA_ENABLED,
            org_id=user.org_id,
            actor_user_id=user_id,
            outcome="SUCCESS",
        )

    @staticmethod
    async def disable_mfa(user_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession) -> None:
        """Disable MFA for a user (admin or self)."""
        repo = AuthRepository(db)
        await repo.update_user(user_id, mfa_enabled=False, mfa_secret=None)
        await write_audit_log(
            db,
            event_type=AuditEventType.MFA_DISABLED,
            org_id=org_id,
            actor_user_id=user_id,
            outcome="SUCCESS",
        )
