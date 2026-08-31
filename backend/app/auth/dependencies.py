from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.security import decode_token
from app.config import get_settings
from app.database import get_db
from app.models import Organization, OrganizationMembership, Role, RolePermission, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


async def get_token_claims(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> dict | None:
    if token is None:
        if get_settings().single_user_mode:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(token, "access")
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


TokenClaims = Annotated[dict | None, Depends(get_token_claims)]


async def get_current_user(
    claims: TokenClaims,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if claims is None:
        user = await db.scalar(
            select(User).where(User.username == get_settings().admin_username)
        )
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Single-user account is not initialized",
            )
        return user

    user = await db.scalar(select(User).where(User.id == int(claims["sub"])))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class OrganizationContext:
    user: User
    membership: OrganizationMembership

    @property
    def organization_id(self) -> int:
        return self.membership.organization_id

    @property
    def user_id(self) -> int:
        return self.user.id

    @property
    def role(self) -> Role:
        return self.membership.role

    @property
    def member_type(self) -> str:
        return self.membership.member_type


async def get_current_organization_context(
    claims: TokenClaims,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationContext:
    organization_id = (
        user.default_organization_id
        if claims is None
        else int(claims["organization_id"])
    )
    if organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active organization")
    now = datetime.now(UTC)
    membership = await db.scalar(
        select(OrganizationMembership)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .options(
            joinedload(OrganizationMembership.organization),
            joinedload(OrganizationMembership.user),
            joinedload(OrganizationMembership.role)
            .selectinload(Role.permission_links)
            .joinedload(RolePermission.permission),
        )
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            Organization.is_active.is_(True),
            or_(
                OrganizationMembership.expires_at.is_(None),
                OrganizationMembership.expires_at > now,
            ),
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active organization")
    return OrganizationContext(user=user, membership=membership)


CurrentOrganizationContext = Annotated[
    OrganizationContext, Depends(get_current_organization_context)
]


async def get_current_membership(
    context: CurrentOrganizationContext,
) -> OrganizationMembership:
    return context.membership


CurrentMembership = Annotated[OrganizationMembership, Depends(get_current_membership)]


def has_permission(membership: OrganizationMembership, permission: str) -> bool:
    available = {
        link.permission.code
        for link in membership.role.permission_links
        if link.permission is not None
    }
    return "*" in available or permission in available


def organization_id_for(user: User) -> int:
    """Compatibility helper; request authorization must use CurrentOrganizationContext."""
    if user.default_organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active organization")
    return user.default_organization_id


def require_permission(*required_permissions: str) -> Callable:
    async def dependency(context: CurrentOrganizationContext) -> OrganizationContext:
        if not all(
            has_permission(context.membership, permission)
            for permission in required_permissions
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return context

    return dependency


def require_role(*allowed_roles: str) -> Callable:
    async def dependency(context: CurrentOrganizationContext) -> OrganizationContext:
        if context.role.name not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return context

    return dependency
