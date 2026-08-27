from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    CurrentOrganizationContext,
    OrganizationContext,
    has_permission,
    require_permission,
)
from app.database import get_db
from app.models import (
    AuditEvent,
    DashboardLayout as DashboardLayoutModel,
    OrganizationMembership,
    PortalAnnouncement,
    PortalAnnouncementRead,
    Reminder,
    Role,
    User,
    WorkItem,
    WorkItemEvent,
)
from app.schemas.portal import (
    ActivityResponse,
    AnnouncementCreate,
    AnnouncementListResponse,
    AnnouncementPinUpdate,
    AnnouncementResponse,
    AnnouncementUpdate,
    CompanyResponse,
    CurrentUserResponse,
    DashboardDataResponse,
    DashboardGridItem,
    DashboardLayoutResponse,
    DashboardLayouts,
    DashboardLayoutUpdate,
    DashboardWidgetResponse,
    DepartmentResponse,
    EnterpriseInfoResponse,
    EnterprisePortalResponse,
    PersonResponse,
    PositionResponse,
    PortalTodoResponse,
    PortalTodoUpdate,
    QuickLinkResponse,
)
from app.services.audit import record_audit


enterprise_router = APIRouter(prefix="/api/enterprise", tags=["Enterprise"])
dashboard_router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def require_internal_member(
    context: CurrentOrganizationContext,
) -> OrganizationContext:
    if context.member_type == "guest":
        raise HTTPException(status_code=403, detail="Guest access is knowledge-only")
    return context


InternalContext = Annotated[OrganizationContext, Depends(require_internal_member)]
PortalReadContext = Annotated[
    OrganizationContext, Depends(require_permission("portal:read"))
]
PortalManageContext = Annotated[
    OrganizationContext, Depends(require_permission("portal:manage"))
]
WorkItemWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("work_items:write"))
]

PORTAL_QUICK_LINKS = (
    QuickLinkResponse(
        id="knowledge-ai",
        name="知识问答",
        url="/knowledge/ai",
        icon="IconBook",
        order=1,
    ),
    QuickLinkResponse(
        id="workspace",
        name="个人工作台",
        url="/workspace",
        icon="IconDashboard",
        order=2,
    ),
    QuickLinkResponse(
        id="organization",
        name="组织架构",
        url="/organization/structure",
        icon="IconUserGroup",
        order=3,
    ),
    QuickLinkResponse(
        id="calendar",
        name="日历",
        url="/calendar",
        icon="IconCalendar",
        order=4,
    ),
)

HR_DEMO_QUICK_LINKS = (
    QuickLinkResponse(id="onboarding", name="新员工入职手册", url="/knowledge", icon="IconBook", order=1),
    QuickLinkResponse(id="training", name="培训系统", url="/workspace", icon="IconDashboard", order=2),
    QuickLinkResponse(id="performance", name="绩效考核", url="/workspace", icon="IconCheckCircle", order=3),
    QuickLinkResponse(id="newcomer-faq", name="新人 FAQ", url="/knowledge", icon="IconMessage", order=4),
    QuickLinkResponse(id="attendance", name="考勤与请假", url="/calendar", icon="IconCalendar", order=5),
    QuickLinkResponse(id="labor-protection", name="劳保用品申领", url="/workspace", icon="IconSend", order=6),
    QuickLinkResponse(id="employee-files", name="员工档案", url="/knowledge", icon="IconUserGroup", order=7),
    QuickLinkResponse(id="safety-training", name="安全培训", url="/calendar", icon="IconNotification", order=8),
)


def is_hr_demo(context: OrganizationContext) -> bool:
    return context.user.username == "phase_c_demo"


def hr_demo_announcements(now: datetime) -> list[AnnouncementResponse]:
    content = (
        ("demo-safety", "月度安全培训安排", "本周五组织全员月度安全培训，请各部门完成参训确认。", "安全行政部", True),
        ("demo-attendance", "考勤与请假制度提醒", "新版考勤与请假流程本月起执行，请按时完成异常考勤补录。", "人力资源部", False),
        ("demo-recruiting", "本周招聘面试安排", "机加工、质检及仓储岗位面试已排期，请相关部门准时参加。", "周敏", False),
        ("demo-protection", "劳保用品发放通知", "夏季劳保用品将按车间名单统一发放，请负责人核对领用数量。", "人力资源部", False),
    )
    return [
        AnnouncementResponse(
            id=item_id,
            title=title,
            summary=summary,
            content=summary,
            author=author,
            priority="important" if pinned else "normal",
            status="published",
            published_at=now - timedelta(hours=index * 8),
            is_pinned=pinned,
            is_read=True,
        )
        for index, (item_id, title, summary, author, pinned) in enumerate(content)
    ]


def hr_demo_activities(now: datetime) -> list[ActivityResponse]:
    return [
        ActivityResponse(id="demo-onboarding", type="event", title="3 名新员工完成入职", summary="机加工车间与质量部的新员工档案已归档。", occurred_at=now - timedelta(hours=2)),
        ActivityResponse(id="demo-training", type="notice", title="岗位技能培训进度更新", summary="本月培训完成率提升至 92%。", occurred_at=now - timedelta(days=1)),
        ActivityResponse(id="demo-recruitment", type="news", title="招聘岗位面试已排期", summary="6 个招聘缺口已完成候选人初筛。", occurred_at=now - timedelta(days=2)),
    ]


ACTIVITY_LABELS = {
    "organization.unit.create": ("组织架构已更新", "新增了组织单元"),
    "organization.unit.update": ("组织架构已更新", "调整了组织单元"),
    "organization.unit.delete": ("组织架构已更新", "移除了组织单元"),
    "organization.position.create": ("组织架构已更新", "新增了组织职位"),
    "organization.position.update": ("组织架构已更新", "调整了组织职位"),
    "organization.position.delete": ("组织架构已更新", "移除了组织职位"),
    "organization.placement.update": ("组织架构已更新", "调整了成员归属"),
    "organization.placement.batch": ("组织架构已更新", "批量调整了成员归属"),
    "portal.announcement.publish": ("企业公告已发布", "发布了一则企业公告"),
    "portal.announcement.withdraw": ("企业公告已撤下", "撤下了一则企业公告"),
}


def portal_role(role_name: str) -> str:
    return role_name if role_name in {"admin", "manager", "user"} else "user"


async def enterprise_info(
    db: AsyncSession, context: OrganizationContext
) -> EnterpriseInfoResponse:
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(User, OrganizationMembership, Role)
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .join(Role, Role.id == OrganizationMembership.role_id)
            .where(
                OrganizationMembership.organization_id == context.organization_id,
                OrganizationMembership.is_active.is_(True),
                OrganizationMembership.member_type == "internal",
                User.is_active.is_(True),
                or_(
                    OrganizationMembership.expires_at.is_(None),
                    OrganizationMembership.expires_at > now,
                ),
            )
            .order_by(User.id)
        )
    ).all()
    organization = context.membership.organization
    demo = is_hr_demo(context)
    company_name = "云枢精密五金" if demo else organization.name
    department_id = "human-resources" if demo else f"organization-{context.organization_id}"
    roles = sorted({role.name for _, _, role in rows} | {context.role.name})
    positions = [
        PositionResponse(
            id=f"role-{role_name}",
            title=role_name,
            department_id=department_id,
            level=role_name,
        )
        for role_name in roles
    ]
    people = [
        PersonResponse(
            id=str(user.id),
            name=user.username,
            email=user.email,
            department_id=department_id,
            department=organization.name,
            position_id=f"role-{role.name}",
            position=role.name,
            joined_at=user.created_at,
        )
        for user, _, role in rows
    ]
    current_user = CurrentUserResponse(
        id=str(context.user_id),
        name="周敏" if demo else context.user.username,
        email=context.user.email,
        department_id=department_id,
        department="人力资源部" if demo else organization.name,
        position_id="position-hr-manager" if demo else f"role-{context.role.name}",
        position="人事经理" if demo else context.role.name,
        avatar=None,
        joined_at=context.user.created_at,
        role=portal_role(context.role.name),
    )
    if demo:
        positions = [
            PositionResponse(
                id="position-hr-manager",
                title="人事经理",
                department_id=department_id,
                level="负责人",
            )
        ]
        people = [PersonResponse(**current_user.model_dump(exclude={"role"}))]
    return EnterpriseInfoResponse(
        company=CompanyResponse(
            id=str(organization.id),
            name=company_name,
            short_name="云枢精密五金" if demo else organization.name[:24],
            industry="精密五金制造" if demo else "Enterprise services",
            description=(
                "精密五金制造企业人力资源协同工作空间"
                if demo
                else f"{organization.name} enterprise workspace"
            ),
        ),
        current_user=current_user,
        announcements=[],
        departments=[
            DepartmentResponse(
                id=department_id,
                name="人力资源部" if demo else organization.name,
                member_count=len(people),
            )
        ],
        positions=positions,
        people=people,
    )


async def scoped_announcement(
    db: AsyncSession,
    organization_id: int,
    announcement_id: int,
) -> PortalAnnouncement:
    announcement = await db.scalar(
        select(PortalAnnouncement).where(
            PortalAnnouncement.id == announcement_id,
            PortalAnnouncement.organization_id == organization_id,
        )
    )
    if announcement is None:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return announcement


async def announcement_responses(
    db: AsyncSession,
    context: OrganizationContext,
    announcements: list[PortalAnnouncement],
) -> list[AnnouncementResponse]:
    if not announcements:
        return []
    author_ids = {announcement.author_user_id for announcement in announcements}
    authors = {
        user.id: user.username
        for user in (await db.scalars(select(User).where(User.id.in_(author_ids)))).all()
    }
    announcement_ids = {announcement.id for announcement in announcements}
    read_ids = set(
        await db.scalars(
            select(PortalAnnouncementRead.announcement_id).where(
                PortalAnnouncementRead.organization_id == context.organization_id,
                PortalAnnouncementRead.user_id == context.user_id,
                PortalAnnouncementRead.announcement_id.in_(announcement_ids),
            )
        )
    )
    return [
        AnnouncementResponse(
            id=str(announcement.id),
            title=announcement.title,
            summary=announcement.summary,
            content=announcement.content,
            author=authors.get(announcement.author_user_id, "企业管理员"),
            priority=announcement.priority,
            status=announcement.status,
            published_at=announcement.published_at,
            is_pinned=announcement.is_pinned,
            is_read=announcement.id in read_ids,
        )
        for announcement in announcements
    ]


def announcement_order():
    return (
        PortalAnnouncement.is_pinned.desc(),
        PortalAnnouncement.published_at.desc(),
        PortalAnnouncement.id.desc(),
    )


async def published_announcements(
    db: AsyncSession,
    context: OrganizationContext,
    *,
    limit: int = 20,
) -> list[AnnouncementResponse]:
    announcements = list(
        (
            await db.scalars(
                select(PortalAnnouncement)
                .where(
                    PortalAnnouncement.organization_id == context.organization_id,
                    PortalAnnouncement.status == "published",
                )
                .order_by(*announcement_order())
                .limit(limit)
            )
        ).all()
    )
    return await announcement_responses(db, context, announcements)


async def portal_todos(
    db: AsyncSession,
    context: OrganizationContext,
) -> list[PortalTodoResponse]:
    reminders = list(
        (
            await db.scalars(
                select(Reminder)
                .where(
                    Reminder.organization_id == context.organization_id,
                    Reminder.user_id == context.user_id,
                    Reminder.status.in_(("active", "completed")),
                )
                .order_by(Reminder.due_date, Reminder.id)
                .limit(20)
            )
        ).all()
    )
    return [
        PortalTodoResponse(
            id=str(reminder.id),
            title=reminder.title,
            due_at=reminder.due_date,
            priority="medium",
            completed=reminder.status == "completed",
            href="/calendar",
        )
        for reminder in reminders
    ]


async def portal_work_item_todos(
    db: AsyncSession,
    context: OrganizationContext,
) -> list[PortalTodoResponse]:
    items = list(
        (
            await db.scalars(
                select(WorkItem)
                .where(
                    WorkItem.organization_id == context.organization_id,
                    WorkItem.assignee_membership_id == context.membership.id,
                    WorkItem.status.in_(("pending", "in_progress", "completed")),
                )
                .order_by(WorkItem.status, WorkItem.due_at, WorkItem.id)
                .limit(20)
            )
        ).all()
    )
    return [
        PortalTodoResponse(
            id=str(item.id),
            title=item.title,
            due_at=item.due_at,
            priority=item.priority,
            completed=item.status == "completed",
            href="/workspace",
        )
        for item in items
    ]


async def portal_activities(
    db: AsyncSession,
    context: OrganizationContext,
) -> list[ActivityResponse]:
    events = list(
        (
            await db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.organization_id == context.organization_id,
                    AuditEvent.action.in_(tuple(ACTIVITY_LABELS)),
                    AuditEvent.outcome == "success",
                )
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .limit(20)
            )
        ).all()
    )
    return [
        ActivityResponse(
            id=f"audit-{event.id}",
            type="notice",
            title=ACTIVITY_LABELS[event.action][0],
            summary=ACTIVITY_LABELS[event.action][1],
            occurred_at=event.created_at,
        )
        for event in events
    ]


@enterprise_router.get("", response_model=EnterpriseInfoResponse)
async def get_enterprise(
    db: DbSession, context: PortalReadContext
) -> EnterpriseInfoResponse:
    info = await enterprise_info(db, context)
    announcements = (
        hr_demo_announcements(datetime.now(UTC))
        if is_hr_demo(context)
        else await published_announcements(db, context)
    )
    return info.model_copy(update={"announcements": announcements})


@enterprise_router.get("/portal", response_model=EnterprisePortalResponse)
async def get_portal(
    db: DbSession, context: PortalReadContext
) -> EnterprisePortalResponse:
    info = await enterprise_info(db, context)
    demo = is_hr_demo(context)
    now = datetime.now(UTC)
    return EnterprisePortalResponse(
        **info.model_dump(exclude={"announcements"}),
        announcements=(
            hr_demo_announcements(now)
            if demo
            else await published_announcements(db, context)
        ),
        activities=(
            hr_demo_activities(now) if demo else await portal_activities(db, context)
        ),
        todos=(
            await portal_work_item_todos(db, context)
            if demo
            else await portal_todos(db, context)
        ),
        quick_links=list(HR_DEMO_QUICK_LINKS if demo else PORTAL_QUICK_LINKS),
        collaborators=[person for person in info.people if person.id != str(context.user_id)][:8],
    )


@enterprise_router.get(
    "/announcements",
    response_model=AnnouncementListResponse,
)
async def list_announcements(
    db: DbSession,
    context: PortalReadContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    include_drafts: bool = False,
) -> AnnouncementListResponse:
    if include_drafts and not has_permission(context.membership, "portal:manage"):
        raise HTTPException(status_code=403, detail="Insufficient permission")
    filters = [PortalAnnouncement.organization_id == context.organization_id]
    if not include_drafts:
        filters.append(PortalAnnouncement.status == "published")
    total = await db.scalar(
        select(func.count(PortalAnnouncement.id)).where(*filters)
    )
    announcements = list(
        (
            await db.scalars(
                select(PortalAnnouncement)
                .where(*filters)
                .order_by(*announcement_order())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return AnnouncementListResponse(
        items=await announcement_responses(db, context, announcements),
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@enterprise_router.post(
    "/announcements",
    response_model=AnnouncementResponse,
    status_code=201,
)
async def create_announcement(
    payload: AnnouncementCreate,
    db: DbSession,
    context: PortalManageContext,
) -> AnnouncementResponse:
    announcement = PortalAnnouncement(
        organization_id=context.organization_id,
        author_user_id=context.user_id,
        status="draft",
        is_pinned=False,
        **payload.model_dump(),
    )
    db.add(announcement)
    await db.flush()
    await record_audit(
        db,
        context.membership,
        action="portal.announcement.create",
        resource_type="portal_announcement",
        resource_id=str(announcement.id),
        details={"priority": announcement.priority, "status": announcement.status},
    )
    await db.commit()
    return (await announcement_responses(db, context, [announcement]))[0]


@enterprise_router.patch(
    "/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
)
async def update_announcement(
    announcement_id: int,
    payload: AnnouncementUpdate,
    db: DbSession,
    context: PortalManageContext,
) -> AnnouncementResponse:
    announcement = await scoped_announcement(db, context.organization_id, announcement_id)
    if announcement.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft announcements can be edited")
    changes = payload.model_dump(exclude_unset=True)
    before = {
        field: getattr(announcement, field)
        for field in changes
        if field != "content"
    }
    for field, value in changes.items():
        setattr(announcement, field, value)
    await record_audit(
        db,
        context.membership,
        action="portal.announcement.update",
        resource_type="portal_announcement",
        resource_id=str(announcement.id),
        details={
            "before": before,
            "after": {field: value for field, value in changes.items() if field != "content"},
        },
    )
    await db.commit()
    return (await announcement_responses(db, context, [announcement]))[0]


@enterprise_router.post(
    "/announcements/{announcement_id}/publish",
    response_model=AnnouncementResponse,
)
async def publish_announcement(
    announcement_id: int,
    db: DbSession,
    context: PortalManageContext,
) -> AnnouncementResponse:
    announcement = await scoped_announcement(db, context.organization_id, announcement_id)
    if announcement.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft announcements can be published")
    announcement.status = "published"
    announcement.published_at = datetime.now(UTC)
    await record_audit(
        db,
        context.membership,
        action="portal.announcement.publish",
        resource_type="portal_announcement",
        resource_id=str(announcement.id),
        details={"status": "published"},
    )
    await db.commit()
    return (await announcement_responses(db, context, [announcement]))[0]


@enterprise_router.post(
    "/announcements/{announcement_id}/pin",
    response_model=AnnouncementResponse,
)
async def pin_announcement(
    announcement_id: int,
    payload: AnnouncementPinUpdate,
    db: DbSession,
    context: PortalManageContext,
) -> AnnouncementResponse:
    announcement = await scoped_announcement(db, context.organization_id, announcement_id)
    if announcement.status != "published":
        raise HTTPException(status_code=409, detail="Only published announcements can be pinned")
    announcement.is_pinned = payload.is_pinned
    await record_audit(
        db,
        context.membership,
        action="portal.announcement.pin",
        resource_type="portal_announcement",
        resource_id=str(announcement.id),
        details={"is_pinned": payload.is_pinned},
    )
    await db.commit()
    return (await announcement_responses(db, context, [announcement]))[0]


@enterprise_router.post(
    "/announcements/{announcement_id}/withdraw",
    response_model=AnnouncementResponse,
)
async def withdraw_announcement(
    announcement_id: int,
    db: DbSession,
    context: PortalManageContext,
) -> AnnouncementResponse:
    announcement = await scoped_announcement(db, context.organization_id, announcement_id)
    if announcement.status != "published":
        raise HTTPException(status_code=409, detail="Only published announcements can be withdrawn")
    announcement.status = "withdrawn"
    announcement.is_pinned = False
    await record_audit(
        db,
        context.membership,
        action="portal.announcement.withdraw",
        resource_type="portal_announcement",
        resource_id=str(announcement.id),
        details={"status": "withdrawn"},
    )
    await db.commit()
    return (await announcement_responses(db, context, [announcement]))[0]


@enterprise_router.post(
    "/announcements/{announcement_id}/read",
    status_code=204,
    response_model=None,
)
async def mark_announcement_read(
    announcement_id: int,
    db: DbSession,
    context: PortalReadContext,
) -> None:
    announcement = await scoped_announcement(db, context.organization_id, announcement_id)
    if announcement.status != "published":
        raise HTTPException(status_code=404, detail="Announcement not found")
    existing = await db.get(
        PortalAnnouncementRead,
        (announcement.id, context.user_id),
    )
    if existing is None:
        db.add(PortalAnnouncementRead(
            organization_id=context.organization_id,
            announcement_id=announcement.id,
            user_id=context.user_id,
        ))
        await db.commit()


@enterprise_router.put(
    "/portal/todos/{reminder_id}",
    response_model=PortalTodoResponse,
)
async def update_portal_todo(
    reminder_id: int,
    payload: PortalTodoUpdate,
    db: DbSession,
    context: WorkItemWriteContext,
) -> PortalTodoResponse:
    if is_hr_demo(context):
        item = await db.scalar(
            select(WorkItem).where(
                WorkItem.id == reminder_id,
                WorkItem.organization_id == context.organization_id,
                WorkItem.assignee_membership_id == context.membership.id,
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Portal todo not found")
        previous = item.status
        target = "completed" if payload.completed else "pending"
        if previous != target:
            item.status = target
            db.add(
                WorkItemEvent(
                    organization_id=context.organization_id,
                    work_item_id=item.id,
                    actor_membership_id=context.membership.id,
                    from_status=previous,
                    to_status=target,
                )
            )
        await record_audit(
            db,
            context.membership,
            action="portal.todo.update",
            resource_type="work_item",
            resource_id=str(item.id),
            details={"completed": payload.completed},
        )
        await db.commit()
        return PortalTodoResponse(
            id=str(item.id),
            title=item.title,
            due_at=item.due_at,
            priority=item.priority,
            completed=payload.completed,
            href="/workspace",
        )
    reminder = await db.scalar(
        select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.organization_id == context.organization_id,
            Reminder.user_id == context.user_id,
        )
    )
    if reminder is None:
        raise HTTPException(status_code=404, detail="Portal todo not found")
    reminder.status = "completed" if payload.completed else "active"
    await record_audit(
        db,
        context.membership,
        action="portal.todo.update",
        resource_type="reminder",
        resource_id=str(reminder.id),
        details={"completed": payload.completed},
    )
    await db.commit()
    return PortalTodoResponse(
        id=str(reminder.id),
        title=reminder.title,
        due_at=reminder.due_date,
        priority="medium",
        completed=payload.completed,
        href="/calendar",
    )


def dashboard_widgets() -> list[DashboardWidgetResponse]:
    return [
        DashboardWidgetResponse(id="todo", type="todo", title="我的任务", settings={"pageSize": 6}),
        DashboardWidgetResponse(id="pipeline", type="pipeline", title="智能任务", settings={"pageSize": 5}),
        DashboardWidgetResponse(id="calendar", type="calendar", title="日历摘要", settings={"days": 7}),
        DashboardWidgetResponse(id="notification", type="notification", title="企业通知", settings={"pageSize": 5}),
        DashboardWidgetResponse(id="recent-visits", type="recent-visits", title="最近访问", settings={"pageSize": 5}),
        DashboardWidgetResponse(id="quick-actions", type="quick-actions", title="常用功能", settings={"columns": 3}),
    ]


def grid_item(i: str, x: int, y: int, w: int, h: int, *, min_size: bool = False) -> DashboardGridItem:
    return DashboardGridItem(
        i=i,
        x=x,
        y=y,
        w=w,
        h=h,
        min_w=3 if min_size else None,
        min_h=3 if min_size else None,
    )


def default_layouts() -> DashboardLayouts:
    return DashboardLayouts(
        lg=[
            grid_item("todo", 0, 0, 4, 4, min_size=True),
            grid_item("pipeline", 4, 0, 4, 4, min_size=True),
            grid_item("calendar", 8, 0, 4, 4, min_size=True),
            grid_item("notification", 0, 4, 4, 3),
            grid_item("recent-visits", 4, 4, 4, 3),
            grid_item("quick-actions", 8, 4, 4, 3),
        ],
        md=[
            grid_item("todo", 0, 0, 4, 4),
            grid_item("pipeline", 4, 0, 4, 4),
            grid_item("calendar", 0, 4, 4, 4),
            grid_item("notification", 4, 4, 4, 3),
            grid_item("recent-visits", 0, 8, 4, 3),
            grid_item("quick-actions", 4, 8, 4, 3),
        ],
        sm=[
            grid_item("todo", 0, 0, 4, 4),
            grid_item("pipeline", 0, 4, 4, 4),
            grid_item("calendar", 0, 8, 4, 4),
            grid_item("notification", 0, 12, 4, 3),
            grid_item("recent-visits", 0, 15, 4, 3),
            grid_item("quick-actions", 0, 18, 4, 3),
        ],
    )


def layout_response(
    context: OrganizationContext, layout: DashboardLayoutModel
) -> DashboardLayoutResponse:
    return DashboardLayoutResponse(
        id=f"layout-{context.organization_id}-{context.user_id}",
        user_id=str(context.user_id),
        layouts=DashboardLayouts.model_validate(layout.layouts),
        updated_at=layout.updated_at,
        revision=layout.revision,
        widgets=dashboard_widgets(),
    )


async def ensure_dashboard_layout(
    db: AsyncSession, context: OrganizationContext
) -> DashboardLayoutModel:
    layout = await db.scalar(
        select(DashboardLayoutModel).where(
            DashboardLayoutModel.organization_id == context.organization_id,
            DashboardLayoutModel.user_id == context.user_id,
        )
    )
    if layout is None:
        layout = DashboardLayoutModel(
            organization_id=context.organization_id,
            user_id=context.user_id,
            layouts=default_layouts().model_dump(),
            revision=1,
        )
        db.add(layout)
        await db.commit()
        await db.refresh(layout)
    return layout


def hr_demo_dashboard(
    now: datetime,
    todos: list[dict[str, object]],
    reminders: list[Reminder],
) -> DashboardDataResponse:
    smart_tasks = (
        ("weekly-headcount", "每周人力统计", "汇总各部门在岗、缺口与人员异动", "weekly", 76),
        ("monthly-attendance", "月度考勤汇总", "核对异常考勤并生成月度汇总", "monthly", 58),
        ("onboarding-reminder", "新员工培训提醒", "提醒新员工与带教负责人完成课程", "weekly", 84),
        ("safety-inspection", "安全培训巡检", "检查各车间安全培训签到与覆盖情况", "weekly", 65),
        ("turnover-review", "人员流失复盘", "分析离职原因并整理稳定性建议", "monthly", 42),
        ("vacancy-analysis", "岗位缺口分析", "按部门梳理招聘优先级和到岗计划", "weekly", 71),
    )
    event_specs = (
        ("interview", "招聘面试", 0, 10, "meeting", "机加工与质检岗位候选人面试"),
        ("onboarding", "入职培训", 1, 9, "event", "新员工入职流程与厂区规范培训"),
        ("safety", "安全培训", 2, 14, "event", "月度安全生产与劳保佩戴培训"),
        ("attendance", "考勤提交", 3, 17, "deadline", "提交本月考勤异常复核结果"),
        ("supplies", "劳保用品发放", 4, 15, "reminder", "按车间清单发放夏季劳保用品"),
    )
    calendar_events = []
    for event_id, title, day_offset, hour, event_type, description in event_specs:
        start = (now + timedelta(days=day_offset)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        calendar_events.append(
            {
                "id": f"demo-{event_id}",
                "title": title,
                "start": start,
                "end": start + timedelta(hours=1),
                "type": event_type,
                "description": description,
                "color": "#1677ff",
                "allDay": False,
            }
        )
    for reminder in reminders:
        calendar_events.append(
            {
                "id": f"reminder-{reminder.id}",
                "title": reminder.title,
                "start": reminder.due_date,
                "end": reminder.due_date + timedelta(hours=1),
                "type": "reminder",
                "description": reminder.description or "",
                "color": "#d46b08",
                "allDay": False,
            }
        )
    return DashboardDataResponse(
        todos=todos,
        pipelines=[
            {
                "id": f"demo-{task_id}",
                "title": title,
                "summary": summary,
                "result": "",
                "source": "每周任务" if recurrence == "weekly" else "每月任务",
                "status": "processing" if progress < 80 else "pending_review",
                "progress": progress,
                "createdAt": now - timedelta(days=index + 1),
                "executedAt": None,
            }
            for index, (task_id, title, summary, recurrence, progress) in enumerate(smart_tasks)
        ],
        calendar_events=calendar_events,
        notifications=[
            {"id": "hr-notice-1", "title": "2 项异常考勤待复核", "createdAt": now, "read": False},
            {"id": "hr-notice-2", "title": "3 名新员工培训即将到期", "createdAt": now - timedelta(hours=3), "read": False},
            {"id": "hr-notice-3", "title": "本周面试安排已更新", "createdAt": now - timedelta(days=1), "read": True},
        ],
        recent_visits=[
            {"id": "employee-files", "label": "员工档案", "path": "/knowledge"},
            {"id": "training", "label": "培训系统", "path": "/workspace"},
            {"id": "attendance", "label": "考勤与请假", "path": "/calendar"},
        ],
        quick_actions=[
            {"id": item.id, "label": item.name, "path": item.url}
            for item in HR_DEMO_QUICK_LINKS
        ],
        metrics=[
            {"id": "headcount", "label": "在岗人数", "value": "286 人", "progress": 95, "trend": "较上月 +4"},
            {"id": "vacancies", "label": "招聘缺口", "value": "6 人", "progress": 68, "trend": "本周已面试 9 人"},
            {"id": "onboarding-cycle", "label": "新员工上岗周期", "value": "6.5 天", "progress": 82, "trend": "缩短 1.2 天"},
            {"id": "turnover", "label": "月度离职率", "value": "1.8%", "progress": 88, "trend": "低于目标 0.7%"},
            {"id": "attendance", "label": "考勤异常", "value": "5 项", "progress": 72, "trend": "2 项待复核"},
            {"id": "training", "label": "培训完成率", "value": "92%", "progress": 92, "trend": "较上月 +6%"},
            {"id": "safety", "label": "安全培训覆盖率", "value": "96%", "progress": 96, "trend": "11 人待补训"},
            {"id": "probation", "label": "试用期转正情况", "value": "8 / 10", "progress": 80, "trend": "2 人待评估"},
        ],
    )


@dashboard_router.get("", response_model=DashboardDataResponse)
async def get_dashboard(
    db: DbSession, context: InternalContext
) -> DashboardDataResponse:
    work_items = list(
        (
            await db.scalars(
                select(WorkItem)
                .where(
                    WorkItem.organization_id == context.organization_id,
                    WorkItem.assignee_membership_id == context.membership.id,
                )
                .order_by(WorkItem.status, WorkItem.due_at, WorkItem.id)
                .limit(20)
            )
        ).all()
    )
    reminders = list(
        (
            await db.scalars(
                select(Reminder)
                .where(
                    Reminder.organization_id == context.organization_id,
                    Reminder.user_id == context.user_id,
                    Reminder.status == "active",
                )
                .order_by(Reminder.due_date, Reminder.id)
                .limit(10)
            )
        ).all()
    )

    pipeline_reminders = [
        reminder
        for reminder in reminders
        if reminder.type == "recurring" or reminder.recurrence in {"weekly", "monthly"}
    ]

    todos = [
            {
                "id": str(item.id),
                "title": item.title,
                "dueAt": item.due_at,
                "priority": item.priority,
                "completed": item.status == "completed",
            }
            for item in work_items
        ]
    if is_hr_demo(context):
        return hr_demo_dashboard(datetime.now(UTC), todos, reminders)

    return DashboardDataResponse(
        todos=todos,
        pipelines=[
            {
                "id": f"pipeline-reminder-{reminder.id}",
                "title": reminder.title,
                "summary": reminder.description or "按固定周期执行的智能流水线任务",
                "result": "",
                "source": "每周流水线" if reminder.recurrence == "weekly" else "每月流水线",
                "status": "processing",
                "progress": 0,
                "createdAt": reminder.created_at,
                "executedAt": None,
            }
            for reminder in pipeline_reminders
        ],
        calendar_events=[
            {
                "id": f"reminder-{reminder.id}",
                "title": reminder.title,
                "start": reminder.due_date,
                "end": reminder.due_date,
                "type": "reminder",
                "description": reminder.description or "",
                "color": "#165dff",
                "allDay": False,
            }
            for reminder in reminders
        ],
        recent_visits=[
            {"id": "knowledge", "label": "企业知识库", "path": "/knowledge"},
            {"id": "portal", "label": "企业门户", "path": "/portal"},
        ],
        quick_actions=[
            {"id": "knowledge-ai", "label": "AI 问答", "path": "/knowledge?panel=ai"},
            {"id": "knowledge", "label": "企业知识库", "path": "/knowledge"},
            {"id": "calendar", "label": "查看日历", "path": "/calendar"},
        ],
        metrics=[
            {"id": "knowledge", "label": "知识空间", "value": "可用", "progress": 100, "trend": "当前组织"},
        ],
    )


@dashboard_router.get(
    "/layout",
    response_model=DashboardLayoutResponse,
    response_model_exclude_none=True,
)
async def get_dashboard_layout(
    db: DbSession, context: InternalContext
) -> DashboardLayoutResponse:
    return layout_response(context, await ensure_dashboard_layout(db, context))


@dashboard_router.put(
    "/layout",
    response_model=DashboardLayoutResponse,
    response_model_exclude_none=True,
)
async def save_dashboard_layout(
    payload: DashboardLayoutUpdate,
    db: DbSession,
    context: InternalContext,
) -> DashboardLayoutResponse:
    await ensure_dashboard_layout(db, context)
    layout = await db.scalar(
        select(DashboardLayoutModel)
        .where(
            DashboardLayoutModel.organization_id == context.organization_id,
            DashboardLayoutModel.user_id == context.user_id,
        )
        .with_for_update()
    )
    if layout is None:
        raise RuntimeError("Dashboard layout is missing")
    if layout.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Dashboard layout revision conflict")
    layout.layouts = payload.layouts.model_dump()
    layout.revision += 1
    await record_audit(
        db,
        context.membership,
        action="dashboard.layout.update",
        resource_type="dashboard_layout",
        resource_id=str(layout.id),
        details={"revision": layout.revision},
    )
    await db.commit()
    await db.refresh(layout)
    return layout_response(context, layout)


@dashboard_router.post(
    "/layout/reset",
    response_model=DashboardLayoutResponse,
    response_model_exclude_none=True,
)
async def reset_dashboard_layout(
    db: DbSession, context: InternalContext
) -> DashboardLayoutResponse:
    layout = await ensure_dashboard_layout(db, context)
    layout.layouts = default_layouts().model_dump()
    layout.revision += 1
    await record_audit(
        db,
        context.membership,
        action="dashboard.layout.reset",
        resource_type="dashboard_layout",
        resource_id=str(layout.id),
        details={"revision": layout.revision},
    )
    await db.commit()
    await db.refresh(layout)
    return layout_response(context, layout)
