import re
import xml.etree.ElementTree as ET

import pytest
from conftest import ADDON_DIR, Game
from test_bridge import env  # noqa: F401

from wow_eye import bridge, cli, savedvars

BOW_SHOP = {"map_id": 37, "x": 45.0, "y": 39.5, "label": "Bow merchant", "note": "Sells bows", "zone": "Elwynn"}
ELSEWHERE = {"map_id": 48, "x": 83.0, "y": 63.0, "label": "Other"}


def game_with_inbox() -> Game:
    g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    g.login()
    return g


def test_pushed_marker_becomes_a_pin_and_waypoint(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP, ELSEWHERE])
    g = game_with_inbox()
    pins = g.g.WorldMapFrame.pins
    assert len(pins) == 1
    assert pins[1].x == pytest.approx(0.45)
    assert pins[1].y == pytest.approx(0.395)
    assert g.g.last_waypoint.mapID == 37
    assert g.g.supertracked is True
    assert any("Bow merchant" in s and "(45.0, 39.5)" in s for s in g.g.printed.values())


def test_pins_follow_the_map_being_viewed(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP, ELSEWHERE])
    g = game_with_inbox()
    world_map = g.g.WorldMapFrame
    world_map.mapID = 48
    world_map.provider.OnMapChanged(world_map.provider)
    assert [p.marker.label for p in world_map.pins.values()] == ["Other"]


def test_waypoint_only_taken_over_by_new_markers(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    first = game_with_inbox()
    assert first.g.waypoint_calls == 1
    saved = first.saved_text()
    inbox = bridge.inbox_path().read_text(encoding="utf-8")

    reloaded = Game(inbox_source=saved + "\n" + inbox)
    reloaded.login()
    assert reloaded.g.waypoint_calls == 0
    assert len(reloaded.g.WorldMapFrame.pins) == 1


def test_clicking_a_pin_sets_the_waypoint_and_tooltip_is_literal(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP, {**ELSEWHERE, "map_id": 37, "label": "|cffff0000x|r"}])
    g = game_with_inbox()
    pin = g.g.WorldMapFrame.pins[2]
    pin.OnMouseUp(pin)
    assert g.g.last_waypoint.x == pytest.approx(0.83)
    pin.OnMouseEnter(pin)
    assert "||cffff0000x||r" in list(g.g.tooltip_lines.values())


def test_map_failure_is_reported_and_chat_line_still_prints(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    g.g.WorldMapFrame.AddDataProvider = None
    g.login()
    g.ns.capture()
    snap = savedvars.loads(g.saved_text())["WowEyeDB"]["characters"]["Tester-TestRealm"]["snapshot"]
    assert "markers" in snap["errors"]
    assert any("Bow merchant" in s for s in g.g.printed.values())
    assert g.g.waypoint_calls == 1


def test_map_that_refuses_waypoints_is_not_an_error(env):  # noqa: F811
    bridge.set_markers([{**BOW_SHOP, "map_id": 999}])
    g = game_with_inbox()
    assert g.g.waypoint_calls == 0
    assert any("can't set a waypoint" in s for s in g.g.printed.values())


@pytest.mark.parametrize(
    "change, message",
    [
        ({"x": 101}, "x must be"),
        ({"y": -1}, "y must be"),
        ({"x": float("nan")}, "x must be"),
        ({"x": True}, "x must be"),
        ({"map_id": 0}, "map_id"),
        ({"map_id": "37"}, "map_id"),
        ({"label": "  "}, "label"),
    ],
)
def test_bad_markers_are_rejected_and_nothing_is_written(env, change, message):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    with pytest.raises(bridge.BridgeError, match=message):
        bridge.set_markers([{**BOW_SHOP, **change}])
    assert bridge.get_markers()[0]["label"] == "Bow merchant"


def test_too_many_markers(env):  # noqa: F811
    with pytest.raises(bridge.BridgeError, match="Too many"):
        bridge.set_markers([BOW_SHOP] * (bridge.MAX_MARKERS + 1))


def test_messages_and_markers_do_not_overwrite_each_other(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    bridge.send_message("t", "b")
    assert len(bridge.get_markers()) == 1
    bridge.clear_messages()
    assert len(bridge.get_markers()) == 1
    bridge.set_markers([])
    inbox = savedvars.load(bridge.inbox_path())["WowEyeInbox"]
    assert inbox["seq"] == 1 and inbox["markerSeq"] == 2 and inbox["markers"] == {}


def test_cli_mark_add_and_unmark(env, capsys):  # noqa: F811
    assert cli.main(["mark", "37", "45", "39.5", "One", "--zone", "Elwynn"]) == 0
    assert cli.main(["mark", "48", "83", "63", "Two", "--add"]) == 0
    assert [m["label"] for m in bridge.get_markers()] == ["One", "Two"]
    assert bridge.get_markers()[0]["x"] == 45
    assert cli.main(["mark", "48", "83", "63", "Three"]) == 0
    assert [m["label"] for m in bridge.get_markers()] == ["Three"]
    assert cli.main(["unmark"]) == 0
    assert bridge.get_markers() == []
    assert cli.main(["mark", "37", "450", "39", "Bad"]) == 1


def test_keybinding_functions_and_labels_exist(game):
    root = ET.parse(ADDON_DIR / "Bindings.xml").getroot()
    for binding in root:
        assert game.g["BINDING_NAME_" + binding.get("name")]
        function = re.fullmatch(r"\s*(\w+)\(\)\s*", binding.text).group(1)
        assert game.g[function]
    game.g.WowEye_Sync()
    assert game.g.reload_count == 1


def test_toc_and_pin_template_are_consistent():
    lines = (ADDON_DIR / "WowEye.toc").read_text().splitlines()
    files = [ln for ln in lines if ln and not ln.startswith("#")]
    for name in files:
        assert name == "Inbox.lua" or (ADDON_DIR / name).exists(), name
    assert files.index("Pins.lua") < files.index("Pins.xml")
    ET.parse(ADDON_DIR / "Pins.xml")
    assert 'mixin="WowEyePinMixin"' in (ADDON_DIR / "Pins.xml").read_text()
