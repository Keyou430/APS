# Hermes-lark Managed Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable Windows `Hermes-lark` bundle in `D:\Hermes-lark` with one editable YAML file and one command entry point for the Hermes, Web, lark-cli MCP, and Feishu user-authorized runtime.

**Architecture:** A package-local launcher owns a single configuration model and projects it into two isolated Hermes homes. `setup` installs pinned dependencies into `.runtime`, generates portable Hermes/MCP configuration, and never copies source-machine state. `start`, `status`, `stop`, `doctor`, and `feishu-login` expose the only supported operations.

**Tech Stack:** Python 3.11/3.12, PyYAML, PowerShell-compatible Windows launcher, Hermes Agent 0.18.0, lark-cli 1.0.90, FastMCP MCP adapter, `ddgs` Web backend.

---

### Task 1: Package skeleton and single configuration model

**Files:**
- Create: `D:\Hermes-lark\hermes-lark.yaml`
- Create: `D:\Hermes-lark\hermes-lark.cmd`
- Create: `D:\Hermes-lark\src\hermes_lark\__init__.py`
- Create: `D:\Hermes-lark\src\hermes_lark\config.py`
- Create: `D:\Hermes-lark\tests\test_config.py`
- Create: `D:\Hermes-lark\.gitignore`

- [ ] **Step 1: Write failing configuration tests**

Add tests that load the default YAML, accept the documented keys, reject an unknown top-level key, reject unsupported `version`, reject invalid ports, and resolve only environment-variable names without reading secret values into the configuration object.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests\test_config.py -q
```

Expected: collection or import failure because the package does not exist yet.

- [ ] **Step 3: Implement the configuration module**

Implement a typed loader with these exact defaults:

```yaml
version: 1
model:
  provider: deepseek
  name: deepseek-v4-flash
  api_key_env: DEEPSEEK_API_KEY
  base_url: https://api.deepseek.com/v1
server:
  host: 127.0.0.1
  agent_port: 8642
  knowledge_port: 8643
  api_key_env: HERMES_API_SERVER_KEY
web:
  provider: ddgs
feishu:
  enabled: true
  identity: user
security:
  browser: false
  terminal: false
  file: false
  code_execution: false
```

Use UTF-8 reads, field-level validation, and a `resolve_secret(name)` helper that returns only presence/absence and never serializes a secret value.

- [ ] **Step 4: Make the tests pass**

Run the focused command again. Expected: all configuration tests pass.

- [ ] **Step 5: Add package ignore rules**

Ignore `.runtime/`, `.env`, `auth.json`, `*.db`, `*.db-*`, logs, PID/lock files, caches, sessions, memories, uploads, and Python bytecode. Do not ignore the single YAML, launcher, source, templates, MCP source, tests, README, or version manifest.

### Task 2: Portable source collection and dependency manifest

**Files:**
- Create: `D:\Hermes-lark\vendor\versions.json`
- Create: `D:\Hermes-lark\src\hermes_lark\paths.py`
- Create: `D:\Hermes-lark\src\hermes_lark\setup_runtime.py`
- Create: `D:\Hermes-lark\tests\test_packaging.py`

- [ ] **Step 1: Write failing packaging tests**

Test that the source allowlist contains only package-owned runtime inputs, that forbidden names (`auth.json`, `.env`, state/response databases, logs, PID/lock files, absolute `D:\Replica1.0` and `D:\TASK\hermes` paths) are rejected, and that the version manifest contains Hermes `0.18.0` and lark-cli `1.0.90`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests\test_packaging.py -q
```

Expected: missing module or missing manifest failures.

- [ ] **Step 3: Implement path and dependency setup logic**

Use package-relative paths derived from `Path(__file__).resolve().parents[2]`. Implement:

1. A source allowlist that copies only `hermes/MCP/src`, `hermes/MCP/pyproject.toml`, selected MCP tests, `hermes/SOUL.md`, the current Agent/Knowledge config templates, and required launcher documentation.
2. A forbidden-file/path scanner that fails closed before copying.
3. A version manifest with upstream repository, Hermes version, lark-cli npm version, Python constraint, and Web backend.
4. An idempotent setup routine that creates `.runtime/python`, `.runtime/hermes-home`, `.runtime/knowledge-home`, `.runtime/generated`, `.runtime/logs`, and `.runtime/pids`.
5. A dependency installer abstraction. Prefer an existing compatible Hermes installation only after version verification; otherwise install the pinned Hermes package into `.runtime/python` using the available Python package installer. Install the pinned `@larksuite/cli` version through npm into a package-local prefix or verify a compatible system installation through `doctor`.

The installer must not copy the source machine's uv trampoline, user auth cache, or runtime databases.

- [ ] **Step 4: Verify packaging tests**

Run the focused tests and confirm the package scanner passes without reading or copying private runtime files.

### Task 3: Hermes profile generation

**Files:**
- Create: `D:\Hermes-lark\templates\agent-config.yaml`
- Create: `D:\Hermes-lark\templates\knowledge-config.yaml`
- Create: `D:\Hermes-lark\templates\SOUL.md`
- Create: `D:\Hermes-lark\templates\knowledge-SOUL.md`
- Create: `D:\Hermes-lark\src\hermes_lark\generate_profiles.py`
- Create: `D:\Hermes-lark\tests\test_profile_generation.py`

- [ ] **Step 1: Write failing profile tests**

Test generation from a temporary package root. Assert that Agent `platform_toolsets.api_server` is exactly `['web', 'hermes-lark-cli']`, Knowledge is exactly `['no_mcp']`, only `hermes-lark-cli` is registered, all MCP paths are package-relative resolved paths, and no generated file contains source-machine paths or secret values.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests\test_profile_generation.py -q
```

- [ ] **Step 3: Implement generation**

Render two isolated Hermes homes under `.runtime`. The Agent profile must enable Web and the controlled MCP only; browser, terminal, file, and code execution must remain disabled. The generated Agent SOUL must require `web_search`, optional `web_extract`, ordinary prose, a `参考来源` section, explicit write intent before `docs +create`/`docs +update`, and no Feishu mutation for search-only or draft-only requests. Knowledge SOUL must deny external tools.

- [ ] **Step 4: Verify GREEN**

Run the profile tests and a UTF-8 YAML parse of both generated configs.

### Task 4: Unified command entry point

**Files:**
- Modify: `D:\Hermes-lark\hermes-lark.cmd`
- Create: `D:\Hermes-lark\src\hermes_lark\cli.py`
- Create: `D:\Hermes-lark\src\hermes_lark\runtime.py`
- Create: `D:\Hermes-lark\tests\test_cli.py`
- Create: `D:\Hermes-lark\README.md`

- [ ] **Step 1: Write failing CLI tests**

Test command dispatch for `setup`, `feishu-login`, `start`, `status`, `stop`, and `doctor`; test that missing commands print usage and return nonzero; test that status output contains no secret values; test that start calls setup/profile generation before launching services.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests\test_cli.py -q
```

- [ ] **Step 3: Implement the launcher and runtime lifecycle**

`hermes-lark.cmd` must resolve its own directory and invoke the package-local Python entry point. `runtime.py` must reuse the existing PID ownership pattern: inspect command lines before stopping, reject busy ports, wait for health endpoints, roll back only processes created by the current start invocation, and keep secrets out of logs and output. `start` launches Agent and Knowledge Hermes only; this package does not launch Replica backend/frontend.

Document the external HTTP endpoints, environment variables, directory layout, supported commands, and security rules in README.

- [ ] **Step 4: Verify CLI behavior**

Run the CLI tests and a dry `hermes-lark doctor` using a temporary package root.

### Task 5: Feishu authorization and provider diagnostics

**Files:**
- Create: `D:\Hermes-lark\src\hermes_lark\feishu.py`
- Create: `D:\Hermes-lark\src\hermes_lark\doctor.py`
- Create: `D:\Hermes-lark\tests\test_doctor.py`

- [ ] **Step 1: Write failing diagnostic tests**

Test that `feishu-login` invokes lark-cli user authorization with approved domains and never prints token output; test normalization of missing authorization, missing scope, and permission errors; test that `doctor` requires `identity=user`, `verified=true`, and a valid token without exposing identity tokens.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests\test_doctor.py -q
```

- [ ] **Step 3: Implement diagnostics**

Use lark-cli's documented commands: authorization through `auth login --domain ... --no-wait --json` followed by the user-visible completion flow, verification through `auth status --json --verify`, and MCP discovery through `hermes mcp test hermes-lark-cli`. Use relative package paths and safe subprocess argv arrays; do not implement OAuth or token storage in Hermes-lark.

- [ ] **Step 4: Verify GREEN**

Run the tests with fake subprocesses and confirm no credential strings appear in captured output.

### Task 6: Copy the controlled MCP adapter and documentation

**Files:**
- Copy from `D:\Replica1.0\hermes\MCP\src\hermes_mcp\lark_cli_full.py` into `D:\Hermes-lark\mcp\src\hermes_mcp\lark_cli_full.py`
- Copy required adapter modules and `pyproject.toml` into `D:\Hermes-lark\mcp\`
- Create: `D:\Hermes-lark\mcp\README.md`
- Create: `D:\Hermes-lark\tests\test_mcp_bundle.py`

- [ ] **Step 1: Write failing bundle tests**

Test that the copied MCP imports from the package-local source path, discovers exactly three tools, rejects non-business root commands, enforces user identity, and excludes private source paths.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests\test_mcp_bundle.py -q
```

- [ ] **Step 3: Collect and adapt the adapter**

Copy only the modules needed by `hermes_mcp.lark_cli_full`. Replace any hard-coded source-machine paths with runtime-provided paths or environment variables. Preserve no-shell execution, command allowlist, confirmation protocol, bounded output, path restrictions, and redaction. Do not broaden the adapter into arbitrary Shell, raw API, or account-management access.

- [ ] **Step 4: Verify MCP bundle behavior**

Run the package-local MCP tests and invoke the adapter in stdio discovery mode.

### Task 7: End-to-end packaging scan and live acceptance

**Files:**
- Create: `D:\Hermes-lark\scripts\verify-package.ps1`
- Create: `D:\Hermes-lark\tests\test_end_to_end.py`
- Modify: `D:\Hermes-lark\README.md`

- [ ] **Step 1: Write failing acceptance tests**

Test the package scan, generated profile boundaries, no-private-state invariant, and command health behavior with fake services. Include checks for no `auth.json`, `.env`, databases, logs, PID/lock files, absolute source paths, or secret values.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests\test_end_to_end.py -q
```

- [ ] **Step 3: Implement package verification**

`verify-package.ps1` must scan the package and fail closed on forbidden filenames, forbidden path fragments, invalid YAML, missing required distributable files, or unexpected executable/runtime state outside `.runtime`.

- [ ] **Step 4: Run full automated verification**

Run:

```powershell
py -3.12 -m pytest D:\Hermes-lark\tests -q
```

Also run UTF-8 YAML parsing, package-local Ruff/compile checks, and MCP discovery.

- [ ] **Step 5: Perform live acceptance without real Feishu writes**

From `D:\Hermes-lark`, run `setup`, `doctor`, `start`, `status`, the Agent `/v1/toolsets` check, a harmless `web_search` smoke, `lark-cli auth status --json --verify`, `hermes mcp test hermes-lark-cli`, and a `docs +create --dry-run`. Stop the package afterward. Do not create or update a real Feishu document.

- [ ] **Step 6: Finalize README and handoff**

Document first-run prerequisites, required environment variables, the one-time per-user Feishu authorization, HTTP integration settings for consuming platforms, search-only `ddgs` limitations, and the explicit list of files excluded from sharing.

