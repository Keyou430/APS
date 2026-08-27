import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import HermesProfile, User


class HermesProfileManager:
    """Reconcile platform profile metadata without running a Hermes CLI.

    The private Hermes HTTP service multiplexes requests by the server-owned
    ``org:{organization_id}:user:{user_id}`` scope. This manager keeps the
    compatibility profile metadata aligned with that scope; it does not decide
    permissions or start a per-user process.
    """

    def __init__(self, profiles_root: Path | None = None) -> None:
        self.profiles_root = profiles_root or get_settings().hermes_profiles_root

    @staticmethod
    def scope_key(user_id: int, organization_id: int) -> str:
        return f"org:{organization_id}:user:{user_id}"

    def _profile_name(self, user: User, organization_id: int) -> str:
        username_slug = re.sub(r"[^a-z0-9._-]+", "-", user.username.lower()).strip("-.")
        return f"org-{organization_id}-user-{user.id}-{username_slug or 'profile'}"

    def _profile_home(self, user: User, organization_id: int) -> str:
        return str(
            (
                self.profiles_root.resolve()
                / f"org-{organization_id}"
                / self._profile_name(user, organization_id)
            ).resolve()
        )

    async def reconcile(
        self,
        db: AsyncSession,
        user: User,
        *,
        organization_id: int | None = None,
    ) -> HermesProfile:
        target_organization_id = (
            user.default_organization_id if organization_id is None else organization_id
        )
        if target_organization_id is None:
            raise ValueError("A server-owned organization is required for Hermes profile scope")

        profile = await db.scalar(
            select(HermesProfile).where(
                HermesProfile.organization_id == target_organization_id,
                HermesProfile.user_id == user.id,
            )
        )
        if profile is None:
            profile = HermesProfile(
                organization_id=target_organization_id,
                user_id=user.id,
                profile_name=self._profile_name(user, target_organization_id),
                hermes_home=self._profile_home(user, target_organization_id),
                port=-(target_organization_id * 1_000_000 + user.id),
                status="stopped",
            )
            db.add(profile)
            await db.flush()
            profile.port = 9000 + profile.id
            return profile

        expected_name = self._profile_name(user, target_organization_id)
        expected_home = self._profile_home(user, target_organization_id)
        if profile.profile_name != expected_name:
            profile.profile_name = expected_name
            profile.status = "stopped"
        if profile.hermes_home != expected_home:
            profile.hermes_home = expected_home
            profile.status = "stopped"

        profiles_root = self.profiles_root.resolve()
        try:
            Path(profile.hermes_home).resolve().relative_to(profiles_root)
        except ValueError:
            profile.hermes_home = expected_home
        return profile

    async def create(self, db: AsyncSession, user: User) -> HermesProfile:
        """Compatibility alias for callers that still use the create name."""

        return await self.reconcile(db, user)

    async def deactivate(self, profile: HermesProfile) -> None:
        profile.status = "stopped"


profile_manager = HermesProfileManager()
