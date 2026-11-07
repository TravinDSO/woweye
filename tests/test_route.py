import json

import pytest
from conftest import Game
from test_bridge import env  # noqa: F401
from test_markers import game_with_inbox

from wow_eye import bridge, cli, savedvars

KEY = "Tester-TestRealm"
FIRST = {"map_id": 37, "x": 30, "y": 50, "label": "Camp", "zone": "Elwynn", "note": "Head east"}
SECOND = {"map_id": 37, "x": 60, "y": 50, "label": "Quest giver",
          "complete_on": "quest_accepted", "quest_id": 7}
THIRD = {"map_id": 37, "x": 70, "y": 50, "label": "Boss", "complete_on": "quest_complete", "quest_id": 7}
FOURTH = {"map_id": 37, "x": 80, "y": 50, "label": "Turn in", "complete_on": "quest_turned_in", "quest_id": 7}
LAST = {"map_id": 37, "x": 90, "y": 50, "label": "Rest", "complete_on": "manual"}


def started(steps=None, goal="Level up") -> Game:
    bridge.set_route(steps or [FIRST, SECOND], goal)
    return game_with_inbox()


def step_of(g):
    return g.g.WowEyeDB.characters[KEY].route.step


def test_new_route_starts_and_sets_the_waypoint(env):  # noqa: F811
    g = started()
    assert step_of(g) == 1
    assert g.g.last_waypoint.x == pytest.approx(0.3)
    assert any("step 1/2: Camp - Elwynn (30.0, 50.0)" in s for s in g.g.printed.values())
    assert any("Head east" in s for s in g.g.printed.values())


def test_arriving_advances_within_the_radius_only(env):  # noqa: F811
    g = started()
    g.g.player_x = 0.25  # 50 yards away on the fake 1000-yard map
    g.g.run_tickers()
    assert step_of(g) == 1
    g.g.player_x = 0.295  # 5 yards away
    g.g.run_tickers()
    assert step_of(g) == 2
    assert g.g.last_waypoint.x == pytest.approx(0.6)


def test_custom_radius(env):  # noqa: F811
    g = started([{**FIRST, "radius": 100}, SECOND])
    g.g.player_x = 0.25
    g.g.run_tickers()
    assert step_of(g) == 2


def test_being_on_another_map_does_not_advance(env):  # noqa: F811
    g = started()
    g.g.player_map = 99
    g.g.player_x = 0.3
    g.g.run_tickers()
    assert step_of(g) == 1


def test_no_advance_in_combat(env):  # noqa: F811
    g = started()
    g.g.player_x = 0.3
    g.g.in_combat = True
    g.g.run_tickers()
    assert step_of(g) == 1


def test_secret_position_does_not_advance(env):  # noqa: F811
    g = started()
    g.g.player_x = g.g.SECRET
    g.g.run_tickers()
    assert step_of(g) == 1


def test_quest_conditions_ignore_position(env):  # noqa: F811
    g = started([SECOND, THIRD, FOURTH, LAST])
    g.g.player_x = 0.6  # standing on the first step isn't enough
    g.g.run_tickers()
    assert step_of(g) == 1
    g.g.quests_on[7] = True
    g.g.run_tickers()
    assert step_of(g) == 2
    g.g.run_tickers()
    assert step_of(g) == 2
    g.g.quests_ready[7] = True
    g.g.run_tickers()
    assert step_of(g) == 3
    g.g.quests_done[7] = True
    g.g.run_tickers()
    assert step_of(g) == 4


def test_manual_step_only_moves_by_key(env):  # noqa: F811
    g = started([LAST, FIRST])
    g.g.player_x = 0.9
    g.g.run_tickers()
    assert step_of(g) == 1
    g.g.WowEye_RouteNext()
    assert step_of(g) == 2
    g.g.WowEye_RoutePrevious()
    assert step_of(g) == 1
    g.g.WowEye_RoutePrevious()
    assert step_of(g) == 1


def test_finishing_clears_our_waypoint_and_stops(env):  # noqa: F811
    g = started([FIRST])
    g.g.SlashCmdList["WOWEYE"]("next")
    assert g.g.WowEyeDB.characters[KEY].route.done is True
    assert g.g.last_waypoint is None
    assert any("route complete" in s for s in g.g.printed.values())
    assert len(g.g.WorldMapFrame.pins) == 0
    g.g.run_tickers()


def test_finishing_leaves_the_players_own_waypoint(env):  # noqa: F811
    g = started([FIRST])
    g.g.last_waypoint = g.lua.eval("{ mapID = 37, x = 0.99, y = 0.99 }")
    g.g.WowEye_RouteNext()
    assert g.g.last_waypoint.x == pytest.approx(0.99)


def test_only_current_and_later_steps_get_pins(env):  # noqa: F811
    g = started()
    labels = lambda: [p.marker.label for p in g.g.WorldMapFrame.pins.values()]  # noqa: E731
    assert labels() == ["1. Camp", "2. Quest giver"]
    g.g.WowEye_RouteNext()
    assert labels() == ["2. Quest giver"]


def test_clicking_a_route_pin_jumps_there(env):  # noqa: F811
    g = started()
    pin = g.g.WorldMapFrame.pins[2]
    pin.OnMouseUp(pin)
    assert step_of(g) == 2


def test_beacon_shows_the_step_label(env):  # noqa: F811
    g = started()
    g.g.run_tickers()
    assert g.ns.beacon.label.text == "1. Camp (42 yds)"


def test_progress_survives_reload_and_does_not_retake_waypoint(env):  # noqa: F811
    first = started()
    first.g.WowEye_RouteNext()
    inbox = bridge.inbox_path().read_text(encoding="utf-8")
    second = Game(inbox_source=first.saved_text() + "\n" + inbox)
    second.g.last_waypoint = second.lua.eval("{ mapID = 37, x = 0.99, y = 0.99 }")
    second.login(initial=False)
    assert step_of(second) == 2
    assert second.g.waypoint_calls == 0


def test_waypoint_is_restored_if_it_went_missing(env):  # noqa: F811
    first = started()
    inbox = bridge.inbox_path().read_text(encoding="utf-8")
    second = Game(inbox_source=first.saved_text() + "\n" + inbox)
    second.login(initial=False)
    assert second.g.waypoint_calls == 1


def test_new_route_from_agent_restarts(env):  # noqa: F811
    first = started()
    first.g.WowEye_RouteNext()
    saved = first.saved_text()
    bridge.set_route([LAST, FIRST])
    second = Game(inbox_source=saved + "\n" + bridge.inbox_path().read_text(encoding="utf-8"))
    second.login(initial=False)
    assert step_of(second) == 1
    assert second.g.last_waypoint.x == pytest.approx(0.9)


def test_route_wins_over_new_markers(env):  # noqa: F811
    bridge.set_markers([{"map_id": 37, "x": 11, "y": 11, "label": "Marker"}])
    g = started()
    assert g.g.last_waypoint.x == pytest.approx(0.3)
    assert len(g.g.WorldMapFrame.pins) == 3


def test_panel_lists_the_route_literally(env):  # noqa: F811
    g = started([{**FIRST, "label": "|cffff0000x|r"}, SECOND], goal="|Tbad|t")
    g.g.WowEye_RouteNext()
    text = g.ns.formatInbox(g.g.WowEyeInbox)
    assert "||Tbad||t" in text
    assert "done 1. ||cffff0000x||r" in text
    assert ">> 2. Quest giver" in text


def test_no_route_is_a_no_op(game):
    game.g.run_tickers()
    game.g.WowEye_RouteNext()
    assert any("no route" in s for s in game.g.printed.values())
    assert "No messages" in game.ns.formatInbox(game.g.WowEyeInbox)


def test_broken_api_stops_ticking_and_is_reported(env):  # noqa: F811
    g = started()
    g.g.C_Map.GetPlayerMapPosition = None
    g.g.run_tickers()
    g.ns.capture()
    snap = savedvars.loads(g.saved_text())["WowEyeDB"]["characters"][KEY]["snapshot"]
    assert "route" in snap["errors"]


@pytest.mark.parametrize(
    "change, message",
    [
        ({"complete_on": "whenever"}, "complete_on"),
        ({"complete_on": "quest_accepted"}, "quest_id"),
        ({"complete_on": "quest_complete", "quest_id": True}, "quest_id"),
        ({"radius": 0}, "radius"),
        ({"radius": 501}, "radius"),
        ({"x": 101}, "x must be"),
    ],
)
def test_bad_steps_are_rejected_and_nothing_is_written(env, change, message):  # noqa: F811
    bridge.set_route([FIRST], "Keep me")
    with pytest.raises(bridge.BridgeError, match=message):
        bridge.set_route([{**FIRST, **change}])
    status = bridge.route_status()
    assert status["goal"] == "Keep me"
    assert status["steps"][0]["label"] == "Camp"


def test_too_many_steps(env):  # noqa: F811
    with pytest.raises(bridge.BridgeError, match="Too many"):
        bridge.set_route([FIRST] * (bridge.MAX_ROUTE_STEPS + 1))


def test_route_does_not_disturb_messages_or_markers(env):  # noqa: F811
    bridge.send_message("t", "b")
    bridge.set_markers([{"map_id": 37, "x": 1, "y": 1, "label": "M"}])
    bridge.set_route([FIRST])
    bridge.clear_messages()
    assert bridge.get_markers()[0]["label"] == "M"
    assert bridge.route_status()["total_steps"] == 1
    bridge.set_route([])
    status = bridge.route_status()
    assert status["total_steps"] == 0 and status["goal"] is None
    assert status["route_seq"] == 2


def test_route_status_reports_progress_from_saved_data(env, tmp_path):  # noqa: F811
    first = started()
    first.g.WowEye_RouteNext()
    path = env / "WTF" / "Account" / "A" / "SavedVariables" / "WowEye.lua"
    path.parent.mkdir(parents=True)
    path.write_text(first.saved_text(), encoding="utf-8")
    status = bridge.route_status()
    assert status["loaded_in_game"] is True
    assert status["current_step"] == 2
    assert status["current"]["label"] == "Quest giver"
    bridge.set_route([LAST])
    assert bridge.route_status()["loaded_in_game"] is False


def test_cli_route(env, tmp_path, capsys):  # noqa: F811
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps([FIRST, SECOND]))
    assert cli.main(["route", str(steps), "--goal", "Go"]) == 0
    assert cli.main(["route"]) == 0
    assert '"total_steps": 2' in capsys.readouterr().out
    assert cli.main(["route", "--clear"]) == 0
    assert bridge.route_status()["total_steps"] == 0
    steps.write_text("{}")
    assert cli.main(["route", str(steps)]) == 1
    assert cli.main(["route", str(tmp_path / "missing.json")]) == 1
