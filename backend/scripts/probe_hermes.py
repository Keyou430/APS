import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.hermes_capabilities import HermesCapabilityClient, HermesCapabilityError
from app.services.hermes_client import (
    HermesHttpClient,
    HermesRequestContext,
    HermesUpstreamError,
    associate_terminal_message,
)
from app.services.runner_client import sandbox_runner_client


async def cleanup_probe_tasks(task_ids, cleanup_client) -> None:
    failures: list[Exception] = []
    for task_id in dict.fromkeys(task_id for task_id in task_ids if task_id):
        try:
            await cleanup_client.cleanup_task(task_id)
        except Exception as exc:
            failures.append(exc)
    if failures:
        raise RuntimeError(f"Failed to clean up {len(failures)} probe task(s)") from failures[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the pinned private Hermes API server")
    parser.add_argument(
        "--exercise",
        action="store_true",
        help="run response continuation, streamed run, and session-history checks",
    )
    parser.add_argument(
        "--prompt",
        default="Hermes platform integration probe",
        help="prompt used only with --exercise",
    )
    return parser.parse_args()


async def probe(exercise: bool, prompt: str) -> dict:
    settings = get_settings()
    if settings.hermes_api_key is None or not settings.hermes_api_key.get_secret_value():
        raise HermesCapabilityError("HERMES_API_KEY is required for the Hermes probe")

    api_key = settings.hermes_api_key.get_secret_value()
    capability_client = HermesCapabilityClient(
        settings.hermes_api_url,
        api_key=api_key,
        timeout_seconds=settings.hermes_http_timeout_seconds,
    )
    report = await capability_client.probe()
    features = report.capabilities.get("features", {})
    result = {
        "healthy": report.healthy,
        "health": report.health,
        "detailed_health": report.detailed_health,
        "stop_supported": features.get("run_stop") is True,
        "approval_supported": features.get("run_approval_response") is True,
        "streaming_supported": features.get("run_events_sse") is True,
    }

    if not exercise:
        return result

    client = HermesHttpClient(
        settings.hermes_api_url,
        api_key=api_key,
        timeout_seconds=settings.hermes_http_timeout_seconds,
        connect_timeout_seconds=settings.hermes_http_connect_timeout_seconds,
        max_retries=settings.hermes_http_max_retries,
    )
    session_id = f"probe-{uuid4().hex}"
    context = HermesRequestContext(
        user_id=0,
        organization_id="probe",
        session_id=session_id,
        correlation_id=uuid4().hex,
    )
    cleanup_task_ids: list[str | None] = [session_id]
    try:
        first, first_session_id = await client.create_openai_response_with_metadata(
            prompt, context=context
        )
        cleanup_task_ids.append(first_session_id)
        response_id = first.get("id")
        if not isinstance(response_id, str) or not response_id:
            raise HermesUpstreamError("Hermes response probe did not return a response id")
        continued, continued_session_id = await client.create_openai_response_with_metadata(
            "Continue the probe.",
            previous_response_id=response_id,
            context=context,
        )
        cleanup_task_ids.append(continued_session_id)
        history_before_run = await client.get_session_messages(session_id, context=context)
        run_id = await client.create_response(
            "Stream the probe result.",
            session_id,
            context=context,
            idempotency_key=f"probe-run-{uuid4().hex}",
        )
        streamed_events = [
            event
            async for event in client.stream_events(
                run_id,
                session_id,
                context=context,
            )
        ]
        history_reads = [
            await client.get_session_messages(session_id, context=context) for _ in range(3)
        ]
        assistant_message_id = associate_terminal_message(
            before_messages=history_before_run,
            history_reads=history_reads,
            streamed_events=streamed_events,
        )
        result["exercise"] = {
            "response_id": response_id,
            "continued_response_id": continued.get("id"),
            "run_id": run_id,
            "stream_event_count": len(streamed_events),
            "history_message_count": len(history_reads[-1]),
            "history_message_ids_stable": True,
            "assistant_message_id": assistant_message_id,
        }
    finally:
        await cleanup_probe_tasks(cleanup_task_ids, sandbox_runner_client)
    return result


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(probe(args.exercise, args.prompt))
    except (HermesCapabilityError, HermesUpstreamError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
