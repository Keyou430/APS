from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

APPROVED_ENV_KEYS = frozenset(
    {
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "HERMES_API_SERVER_KEY",
        "HERMES_HTTP_TIMEOUT_SECONDS",
    }
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
    port: int | None
    health_url: str | None
    environment: dict[str, str] = field(repr=False)
    process_markers: tuple[str, ...]


@dataclass(frozen=True)
class ServiceState:
    name: str
    pid: int | None
    state: str

    def as_dict(self) -> dict[str, str | int | None]:
        return {"name": self.name, "pid": self.pid, "state": self.state}


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
            raise RuntimeConfigurationError(
                f"required runtime secret is invalid: {name}"
            )
    values.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    return values


def _base_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        *APPROVED_ENV_KEYS,
        "API_SERVER_KEY",
        "DATABASE_URL",
        "HERMES_API_KEY",
    ):
        environment.pop(name, None)
    return environment


def _hermes_environment(
    *,
    home: Path,
    port: int,
    secrets: Mapping[str, str],
) -> dict[str, str]:
    environment = _base_environment()
    environment.update(
        {
            "API_SERVER_ENABLED": "true",
            "API_SERVER_HOST": "127.0.0.1",
            "API_SERVER_KEY": secrets["HERMES_API_SERVER_KEY"],
            "API_SERVER_PORT": str(port),
            "DEEPSEEK_API_KEY": secrets["DEEPSEEK_API_KEY"],
            "DEEPSEEK_BASE_URL": secrets.get(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
            ),
            "HERMES_HOME": str(home),
            "PYTHONUTF8": "1",
        }
    )
    return environment


def build_service_specs(
    project_root: Path,
    secrets: Mapping[str, str],
) -> dict[str, ServiceSpec]:
    project_root = project_root.resolve()
    hermes_home = project_root / "hermes"
    knowledge_home = hermes_home / "knowledge-home"
    backend_home = project_root / "backend"
    frontend_home = project_root / "web-platform"

    hermes_executable = hermes_home / "hermes.exe"
    hermes_command = (str(hermes_executable), "gateway", "run", "--force")
    hermes_markers = ("hermes.exe", "gateway", "run", "--force")

    backend_environment = _base_environment()
    backend_environment.update(
        {
            "HERMES_API_KEY": secrets["HERMES_API_SERVER_KEY"],
            "HERMES_API_URL": "http://127.0.0.1:8642",
            "HERMES_KNOWLEDGE_API_URL": "http://127.0.0.1:8643",
            "HERMES_HTTP_TIMEOUT_SECONDS": secrets.get(
                "HERMES_HTTP_TIMEOUT_SECONDS", "180"
            ),
            "HERMES_USE_HTTP": "true",
            "PYTHONUTF8": "1",
        }
    )
    worker_environment = backend_environment.copy()

    frontend_environment = _base_environment()

    return {
        "hermes-agent": ServiceSpec(
            name="hermes-agent",
            command=hermes_command,
            cwd=hermes_home,
            port=8642,
            health_url="http://127.0.0.1:8642/health",
            environment=_hermes_environment(
                home=hermes_home,
                port=8642,
                secrets=secrets,
            ),
            process_markers=hermes_markers,
        ),
        "hermes-knowledge": ServiceSpec(
            name="hermes-knowledge",
            command=hermes_command,
            cwd=hermes_home,
            port=8643,
            health_url="http://127.0.0.1:8643/health",
            environment=_hermes_environment(
                home=knowledge_home,
                port=8643,
                secrets=secrets,
            ),
            process_markers=hermes_markers,
        ),
        "backend": ServiceSpec(
            name="backend",
            command=(
                str(backend_home / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ),
            cwd=backend_home,
            port=8000,
            health_url="http://127.0.0.1:8000/health",
            environment=backend_environment,
            process_markers=("python.exe", "uvicorn", "main:app", "8000"),
        ),
        "pipeline-worker": ServiceSpec(
            name="pipeline-worker",
            command=(
                str(backend_home / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "app.workers.pipeline_worker",
            ),
            cwd=backend_home,
            port=None,
            health_url=None,
            environment=worker_environment,
            process_markers=("python.exe", "app.workers.pipeline_worker"),
        ),
        "pipeline-approval-worker": ServiceSpec(
            name="pipeline-approval-worker",
            command=(
                str(backend_home / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "app.workers.pipeline_approval_worker",
            ),
            cwd=backend_home,
            port=None,
            health_url=None,
            environment=worker_environment.copy(),
            process_markers=(
                "python.exe",
                "app.workers.pipeline_approval_worker",
            ),
        ),
        "frontend": ServiceSpec(
            name="frontend",
            command=(
                "node.exe",
                str(frontend_home / "node_modules" / "vite" / "bin" / "vite.js"),
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
            ),
            cwd=frontend_home,
            port=5173,
            health_url="http://127.0.0.1:5173/",
            environment=frontend_environment,
            process_markers=("node.exe", "vite", "5173"),
        ),
    }


def find_listener_pid(port: int) -> int | None:
    script = (
        "$connection=Get-NetTCPConnection -State Listen -LocalPort "
        f"{port} -ErrorAction SilentlyContinue | Select-Object -First 1;"
        "if($connection){$connection.OwningProcess}"
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


def launch_service(spec: ServiceSpec, stdout: IO[str], stderr: IO[str]):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.Popen(
        spec.command,
        cwd=spec.cwd,
        env=spec.environment,
        stdout=stdout,
        stderr=stderr,
        creationflags=creationflags,
    )


def terminate_process(pid: int) -> None:
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-Command",
            f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue",
        ],
        capture_output=True,
        check=False,
    )


def _process_id(process: object) -> int:
    value = getattr(process, "pid", process)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeConfigurationError("service launcher did not return a valid PID")
    return value


def _wait_until_healthy(
    url: str,
    *,
    timeout: float,
    health_probe: Callable[[str, float], bool],
) -> bool:
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        remaining = max(deadline - time.monotonic(), 0)
        if health_probe(url, min(max(remaining, 0.1), 2.0)):
            return True
        if remaining <= 0:
            return False
        time.sleep(min(0.25, remaining))


def start_services(
    specs: Mapping[str, ServiceSpec],
    *,
    runtime_dir: Path,
    listener_lookup: Callable[[int], int | None] = find_listener_pid,
    launcher: Callable[[ServiceSpec, IO[str], IO[str]], object] = launch_service,
    health_probe: Callable[[str, float], bool] = probe_health,
    stopper: Callable[[int], None] = terminate_process,
    health_timeout: float = 45.0,
) -> dict[str, int]:
    for spec in specs.values():
        if spec.port is not None and listener_lookup(spec.port) is not None:
            raise RuntimeConfigurationError(
                f"port {spec.port} is already in use; no services were started"
            )

    runtime_dir.mkdir(parents=True, exist_ok=True)
    created: list[tuple[str, int]] = []
    try:
        for name, spec in specs.items():
            log_path = runtime_dir / f"{name}.log"
            try:
                with log_path.open("a", encoding="utf-8", buffering=1) as log:
                    process = launcher(spec, log, log)
                pid = _process_id(process)
            # The launcher is injectable; discard arbitrary exception text at this boundary.
            except Exception:  # noqa: BLE001
                raise RuntimeConfigurationError(f"{name} failed to launch") from None

            (runtime_dir / f"{name}.pid").write_text(str(pid), encoding="ascii")
            created.append((name, pid))

            if spec.health_url is not None and not _wait_until_healthy(
                    spec.health_url,
                    timeout=health_timeout,
                    health_probe=health_probe,
                ):
                raise RuntimeConfigurationError(f"{name} did not become healthy")
    except Exception:
        for name, pid in reversed(created):
            stopper(pid)
            (runtime_dir / f"{name}.pid").unlink(missing_ok=True)
        raise

    return dict(created)


def get_process_command(pid: int) -> str | None:
    script = (
        "$process=Get-CimInstance Win32_Process -Filter \"ProcessId="
        f"{pid}\" -ErrorAction SilentlyContinue;"
        "if($process){@{ExecutablePath=$process.ExecutablePath;"
        "CommandLine=$process.CommandLine}|ConvertTo-Json -Compress}"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    raw = result.stdout.strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    executable = payload.get("ExecutablePath") or ""
    command_line = payload.get("CommandLine") or ""
    command = f"{executable} {command_line}".strip()
    return command or None


def _command_matches(command: str, markers: tuple[str, ...]) -> bool:
    normalized = " ".join(command.casefold().replace("/", "\\").split())
    return all(
        " ".join(marker.casefold().replace("/", "\\").split()) in normalized
        for marker in markers
    )


def _read_recorded_pid(pid_path: Path) -> tuple[int | None, bool]:
    if not pid_path.is_file():
        return None, False
    try:
        raw = pid_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        pid_path.unlink(missing_ok=True)
        return None, True
    if not raw.isdecimal() or int(raw) <= 0:
        pid_path.unlink(missing_ok=True)
        return None, True
    return int(raw), False


def stop_service(
    name: str,
    markers: tuple[str, ...],
    *,
    runtime_dir: Path,
    process_command: Callable[[int], str | None] = get_process_command,
    stopper: Callable[[int], None] = terminate_process,
    stop_timeout: float = 10.0,
) -> ServiceState:
    pid_path = runtime_dir / f"{name}.pid"
    pid, invalid = _read_recorded_pid(pid_path)
    if invalid:
        return ServiceState(name=name, pid=None, state="stale")
    if pid is None:
        return ServiceState(name=name, pid=None, state="stopped")

    command = process_command(pid)
    if command is None or not _command_matches(command, markers):
        pid_path.unlink(missing_ok=True)
        return ServiceState(name=name, pid=pid, state="stale")

    stopper(pid)
    deadline = time.monotonic() + max(stop_timeout, 0)
    while process_command(pid) is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeConfigurationError(f"{name} did not stop")
        time.sleep(min(0.1, remaining))
    pid_path.unlink(missing_ok=True)
    return ServiceState(name=name, pid=pid, state="stopped")


def service_status(
    name: str,
    *,
    port: int | None,
    health_url: str | None,
    markers: tuple[str, ...],
    runtime_dir: Path,
    process_command: Callable[[int], str | None] = get_process_command,
    health_probe: Callable[[str, float], bool] = probe_health,
) -> ServiceState:
    del port
    pid_path = runtime_dir / f"{name}.pid"
    pid, invalid = _read_recorded_pid(pid_path)
    if invalid:
        return ServiceState(name=name, pid=None, state="stale")
    if pid is None:
        return ServiceState(name=name, pid=None, state="stopped")

    command = process_command(pid)
    if command is None or not _command_matches(command, markers):
        pid_path.unlink(missing_ok=True)
        return ServiceState(name=name, pid=pid, state="stale")

    state = (
        "healthy"
        if health_url is None or health_probe(health_url, 2.0)
        else "unhealthy"
    )
    return ServiceState(name=name, pid=pid, state=state)


def _lifecycle_specs(project_root: Path) -> dict[str, ServiceSpec]:
    return build_service_specs(
        project_root,
        {
            "DEEPSEEK_API_KEY": "not-loaded",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
            "HERMES_API_SERVER_KEY": "not-loaded",
        },
    )


def _dependency_environment() -> dict[str, str]:
    environment = _base_environment()
    sensitive_fragments = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    for name in tuple(environment):
        upper_name = name.upper()
        if any(fragment in upper_name for fragment in sensitive_fragments):
            environment.pop(name, None)
    environment["PYTHONUTF8"] = "1"
    return environment


def run_preparation_command(
    command: Sequence[str], cwd: Path, environment: Mapping[str, str]
) -> None:
    subprocess.run(
        tuple(command),
        cwd=cwd,
        env=dict(environment),
        check=True,
    )


def resolve_lark_cli_path() -> str:
    """Resolve the npm launcher to lark-cli's native executable on Windows."""

    configured = shutil.which("lark-cli") or shutil.which("lark-cli.cmd")
    if not configured:
        return "lark-cli"
    resolved = Path(configured)
    if resolved.suffix.casefold() == ".exe":
        return str(resolved)
    native = resolved.parent / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe"
    return str(native) if native.is_file() else str(resolved)


def verify_lark_cli_integration(
    project_root: Path,
    *,
    runner: Callable[..., object] = subprocess.run,
    timeout_seconds: float = 60.0,
) -> None:
    """Fail startup unless auth, MCP registration, and IM access all work."""

    project_root = project_root.resolve()
    hermes_home = project_root / "hermes"
    hermes = hermes_home / "hermes.exe"
    lark_cli = resolve_lark_cli_path()
    environment = _dependency_environment()
    environment["HERMES_HOME"] = str(hermes_home)
    checks = (
        (
            (lark_cli, "auth", "status", "--json", "--verify"),
            project_root,
            "lark-cli user authorization",
        ),
        (
            (str(hermes), "mcp", "test", "hermes-lark-cli"),
            hermes_home,
            "Hermes hermes-lark-cli MCP registration",
        ),
        (
            (lark_cli, "im", "+chat-list", "--as", "user", "--format", "json"),
            project_root,
            "Feishu group chat access",
        ),
    )

    for command, cwd, description in checks:
        try:
            result = runner(
                tuple(command),
                cwd=cwd,
                env=dict(environment),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except Exception:  # noqa: BLE001
            raise RuntimeConfigurationError(f"{description} check failed") from None

        return_code = getattr(result, "returncode", 1)
        stdout = getattr(result, "stdout", "") or ""
        if return_code != 0:
            raise RuntimeConfigurationError(f"{description} check failed")

        if command[1:3] == ("auth", "status"):
            try:
                payload = json.loads(stdout)
            except (TypeError, json.JSONDecodeError):
                raise RuntimeConfigurationError(
                    "lark-cli user authorization check returned invalid JSON"
                ) from None
            identities = payload.get("identities") if isinstance(payload, dict) else None
            user_identity = (
                identities.get("user", {})
                if isinstance(identities, dict)
                else {}
            )
            if not isinstance(user_identity, dict):
                user_identity = {}
            if (
                not isinstance(payload, dict)
                or payload.get("verified") is not True
                or user_identity.get("verified") is not True
                or user_identity.get("tokenStatus") != "valid"
            ):
                raise RuntimeConfigurationError(
                    "lark-cli user authorization is not valid"
                )
        elif command[1:3] == ("mcp", "test"):
            required_tools = (
                "lark_cli_help",
                "lark_cli_schema",
                "lark_cli_execute",
            )
            if "Connected" not in stdout or any(tool not in stdout for tool in required_tools):
                raise RuntimeConfigurationError(
                    "Hermes hermes-lark-cli MCP registration is incomplete"
                )
        else:
            try:
                payload = json.loads(stdout)
            except (TypeError, json.JSONDecodeError):
                raise RuntimeConfigurationError(
                    "Feishu group chat access check returned invalid JSON"
                ) from None
            if (
                not isinstance(payload, dict)
                or payload.get("ok") is not True
                or not isinstance(payload.get("data"), (dict, list))
            ):
                raise RuntimeConfigurationError(
                    "Feishu group chat access check returned an invalid response"
                )


def prepare_local_dependencies(
    project_root: Path,
    *,
    runner: Callable[[Sequence[str], Path, Mapping[str, str]], object] = (
        run_preparation_command
    ),
) -> None:
    backend = project_root / "backend"
    frontend = project_root / "web-platform"
    hermes_home = project_root / "hermes"
    hermes = hermes_home / "hermes.exe"
    venv = backend / ".venv"
    python = venv / "Scripts" / "python.exe"
    alembic = venv / "Scripts" / "alembic.exe"
    environment = _dependency_environment()

    commands: list[tuple[tuple[str, ...], Path, str]] = []
    if not python.is_file():
        commands.extend(
            (
                (
                    ("py", "-3.12", "-m", "venv", str(venv)),
                    project_root,
                    "Python virtual environment creation",
                ),
                (
                    (
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "-r",
                        str(backend / "requirements.txt"),
                    ),
                    project_root,
                    "Python dependency installation",
                ),
            )
        )

    commands.extend(
        (
            (
                (str(hermes), "tools", "post-setup", "ddgs"),
                hermes_home,
                "Hermes Web search dependency installation",
            ),
            ((str(alembic), "upgrade", "head"), backend, "database migration"),
            ((str(python), "seed.py"), backend, "database seed"),
        )
    )
    if not (frontend / "node_modules").is_dir():
        commands.append((("npm.cmd", "ci"), frontend, "frontend dependency installation"))

    for command, cwd, description in commands:
        try:
            runner(command, cwd, environment)
        # Preparation runners may include secrets in errors; expose only the step name.
        except Exception:  # noqa: BLE001
            raise RuntimeConfigurationError(f"{description} failed") from None


def _all_statuses(
    specs: Mapping[str, ServiceSpec], runtime_dir: Path
) -> list[ServiceState]:
    return [
        service_status(
            name,
            port=spec.port,
            health_url=spec.health_url,
            markers=spec.process_markers,
            runtime_dir=runtime_dir,
        )
        for name, spec in specs.items()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the local Hermes AI stack")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    subparsers.add_parser("stop")
    subparsers.add_parser("status")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    runtime_dir = project_root / "deploy" / ".runtime" / "local-ai"

    try:
        if args.command == "start":
            secrets = load_runtime_secrets(project_root / "deploy" / ".env")
            prepare_local_dependencies(project_root)
            verify_lark_cli_integration(project_root)
            specs = build_service_specs(project_root, secrets)
            start_services(specs, runtime_dir=runtime_dir)
            statuses = _all_statuses(specs, runtime_dir)
            print(json.dumps({"services": [item.as_dict() for item in statuses]}))
            return 0

        specs = _lifecycle_specs(project_root)
        if args.command == "stop":
            statuses = [
                stop_service(
                    name,
                    spec.process_markers,
                    runtime_dir=runtime_dir,
                )
                for name, spec in reversed(tuple(specs.items()))
            ]
            print(json.dumps({"services": [item.as_dict() for item in statuses]}))
            return 0

        statuses = _all_statuses(specs, runtime_dir)
        print(json.dumps({"services": [item.as_dict() for item in statuses]}))
        return 0 if all(item.state == "healthy" for item in statuses) else 1
    except RuntimeConfigurationError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
