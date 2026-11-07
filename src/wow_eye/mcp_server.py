"""MCP server that lets an AI agent read game data and write to the in-game panel."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from . import bridge

mcp = MCPServer(
    "wow-eye",
    instructions=(
        "Reads World of Warcraft: Forever data saved by the WowEye addon. Data is only as "
        "fresh as the player's last /eye sync, UI reload or logout, so check "
        "snapshot_age_seconds in wow_status. There is no live feed. The agent can show messages "
        "and map markers but can't act in game."
    ),
)


@mcp.tool()
def wow_status() -> dict[str, Any]:
    """Report whether the addon is installed, which characters have data, and data age."""
    return bridge.status()


@mcp.tool()
def wow_snapshot(section: str | None = None, character: str | None = None) -> Any:
    """Get the latest snapshot, or one section: identity, location, money, quests, equipment,
    bags, spells, talents, professions or reputation. Prefer a single section, since the
    whole snapshot is large. Positions are 0-1 fractions, so multiply by 100 for markers and
    routes. Each quest's waypoint is the game's own guidance on where it goes next, and
    mapPin is its location on the player's current map. Character is Name-Realm and defaults
    to the last played."""
    return bridge.snapshot(character, section)


@mcp.tool()
def wow_events(limit: int = 50, character: str | None = None) -> list[dict[str, Any]]:
    """Get recent logged events (level ups, deaths, quests, zone changes), oldest first."""
    return bridge.events(limit, character)


@mcp.tool()
def wow_send_to_panel(title: str, body: str) -> dict[str, Any]:
    """Queue a plain-text message for the in-game panel. The player sees it after their
    next /eye sync or UI reload."""
    return bridge.send_message(title, body)


class Marker(BaseModel):
    map_id: int
    x: float
    y: float
    label: str
    note: str | None = None
    zone: str | None = None


@mcp.tool()
def wow_set_map_markers(markers: list[Marker]) -> dict[str, Any]:
    """Replace the player's world map markers. x and y are percentages (0-100), as in game
    coordinates and on wikis. map_id is the uiMapID, as in the location section of the
    snapshot. The first marker also becomes the waypoint. Pass an empty list to remove all.
    Only mark locations you can back up, and tell the player where a location came from.
    The player sees the markers after their next sync or UI reload."""
    return bridge.set_markers([m.model_dump() for m in markers])


class RouteStep(Marker):
    complete_on: Literal[
        "arrive", "manual", "quest_accepted", "quest_complete", "quest_turned_in"
    ] = "arrive"
    quest_id: int | None = None
    radius: float | None = None


@mcp.tool()
def wow_set_route(steps: list[RouteStep], goal: str | None = None) -> dict[str, Any]:
    """Replace the player's route, an ordered plan that advances without further syncs. Steps
    use map percentages (0-100), like markers. complete_on decides when a step moves on:
    arrive (within radius yards, default 12), quest_accepted, quest_complete or
    quest_turned_in (these need quest_id), or manual (the player's next key). Use a quest
    condition for steps with work to do there, so walking past doesn't skip them. Pass an empty
    list to remove the route. It starts at step 1 after the player's next sync."""
    return bridge.set_route([s.model_dump() for s in steps], goal)


@mcp.tool()
def wow_route_status(character: str | None = None) -> dict[str, Any]:
    """Get the current route and how far the player was at their last sync."""
    return bridge.route_status(character)


@mcp.tool()
def wow_completed_quests(
    quest_ids: list[int] | None = None, character: str | None = None
) -> dict[str, Any]:
    """Check which quests this character has already finished, as of the last sync. Check
    before recommending any quest from outside the player's quest log, and don't direct them
    to completed ones. Pass quest_ids to check specific quests, which is much smaller than the
    full list. IDs must be Forever's own, because it has new quests and may differ from
    Classic. The list includes hidden tracking quests, and some quests can be repeated."""
    return bridge.completed_quests(quest_ids, character)


@mcp.tool()
def wow_npcs(
    query: str | None = None,
    role: str | None = None,
    map_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find NPCs the player has actually talked to, newest first, with real positions from the
    game. Prefer these over wiki coordinates. query matches name or title. role is one of
    merchant, trainer, flight, quest, gossip or banker."""
    return bridge.npcs(query, role, map_id, limit)


@mcp.tool()
def wow_vendors(query: str | None = None, character: str | None = None) -> list[dict[str, Any]]:
    """Get the stock of vendors this character has opened, with prices and item stats. Stock
    is as of the last visit, and the game's item filter may hide some items (itemFilter)."""
    return bridge.vendors(query, character)


@mcp.tool()
def wow_trainers(query: str | None = None, character: str | None = None) -> list[dict[str, Any]]:
    """Get what trainers this character has opened can teach, with cost, level and required
    skill rank. state is available, unavailable or used. showing lists the window's filters,
    which can hide some."""
    return bridge.trainers(query, character)


@mcp.tool()
def wow_flight_paths(character: str | None = None) -> list[dict[str, Any]]:
    """Get flight nodes seen at flight masters. Current and Reachable nodes are known;
    Unreachable ones aren't yet. Only maps where a flight master was opened are included."""
    return bridge.flight_paths(character)


@mcp.tool()
def wow_session(history: int = 5, character: str | None = None) -> dict[str, Any]:
    """Get statistics for this session and recent ones: XP per hour, levels, money, deaths,
    quests, combat share and time per zone. Use these to find what's slowing the player down."""
    return bridge.session(history, character)


@mcp.tool()
def wow_clear_panel() -> str:
    """Remove all messages from the in-game panel."""
    bridge.clear_messages()
    return "Cleared."


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
