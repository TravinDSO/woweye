from conftest import Game

from wow_eye import savedvars


def db_of(game):
    return savedvars.loads(game.saved_text())["WowEyeDB"]


def test_snapshot_round_trips_through_saved_variables(game):
    assert game.ns.capture() is True
    snap = db_of(game)["characters"]["Tester-TestRealm"]["snapshot"]
    assert snap["identity"]["level"] == 12
    assert snap["identity"]["interface"] == 16001
    assert snap["location"]["zone"] == "Elwynn Forest"
    assert snap["location"]["x"] == 0.25
    assert snap["money"] == 12345
    assert snap["quests"][0]["title"] == 'Kill "Wolves"'
    assert snap["quests"][0]["objectives"][0]["text"] == "Wolves: 2/8"
    sword = snap["equipment"]["16"]
    assert sword["link"].endswith("[Sword]|h")
    assert sword["itemLevel"] == 12
    assert sword["stats"] == {"ITEM_MOD_STAMINA_SHORT": 2}
    assert (sword["durability"], sword["maxDurability"]) == (40, 50)
    assert snap["bags"]["freeSlots"] == 1
    assert snap["bags"]["totalSlots"] == 2
    assert snap["bags"]["items"][0]["count"] == 3
    assert snap["bags"]["items"][0]["equipLoc"] == "INVTYPE_WEAPON"
    assert "errors" not in snap


def test_quest_details_and_locations(game):
    game.ns.capture()
    quest = db_of(game)["characters"]["Tester-TestRealm"]["snapshot"]["quests"][0]
    assert quest["description"] == "Wolves are a problem."
    assert quest["objectiveText"] == "Kill 8 wolves."
    assert quest["waypoint"] == {"mapID": 37, "x": 0.4, "y": 0.6, "text": "Go to the forest"}
    assert quest["mapPin"] == {"mapID": 37, "x": 0.41, "y": 0.61}
    assert quest["rewards"]["xp"] == 250
    assert quest["rewards"]["money"] == 75
    assert quest["rewards"]["items"][0]["id"] == 99
    assert [c["usable"] for c in quest["rewards"]["choices"]] == [True, False]


def test_quest_text_is_only_fetched_once(game):
    game.ns.capture()
    game.ns.capture()
    assert game.g.quest_text_calls == 1


def test_a_missing_quest_detail_keeps_the_quest(game):
    game.g.C_QuestLog.GetNextWaypoint = None
    game.g.GetQuestLogQuestText = None
    game.g.GetQuestLogRewardXP = None
    game.ns.capture()
    snap = db_of(game)["characters"]["Tester-TestRealm"]["snapshot"]
    assert snap["quests"][0]["title"] == 'Kill "Wolves"'
    assert "waypoint" not in snap["quests"][0]
    assert "errors" not in snap


def test_character_profile(game):
    game.ns.capture()
    snap = db_of(game)["characters"]["Tester-TestRealm"]["snapshot"]
    assert snap["identity"]["restedXP"] == 600
    assert snap["identity"]["hearthstone"] == "Goldshire"
    assert snap["spells"]["known"][0]["name"] == "Corruption"
    assert snap["spells"]["future"] == [
        {"name": "Drain Soul", "rank": "", "id": 1120, "tab": "Affliction", "passive": False, "level": 10}
    ]
    assert snap["talents"]["chosen"] == [
        {"name": "Improved Corruption", "spellID": 700, "rank": 2, "maxRank": 5}
    ]
    assert snap["talents"]["unspent"] == [3]
    assert [p["name"] for p in snap["professions"]] == ["Tailoring", "Cooking"]
    assert snap["reputation"]["factions"][0]["name"] == "Stormwind"
    assert snap["reputation"]["collapsedHeaders"] == 1


def test_uncached_item_is_marked_pending(game):
    game.g.GetInventoryItemLink = game.lua.eval('function() return "|Hitem:1|h[Uncached]|h" end')
    game.ns.capture()
    item = db_of(game)["characters"]["Tester-TestRealm"]["snapshot"]["equipment"]["1"]
    assert item["pending"] is True
    assert "[Uncached]" in item["link"]


def test_secret_values_are_dropped_and_counted(game):
    game.ns.capture()
    snap = db_of(game)["characters"]["Tester-TestRealm"]["snapshot"]
    assert "xp" not in snap["identity"]
    assert snap["identity"]["xpMax"] == 900
    assert snap["redacted"] == 1


def test_no_capture_during_combat(game):
    game.g.in_combat = True
    assert game.ns.capture() is False
    assert "snapshot" not in db_of(game)["characters"]["Tester-TestRealm"]


def test_capture_waits_for_timer_and_debounces(game):
    game.g.fire("QUEST_LOG_UPDATE")
    game.g.fire("PLAYER_MONEY")
    game.g.fire("QUEST_LOG_UPDATE")
    # One capture, plus one marker list refresh: each burst is gathered into a single timer.
    assert len(game.g.timers) == 2
    game.g.run_timers()
    assert "snapshot" in db_of(game)["characters"]["Tester-TestRealm"]


def test_a_broken_api_only_costs_its_own_section(game):
    game.g.GetMoney = None
    game.ns.capture()
    snap = db_of(game)["characters"]["Tester-TestRealm"]["snapshot"]
    assert "money" in snap["errors"]
    assert snap["location"]["zone"] == "Elwynn Forest"


def test_unknown_event_does_not_stop_registration():
    known = ["ADDON_LOADED", "PLAYER_LOGIN", "PLAYER_MONEY"]
    g = Game(known_events=known)
    g.login()
    g.ns.capture()
    snap = db_of(g)["characters"]["Tester-TestRealm"]["snapshot"]
    assert "QUEST_ACCEPTED" in snap["unknownEvents"]
    g.g.fire("PLAYER_MONEY")
    assert len(g.g.timers) == 1


def test_events_are_logged_and_capped(game):
    game.g.fire("QUEST_ACCEPTED", 7)
    log = db_of(game)["characters"]["Tester-TestRealm"]["events"]
    assert log == [{"t": 1000, "e": "QUEST_ACCEPTED", "args": [7]}]
    for i in range(250):
        game.g.fire("PLAYER_LEVEL_UP", i)
    log = db_of(game)["characters"]["Tester-TestRealm"]["events"]
    assert len(log) == 200
    assert log[-1]["args"] == [249]


def test_secret_event_args_are_dropped(game):
    game.g.fire("QUEST_ACCEPTED", game.g.SECRET)
    log = db_of(game)["characters"]["Tester-TestRealm"]["events"]
    assert log[0]["e"] == "QUEST_ACCEPTED"
    assert log[0]["args"] == {}


def test_sync_captures_then_reloads(game):
    game.g.SlashCmdList["WOWEYE"]("sync")
    assert game.g.reload_count == 1
    assert "snapshot" in db_of(game)["characters"]["Tester-TestRealm"]


def test_sync_refused_in_combat(game):
    game.g.in_combat = True
    game.g.SlashCmdList["WOWEYE"]("sync")
    assert game.g.reload_count == 0


def test_saved_data_survives_reload():
    first = Game()
    first.login()
    first.ns.capture()
    saved = first.saved_text()
    second = Game(inbox_source=saved)
    second.login()
    assert "snapshot" in db_of(second)["characters"]["Tester-TestRealm"]


def test_panel_opens_and_marks_messages_read():
    inbox = 'WowEyeInbox = { seq = 3, messages = { { title = "a", body = "b" } } }'
    g = Game(inbox_source=inbox)
    g.login()
    assert any("new messages" in s for s in g.g.printed.values())
    g.g.SlashCmdList["WOWEYE"]("")
    assert g.g.WowEyeDB.lastInboxSeq == 3
