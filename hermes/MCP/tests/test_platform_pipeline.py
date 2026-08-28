import pytest

from hermes_mcp.platform_pipeline import create_server


@pytest.mark.asyncio
async def test_standalone_server_exposes_only_pipeline_trigger() -> None:
    tools = await create_server().list_tools()

    assert [tool.name for tool in tools] == ["platform_pipeline_trigger"]
    assert tools[0].parameters["properties"] == {
        "task_id": {"type": "integer"},
        "scheduled_for": {"default": "", "type": "string"},
    }
