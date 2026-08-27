from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx


base_url = os.getenv("HERMES_API_URL", "http://hermes:8642").rstrip("/")
api_key = os.environ["HERMES_API_KEY"]
headers = {
    "Authorization": f"Bearer {api_key}",
    "Accept": "application/json",
}
session_id = f"dingtalk-demo-smoke-{uuid4().hex}"

created = httpx.post(
    f"{base_url}/v1/runs",
    json={"input": "帮我完成周报", "session_id": session_id},
    headers=headers,
    timeout=30,
)
created.raise_for_status()
run_id = created.json()["run_id"]
output = ""

with httpx.stream(
    "GET",
    f"{base_url}/v1/runs/{run_id}/events",
    headers=headers,
    timeout=180,
) as events:
    events.raise_for_status()
    events_status = events.status_code
    for line in events.iter_lines():
        if not line.startswith("data:"):
            continue
        try:
            data = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if data.get("event") == "run.completed":
            output = str(data.get("output") or "")

checks = {
    "create_status": created.status_code,
    "events_status": events_status,
    "output_length": len(output),
    "has_weekly_title": "# 人力资源部周报" in output,
    "has_overview_section": "## 一、本周工作概览" in output,
    "has_next_section": "## 八、下周计划" in output,
    "uses_missing_data_marker": "待补充" in output,
    "claims_attachment": "附件已" in output or "已发送附件" in output,
}
print(json.dumps(checks, ensure_ascii=False))

if not all(
    (
        checks["has_weekly_title"],
        checks["has_overview_section"],
        checks["has_next_section"],
        checks["uses_missing_data_marker"],
    )
) or checks["claims_attachment"]:
    raise SystemExit(1)
