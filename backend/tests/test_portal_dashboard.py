from sqlalchemy import delete, select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import NotificationOutbox, Organization, OrganizationMembership, Role, User


async def test_portal_and_dashboard_use_current_organization_context(
    client, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        admin_role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert admin is not None and admin_role is not None
        default_organization_id = admin.default_organization_id

        second = Organization(name="Portal Contract Organization", slug="portal-contract-org")
        db.add(second)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=second.id,
                user_id=admin.id,
                role_id=admin_role.id,
            )
        )
        await db.commit()
        second_id = second.id

    try:
        switched = await client.post(
            "/api/auth/switch-organization",
            headers=admin_headers,
            json={"organization_id": second_id},
        )
        assert switched.status_code == 200, switched.text
        headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}

        portal = await client.get("/api/enterprise/portal", headers=headers)
        assert portal.status_code == 200, portal.text
        assert portal.json()["company"]["id"] == str(second_id)
        assert portal.json()["company"]["name"] == "Portal Contract Organization"
        assert portal.json()["currentUser"]["id"] == str(admin.id)
        assert portal.json()["currentUser"]["role"] == "admin"
        assert portal.json()["company"]["id"] != str(default_organization_id)

        enterprise = await client.get("/api/enterprise", headers=headers)
        assert enterprise.status_code == 200, enterprise.text
        assert enterprise.json()["company"]["id"] == str(second_id)

        dashboard = await client.get("/api/dashboard", headers=headers)
        assert dashboard.status_code == 200, dashboard.text
        assert set(dashboard.json()) == {
            "todos",
            "pipelines",
            "calendarEvents",
            "notifications",
            "recentVisits",
            "quickActions",
            "metrics",
        }

        layout = await client.get("/api/dashboard/layout", headers=headers)
        assert layout.status_code == 200, layout.text
        assert layout.json()["userId"] == str(admin.id)
        assert layout.json()["id"] == f"layout-{second_id}-{admin.id}"
        assert layout.json()["layouts"]["lg"]
        assert layout.json()["widgets"]
        assert "business-overview" not in {
            widget["type"] for widget in layout.json()["widgets"]
        }
        assert "xs" not in layout.json()["layouts"]
        notification_layout = next(
            item for item in layout.json()["layouts"]["lg"] if item["i"] == "notification"
        )
        assert "minW" not in notification_layout
    finally:
        async with SessionLocal() as db:
            second = await db.get(Organization, second_id)
            if second is not None:
                await db.delete(second)
                await db.commit()


async def test_portal_and_dashboard_reject_guest_surface(client) -> None:
    async with SessionLocal() as db:
        organization = await db.scalar(select(Organization).order_by(Organization.id))
        guest_role = await db.scalar(select(Role).where(Role.name == "guest"))
        assert organization is not None and guest_role is not None
        guest = User(
            username="portal-contract-guest",
            email="portal-contract-guest@example.com",
            password_hash=hash_password("portal-contract-password"),
            role_id=guest_role.id,
            default_organization_id=organization.id,
        )
        db.add(guest)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=guest.id,
                role_id=guest_role.id,
                member_type="guest",
            )
        )
        await db.commit()

    try:
        login = await client.post(
            "/api/auth/login",
            json={"username": "portal-contract-guest", "password": "portal-contract-password"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        assert (await client.get("/api/enterprise/portal", headers=headers)).status_code == 403
        assert (await client.get("/api/dashboard", headers=headers)).status_code == 403
    finally:
        async with SessionLocal() as db:
            guest_id = await db.scalar(
                select(User.id).where(User.username == "portal-contract-guest")
            )
            if guest_id is not None:
                await db.execute(
                    delete(OrganizationMembership).where(
                        OrganizationMembership.user_id == guest_id
                    )
                )
                await db.execute(
                    delete(User).where(User.id == guest_id)
                )
                await db.commit()


async def test_dashboard_notifications_come_from_the_real_outbox(
    client, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        notification = NotificationOutbox(
            organization_id=admin.default_organization_id,
            event_key="dashboard-real-notification-probe",
            event_type="pipeline.decision.pending",
            payload={
                "decision_id": 987,
                "task_id": 654,
                "status": "pending",
                "recipient_user_ids": [admin.id],
            },
            status="pending",
        )
        db.add(notification)
        await db.commit()
        notification_id = notification.id

    try:
        response = await client.get("/api/dashboard", headers=admin_headers)
        assert response.status_code == 200, response.text
        matching = next(
            item
            for item in response.json()["notifications"]
            if item["id"] == str(notification_id)
        )
        assert matching["title"] == "定时任务结果待审批"
        assert matching["read"] is False
        assert matching["path"] == "/pipeline"
    finally:
        async with SessionLocal() as db:
            row = await db.get(NotificationOutbox, notification_id)
            if row is not None:
                await db.delete(row)
                await db.commit()


async def test_phase_c_demo_receives_hr_portal_and_dashboard_presentation(
    client, admin_headers: dict[str, str]
) -> None:
    demo_item_id: int | None = None
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        admin.username = "phase_c_demo"
        await db.commit()

    try:
        created_item = await client.post(
            "/api/work-items",
            headers=admin_headers,
            json={
                "title": "复核本月异常考勤",
                "description": "核对两项异常记录",
                "priority": "high",
                "origin": "manual",
            },
        )
        assert created_item.status_code == 201, created_item.text
        demo_item_id = created_item.json()["id"]
        created_reminder = await client.post(
            "/api/reminders",
            headers=admin_headers,
            json={
                "title": "新增招聘复试",
                "description": "生产主管岗位复试",
                "due_date": "2026-08-12T09:30:00+08:00",
                "type": "one-time",
                "notification_channel": "in-app",
            },
        )
        assert created_reminder.status_code == 201, created_reminder.text

        portal = await client.get("/api/enterprise/portal", headers=admin_headers)
        assert portal.status_code == 200, portal.text
        portal_body = portal.json()
        assert portal_body["company"]["name"] == "云枢精密五金"
        assert portal_body["currentUser"]["name"] == "周敏"
        assert portal_body["currentUser"]["department"] == "人力资源部"
        assert portal_body["currentUser"]["position"] == "人事经理"
        assert {item["name"] for item in portal_body["quickLinks"]} == {
            "新员工入职手册", "培训系统", "绩效考核", "新人 FAQ",
            "考勤与请假", "劳保用品申领", "员工档案", "安全培训",
        }
        assert {item["title"] for item in portal_body["announcements"]} >= {
            "月度安全培训安排", "考勤与请假制度提醒",
            "本周招聘面试安排", "劳保用品发放通知",
        }
        matching_todo = next(
            item for item in portal_body["todos"] if item["id"] == str(demo_item_id)
        )
        assert matching_todo["completed"] is False
        completed_todo = await client.put(
            f"/api/enterprise/portal/todos/{demo_item_id}",
            headers=admin_headers,
            json={"completed": True},
        )
        assert completed_todo.status_code == 200, completed_todo.text
        assert completed_todo.json()["completed"] is True

        dashboard = await client.get("/api/dashboard", headers=admin_headers)
        assert dashboard.status_code == 200, dashboard.text
        dashboard_body = dashboard.json()
        assert {item["label"] for item in dashboard_body["metrics"]} == {
            "在岗人数", "招聘缺口", "新员工上岗周期", "月度离职率",
            "考勤异常", "培训完成率", "安全培训覆盖率", "试用期转正情况",
        }
        assert {item["title"] for item in dashboard_body["pipelines"]} == {
            "每周人力统计", "月度考勤汇总", "新员工培训提醒",
            "安全培训巡检", "人员流失复盘", "岗位缺口分析",
        }
        assert {item["title"] for item in dashboard_body["calendarEvents"]} >= {
            "招聘面试", "入职培训", "安全培训", "考勤提交", "劳保用品发放",
            "新增招聘复试",
        }
    finally:
        if demo_item_id is not None:
            await client.delete(
                f"/api/work-items/{demo_item_id}", headers=admin_headers
            )
        async with SessionLocal() as db:
            demo = await db.scalar(select(User).where(User.username == "phase_c_demo"))
            if demo is not None:
                demo.username = "admin"
                await db.commit()
