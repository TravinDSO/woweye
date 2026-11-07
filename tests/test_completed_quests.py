import pytest
from test_bridge import env  # noqa: F401
from test_tracking import rec_of, save

from wow_eye import bridge, cli

STEP = {"map_id": 37, "x": 10, "y": 10, "label": "Old quest", "complete_on": "quest_accepted", "quest_id": 62}


def test_capture_saves_the_list_outside_the_snapshot(game):
    game.ns.capture()
    rec = rec_of(game)
    assert rec["completedQuests"] == {"at": 1000, "ids": [7, 62, 91775]}
    assert "completedQuests" not in rec["snapshot"]


def test_sync_includes_a_quest_just_finished(game):
    game.ns.capture()
    game.g.completed_ids[4] = 500
    game.g.SlashCmdList["WOWEYE"]("sync")
    assert 500 in rec_of(game)["completedQuests"]["ids"]


def test_broken_api_is_reported_and_snapshot_still_works(game):
    game.g.C_QuestLog.GetAllCompletedQuestIDs = None
    game.ns.capture()
    rec = rec_of(game)
    assert "completedQuests" in rec["snapshot"]["errors"]
    assert rec["snapshot"]["money"] == 12345


def test_bridge_checks_specific_quests(game, env):  # noqa: F811
    game.ns.capture()
    save(game, env)
    result = bridge.completed_quests([62, 99, 91775])
    assert result["completed"] == [62, 91775]
    assert result["not_completed"] == [99]
    assert result["total"] == 3


def test_bridge_returns_whole_list_and_status_count(game, env):  # noqa: F811
    game.ns.capture()
    save(game, env)
    assert bridge.completed_quests()["completed"] == [7, 62, 91775]
    assert bridge.status()["completed_quests"] == 3


def test_empty_list_is_valid(game, env):  # noqa: F811
    game.g.completed_ids = game.lua.eval("{}")
    game.ns.capture()
    save(game, env)
    assert bridge.completed_quests([62])["not_completed"] == [62]


def test_before_any_sync_is_a_clear_error(game, env):  # noqa: F811
    save(game, env)
    with pytest.raises(bridge.BridgeError, match="eye sync"):
        bridge.completed_quests()


def test_route_warns_about_completed_quests_but_still_saves(game, env):  # noqa: F811
    game.ns.capture()
    save(game, env)
    result = bridge.set_route([STEP, {**STEP, "quest_id": 99, "label": "New quest"}])
    assert result["warnings"] == ["Step 1 (Old quest): quest 62 is already completed"]
    assert bridge.route_status()["total_steps"] == 2


def test_route_has_no_warning_without_completed_data(env):  # noqa: F811
    assert "warnings" not in bridge.set_route([STEP])


def test_cli_completed(game, env, capsys):  # noqa: F811
    game.ns.capture()
    save(game, env)
    assert cli.main(["completed", "62", "99"]) == 0
    out = capsys.readouterr().out
    assert '"not_completed"' in out and "99" in out
