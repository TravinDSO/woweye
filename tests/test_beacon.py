from conftest import Game
from test_bridge import env  # noqa: F401
from test_markers import BOW_SHOP, ELSEWHERE, game_with_inbox

from wow_eye import bridge, savedvars


def tracked_game() -> Game:
    bridge.set_markers([BOW_SHOP, ELSEWHERE])
    return game_with_inbox()


def same_table(g, a, b) -> bool:
    return g.lua.eval("rawequal")(a, b)


def tick(g):
    g.g.run_tickers()
    return g.ns.beacon


def test_beacon_follows_the_tracked_marker(env):  # noqa: F811
    g = tracked_game()
    beacon = tick(g)
    assert beacon.IsShown()
    assert same_table(g, beacon.anchor, g.g.nav_frame)
    assert beacon.label.text == "Bow merchant (42 yds)"
    beacon.scripts.OnUpdate(beacon)


def test_label_shows_the_marker_now_tracked(env):  # noqa: F811
    g = tracked_game()
    tick(g)
    g.ns.setWaypoint(g.g.WowEyeInbox.markers[2])
    assert tick(g).label.text == "Other (42 yds)"


def test_hidden_when_tracking_something_else(env):  # noqa: F811
    g = tracked_game()
    assert tick(g).IsShown()
    g.g.supertracked = False
    assert not tick(g).IsShown()


def test_hidden_for_a_waypoint_that_is_not_ours(env):  # noqa: F811
    g = tracked_game()
    assert tick(g).IsShown()
    g.g.last_waypoint = g.lua.eval("{ mapID = 37, x = 0.9, y = 0.9 }")
    assert not tick(g).IsShown()


def test_hidden_in_combat_and_returns_after(env):  # noqa: F811
    g = tracked_game()
    assert tick(g).IsShown()
    g.g.in_combat = True
    assert not tick(g).IsShown()
    g.g.in_combat = False
    assert tick(g).IsShown()


def test_hidden_without_a_screen_position(env):  # noqa: F811
    g = tracked_game()
    assert tick(g).IsShown()
    g.g.nav_valid = False
    assert not tick(g).IsShown()
    g.g.nav_valid = True
    g.g.nav_frame = None
    assert not tick(g).IsShown()


def test_reanchors_when_the_game_replaces_the_frame(env):  # noqa: F811
    g = tracked_game()
    tick(g)
    g.g.nav_frame = g.lua.eval("{}")
    assert same_table(g, tick(g).anchor, g.g.nav_frame)


def test_distance_is_left_out_if_secret_or_missing(env):  # noqa: F811
    g = tracked_game()
    g.g.nav_distance = g.g.SECRET
    assert tick(g).label.text == "Bow merchant"
    g.g.C_Navigation.GetDistance = None
    assert tick(g).label.text == "Bow merchant"


def test_label_is_literal(env):  # noqa: F811
    bridge.set_markers([{**BOW_SHOP, "label": "|cffff0000x|r"}])
    g = game_with_inbox()
    assert tick(g).label.text.startswith("||cffff0000x||r")


def test_toggle_persists_and_hides(env):  # noqa: F811
    g = tracked_game()
    assert tick(g).IsShown()
    g.g.SlashCmdList["WOWEYE"]("beacon")
    assert g.g.WowEyeDB.beacon is False
    assert not g.ns.beacon.IsShown()
    assert not tick(g).IsShown()
    g.g.SlashCmdList["WOWEYE"]("beacon")
    assert tick(g).IsShown()


def test_broken_api_stops_ticking_and_reports_once(env):  # noqa: F811
    g = tracked_game()
    g.g.C_Navigation.GetFrame = None
    g.g.run_tickers()
    assert any(t.cancelled for t in g.g.tickers.values())
    g.ns.capture()
    db = savedvars.loads(g.saved_text())["WowEyeDB"]
    assert "markers" in db["characters"]["Tester-TestRealm"]["snapshot"]["errors"]


def beacon_shown(g) -> bool:
    beacon = tick(g)
    return beacon is not None and beacon.IsShown()


QUEST_TRACKING = r'''
tracked_quest = nil
priority = nil
C_SuperTrack.IsSuperTrackingQuest = function() return tracked_quest ~= nil end
C_SuperTrack.GetSuperTrackedQuestID = function() return tracked_quest or 0 end
C_SuperTrack.GetHighestPrioritySuperTrackingType = function() return priority end
C_QuestLog.GetTitleForQuestID = function(id)
    if id == 1688 then return "Surena Caledon" end
    if id == 66 then return "|cffff0000Red|r" end
end
'''


def quest_game(markers=True) -> Game:
    if markers:
        bridge.set_markers([BOW_SHOP])
        g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    else:
        g = Game()
    g.lua.execute(QUEST_TRACKING)
    g.login()
    return g


def test_selected_quest_gets_the_beacon(env):  # noqa: F811
    g = quest_game(markers=False)
    assert not beacon_shown(g)
    g.g.tracked_quest = 1688
    g.g.priority = 0
    beacon = tick(g)
    assert beacon.IsShown()
    assert beacon.label.text == "Surena Caledon (42 yds)"


def test_beacon_follows_what_the_game_tracks_first(env):  # noqa: F811
    g = quest_game()
    g.g.tracked_quest = 1688
    g.g.priority = 1
    assert tick(g).label.text == "Bow merchant (42 yds)"
    g.g.priority = 0
    assert tick(g).label.text == "Surena Caledon (42 yds)"


def test_other_tracked_things_get_no_beacon(env):  # noqa: F811
    g = quest_game()
    g.g.tracked_quest = 1688
    g.g.priority = 2  # a corpse
    assert not beacon_shown(g)


def test_without_a_priority_api_markers_come_before_quests(env):  # noqa: F811
    g = quest_game()
    g.g.C_SuperTrack.GetHighestPrioritySuperTrackingType = None
    g.g.tracked_quest = 1688
    assert tick(g).label.text == "Bow merchant (42 yds)"
    g.g.supertracked = False
    assert tick(g).label.text == "Surena Caledon (42 yds)"


def test_quest_title_is_literal_and_has_a_fallback(env):  # noqa: F811
    g = quest_game(markers=False)
    g.g.priority = 0
    g.g.tracked_quest = 66
    assert tick(g).label.text.startswith("||cffff0000Red||r")
    g.g.tracked_quest = 5
    assert tick(g).label.text == "Quest (42 yds)"


def test_quest_beacon_hides_in_combat(env):  # noqa: F811
    g = quest_game(markers=False)
    g.g.priority = 0
    g.g.tracked_quest = 1688
    g.g.in_combat = True
    assert not beacon_shown(g)


def test_keybinding_toggles_the_beacon(env):  # noqa: F811
    g = tracked_game()
    assert tick(g).IsShown()
    g.g.WowEye_ToggleBeacon()
    assert g.g.WowEyeDB.beacon is False
    assert not tick(g).IsShown()
    g.g.WowEye_ToggleBeacon()
    assert tick(g).IsShown()
