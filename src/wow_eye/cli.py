"""Command line for the bridge: `wow-eye status`, `snapshot`, `events`, `send`, ..."""

from __future__ import annotations

import argparse
import json
import sys

from . import bridge


def _print_json(value) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _read_steps(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            steps = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise bridge.BridgeError(f"Couldn't read {path}: {e}") from e
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        raise bridge.BridgeError(f"{path} must contain a JSON list of step objects")
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wow-eye", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Is the addon installed, and how fresh is the data?")

    snap = sub.add_parser("snapshot", help="Print the latest game snapshot")
    snap.add_argument("--section", help="identity, location, money, quests, equipment or bags")
    snap.add_argument("--character", help="Name-Realm (default: last played)")

    ev = sub.add_parser("events", help="Print recent logged game events")
    ev.add_argument("-n", "--limit", type=int, default=50)
    ev.add_argument("--character", help="Name-Realm (default: last played)")

    send = sub.add_parser("send", help="Queue a message for the in-game panel")
    send.add_argument("title")
    send.add_argument("body")

    sub.add_parser("clear", help="Remove all messages from the in-game panel")

    mark = sub.add_parser("mark", help="Put a marker on the world map, replacing existing ones")
    mark.add_argument("map_id", type=int, help="Map ID, as in snapshot --section location")
    mark.add_argument("x", type=float, help="Map percentage, 0-100")
    mark.add_argument("y", type=float, help="Map percentage, 0-100")
    mark.add_argument("label")
    mark.add_argument("--note")
    mark.add_argument("--zone")
    mark.add_argument("--add", action="store_true", help="Keep existing markers")

    sub.add_parser("unmark", help="Remove all map markers")

    route = sub.add_parser("route", help="Show the route, or set it from a JSON file")
    route.add_argument("file", nargs="?", help="JSON list of steps (map_id, x, y, label, ...)")
    route.add_argument("--goal", help="Short description shown in the panel")
    route.add_argument("--clear", action="store_true", help="Remove the route")

    for name, help_text in (
        ("vendors", "Vendors this character has opened, with stock"),
        ("trainers", "Trainers this character has opened, with what they teach"),
        ("npcs", "NPCs you've talked to, with real positions"),
    ):
        lookup = sub.add_parser(name, help=help_text)
        lookup.add_argument("query", nargs="?", help="Match on name or title")
        if name == "npcs":
            lookup.add_argument("--role", help="merchant, trainer, flight, quest, gossip or banker")
            lookup.add_argument("--map-id", type=int)
            lookup.add_argument("-n", "--limit", type=int, default=50)

    sub.add_parser("flights", help="Flight nodes seen at flight masters")

    completed = sub.add_parser("completed", help="Quests this character has finished")
    completed.add_argument("quest_ids", nargs="*", type=int, help="Only check these quest IDs")

    stats = sub.add_parser("session", help="Statistics for this session and recent ones")
    stats.add_argument("--history", type=int, default=5)
    sub.add_parser("install", help="Link the addon into the game's AddOns folder")
    sub.add_parser("uninstall", help="Remove that link")
    gamedir = sub.add_parser("game-dir", help="Show the game folder, or save one in wow-eye.local.toml")
    gamedir.add_argument("folder", nargs="?", help="The _forever_ folder, with Interface and WTF in it")

    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            _print_json(bridge.status())
        elif args.command == "snapshot":
            _print_json(bridge.snapshot(args.character, args.section))
        elif args.command == "events":
            _print_json(bridge.events(args.limit, args.character))
        elif args.command == "send":
            _print_json(bridge.send_message(args.title, args.body))
        elif args.command == "clear":
            bridge.clear_messages()
        elif args.command == "mark":
            marker = {k: getattr(args, k) for k in ("map_id", "x", "y", "label", "note", "zone")}
            existing = bridge.get_markers() if args.add else []
            _print_json(bridge.set_markers([*existing, marker]))
        elif args.command == "unmark":
            _print_json(bridge.set_markers([]))
        elif args.command == "route":
            if args.clear:
                _print_json(bridge.set_route([]))
            elif args.file:
                _print_json(bridge.set_route(_read_steps(args.file), args.goal))
            else:
                _print_json(bridge.route_status())
        elif args.command == "vendors":
            _print_json(bridge.vendors(args.query))
        elif args.command == "trainers":
            _print_json(bridge.trainers(args.query))
        elif args.command == "npcs":
            _print_json(bridge.npcs(args.query, args.role, args.map_id, args.limit))
        elif args.command == "flights":
            _print_json(bridge.flight_paths())
        elif args.command == "completed":
            _print_json(bridge.completed_quests(args.quest_ids or None))
        elif args.command == "session":
            _print_json(bridge.session(args.history))
        elif args.command == "install":
            print(bridge.install())
        elif args.command == "game-dir":
            print(bridge.set_game_dir(args.folder) if args.folder else bridge.game_dir())
        elif args.command == "uninstall":
            print(bridge.uninstall())
    except bridge.BridgeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
