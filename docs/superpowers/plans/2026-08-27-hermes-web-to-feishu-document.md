# Hermes Web-to-Feishu Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Agent Hermes to search the web, synthesize normal document text, and create or update a Feishu document when the user explicitly requests a write.

**Architecture:** Add Hermes' built-in `web` toolset beside the existing controlled `hermes-lark-cli` MCP in the Agent API profile. Encode the cross-tool workflow and write-intent boundary in the Agent profile instructions while leaving Knowledge Hermes toolless. Reuse the platform's existing Web evidence parser and the existing lark-cli document write path.

**Tech Stack:** Hermes Agent config YAML, Hermes SOUL instructions, pytest, PowerShell local runtime manager, FastMCP/lark-cli.

---

### Task 1: Agent capability contract

**Files:**
- Modify: `backend/tests/test_local_ai_runtime.py`
- Modify: `hermes/config.yaml`

- [ ] **Step 1: Write the failing configuration test**

Change the expected Agent API toolsets to exactly:

```python
assert config["platform_toolsets"]["api_server"] == [
    "web",
    "hermes-lark-cli",
]
```

Keep the assertions that the Knowledge profile remains `no_mcp` and that `hermes-lark-cli` is the only MCP server.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest backend/tests/test_local_ai_runtime.py::test_agent_api_server_allows_only_lark_cli_mcp -v`

Expected: FAIL because the current list contains only `hermes-lark-cli`.

- [ ] **Step 3: Add the Web toolset to the Agent profile**

Set:

```yaml
platform_toolsets:
  api_server:
    - web
    - hermes-lark-cli
```

Do not enable browser, terminal, file, or code execution.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the same pytest command and expect one passing test.

### Task 2: Web-to-document behavior policy

**Files:**
- Modify: `backend/tests/test_local_ai_runtime.py`
- Modify: `hermes/SOUL.md`

- [ ] **Step 1: Write failing profile-policy tests**

Add a test which reads `hermes/SOUL.md` and asserts the instructions contain these exact behavioral markers:

```python
for marker in (
    "web_search",
    "web_extract",
    "docs +create",
    "docs +update",
    "参考来源",
    "明确要求写入",
    "不得创建或更新飞书文档",
):
    assert marker in instructions
```

Also retain the existing exact-content Knowledge SOUL test so external tools remain unavailable there.

- [ ] **Step 2: Run the policy test and verify RED**

Run: `python -m pytest backend/tests/test_local_ai_runtime.py -k profile -v`

Expected: FAIL because the Agent SOUL does not yet define the workflow.

- [ ] **Step 3: Add concise Agent workflow instructions**

Extend `hermes/SOUL.md` with a section that requires:

- `web_search` followed by `web_extract` when source detail is needed;
- normal title, paragraph, and list text in the document body;
- a final `参考来源` section containing only actually retrieved URLs;
- `docs +create` for a new document and `docs +update` for an identified document;
- no document mutation for search-only or draft-only requests;
- no fabricated citations when Web search is unavailable.

- [ ] **Step 4: Run the policy tests and verify GREEN**

Run the same pytest selection and expect all selected tests to pass.

### Task 3: Static regression verification and documentation

**Files:**
- Modify: `hermes/MCP/README.md`
- Test: `backend/tests/test_local_ai_runtime.py`
- Test: `backend/tests/test_hermes_web_contract.py`
- Test: `hermes/MCP/tests/test_lark_cli_full.py`

- [ ] **Step 1: Document the two-toolset workflow**

State that the three lark-cli tools are generic Feishu control tools, while Web search is a separate built-in Hermes toolset. Document that generated prose is written as document content and URLs are retained as references.

- [ ] **Step 2: Run relevant automated tests**

Run:

```powershell
python -m pytest backend/tests/test_local_ai_runtime.py backend/tests/test_hermes_web_contract.py hermes/MCP/tests/test_lark_cli_full.py -v
```

Expected: zero failures.

- [ ] **Step 3: Validate YAML and whitespace**

Run a UTF-8 Python YAML load of `hermes/config.yaml` and `hermes/knowledge-home/config.yaml`, then run `git diff --check` only if Git metadata exists. Expected: both YAML documents parse and no whitespace errors are reported.

### Task 4: Runtime activation and read-only live acceptance

**Files:**
- Runtime: `hermes/config.yaml`
- Runtime manager: `deploy/scripts/local_ai_runtime.py`

- [ ] **Step 1: Confirm process ownership and current status**

Run: `python deploy/scripts/local_ai_runtime.py status`

Proceed only when the Agent PID belongs to the runtime manager's recorded service.

- [ ] **Step 2: Restart only the managed local stack**

Run:

```powershell
python deploy/scripts/local_ai_runtime.py stop
python deploy/scripts/local_ai_runtime.py start
python deploy/scripts/local_ai_runtime.py status
```

Expected: Agent, Knowledge, backend, and frontend report healthy.

- [ ] **Step 3: Verify the live Agent toolset boundary**

Call the authenticated `/v1/toolsets` endpoint without printing the key. Assert `web.enabled == true`, and assert browser, terminal, file, and code execution are disabled. Verify `hermes mcp test hermes-lark-cli` still discovers exactly the three controlled Feishu tools.

- [ ] **Step 4: Run a harmless Web search smoke**

Submit an Agent request that searches for a stable public fact and returns cited text without asking for a Feishu write. Require a Web tool event and at least one valid `http` or `https` source. If no provider can execute, report the provider configuration as an external blocker rather than claiming completion.

- [ ] **Step 5: Preserve the real-write boundary**

Do not create or update a real Feishu document during automated acceptance because no destination or substantive document topic was supplied. Verify Feishu write capability through MCP discovery, existing document-read smoke, and automated adapter tests; perform a real document write only for a later explicit content request.
