from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import hermes_mcp.backends.lark_cli_full as lark_cli_full_module
from hermes_mcp.backends.lark_cli_full import (
    ALLOWED_BUSINESS_DOMAINS,
    LarkCLIFullBackend,
    LarkCLIFullError,
)
from hermes_mcp.config.loader import load_config
from hermes_mcp.lark_cli_full import (
    create_lark_cli_full_server,
    register_lark_cli_full_tools,
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
    process: FakeProcess,
    calls: list[tuple[tuple[str, ...], dict]],
) -> Callable:
    async def create_process(*args, **kwargs):
        calls.append((tuple(args), kwargs))
        return process

    return create_process


def sequence_process_factory(
    processes: list[FakeProcess],
    calls: list[tuple[tuple[str, ...], dict]],
) -> Callable:
    async def create_process(*args, **kwargs):
        calls.append((tuple(args), kwargs))
        return processes.pop(0)

    return create_process


def success(data: object) -> bytes:
    return json.dumps({"ok": True, "identity": "user", "data": data}).encode("utf-8")


def confirmation_required(
    action: str = "task +create",
    risk: str = "high-risk-write",
) -> bytes:
    return json.dumps(
        {
            "ok": False,
            "identity": "user",
            "error": {
                "type": "confirmation",
                "subtype": "confirmation_required",
                "message": f"{action} requires confirmation",
                "hint": "add --yes to confirm",
                "action": action,
                "risk": risk,
            },
        }
    ).encode("utf-8")


def make_backend(
    tmp_path: Path,
    *,
    process: FakeProcess | None = None,
    calls: list[tuple[tuple[str, ...], dict]] | None = None,
) -> tuple[LarkCLIFullBackend, list[tuple[tuple[str, ...], dict]]]:
    recorded_calls = calls if calls is not None else []
    fake_process = process or FakeProcess(stdout=success({"items": []}))
    backend = LarkCLIFullBackend(
        cli_path="lark-cli",
        workspace_root=tmp_path,
        process_factory=process_factory_for(fake_process, recorded_calls),
    )
    return backend, recorded_calls


def test_business_domain_allowlist_matches_the_approved_design() -> None:
    assert frozenset(
        {
            "approval",
            "apps",
            "attendance",
            "base",
            "calendar",
            "contact",
            "docs",
            "drive",
            "event",
            "im",
            "mail",
            "markdown",
            "mindnotes",
            "minutes",
            "note",
            "okr",
            "sheets",
            "slides",
            "task",
            "vc",
            "whiteboard",
            "wiki",
        }
    ) == ALLOWED_BUSINESS_DOMAINS


@pytest.mark.asyncio
async def test_execute_forces_user_identity_without_shell(tmp_path: Path) -> None:
    backend, calls = make_backend(tmp_path)

    result = await backend.execute(["task", "+get-my-tasks", "--query", "x & whoami"])

    assert result == {"ok": True, "data": {"items": []}}
    assert calls[0][0] == (
        "lark-cli",
        "task",
        "+get-my-tasks",
        "--query",
        "x & whoami",
        "--as",
        "user",
        "--format",
        "json",
    )
    assert calls[0][1]["cwd"] == tmp_path


@pytest.mark.asyncio
async def test_execute_allows_empty_query_value(tmp_path: Path) -> None:
    backend, calls = make_backend(tmp_path)

    await backend.execute(["drive", "+search", "--query", ""])

    assert calls[0][0] == (
        "lark-cli",
        "drive",
        "+search",
        "--query",
        "",
        "--as",
        "user",
        "--format",
        "json",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "root_command",
    [
        "api",
        "auth",
        "config",
        "profile",
        "update",
        "doctor",
        "skills",
        "schema",
        "help",
        "whoami",
        "application",
    ],
)
async def test_execute_rejects_non_business_root_commands(
    tmp_path: Path,
    root_command: str,
) -> None:
    backend, calls = make_backend(tmp_path)

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute([root_command])

    assert captured.value.code == "invalid_command"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argv",
    [
        ["task", "+get-my-tasks", "--yes"],
        ["task", "+get-my-tasks", "--yes=true"],
        ["task", "+get-my-tasks", "--as", "bot"],
        ["task", "+get-my-tasks", "--as=user"],
        ["task", "+get-my-tasks", "--profile", "other"],
        ["task", "+get-my-tasks", "--profile=other"],
        ["task", "+get-my-tasks", "--format", "table"],
        ["task", "+get-my-tasks", "--json"],
        ["task", "+get-my-tasks", "--jq", ".data"],
    ],
)
async def test_execute_rejects_security_and_output_control_flags(
    tmp_path: Path,
    argv: list[str],
) -> None:
    backend, calls = make_backend(tmp_path)

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute(argv)

    assert captured.value.code == "invalid_command"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argv",
    [
        [],
        [""],
        ["task", ""],
        ["task", "bad\x00value"],
        ["task", "x" * 32769],
    ],
)
async def test_execute_rejects_invalid_argument_arrays(
    tmp_path: Path,
    argv: list[str],
) -> None:
    backend, calls = make_backend(tmp_path)

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute(argv)

    assert captured.value.code == "invalid_command"
    assert calls == []


@pytest.mark.asyncio
async def test_help_allows_only_root_or_approved_business_domain(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend, _ = make_backend(
        tmp_path,
        process=FakeProcess(stdout=b"Task help"),
        calls=calls,
    )

    result = await backend.help("task")

    assert result == {"ok": True, "data": {"topic": "task", "content": "Task help"}}
    assert calls[0][0] == ("lark-cli", "task", "--help")

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.help("auth")
    assert captured.value.code == "invalid_command"


@pytest.mark.asyncio
async def test_schema_accepts_only_approved_domain_identifiers(tmp_path: Path) -> None:
    backend, calls = make_backend(
        tmp_path,
        process=FakeProcess(
            stdout=json.dumps({"name": "task tasks list", "risk": "read"}).encode()
        ),
    )

    result = await backend.schema("task.tasks.list")

    assert result == {
        "ok": True,
        "data": {"name": "task tasks list", "risk": "read"},
    }
    assert calls[0][0] == ("lark-cli", "schema", "task.tasks.list")

    for identifier in ("api.any.call", "task", "task..list", "task.tasks.list;whoami"):
        with pytest.raises(LarkCLIFullError) as captured:
            await backend.schema(identifier)
        assert captured.value.code == "invalid_command"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argv",
    [
        ["drive", "+upload", "--file", "../outside.txt"],
        ["drive", "+upload", "--file=../outside.txt"],
        ["drive", "+download", "--output-dir", "..\\outside"],
        ["drive", "+download", "--output", "C:\\outside\\result.bin"],
        ["docs", "+import", "@../request.json"],
        ["drive", "+upload", "--file"],
        ["drive", "+upload", "--file="],
    ],
)
async def test_execute_rejects_unsafe_or_missing_local_paths(
    tmp_path: Path,
    argv: list[str],
) -> None:
    backend, calls = make_backend(tmp_path)

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute(argv)

    assert captured.value.code == "invalid_path"
    assert calls == []


@pytest.mark.asyncio
async def test_execute_keeps_safe_relative_paths(tmp_path: Path) -> None:
    backend, calls = make_backend(tmp_path)

    await backend.execute(
        [
            "drive",
            "+upload",
            "--file",
            "uploads/source.txt",
            "--output=results/receipt.json",
            "@requests/body.json",
        ]
    )

    argv = calls[0][0]
    assert "uploads/source.txt" in argv
    assert "--output=results/receipt.json" in argv
    assert "@requests/body.json" in argv


@pytest.mark.asyncio
async def test_success_data_is_recursively_redacted_but_page_tokens_survive(
    tmp_path: Path,
) -> None:
    jwt = "eyJabcdefghijk.abcdefghijklm.abcdefghijklmno"
    process = FakeProcess(
        stdout=success(
            {
                "tenant_access_token": "tenant-secret",
                "nested": {
                    "password": "password-secret",
                    "message": f"Authorization: Bearer bearer-secret jwt={jwt}",
                },
                "page_token": "pagination-value",
            }
        )
    )
    backend, _ = make_backend(tmp_path, process=process)

    result = await backend.execute(["task", "+get-my-tasks"])

    rendered = json.dumps(result, ensure_ascii=False)
    assert "tenant-secret" not in rendered
    assert "password-secret" not in rendered
    assert "bearer-secret" not in rendered
    assert jwt not in rendered
    assert result["data"]["page_token"] == "pagination-value"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code", "expected_text"),
    [
        (
            {"type": "authentication", "subtype": "token_missing", "message": "missing"},
            "user_auth_required",
            "用户授权",
        ),
        (
            {
                "type": "authorization",
                "subtype": "scope_missing",
                "message": "scope missing",
                "missing_scopes": ["task:task:read", "docs:document:readonly"],
            },
            "missing_scope",
            "task:task:read",
        ),
        (
            {"type": "permission", "subtype": "forbidden", "message": "forbidden"},
            "permission_denied",
            "无权访问",
        ),
    ],
)
async def test_stderr_error_envelopes_are_normalized(
    tmp_path: Path,
    error: dict[str, object],
    expected_code: str,
    expected_text: str,
) -> None:
    stderr = json.dumps({"ok": False, "identity": "user", "error": error}).encode()
    backend, _ = make_backend(tmp_path, process=FakeProcess(stderr=stderr, returncode=1))

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute(["task", "+get-my-tasks"])

    assert captured.value.code == expected_code
    assert expected_text in captured.value.message


@pytest.mark.asyncio
async def test_stderr_log_prefix_before_auth_envelope_is_ignored(tmp_path: Path) -> None:
    private_user_id = "ou_private-user-id"
    envelope = json.dumps(
        {
            "ok": False,
            "identity": "user",
            "error": {
                "type": "authentication",
                "subtype": "token_missing",
                "message": f"need_user_authorization (user: {private_user_id})",
                "user_open_id": private_user_id,
            },
        },
        indent=2,
    )
    stderr = (
        f"[lark-cli] refresh_token expired for {private_user_id}, clearing\n{envelope}\n"
    ).encode()
    backend, _ = make_backend(
        tmp_path,
        process=FakeProcess(stderr=stderr, returncode=1),
    )

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute(["task", "tasks", "list", "--page-size", "1"])

    assert captured.value.code == "user_auth_required"
    assert private_user_id not in captured.value.message


@pytest.mark.asyncio
async def test_invalid_json_diagnostic_is_bounded_and_redacted(tmp_path: Path) -> None:
    process = FakeProcess(
        stderr=b"access_token=secret-token Authorization: Bearer bearer-secret",
        returncode=1,
    )
    backend, _ = make_backend(tmp_path, process=process)

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute(["task", "+get-my-tasks"])

    assert captured.value.code == "invalid_json"
    assert "secret-token" not in captured.value.message
    assert "bearer-secret" not in captured.value.message
    assert "<redacted>" in captured.value.message
    assert len(captured.value.message) <= 2000


@pytest.mark.asyncio
async def test_timeout_terminates_process_and_oversized_output_fails_closed(
    tmp_path: Path,
) -> None:
    timeout_process = FakeProcess(communicate_error=TimeoutError())
    backend, _ = make_backend(tmp_path, process=timeout_process)
    backend.timeout = 0.01

    with pytest.raises(LarkCLIFullError) as timeout_error:
        await backend.execute(["task", "+get-my-tasks"])
    assert timeout_error.value.code == "timeout"
    assert timeout_process.terminated

    backend, _ = make_backend(
        tmp_path,
        process=FakeProcess(stdout=b"{" + b"x" * 100 + b"}"),
    )
    backend.max_output_bytes = 32
    with pytest.raises(LarkCLIFullError) as size_error:
        await backend.execute(["task", "+get-my-tasks"])
    assert size_error.value.code == "output_too_large"


@pytest.mark.asyncio
async def test_unexpected_process_failure_does_not_expose_details(tmp_path: Path) -> None:
    async def failing_process_factory(*args, **kwargs):
        raise RuntimeError("internal secret detail")

    backend = LarkCLIFullBackend(
        workspace_root=tmp_path,
        process_factory=failing_process_factory,
    )

    with pytest.raises(LarkCLIFullError) as captured:
        await backend.execute(["task", "+get-my-tasks"])

    assert captured.value.code == "cli_unavailable"
    assert "internal secret detail" not in str(captured.value)


def test_windows_default_cli_resolves_the_native_npm_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrapper = r"C:\tools\lark-cli.cmd"
    native = r"C:\tools\node_modules\@larksuite\cli\bin\lark-cli.exe"
    monkeypatch.setattr(lark_cli_full_module.os, "name", "nt")
    monkeypatch.setattr(
        lark_cli_full_module.shutil,
        "which",
        lambda candidate: wrapper if candidate == "lark-cli" else None,
    )
    monkeypatch.setattr(
        lark_cli_full_module.Path,
        "is_file",
        lambda path: str(path).lower().endswith("lark-cli.exe"),
    )
    backend = LarkCLIFullBackend(workspace_root=tmp_path)

    assert backend._command_path().lower() == native.lower()


@pytest.mark.asyncio
async def test_exit_10_creates_an_argv_bound_confirmation_without_yes(
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIFullBackend(
        workspace_root=tmp_path,
        process_factory=process_factory_for(
            FakeProcess(stderr=confirmation_required(), returncode=10),
            calls,
        ),
        id_factory=lambda: "approval-1",
        time_source=lambda: 100.0,
    )
    argv = ["task", "+create", "--summary", "Prepare report"]

    result = await backend.execute(argv)

    assert result == {
        "ok": False,
        "error": {
            "code": "confirmation_required",
            "message": "该飞书操作属于高风险写操作，需要用户明确确认。",
            "approval_id": "approval-1",
            "action": "task +create",
            "risk": "high-risk-write",
            "argv": argv,
        },
    }
    assert "--yes" not in calls[0][0]


@pytest.mark.asyncio
async def test_valid_confirmation_appends_yes_once_and_consumes_ticket(
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIFullBackend(
        workspace_root=tmp_path,
        process_factory=sequence_process_factory(
            [
                FakeProcess(stderr=confirmation_required(), returncode=10),
                FakeProcess(stdout=success({"guid": "task-guid"})),
            ],
            calls,
        ),
        id_factory=lambda: "approval-1",
        time_source=lambda: 100.0,
    )
    argv = ["task", "+create", "--summary", "Prepare report"]
    first = await backend.execute(argv)

    result = await backend.execute(
        argv,
        approval_id=first["error"]["approval_id"],
        confirmed=True,
    )

    assert result == {"ok": True, "data": {"guid": "task-guid"}}
    assert calls[1][0][-1] == "--yes"
    assert calls[1][0].count("--yes") == 1
    with pytest.raises(LarkCLIFullError) as replay:
        await backend.execute(argv, approval_id="approval-1", confirmed=True)
    assert replay.value.code == "confirmation_invalid"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_confirmation_rejects_changed_argv_and_missing_confirmation_flag(
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIFullBackend(
        workspace_root=tmp_path,
        process_factory=process_factory_for(
            FakeProcess(stderr=confirmation_required(), returncode=10),
            calls,
        ),
        id_factory=lambda: "approval-1",
        time_source=lambda: 100.0,
    )
    argv = ["task", "+create", "--summary", "Original"]
    await backend.execute(argv)

    with pytest.raises(LarkCLIFullError) as changed:
        await backend.execute(
            ["task", "+create", "--summary", "Changed"],
            approval_id="approval-1",
            confirmed=True,
        )
    assert changed.value.code == "confirmation_invalid"

    with pytest.raises(LarkCLIFullError) as not_confirmed:
        await backend.execute(argv, approval_id="approval-1", confirmed=False)
    assert not_confirmed.value.code == "confirmation_invalid"

    with pytest.raises(LarkCLIFullError) as missing_id:
        await backend.execute(argv, confirmed=True)
    assert missing_id.value.code == "confirmation_invalid"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_confirmation_ticket_expires(tmp_path: Path) -> None:
    now = [100.0]
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIFullBackend(
        workspace_root=tmp_path,
        process_factory=process_factory_for(
            FakeProcess(stderr=confirmation_required(), returncode=10),
            calls,
        ),
        approval_ttl=30.0,
        id_factory=lambda: "approval-1",
        time_source=lambda: now[0],
    )
    argv = ["task", "+create", "--summary", "Original"]
    await backend.execute(argv)
    now[0] = 131.0

    with pytest.raises(LarkCLIFullError) as expired:
        await backend.execute(argv, approval_id="approval-1", confirmed=True)

    assert expired.value.code == "confirmation_invalid"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_confirmation_is_consumed_before_retry_and_second_exit_10_fails_closed(
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], dict]] = []
    backend = LarkCLIFullBackend(
        workspace_root=tmp_path,
        process_factory=sequence_process_factory(
            [
                FakeProcess(stderr=confirmation_required(), returncode=10),
                FakeProcess(stderr=confirmation_required(), returncode=10),
            ],
            calls,
        ),
        id_factory=lambda: "approval-1",
        time_source=lambda: 100.0,
    )
    argv = ["task", "+create", "--summary", "Original"]
    await backend.execute(argv)

    with pytest.raises(LarkCLIFullError) as second_confirmation:
        await backend.execute(argv, approval_id="approval-1", confirmed=True)
    assert second_confirmation.value.code == "confirmation_invalid"

    with pytest.raises(LarkCLIFullError) as replay:
        await backend.execute(argv, approval_id="approval-1", confirmed=True)
    assert replay.value.code == "confirmation_invalid"
    assert len(calls) == 2


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable] = {}

    def tool(self, *, name: str, description: str):
        def decorator(function: Callable) -> Callable:
            self.tools[name] = function
            return function

        return decorator


def test_full_server_registers_exactly_three_controlled_tools(tmp_path: Path) -> None:
    mcp = FakeMCP()
    backend, _ = make_backend(tmp_path)

    register_lark_cli_full_tools(mcp, backend)

    assert set(mcp.tools) == {
        "lark_cli_help",
        "lark_cli_schema",
        "lark_cli_execute",
    }
    server = create_lark_cli_full_server(backend=backend)
    assert server.name == "hermes-lark-cli"


@pytest.mark.asyncio
async def test_tool_wrappers_return_safe_error_envelopes(tmp_path: Path) -> None:
    mcp = FakeMCP()
    backend, _ = make_backend(tmp_path)
    register_lark_cli_full_tools(mcp, backend)

    result = await mcp.tools["lark_cli_execute"](["auth", "status"])

    assert result == {
        "ok": False,
        "error": {
            "code": "invalid_command",
            "message": "只允许已批准的飞书业务域命令。",
        },
    }


def test_full_mode_config_defaults_and_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_MCP_LARK_CLI_FULL_ENABLED", "false")
    monkeypatch.setenv("HERMES_MCP_LARK_CLI_FULL_CLI_PATH", r"C:\tools\lark-cli.exe")
    monkeypatch.setenv("HERMES_MCP_LARK_CLI_FULL_TIMEOUT", "12.5")
    monkeypatch.setenv("HERMES_MCP_LARK_CLI_FULL_MAX_OUTPUT_BYTES", "4096")
    monkeypatch.setenv("HERMES_MCP_LARK_CLI_FULL_APPROVAL_TTL", "90")

    config = load_config()

    assert config.lark_cli_full.enabled is False
    assert config.lark_cli_full.cli_path == r"C:\tools\lark-cli.exe"
    assert config.lark_cli_full.timeout == 12.5
    assert config.lark_cli_full.max_output_bytes == 4096
    assert config.lark_cli_full.approval_ttl == 90.0
