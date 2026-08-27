import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_agent_api_server_allows_web_and_only_lark_cli_mcp() -> None:
    config = load_yaml(PROJECT_ROOT / "hermes" / "config.yaml")

    assert config["platform_toolsets"]["api_server"] == [
        "web",
        "hermes-lark-cli"
    ]
    assert config["web"] == {"backend": "ddgs"}
    servers = config["mcp_servers"]
    assert set(servers) == {"hermes-lark-cli"}
    assert servers["hermes-lark-cli"]["enabled"] is True
    assert servers["hermes-lark-cli"]["args"] == [
        "-m",
        "hermes_mcp.lark_cli_full",
    ]
    assert servers["hermes-lark-cli"]["env"]["HERMES_HOME"] == str(
        PROJECT_ROOT / "hermes"
    )
    assert servers["hermes-lark-cli"]["env"]["PYTHONPATH"] == str(
        PROJECT_ROOT / "hermes" / "MCP" / "src"
    )
    assert config["gateway"]["platforms"] == {
        "feishu": {"enabled": False},
        "dingtalk": {"enabled": True},
    }
    assert config["plugins"] == {
        "enabled": ["dingtalk-platform"],
        "disabled": ["three-source-retrieval", "hermes-mcp", "feishu-platform"],
        "entries": {
            "three-source-retrieval": {"allow_tool_override": False},
            "hermes-mcp": {"allow_tool_override": False},
        },
    }


def test_knowledge_api_server_is_toolless_and_has_no_mcp_servers() -> None:
    config = load_yaml(
        PROJECT_ROOT / "hermes" / "knowledge-home" / "config.yaml"
    )

    assert config["model"] == {
        "default": "deepseek-v4-flash",
        "provider": "deepseek",
    }
    assert config["platform_toolsets"]["api_server"] == ["no_mcp"]
    assert config["_config_version"] == 32
    assert "mcp_servers" not in config
    assert "plugins" not in config


def test_knowledge_profile_instructions_match_the_runtime_contract() -> None:
    knowledge_home = PROJECT_ROOT / "hermes" / "knowledge-home"

    assert (knowledge_home / "SOUL.md").read_text(encoding="utf-8") == (
        "# Knowledge Hermes\n"
        "\n"
        "Answer only from context supplied by the platform. Do not claim access "
        "to tools,\n"
        "external systems, private files, or Feishu. State clearly when supplied "
        "context\n"
        "is insufficient.\n"
    )
    assert (knowledge_home / ".gitignore").read_text(encoding="utf-8") == (
        "*\n"
        "!.gitignore\n"
        "!config.yaml\n"
        "!SOUL.md\n"
    )


def test_agent_profile_defines_web_to_feishu_document_write_boundary() -> None:
    instructions = (PROJECT_ROOT / "hermes" / "SOUL.md").read_text(
        encoding="utf-8"
    )

    for marker in (
        "web_search",
        "web_extract",
        "docs +create",
        "docs +update",
        "参考来源",
        "明确要求写入",
        "不得创建或更新飞书文档",
        "ddgs 仅支持搜索",
    ):
        assert marker in instructions

    assert "Cite only URLs that the tools actually returned." in instructions
    assert "do not invent citations" in instructions
    assert "a useful title, paragraphs, and lists as appropriate" in instructions
    assert "The body must contain the actual findings" in instructions
    assert "links do not replace the prose" in instructions


def test_mcp_readme_defines_lark_cli_and_web_document_contract() -> None:
    readme = (PROJECT_ROOT / "hermes" / "MCP" / "README.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(readme.split())

    assert (
        "It exposes three control tools (`lark_cli_help`, `lark_cli_schema`, and "
        "`lark_cli_execute`) over the approved lark-cli business domains"
    ) in normalized
    assert (
        "The three lark-cli tools are controlled entry points, not a three-feature limit."
    ) in normalized
    assert "Web research is a separate Hermes built-in toolset." in normalized
    assert "enables `web` beside `hermes-lark-cli`" in normalized
    assert (
        "Hermes synthesizes a title, paragraphs, and lists as the actual document body."
    ) in normalized
    assert "writes that body to a new or identified Feishu document" in normalized
    assert "URLs actually used" in normalized
    assert "URLs support verification; they do not replace the written content." in normalized


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
        "DEEPSEEK_API_KEY=deepseek-secret\n"
        "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1\n"
        "HERMES_API_SERVER_KEY=hermes-secret\n"
        "PLATFORM_FEISHU_APP_SECRET=must-not-be-loaded\n"
        "POSTGRES_PASSWORD=must-not-be-loaded",
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
    for service_name in ("hermes-agent", "hermes-knowledge"):
        environment = specs[service_name].environment
        assert environment["API_SERVER_KEY"] == "hermes-secret"
        assert "HERMES_API_SERVER_KEY" not in environment
    assert specs["backend"].environment["HERMES_USE_HTTP"] == "true"
    assert specs["backend"].environment["HERMES_API_URL"] == (
        "http://127.0.0.1:8642"
    )
    assert specs["backend"].environment["HERMES_KNOWLEDGE_API_URL"] == (
        "http://127.0.0.1:8643"
    )
    assert "DATABASE_URL" not in specs["backend"].environment
    assert "DEEPSEEK_API_KEY" not in specs["backend"].environment
    assert "HERMES_API_KEY" not in specs["frontend"].environment
    assert "DEEPSEEK_API_KEY" not in specs["frontend"].environment


def test_start_rejects_busy_port_without_launching(tmp_path: Path) -> None:
    module = load_runtime_module()
    launched: list[str] = []

    with pytest.raises(module.RuntimeConfigurationError, match="port 8642"):
        module.start_services(
            {
                "hermes-agent": module.ServiceSpec(
                    name="hermes-agent",
                    command=("hermes.exe", "gateway", "run"),
                    cwd=tmp_path,
                    port=8642,
                    health_url="http://127.0.0.1:8642/health",
                    environment={},
                    process_markers=("hermes.exe", "gateway", "run"),
                )
            },
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

    with pytest.raises(
        module.RuntimeConfigurationError, match="two did not become healthy"
    ):
        module.start_services(
            specs,
            runtime_dir=tmp_path / "runtime",
            listener_lookup=lambda port: None,
            launcher=lambda spec, stdout, stderr: next(pids),
            health_probe=lambda url, timeout: url.endswith("18001/health"),
            stopper=lambda pid: stopped.append(pid),
            health_timeout=0,
        )

    assert stopped == [102, 101]


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


def test_prepare_local_dependencies_emits_required_commands_in_order(
    tmp_path: Path,
) -> None:
    module = load_runtime_module()
    project_root = tmp_path / "project"
    backend = project_root / "backend"
    frontend = project_root / "web-platform"
    backend.mkdir(parents=True)
    frontend.mkdir()
    (backend / "requirements.txt").write_text("pytest==8.4.1\n", encoding="utf-8")
    commands: list[tuple[tuple[str, ...], Path]] = []

    module.prepare_local_dependencies(
        project_root,
        runner=lambda command, cwd, env: commands.append((tuple(command), cwd)),
    )

    python = backend / ".venv" / "Scripts" / "python.exe"
    alembic = backend / ".venv" / "Scripts" / "alembic.exe"
    hermes = project_root / "hermes" / "hermes.exe"
    assert commands == [
        (("py", "-3.12", "-m", "venv", str(backend / ".venv")), project_root),
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
        ),
        ((str(hermes), "tools", "post-setup", "ddgs"), project_root / "hermes"),
        ((str(alembic), "upgrade", "head"), backend),
        ((str(python), "seed.py"), backend),
        (("npm.cmd", "ci"), frontend),
    ]


def test_main_prepares_local_dependencies_before_starting_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_runtime_module()
    calls: list[str] = []
    secrets = {"HERMES_API_SERVER_KEY": "test-secret"}
    specs = {"test-service": object()}

    monkeypatch.setattr(module, "load_runtime_secrets", lambda path: secrets)
    monkeypatch.setattr(
        module,
        "prepare_local_dependencies",
        lambda project_root: calls.append("prepare"),
    )

    def build_service_specs(project_root: Path, received_secrets: dict) -> dict:
        calls.append("build")
        assert received_secrets is secrets
        return specs

    def start_services(received_specs: dict, *, runtime_dir: Path) -> None:
        calls.append("start")
        assert received_specs is specs

    monkeypatch.setattr(module, "build_service_specs", build_service_specs)
    monkeypatch.setattr(module, "start_services", start_services)
    monkeypatch.setattr(module, "_all_statuses", lambda specs, runtime_dir: [])

    assert module.main(["start"]) == 0
    assert calls == ["prepare", "build", "start"]


def test_runtime_rendering_and_errors_redact_secret_values(tmp_path: Path) -> None:
    module = load_runtime_module()
    secrets = {
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "HERMES_API_SERVER_KEY": "hermes-secret",
    }
    specs = module.build_service_specs(PROJECT_ROOT, secrets)

    rendered = repr(specs)
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.start_services(
            specs,
            runtime_dir=tmp_path / "runtime",
            listener_lookup=lambda port: 999,
        )
    rendered += str(captured.value)

    assert "deepseek-secret" not in rendered
    assert "hermes-secret" not in rendered
