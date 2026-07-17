"""
app/core/audit.py — Async audit log writer.

Writes structured AuditLog records to the database for every security-relevant
event. All writes are fire-and-continue: failures are logged but never bubble
up to the caller so that audit errors never break business flows.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditLog

log = structlog.get_logger(__name__)

# Canonical event_type constants — use these everywhere instead of raw strings.
class AuditEventType:
    USER_LOGIN_SUCCESS = "USER_LOGIN_SUCCESS"
    USER_LOGIN_FAILURE = "USER_LOGIN_FAILURE"
    USER_LOGOUT = "USER_LOGOUT"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DELETED = "USER_DELETED"
    USER_SUSPENDED = "USER_SUSPENDED"
    USER_INVITED = "USER_INVITED"
    USER_INVITE_ACCEPTED = "USER_INVITE_ACCEPTED"
    USER_INVITE_REVOKED = "USER_INVITE_REVOKED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    PASSWORD_RESET_COMPLETED = "PASSWORD_RESET_COMPLETED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    ROLE_REMOVED = "ROLE_REMOVED"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_DISABLED = "MFA_DISABLED"
    MFA_CHALLENGE_FAILED = "MFA_CHALLENGE_FAILED"
    SESSION_REVOKED = "SESSION_REVOKED"
    ALL_SESSIONS_REVOKED = "ALL_SESSIONS_REVOKED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ORG_SETTINGS_UPDATED = "ORG_SETTINGS_UPDATED"
    TOKEN_REFRESHED = "TOKEN_REFRESHED"


async def write_audit_log(
    db: AsyncSession,
    event_type: str,
    org_id: uuid.UUID,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_role: Optional[str] = None,
    actor_ip: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[uuid.UUID] = None,
    warehouse_id: Optional[uuid.UUID] = None,
    before_state: Optional[dict[str, Any]] = None,
    after_state: Optional[dict[str, Any]] = None,
    outcome: str = "SUCCESS",
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[AuditLog]:
    """
    Persist an AuditLog record to the database.

    Args:
        db:            Active AsyncSession (uses current transaction — does NOT commit).
        event_type:    One of the AuditEventType constants or a custom string.
        org_id:        Organization context for the event.
        actor_user_id: UUID of the user performing the action (None for system events).
        actor_role:    Stringified role name of the actor at time of action.
        actor_ip:      Source IP address of the actor.
        resource_type: Type of the affected resource (e.g., "user", "session").
        resource_id:   UUID of the affected resource.
        warehouse_id:  Scoped warehouse context (None if org-wide).
        before_state:  Snapshot of resource state before the change.
        after_state:   Snapshot of resource state after the change.
        outcome:       "SUCCESS" or "FAILURE".
        metadata:      Any additional key-value context.

    Returns:
        The created AuditLog ORM instance, or None on failure.
    """
    try:
        audit = AuditLog(
            org_id=org_id,
            warehouse_id=warehouse_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            actor_ip=actor_ip,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            before_state=before_state,
            after_state=after_state,
            outcome=outcome,
            metadata=metadata,
        )
        db.add(audit)
        # Flush to get the DB-assigned id without committing the outer transaction.
        await db.flush([audit])
        log.debug(
            "audit.written",
            event_type=event_type,
            org_id=str(org_id),
            actor_user_id=str(actor_user_id) if actor_user_id else None,
            outcome=outcome,
        )
        return audit
    except Exception as exc:
        # Audit failures must never crash the calling request.
        log.error(
            "audit.write_failed",
            event_type=event_type,
            org_id=str(org_id),
            error=str(exc),
            exc_info=True,
        )
        return None
