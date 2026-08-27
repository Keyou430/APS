# Local Hermes AI Service Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the local project AI workbench through two loopback-only Hermes HTTP gateways, with Feishu read-only tools available only to general agent conversations.

**Architecture:** A testable Python runtime module owns local process orchestration and secret-safe environment construction; thin PowerShell wrappers expose start, stop, and status commands. The existing platform `HermesHttpClient` connects FastAPI to agent Hermes on port 8642 and tool-less knowledge Hermes on port 8643, while Vite continues proxying `/api` to FastAPI.

**Tech Stack:** Python 3.12, pytest, PowerShell 7, Hermes Agent v0.18, FastAPI/Uvicorn, React/Vite, YAML, Lark CLI user OAuth.

**Environment note:** `D:\Replica1.0` is not a Git repository. Verification checkpoints replace commit steps; do not initialize Git or copy credentials to create artificial commits.

---

## File Map

- Modify `hermes/config.yaml`: allow only the Feishu read-only MCP on the API-server platform.
- Create `hermes/knowledge-home/config.yaml`: isolated DeepSeek knowledge profile with `no_mcp`.
- Create `hermes/knowledge-home/SOUL.md`: concise tool-less knowledge-channel instructions.
- Create `hermes/knowledge-home/.gitignore`: keep generated profile state out of future source control.
- Create `deploy/scripts/local_ai_runtime.py`: dotenv filtering, service specifications, port/PID safety, process lifecycle, and health checks.
- Create `deploy/scripts/start-local-ai.ps1`: thin `start` wrapper.
- Create `deploy/scripts/stop-local-ai.ps1`: thin `stop` wrapper.
- Create `deploy/scripts/status-local-ai.ps1`: thin `status` wrapper.
- Create `backend/tests/test_local_ai_runtime.py`: runtime and profile contract tests.
- Modify `deploy/README.md`: local dual-Hermes runbook and troubleshooting.

## Task 1: Lock the two Hermes profile boundaries

**Files:**
- Modify: `hermes/config.yaml`
- Create: `hermes/knowledge-home/config.yaml`
- Create: `hermes/knowledge-home/SOUL.md`
- Create: `hermes/knowledge-home/.gitignore`
- Test: `backend/tests/test_local_ai_runtime.py`

- [ ] **Step 1: Write the failing profile-boundary test**

Create `backend/tests/test_local_ai_runtime.py` with:

```python
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_agent_api_server_allows_only_feishu_readonly_mcp() -> None:
    config = load_yaml(PROJECT_ROOT / "hermes" / "config.yaml")

    assert config["platform_toolsets"]["api_server"] == [
        "hermes-feishu-readonly"
    ]
    servers = config["mcp_servers"]
    assert set(servers) == {"hermes-feishu-readonly"}
    assert servers["hermes-feishu-readonly"]["enabled"] is True


def test_knowledge_api_server_is_toolless_and_has_no_mcp_servers() -> None:
    config = load_yaml(
        PROJECT_ROOT / "hermes" / "knowledge-home" / "config.yaml"
    )

    assert config["model"] == {
        "default": "deepseek-v4-flash",
        "provider": "deepseek",
    }
    assert config["platform_toolsets"]["api_server"] == ["no_mcp"]
    assert "mcp_servers" not in config
    assert "plugins" not in config
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
cd D:\Replica1.0\backend
py -3.12 -m pytest tests/test_local_ai_runtime.py -v
```

Expected: failure because `platform_toolsets.api_server` and the knowledge profile do not exist.

- [ ] **Step 3: Add the explicit agent allowlist**

Add to `hermes/config.yaml` without changing other platform configuration:

```yaml
platform_toolsets:
  api_server:
    - hermes-feishu-readonly
```

- [ ] **Step 4: Create the tool-less knowledge profile**

Create `hermes/knowledge-home/config.yaml`:

```yaml
model:
  default: deepseek-v4-flash
  provider: deepseek
platform_toolsets:
  api_server:
    - no_mcp
_config_version: 32
```

Create `hermes/knowledge-home/SOUL.md`:

```markdown
# Knowledge Hermes

Answer only from context supplied by the platform. Do not claim access to tools,
external systems, private files, or Feishu. State clearly when supplied context
is insufficient.
```

Create `hermes/knowledge-home/.gitignore`:

```gitignore
*
!.gitignore
!config.yaml
!SOUL.md
```

- [ ] **Step 5: Run the profile tests and verify GREEN**

Run:

```powershell
cd D:\Replica1.0\backend
py -3.12 -m pytest tests/test_local_ai_runtime.py -v
```

Expected: `2 passed`.

## Task 2: Build the secret-safe runtime configuration module

**Files:**
- Create: `deploy/scripts/local_ai_runtime.py`
- Modify: `backend/tests/test_local_ai_runtime.py`

- [ ] **Step 1: Add failing dotenv and service-spec tests**

Append:

```python
import importlib.util
import sys


def load_runtime_module():
    path = PROJECT_ROOT / "deploy" / "scripts" / "local_ai_runtime.py"
    spec = importlib.util.spec_from_file_location("local_ai_runtime", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_reads_only_approved_secrets(tmp_path: Path) -> None:
    module = load_runtime_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "DEEPSEEK_API_KEY=deepseek-secret",
                "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1",
                "HERMES_API_SERVER_KEY=hermes-secret",
                "PLATFORM_FEISHU_APP_SECRET=must-not-be-loaded",
                "POSTGRES_PASSWORD=must-not-be-loaded",
            )
        ),
        encoding="utf-8",
    )

    values = module.load_runtime_secrets(env_file)

    assert values == {
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "HERMES_API_SERVER_KEY": "hermes-secret",
    }


def test_runtime_rejects_missing_or_placeholder_secrets(tmp_path: Path) -> None:
    module = load_runtime_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=change-this-key\nHERMES_API_SERVER_KEY=\n",
        encoding="utf-8",
    )

    with pytest.raises(module.RuntimeConfigurationError, match="required runtime secret"):
        module.load_runtime_secrets(env_file)


def test_service_specs_keep_secrets_out_of_frontend_and_backend_model_env() -> None:
    module = load_runtime_module()
    specs = module.build_service_specs(
        PROJECT_ROOT,
        {
            "DEEPSEEK_API_KEY": "deepseek-secret",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
            "HERMES_API_SERVER_KEY": "hermes-secret",
        },
    )

    assert set(specs) == {"hermes-agent", "hermes-knowledge", "backend", "frontend"}
    assert specs["hermes-agent"].environment["API_SERVER_PORT"] == "8642"
    assert specs["hermes-knowledge"].environment["API_SERVER_PORT"] == "8643"
    assert specs["backend"].environment["HERMES_USE_HTTP"] == "true"
    assert specs["backend"].environment["HERMES_API_URL"] == "http://127.0.0.1:8642"
    assert specs["backend"].environment["HERMES_KNOWLEDGE_API_URL"] == (
        "http://127.0.0.1:8643"
    )
    assert "DEEPSEEK_API_KEY" not in specs["backend"].environment
    assert "HERMES_API_KEY" not in specs["frontend"].environment
    assert "DEEPSEEK_API_KEY" not in specs["frontend"].environment
```

Also add `import pytest` at the top.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
cd D:\Replica1.0\backend
py -3.12 -m pytest tests/test_local_ai_runtime.py -v
```

Expected: import failure because `local_ai_runtime.py` does not exist.

- [ ] **Step 3: Implement dotenv parsing and immutable service specifications**

Create `deploy/scripts/local_ai_runtime.py` with these public contracts:

```python
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


APPROVED_ENV_KEYS = frozenset(
    {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "HERMES_API_SERVER_KEY"}
)
REQUIRED_SECRET_KEYS = ("DEEPSEEK_API_KEY", "HERMES_API_SERVER_KEY")
PLACEHOLDER_PREFIXES = ("change-this", "replace-with", "your-")


class RuntimeConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    command: tuple[str, ...]
    cwd: Path
    port: int
    health_url: str
    environment: dict[str, str]
    process_markers: tuple[str, ...]


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in APPROVED_ENV_KEYS:
            values[name] = value.strip().strip('"').strip("'")
    return values


def load_runtime_secrets(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeConfigurationError("deploy/.env is required")
    values = parse_dotenv(path)
    for name in REQUIRED_SECRET_KEYS:
        value = values.get(name, "")
        if not value or value.lower().startswith(PLACEHOLDER_PREFIXES):
            raise RuntimeConfigurationError(f"required runtime secret is invalid: {name}")
    values.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    return values
```

Implement `build_service_specs(project_root, secrets)` so:

- both Hermes commands use `hermes/hermes.exe gateway run --force`;
- both bind `API_SERVER_HOST=127.0.0.1` and set `API_SERVER_ENABLED=true`;
- the agent uses `HERMES_HOME=hermes` and port 8642;
- knowledge uses `HERMES_HOME=hermes/knowledge-home` and port 8643;
- FastAPI uses `backend/.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000` with `HERMES_USE_HTTP=true`, both URLs, and `HERMES_API_KEY`;
- Vite uses `node.exe web-platform/node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173` and receives no secret values. Launching Node directly makes the PID file identify the real listener instead of an `npm.cmd` parent process.

All service environments begin with `os.environ.copy()` and then receive only the service-specific approved values. Set `PYTHONUTF8=1` on Python/Hermes services.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
cd D:\Replica1.0\backend
py -3.12 -m pytest tests/test_local_ai_runtime.py -v
```

Expected: all profile, dotenv, and service-spec tests pass.

## Task 3: Implement fail-closed start lifecycle

**Files:**
- Modify: `deploy/scripts/local_ai_runtime.py`
- Modify: `backend/tests/test_local_ai_runtime.py`
- Create: `deploy/scripts/start-local-ai.ps1`

- [ ] **Step 1: Add failing port and rollback tests**

Append tests using dependency injection:

```python
def test_start_rejects_busy_port_without_launching(tmp_path: Path) -> None:
    module = load_runtime_module()
    launched: list[str] = []

    with pytest.raises(module.RuntimeConfigurationError, match="port 8642"):
        module.start_services(
            {"hermes-agent": module.ServiceSpec(
                name="hermes-agent",
                command=("hermes.exe", "gateway", "run"),
                cwd=tmp_path,
                port=8642,
                health_url="http://127.0.0.1:8642/health",
                environment={},
                process_markers=("hermes.exe", "gateway", "run"),
            )},
            runtime_dir=tmp_path / "runtime",
            listener_lookup=lambda port: 777 if port == 8642 else None,
            launcher=lambda spec, stdout, stderr: launched.append(spec.name),
        )

    assert launched == []


def test_start_rolls_back_only_processes_created_by_this_run(tmp_path: Path) -> None:
    module = load_runtime_module()
    stopped: list[int] = []
    specs = {
        name: module.ServiceSpec(
            name=name,
            command=(f"{name}.exe",),
            cwd=tmp_path,
            port=port,
            health_url=f"http://127.0.0.1:{port}/health",
            environment={},
            process_markers=(f"{name}.exe",),
        )
        for name, port in (("one", 18001), ("two", 18002))
    }
    pids = iter((101, 102))

    with pytest.raises(module.RuntimeConfigurationError, match="two did not become healthy"):
        module.start_services(
            specs,
            runtime_dir=tmp_path / "runtime",
            listener_lookup=lambda port: None,
            launcher=lambda spec, stdout, stderr: next(pids),
            health_probe=lambda url, timeout: url.endswith("18001/health"),
            stopper=lambda pid: stopped.append(pid),
        )

    assert stopped == [102, 101]
```

- [ ] **Step 2: Run and verify RED**

Expected: `start_services` is missing.

- [ ] **Step 3: Implement safe start helpers**

Add:

```python
def find_listener_pid(port: int) -> int | None:
    script = (
        "$c=Get-NetTCPConnection -State Listen -LocalPort "
        f"{port} -ErrorAction SilentlyContinue | Select-Object -First 1;"
        "if($c){$c.OwningProcess}"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def probe_health(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False
```

Implement `start_services` with this order:

1. Check every requested port before launching anything.
2. Create `deploy/.runtime/local-ai` and open per-service UTF-8 log files.
3. Launch with `subprocess.Popen(..., creationflags=subprocess.CREATE_NO_WINDOW)` on Windows.
4. Write only the decimal PID to `<name>.pid`.
5. Poll each health URL for up to 45 seconds.
6. On failure, stop created PIDs in reverse order and retain logs.

Do not include environment dictionaries, command environments, or secret values in exceptions or logs.

- [ ] **Step 4: Add the thin PowerShell start wrapper**

Create `deploy/scripts/start-local-ai.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "local_ai_runtime.py"
& py -3.12 $Script start
exit $LASTEXITCODE
```

- [ ] **Step 5: Run tests and verify GREEN**

Run the focused test file, then:

```powershell
py -3.12 -m py_compile D:\Replica1.0\deploy\scripts\local_ai_runtime.py
```

Expected: tests pass and compilation exits 0.

## Task 4: Implement identity-safe stop and status

**Files:**
- Modify: `deploy/scripts/local_ai_runtime.py`
- Modify: `backend/tests/test_local_ai_runtime.py`
- Create: `deploy/scripts/stop-local-ai.ps1`
- Create: `deploy/scripts/status-local-ai.ps1`

- [ ] **Step 1: Add failing PID identity tests**

Append:

```python
def test_stop_refuses_reused_pid_with_wrong_command(tmp_path: Path) -> None:
    module = load_runtime_module()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "hermes-agent.pid").write_text("123", encoding="ascii")
    stopped: list[int] = []

    result = module.stop_service(
        "hermes-agent",
        ("hermes.exe", "gateway", "run"),
        runtime_dir=runtime_dir,
        process_command=lambda pid: "unrelated.exe --serve",
        stopper=lambda pid: stopped.append(pid),
    )

    assert result.state == "stale"
    assert stopped == []
    assert not (runtime_dir / "hermes-agent.pid").exists()


def test_status_reports_health_without_exposing_environment(tmp_path: Path) -> None:
    module = load_runtime_module()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "backend.pid").write_text("456", encoding="ascii")

    result = module.service_status(
        "backend",
        port=8000,
        health_url="http://127.0.0.1:8000/health",
        markers=("python.exe", "uvicorn"),
        runtime_dir=runtime_dir,
        process_command=lambda pid: "python.exe -m uvicorn main:app",
        health_probe=lambda url, timeout: True,
    )

    assert result.as_dict() == {"name": "backend", "pid": 456, "state": "healthy"}
```

- [ ] **Step 2: Run and verify RED**

Expected: `stop_service` and `service_status` are missing.

- [ ] **Step 3: Implement process identity lookup and termination**

Use `Get-CimInstance Win32_Process -Filter "ProcessId=<pid>"` with `ConvertTo-Json -Compress` to obtain executable path and command line. Match all normalized `process_markers` before calling `Stop-Process -Id <pid>`.

`stop_service` must:

- reject invalid or non-decimal PID files;
- remove a stale PID file when the process no longer exists;
- refuse and clean only the PID file when markers do not match;
- stop and wait for the matching process, then remove its PID file;
- never recursively enumerate or terminate processes not recorded by this runtime.

`service_status` returns `healthy`, `unhealthy`, `stopped`, or `stale` and never includes command lines or environment values.

- [ ] **Step 4: Wire CLI subcommands and wrappers**

Add argparse subcommands `start`, `stop`, and `status`. `status` prints one JSON object containing the four service states and returns nonzero unless all are healthy.

Create `deploy/scripts/stop-local-ai.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "local_ai_runtime.py"
& py -3.12 $Script stop
exit $LASTEXITCODE
```

Create `deploy/scripts/status-local-ai.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "local_ai_runtime.py"
& py -3.12 $Script status
exit $LASTEXITCODE
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
cd D:\Replica1.0\backend
py -3.12 -m pytest tests/test_local_ai_runtime.py -v
```

Expected: all local runtime tests pass.

## Task 5: Add dependency bootstrap, database preparation, and runbook

**Files:**
- Modify: `deploy/scripts/local_ai_runtime.py`
- Modify: `backend/tests/test_local_ai_runtime.py`
- Modify: `deploy/README.md`

- [ ] **Step 1: Add failing command-order and redaction tests**

Test that `prepare_local_dependencies` emits these commands in order when artifacts are absent:

```text
py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
backend/.venv/Scripts/alembic.exe upgrade head
backend/.venv/Scripts/python.exe seed.py
npm.cmd ci
```

Also test that rendered status and raised exceptions never contain the fixture values `deepseek-secret` or `hermes-secret`.

- [ ] **Step 2: Run and verify RED**

Expected: dependency preparation API is missing.

- [ ] **Step 3: Implement idempotent preparation**

Implement preparation so:

- venv creation and `pip install` run only when `backend/.venv/Scripts/python.exe` is absent;
- `npm ci` runs only when `web-platform/node_modules` is absent;
- Alembic and seed run on every start before Uvicorn;
- preparation subprocesses use `check=True` and inherited console output without secret environment values;
- SQLite remains the local database because no `DATABASE_URL` is injected into FastAPI.

- [ ] **Step 4: Document the local workflow**

Add to `deploy/README.md`:

```powershell
cd D:\Replica1.0\deploy
.\scripts\start-local-ai.ps1
.\scripts\status-local-ai.ps1
.\scripts\stop-local-ai.ps1
```

Document URLs `5173`, `8000`, `8642`, and `8643`; state that `deploy/.env` is the only secret source; describe port-conflict behavior and log location; explicitly state that only the agent gateway has Feishu read-only MCP tools.

- [ ] **Step 5: Run focused and existing deployment tests**

Run:

```powershell
cd D:\Replica1.0\backend
py -3.12 -m pytest tests/test_local_ai_runtime.py tests/test_deploy_startup_scripts.py -q
```

Expected: all pass.

## Task 6: Start and verify the complete local stack

**Files:**
- Verify only; do not write secrets or chat content to source-controlled files.

- [ ] **Step 1: Run static and automated verification**

Run:

```powershell
cd D:\Replica1.0\backend
py -3.12 -m pytest -q
py -3.12 -m ruff check app tests scripts

cd D:\Replica1.0\hermes\MCP
$env:PYTHONPATH = "src"
python -m pytest -q
python -m ruff check src/hermes_mcp/backends/lark_cli.py src/hermes_mcp/feishu_readonly.py tests/test_feishu_readonly.py
```

Expected: project tests and Feishu MCP tests pass. If unrelated baseline failures exist, record them separately and do not call the integration complete until the affected integration suites pass.

- [ ] **Step 2: Start the stack**

Run:

```powershell
cd D:\Replica1.0\deploy
.\scripts\start-local-ai.ps1
.\scripts\status-local-ai.ps1
```

Expected: four services report `healthy`; ports bind only to `127.0.0.1`.

- [ ] **Step 3: Probe Hermes capabilities and tool isolation**

Load only `HERMES_API_SERVER_KEY` from `deploy/.env` into the current process, then call:

```powershell
Invoke-RestMethod http://127.0.0.1:8642/health
Invoke-RestMethod http://127.0.0.1:8643/health
Invoke-RestMethod http://127.0.0.1:8642/v1/toolsets -Headers @{ Authorization = "Bearer $env:HERMES_API_KEY" }
Invoke-RestMethod http://127.0.0.1:8643/v1/toolsets -Headers @{ Authorization = "Bearer $env:HERMES_API_KEY" }
```

Expected: agent toolsets expose only `hermes-feishu-readonly`; knowledge exposes no MCP server. Do not print the authorization header.

- [ ] **Step 4: Verify direct real inference**

Run `backend/scripts/probe_hermes.py` with `HERMES_API_URL=http://127.0.0.1:8642` and the runtime API key, first without `--exercise`, then with `--exercise` and a harmless prompt. Repeat the capability probe against port 8643 without requesting tools.

Expected: health, responses, stateful run, SSE, history, stop, and approval capabilities pass; a real DeepSeek response is returned.

- [ ] **Step 5: Verify the project API and browser AI workbench**

Open `http://127.0.0.1:5173`, sign in with the local seed administrator, create an agent conversation, and send a harmless ordinary prompt. Confirm the backend log shows the Hermes HTTP boundary rather than the compatibility mock and the UI renders the streamed answer.

- [ ] **Step 6: Verify Feishu read-only calls through the project conversation**

In the same agent conversation:

1. Ask Hermes to list groups available to the authorized Feishu account.
2. Ask for one page of recent messages from one returned group.
3. Ask for a bounded keyword search in that group.

Confirm tool events name only the three read-only tools. Confirm no send/reply/forward/revoke/download request occurs and no private chat is read.

- [ ] **Step 7: Verify knowledge isolation**

Create a knowledge conversation and ask it to list Feishu groups. Expected: it states that it has no Feishu/tool access; no MCP tool event appears.

- [ ] **Step 8: Leave the runnable result and report residual limits**

Keep the four services running and provide:

- application URL `http://127.0.0.1:5173`;
- backend URL `http://127.0.0.1:8000`;
- verification counts and live-probe results;
- log directory `D:\Replica1.0\deploy\.runtime\local-ai`;
- remaining platform limits: Feishu retention, deleted messages, private chats, attachments, and reactions remain unavailable.
