import pytest
from conftest import Game
from test_bridge import env  # noqa: F401
from test_markers import BOW_SHOP, ELSEWHERE, game_with_inbox
from test_route import FIRST, SECOND, step_of

from wow_eye import bridge


def shown_rows(g):
    rows = g.ns.markerListRows
    return [rows[i] for i in range(1, len(rows) + 1) if rows[i].IsShown()]


def labels(g):
    return [row.label.text for row in shown_rows(g)]


def test_no_markers_means_no_list():
    g = Game()
    g.login()
    assert not g.ns.markerList.IsShown()
    assert "markerList" not in g.ns.errors


def test_lists_route_steps_then_markers_with_zone_and_coordinates(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP, ELSEWHERE])
    bridge.set_route([FIRST, SECOND], "Level up")
    g = game_with_inbox()
    assert g.ns.markerList.IsShown()
    assert labels(g) == ["1. Camp", "2. Quest giver", "Bow merchant", "Other"]
    assert [row.where.text for row in shown_rows(g)] == [
        "Elwynn (30.0, 50.0)",
        "map 37 (60.0, 50.0)",
        "Elwynn (45.0, 39.5)",
        "map 48 (83.0, 63.0)",
    ]
    assert g.ns.markerList.header.text.text == "WoW Eye"


def test_current_waypoint_is_marked_active(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP, ELSEWHERE])
    g = game_with_inbox()
    assert [row.entry.active for row in shown_rows(g)] == [True, False]


def test_clicking_a_marker_sets_the_waypoint_and_moves_the_highlight(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP, ELSEWHERE])
    g = game_with_inbox()
    row = shown_rows(g)[1]
    row.scripts.OnClick(row)
    assert g.g.last_waypoint.mapID == 48
    assert g.g.last_waypoint.x == pytest.approx(0.83)
    g.g.fire("USER_WAYPOINT_UPDATED")
    assert [r.entry.active for r in shown_rows(g)] == [False, True]


def test_clicking_a_route_step_moves_the_route(env):  # noqa: F811
    bridge.set_route([FIRST, SECOND])
    g = game_with_inbox()
    second = shown_rows(g)[1]
    second.scripts.OnClick(second)
    assert step_of(g) == 2
    assert labels(g) == ["2. Quest giver"]


def test_finished_steps_drop_off_the_list(env):  # noqa: F811
    bridge.set_route([FIRST, SECOND])
    g = game_with_inbox()
    g.g.player_x = 0.3
    g.g.run_tickers()
    assert labels(g) == ["2. Quest giver"]


def test_header_collapses_and_remembers(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP, ELSEWHERE])
    g = game_with_inbox()
    header = g.ns.markerList.header
    header.scripts.OnClick(header)
    assert g.g.WowEyeDB.markerListCollapsed is True
    assert not g.ns.markerList.content.IsShown()
    assert header.text.text == "WoW Eye (2)"
    header.scripts.OnClick(header)
    assert g.ns.markerList.content.IsShown()
    assert header.text.text == "WoW Eye"


def test_slash_command_hides_and_shows_the_list(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = game_with_inbox()
    g.g.SlashCmdList["WOWEYE"]("list")
    assert not g.ns.markerList.IsShown()
    assert g.g.WowEyeDB.markerList is False
    g.g.SlashCmdList["WOWEYE"]("list")
    assert g.ns.markerList.IsShown()


def test_agent_text_is_shown_literally(env):  # noqa: F811
    bridge.set_markers([{**BOW_SHOP, "label": "|cffff0000x|r", "zone": "|Hlink|h"}])
    g = game_with_inbox()
    row = shown_rows(g)[0]
    assert row.label.text == "||cffff0000x||r"
    assert row.where.text.startswith("||Hlink||h")


def test_a_list_failure_leaves_pins_and_waypoint_working(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = game_with_inbox()
    g.ns.markerListEntries = None
    g.ns.refreshPins()
    assert "markerList" in g.ns.errors
    assert len(g.g.WorldMapFrame.pins) == 1
    assert g.g.last_waypoint.mapID == 37


FAKE_TRACKER_OPACITY = r'''
function hooksecurefunc(t, name, hook)
    local original = t[name]
    t[name] = function(...)
        original(...)
        hook(...)
    end
end
ObjectiveTrackerManager = {
    backgroundAlpha = 0.5,
    SetOpacity = function(self, opacity) self.backgroundAlpha = (opacity or 0) / 100 end,
}
'''


def game_with_tracker() -> Game:
    g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    g.lua.execute(FAKE_TRACKER_OPACITY)
    g.login()
    return g


def test_background_starts_at_the_tracker_opacity(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = game_with_tracker()
    assert g.ns.markerList.backgroundAlpha == pytest.approx(0.5)


def test_background_follows_edit_mode_opacity_changes(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = game_with_tracker()
    manager = g.g.ObjectiveTrackerManager
    manager.SetOpacity(manager, 80)
    assert g.ns.markerList.backgroundAlpha == pytest.approx(0.8)
    manager.SetOpacity(manager, 0)
    assert g.ns.markerList.backgroundAlpha == 0


def test_background_is_clear_without_a_tracker(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = game_with_inbox()
    assert g.ns.markerList.backgroundAlpha == 0


def test_header_button_toggles_the_beacon(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = game_with_inbox()
    button = g.ns.markerList.header.beacon
    assert button.on is True
    button.scripts.OnClick(button)
    assert g.g.WowEyeDB.beacon is False
    assert button.on is False
    g.g.run_tickers()
    assert g.ns.beacon is None or not g.ns.beacon.IsShown()
    button.scripts.OnClick(button)
    assert g.g.WowEyeDB.beacon is True
    assert button.on is True
    g.g.run_tickers()
    assert g.ns.beacon.IsShown()


def test_slash_beacon_updates_the_header_button(env):  # noqa: F811
    bridge.set_markers([BOW_SHOP])
    g = game_with_inbox()
    g.g.SlashCmdList["WOWEYE"]("beacon")
    assert g.ns.markerList.header.beacon.on is False
