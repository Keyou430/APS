from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.config import get_settings
from app.database import get_db
from app.models import (
    KnowledgeAccessGrant,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)
from app.schemas.invitations import (
    GuestMembershipResponse,
    InvitationAccept,
    InvitationAcceptResponse,
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationListResponse,
    InvitationRegenerate,
    InvitationResponse,
)
from app.services.audit import record_audit
from app.services.guest_invitation_delivery import InvitationDeliveryError, deliver_invitation
from app.services.invitations import (
    accept_invitation,
    authenticated_user_from_bearer,
    create_invitation,
    invitation_resource_ids,
    invitation_status,
    issue_invitation_token,
    as_utc,
    invitation_accept_allowed,
)


def require_guest_feature() -> None:
    if not get_settings().feature_external_guests:
        raise HTTPException(status_code=404, detail="Not found")


GuestFeature = Annotated[None, Depends(require_guest_feature)]
router = APIRouter(
    prefix="/api/invitations",
    tags=["Invitations"],
    dependencies=[Depends(require_guest_feature)],
)
DbSession = Annotated[AsyncSession, Depends(get_db)]
InviteContext = Annotated[OrganizationContext, Depends(require_permission("members:invite"))]


async def response_for(db: AsyncSession, invitation: OrganizationInvitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.normalized_email,
        status=invitation_status(invitation),
        token_expires_at=invitation.token_expires_at,
        membership_expires_at=invitation.membership_expires_at,
        resource_ids=await invitation_resource_ids(db, invitation.id),
        created_at=invitation.created_at,
    )


async def deliver_or_return_test_token(
    *,
    db: AsyncSession,
    context: OrganizationContext,
    invitation: OrganizationInvitation,
    token: str,
) -> str | None:
    settings = get_settings()
    if settings.guest_invitation_delivery_adapter == "test":
        return token
    try:
        await deliver_invitation(
            settings=settings,
            recipient=invitation.normalized_email,
            token=token,
            token_expires_at=invitation.token_expires_at,
        )
    except InvitationDeliveryError:
        invitation.revoked_at = datetime.now(UTC)
        await record_audit(
            db,
            context.membership,
            action="invitation.delivery_failed",
            resource_type="organization_invitation",
            resource_id=str(invitation.id),
            details={"adapter": "smtp"},
        )
        await db.commit()
        raise HTTPException(status_code=503, detail="Invitation delivery failed") from None
    await record_audit(
        db,
        context.membership,
        action="invitation.deliver",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        details={"adapter": "smtp"},
    )
    await db.commit()
    return None


def require_approved_delivery_recipient(email: str) -> None:
    settings = get_settings()
    if (
        settings.guest_invitation_delivery_adapter == "smtp"
        and not settings.guest_invitation_recipient_allowed(email)
    ):
        raise HTTPException(status_code=403, detail="Invitation recipient is not approved")


@router.get("", response_model=InvitationListResponse)
async def list_invitations(
    db: DbSession, context: InviteContext, _feature: GuestFeature
) -> InvitationListResponse:
    rows = list((await db.scalars(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == context.organization_id)
        .order_by(OrganizationInvitation.id.desc())
    )).all())
    return InvitationListResponse(items=[await response_for(db, row) for row in rows])


@router.post(
    "",
    response_model=InvitationCreatedResponse,
    response_model_exclude_none=True,
    status_code=201,
)
async def create(
    payload: InvitationCreate, db: DbSession, context: InviteContext, _feature: GuestFeature
) -> InvitationCreatedResponse:
    require_approved_delivery_recipient(str(payload.email))
    invitation, token = await create_invitation(
        db,
        payload=payload,
        organization_id=context.organization_id,
        invited_by_user_id=context.user_id,
        actor_membership=context.membership,
    )
    base = await response_for(db, invitation)
    response_token = await deliver_or_return_test_token(
        db=db, context=context, invitation=invitation, token=token
    )
    return InvitationCreatedResponse(**base.model_dump(), token=response_token)


@router.post("/{invitation_id}/revoke", response_model=InvitationResponse)
async def revoke(
    invitation_id: int, db: DbSession, context: InviteContext, _feature: GuestFeature
) -> InvitationResponse:
    invitation = await db.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.id == invitation_id,
        OrganizationInvitation.organization_id == context.organization_id,
    ).with_for_update())
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Accepted invitation cannot revoke membership")
    invitation.revoked_at = datetime.now(UTC)
    await record_audit(db, context.membership, action="invitation.revoke", resource_type="organization_invitation", resource_id=str(invitation.id))
    await db.commit()
    return await response_for(db, invitation)


@router.post(
    "/{invitation_id}/regenerate",
    response_model=InvitationCreatedResponse,
    response_model_exclude_none=True,
)
async def regenerate(
    payload: InvitationRegenerate,
    invitation_id: int,
    db: DbSession,
    context: InviteContext,
    _feature: GuestFeature,
) -> InvitationCreatedResponse:
    invitation = await db.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.id == invitation_id,
        OrganizationInvitation.organization_id == context.organization_id,
    ).with_for_update())
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Accepted invitation cannot be regenerated")
    require_approved_delivery_recipient(invitation.normalized_email)
    if as_utc(payload.token_expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="token_expires_at must be in the future")
    token, invitation.token_digest = issue_invitation_token()
    invitation.token_expires_at = payload.token_expires_at
    invitation.revoked_at = None
    await record_audit(db, context.membership, action="invitation.regenerate", resource_type="organization_invitation", resource_id=str(invitation.id))
    await db.commit()
    base = await response_for(db, invitation)
    response_token = await deliver_or_return_test_token(
        db=db, context=context, invitation=invitation, token=token
    )
    return InvitationCreatedResponse(**base.model_dump(), token=response_token)


@router.post("/accept", response_model=InvitationAcceptResponse)
async def accept(
    payload: InvitationAccept,
    db: DbSession,
    _feature: GuestFeature,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> InvitationAcceptResponse:
    if not invitation_accept_allowed(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many invitation attempts")
    current_user = await authenticated_user_from_bearer(db, authorization)
    status, user, membership = await accept_invitation(
        db, payload=payload, authenticated_user=current_user
    )
    return InvitationAcceptResponse(
        status=status,
        user_id=user.id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
    )


@router.post("/guest-memberships/{membership_id}/revoke", response_model=GuestMembershipResponse)
async def revoke_guest_membership(
    membership_id: int, db: DbSession, context: InviteContext, _feature: GuestFeature
) -> GuestMembershipResponse:
    membership = await db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.id == membership_id,
        OrganizationMembership.organization_id == context.organization_id,
        OrganizationMembership.member_type == "guest",
    ).with_for_update())
    if membership is None:
        raise HTTPException(status_code=404, detail="Guest membership not found")
    membership.is_active = False
    now = datetime.now(UTC)
    await db.execute(
        update(KnowledgeAccessGrant)
        .where(
            KnowledgeAccessGrant.grantee_membership_id == membership.id,
            KnowledgeAccessGrant.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await record_audit(db, context.membership, action="guest_membership.revoke", resource_type="organization_membership", resource_id=str(membership.id))
    await db.commit()
    user = await db.get(User, membership.user_id)
    assert user is not None
    return GuestMembershipResponse(
        membership_id=membership.id,
        user_id=user.id,
        username=user.username,
        email=user.email,
        status="revoked",
        expires_at=membership.expires_at,
    )
