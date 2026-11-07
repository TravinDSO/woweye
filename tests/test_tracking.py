import pytest
from test_bridge import env  # noqa: F401

from wow_eye import bridge, cli, savedvars

KEY = "Tester-TestRealm"


def db_of(game):
    return savedvars.loads(game.saved_text())["WowEyeDB"]


def rec_of(game):
    return db_of(game)["characters"][KEY]


def save(game, env_dir):
    path = env_dir / "WTF" / "Account" / "A" / "SavedVariables" / "WowEye.lua"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(game.saved_text(), encoding="utf-8")


def test_talking_to_an_npc_records_a_real_location(game):
    game.g.fire("GOSSIP_SHOW")
    npc = db_of(game)["npcs"]["id:1198"]
    assert npc["name"] == "Rallic Finn"
    assert npc["title"] == "Bowyer"
    assert (npc["mapID"], npc["x"], npc["y"]) == (37, 0.25, 0.5)
    assert npc["zone"] == "Elwynn Forest"
    assert npc["roles"] == {"gossip": True}


def test_roles_accumulate_and_location_updates(game):
    game.g.fire("GOSSIP_SHOW")
    game.g.player_x = 0.9
    game.g.now = 2000
    game.g.fire("MERCHANT_SHOW")
    npc = db_of(game)["npcs"]["id:1198"]
    assert npc["roles"] == {"gossip": True, "merchant": True}
    assert npc["x"] == 0.9
    assert (npc["firstSeen"], npc["lastSeen"]) == (1000, 2000)


def test_level_line_is_not_a_title(game):
    game.g.C_TooltipInfo.GetUnit = game.lua.eval(
        'function() return { lines = { { leftText = "X" }, { leftText = "Level 5" } } } end'
    )
    game.g.fire("GOSSIP_SHOW")
    assert "title" not in db_of(game)["npcs"]["id:1198"]


def test_npc_without_usable_guid_is_keyed_by_name(game):
    game.g.npc_guid = None
    game.g.fire("BANKFRAME_OPENED")
    assert db_of(game)["npcs"]["name:Rallic Finn"]["roles"] == {"banker": True}


def test_secret_npc_details_are_not_recorded(game):
    game.g.npc_name = game.g.SECRET
    game.g.fire("GOSSIP_SHOW")
    assert db_of(game)["npcs"] == {}
    game.g.npc_name = "Rallic Finn"
    game.g.npc_guid = game.g.SECRET
    game.g.fire("GOSSIP_SHOW")
    assert list(db_of(game)["npcs"]) == ["name:Rallic Finn"]


def test_secret_position_keeps_npc_without_a_location(game):
    game.g.player_x = game.g.SECRET
    game.g.fire("GOSSIP_SHOW")
    npc = db_of(game)["npcs"]["id:1198"]
    assert npc["name"] == "Rallic Finn"
    assert "x" not in npc


def test_vendor_stock_is_recorded(game):
    game.g.fire("MERCHANT_SHOW")
    vendor = rec_of(game)["vendors"]["id:1198"]
    assert vendor["name"] == "Rallic Finn"
    assert vendor["repairAllCost"] == 42
    assert vendor["itemFilter"] == 1
    item = vendor["items"][0]
    assert (item["name"], item["price"], item["usable"]) == ("Sword", 300, True)
    assert item["stats"] == {"ITEM_MOD_STAMINA_SHORT": 2}


def test_vendor_updates_are_debounced_and_empty_list_keeps_old_stock(game):
    game.g.fire("MERCHANT_SHOW")
    game.g.run_timers()
    before = len(game.g.timers)
    game.g.fire("MERCHANT_UPDATE")
    game.g.fire("MERCHANT_UPDATE")
    assert len(game.g.timers) == before + 1
    game.g.merchant_items = 0
    game.g.run_timers()
    assert len(rec_of(game)["vendors"]["id:1198"]["items"]) == 1


def test_old_vendors_are_dropped_at_the_limit(game):
    for i in range(45):
        game.g.now = 1000 + i
        game.g.npc_guid = f"Creature-0-1-0-12-{i + 1}-0"
        game.g.fire("MERCHANT_SHOW")
    vendors = rec_of(game)["vendors"]
    assert len(vendors) == 40
    assert "id:1" not in vendors
    assert "id:45" in vendors


def test_trainer_offers_skip_headers(game):
    game.g.fire("TRAINER_SHOW")
    trainer = rec_of(game)["trainers"]["id:1198"]
    assert trainer["services"] == [
        {
            "name": "Corruption",
            "rank": "Rank 2",
            "state": "available",
            "level": 10,
            "cost": 500,
            "skill": "Tailoring",
            "skillRank": 40,
            "meetsSkill": False,
        }
    ]
    assert trainer["showing"] == {"available": True, "unavailable": True, "used": False}


def test_flight_paths_with_known_state(game):
    game.g.fire("TAXIMAP_OPENED")
    entry = rec_of(game)["flightPaths"]["map:1415"]
    assert [(n["name"], n["state"]) for n in entry["nodes"]] == [
        ("Stormwind", "Reachable"),
        ("Sentinel Hill", "Unreachable"),
    ]
    assert db_of(game)["npcs"]["id:1198"]["roles"] == {"flight": True}


def test_session_counts_events(game):
    game.g.fire("PLAYER_DEAD")
    game.g.fire("QUEST_ACCEPTED", 7)
    game.g.fire("QUEST_TURNED_IN", 7, 100, 50)
    game.g.fire("PLAYER_LEVEL_UP", 13)
    session = rec_of(game)["session"]
    assert session["deaths"] == 1
    assert session["questsAccepted"] == 1
    assert session["questsTurnedIn"] == 1
    assert session["levelsGained"] == 1


def _set_xp(game, xp, xp_max=900):
    game.g.UnitXP = game.lua.eval(f"function() return {xp} end")
    game.g.UnitXPMax = game.lua.eval(f"function() return {xp_max} end")


def test_xp_counts_across_a_level_up():
    from conftest import Game

    g = Game()
    g.lua.execute("function UnitXP() return 800 end")
    g.login()
    _set_xp(g, 850)
    g.g.fire("PLAYER_XP_UPDATE")
    assert rec_of(g)["session"]["xpGained"] == 50
    _set_xp(g, 20, 1000)
    g.g.fire("PLAYER_XP_UPDATE")
    assert rec_of(g)["session"]["xpGained"] == 120  # 50 to level, then 20


def test_secret_xp_is_skipped(game):
    # The fake's UnitXP starts secret, so nothing can be counted yet.
    game.g.fire("PLAYER_XP_UPDATE")
    assert rec_of(game)["session"]["xpGained"] == 0


def test_time_per_zone_and_combat(game):
    game.g.now = 1060
    game.ns.sessionTouch()
    game.g.GetRealZoneText = game.lua.eval('function() return "Westfall" end')
    game.g.now = 1090
    game.ns.sessionTouch()
    game.g.fire("PLAYER_REGEN_DISABLED")
    game.g.now = 1100
    game.g.fire("PLAYER_REGEN_ENABLED")
    session = rec_of(game)["session"]
    assert session["zoneSeconds"] == {"Elwynn Forest": 60, "Westfall": 30}
    assert session["combatSeconds"] == 10


def test_long_gaps_are_not_counted_as_play_time(game):
    game.g.now = 1000 + 3600
    game.ns.sessionTouch()
    assert rec_of(game)["session"]["zoneSeconds"] == {}


def test_reload_continues_the_session_and_login_starts_a_new_one(game):
    from conftest import Game

    game.g.fire("PLAYER_DEAD")
    reloaded = Game(inbox_source=game.saved_text())
    reloaded.login(initial=False)
    assert rec_of(reloaded)["session"]["deaths"] == 1
    assert rec_of(reloaded)["sessions"] == {}

    relogged = Game(inbox_source=reloaded.saved_text())
    relogged.login(initial=True)
    assert rec_of(relogged)["session"]["deaths"] == 0
    assert rec_of(relogged)["sessions"][0]["deaths"] == 1


def test_session_history_is_capped():
    from conftest import Game

    g = Game()
    g.login()
    for _ in range(25):
        next_game = Game(inbox_source=g.saved_text())
        next_game.login(initial=True)
        g = next_game
    assert len(rec_of(g)["sessions"]) == 20


def test_broken_api_is_reported_and_other_tracking_continues(game):
    game.g.GetMerchantNumItems = None
    game.g.fire("MERCHANT_SHOW")
    game.g.fire("TRAINER_SHOW")
    game.ns.capture()
    rec = rec_of(game)
    assert "vendors" in rec["snapshot"]["errors"]
    assert "id:1198" in rec["trainers"]


def test_bridge_finds_npcs_by_query_role_and_map(game, env):  # noqa: F811
    game.g.fire("MERCHANT_SHOW")
    game.g.npc_name = "Marshal Dughan"
    game.g.npc_title = "Marshal"
    game.g.npc_guid = "Creature-0-1-0-12-240-0"
    game.g.now = 2000
    game.g.player_map = 50
    game.g.fire("QUEST_DETAIL")
    save(game, env)

    assert [n["name"] for n in bridge.npcs()] == ["Marshal Dughan", "Rallic Finn"]
    bowyer = bridge.npcs("bowyer")
    assert [n["name"] for n in bowyer] == ["Rallic Finn"]
    assert bowyer[0]["x_percent"] == 25.0
    assert bowyer[0]["roles"] == ["merchant"]
    assert [n["name"] for n in bridge.npcs(role="quest")] == ["Marshal Dughan"]
    assert [n["name"] for n in bridge.npcs(map_id=37)] == ["Rallic Finn"]
    assert len(bridge.npcs(limit=1)) == 1


def test_bridge_vendors_trainers_and_flights(game, env):  # noqa: F811
    game.g.fire("MERCHANT_SHOW")
    game.g.fire("TRAINER_SHOW")
    game.g.fire("TAXIMAP_OPENED")
    save(game, env)
    assert bridge.vendors("rallic")[0]["items"][0]["price"] == 300
    assert bridge.vendors("nobody") == []
    assert bridge.trainers()[0]["services"][0]["cost"] == 500
    assert bridge.flight_paths()[0]["mapID"] == 1415


def test_bridge_session_summary(game, env):  # noqa: F811
    from conftest import Game

    g = Game()
    g.lua.execute("function UnitXP() return 100 end")
    g.login()
    _set_xp(g, 700)
    g.g.fire("PLAYER_XP_UPDATE")
    g.g.fire("PLAYER_DEAD")
    g.g.now = 1000 + 299
    g.ns.sessionTouch()
    g.g.now = 1000 + 598
    g.ns.sessionTouch()
    g.g.GetMoney = g.lua.eval("function() return 12445 end")
    g.g.now = 1000 + 897
    g.ns.sessionTouch()
    save(g, env)
    current = bridge.session()["current"]
    assert current["xp_gained"] == 600
    assert current["minutes"] == pytest.approx(15, abs=0.1)
    assert current["xp_per_hour"] == pytest.approx(2408, abs=5)
    assert current["money_change_copper"] == 100
    assert current["deaths"] == 1
    assert current["zone_minutes"]["Elwynn Forest"] == pytest.approx(15, abs=0.1)


def test_session_rate_is_withheld_for_very_short_sessions(game, env):  # noqa: F811
    game.g.now = 1030
    game.ns.sessionTouch()
    save(game, env)
    assert bridge.session()["current"]["xp_per_hour"] is None


def test_cli_lookups(game, env, capsys):  # noqa: F811
    game.g.fire("MERCHANT_SHOW")
    save(game, env)
    for command in (["npcs", "rallic", "--role", "merchant"], ["vendors"], ["trainers"], ["flights"], ["session"]):
        assert cli.main(command) == 0
    assert "Rallic Finn" in capsys.readouterr().out
