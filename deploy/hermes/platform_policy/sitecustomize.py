"""Fail-closed policy overrides for the dedicated remote Docker runner."""

from __future__ import annotations

from copy import deepcopy
import os


FOREGROUND_TERMINAL_DESCRIPTION = """Execute a foreground shell command in the dedicated Linux sandbox.

Use read_file, search_files, write_file, or patch for file operations. Use terminal only for builds,
tests, package managers, scripts, and commands that require a shell. Commands are bounded by the
configured timeout and return when complete. Long-lived and detached commands are not available.
"""


def _without_cap_add(arguments: list[str]) -> list[str]:
    filtered: list[str] = []
    index = 0
    while index < len(arguments):
        if arguments[index] == "--cap-add":
            index += 2
            continue
        filtered.append(arguments[index])
        index += 1
    return filtered


def _isolated_task_id(task_id: str | None) -> str:
    if not task_id:
        raise RuntimeError("Hermes sandbox task id is required by platform policy")
    return task_id


def _foreground_terminal_schema(schema: dict[str, object]) -> dict[str, object]:
    restricted = deepcopy(schema)
    restricted["description"] = FOREGROUND_TERMINAL_DESCRIPTION
    parameters = restricted.get("parameters", {})
    properties = parameters.get("properties", {})
    for name in ("background", "notify_on_complete", "watch_patterns"):
        properties.pop(name, None)
    return restricted


if os.getenv("HERMES_REMOTE_DOCKER_STRICT") == "1":
    from tools import credential_files
    from tools.environments import docker as docker_environment
    from tools import process_registry
    from tools import terminal_tool
    from tools.registry import registry

    docker_environment._BASE_SECURITY_ARGS = _without_cap_add(
        docker_environment._BASE_SECURITY_ARGS
    )
    docker_environment._PRIVDROP_CAP_ARGS = []
    terminal_tool._resolve_container_task_id = _isolated_task_id

    def _no_automatic_mounts(*_args: object, **_kwargs: object) -> list[dict[str, str]]:
        return []

    credential_files.get_credential_file_mounts = _no_automatic_mounts
    credential_files.get_skills_directory_mount = _no_automatic_mounts
    credential_files.get_cache_directory_mounts = _no_automatic_mounts

    terminal_entry = registry._tools["terminal"]
    terminal_entry.schema = _foreground_terminal_schema(terminal_entry.schema)
    terminal_entry.description = FOREGROUND_TERMINAL_DESCRIPTION
    original_terminal_handler = terminal_entry.handler

    def _foreground_terminal_handler(
        args: dict[str, object], **kwargs: object
    ) -> object:
        if any(
            args.get(name)
            for name in ("background", "notify_on_complete", "watch_patterns")
        ):
            return "Error: background terminal execution is disabled by platform policy"
        return original_terminal_handler(args, **kwargs)

    terminal_entry.handler = _foreground_terminal_handler

    original_register = registry.register

    def _register_without_process(*args: object, **kwargs: object) -> object:
        name = kwargs.get("name")
        if name is None and args:
            name = args[0]
        if name == "process":
            return None
        return original_register(*args, **kwargs)

    registry.register = _register_without_process
    registry.deregister("process")
    del process_registry
