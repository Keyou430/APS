from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.config import get_settings
from app.models import Organization, OrganizationMembership, Permission, Role, RolePermission, User
from app.services.hermes_manager import profile_manager
from app.services.organization_structure import ensure_organization_structure

DEFAULT_ROLES = {
    "admin": ["*"],
    "manager": ["users:read", "content:*"],
    "user": ["profile:own", "content:own"],
    "guest": ["knowledge:read"],
}
DEFAULT_PERMISSIONS = {
    "chat:use": "Use platform chat sessions",
    "chat:route": "Route messages to an agent",
    "knowledge:read": "Read organization knowledge",
    "knowledge:write": "Write organization knowledge",
    "knowledge:share": "Share owned knowledge",
    "knowledge:govern": "Govern organization knowledge",
    "knowledge:ops": "Read knowledge operations",
    "experience:read": "Read organization experience methods",
    "experience:write": "Write organization experience methods",
    "audit:read": "Read organization audit events",
    "members:invite": "Invite organization guests",
    "agent:admin": "Manage Hermes profile metadata",
    "org:admin": "Manage organization users, roles, and structure",
    "org:read": "Read organization structure",
    "portal:read": "Read organization portal",
    "portal:manage": "Manage organization portal",
    "work_items:read": "Read organization work items",
    "work_items:write": "Write organization work items",
    "users:read": "Read organization users",
    "profile:read": "Read own profile metadata",
    "memory:read": "Read scoped memory",
    "memory:write": "Write scoped memory",
    "skills:read": "Read scoped skills",
    "skills:write": "Write scoped skills",
    "skills:review": "Review draft skills for publication",
    "skills:publish": "Publish reviewed skills",
    "projects:read": "Read scoped projects",
    "projects:write": "Create and update scoped projects",
    "projects:manage": "Manage project rosters and placements",
    "skills:share": "Share owned skills with organization members",
    "skills:govern": "Promote reviewed skills for organization discovery",
    "reminders:read": "Read scoped reminders",
    "reminders:write": "Write scoped reminders",
    "pipeline:read": "Read owned pipeline tasks and outputs",
    "pipeline:write": "Create and update owned pipeline tasks",
    "pipeline:run": "Run owned pipeline tasks",
    "pipeline:observe": "Observe pipeline operational metadata",
    "decisions:read": "Read owned dashboard decisions",
    "decisions:decide": "Decide owned dashboard decisions",
}
DEFAULT_ROLE_PERMISSIONS = {
    "admin": tuple(DEFAULT_PERMISSIONS),
    "manager": (
        "users:read",
        "chat:use",
        "knowledge:read",
        "knowledge:write",
        "knowledge:share",
        "knowledge:govern",
        "knowledge:ops",
        "experience:read",
        "experience:write",
        "audit:read",
        "agent:admin",
        "profile:read",
        "memory:read",
        "memory:write",
        "skills:read",
        "skills:write",
        "reminders:read",
        "reminders:write",
        "org:read",
        "portal:read",
        "work_items:read",
        "work_items:write",
        "projects:read",
        "projects:write",
        "projects:manage",
        "skills:share",
        "skills:govern",
        "pipeline:read",
        "pipeline:write",
        "pipeline:run",
        "pipeline:observe",
        "decisions:read",
        "decisions:decide",
    ),
    "user": (
        "chat:use",
        "knowledge:read",
        "knowledge:write",
        "knowledge:share",
        "experience:read",
        "experience:write",
        "profile:read",
        "memory:read",
        "memory:write",
        "skills:read",
        "skills:write",
        "reminders:read",
        "reminders:write",
        "org:read",
        "portal:read",
        "work_items:read",
        "work_items:write",
        "projects:read",
        "projects:write",
        "skills:share",
        "pipeline:read",
        "pipeline:write",
        "pipeline:run",
        "decisions:read",
        "decisions:decide",
    ),
    "guest": (
        "chat:use",
        "knowledge:read",
        "experience:read",
    ),
}


async def seed_database(db: AsyncSession) -> None:
    organization = await db.scalar(
        select(Organization).where(Organization.slug == "default")
    )
    if organization is None:
        organization = Organization(name="Default Organization", slug="default")
        db.add(organization)
        await db.flush()

    permission_rows: dict[str, Permission] = {}
    for code, description in DEFAULT_PERMISSIONS.items():
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=description)
            db.add(permission)
            await db.flush()
        else:
            permission.description = description
        permission_rows[code] = permission

    roles: dict[str, Role] = {}
    for name, permissions in DEFAULT_ROLES.items():
        role = await db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name, permissions=permissions)
            db.add(role)
            await db.flush()
        else:
            role.permissions = permissions
        roles[name] = role

        desired_permission_ids = {
            permission_rows[permission_code].id
            for permission_code in DEFAULT_ROLE_PERMISSIONS.get(name, ())
        }
        await db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_id.not_in(desired_permission_ids),
            )
        )

        for permission_code in DEFAULT_ROLE_PERMISSIONS.get(name, ()):
            existing_link = await db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission_rows[permission_code].id,
                )
            )
            if existing_link is None:
                db.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission_rows[permission_code].id,
                    )
                )

    settings = get_settings()
    admin = await db.scalar(select(User).where(User.username == settings.admin_username))
    if admin is None:
        admin = User(
            username=settings.admin_username,
            email=settings.admin_email,
            normalized_email=settings.admin_email.strip().casefold(),
            password_hash=hash_password(settings.admin_password),
            role=roles["admin"],
            default_organization=organization,
        )
        db.add(admin)
        await db.flush()
        await profile_manager.create(db, admin)

    normalized_admin_email = admin.email.strip().casefold()
    if admin.normalized_email != normalized_admin_email:
        admin.normalized_email = normalized_admin_email

    if admin.default_organization_id is None:
        admin.default_organization = organization
        await db.flush()
    membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == admin.default_organization_id,
            OrganizationMembership.user_id == admin.id,
        )
    )
    if membership is None:
        db.add(
            OrganizationMembership(
                organization_id=admin.default_organization_id,
                user_id=admin.id,
                role_id=admin.role_id,
            )
        )
        await db.flush()
    await ensure_organization_structure(db, admin.default_organization_id)
    await db.commit()
