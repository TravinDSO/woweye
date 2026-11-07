"""Everything the CLI and MCP server share: locating files, reading game data,
writing panel messages, and installing the addon."""

from __future__ import annotations

import os
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from . import savedvars

ADDON = "WowEye"
SV_FILE = f"{ADDON}.lua"
FOREVER_FOLDER = "_forever_"
CONFIG_FILE = "wow-eye.local.toml"
MAX_INBOX_MESSAGES = 50
MAX_MARKERS = 50
MAX_ROUTE_STEPS = 100
MIN_RATE_HOURS = 0.1
COMPLETE_ON = {"arrive", "manual", "quest_accepted", "quest_complete", "quest_turned_in"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADDON_SOURCE = PROJECT_ROOT / "addon" / ADDON


class BridgeError(ToolError):
    """A problem to show the user or agent as a plain message. It's a ToolError
    because the MCP SDK hides the text of any other exception from the agent."""


def game_dir_candidates() -> list[Path]:
    """Where Battle.net usually puts WoW: Program Files, then a World of Warcraft or
    Games folder at the root of any drive, then the Mac Applications folder."""
    roots = []
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(var):
            roots.append(Path(os.environ[var]))
    for letter in "CDEFGH":
        drive = Path(f"{letter}:\\")
        roots += [drive, drive / "Games", drive / "Program Files (x86)", drive / "Program Files"]
    roots.append(Path("/Applications"))

    out: list[Path] = []
    for root in roots:
        candidate = root / "World of Warcraft" / FOREVER_FOLDER
        if candidate not in out:
            out.append(candidate)
    return out


def config_path() -> Path:
    """Local settings, kept out of git so personal paths stay on this machine."""
    return PROJECT_ROOT / CONFIG_FILE


def read_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BridgeError(f"Can't read {path}: {exc}") from exc


def set_game_dir(folder: str) -> str:
    """Save the game folder in the local config file."""
    path = Path(folder).expanduser()
    if not path.is_dir():
        raise BridgeError(f"Folder not found: {path}")
    if not (path / "Interface").is_dir() and not (path / "WTF").is_dir():
        raise BridgeError(f"{path} has no Interface or WTF folder. Point at the _forever_ folder.")
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    config_path().write_text(
        "# Local WoW Eye settings. Git ignores this file.\n" f'game_dir = "{escaped}"\n',
        encoding="utf-8",
    )
    return f"Saved game folder {path} to {config_path()}"


def game_dir() -> Path:
    """The game folder, from the first of: WOW_EYE_GAME_DIR, game_dir in the local config
    file, or the first standard install folder that exists. With none, the first
    candidate, so error messages show where it looked."""
    configured = os.environ.get("WOW_EYE_GAME_DIR")
    if configured:
        return Path(configured)
    saved = read_config().get("game_dir")
    if isinstance(saved, str) and saved.strip():
        return Path(saved)
    candidates = game_dir_candidates()
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return candidates[0]


def addon_link() -> Path:
    return game_dir() / "Interface" / "AddOns" / ADDON


def inbox_path() -> Path:
    return ADDON_SOURCE / "Inbox.lua"


def saved_variables_path() -> Path | None:
    """The newest WowEye data file across accounts, or None if the game hasn't written one."""
    found = list((game_dir() / "WTF" / "Account").glob(f"*/SavedVariables/{SV_FILE}"))
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def read_db() -> dict[str, Any]:
    path = saved_variables_path()
    if path is None:
        raise BridgeError(
            "No WowEye data yet. Install the addon, restart the game, log in, then run /eye sync."
        )
    return savedvars.load(path).get("WowEyeDB") or {}


def _character(db: dict[str, Any], character: str | None) -> dict[str, Any]:
    characters = db.get("characters") or {}
    key = character or db.get("lastCharacter")
    if key not in characters:
        raise BridgeError(f"Unknown character {key!r}. Known: {sorted(characters)}")
    return characters[key]


def snapshot(character: str | None = None, section: str | None = None) -> Any:
    snap = _character(read_db(), character).get("snapshot")
    if snap is None:
        raise BridgeError("No snapshot yet for that character. Run /eye sync in game.")
    if section is None:
        return snap
    if section not in snap:
        raise BridgeError(f"Unknown section {section!r}. Available: {sorted(snap)}")
    return snap[section]


def events(limit: int = 50, character: str | None = None) -> list[dict[str, Any]]:
    log = _character(read_db(), character).get("events") or []
    return log[-limit:] if limit > 0 else []


def status() -> dict[str, Any]:
    link = addon_link()
    out: dict[str, Any] = {
        "game_dir": str(game_dir()),
        "game_dir_exists": game_dir().is_dir(),
        "addon_installed": os.path.isjunction(link) or link.is_dir(),
        "has_data": False,
    }
    path = saved_variables_path()
    if path is None:
        return out
    db = savedvars.load(path).get("WowEyeDB") or {}
    now = time.time()
    out.update(
        has_data=True,
        file_age_seconds=round(now - path.stat().st_mtime),
        characters=sorted(db.get("characters") or {}),
        last_character=db.get("lastCharacter"),
        panel_messages_read_through=db.get("lastInboxSeq", 0),
        map_markers_applied_through=db.get("lastMarkerSeq", 0),
    )
    current = (db.get("characters") or {}).get(db.get("lastCharacter")) or {}
    snap = current.get("snapshot")
    if snap:
        out["snapshot_age_seconds"] = round(now - snap.get("capturedAt", now))
        out["snapshot_errors"] = snap.get("errors") or {}
        out["snapshot_redacted"] = snap.get("redacted", 0)
    completed = current.get("completedQuests")
    if completed:
        out["completed_quests"] = len(completed.get("ids") or [])
    return out


def _read_inbox() -> dict[str, Any]:
    inbox: dict[str, Any] = {}
    if inbox_path().exists():
        inbox = savedvars.load(inbox_path()).get("WowEyeInbox") or {}
    return {
        "seq": inbox.get("seq", 0),
        "messages": inbox.get("messages") or [],
        "markerSeq": inbox.get("markerSeq", 0),
        "markers": inbox.get("markers") or [],
        "routeSeq": inbox.get("routeSeq", 0),
        "routeGoal": inbox.get("routeGoal"),
        "route": inbox.get("route") or [],
    }


def _write_inbox(inbox: dict[str, Any]) -> None:
    text = f"WowEyeInbox = {savedvars.dumps_value(inbox)}\n"
    path = inbox_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8", errors="replace", newline="\n")
    os.replace(tmp, path)


def send_message(title: str, body: str) -> dict[str, Any]:
    inbox = _read_inbox()
    inbox["seq"] += 1
    inbox["messages"] = [*inbox["messages"], {"title": title, "body": body, "at": int(time.time())}][
        -MAX_INBOX_MESSAGES:
    ]
    _write_inbox(inbox)
    return {"seq": inbox["seq"], "note": "Visible in game after the next /eye sync or UI reload."}


def clear_messages() -> None:
    _write_inbox({**_read_inbox(), "messages": []})


def _marker(raw: dict[str, Any]) -> dict[str, Any]:
    map_id, x, y, label = (raw.get(k) for k in ("map_id", "x", "y", "label"))
    if not isinstance(map_id, int) or isinstance(map_id, bool) or map_id <= 0:
        raise BridgeError(f"map_id must be a positive whole number, got {map_id!r}")
    for name, value in (("x", x), ("y", y)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100:
            raise BridgeError(f"{name} must be a map percentage from 0 to 100, got {value!r}")
    if not isinstance(label, str) or not label.strip():
        raise BridgeError("label must be non-empty text")
    marker = {"mapID": map_id, "x": x / 100, "y": y / 100, "label": label}
    for key in ("note", "zone"):
        if raw.get(key):
            marker[key] = str(raw[key])
    return marker


def set_markers(markers: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace the map markers. x and y are percentages, as in game coordinates and on
    wikis. The first marker becomes the waypoint. An empty list removes them all."""
    if len(markers) > MAX_MARKERS:
        raise BridgeError(f"Too many markers: {len(markers)} (limit {MAX_MARKERS})")
    cleaned = [_marker(m) for m in markers]
    inbox = _read_inbox()
    inbox["markerSeq"] += 1
    inbox["markers"] = cleaned
    _write_inbox(inbox)
    return {
        "marker_seq": inbox["markerSeq"],
        "count": len(cleaned),
        "note": "Visible in game after the next /eye sync or UI reload.",
    }


def get_markers() -> list[dict[str, Any]]:
    """Current markers, in the same form set_markers accepts."""
    return [
        {
            "map_id": m["mapID"],
            "x": round(m["x"] * 100, 4),
            "y": round(m["y"] * 100, 4),
            "label": m["label"],
            "note": m.get("note"),
            "zone": m.get("zone"),
        }
        for m in _read_inbox()["markers"]
    ]


def _route_step(raw: dict[str, Any]) -> dict[str, Any]:
    step = _marker(raw)
    complete_on = raw.get("complete_on") or "arrive"
    if complete_on not in COMPLETE_ON:
        raise BridgeError(f"complete_on must be one of {sorted(COMPLETE_ON)}, got {complete_on!r}")
    step["completeOn"] = complete_on
    quest_id = raw.get("quest_id")
    if complete_on.startswith("quest_"):
        if not isinstance(quest_id, int) or isinstance(quest_id, bool) or quest_id <= 0:
            raise BridgeError(f"complete_on {complete_on} needs a quest_id, got {quest_id!r}")
        step["questID"] = quest_id
    radius = raw.get("radius")
    if radius is not None:
        if not isinstance(radius, (int, float)) or isinstance(radius, bool) or not 0 < radius <= 500:
            raise BridgeError(f"radius must be from 1 to 500 yards, got {radius!r}")
        step["radius"] = radius
    return step


def set_route(steps: list[dict[str, Any]], goal: str | None = None) -> dict[str, Any]:
    """Replace the route. It starts at step 1 after the next sync. An empty list removes it."""
    if len(steps) > MAX_ROUTE_STEPS:
        raise BridgeError(f"Too many route steps: {len(steps)} (limit {MAX_ROUTE_STEPS})")
    cleaned = [_route_step(s) for s in steps]
    inbox = _read_inbox()
    inbox["routeSeq"] += 1
    inbox["route"] = cleaned
    inbox["routeGoal"] = goal if cleaned and goal else None
    if inbox["routeGoal"] is None:
        del inbox["routeGoal"]
    warnings = _completed_step_warnings(cleaned)
    _write_inbox(inbox)
    result = {
        "route_seq": inbox["routeSeq"],
        "steps": len(cleaned),
        "note": "Starts in game after the next /eye sync or UI reload.",
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _completed_ids() -> set[int] | None:
    """Completed quest IDs for the last played character, or None if none are synced yet."""
    if saved_variables_path() is None:
        return None
    db = read_db()
    record = (db.get("characters") or {}).get(db.get("lastCharacter")) or {}
    data = record.get("completedQuests")
    return set(data.get("ids") or []) if data else None


def _completed_step_warnings(steps: list[dict[str, Any]]) -> list[str]:
    done = _completed_ids()
    if not done:
        return []
    return [
        f"Step {i} ({step['label']}): quest {step['questID']} is already completed"
        for i, step in enumerate(steps, start=1)
        if step.get("questID") in done
    ]


def completed_quests(
    quest_ids: list[int] | None = None, character: str | None = None
) -> dict[str, Any]:
    """Quests this character has finished, as of the last sync. With quest_ids, says which of
    those are done. Without them, returns the whole list."""
    data = _character(read_db(), character).get("completedQuests")
    if not data:
        raise BridgeError("No completed quest list yet. Run /eye sync in game.")
    ids = data.get("ids") or []
    out: dict[str, Any] = {"synced_at": data.get("at"), "total": len(ids)}
    if quest_ids is None:
        out["completed"] = sorted(ids)
    else:
        done = set(ids)
        out["completed"] = [q for q in quest_ids if q in done]
        out["not_completed"] = [q for q in quest_ids if q not in done]
    return out


def route_status(character: str | None = None) -> dict[str, Any]:
    """The route as sent, and how far the player was at their last sync."""
    inbox = _read_inbox()
    route = inbox["route"]
    out: dict[str, Any] = {
        "route_seq": inbox["routeSeq"],
        "goal": inbox.get("routeGoal"),
        "total_steps": len(route),
        "steps": route,
        "loaded_in_game": False,
    }
    if saved_variables_path() is None:
        return out
    progress = _character(read_db(), character).get("route") or {}
    if progress.get("seq") == inbox["routeSeq"]:
        step = progress.get("step", 1)
        out.update(
            loaded_in_game=True,
            current_step=step,
            done=bool(progress.get("done")),
            current=route[step - 1] if 1 <= step <= len(route) else None,
        )
    return out


def _records(field: str, character: str | None) -> list[dict[str, Any]]:
    data = _character(read_db(), character).get(field) or {}
    return list(data.values() if isinstance(data, dict) else data)


def _matches(record: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    query = query.lower()
    return query in str(record.get("name", "")).lower() or query in str(record.get("title", "")).lower()


def vendors(query: str | None = None, character: str | None = None) -> list[dict[str, Any]]:
    """Vendors this character has opened, with stock. query matches name or title."""
    return [v for v in _records("vendors", character) if _matches(v, query)]


def trainers(query: str | None = None, character: str | None = None) -> list[dict[str, Any]]:
    """Trainers this character has opened, with what they offer and its cost."""
    return [t for t in _records("trainers", character) if _matches(t, query)]


def flight_paths(character: str | None = None) -> list[dict[str, Any]]:
    """Flight nodes seen at flight masters. Reachable and Current nodes are known."""
    return _records("flightPaths", character)


def npcs(
    query: str | None = None,
    role: str | None = None,
    map_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """NPCs the player has talked to, on any character, with positions as map percentages.
    These locations are from the real game, so prefer them over wiki coordinates."""
    data = read_db().get("npcs") or {}
    found = []
    for npc in data.values():
        if not _matches(npc, query):
            continue
        if role and role not in (npc.get("roles") or {}):
            continue
        if map_id and npc.get("mapID") != map_id:
            continue
        found.append(
            {
                **npc,
                "roles": sorted(npc.get("roles") or {}),
                "x_percent": round(npc["x"] * 100, 1) if "x" in npc else None,
                "y_percent": round(npc["y"] * 100, 1) if "y" in npc else None,
            }
        )
    found.sort(key=lambda n: n.get("lastSeen", 0), reverse=True)
    return found[:limit] if limit > 0 else []


def _session_summary(session: dict[str, Any]) -> dict[str, Any]:
    seconds = max(0, session.get("lastSeen", 0) - session.get("startedAt", 0))
    hours = seconds / 3600
    xp = session.get("xpGained", 0)
    zones = session.get("zoneSeconds") or {}
    return {
        "started_at": session.get("startedAt"),
        "minutes": round(seconds / 60, 1),
        "xp_gained": xp,
        "xp_per_hour": round(xp / hours) if hours >= MIN_RATE_HOURS else None,
        "levels_gained": session.get("levelsGained", 0),
        "start_level": session.get("startLevel"),
        "end_level": session.get("endLevel"),
        "money_change_copper": session.get("endMoney", session.get("startMoney", 0))
        - session.get("startMoney", 0),
        "deaths": session.get("deaths", 0),
        "quests_accepted": session.get("questsAccepted", 0),
        "quests_turned_in": session.get("questsTurnedIn", 0),
        "combat_percent": round(100 * session.get("combatSeconds", 0) / seconds) if seconds else 0,
        "zone_minutes": {
            zone: round(zone_seconds / 60, 1)
            for zone, zone_seconds in sorted(zones.items(), key=lambda kv: kv[1], reverse=True)
        },
    }


def session(history: int = 5, character: str | None = None) -> dict[str, Any]:
    """Statistics for the current session, as of the last sync, and recent past sessions."""
    rec = _character(read_db(), character)
    current = rec.get("session")
    past = rec.get("sessions") or []
    return {
        "current": _session_summary(current) if current else None,
        "past": [_session_summary(s) for s in past[-history:]] if history > 0 else [],
    }


def ensure_inbox() -> None:
    if not inbox_path().exists():
        _write_inbox(_read_inbox())


def install() -> str:
    """Link the addon into the game folder so edits apply on the next /reload."""
    link = addon_link()
    if not game_dir().is_dir():
        raise BridgeError(
            f"Couldn't find WoW: Forever in the usual install folders, such as {game_dir()}. "
            f"Run `wow-eye game-dir <folder>` with the folder that contains Interface and WTF."
        )
    ensure_inbox()
    if os.path.isjunction(link):
        return f"Already installed: {link}"
    if link.exists():
        raise BridgeError(f"{link} exists and isn't a link from this tool. Move it away first.")
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(ADDON_SOURCE)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BridgeError(f"mklink failed: {result.stdout}{result.stderr}".strip())
    return f"Linked {link} -> {ADDON_SOURCE}. Restart the game so it finds the new addon."


def uninstall() -> str:
    """Remove the link only. The addon source and saved data stay where they are."""
    link = addon_link()
    if not os.path.isjunction(link):
        return f"Nothing to remove: {link} isn't a link from this tool."
    os.rmdir(link)
    return f"Removed link {link}"
