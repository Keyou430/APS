from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.security import hash_password
from app.config import Settings
from app.database import SessionLocal
from app.models import (
    ChatSession,
    ChatTurn,
    KnowledgeEntry,
    OrganizationMembership,
    KnowledgeRetrievalEvent,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.schemas.chat import LinkPreviewRequest, MessageCreate
from app.schemas.knowledge import KnowledgeCitation
from app.schemas.knowledge import KnowledgeRetrieveResponse
from app.services.chat_context import build_chat_context, resolve_knowledge_scope
from app.services.fixed_knowledge import (
    ENTERPRISE_CONTEXT,
    ROLE_CONTEXT,
    fixed_context_by_id,
    fixed_contexts_for_username,
)
from app.services.hermes_client import HermesRequestContext, HermesUpstreamError
from app.routers import chat as chat_router


def test_chat_context_contains_only_authorized_citations() -> None:
    citation = KnowledgeCitation(
        entry_id=11,
        title="员工制度",
        content_sha256="a" * 64,
        source_locator="page:2",
        text="年假按制度执行。",
        score=0.91,
    )

    context = build_chat_context(question="制度是什么？", citations=[citation])

    assert context.user_input == "制度是什么？"
    assert "AUTHORIZED_KNOWLEDGE" in context.instructions
    assert "年假按制度执行。" in context.instructions
    assert "[K1]" in context.instructions
    assert "oss://" not in context.instructions
    assert "Do not upload files" in context.instructions
    assert "dingtalk_search_documents" in context.instructions
    assert "Do not execute any other tools" in context.instructions
    assert "never invent" in context.instructions
    assert "飞书和钉钉是两个独立渠道" in context.instructions
    assert "live search is unavailable" in context.instructions


def test_client_message_id_accepts_only_stable_safe_identifiers() -> None:
    payload = MessageCreate(content="创建定时任务", client_message_id="m_1724371200000")

    assert payload.client_message_id == "m_1724371200000"
    with pytest.raises(ValueError):
        MessageCreate(content="创建定时任务", client_message_id="invalid id")


def test_fixed_enterprise_and_role_context_is_independent_from_ordinary_scope() -> None:
    context = build_chat_context(
        question="你好",
        citations=[],
        fixed_contexts=[
            (ENTERPRISE_CONTEXT.title, ENTERPRISE_CONTEXT.content),
            (ROLE_CONTEXT.title, ROLE_CONTEXT.content),
        ],
    )

    assert "No ordinary knowledge excerpts were selected." in context.instructions
    assert "FIXED_ENTERPRISE_AND_ROLE_CONTEXT" in context.instructions
    assert "云枢精密五金制造行业知识库" in context.instructions
    assert "人事经理岗位资料" in context.instructions
    assert "星纪云1.0的 AI 办事助手" in context.instructions
    assert "当前服务于云枢精密五金" in context.instructions
    assert "云枢企业知识助手" not in context.instructions


def test_transient_attachment_content_is_included_without_selecting_knowledge() -> None:
    context = build_chat_context(
        question="候选人有哪些经验？",
        citations=[],
        attachments=[("候选人简历.pdf", "候选人周敏具备五年人力资源管理经验。")],
    )

    assert "No ordinary knowledge excerpts were selected." in context.instructions
    assert "TRANSIENT_USER_CONTEXT" in context.instructions
    assert "候选人简历.pdf" in context.instructions
    assert "五年人力资源管理经验" in context.instructions


def test_fixed_contexts_are_code_owned_and_limited_to_demo_user() -> None:
    contexts = fixed_contexts_for_username("phase_c_demo")

    assert [item.id for item in contexts] == ["enterprise-profile", "role-profile"]
    assert fixed_contexts_for_username("admin") == ()
    assert fixed_context_by_id("phase_c_demo", "enterprise-profile") is ENTERPRISE_CONTEXT
    assert fixed_context_by_id("phase_c_demo", "missing") is None
    with pytest.raises(Exception):
        ENTERPRISE_CONTEXT.title = "可修改资料"


def test_chat_context_rejects_storage_locator() -> None:
    citation = KnowledgeCitation(
        entry_id=11,
        title="员工制度",
        content_sha256="a" * 64,
        source_locator="oss://private-bucket/document.pdf",
        text="年假按制度执行。",
        score=0.91,
    )

    with pytest.raises(ValueError, match="unsafe citation source locator"):
        build_chat_context(question="制度是什么？", citations=[citation])


def test_legacy_source_ids_are_nullable_and_omission_is_distinct_from_empty() -> None:
    omitted = MessageCreate.model_validate({"content": "制度是什么？"})
    explicit_null = MessageCreate.model_validate(
        {"content": "制度是什么？", "source_ids": None}
    )
    explicit_empty = MessageCreate.model_validate(
        {"content": "制度是什么？", "source_ids": []}
    )

    assert omitted.source_ids is None
    assert explicit_null.source_ids is None
    assert explicit_empty.source_ids == []


@pytest.mark.parametrize(
    ("session_scope", "selected_ids", "legacy_source_ids", "expected"),
    [
        ("none", [], None, ("none", [], False)),
        ("all_visible", [], None, ("all_visible", [], False)),
        ("selected", [7, 9], None, ("selected", [7, 9], False)),
        ("none", [], [], ("none", [], True)),
        ("all_visible", [], [11], ("selected", [11], True)),
    ],
)
def test_legacy_source_ids_have_one_way_session_scope_mapping(
    session_scope, selected_ids, legacy_source_ids, expected
) -> None:
    resolved = resolve_knowledge_scope(
        session_scope=session_scope,
        selected_source_ids=selected_ids,
        legacy_source_ids=legacy_source_ids,
    )

    assert (resolved.mode, resolved.source_ids, resolved.legacy_used) == expected


@pytest.mark.asyncio
async def test_knowledge_chat_uses_server_backend_and_authorized_context(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class RecordingHermes:
        async def create_response(self, content, session_id, **kwargs):
            captured.update(content=content, session_id=session_id, **kwargs)
            return "run-knowledge"

        async def stream_events(self, run_id, session_id, prompt=None, **kwargs):
            del prompt, kwargs
            yield f'event: run.created\ndata: {{"run_id":"{run_id}","session_id":"{session_id}"}}\n\n'
            yield f'event: response.completed\ndata: {{"run_id":"{run_id}"}}\n\n'

    class RecordingRetriever:
        async def retrieve(self, **_kwargs):
            return KnowledgeRetrieveResponse(
                citations=[
                    KnowledgeCitation(
                        entry_id=11,
                        title="授权制度",
                        content_sha256="a" * 64,
                        source_locator="page:2",
                        text="授权内容",
                        score=0.9,
                    )
                ],
                mode="hybrid",
            )

    monkeypatch.setattr(chat_router, "hermes_client", RecordingHermes())
    monkeypatch.setattr(
        chat_router,
        "build_platform_knowledge_retriever",
        lambda _db: RecordingRetriever(),
    )
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Knowledge", "backend": "agent"},
    )
    assert created.status_code == 201, created.text

    streamed = await client.post(
        f"/api/chat/sessions/{created.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "制度是什么？", "backend": "agent", "source_ids": [11]},
    )

    assert streamed.status_code == 200, streamed.text
    assert captured["content"] == "制度是什么？"
    assert "授权内容" in str(captured["instructions"])
    assert "Do not upload files" in str(captured["instructions"])
    assert "agent" not in created.json()
    assert "event: knowledge.context" in streamed.text
    assert "授权内容" not in streamed.text
    async with SessionLocal() as db:
        event = await db.scalar(
            select(KnowledgeRetrievalEvent).where(
                KnowledgeRetrievalEvent.request_kind == "chat"
            ).order_by(KnowledgeRetrievalEvent.id.desc())
        )
    assert event is not None
    assert event.chat_session_id == created.json()["id"]
    assert event.query_hmac is not None
    assert event.query_sha256 is None


@pytest.mark.asyncio
async def test_session_surface_create_and_list_are_isolated(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    agent = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Agent surface", "surface": "agent"},
    )
    knowledge = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Knowledge surface", "surface": "knowledge"},
    )

    assert agent.status_code == 201, agent.text
    assert knowledge.status_code == 201, knowledge.text
    assert agent.json()["surface"] == "agent"
    assert knowledge.json()["surface"] == "knowledge"

    agent_list = await client.get(
        "/api/chat/sessions",
        headers=admin_headers,
        params={"surface": "agent"},
    )
    knowledge_list = await client.get(
        "/api/chat/sessions",
        headers=admin_headers,
        params={"surface": "knowledge"},
    )
    assert {item["id"] for item in agent_list.json()["items"]} == {agent.json()["id"]}
    assert knowledge.json()["id"] in {
        item["id"] for item in knowledge_list.json()["items"]
    }
    assert agent.json()["id"] not in {
        item["id"] for item in knowledge_list.json()["items"]
    }


@pytest.mark.asyncio
async def test_guest_cannot_create_agent_surface(
    client: AsyncClient,
) -> None:
    async with SessionLocal() as db:
        organization = await db.scalar(
            select(OrganizationMembership.organization_id).join(
                User, User.id == OrganizationMembership.user_id
            ).where(User.username == "admin")
        )
        guest_role = await db.scalar(select(Role).where(Role.name == "guest"))
        if guest_role is None:
            guest_role = Role(name="guest", permissions=[])
            db.add(guest_role)
            await db.flush()
            for code in ("chat:use", "knowledge:read"):
                permission = await db.scalar(select(Permission).where(Permission.code == code))
                assert permission is not None
                db.add(RolePermission(role_id=guest_role.id, permission_id=permission.id))

        guest = User(
            username="phase-b-guest",
            email="phase-b-guest@example.com",
            password_hash=hash_password("phase-b-guest-password"),
            role_id=guest_role.id,
            default_organization_id=organization,
        )
        if hasattr(User, "normalized_email"):
            guest.normalized_email = "phase-b-guest@example.com"
        db.add(guest)
        await db.flush()
        membership = OrganizationMembership(
            organization_id=organization,
            user_id=guest.id,
            role_id=guest_role.id,
        )
        if hasattr(OrganizationMembership, "member_type"):
            membership.member_type = "guest"
        db.add(membership)
        await db.commit()

    login = await client.post(
        "/api/auth/login",
        json={"username": "phase-b-guest", "password": "phase-b-guest-password"},
    )
    assert login.status_code == 200, login.text
    response = await client.post(
        "/api/chat/sessions",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"title": "Forbidden agent", "surface": "agent"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_regular_chat_user_can_create_agent_surface(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "chat-surface-user",
            "password": "chat-surface-password",
            "email": "chat-surface-user@example.com",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/auth/login",
        json={"username": "chat-surface-user", "password": "chat-surface-password"},
    )
    assert login.status_code == 200, login.text
    response = await client.post(
        "/api/chat/sessions",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"title": "普通用户 Agent 会话", "surface": "agent"},
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_knowledge_scope_supports_all_selected_and_none_and_locks_active_run(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    entry = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Scoped source", "content": "scope"},
    )
    assert entry.status_code == 201, entry.text
    session = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Scoped knowledge", "surface": "knowledge"},
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    for payload in (
        {"mode": "all_visible", "source_ids": []},
        {"mode": "selected", "source_ids": [entry.json()["id"]]},
        {"mode": "none", "source_ids": []},
    ):
        changed = await client.put(
            f"/api/chat/sessions/{session_id}/knowledge-scope",
            headers=admin_headers,
            json=payload,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["knowledge_scope"] == payload["mode"]
        listed = await client.get(
            "/api/chat/sessions?surface=knowledge",
            headers=admin_headers,
        )
        listed_session = next(item for item in listed.json()["items"] if item["id"] == session_id)
        assert listed_session["source_ids"] == payload["source_ids"]

    async with SessionLocal() as db:
        from app.models import ChatSession

        stored = await db.get(ChatSession, session_id)
        assert stored is not None
        stored.active_hermes_run_id = "scope-active-run"
        stored.active_run_status = "running"
        await db.commit()

    blocked = await client.put(
        f"/api/chat/sessions/{session_id}/knowledge-scope",
        headers=admin_headers,
        json={"mode": "all_visible", "source_ids": []},
    )

    async with SessionLocal() as db:
        from app.models import ChatSession

        stored = await db.get(ChatSession, session_id)
        assert stored is not None
        stored.active_hermes_run_id = None
        stored.active_run_status = "stopped"
        await db.commit()

    assert blocked.status_code == 409


def test_session_title_is_summarized_from_the_first_question() -> None:
    assert chat_router.summarize_session_title("如何处理知识库权限？后续补充") == "如何处理知识库权限"
    assert chat_router.summarize_session_title("这是一个明显超过二十四个字符的会话问题标题，需要被安全截断") == "这是一个明显超过二十四个字符的会话问题标题，需要…"


@pytest.mark.asyncio
async def test_chat_history_hides_tool_payloads_and_empty_tool_call_messages(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Tool history", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text

    class ToolHistoryHermes:
        async def get_session_messages(self, _session_id, **_kwargs):
            return [
                {"id": "user-1", "role": "user", "content": "读取钉钉文档", "created_at": "2026-08-07T01:00:00Z"},
                {"id": "assistant-call", "role": "assistant", "content": "", "created_at": "2026-08-07T01:00:01Z"},
                {"id": "tool-1", "role": "tool", "content": '{"required_scopes":["Storage.Dentry.Search"]}', "created_at": "2026-08-07T01:00:02Z"},
                {"id": "assistant-1", "role": "assistant", "content": "需要开通 Storage.Dentry.Search。", "created_at": "2026-08-07T01:00:03Z"},
            ]

    monkeypatch.setattr(chat_router, "provider_for_session", lambda _session: ToolHistoryHermes())

    history = await client.get(
        f"/api/chat/sessions/{created.json()['id']}/messages",
        headers=admin_headers,
    )

    assert history.status_code == 200, history.text
    assert [(item["role"], item["content"]) for item in history.json()["items"]] == [
        ("user", "读取钉钉文档"),
        ("assistant", "需要开通 Storage.Dentry.Search。"),
    ]


def knowledge_context_payload(stream_text: str) -> dict[str, object]:
    match = re.search(r"event: knowledge\.context\r?\ndata: ([^\r\n]+)", stream_text)
    assert match is not None, stream_text
    return json.loads(match.group(1))


@pytest.mark.asyncio
async def test_citations_survive_history_refresh_and_resolve_rechecks_authorization(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieved_source_ids: list[int] = []
    entry = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Citation source", "content": "policy"},
    )
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["id"]

    class CitationHermes:
        def __init__(self):
            self.completed = False

        async def create_response(self, *_args, **_kwargs):
            return "citation-run"

        async def stream_events(self, run_id, session_id, prompt=None, **kwargs):
            del prompt, kwargs
            yield f'event: run.created\ndata: {{"run_id":"{run_id}","session_id":"{session_id}"}}\n\n'
            self.completed = True
            yield (
                "event: response.completed\n"
                f'data: {{"event":"run.completed","run_id":"{run_id}","output":"制度回答"}}\n\n'
            )

        async def get_session_messages(self, _session_id, **_kwargs):
            if not self.completed:
                return []
            return [
                {
                    "id": "stable-assistant-message",
                    "role": "assistant",
                    "content": "制度回答",
                    "created_at": "2026-07-31T01:02:03Z",
                }
            ]

    class CitationRetriever:
        async def retrieve(self, **kwargs):
            retrieved_source_ids.extend(kwargs["source_ids"])
            return KnowledgeRetrieveResponse(
                citations=[
                    KnowledgeCitation(
                        entry_id=entry_id,
                        title="Citation source",
                        content_sha256="c" * 64,
                        source_locator="chunk:0",
                        text="private citation text",
                        score=0.95,
                    )
                ],
                mode="hybrid",
            )

    provider = CitationHermes()
    monkeypatch.setattr(chat_router, "provider_for_session", lambda _session: provider)
    monkeypatch.setattr(
        chat_router,
        "build_platform_knowledge_retriever",
        lambda _db: CitationRetriever(),
    )
    session = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Citation history", "surface": "knowledge"},
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]
    selected = await client.put(
        f"/api/chat/sessions/{session_id}/knowledge-scope",
        headers=admin_headers,
        json={"mode": "selected", "source_ids": [entry_id]},
    )
    assert selected.status_code == 200, selected.text
    streamed = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        headers=admin_headers,
        json={"content": "制度是什么？"},
    )
    assert streamed.status_code == 200, streamed.text
    context = knowledge_context_payload(streamed.text)
    assert context["mode"] == "hybrid"
    assert context["rejected_source_count"] == 0
    assert retrieved_source_ids == [entry_id]
    assert "private citation text" not in streamed.text

    history = await client.get(
        f"/api/chat/sessions/{session_id}/messages",
        headers=admin_headers,
    )
    assert history.status_code == 200, history.text
    assistant = history.json()["items"][0]
    assert assistant["turn_id"] == context["turn_id"]
    assert assistant["retrieval_mode"] == "hybrid"
    assert assistant["rejected_source_count"] == 0
    assert assistant["citations"] == [
        {
            "ordinal": 0,
            "entry_id": entry_id,
            "title": "Citation source",
            "content_sha256": "c" * 64,
            "source_locator": "chunk:0",
        }
    ]

    turn_id = context["turn_id"]
    visible = await client.get(
        f"/api/knowledge/citations/{turn_id}/0",
        headers=admin_headers,
    )
    assert visible.status_code == 200, visible.text
    assert visible.json()["entry_id"] == entry_id

    async with SessionLocal() as db:
        stored_session = await db.get(ChatSession, session_id)
        assert stored_session is not None
        member_role = await db.scalar(select(Role).where(Role.name == "user"))
        assert member_role is not None
        private_owner = User(
            username="citation-private-owner",
            email="citation-private-owner@example.com",
            password_hash=hash_password("citation-private-owner-password"),
            role_id=member_role.id,
            default_organization_id=stored_session.organization_id,
        )
        if hasattr(User, "normalized_email"):
            private_owner.normalized_email = "citation-private-owner@example.com"
        db.add(private_owner)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=stored_session.organization_id,
                user_id=private_owner.id,
                role_id=member_role.id,
                member_type="internal",
            )
        )
        stored_entry = await db.get(KnowledgeEntry, entry_id)
        assert stored_entry is not None
        stored_entry.user_id = private_owner.id
        stored_entry.visibility = "private"
        await db.commit()

    refreshed_history = await client.get(
        f"/api/chat/sessions/{session_id}/messages",
        headers=admin_headers,
    )
    assert refreshed_history.status_code == 200, refreshed_history.text
    assert refreshed_history.json()["items"][0]["rejected_source_count"] == 1

    revoked = await client.get(
        f"/api/knowledge/citations/{turn_id}/0",
        headers=admin_headers,
    )
    assert revoked.status_code == 404


@pytest.mark.asyncio
async def test_knowledge_context_precedes_the_first_upstream_event(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Context order", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    run_id = "context-order-run"

    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session is not None
        session.active_hermes_run_id = run_id
        session.active_run_status = "running"
        await db.commit()

    async def upstream_events():
        yield 'event: run.created\ndata: {"run_id":"context-order-run"}\n\n'
        yield (
            "event: response.completed\n"
            'data: {"event":"run.completed","run_id":"context-order-run","output":"answer"}\n\n'
        )

    events = [
        event
        async for event in chat_router.stream_session_run(
            upstream_events(),
            session_id=session_id,
            run_id=run_id,
            task_id=created.json()["hermes_session_id"],
            cleanup_runner=False,
            knowledge_context_event=(
                'event: knowledge.context\ndata: {"turn_id":1,"mode":"hybrid",'
                '"rejected_source_count":0,"citations":[]}\n\n'
            ),
        )
    ]

    assert events[0].startswith("event: knowledge.context")
    assert events[1].startswith("event: run.created")


@pytest.mark.asyncio
async def test_platform_action_precedes_context_and_upstream_events(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Platform action order", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    run_id = "platform-action-order-run"

    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session is not None
        session.active_hermes_run_id = run_id
        session.active_run_status = "running"
        await db.commit()

    async def upstream_events():
        yield 'event: run.created\ndata: {"run_id":"platform-action-order-run"}\n\n'
        yield 'event: response.completed\ndata: {"run_id":"platform-action-order-run"}\n\n'

    events = [
        event
        async for event in chat_router.stream_session_run(
            upstream_events(),
            session_id=session_id,
            run_id=run_id,
            task_id=created.json()["hermes_session_id"],
            cleanup_runner=False,
            platform_action_event=(
                'event: platform.action\ndata: {"action":"pipeline_task",'
                '"status":"completed","task_id":1,"run_id":2}\n\n'
            ),
            knowledge_context_event=(
                'event: knowledge.context\ndata: {"turn_id":1,"mode":"hybrid",'
                '"rejected_source_count":0,"citations":[]}\n\n'
            ),
        )
    ]

    assert events[0].startswith("event: platform.action")
    assert events[1].startswith("event: knowledge.context")
    assert events[2].startswith("event: run.created")


@pytest.mark.asyncio
async def test_chat_checks_session_ownership_before_reading_link_context(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context_read = False

    async def mark_link_context_read(*_args, **_kwargs):
        nonlocal context_read
        context_read = True
        return []

    monkeypatch.setattr(chat_router, "resolve_chat_link_context", mark_link_context_read)

    response = await client.post(
        "/api/chat/sessions/999999/messages",
        headers=admin_headers,
        json={"content": "读取链接", "links": ["https://example.feishu.cn/docx/doxcn123"]},
    )

    assert response.status_code == 404
    assert context_read is False


@pytest.mark.asyncio
async def test_non_allowlisted_feishu_link_never_falls_back_to_public_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        feishu_read_configured=True,
        feishu_app_id="cli_app",
        feishu_app_secret="secret",
        feishu_read_allowed_organization_ids="1",
    )

    class Reader:
        async def read_link(self, _url: str) -> str:
            raise AssertionError("unapproved Feishu resource reached credential reader")

    async def unexpected_public_fetch(_url: str) -> str:
        raise AssertionError("unapproved Feishu resource reached public fetcher")

    monkeypatch.setattr(chat_router, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_router, "build_feishu_resource_reader", lambda _settings: Reader())
    monkeypatch.setattr(chat_router, "fetch_public_collaboration_link", unexpected_public_fetch)

    context = await chat_router.resolve_chat_link_context(
        "读取链接", ["https://example.feishu.cn/docx/doxcn123"], 1
    )

    assert context == [
        ("https://example.feishu.cn/docx/doxcn123", "飞书授权读取失败：feishu_resource_not_authorized")
    ]


@pytest.mark.asyncio
async def test_feishu_link_without_configured_reader_never_falls_back_to_public_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(feishu_read_configured=False)

    async def unexpected_public_fetch(_url: str) -> str:
        raise AssertionError("unconfigured Feishu resource reached public fetcher")

    monkeypatch.setattr(chat_router, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_router, "fetch_public_collaboration_link", unexpected_public_fetch)

    context = await chat_router.resolve_chat_link_context(
        "请读取 https://example.feishu.cn/docx/doxcn123。", [], 1
    )

    assert context == [
        ("https://example.feishu.cn/docx/doxcn123", "飞书授权读取失败：feishu_reader_not_configured")
    ]


@pytest.mark.asyncio
async def test_feishu_link_preview_never_uses_public_fetch_without_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(feishu_read_configured=False)

    async def unexpected_public_fetch(_url: str) -> str:
        raise AssertionError("Feishu preview reached public fetcher")

    monkeypatch.setattr(chat_router, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_router, "fetch_public_collaboration_link", unexpected_public_fetch)

    with pytest.raises(HTTPException, match="feishu_reader_not_configured") as error:
        await chat_router.preview_link(
            LinkPreviewRequest(url="https://example.feishu.cn/docx/doxcn123"),
            SimpleNamespace(organization_id=1),
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_content_feishu_link_uses_authorized_reader_without_public_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        feishu_read_configured=True,
        feishu_app_id="cli_app",
        feishu_app_secret="secret",
        feishu_read_allowed_organization_ids="1",
        feishu_read_allowed_document_tokens="doxcn123",
    )

    class Reader:
        async def read_link(self, url: str) -> str:
            assert url == "https://example.feishu.cn/docx/doxcn123"
            return "来自授权飞书文档的内容"

    async def unexpected_public_fetch(_url: str) -> str:
        raise AssertionError("authorized Feishu resource reached public fetcher")

    monkeypatch.setattr(chat_router, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_router, "build_feishu_resource_reader", lambda _settings: Reader())
    monkeypatch.setattr(chat_router, "fetch_public_collaboration_link", unexpected_public_fetch)

    context = await chat_router.resolve_chat_link_context(
        "请阅读 https://example.feishu.cn/docx/doxcn123。", [], 1
    )

    assert context == [
        ("https://example.feishu.cn/docx/doxcn123", "来自授权飞书文档的内容")
    ]


@pytest.mark.asyncio
async def test_feishu_base_link_uses_table_grant_without_public_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = (
        "https://my.feishu.cn/base/FWVxbAjvia1LlzsBwxFcAEFrn8b"
        "?table=tblLQYPgSQV7SIEy&view=vewSZjyq3j"
    )
    settings = Settings(
        feishu_read_configured=True,
        feishu_app_id="cli_app",
        feishu_app_secret="secret",
        feishu_read_allowed_organization_ids="1",
        feishu_read_allowed_base_tables=(
            "1:FWVxbAjvia1LlzsBwxFcAEFrn8b:tblLQYPgSQV7SIEy"
        ),
    )

    class Reader:
        async def read_link(self, received_url: str) -> str:
            assert received_url == url
            return "任务: 完成验收"

    async def unexpected_public_fetch(_url: str) -> str:
        raise AssertionError("authorized Base link reached public fetcher")

    monkeypatch.setattr(chat_router, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_router, "build_feishu_resource_reader", lambda _settings: Reader())
    monkeypatch.setattr(chat_router, "fetch_public_collaboration_link", unexpected_public_fetch)

    context = await chat_router.resolve_chat_link_context(f"请读取 {url}", [], 1)

    assert context == [(url, "任务: 完成验收")]


@pytest.mark.asyncio
async def test_feishu_base_link_rejects_ungranted_table_without_public_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = (
        "https://my.feishu.cn/base/FWVxbAjvia1LlzsBwxFcAEFrn8b"
        "?table=tblNotGranted&view=vewSZjyq3j"
    )
    settings = Settings(
        feishu_read_configured=True,
        feishu_app_id="cli_app",
        feishu_app_secret="secret",
        feishu_read_allowed_organization_ids="1",
        feishu_read_allowed_base_tables=(
            "1:FWVxbAjvia1LlzsBwxFcAEFrn8b:tblLQYPgSQV7SIEy"
        ),
    )

    class Reader:
        async def read_link(self, _url: str) -> str:
            raise AssertionError("unapproved Base link reached credential reader")

    async def unexpected_public_fetch(_url: str) -> str:
        raise AssertionError("unapproved Base link reached public fetcher")

    monkeypatch.setattr(chat_router, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_router, "build_feishu_resource_reader", lambda _settings: Reader())
    monkeypatch.setattr(chat_router, "fetch_public_collaboration_link", unexpected_public_fetch)

    context = await chat_router.resolve_chat_link_context(f"请读取 {url}", [], 1)

    assert context == [(url, "飞书授权读取失败：feishu_resource_not_authorized")]


@pytest.mark.asyncio
async def test_blank_completed_knowledge_answer_is_persisted_as_failed(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Blank answer", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    run_id = "blank-answer-run"

    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session is not None
        session.active_hermes_run_id = run_id
        session.active_run_status = "running"
        turn = ChatTurn(
            organization_id=session.organization_id,
            user_id=session.user_id,
            chat_session_id=session.id,
            run_id=run_id,
            status="streaming",
            retrieval_mode="hybrid",
        )
        db.add(turn)
        await db.commit()
        await db.refresh(turn)
        turn_id = turn.id
        request_context = HermesRequestContext(
            user_id=session.user_id,
            organization_id=str(session.organization_id),
            session_id=session.hermes_session_id,
            correlation_id="blank-answer-correlation",
        )

    class BlankAnswerProvider:
        async def get_session_messages(self, _session_id, **_kwargs):
            return [
                {
                    "id": "blank-assistant-message",
                    "role": "assistant",
                    "content": "",
                    "created_at": "2026-08-03T00:00:00Z",
                }
            ]

    async def blank_completed_events():
        yield (
            "event: response.completed\n"
            'data: {"event":"run.completed","run_id":"blank-answer-run","output":""}\n\n'
        )

    _ = [
        event
        async for event in chat_router.stream_session_run(
            blank_completed_events(),
            session_id=session_id,
            run_id=run_id,
            task_id=request_context.session_id,
            cleanup_runner=False,
            provider=BlankAnswerProvider(),
            request_context=request_context,
            before_messages=[],
            turn_id=turn_id,
        )
    ]

    async with SessionLocal() as db:
        turn = await db.get(ChatTurn, turn_id)
        assert turn is not None
        assert turn.status == "failed"
        assert turn.assistant_message_id is None


@pytest.mark.asyncio
async def test_completed_turn_is_not_overwritten_when_history_retry_fails(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Completed then retry", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    run_id = "completed-then-retry-run"

    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session is not None
        session.active_hermes_run_id = run_id
        session.active_run_status = "running"
        turn = ChatTurn(
            organization_id=session.organization_id,
            user_id=session.user_id,
            chat_session_id=session.id,
            run_id=run_id,
            status="completed",
            retrieval_mode="hybrid",
        )
        db.add(turn)
        await db.commit()
        await db.refresh(turn)
        turn_id = turn.id

    class FailingHistoryProvider:
        async def get_session_messages(self, _session_id, **_kwargs):
            raise HermesUpstreamError("history unavailable")

    async def completed_events():
        yield 'event: response.completed\ndata: {"run_id":"completed-then-retry-run"}\n\n'

    _ = [
        event
        async for event in chat_router.stream_session_run(
            completed_events(),
            session_id=session_id,
            run_id=run_id,
            task_id=created.json()["hermes_session_id"],
            cleanup_runner=False,
            provider=FailingHistoryProvider(),
            request_context=SimpleNamespace(),
            before_messages=[],
            turn_id=turn_id,
        )
    ]

    async with SessionLocal() as db:
        turn = await db.get(ChatTurn, turn_id)
        assert turn is not None
        assert turn.status == "completed"


@pytest.mark.asyncio
async def test_knowledge_stream_without_terminal_event_is_interrupted(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Interrupted answer", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    run_id = "interrupted-answer-run"

    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        assert session is not None
        session.active_hermes_run_id = run_id
        session.active_run_status = "running"
        turn = ChatTurn(
            organization_id=session.organization_id,
            user_id=session.user_id,
            chat_session_id=session.id,
            run_id=run_id,
            status="streaming",
            retrieval_mode="empty",
        )
        db.add(turn)
        await db.commit()
        await db.refresh(turn)
        turn_id = turn.id

    async def incomplete_events():
        yield 'event: run.created\ndata: {"run_id":"interrupted-answer-run"}\n\n'

    _ = [
        event
        async for event in chat_router.stream_session_run(
            incomplete_events(),
            session_id=session_id,
            run_id=run_id,
            task_id=created.json()["hermes_session_id"],
            cleanup_runner=False,
            turn_id=turn_id,
        )
    ]

    async with SessionLocal() as db:
        turn = await db.get(ChatTurn, turn_id)
        assert turn is not None
        assert turn.status == "interrupted"
        assert turn.assistant_message_id is None
