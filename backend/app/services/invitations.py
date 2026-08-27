from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import secrets
from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models import (
    KnowledgeAccessGrant,
    KnowledgeEntry,
    OrganizationInvitation,
    OrganizationInvitationResource,
    OrganizationMembership,
    Role,
    User,
)
from app.schemas.invitations import InvitationAccept, InvitationCreate
from app.services.audit import record_audit


_INVITATION_ACCEPT_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_INVITATION_ACCEPT_WINDOW_SECONDS = 60.0
_INVITATION_ACCEPT_MAX_ATTEMPTS = 8


def reset_invitation_accept_limiter() -> None:
    _INVITATION_ACCEPT_ATTEMPTS.clear()


def invitation_accept_allowed(key: str) -> bool:
    now = monotonic()
    attempts = _INVITATION_ACCEPT_ATTEMPTS[key]
    while attempts and now - attempts[0] >= _INVITATION_ACCEPT_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _INVITATION_ACCEPT_MAX_ATTEMPTS:
        return False
    attempts.append(now)
    return True


def locked_user_by_email_statement(normalized_email: str):
    return select(User).where(User.normalized_email == normalized_email).with_for_update(of=User)


def locked_membership_statement(organization_id: int, user_id: int):
    return (
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
        .with_for_update(of=OrganizationMembership)
    )


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def issue_invitation_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, token_digest(token)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def invitation_status(invitation: OrganizationInvitation, now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.accepted_at is not None:
        return "accepted"
    if as_utc(invitation.token_expires_at) <= current:
        return "expired"
    return "pending"


async def validate_invitation_resources(
    db: AsyncSession, organization_id: int, resource_ids: list[int]
) -> list[KnowledgeEntry]:
    entries = list(
        (
            await db.scalars(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.organization_id == organization_id,
                    KnowledgeEntry.id.in_(resource_ids),
                    KnowledgeEntry.archived_at.is_(None),
                )
            )
        ).all()
    )
    if {entry.id for entry in entries} != set(resource_ids):
        raise HTTPException(status_code=404, detail="Invitation resource not found")
    return entries


async def create_invitation(
    db: AsyncSession,
    *,
    payload: InvitationCreate,
    organization_id: int,
    invited_by_user_id: int,
    actor_membership: OrganizationMembership,
) -> tuple[OrganizationInvitation, str]:
    now = datetime.now(UTC)
    if as_utc(payload.token_expires_at) <= now:
        raise HTTPException(status_code=422, detail="token_expires_at must be in the future")
    await validate_invitation_resources(db, organization_id, payload.resource_ids)
    token, digest = issue_invitation_token()
    invitation = OrganizationInvitation(
        organization_id=organization_id,
        normalized_email=str(payload.email).strip().casefold(),
        token_digest=digest,
        invited_by_user_id=invited_by_user_id,
        token_expires_at=payload.token_expires_at,
        membership_expires_at=payload.membership_expires_at,
    )
    db.add(invitation)
    await db.flush()
    db.add_all([
        OrganizationInvitationResource(
            invitation_id=invitation.id,
            knowledge_entry_id=entry_id,
            organization_id=organization_id,
        )
        for entry_id in payload.resource_ids
    ])
    await record_audit(
        db,
        actor_membership,
        action="invitation.create",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        details={"resource_count": len(payload.resource_ids)},
    )
    await db.commit()
    await db.refresh(invitation)
    return invitation, token


async def invitation_resource_ids(db: AsyncSession, invitation_id: int) -> list[int]:
    return list(
        (
            await db.scalars(
                select(OrganizationInvitationResource.knowledge_entry_id)
                .where(OrganizationInvitationResource.invitation_id == invitation_id)
                .order_by(OrganizationInvitationResource.knowledge_entry_id)
            )
        ).all()
    )


async def authenticated_user_from_bearer(
    db: AsyncSession, authorization: str | None
) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    from app.auth.security import decode_token

    try:
        claims = decode_token(authorization[7:], "access")
    except (ValueError, TypeError):
        return None
    user = await db.get(User, int(claims["sub"]))
    return user if user is not None and user.is_active else None


async def accept_invitation(
    db: AsyncSession,
    *,
    payload: InvitationAccept,
    authenticated_user: User | None,
) -> tuple[str, User, OrganizationMembership]:
    now = datetime.now(UTC)
    invitation = await db.scalar(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.token_digest == token_digest(payload.token))
        .with_for_update()
    )
    if invitation is None or invitation.revoked_at is not None or as_utc(invitation.token_expires_at) <= now:
        raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
    existing_user = await db.scalar(locked_user_by_email_statement(invitation.normalized_email))
    if existing_user is not None:
        if authenticated_user is None or authenticated_user.id != existing_user.id:
            raise HTTPException(status_code=403, detail="Authenticate the invited account before accepting")
        user = existing_user
    else:
        if authenticated_user is not None:
            raise HTTPException(status_code=403, detail="Invitation account does not match")
        if payload.username is None or payload.password is None:
            raise HTTPException(status_code=422, detail="username and password are required")
        guest_role = await db.scalar(select(Role).where(Role.name == "guest"))
        if guest_role is None:
            raise HTTPException(status_code=503, detail="Guest role is unavailable")
        user = User(
            username=payload.username,
            email=invitation.normalized_email,
            normalized_email=invitation.normalized_email,
            password_hash=hash_password(payload.password),
            role_id=guest_role.id,
            default_organization_id=invitation.organization_id,
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Invitation account already exists") from None

    membership = await db.scalar(locked_membership_statement(invitation.organization_id, user.id))
    if invitation.accepted_at is not None:
        if membership is None:
            raise HTTPException(status_code=409, detail="Invitation membership is unavailable")
        return "already_accepted", user, membership
    guest_role = await db.scalar(select(Role).where(Role.name == "guest"))
    if guest_role is None:
        raise HTTPException(status_code=503, detail="Guest role is unavailable")
    if membership is None:
        membership = OrganizationMembership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role_id=guest_role.id,
            member_type="guest",
            is_active=True,
            expires_at=invitation.membership_expires_at,
        )
        db.add(membership)
        await db.flush()
    elif membership.member_type == "guest":
        membership.is_active = True
        membership.role_id = guest_role.id
        membership.expires_at = invitation.membership_expires_at

    resource_ids = await invitation_resource_ids(db, invitation.id)
    await validate_invitation_resources(db, invitation.organization_id, resource_ids)
    for entry_id in resource_ids:
        active = await db.scalar(
            select(KnowledgeAccessGrant)
            .where(
                KnowledgeAccessGrant.knowledge_entry_id == entry_id,
                KnowledgeAccessGrant.grantee_membership_id == membership.id,
                KnowledgeAccessGrant.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if active is not None and active.expires_at is not None and as_utc(active.expires_at) <= now:
            active.revoked_at = now
            active = None
        if active is None:
            db.add(KnowledgeAccessGrant(
                organization_id=invitation.organization_id,
                knowledge_entry_id=entry_id,
                grantee_membership_id=membership.id,
                capability="read",
                expires_at=invitation.membership_expires_at,
                granted_by_user_id=invitation.invited_by_user_id,
            ))
    invitation.accepted_at = now
    await record_audit(
        db,
        membership,
        action="invitation.accept",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        details={"resource_count": len(resource_ids)},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Invitation was already accepted") from None
    return "accepted", user, membership
