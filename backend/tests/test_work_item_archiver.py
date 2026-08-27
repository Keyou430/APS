from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditEvent
from app.services.work_item_archiver import (
    archive_overdue_day_work_items,
    calculate_archive_after,
)


def test_archive_after_uses_the_task_timezone_instead_of_server_local_time() -> None:
    due_at = datetime.fromisoformat("2026-08-16T10:00:00+08:00")

    assert calculate_archive_after(due_at, "Asia/Shanghai") == datetime(
        2026, 8, 16, 16, 0, tzinfo=UTC
    )


async def test_overdue_day_items_archive_once_and_completed_items_stay_daily(
    client, admin_headers: dict[str, str]
) -> None:
    async def create(title: str, *, scope: str = "day") -> dict:
        response = await client.post(
            "/api/work-items",
            headers=admin_headers,
            json={
                "title": title,
                "dueAt": "2026-08-16T10:00:00+08:00",
                "taskScope": scope,
                "archiveTimezone": "Asia/Shanghai",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    overdue = await create("Archive overdue day item")
    completed = await create("Keep completed day item")
    manual_week = await create("Existing weekly item", scope="week")
    assert overdue["taskScope"] == "day"
    assert overdue["archiveAfter"] == "2026-08-16T16:00:00Z"
    assert manual_week["taskScope"] == "week"
    assert manual_week["archiveAfter"] is None

    completed_response = await client.patch(
        f"/api/work-items/{completed['id']}/status",
        headers=admin_headers,
        json={"status": "completed"},
    )
    assert completed_response.status_code == 200

    first = await archive_overdue_day_work_items(
        SessionLocal,
        now=datetime.fromisoformat("2026-08-18T00:01:00+08:00"),
        batch_size=100,
    )
    second = await archive_overdue_day_work_items(
        SessionLocal,
        now=datetime.fromisoformat("2026-08-18T00:02:00+08:00"),
        batch_size=100,
    )

    assert first.archived_count == 1
    assert first.batch_id is not None
    assert second.archived_count == 0

    archived_response = await client.get(
        f"/api/work-items/{overdue['id']}", headers=admin_headers
    )
    assert archived_response.status_code == 200
    archived = archived_response.json()
    assert archived["taskScope"] == "week"
    assert archived["originalScope"] == "day"
    assert archived["originalDueAt"].startswith("2026-08-16T10:00:00")
    archived_at = datetime.fromisoformat(archived["archivedAt"].replace("Z", "+00:00"))
    assert archived_at == datetime(2026, 8, 17, 16, 1, tzinfo=UTC)
    assert archived["archiveReason"] == "overdue"
    assert archived["archiveBatchId"] == first.batch_id
    assert archived["weekKey"] == "2026-W34"
    assert archived["archiveAfter"] is None

    completed_after = await client.get(
        f"/api/work-items/{completed['id']}", headers=admin_headers
    )
    assert completed_after.json()["taskScope"] == "day"
    assert completed_after.json()["status"] == "completed"

    day_items = await client.get("/api/work-items?scope=day", headers=admin_headers)
    week_items = await client.get("/api/work-items?scope=week", headers=admin_headers)
    assert day_items.status_code == 200
    assert week_items.status_code == 200
    assert completed["id"] in {item["id"] for item in day_items.json()["items"]}
    assert {overdue["id"], manual_week["id"]}.issubset(
        {item["id"] for item in week_items.json()["items"]}
    )

    async with SessionLocal() as db:
        audit = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "work_item.scope.archive",
                AuditEvent.resource_id == str(overdue["id"]),
            )
        )
        assert audit is not None
        assert audit.actor_kind == "system"
        assert audit.actor_user_id is None
        assert audit.details["archive_batch_id"] == first.batch_id
        assert audit.details["from_scope"] == "day"
        assert audit.details["to_scope"] == "week"


async def test_work_item_scope_filter_rejects_unknown_values(
    client, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/api/work-items?scope=month", headers=admin_headers)
    assert response.status_code == 422
