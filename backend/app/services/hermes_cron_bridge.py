"""Native Hermes cron registration for platform-owned pipeline tasks."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import PipelineTask


def _hermes_executable() -> str:
    configured = os.getenv("HERMES_CLI_EXE_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path.cwd() / "hermes" / "hermes.exe",
        Path(__file__).resolve().parents[3] / "hermes" / "hermes.exe",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return str(candidate)
    return str(next((c for c in candidates if c is not None), Path("hermes") / "hermes.exe"))


def _hermes_cli_environment(executable: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("RAG_QUERY_AUDIT_HMAC_KEY", None)
    environment["HERMES_HOME"] = str(Path(executable).resolve().parent)
    return environment


def _script_path(executable: str, task_id: int) -> Path:
    return Path(executable).resolve().parent / "scripts" / f"platform_pipeline_task_{task_id}.py"


async def register_hermes_cron(
    *, task_id: int, schedule: str, title: str, timezone: str
) -> str:
    """Create one native Hermes cron job and return its durable job id."""
    executable = _hermes_executable()
    script_path = _script_path(executable, task_id)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    endpoint = f"{settings.platform_internal_api_url.rstrip('/')}/api/internal/pipeline/trigger"
    script_path.write_text(
        "from datetime import UTC, datetime\n"
        "import json\n"
        "from urllib.request import Request, urlopen\n\n"
        f"TASK_ID = {task_id}\n"
        f"TIMEZONE = {json.dumps(timezone)}\n"
        f"ENDPOINT = {json.dumps(endpoint)}\n"
        f"INTERNAL_KEY = {json.dumps(settings.hermes_cron_internal_key)}\n\n"
        "scheduled_for = datetime.now(UTC).replace(second=0, microsecond=0).isoformat()\n"
        "payload = json.dumps({\"task_id\": TASK_ID, \"scheduled_for\": scheduled_for}).encode()\n"
        "request = Request(ENDPOINT, data=payload, headers={\n"
        "    \"Content-Type\": \"application/json\",\n"
        "    \"X-Hermes-Internal-Key\": INTERNAL_KEY,\n"
        "}, method=\"POST\")\n"
        "with urlopen(request, timeout=30) as response:\n"
        "    print(response.read().decode(\"utf-8\"))\n",
        encoding="utf-8",
    )
    proc = await asyncio.create_subprocess_exec(
        executable,
        "cron",
        "create",
        schedule,
        "--name",
        title,
        "--script",
        script_path.name,
        "--no-agent",
        env=_hermes_cli_environment(executable),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.hermes_http_timeout_seconds
        )
    except TimeoutError as exc:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        script_path.unlink(missing_ok=True)
        raise RuntimeError("Hermes cron create timed out") from exc
    output = stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        script_path.unlink(missing_ok=True)
        detail = stderr.decode("utf-8", errors="replace").strip() or output.strip()
        raise RuntimeError(f"Hermes cron create failed: {detail[:300]}")
    match = re.search(r"Created job:\s*([A-Za-z0-9_-]+)", output)
    if not match:
        script_path.unlink(missing_ok=True)
        raise RuntimeError("Hermes cron create returned no job id")
    return match.group(1)


async def remove_hermes_cron(job_id: str, *, task_id: int | None = None) -> None:
    """Remove one native Hermes cron job."""
    executable = _hermes_executable()
    proc = await asyncio.create_subprocess_exec(
        executable,
        "cron",
        "remove",
        job_id,
        env=_hermes_cli_environment(executable),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timeout = get_settings().hermes_http_timeout_seconds
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as exc:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise RuntimeError(
            f"Hermes cron remove timed out after {timeout:g} seconds"
        ) from exc
    if proc.returncode != 0:
        detail = (
            stderr.decode("utf-8", errors="replace").strip()
            or stdout.decode("utf-8", errors="replace").strip()
            or "unknown error"
        )
        raise RuntimeError(f"Hermes cron remove failed: {detail[:300]}")
    if task_id is not None:
        _script_path(executable, task_id).unlink(missing_ok=True)


async def reconcile_unbound_pipeline_tasks(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    registrar: Callable[..., Awaitable[str]] | None = None,
    remover: Callable[[str], Awaitable[None]] | None = None,
) -> int:
    """Bind existing scheduled tasks to native Hermes cron during startup."""
    register = registrar or register_hermes_cron
    remove = remover or remove_hermes_cron
    async with session_factory() as db:
        tasks = list(
            (
                await db.scalars(
                    select(PipelineTask)
                    .where(
                        PipelineTask.schedule.is_not(None),
                        PipelineTask.status == "ready",
                        PipelineTask.deleted_at.is_(None),
                        PipelineTask.hermes_cron_job_id.is_(None),
                    )
                    .order_by(PipelineTask.id)
                )
            ).all()
        )
        reconciled = 0
        for task in tasks:
            job_id = await register(
                task_id=task.id,
                schedule=task.schedule,
                title=task.title,
                timezone=task.timezone,
            )
            task.hermes_cron_job_id = job_id
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                await remove(job_id, task_id=task.id)
                raise
            reconciled += 1
        return reconciled
