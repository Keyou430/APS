from datetime import UTC, datetime, timedelta

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy import select

from app.routers import chat as chat_router
from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent, ChatSession
from app.services.hermes_client import HermesUpstreamError
from app.routers.auth import locked_refresh_token_statement


def test_refresh_statement_locks_the_persisted_jti() -> None:
    sql = str(locked_refresh_token_statement("jti").compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_health_auth_refresh_and_invalid_credentials(client: AsyncClient):
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    readiness = await client.get("/ready")
    assert readiness.status_code == 200
    assert readiness.json()["rag_worker"] == "disabled"

    bad_login = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong-password"}
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["error"]["code"] == "http_401"

    login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert me.json()["role"] == "admin"

    refreshed = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    replay = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 401

    oauth2 = await client.post(
        "/api/auth/token", data={"username": "admin", "password": "admin123"}
    )
    assert oauth2.status_code == 200
    assert oauth2.json()["token_type"] == "bearer"
    not_found = await client.get("/not-a-real-route")
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "http_404"


@pytest.mark.asyncio
async def test_chat_session_title_patch_persists_and_validates(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "原始标题"}
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    updated = await client.patch(
        f"/api/chat/sessions/{session_id}",
        headers=admin_headers,
        json={"title": "  首条消息标题  "},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "首条消息标题"

    blank = await client.patch(
        f"/api/chat/sessions/{session_id}",
        headers=admin_headers,
        json={"title": "   "},
    )
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_logout_revokes_only_the_submitted_refresh_token(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    admin_login = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}
    )
    admin_tokens = admin_login.json()

    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "logout-isolation-user",
            "password": "logout-isolation-password",
            "email": "logout-isolation@example.com",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    user_login = await client.post(
        "/api/auth/login",
        json={"username": "logout-isolation-user", "password": "logout-isolation-password"},
    )
    user_tokens = user_login.json()

    revoked = await client.post(
        "/api/auth/logout", json={"refresh_token": admin_tokens["refresh_token"]}
    )
    assert revoked.status_code == 204
    assert (
        await client.post("/api/auth/logout", json={"refresh_token": "not-a-token"})
    ).status_code == 204
    assert (
        await client.post(
            "/api/auth/refresh", json={"refresh_token": admin_tokens["refresh_token"]}
        )
    ).status_code == 401

    assert (
        await client.post(
            "/api/auth/refresh", json={"refresh_token": user_tokens["refresh_token"]}
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/auth/logout", json={"refresh_token": admin_tokens["refresh_token"]}
        )
    ).status_code == 204

    user_logout = await client.post(
        "/api/auth/logout", json={"refresh_token": user_tokens["refresh_token"]}
    )
    assert user_logout.status_code == 204
    assert (
        await client.post(
            "/api/auth/refresh", json={"refresh_token": user_tokens["refresh_token"]}
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_readiness_fails_when_enabled_worker_is_not_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    monkeypatch.setattr(
        main_module.settings,
        "rag_embedding_enabled",
        True,
    )
    monkeypatch.setattr(main_module.settings, "rag_query_embedding_url", None)
    monkeypatch.setattr(main_module.settings, "rag_query_embedding_token", None)

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["components"]["rag_worker"] == "misconfigured"


@pytest.mark.asyncio
async def test_admin_user_crud_rbac_and_profile(client: AsyncClient, admin_headers: dict[str, str]):
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "regular-user",
            "password": "regular-password",
            "email": "regular@example.com",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["role"] == "user"
    invalid_username = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "../escape",
            "password": "regular-password",
            "email": "escape@example.com",
            "role": "user",
        },
    )
    assert invalid_username.status_code == 422

    listed = await client.get(
        "/api/users?page=1&page_size=10&search=regular", headers=admin_headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    login = await client.post(
        "/api/auth/login", json={"username": "regular-user", "password": "regular-password"}
    )
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/users", headers=user_headers)).status_code == 403

    profile = await client.post(
        "/api/hermes/profiles", headers=admin_headers, json={"user_id": user["id"]}
    )
    assert profile.status_code == 201
    assert profile.json()["status"] == "stopped"
    assert "regular-user" in profile.json()["profile_name"]
    health = await client.get(f"/api/hermes/profiles/{user['id']}/health", headers=admin_headers)
    assert health.json()["healthy"] is True

    assigned = await client.put(
        f"/api/users/{user['id']}/roles", headers=admin_headers, json={"role": "manager"}
    )
    assert assigned.status_code == 200
    assert assigned.json()["role"] == "manager"


@pytest.mark.asyncio
async def test_chat_plan_b_stream_and_messages(client: AsyncClient, admin_headers: dict[str, str]):
    session = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Streaming test"}
    )
    assert session.status_code == 201
    session_id = session.json()["id"]
    streamed = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        headers=admin_headers,
        json={"content": "Hello Hermes"},
    )
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert "event: response.output_text.delta" in streamed.text
    assert "event: response.completed" in streamed.text

    messages = await client.get(f"/api/chat/sessions/{session_id}/messages", headers=admin_headers)
    assert [item["role"] for item in messages.json()["items"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_chat_router_passes_server_owned_hermes_context(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    class RecordingHermesClient:
        context = None

        async def create_response(self, content, session_id, *, context=None, **_kwargs):
            self.context = context
            return "recorded-run"

        async def stream_events(self, run_id, session_id, prompt, *, context=None):
            self.context = context
            yield 'event: response.completed\ndata: {"run_id":"recorded-run"}\n\n'

        async def get_session_messages(self, session_id, *, context=None):
            self.context = context
            return []

    recorder = RecordingHermesClient()
    monkeypatch.setattr(chat_router, "hermes_client", recorder)

    session = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Context test"}
    )
    assert session.status_code == 201
    session_id = session.json()["id"]
    streamed = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        headers=admin_headers,
        json={"content": "Context please"},
    )

    assert streamed.status_code == 200
    assert recorder.context is not None
    assert recorder.context.user_id == 1
    assert recorder.context.organization_id == "1"
    assert recorder.context.session_id == session.json()["hermes_session_id"]
    assert recorder.context.correlation_id


@pytest.mark.asyncio
async def test_chat_maps_hermes_upstream_failure_to_service_unavailable(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingHermesClient:
        async def create_response(self, *_args, **_kwargs):
            raise HermesUpstreamError(
                "Hermes upstream returned HTTP 502",
                status_code=502,
            )

    monkeypatch.setattr(chat_router, "hermes_client", FailingHermesClient())
    session = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Upstream failure"},
    )
    assert session.status_code == 201

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as safe_client:
        response = await safe_client.post(
            f"/api/chat/sessions/{session.json()['id']}/messages",
            headers=admin_headers,
            json={"content": "列出我的飞书群聊"},
        )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "http_503",
        "message": "Hermes AI service is temporarily unavailable",
    }


@pytest.mark.asyncio
async def test_chat_memory_auto_passes_embedding_provider_to_retrieval(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_embedding_provider = object()
    seen_provider = None

    async def retrieve_with_required_provider(
        _db,
        *,
        scope,
        query,
        limit,
        embedding_provider,
    ):
        nonlocal seen_provider
        del scope, query, limit
        seen_provider = embedding_provider
        return []

    class RecordingHermesClient:
        async def create_response(self, content, session_id, *, context=None, **_kwargs):
            return "run-with-memory-provider"

        async def stream_events(self, run_id, session_id, prompt, *, context=None):
            yield "event: response.completed\ndata: {}\n\n"

        async def get_session_messages(self, session_id, *, context=None):
            return []

    monkeypatch.setattr(chat_router, "hermes_client", RecordingHermesClient())
    monkeypatch.setattr(
        chat_router,
        "retrieve_authorized_memories",
        retrieve_with_required_provider,
    )
    monkeypatch.setattr(
        chat_router,
        "build_memory_embedding_provider",
        lambda: fake_embedding_provider,
        raising=False,
    )

    session = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Memory provider route", "surface": "knowledge"},
    )
    assert session.status_code == 201, session.text
    mode = await client.put(
        f"/api/chat/sessions/{session.json()['id']}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "auto", "expected_revision": session.json()["revision"]},
    )
    assert mode.status_code == 200, mode.text

    streamed = await client.post(
        f"/api/chat/sessions/{session.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "semantic memory query"},
    )

    assert streamed.status_code == 200, streamed.text
    assert seen_provider is fake_embedding_provider


@pytest.mark.asyncio
async def test_chat_stream_forces_runner_cleanup_after_completion(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    cleaned: list[str] = []

    class RecordingRunner:
        async def cleanup_task(self, task_id: str):
            cleaned.append(task_id)

    monkeypatch.setattr(chat_router, "sandbox_runner_client", RecordingRunner(), raising=False)

    session = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Cleanup test"}
    )
    async with SessionLocal() as db:
        persisted = await db.get(ChatSession, session.json()["id"])
        assert persisted is not None
        persisted.hermes_backend = "agent"
        await db.commit()
    streamed = await client.post(
        f"/api/chat/sessions/{session.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "Cleanup please"},
    )

    assert streamed.status_code == 200
    assert cleaned == [session.json()["hermes_session_id"]]


@pytest.mark.asyncio
async def test_chat_session_admission_serializes_concurrent_run_creation(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    create_entered = asyncio.Event()
    release_create = asyncio.Event()
    release_stream = asyncio.Event()
    create_calls = 0

    class BlockingHermesClient:
        async def create_response(self, content, session_id, *, context=None, **_kwargs):
            nonlocal create_calls
            create_calls += 1
            create_entered.set()
            await release_create.wait()
            return f"run-{create_calls}"

        async def stream_events(self, run_id, session_id, prompt, *, context=None):
            await release_stream.wait()
            yield f'event: response.completed\ndata: {{"run_id":"{run_id}"}}\n\n'

    monkeypatch.setattr(chat_router, "hermes_client", BlockingHermesClient())
    session = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Concurrent admission"}
    )
    path = f"/api/chat/sessions/{session.json()['id']}/messages"

    first = asyncio.create_task(
        client.post(path, headers=admin_headers, json={"content": "first"})
    )
    await create_entered.wait()
    second = asyncio.create_task(
        client.post(path, headers=admin_headers, json={"content": "second"})
    )
    await asyncio.sleep(0.05)

    observed_create_calls = create_calls
    release_create.set()
    if observed_create_calls == 1:
        second_response = await second
    else:
        second_response = None
    release_stream.set()
    first_response = await first
    if not second.done():
        await second

    assert observed_create_calls == 1
    assert second_response is not None and second_response.status_code == 409
    assert first_response.status_code == 200


@pytest.mark.asyncio
async def test_chat_run_admission_enforces_per_user_quota(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    settings = chat_router.get_settings()
    monkeypatch.setattr(settings, "sandbox_max_active_runs_per_user", 1)
    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Quota active"}
    )
    blocked = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Quota blocked"}
    )
    async with SessionLocal() as db:
        active = await db.get(ChatSession, created.json()["id"])
        active.active_hermes_run_id = "run-quota-active"
        active.active_run_status = "running"
        await db.commit()

    response = await client.post(
        f"/api/chat/sessions/{blocked.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "must be rejected before upstream"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["message"] == "User sandbox run quota reached"
    async with SessionLocal() as db:
        active = await db.get(ChatSession, created.json()["id"])
        active.active_hermes_run_id = None
        active.active_run_status = "completed"
        await db.commit()


@pytest.mark.asyncio
async def test_chat_run_admission_enforces_per_organization_quota(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    settings = chat_router.get_settings()
    monkeypatch.setattr(settings, "sandbox_max_active_runs_global", 99)
    monkeypatch.setattr(settings, "sandbox_max_active_runs_per_organization", 1)
    monkeypatch.setattr(settings, "sandbox_max_active_runs_per_user", 99)
    active_response = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Org quota active"}
    )
    blocked_response = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Org quota blocked"}
    )
    async with SessionLocal() as db:
        active = await db.get(ChatSession, active_response.json()["id"])
        active.active_hermes_run_id = "run-org-quota-active"
        active.active_run_status = "running"
        await db.commit()

    response = await client.post(
        f"/api/chat/sessions/{blocked_response.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "must be rejected before upstream"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["message"] == "Organization sandbox run quota reached"
    async with SessionLocal() as db:
        active = await db.get(ChatSession, active_response.json()["id"])
        active.active_hermes_run_id = None
        active.active_run_status = "completed"
        await db.commit()


@pytest.mark.asyncio
async def test_chat_run_admission_enforces_global_quota(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    settings = chat_router.get_settings()
    monkeypatch.setattr(settings, "sandbox_max_active_runs_global", 1)
    monkeypatch.setattr(settings, "sandbox_max_active_runs_per_organization", 99)
    monkeypatch.setattr(settings, "sandbox_max_active_runs_per_user", 99)
    active_response = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Global quota active"}
    )
    blocked_response = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Global quota blocked"}
    )
    async with SessionLocal() as db:
        active = await db.get(ChatSession, active_response.json()["id"])
        active.active_hermes_run_id = "run-global-quota-active"
        active.active_run_status = "running"
        await db.commit()

    response = await client.post(
        f"/api/chat/sessions/{blocked_response.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "must be rejected before upstream"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Global sandbox run quota reached"
    async with SessionLocal() as db:
        active = await db.get(ChatSession, active_response.json()["id"])
        active.active_hermes_run_id = None
        active.active_run_status = "completed"
        await db.commit()


@pytest.mark.asyncio
async def test_chat_lifecycle_mutations_lock_the_owned_session(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[bool] = []
    session = SimpleNamespace(
        id=1,
        organization_id=1,
        user_id=1,
        hermes_session_id="locked-session",
        active_hermes_run_id="run-locked",
        active_run_status="running",
    )
    user = SimpleNamespace(id=1, default_organization_id=1)
    context = SimpleNamespace(organization_id=1, membership=object())

    async def locked_owned_session(*_args, for_update=False, **_kwargs):
        calls.append(for_update)
        return session

    class FakeDb:
        executed = 0

        class EmptyScalars:
            def all(self):
                return []

        async def scalars(self, _statement):
            return self.EmptyScalars()

        async def execute(self, _statement):
            self.executed += 1
            return None

        async def delete(self, _session):
            return None

        async def commit(self):
            return None

    class FakeHermesClient:
        async def stop_run(self, run_id, *, context=None):
            return {"run_id": run_id, "status": "stopping"}

        async def approve_run(self, run_id, choice, *, context=None):
            return {"run_id": run_id, "choice": choice, "resolved": 1}

    class FakeRunner:
        async def cleanup_task(self, _task_id):
            return None

    async def record_no_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(chat_router, "owned_session", locked_owned_session)
    monkeypatch.setattr(chat_router, "hermes_client", FakeHermesClient())
    monkeypatch.setattr(chat_router, "sandbox_runner_client", FakeRunner())
    monkeypatch.setattr(chat_router, "record_audit", record_no_audit)
    db = FakeDb()

    await chat_router.delete_session(1, db, user, context)
    session.active_hermes_run_id = "run-locked"
    await chat_router.stop_run(1, "run-locked", db, user, context)
    session.active_hermes_run_id = "run-locked"
    await chat_router.approve_run(
        SimpleNamespace(choice="deny"), 1, "run-locked", db, user, context
    )

    assert calls == [True] * 6
    assert db.executed == 1

@pytest.mark.asyncio
async def test_chat_run_stop_is_owned_audited_and_forces_cleanup(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[str, str]] = []
    cleaned: list[str] = []

    class RecordingHermesClient:
        async def stop_run(self, run_id, *, context=None):
            calls.append((run_id, context.session_id))
            return {"run_id": run_id, "status": "stopping"}

    class RecordingRunner:
        async def cleanup_task(self, task_id: str):
            cleaned.append(task_id)

    monkeypatch.setattr(chat_router, "hermes_client", RecordingHermesClient())
    monkeypatch.setattr(chat_router, "sandbox_runner_client", RecordingRunner())

    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Stop lifecycle"}
    )
    session_id = created.json()["id"]
    hermes_session_id = created.json()["hermes_session_id"]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        session.hermes_backend = "agent"
        session.active_hermes_run_id = "run-owned-stop"
        session.active_run_status = "running"
        await db.commit()

    stopped = await client.post(
        f"/api/chat/sessions/{session_id}/runs/run-owned-stop/stop",
        headers=admin_headers,
    )

    assert stopped.status_code == 200, stopped.text
    assert stopped.json() == {"run_id": "run-owned-stop", "status": "stopping"}
    assert calls == [("run-owned-stop", hermes_session_id)]
    assert cleaned == [hermes_session_id]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session.active_hermes_run_id is None
        assert session.active_run_status == "stopped"
        audit = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "hermes.run.stop",
                AuditEvent.resource_id == "run-owned-stop",
            )
        )
        assert audit is not None
        assert audit.organization_id == session.organization_id


@pytest.mark.asyncio
async def test_chat_run_stop_treats_upstream_not_found_as_already_stopped(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    cleaned: list[str] = []

    class CompletedHermesClient:
        async def stop_run(self, run_id, *, context=None):
            raise HermesUpstreamError("run already completed", status_code=404)

    class RecordingRunner:
        async def cleanup_task(self, task_id: str):
            cleaned.append(task_id)

    monkeypatch.setattr(chat_router, "hermes_client", CompletedHermesClient())
    monkeypatch.setattr(chat_router, "sandbox_runner_client", RecordingRunner())
    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Stop race"}
    )
    session_id = created.json()["id"]
    hermes_session_id = created.json()["hermes_session_id"]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        session.hermes_backend = "agent"
        session.active_hermes_run_id = "run-already-finished"
        session.active_run_status = "running"
        await db.commit()

    stopped = await client.post(
        f"/api/chat/sessions/{session_id}/runs/run-already-finished/stop",
        headers=admin_headers,
    )

    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "already_stopped"
    assert cleaned == [hermes_session_id]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session.active_hermes_run_id is None
        assert session.active_run_status == "stopped"


@pytest.mark.asyncio
async def test_chat_run_approval_is_scoped_and_rejection_forces_cleanup(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    choices: list[str] = []
    cleaned: list[str] = []

    class RecordingHermesClient:
        async def approve_run(self, run_id, choice, *, context=None):
            choices.append(choice)
            return {"run_id": run_id, "choice": choice, "resolved": 1}

    class RecordingRunner:
        async def cleanup_task(self, task_id: str):
            cleaned.append(task_id)

    monkeypatch.setattr(chat_router, "hermes_client", RecordingHermesClient())
    monkeypatch.setattr(chat_router, "sandbox_runner_client", RecordingRunner())

    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Approval lifecycle"}
    )
    session_id = created.json()["id"]
    hermes_session_id = created.json()["hermes_session_id"]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        session.hermes_backend = "agent"
        session.active_hermes_run_id = "run-owned-approval"
        session.active_run_status = "awaiting_approval"
        await db.commit()

    persistent = await client.post(
        f"/api/chat/sessions/{session_id}/runs/run-owned-approval/approval",
        headers=admin_headers,
        json={"choice": "always"},
    )
    assert persistent.status_code == 422

    approved = await client.post(
        f"/api/chat/sessions/{session_id}/runs/run-owned-approval/approval",
        headers=admin_headers,
        json={"choice": "once"},
    )
    assert approved.status_code == 200, approved.text
    assert cleaned == []

    denied = await client.post(
        f"/api/chat/sessions/{session_id}/runs/run-owned-approval/approval",
        headers=admin_headers,
        json={"choice": "deny"},
    )
    assert denied.status_code == 200, denied.text
    assert choices == ["once", "deny"]
    assert cleaned == [hermes_session_id]

    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session.active_hermes_run_id is None
        assert session.active_run_status == "denied"
        audits = (
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "hermes.run.approval",
                    AuditEvent.resource_id == "run-owned-approval",
                )
            )
        ).all()
        assert [audit.details["choice"] for audit in audits] == ["once", "deny"]


@pytest.mark.asyncio
async def test_chat_run_timeout_marks_interrupted_and_forces_cleanup(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    cleaned: list[str] = []

    class RecordingRunner:
        async def cleanup_task(self, task_id: str):
            cleaned.append(task_id)

    async def timing_out_stream():
        yield "event: run.created\n\n"
        raise TimeoutError("run timed out")

    monkeypatch.setattr(chat_router, "sandbox_runner_client", RecordingRunner())
    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Timeout lifecycle"}
    )
    session_id = created.json()["id"]
    hermes_session_id = created.json()["hermes_session_id"]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        session.hermes_backend = "agent"
        session.active_hermes_run_id = "run-timeout"
        session.active_run_status = "running"
        await db.commit()

    with pytest.raises(TimeoutError, match="run timed out"):
        _ = [
            event
            async for event in chat_router.stream_session_run(
                timing_out_stream(),
                session_id=session_id,
                run_id="run-timeout",
                task_id=hermes_session_id,
            )
        ]

    assert cleaned == [hermes_session_id]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session.active_hermes_run_id is None
        assert session.active_run_status == "interrupted"


@pytest.mark.asyncio
async def test_deleting_active_chat_session_stops_run_before_cleanup(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    lifecycle: list[str] = []

    class RecordingHermesClient:
        async def stop_run(self, run_id, *, context=None):
            lifecycle.append(f"stop:{run_id}:{context.session_id}")
            return {"run_id": run_id, "status": "stopping"}

    class RecordingRunner:
        async def cleanup_task(self, task_id: str):
            lifecycle.append(f"cleanup:{task_id}")

    monkeypatch.setattr(chat_router, "hermes_client", RecordingHermesClient())
    monkeypatch.setattr(chat_router, "sandbox_runner_client", RecordingRunner())
    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Delete active run"}
    )
    session_id = created.json()["id"]
    hermes_session_id = created.json()["hermes_session_id"]
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        session.hermes_backend = "agent"
        session.active_hermes_run_id = "run-delete"
        session.active_run_status = "running"
        await db.commit()

    deleted = await client.delete(f"/api/chat/sessions/{session_id}", headers=admin_headers)

    assert deleted.status_code == 204, deleted.text
    assert lifecycle == [
        f"stop:run-delete:{hermes_session_id}",
        f"cleanup:{hermes_session_id}",
    ]
    async with SessionLocal() as db:
        audit = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "hermes.run.stop",
                AuditEvent.resource_id == "run-delete",
            )
        )
        assert audit is not None
        assert audit.details["reason"] == "session_delete"


@pytest.mark.asyncio
async def test_knowledge_and_skills_contracts(client: AsyncClient, admin_headers: dict[str, str]):
    link_payload = {
        "type": "link",
        "title": "Hermes Docs",
        "url": "https://hermes-agent.nousresearch.com/docs",
    }
    entry = await client.post("/api/knowledge", headers=admin_headers, json=link_payload)
    assert entry.status_code == 201, entry.text
    duplicate = await client.post("/api/knowledge", headers=admin_headers, json=link_payload)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == entry.json()["id"]
    filtered = await client.get("/api/knowledge?type=link", headers=admin_headers)
    assert filtered.json()["total"] >= 1
    assert sum(item["url"] == link_payload["url"] for item in filtered.json()["items"]) == 1
    search = await client.post(
        "/api/knowledge/search", headers=admin_headers, json={"query": "Hermes"}
    )
    assert search.status_code == 200
    assert search.json()["provider"] == "platform-pgvector"

    collection = await client.post(
        "/api/knowledge/collections",
        headers=admin_headers,
        json={"name": "测试上传文件夹"},
    )
    assert collection.status_code == 201, collection.text

    upload = await client.post(
        "/api/knowledge/upload",
        headers=admin_headers,
        data={"title": "Test file", "collection_id": str(collection.json()["id"])},
        files={"file": ("notes.txt", b"private test notes", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["type"] == "file"

    generated = await client.post(
        "/api/skills/generate",
        headers=admin_headers,
        json={"description": "Help write a monthly sales report"},
    )
    assert generated.status_code == 200
    assert generated.json()["generated_skill"].startswith("# ")
    assert (await client.get("/api/skills/hub", headers=admin_headers)).status_code == 200

    skill = await client.post(
        "/api/skills",
        headers=admin_headers,
        json={"name": "Report", "category": "general", "content": "# Report"},
    )
    assert skill.status_code == 201
    assert (await client.get("/api/skills?category=general", headers=admin_headers)).json()["items"]


@pytest.mark.asyncio
async def test_memory_and_reminder_crud(client: AsyncClient, admin_headers: dict[str, str]):
    memory = await client.post(
        "/api/memory",
        headers=admin_headers,
        json={"content": "User prefers dark mode", "type": "preference"},
    )
    assert memory.status_code == 201
    memory_id = memory.json()["memory_id"]
    updated = await client.put(
        f"/api/memory/{memory_id}",
        headers=admin_headers,
        json={"content": "User prefers light mode", "expected_revision": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["content"].endswith("light mode")
    assert (
        await client.delete(
            f"/api/memory/{memory_id}",
            headers=admin_headers,
            params={"expected_revision": 2},
        )
    ).status_code == 204

    due_date = datetime.now(UTC) + timedelta(days=2)
    reminder = await client.post(
        "/api/reminders",
        headers=admin_headers,
        json={
            "title": "Submit report",
            "due_date": due_date.isoformat(),
            "type": "recurring",
            "recurrence": "monthly",
            "notification_channel": "feishu",
        },
    )
    assert reminder.status_code == 201, reminder.text
    reminder_id = reminder.json()["id"]
    upcoming = await client.get("/api/reminders/upcoming", headers=admin_headers)
    assert any(item["id"] == reminder_id for item in upcoming.json()["items"])
    completed = await client.post(f"/api/reminders/{reminder_id}/complete", headers=admin_headers)
    assert completed.json()["status"] == "completed"
    active = await client.get("/api/reminders?status=active", headers=admin_headers)
    assert all(item["id"] != reminder_id for item in active.json()["items"])


@pytest.mark.asyncio
async def test_openapi_contract(client: AsyncClient):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    expected_paths = {
        "/api/auth/login",
        "/api/users",
        "/api/hermes/profiles",
        "/api/chat/sessions",
        "/api/chat/sessions/{session_id}",
        "/api/knowledge",
        "/api/skills",
        "/api/memory",
        "/api/reminders",
    }
    assert expected_paths.issubset(schema["paths"])
    assert "/redoc" not in schema["paths"]


@pytest.mark.asyncio
async def test_cross_user_resource_isolation(client: AsyncClient, admin_headers: dict[str, str]):
    async def create_and_login(username: str) -> dict[str, str]:
        response = await client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "username": username,
                "password": "tenant-password",
                "email": f"{username}@example.com",
                "role": "user",
            },
        )
        assert response.status_code == 201, response.text
        login = await client.post(
            "/api/auth/login", json={"username": username, "password": "tenant-password"}
        )
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    tenant_a = await create_and_login("tenant-a")
    tenant_b = await create_and_login("tenant-b")

    memory = await client.post("/api/memory", headers=tenant_a, json={"content": "Tenant A secret"})
    memory_id = memory.json()["memory_id"]
    assert (await client.get(f"/api/memory/{memory_id}", headers=tenant_b)).status_code == 404

    entry = await client.post(
        "/api/knowledge",
        headers=tenant_a,
        json={"type": "workflow_result", "title": "Tenant A", "content": "Private"},
    )
    entry_id = entry.json()["id"]
    assert (await client.get(f"/api/knowledge/{entry_id}", headers=tenant_b)).status_code == 404

    session = await client.post("/api/chat/sessions", headers=tenant_a, json={"title": "Tenant A"})
    session_id = session.json()["id"]
    assert (
        await client.get(f"/api/chat/sessions/{session_id}/messages", headers=tenant_b)
    ).status_code == 404
    async with SessionLocal() as db:
        owned = await db.get(ChatSession, session_id)
        owned.active_hermes_run_id = "run-tenant-a"
        owned.active_run_status = "running"
        await db.commit()
    assert (
        await client.post(
            f"/api/chat/sessions/{session_id}/runs/run-tenant-a/stop",
            headers=tenant_b,
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/chat/sessions/{session_id}/runs/run-tenant-a/approval",
            headers=tenant_b,
            json={"choice": "once"},
        )
    ).status_code == 404
