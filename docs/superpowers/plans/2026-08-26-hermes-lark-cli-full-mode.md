# Hermes lark-cli Full Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-command Feishu read-only MCP with a controlled, user-identity lark-cli MCP covering every approved Feishu business domain while retaining lark-cli's high-risk confirmation gate.

**Architecture:** A focused backend validates argv, local paths, identity, output limits, and one-time approval tickets before calling the native lark-cli executable with `asyncio.create_subprocess_exec`. A separate FastMCP entry point exposes only help, schema, and execute; Agent Hermes loads that server while Knowledge Hermes remains toolless.

**Tech Stack:** Python 3.11+, asyncio, FastMCP, Pydantic, pytest/pytest-asyncio, YAML, Hermes API server MCP configuration, lark-cli native Windows executable.

**Repository note:** `D:\Replica1.0` is not a Git repository. Do not initialize Git or create synthetic commits; preserve the same TDD and verification checkpoints as filesystem changes.

---

### Task 1: General lark-cli backend and safety policy

**Files:**
- Create: `hermes/MCP/src/hermes_mcp/backends/lark_cli_full.py`
- Create: `hermes/MCP/tests/test_lark_cli_full.py`

- [ ] **Step 1: Write failing tests for command and argument validation**

Add tests constructing `LarkCLIFullBackend` with an injected async process factory. Assert that the approved business domains are accepted, `api/auth/config/profile/update/doctor/skills/schema/help/whoami` are rejected by `execute`, all direct `--yes`, `--as`, and `--profile` arguments are rejected, empty/NUL/overlong arguments fail, and a metacharacter-bearing value remains one argv element.

```python
@pytest.mark.asyncio
async def test_execute_forces_user_identity_without_shell() -> None:
    calls = []
    backend = LarkCLIFullBackend(process_factory=process_factory(success({"items": []}), calls))
    result = await backend.execute(["task", "+get-my-tasks", "--query", "x & whoami"])
    assert result["ok"] is True
    assert calls[0][0] == (
        "lark-cli", "task", "+get-my-tasks", "--query", "x & whoami",
        "--as", "user", "--format", "json",
    )
```

- [ ] **Step 2: Run the policy tests and verify RED**

Run: `python -m pytest tests/test_lark_cli_full.py -v` from `hermes/MCP`.

Expected: collection fails because `hermes_mcp.backends.lark_cli_full` does not exist.

- [ ] **Step 3: Implement validation, native executable resolution, and bounded subprocess execution**

Implement this public surface:

```python
class LarkCLIFullBackend:
    async def help(self, topic: str | None = None) -> dict[str, object]: ...
    async def schema(self, identifier: str) -> dict[str, object]: ...
    async def execute(
        self,
        argv: Sequence[str],
        *,
        approval_id: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, object]: ...
```

Use a frozen allowlist containing `approval apps attendance base calendar contact docs drive event im mail markdown mindnotes minutes note okr sheets slides task vc whiteboard wiki`. Resolve npm wrappers to `node_modules/@larksuite/cli/bin/lark-cli.exe` on Windows. Invoke only `asyncio.create_subprocess_exec`, pass `cwd=workspace_root`, and enforce time/output limits.

- [ ] **Step 4: Write failing tests for paths, output handling, and error normalization**

Cover relative paths below `workspace_root`, reject absolute paths and `..` traversal for `--file`, `--output`, `--output-dir`, and `@file`; parse success JSON from stdout and failure JSON from stderr; preserve pagination tokens while redacting tokens, secrets, passwords, bearer headers, and JWTs; normalize missing user authorization, missing scope, and permission errors; fail closed on timeout, invalid JSON, or oversized output.

- [ ] **Step 5: Implement path policy, envelope parsing, redaction, and normalized errors**

Return stable envelopes:

```python
{"ok": True, "data": safe_data}
{"ok": False, "error": {"code": "missing_scope", "message": safe_message}}
```

Do not return environment variables, full executable paths, credentials, or unbounded stderr.

- [ ] **Step 6: Run backend tests and the existing read-only regression tests**

Run:

```powershell
python -m pytest tests/test_lark_cli_full.py tests/test_feishu_readonly.py -v
```

Expected: all tests pass; the legacy backend remains available for rollback but is no longer selected by Hermes.

### Task 2: One-time confirmation tickets

**Files:**
- Modify: `hermes/MCP/src/hermes_mcp/backends/lark_cli_full.py`
- Modify: `hermes/MCP/tests/test_lark_cli_full.py`

- [ ] **Step 1: Write failing tests for exit-code-10 confirmation**

Use a fake process whose stderr contains the lark-cli confirmation envelope. Assert the first call returns `confirmation_required` with a nonempty `approval_id`, safe action/risk/argv summary, and no `--yes` in the subprocess argv.

- [ ] **Step 2: Run the confirmation test and verify RED**

Run: `python -m pytest tests/test_lark_cli_full.py -k confirmation_required -v`.

Expected: failure because no approval ticket is created.

- [ ] **Step 3: Implement short-lived, argv-bound approval tickets**

Store tickets only in process memory with `approval_id`, exact normalized argv tuple, expiry, and used state. On exit 10 plus `confirmation/confirmation_required`, create a ticket. Require both `confirmed=True` and a matching unexpired unused id before appending `--yes`.

- [ ] **Step 4: Write failing tests for replay, expiry, mutation, and false confirmation**

Assert rejection for reused ids, expired ids, changed argv, `approval_id` without `confirmed=True`, `confirmed=True` without an id, and a second exit 10 after confirmation. Assert the valid retry appends exactly one trailing `--yes` and consumes the ticket before launching so concurrent replay cannot execute.

- [ ] **Step 5: Implement ticket consumption and run all backend tests**

Run: `python -m pytest tests/test_lark_cli_full.py -v`.

Expected: all approval and backend safety tests pass.

### Task 3: FastMCP entry point and Hermes isolation configuration

**Files:**
- Create: `hermes/MCP/src/hermes_mcp/lark_cli_full.py`
- Modify: `hermes/MCP/pyproject.toml`
- Modify: `hermes/MCP/tests/test_lark_cli_full.py`
- Modify: `hermes/config.yaml`
- Modify: `backend/tests/test_local_ai_runtime.py`

- [ ] **Step 1: Write failing tests for the exact MCP tool surface**

Register tools against a fake MCP and assert exactly:

```python
{"lark_cli_help", "lark_cli_schema", "lark_cli_execute"}
```

Assert each wrapper catches `LarkCLIFullError` and returns its safe structured envelope.

- [ ] **Step 2: Run the server tests and verify RED**

Run: `python -m pytest tests/test_lark_cli_full.py -k 'server or tools' -v`.

Expected: failure because `hermes_mcp.lark_cli_full` does not exist.

- [ ] **Step 3: Implement the dedicated FastMCP server**

Create `create_lark_cli_full_server`, `register_lark_cli_full_tools`, and a stdio-first `main`. Non-stdio transports may bind only to loopback. Give each tool a description that tells the model to prefer shortcuts, inspect schema before typed calls, and forward approval ids only after explicit user confirmation.

- [ ] **Step 4: Write and run a failing Hermes configuration test**

Update the expected configuration contract first:

```python
assert config["platform_toolsets"]["api_server"] == ["hermes-lark-cli"]
assert set(config["mcp_servers"]) == {"hermes-lark-cli"}
assert config["plugins"]["enabled"] == ["dingtalk-platform"]
assert {"hermes-mcp", "feishu-platform", "three-source-retrieval"} <= set(
    config["plugins"]["disabled"]
)
```

Run: `python -m pytest backend/tests/test_local_ai_runtime.py::test_agent_api_server_allows_only_lark_cli_mcp -v` from the project root.

Expected: failure against the old read-only configuration.

- [ ] **Step 5: Switch Agent Hermes to the new MCP and keep Knowledge Hermes unchanged**

Set the MCP module to `hermes_mcp.lark_cli_full`, keep `PYTHONPATH` and `HERMES_HOME`, remove the old MCP selection, disable `hermes-mcp` and `feishu-platform`, and retain `dingtalk-platform`. Do not add any MCP server or plugin to `hermes/knowledge-home/config.yaml`.

- [ ] **Step 6: Run MCP and runtime configuration tests**

Run:

```powershell
python -m pytest hermes/MCP/tests/test_lark_cli_full.py backend/tests/test_local_ai_runtime.py -v
```

Expected: all tests pass, including the Knowledge `no_mcp` assertions.

### Task 4: Documentation and live acceptance

**Files:**
- Modify: `hermes/MCP/README.md`
- Modify: `deploy/README.md`

- [ ] **Step 1: Document capability and trust boundaries**

Explain that Agent Hermes can use the approved lark-cli business domains under the locally authorized user identity, while raw `api`, account/config commands, arbitrary Shell, and paths outside `HERMES_HOME` remain unavailable. Document the exit-10 approval retry and state that API scopes and Feishu visibility still constrain results.

- [ ] **Step 2: Run static and full automated verification**

Run from `hermes/MCP`:

```powershell
python -m pytest -v
python -m ruff check src/hermes_mcp/lark_cli_full.py src/hermes_mcp/backends/lark_cli_full.py tests/test_lark_cli_full.py
python -m compileall -q src/hermes_mcp
```

Run from the project root:

```powershell
python -m pytest backend/tests/test_local_ai_runtime.py -v
```

Expected: zero failures and zero Ruff errors.

- [ ] **Step 3: Exercise the MCP without mutating Feishu**

Run:

```powershell
cd D:\Replica1.0\hermes
.\hermes.exe mcp test hermes-lark-cli
```

Verify discovery reports only the three tools. Exercise `lark_cli_help` and `lark_cli_schema`; then use a read-only task, document, or IM shortcut under user identity. Do not execute an actual write during automated acceptance.

- [ ] **Step 4: Restart and inspect the local AI stack**

Run only after checking port ownership through the provided status command:

```powershell
cd D:\Replica1.0\deploy
.\scripts\status-local-ai.ps1
.\scripts\stop-local-ai.ps1
.\scripts\start-local-ai.ps1
.\scripts\status-local-ai.ps1
```

Expected: Agent gateway, Knowledge gateway, backend, and frontend are healthy; Agent MCP discovery includes `hermes-lark-cli`; Knowledge remains `no_mcp`. If services were not started by the project scripts, do not stop unrelated listeners.

- [ ] **Step 5: Review the approved specification line by line**

Confirm coverage of all three tools, every approved business domain, user identity, Shell prohibition, raw API/management command denial, path and output limits, redaction, confirmation ticket single use, Agent/Knowledge isolation, documentation, and live read-only exercise. Report any external limitation such as missing scope or inaccessible resource as an honest acceptance gap rather than a software success.
