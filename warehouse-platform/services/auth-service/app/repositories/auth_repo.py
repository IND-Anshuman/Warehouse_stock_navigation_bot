"""
app/repositories/auth_repo.py — Async data-access layer for auth-service.

All methods accept an AsyncSession and return ORM model instances.
No business logic lives here — only DB queries.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import (
    AuditLog,
    InviteToken,
    NotificationPreference,
    Organization,
    PasswordReset,
    Permission,
    Role,
    RolePermission,
    Session,
    User,
    UserRole,
)
from app.schemas.auth import OrganizationCreate

log = structlog.get_logger(__name__)

# ── Default system roles and their permissions ────────────────────────────────
_SYSTEM_ROLES: list[dict] = [
    {
        "name": "WAREHOUSE_OPERATOR",
        "display_name": "Warehouse Operator",
        "description": "Day-to-day warehouse floor operations",
        "permissions": [
            ("inventory", "read"),
            ("mission", "read"),
            ("mission", "execute"),
            ("robot", "read"),
        ],
    },
    {
        "name": "WAREHOUSE_SUPERVISOR",
        "display_name": "Warehouse Supervisor",
        "description": "Supervises operators and manages missions",
        "permissions": [
            ("inventory", "read"),
            ("inventory", "update"),
            ("mission", "read"),
            ("mission", "create"),
            ("mission", "execute"),
            ("mission", "cancel"),
            ("robot", "read"),
            ("robot", "control"),
            ("report", "read"),
        ],
    },
    {
        "name": "WAREHOUSE_MANAGER",
        "display_name": "Warehouse Manager",
        "description": "Full warehouse management including user management",
        "permissions": [
            ("inventory", "read"),
            ("inventory", "create"),
            ("inventory", "update"),
            ("inventory", "delete"),
            ("mission", "read"),
            ("mission", "create"),
            ("mission", "execute"),
            ("mission", "cancel"),
            ("mission", "delete"),
            ("robot", "read"),
            ("robot", "control"),
            ("robot", "configure"),
            ("report", "read"),
            ("report", "export"),
            ("user", "read"),
            ("user", "invite"),
        ],
    },
    {
        "name": "ENTERPRISE_ADMIN",
        "display_name": "Enterprise Administrator",
        "description": "Full platform administration across all warehouses",
        "permissions": [
            ("inventory", "read"),
            ("inventory", "create"),
            ("inventory", "update"),
            ("inventory", "delete"),
            ("mission", "read"),
            ("mission", "create"),
            ("mission", "execute"),
            ("mission", "cancel"),
            ("mission", "delete"),
            ("robot", "read"),
            ("robot", "control"),
            ("robot", "configure"),
            ("robot", "decommission"),
            ("report", "read"),
            ("report", "export"),
            ("user", "read"),
            ("user", "create"),
            ("user", "update"),
            ("user", "delete"),
            ("user", "invite"),
            ("org", "read"),
            ("org", "update"),
            ("audit", "read"),
            ("role", "read"),
            ("role", "assign"),
        ],
    },
]


class AuthRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Organization ───────────────────────────────────────────────────────────

    async def get_org_by_id(self, org_id: uuid.UUID) -> Optional[Organization]:
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_org_by_slug(self, slug: str) -> Optional[Organization]:
        result = await self.db.execute(
            select(Organization).where(Organization.slug == slug)
        )
        return result.scalar_one_or_none()

    async def create_org(self, data: OrganizationCreate) -> Organization:
        org = Organization(
            name=data.name,
            slug=data.slug,
            logo_url=data.logo_url,
            industry=data.industry,
            mfa_policy=data.mfa_policy,
            session_timeout_hours=data.session_timeout_hours,
            data_retention_days=data.data_retention_days,
        )
        self.db.add(org)
        await self.db.flush([org])
        await self.db.refresh(org)
        log.info("org.created", org_id=str(org.id), slug=org.slug)
        return org

    async def update_org(self, org_id: uuid.UUID, **kwargs) -> Optional[Organization]:
        stmt = (
            update(Organization)
            .where(Organization.id == org_id)
            .values(**kwargs, updated_at=datetime.now(tz=timezone.utc))
            .returning(Organization)
        )
        result = await self.db.execute(stmt)
        org = result.scalar_one_or_none()
        if org:
            await self.db.refresh(org)
        return org

    # ── User ───────────────────────────────────────────────────────────────────

    async def get_user_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_users_by_org(
        self,
        org_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        status_filter: Optional[str] = None,
    ) -> tuple[list[User], int]:
        base_where = [User.org_id == org_id, User.deleted_at.is_(None)]
        if status_filter:
            base_where.append(User.status == status_filter)

        # Total count
        count_result = await self.db.execute(
            select(func.count(User.id)).where(and_(*base_where))
        )
        total = count_result.scalar_one()

        # Paginated rows
        rows_result = await self.db.execute(
            select(User)
            .where(and_(*base_where))
            .order_by(User.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        users = list(rows_result.scalars().all())
        return users, total

    async def create_user(
        self,
        org_id: uuid.UUID,
        email: str,
        display_name: str,
        password_hash: Optional[str] = None,
        status: str = "ACTIVE",
    ) -> User:
        user = User(
            org_id=org_id,
            email=email.lower(),
            display_name=display_name,
            password_hash=password_hash,
            status=status,
        )
        self.db.add(user)
        await self.db.flush([user])
        await self.db.refresh(user)
        log.info("user.created", user_id=str(user.id), email=email)
        return user

    async def update_user(self, user_id: uuid.UUID, **kwargs) -> Optional[User]:
        kwargs["updated_at"] = datetime.now(tz=timezone.utc)
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(**kwargs)
            .returning(User)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            await self.db.refresh(user)
        return user

    async def increment_failed_logins(
        self,
        user_id: uuid.UUID,
        lockout_until: Optional[datetime] = None,
    ) -> Optional[User]:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(
                failed_login_attempts=User.failed_login_attempts + 1,
                locked_until=lockout_until,
                updated_at=datetime.now(tz=timezone.utc),
            )
            .returning(User)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            await self.db.refresh(user)
        return user

    async def reset_failed_logins(self, user_id: uuid.UUID) -> Optional[User]:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(
                failed_login_attempts=0,
                locked_until=None,
                updated_at=datetime.now(tz=timezone.utc),
            )
            .returning(User)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            await self.db.refresh(user)
        return user

    async def update_last_login(self, user_id: uuid.UUID, ip: str) -> Optional[User]:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(
                last_login_at=now,
                last_login_ip=ip,
                updated_at=now,
            )
            .returning(User)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            await self.db.refresh(user)
        return user

    async def soft_delete_user(self, user_id: uuid.UUID) -> Optional[User]:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(
                status="DELETED",
                deleted_at=now,
                updated_at=now,
            )
            .returning(User)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            await self.db.refresh(user)
        return user

    # ── Roles & Permissions ────────────────────────────────────────────────────

    async def get_roles_for_org(self, org_id: uuid.UUID) -> list[Role]:
        result = await self.db.execute(
            select(Role)
            .where(Role.org_id == org_id)
            .options(
                selectinload(Role.role_permissions).selectinload(RolePermission.permission)
            )
            .order_by(Role.name)
        )
        return list(result.scalars().all())

    async def get_role_by_id(self, role_id: uuid.UUID) -> Optional[Role]:
        result = await self.db.execute(
            select(Role)
            .where(Role.id == role_id)
            .options(
                selectinload(Role.role_permissions).selectinload(RolePermission.permission)
            )
        )
        return result.scalar_one_or_none()

    async def get_role_by_name(self, org_id: uuid.UUID, name: str) -> Optional[Role]:
        result = await self.db.execute(
            select(Role).where(and_(Role.org_id == org_id, Role.name == name))
        )
        return result.scalar_one_or_none()

    async def _get_or_create_permission(
        self, resource: str, action: str
    ) -> Permission:
        result = await self.db.execute(
            select(Permission).where(
                and_(Permission.resource == resource, Permission.action == action)
            )
        )
        perm = result.scalar_one_or_none()
        if not perm:
            perm = Permission(resource=resource, action=action)
            self.db.add(perm)
            await self.db.flush([perm])
        return perm

    async def seed_default_roles(self, org_id: uuid.UUID) -> list[Role]:
        """Create the 4 system roles with their permissions for a new organization."""
        created_roles: list[Role] = []
        for role_def in _SYSTEM_ROLES:
            # Check if role already exists (idempotent)
            existing = await self.get_role_by_name(org_id, role_def["name"])
            if existing:
                created_roles.append(existing)
                continue

            role = Role(
                org_id=org_id,
                name=role_def["name"],
                display_name=role_def["display_name"],
                description=role_def["description"],
                is_system_role=True,
            )
            self.db.add(role)
            await self.db.flush([role])

            # Attach permissions
            for resource, action in role_def["permissions"]:
                perm = await self._get_or_create_permission(resource, action)
                rp = RolePermission(role_id=role.id, permission_id=perm.id)
                self.db.add(rp)

            await self.db.flush()
            await self.db.refresh(role)
            created_roles.append(role)
            log.info("role.seeded", org_id=str(org_id), role=role.name)

        return created_roles

    async def assign_role(
        self,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        warehouse_id: Optional[uuid.UUID],
        assigned_by: uuid.UUID,
    ) -> UserRole:
        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
            warehouse_id=warehouse_id,
            assigned_by=assigned_by,
        )
        self.db.add(user_role)
        await self.db.flush([user_role])
        await self.db.refresh(user_role)
        return user_role

    async def remove_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        stmt = delete(UserRole).where(
            and_(UserRole.user_id == user_id, UserRole.role_id == role_id)
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def get_user_roles(self, user_id: uuid.UUID) -> list[UserRole]:
        result = await self.db.execute(
            select(UserRole)
            .where(UserRole.user_id == user_id)
            .options(
                selectinload(UserRole.role).selectinload(Role.role_permissions).selectinload(RolePermission.permission)
            )
        )
        return list(result.scalars().all())

    async def get_user_permissions(self, user_id: uuid.UUID) -> list[str]:
        """Return a deduplicated list of 'resource:action' strings for the user."""
        result = await self.db.execute(
            select(Permission.resource, Permission.action)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .distinct()
        )
        rows = result.all()
        return [f"{row.resource}:{row.action}" for row in rows]

    # ── Sessions ───────────────────────────────────────────────────────────────

    async def create_session(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        device_fp: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> Session:
        session = Session(
            user_id=user_id,
            refresh_token_hash=token_hash,
            expires_at=expires_at,
            device_fingerprint=device_fp,
            user_agent=user_agent,
            ip_address=ip,
        )
        self.db.add(session)
        await self.db.flush([session])
        await self.db.refresh(session)
        return session

    async def get_session_by_token_hash(self, token_hash: str) -> Optional[Session]:
        result = await self.db.execute(
            select(Session)
            .where(Session.refresh_token_hash == token_hash)
            .options(selectinload(Session.user))
        )
        return result.scalar_one_or_none()

    async def get_session_by_id(self, session_id: uuid.UUID) -> Optional[Session]:
        result = await self.db.execute(
            select(Session).where(Session.id == session_id)
        )
        return result.scalar_one_or_none()

    async def revoke_session(self, session_id: uuid.UUID, reason: str) -> Optional[Session]:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            update(Session)
            .where(Session.id == session_id)
            .values(is_revoked=True, revoked_at=now, revoked_reason=reason)
            .returning(Session)
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            await self.db.refresh(session)
        return session

    async def revoke_all_user_sessions(self, user_id: uuid.UUID, reason: str) -> int:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            update(Session)
            .where(and_(Session.user_id == user_id, Session.is_revoked.is_(False)))
            .values(is_revoked=True, revoked_at=now, revoked_reason=reason)
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    async def list_user_sessions(self, user_id: uuid.UUID) -> list[Session]:
        result = await self.db.execute(
            select(Session)
            .where(and_(Session.user_id == user_id, Session.is_revoked.is_(False)))
            .order_by(Session.last_used_at.desc())
        )
        return list(result.scalars().all())

    async def update_session_last_used(self, session_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(last_used_at=datetime.now(tz=timezone.utc))
        )

    async def cleanup_expired_sessions(self) -> int:
        now = datetime.now(tz=timezone.utc)
        stmt = delete(Session).where(
            or_(
                Session.expires_at < now,
                and_(Session.is_revoked.is_(True), Session.revoked_at < now),
            )
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    # ── Invite tokens ──────────────────────────────────────────────────────────

    async def create_invite(
        self,
        org_id: uuid.UUID,
        inviter_id: uuid.UUID,
        email: str,
        role_id: uuid.UUID,
        warehouse_id: Optional[uuid.UUID],
        token_hash: str,
        expires_at: datetime,
    ) -> InviteToken:
        invite = InviteToken(
            org_id=org_id,
            inviter_user_id=inviter_id,
            invited_email=email.lower(),
            role_id=role_id,
            warehouse_id=warehouse_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(invite)
        await self.db.flush([invite])
        await self.db.refresh(invite)
        return invite

    async def get_invite_by_token_hash(self, token_hash: str) -> Optional[InviteToken]:
        result = await self.db.execute(
            select(InviteToken)
            .where(InviteToken.token_hash == token_hash)
            .options(selectinload(InviteToken.role))
        )
        return result.scalar_one_or_none()

    async def accept_invite(self, invite_id: uuid.UUID) -> Optional[InviteToken]:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            update(InviteToken)
            .where(InviteToken.id == invite_id)
            .values(status="ACCEPTED", accepted_at=now)
            .returning(InviteToken)
        )
        result = await self.db.execute(stmt)
        invite = result.scalar_one_or_none()
        if invite:
            await self.db.refresh(invite)
        return invite

    async def revoke_invite(self, invite_id: uuid.UUID) -> Optional[InviteToken]:
        stmt = (
            update(InviteToken)
            .where(InviteToken.id == invite_id)
            .values(status="REVOKED")
            .returning(InviteToken)
        )
        result = await self.db.execute(stmt)
        invite = result.scalar_one_or_none()
        if invite:
            await self.db.refresh(invite)
        return invite

    async def get_invite_by_id(self, invite_id: uuid.UUID) -> Optional[InviteToken]:
        result = await self.db.execute(
            select(InviteToken).where(InviteToken.id == invite_id)
        )
        return result.scalar_one_or_none()

    async def list_pending_invites(self, org_id: uuid.UUID) -> list[InviteToken]:
        result = await self.db.execute(
            select(InviteToken)
            .where(
                and_(
                    InviteToken.org_id == org_id,
                    InviteToken.status == "PENDING",
                )
            )
            .order_by(InviteToken.created_at.desc())
        )
        return list(result.scalars().all())

    # ── Password resets ────────────────────────────────────────────────────────

    async def create_password_reset(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordReset:
        reset = PasswordReset(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(reset)
        await self.db.flush([reset])
        await self.db.refresh(reset)
        return reset

    async def get_reset_by_token_hash(self, token_hash: str) -> Optional[PasswordReset]:
        result = await self.db.execute(
            select(PasswordReset)
            .where(PasswordReset.token_hash == token_hash)
            .options(selectinload(PasswordReset.user))
        )
        return result.scalar_one_or_none()

    async def use_password_reset(self, reset_id: uuid.UUID) -> Optional[PasswordReset]:
        stmt = (
            update(PasswordReset)
            .where(PasswordReset.id == reset_id)
            .values(used_at=datetime.now(tz=timezone.utc))
            .returning(PasswordReset)
        )
        result = await self.db.execute(stmt)
        reset = result.scalar_one_or_none()
        if reset:
            await self.db.refresh(reset)
        return reset

    # ── Audit logs ─────────────────────────────────────────────────────────────

    async def get_audit_logs(
        self,
        org_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
        event_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditLog], int]:
        filters = [AuditLog.org_id == org_id]
        if actor_id:
            filters.append(AuditLog.actor_user_id == actor_id)
        if event_type:
            filters.append(AuditLog.event_type == event_type)
        if start_date:
            filters.append(AuditLog.created_at >= start_date)
        if end_date:
            filters.append(AuditLog.created_at <= end_date)

        count_result = await self.db.execute(
            select(func.count(AuditLog.id)).where(and_(*filters))
        )
        total = count_result.scalar_one()

        rows_result = await self.db.execute(
            select(AuditLog)
            .where(and_(*filters))
            .order_by(AuditLog.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        logs = list(rows_result.scalars().all())
        return logs, total

    # ── Notification preferences ───────────────────────────────────────────────

    async def get_notification_prefs(self, user_id: uuid.UUID) -> list[NotificationPreference]:
        result = await self.db.execute(
            select(NotificationPreference)
            .where(NotificationPreference.user_id == user_id)
            .order_by(NotificationPreference.category, NotificationPreference.channel)
        )
        return list(result.scalars().all())

    async def upsert_notification_pref(
        self,
        user_id: uuid.UUID,
        category: str,
        channel: str,
        **kwargs,
    ) -> NotificationPreference:
        result = await self.db.execute(
            select(NotificationPreference).where(
                and_(
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.category == category,
                    NotificationPreference.channel == channel,
                )
            )
        )
        pref = result.scalar_one_or_none()
        if pref:
            for key, value in kwargs.items():
                setattr(pref, key, value)
            self.db.add(pref)
        else:
            pref = NotificationPreference(
                user_id=user_id,
                category=category,
                channel=channel,
                **kwargs,
            )
            self.db.add(pref)
        await self.db.flush([pref])
        await self.db.refresh(pref)
        return pref
