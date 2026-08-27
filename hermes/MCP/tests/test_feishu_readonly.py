from __future__ import annotations

import json
from collections.abc import Callable

import pytest

import hermes_mcp.backends.lark_cli as lark_cli_module
from hermes_mcp.config.loader import load_config
from hermes_mcp.feishu_readonly import (
    LarkCLIBackend,
    LarkCLIError,
    create_feishu_readonly_server,
    register_feishu_readonly_tools,
)


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        communicate_error: BaseException | None = None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.communicate_error = communicate_error
        self.terminated = False
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self.communicate_error is not None:
            raise self.communicate_error
        return self.stdout, self.stderr

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def process_factory_for(
    process: FakeProcess, calls: list[tuple[tuple[str, ...], dict]]
) -> Callable:
    async def create_process(*args, **kwargs):
        calls.append((tuple(args), kwargs))
        return process

    return create_process


def sequence_process_factory(
    processes: list[FakeProcess], calls: list[tuple[tuple[str, ...], dict]]
) -> Callable:
    async def create_process(*args, **kwargs):
        calls.append((tuple(args), kwargs))
        return processes.pop(0)

    return create_process


def envelope(data: object) -> bytes:
    return json.dumps({"ok": True, "data": data}).encode("utf-8")


@pytest.mark.asyncio
async def test_list_groups_uses_user_identity_and_group_only_command() -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIBackend(
        cli_path="lark-cli",
        process_factory=process_factory_for(
            FakeProcess(stdout=envelope({"items": [], "page_token": "next"})), calls
        ),
    )

    result = await backend.list_feishu_groups(page_size=12, page_token="p1", sort="active_time")

    assert result == {"items": [], "page_token": "next"}
    argv = calls[0][0]
    assert argv == (
        "lark-cli",
        "im",
        "+chat-list",
        "--as",
        "user",
        "--types",
        "group",
        "--page-size",
        "12",
        "--page-token",
        "p1",
        "--sort",
        "active_time",
        "--format",
        "json",
    )


@pytest.mark.asyncio
async def test_list_and_read_reject_unsupported_ordering_values() -> None:
    backend = LarkCLIBackend(process_factory=process_factory_for(FakeProcess(), []))

    with pytest.raises(LarkCLIError) as sort_error:
        await backend.list_feishu_groups(sort="recent")
    assert sort_error.value.code == "invalid_sort"

    with pytest.raises(LarkCLIError) as order_error:
        await backend.read_feishu_group_messages("oc_group", order="recent")
    assert order_error.value.code == "invalid_order"


@pytest.mark.asyncio
async def test_read_group_messages_rejects_non_group_ids_and_never_enables_downloads() -> None:
    backend = LarkCLIBackend(process_factory=process_factory_for(FakeProcess(), []))

    with pytest.raises(LarkCLIError) as error:
        await backend.read_feishu_group_messages("ou_private_user")
    assert error.value.code == "invalid_chat_id"

    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIBackend(
        process_factory=sequence_process_factory(
            [
                FakeProcess(stdout=envelope({"items": [{"chat_id": "oc_group-1"}]})),
                FakeProcess(stdout=envelope({"items": []})),
            ],
            calls,
        )
    )
    await backend.read_feishu_group_messages(
        "oc_group-1",
        start="2026-08-01",
        end="2026-08-02",
        order="asc",
        page_size=7,
        page_token="next",
    )
    argv = calls[1][0]
    assert "--as" in argv and argv[argv.index("--as") + 1] == "user"
    assert "--chat-id" in argv and argv[argv.index("--chat-id") + 1] == "oc_group-1"
    assert "--no-reactions" in argv
    assert "--download-resources" not in argv
    assert "--user-id" not in argv


@pytest.mark.asyncio
async def test_read_group_messages_rejects_chat_not_in_current_user_group_list() -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(stdout=envelope({"items": [{"chat_id": "oc_allowed"}]})), calls
        )
    )

    with pytest.raises(LarkCLIError) as error:
        await backend.read_feishu_group_messages("oc_private-shaped")

    assert error.value.code == "chat_not_allowed"
    assert "oc_private-shaped" not in error.value.message
    assert len(calls) == 1
    assert "+chat-list" in calls[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "error_subtype", "expected"),
    [
        ("authentication", "token_missing", "user_auth_required"),
        ("authorization", "scope_missing", "missing_scope"),
        ("permission", "forbidden", "permission_denied"),
    ],
)
async def test_cli_error_type_and_subtype_are_normalized(
    error_type: str, error_subtype: str, expected: str
) -> None:
    payload = {
        "ok": False,
        "error": {"type": error_type, "subtype": error_subtype, "message": "detail"},
    }
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(stdout=json.dumps(payload).encode("utf-8"), returncode=1), []
        )
    )

    with pytest.raises(LarkCLIError) as error:
        await backend.list_feishu_groups()

    assert error.value.code == expected


@pytest.mark.asyncio
async def test_missing_scope_error_uses_hint_scopes_with_actionable_message() -> None:
    payload = {
        "ok": False,
        "error": {
            "type": "authorization",
            "subtype": "scope_missing",
            "message": "scope missing",
            "hint": {"missing_scopes": ["im:chat:readonly", "im:message"]},
        },
    }
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(stdout=json.dumps(payload).encode("utf-8"), returncode=1), []
        )
    )

    with pytest.raises(LarkCLIError) as error:
        await backend.list_feishu_groups()

    assert error.value.code == "missing_scope"
    assert "im:chat:readonly" in error.value.message
    assert "请在飞书应用或用户授权中补齐这些权限" in error.value.message


@pytest.mark.asyncio
async def test_missing_scope_error_extracts_scopes_from_string_hint() -> None:
    payload = {
        "ok": False,
        "error": {
            "type": "authorization",
            "subtype": "scope_missing",
            "hint": "Missing scopes: im:chat:read, im:message:readonly",
        },
    }
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(stdout=json.dumps(payload).encode("utf-8"), returncode=1), []
        )
    )

    with pytest.raises(LarkCLIError) as error:
        await backend.list_feishu_groups()

    assert error.value.code == "missing_scope"
    assert "im:chat:read" in error.value.message
    assert "im:message:readonly" in error.value.message


@pytest.mark.asyncio
async def test_page_token_is_preserved_when_returned_in_data() -> None:
    page_token = "eyJpagination-token-that-is-not-a-secret"
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(stdout=envelope({"items": [], "page_token": page_token})), []
        )
    )

    result = await backend.list_feishu_groups()

    assert result == {"items": [], "page_token": page_token}


@pytest.mark.asyncio
async def test_group_list_normalizes_real_cli_shape_and_projects_safe_fields() -> None:
    raw_group = {
        "avatar": "https://example.invalid/avatar",
        "chat_id": "oc_group",
        "chat_mode": "group",
        "chat_status": "normal",
        "description": "项目群",
        "external": False,
        "name": "项目",
        "owner_id": "ou_owner",
        "owner_id_type": "open_id",
        "tenant_key": "tenant-sensitive",
    }
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(
                stdout=envelope(
                    {"chats": [raw_group], "has_more": True, "page_token": "next"}
                )
            ),
            [],
        )
    )

    result = await backend.list_feishu_groups()

    assert result == {
        "items": [
            {
                "chat_id": "oc_group",
                "name": "项目",
                "description": "项目群",
                "status": "normal",
            }
        ],
        "has_more": True,
        "page_token": "next",
    }
    assert backend._group_ids == {"oc_group"}


@pytest.mark.asyncio
async def test_success_payload_redacts_prefixed_credentials_but_keeps_page_token() -> None:
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(
                stdout=envelope(
                    {
                        "tenant_access_token": "tenant-secret",
                        "user_refresh_token": "refresh-secret",
                        "page_token": "pagination-value",
                    }
                )
            ),
            [],
        )
    )

    result = await backend._run(["read-only-test"])

    assert result == {
        "tenant_access_token": "<redacted>",
        "user_refresh_token": "<redacted>",
        "page_token": "pagination-value",
    }


@pytest.mark.asyncio
async def test_invalid_json_includes_bounded_redacted_stderr_diagnostic() -> None:
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(stdout=b"not-json", stderr=b"access_token=secret detail"), []
        )
    )

    with pytest.raises(LarkCLIError) as error:
        await backend.list_feishu_groups()

    assert error.value.code == "invalid_json"
    assert "access_token=<redacted>" in error.value.message
    assert "secret" not in error.value.message


@pytest.mark.asyncio
async def test_search_requires_a_filter_and_forces_group_no_reactions() -> None:
    backend = LarkCLIBackend(process_factory=process_factory_for(FakeProcess(), []))

    with pytest.raises(LarkCLIError) as error:
        await backend.search_feishu_group_messages()
    assert error.value.code == "search_filter_required"

    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIBackend(
        process_factory=process_factory_for(FakeProcess(stdout=envelope({"items": []})), calls)
    )
    await backend.search_feishu_group_messages(
        query="安全培训",
        chat_ids=["oc_a", "oc_b"],
        sender_ids=["ou_sender"],
        start="2026-08-01T00:00:00+08:00",
        end="2026-08-02T00:00:00+08:00",
        page_size=9,
        page_token="p2",
    )
    argv = calls[0][0]
    assert "--chat-type" in argv and argv[argv.index("--chat-type") + 1] == "group"
    assert "--no-reactions" in argv
    assert "--query" in argv and argv[argv.index("--query") + 1] == "安全培训"
    assert "--chat-id" in argv and argv[argv.index("--chat-id") + 1] == "oc_a,oc_b"
    assert "--sender" in argv and argv[argv.index("--sender") + 1] == "ou_sender"


@pytest.mark.asyncio
async def test_search_allows_empty_query_with_group_filter() -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIBackend(
        process_factory=process_factory_for(FakeProcess(stdout=envelope({"items": []})), calls)
    )

    await backend.search_feishu_group_messages(query="  ", chat_ids=["oc_group"])

    argv = calls[0][0]
    assert "--query" not in argv
    assert argv[argv.index("--chat-id") + 1] == "oc_group"


@pytest.mark.asyncio
async def test_search_keeps_shell_metacharacters_as_one_argument() -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIBackend(
        process_factory=process_factory_for(FakeProcess(stdout=envelope({"items": []})), calls)
    )

    query = 'x" & echo INJECT & exit /b 0 &'
    await backend.search_feishu_group_messages(query=query)

    argv = calls[0][0]
    assert argv[argv.index("--query") + 1] == query


@pytest.mark.asyncio
async def test_message_time_filters_must_be_iso_8601() -> None:
    backend = LarkCLIBackend(process_factory=process_factory_for(FakeProcess(), []))

    with pytest.raises(LarkCLIError) as error:
        await backend.read_feishu_group_messages("oc_group", start="yesterday")

    assert error.value.code == "invalid_parameter"


@pytest.mark.asyncio
async def test_cli_errors_are_bounded_and_redacted() -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    process = FakeProcess(
        stdout=json.dumps(
            {
                "ok": False,
                "error": {"code": "missing_scope", "message": "access_token=secret-token"},
            }
        ).encode("utf-8"),
        stderr=b"refresh_token=another-secret",
        returncode=1,
    )
    backend = LarkCLIBackend(
        max_output_bytes=256,
        process_factory=process_factory_for(process, calls),
    )

    with pytest.raises(LarkCLIError) as error:
        await backend.list_feishu_groups()

    assert error.value.code == "missing_scope"
    assert "secret-token" not in str(error.value)
    assert "another-secret" not in str(error.value)
    assert "access_token=<redacted>" in str(error.value)


@pytest.mark.asyncio
async def test_cli_diagnostics_redact_bearer_and_camel_case_tokens() -> None:
    payload = {
        "ok": False,
        "error": {
            "code": "cli_error",
            "message": "Authorization: Bearer bearer-secret accessToken=camel-secret",
        },
    }
    backend = LarkCLIBackend(
        process_factory=process_factory_for(
            FakeProcess(stdout=json.dumps(payload).encode("utf-8"), returncode=1), []
        )
    )

    with pytest.raises(LarkCLIError) as error:
        await backend.list_feishu_groups()

    diagnostic = str(error.value)
    assert "bearer-secret" not in diagnostic
    assert "camel-secret" not in diagnostic


@pytest.mark.asyncio
async def test_cli_timeout_and_oversized_output_fail_closed() -> None:
    timeout_process = FakeProcess(communicate_error=TimeoutError())
    backend = LarkCLIBackend(
        process_factory=process_factory_for(timeout_process, []), timeout=0.01
    )

    with pytest.raises(LarkCLIError) as timeout_error:
        await backend.list_feishu_groups()
    assert timeout_error.value.code == "timeout"
    assert timeout_process.terminated

    oversized = FakeProcess(stdout=b"{" + b"x" * 100 + b"}")
    backend = LarkCLIBackend(
        max_output_bytes=32,
        process_factory=process_factory_for(oversized, []),
    )
    with pytest.raises(LarkCLIError) as size_error:
        await backend.list_feishu_groups()
    assert size_error.value.code == "output_too_large"


@pytest.mark.asyncio
async def test_unexpected_process_start_failure_is_safe() -> None:
    async def failing_process_factory(*args, **kwargs):
        raise RuntimeError("internal process detail")

    backend = LarkCLIBackend(process_factory=failing_process_factory)

    with pytest.raises(LarkCLIError) as error:
        await backend.list_feishu_groups()

    assert error.value.code == "cli_unavailable"
    assert "internal process detail" not in str(error.value)


def test_windows_default_cli_resolves_native_npm_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lark_cli_module.os, "name", "nt")
    wrapper = r"C:\tools\lark-cli.cmd"
    native = r"C:\tools\node_modules\@larksuite\cli\bin\lark-cli.exe"
    monkeypatch.setattr(
        lark_cli_module.Path,
        "is_file",
        lambda path: str(path).lower().endswith("lark-cli.exe"),
    )
    monkeypatch.setattr(
        lark_cli_module.shutil,
        "which",
        lambda candidate: wrapper if candidate == "lark-cli" else None,
    )

    backend = LarkCLIBackend()

    assert backend._command_path().lower() == native.lower()


def test_config_has_feishu_readonly_defaults_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_MCP_FEISHU_READONLY_ENABLED", "false")
    monkeypatch.setenv("HERMES_MCP_FEISHU_READONLY_CLI_PATH", "C:\\tools\\lark-cli.exe")
    monkeypatch.setenv("HERMES_MCP_FEISHU_READONLY_TIMEOUT", "9.5")
    monkeypatch.setenv("HERMES_MCP_FEISHU_READONLY_MAX_OUTPUT_BYTES", "2048")

    config = load_config()

    assert config.feishu_readonly.enabled is False
    assert config.feishu_readonly.cli_path == "C:\\tools\\lark-cli.exe"
    assert config.feishu_readonly.timeout == 9.5
    assert config.feishu_readonly.max_output_bytes == 2048


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable] = {}

    def tool(self, *, name: str, description: str):
        def decorator(function: Callable) -> Callable:
            self.tools[name] = function
            return function

        return decorator


def test_readonly_server_registers_exactly_three_tools() -> None:
    mcp = FakeMCP()
    backend = LarkCLIBackend(process_factory=process_factory_for(FakeProcess(), []))

    register_feishu_readonly_tools(mcp, backend)

    assert set(mcp.tools) == {
        "list_feishu_groups",
        "read_feishu_group_messages",
        "search_feishu_group_messages",
    }
    server = create_feishu_readonly_server(backend=backend)
    assert server.name == "hermes-feishu-readonly"
