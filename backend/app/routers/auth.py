from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import CurrentOrganizationContext, OrganizationContext
from app.auth.security import create_token, decode_token, verify_password
from app.config import get_settings
from app.database import get_db
from app.models import Organization, OrganizationMembership, RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    OrganizationMembershipListResponse,
    OrganizationMembershipResponse,
    RefreshRequest,
    SwitchOrganizationRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


def locked_refresh_token_statement(jti: str):
    return select(RefreshToken).where(RefreshToken.jti == jti).with_for_update()


async def revoke_current_refresh_token(db: AsyncSession, raw_token: str) -> bool:
    """Revoke exactly one persisted refresh token, without revealing token state."""
    try:
        claims = decode_token(raw_token, "refresh")
    except ValueError:
        return False

    stored = await db.scalar(locked_refresh_token_statement(claims["jti"]))
    if (
        stored is None
        or stored.revoked
        or stored.user_id != int(claims["sub"])
        or stored.organization_id != int(claims["organization_id"])
    ):
        return False

    stored.revoked = True
    await db.commit()
    return True


def active_membership_statement(user_id: int):
    now = datetime.now(UTC)
    return (
        select(OrganizationMembership)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .options(
            joinedload(OrganizationMembership.organization),
            joinedload(OrganizationMembership.role),
        )
        .where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
            Organization.is_active.is_(True),
            or_(
                OrganizationMembership.expires_at.is_(None),
                OrganizationMembership.expires_at > now,
            ),
        )
    )


async def preferred_login_membership(
    db: AsyncSession, user: User
) -> OrganizationMembership:
    membership = await db.scalar(
        active_membership_statement(user.id).order_by(
            case(
                (OrganizationMembership.organization_id == user.default_organization_id, 0),
                else_=1,
            ),
            OrganizationMembership.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="No active organization")
    return membership


async def issue_token_pair(
    db: AsyncSession, user_id: int, organization_id: int
) -> TokenResponse:
    settings = get_settings()
    access_delta = timedelta(minutes=settings.access_token_expire_minutes)
    refresh_delta = timedelta(days=settings.refresh_token_expire_days)
    access_token, _, _ = create_token(
        user_id,
        "access",
        access_delta,
        organization_id=organization_id,
    )
    refresh_token, refresh_jti, refresh_expires = create_token(
        user_id,
        "refresh",
        refresh_delta,
        organization_id=organization_id,
    )
    db.add(
        RefreshToken(
            jti=refresh_jti,
            user_id=user_id,
            organization_id=organization_id,
            expires_at=refresh_expires,
        )
    )
    await db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(access_delta.total_seconds()),
        organization_id=organization_id,
    )


def current_user_response(context: OrganizationContext) -> UserResponse:
    user = context.user
    permissions = sorted({
        link.permission.code
        for link in context.role.permission_links
        if link.permission is not None
    })
    return UserResponse.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": context.role.name,
            "member_type": context.member_type,
            "permissions": permissions,
            "membership_id": context.membership.id,
            "membership_expires_at": context.membership.expires_at,
            "organization_id": context.organization_id,
            "is_active": user.is_active,
            "created_at": user.created_at,
        }
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate with a local platform account",
    responses={401: {"description": "Invalid username or password"}},
)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == payload.username))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    membership = await preferred_login_membership(db, user)
    return await issue_token_pair(db, user.id, membership.organization_id)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="OAuth2 password-form token endpoint for Swagger UI",
)
async def oauth2_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == form.username))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    membership = await preferred_login_membership(db, user)
    return await issue_token_pair(db, user.id, membership.organization_id)


@router.post("/refresh", response_model=TokenResponse, summary="Exchange a refresh token")
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    stored = await db.scalar(locked_refresh_token_statement(claims["jti"]))
    organization_id = int(claims["organization_id"])
    if (
        stored is None
        or stored.revoked
        or stored.organization_id != organization_id
    ):
        raise HTTPException(status_code=401, detail="Refresh token is revoked or unknown")
    user = await db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive")
    membership = await db.scalar(
        active_membership_statement(user.id).where(
            OrganizationMembership.organization_id == organization_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=401, detail="Organization membership is inactive")
    stored.revoked = True
    await db.flush()
    return await issue_token_pair(db, user.id, organization_id)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the current refresh token",
    description=(
        "Idempotently revokes only the submitted refresh token. This endpoint does not revoke "
        "other sessions; clients must clear local access and refresh tokens after the request."
    ),
)
async def logout(payload: RefreshRequest, db: DbSession) -> Response:
    await revoke_current_refresh_token(db, payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse, summary="Get the current user")
async def me(context: CurrentOrganizationContext) -> UserResponse:
    return current_user_response(context)


@router.get(
    "/organizations",
    response_model=OrganizationMembershipListResponse,
    summary="List active organization memberships",
)
async def list_organizations(
    context: CurrentOrganizationContext,
    db: DbSession,
) -> OrganizationMembershipListResponse:
    memberships = list(
        (
            await db.scalars(
                active_membership_statement(context.user_id).order_by(
                    OrganizationMembership.id
                )
            )
        ).unique().all()
    )
    return OrganizationMembershipListResponse(
        current_organization_id=context.organization_id,
        items=[
            OrganizationMembershipResponse(
                organization_id=membership.organization_id,
                organization_name=membership.organization.name,
                organization_slug=membership.organization.slug,
                role=membership.role.name,
                member_type=membership.member_type,
                expires_at=membership.expires_at,
            )
            for membership in memberships
        ],
    )


@router.post(
    "/switch-organization",
    response_model=TokenResponse,
    summary="Issue a token pair for another active membership",
)
async def switch_organization(
    payload: SwitchOrganizationRequest,
    context: CurrentOrganizationContext,
    db: DbSession,
) -> TokenResponse:
    membership = await db.scalar(
        active_membership_statement(context.user_id).where(
            OrganizationMembership.organization_id == payload.organization_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")
    return await issue_token_pair(db, context.user_id, membership.organization_id)


@router.get("/oauth/{provider}", summary="Get OAuth stub status")
async def oauth_stub(provider: str) -> dict[str, str]:
    if provider not in {"feishu", "dingtalk"}:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")
    return {"provider": provider, "status": "stub", "message": "OAuth is planned for Phase 2"}
