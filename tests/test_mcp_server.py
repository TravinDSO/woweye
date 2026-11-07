"""Starts the real server over stdio, so a broken import or SDK change fails here."""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_server_lists_tools_and_answers(tmp_path):
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "wow_eye.mcp_server"],
            env={**os.environ, "WOW_EYE_GAME_DIR": str(tmp_path)},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                status = await session.call_tool("wow_status", {})
                missing = await session.call_tool("wow_snapshot", {})
                return tools, status, missing

    tools, status, missing = asyncio.run(run())
    assert tools == {
        "wow_status",
        "wow_snapshot",
        "wow_events",
        "wow_send_to_panel",
        "wow_set_map_markers",
        "wow_set_route",
        "wow_route_status",
        "wow_completed_quests",
        "wow_npcs",
        "wow_vendors",
        "wow_trainers",
        "wow_flight_paths",
        "wow_session",
        "wow_clear_panel",
    }
    assert '"has_data": false' in status.content[0].text
    assert missing.is_error
    assert "No WowEye data" in missing.content[0].text
