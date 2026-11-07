import math

import pytest
from conftest import Game
from test_bridge import env  # noqa: F401
from test_marker_list import labels, shown_rows
from test_markers import BOW_SHOP, ELSEWHERE

from wow_eye import bridge

# A flat world: map 37 is a 1000-yard square on continent 0, map 48 is on continent 1.
# World x points north and world y points west, as in the game.
FAKE_WORLD = r'''
watched = {}
quest_titles = { [1688] = "Surena Caledon", [109] = "Report to Gryan Stoutmantle" }
quest_waypoints = { [109] = { 37, 0.25, 0.30 } }
quest_pois = { [1688] = { 0.71, 0.81 } }
C_QuestLog.GetNumQuestWatches = function() return #watched end
C_QuestLog.GetQuestIDForQuestWatchIndex = function(i) return watched[i] end
C_QuestLog.GetQuestWatchType = function(id)
    for _, w in ipairs(watched) do if w == id then return 0 end end
end
C_QuestLog.GetTitleForQuestID = function(id) return quest_titles[id] end
C_QuestLog.GetNextWaypoint = function(id)
    local w = quest_waypoints[id]
    if w then return w[1], w[2], w[3] end
end
C_QuestLog.GetQuestsOnMap = function(mapID)
    local out = {}
    if mapID == 37 then
        for id, p in pairs(quest_pois) do out[#out + 1] = { questID = id, x = p[1], y = p[2] } end
    end
    return out
end

facing = 0
function GetPlayerFacing() return facing end
function CreateVector2D(x, y) return { x = x, y = y } end
C_Map.GetWorldPosFromMapPos = function(mapID, v)
    local continent = (mapID == 48) and 1 or 0
    return continent, { x = -v.y * 1000, y = -v.x * 1000 }
end

menu_handlers = {}
Menu = { ModifyMenu = function(tag, fn) menu_handlers[tag] = fn end }
function open_menu(tag, owner)
    local m = { checks = {}, dividers = 0 }
    m.CreateDivider = function(self) self.dividers = self.dividers + 1 end
    m.CreateCheckbox = function(self, text, isSelected, setSelected)
        self.checks[#self.checks + 1] = { text = text, isSelected = isSelected, setSelected = setSelected }
    end
    menu_handlers[tag](owner, m)
    return m
end
-- What the mouse is over when a tracker quest is right-clicked: its header, inside its block.
tracker_block = { id = 1688, parentModule = {} }
mouse_focus = { GetParent = function() return tracker_block end }
function GetMouseFoci() return { mouse_focus } end
'''

KEY = "Tester-TestRealm"
BAR_CENTER = 320
BAR_REACH = 308  # pixels from the center to 90 degrees off
MERCHANT = math.atan2(-200, 105)  # bearing to the Bow merchant: 105 yards north, 200 east


def world_game(markers=None, watched=()) -> Game:
    if markers:
        bridge.set_markers(markers)
        g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    else:
        g = Game()
    g.lua.execute(FAKE_WORLD)
    g.g.watched = g.lua.table_from(list(watched))
    g.login()
    g.g.run_timers()
    return g


def row_named(g, label):
    return next(r for r in shown_rows(g) if r.label.text == label)


def toggle_row(g, label):
    button = row_named(g, label).compass
    button.scripts.OnClick(button)


def slots(g):
    found = g.ns.compassSlots
    return [found[i] for i in range(1, len(found) + 1) if found[i].IsShown()]


def slot_for(g, name):
    return next(s for s in slots(g) if s.entry.label == name)


def heading(g, text):
    return next(h for h in g.ns.compassHeadings.values() if h.text == text)


def tracker_checkbox(g):
    menu = g.g.open_menu("MENU_QUEST_OBJECTIVE_TRACKER", g.lua.eval("{}"))
    return menu.checks[1] if len(menu.checks) else None


def tick(g):
    g.g.run_tickers()
    return g.ns.compass


def test_bar_shows_headings_even_with_nothing_to_follow():
    g = world_game()
    assert tick(g).IsShown()
    assert heading(g, "N").x == pytest.approx(BAR_CENTER)
    assert heading(g, "W").x == pytest.approx(BAR_CENTER - BAR_REACH)
    assert heading(g, "E").x == pytest.approx(BAR_CENTER + BAR_REACH)
    assert heading(g, "NE").x == pytest.approx(BAR_CENTER + BAR_REACH / 2)
    assert g.lua.eval("rawget")(heading(g, "S"), "x") is None


def test_headings_turn_with_the_player():
    g = world_game()
    g.g.facing = -math.pi / 2  # facing east, so north is on the left
    tick(g)
    assert heading(g, "E").x == pytest.approx(BAR_CENTER)
    assert heading(g, "N").x == pytest.approx(BAR_CENTER - BAR_REACH)
    assert heading(g, "S").x == pytest.approx(BAR_CENTER + BAR_REACH)


def test_wow_eye_entries_and_tracked_quests_are_on_by_default(env):  # noqa: F811
    g = world_game([BOW_SHOP], watched=[1688, 109])
    tick(g)
    assert sorted(s.entry.label for s in slots(g)) == [
        "Bow merchant", "Report to Gryan Stoutmantle", "Surena Caledon"]
    assert labels(g) == ["Bow merchant"]  # quests aren't repeated in the list


def test_a_target_slides_along_the_bar_as_the_player_turns(env):  # noqa: F811
    g = world_game([BOW_SHOP])
    tick(g)
    merchant = slot_for(g, "Bow merchant")
    assert merchant.x == pytest.approx(BAR_CENTER - MERCHANT / (math.pi / 2) * BAR_REACH)
    assert merchant.label.text == "Bow merchant  225 yds"
    assert merchant.yards == pytest.approx(math.hypot(105, 200))

    g.g.facing = MERCHANT
    tick(g)
    assert slot_for(g, "Bow merchant").x == pytest.approx(BAR_CENTER)


def test_a_target_behind_is_pinned_to_the_end_to_turn_to(env):  # noqa: F811
    g = world_game([BOW_SHOP])
    g.g.facing = math.pi  # facing south, the merchant is behind on the left
    tick(g)
    merchant = slot_for(g, "Bow merchant")
    assert merchant.side == "left"
    assert merchant.x == pytest.approx(12)
    assert merchant.label.text == "< Bow merchant  225 yds"


def test_targets_at_the_same_spot_share_one_pin_and_label(env):  # noqa: F811
    near = {**BOW_SHOP, "x": 46.0, "label": "Next door"}
    g = world_game([BOW_SHOP, near])
    tick(g)
    [slot] = slots(g)
    assert slot.count == 2
    assert slot.entry.label == "Bow merchant"  # the nearer one names the group
    assert slot.label.text == "Bow merchant  225 yds  +1"


def test_the_tracked_target_names_its_group(env):  # noqa: F811
    near = {**BOW_SHOP, "x": 46.0, "label": "Next door"}
    g = world_game([near, BOW_SHOP])  # the first marker becomes the waypoint
    tick(g)
    assert slots(g)[0].label.text.startswith("Next door")


def test_overlapping_labels_take_a_second_row_and_then_drop(env):  # noqa: F811
    west = [{**BOW_SHOP, "x": 40.0, "label": "Middle"}, {**BOW_SHOP, "x": 35.0, "label": "Left"}]
    g = world_game([BOW_SHOP, *west])
    tick(g)
    rows = {s.entry.label: g.lua.eval("rawget")(s, "row") for s in slots(g)}
    assert rows == {"Left": 0, "Middle": 1, "Bow merchant": None}
    dropped = slot_for(g, "Bow merchant")
    assert not dropped.labelHit.IsShown()
    assert dropped.IsShown()  # its pin stays


def test_long_names_are_shortened_on_the_bar(env):  # noqa: F811
    g = world_game([{**BOW_SHOP, "label": "A very long marker name that goes on"}])
    tick(g)
    assert slots(g)[0].label.text == "A very long marker name ...  225 yds"


def test_hovering_a_pin_lists_every_target_there(env):  # noqa: F811
    near = {**BOW_SHOP, "x": 46.0, "label": "Next door", "note": "Knock first"}
    g = world_game([BOW_SHOP, near])
    tick(g)
    slot = slots(g)[0]
    slot.scripts.OnEnter(slot)
    lines = list(g.g.tooltip_lines.values())
    assert lines[0] == "2 targets this way"
    assert "Bow merchant" in lines and "Next door" in lines
    assert "Elwynn (45.0, 39.5) - 225 yds" in lines
    assert "Knock first" in lines
    assert lines[-1] == "Click to track Bow merchant"


def test_hovering_the_label_shows_the_same_tooltip(env):  # noqa: F811
    g = world_game([BOW_SHOP])
    tick(g)
    hit = slots(g)[0].labelHit
    hit.scripts.OnEnter(hit)
    assert list(g.g.tooltip_lines.values())[0] == "Bow merchant"


def test_clicking_a_pin_tracks_its_target(env):  # noqa: F811
    g = world_game([BOW_SHOP, ELSEWHERE])
    g.g.last_waypoint = None
    tick(g)
    slot = slots(g)[0]
    slot.scripts.OnClick(slot)
    assert g.g.last_waypoint.mapID == 37


def test_other_continents_are_left_off(env):  # noqa: F811
    g = world_game([BOW_SHOP, ELSEWHERE])
    tick(g)
    assert [s.entry.label for s in slots(g)] == ["Bow merchant"]


def test_row_button_hides_and_shows_a_wow_eye_entry(env):  # noqa: F811
    g = world_game([BOW_SHOP])
    assert row_named(g, "Bow merchant").compass.on is True
    toggle_row(g, "Bow merchant")
    assert row_named(g, "Bow merchant").compass.on is False
    assert g.g.WowEyeDB.characters[KEY].compass["p:37:0.4500:0.3950"] is False
    tick(g)
    assert slots(g) == []
    toggle_row(g, "Bow merchant")
    assert g.lua.eval("rawget")(g.g.WowEyeDB.characters[KEY].compass, "p:37:0.4500:0.3950") is None


def test_tracker_menu_hides_and_shows_a_tracked_quest(env):  # noqa: F811
    g = world_game(watched=[1688])
    item = tracker_checkbox(g)
    assert item.text == "Show on WoW Eye compass"
    assert item.isSelected() is True
    item.setSelected()
    assert tracker_checkbox(g).isSelected() is False
    tick(g)
    assert slots(g) == []
    tracker_checkbox(g).setSelected()
    tick(g)
    assert [s.entry.label for s in slots(g)] == ["Surena Caledon"]


def test_tracker_menu_is_left_alone_off_a_quest(env):  # noqa: F811
    g = world_game()
    g.g.mouse_focus = g.lua.eval("{ GetParent = function() return nil end }")
    menu = g.g.open_menu("MENU_QUEST_OBJECTIVE_TRACKER", g.lua.eval("{}"))
    assert len(menu.checks) == 0 and menu.dividers == 0
    assert "questMenus" not in g.ns.errors


def test_an_untracked_quest_can_be_added_from_the_quest_log(env):  # noqa: F811
    g = world_game()
    menu = g.g.open_menu("MENU_QUEST_MAP_LOG_TITLE", g.lua.eval("{ questID = 109 }"))
    assert menu.checks[1].isSelected() is False
    menu.checks[1].setSelected()
    assert g.g.WowEyeDB.characters[KEY].compass["q:109"] is True
    tick(g)
    assert [s.entry.label for s in slots(g)] == ["Report to Gryan Stoutmantle"]
    # The same menu tag is used for waypoints, which have no quest.
    waypoint = g.g.open_menu("MENU_QUEST_MAP_LOG_TITLE", g.lua.eval("{}"))
    assert len(waypoint.checks) == 0


def test_a_removed_quest_drops_its_choice(env):  # noqa: F811
    g = world_game()
    g.g.open_menu("MENU_QUEST_MAP_LOG_TITLE", g.lua.eval("{ questID = 109 }")).checks[1].setSelected()
    g.g.fire("QUEST_REMOVED", 109)
    assert g.ns.isOnCompass("q:109") is False


def test_stays_in_combat_but_hides_without_facing_with_secret_facing_or_switched_off(env):  # noqa: F811
    g = world_game([BOW_SHOP])
    assert tick(g).IsShown()

    g.g.in_combat = True
    assert tick(g).IsShown()
    assert [s.entry.label for s in slots(g)] == ["Bow merchant"]
    g.g.in_combat = False

    g.g.facing = None
    assert not tick(g).IsShown()
    g.g.facing = g.g.SECRET
    assert not tick(g).IsShown()
    g.g.facing = 0
    assert tick(g).IsShown()

    g.g.SlashCmdList["WOWEYE"]("compass")
    assert g.g.WowEyeDB.compassBar is False
    assert not tick(g).IsShown()
    g.g.SlashCmdList["WOWEYE"]("compass")
    assert tick(g).IsShown()


def test_a_broken_world_api_stops_the_bar_and_reports_it(env):  # noqa: F811
    g = world_game([BOW_SHOP])
    g.lua.execute("function CreateVector2D() error('boom') end")
    g.g.run_tickers()
    assert "compass" in g.ns.errors
    assert not g.ns.compass.IsShown()
    assert len(g.g.WorldMapFrame.pins) == 1


EDIT_MODE = r"""
edit_callbacks = {}
EventRegistry = { RegisterCallback = function(self, event, fn) edit_callbacks[event] = fn end }
"""


def edit_game(markers=None) -> Game:
    if markers:
        bridge.set_markers(markers)
        g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    else:
        g = Game()
    g.lua.execute(FAKE_WORLD)
    g.lua.execute(EDIT_MODE)
    g.login()
    tick(g)
    return g


def test_edit_mode_highlights_the_bar_and_lets_it_move():
    g = edit_game()
    bar = g.ns.compass
    g.g.edit_callbacks["EditMode.Enter"]()
    assert g.ns.compassEditing is True
    bar.GetPoint = g.lua.eval("function() return 'TOP', nil, 'TOP', 40, -200 end")
    bar.scripts.OnDragStop(bar)
    assert g.g.WowEyeDB.compassPosition.y == -200
    g.g.edit_callbacks["EditMode.Exit"]()
    assert g.ns.compassEditing is False


def test_edit_mode_shows_the_bar_even_where_it_would_hide():
    g = edit_game()
    g.g.facing = None
    assert not tick(g).IsShown()
    g.g.edit_callbacks["EditMode.Enter"]()
    assert tick(g).IsShown()
    g.g.edit_callbacks["EditMode.Exit"]()
    assert not tick(g).IsShown()


def test_right_click_in_edit_mode_resets_the_position():
    g = edit_game()
    g.g.WowEyeDB.compassPosition = g.lua.table_from({"point": "TOP", "x": 40, "y": -200})
    bar = g.ns.compass
    bar.scripts.OnMouseUp(bar, "RightButton")
    assert g.g.WowEyeDB.compassPosition is not None  # ignored outside Edit Mode
    g.g.edit_callbacks["EditMode.Enter"]()
    bar.scripts.OnMouseUp(bar, "RightButton")
    assert g.g.WowEyeDB.compassPosition is None




def party_slots(g):
    found = g.ns.compassPartySlots
    return [found[i] for i in range(1, len(found) + 1) if found[i].IsShown()]


FAKE_PARTY = r'''
party = {
    party1 = { map = 37, x = 0.25, y = 0.30, name = "Friend", class = "MAGE" },
}
RAID_CLASS_COLORS = { MAGE = { r = 0.25, g = 0.78, b = 0.92 } }
C_Map.GetBestMapForUnit = function(unit)
    local p = party[unit]
    if p then return p.map end
    return player_map
end
C_Map.GetPlayerMapPosition = function(mapID, unit)
    local p = party[unit]
    if p then
        if p.map == mapID then return { GetXY = function() return p.x, p.y end } end
        return nil
    end
    if mapID == player_map then return { GetXY = function() return player_x, player_y end } end
end
function UnitExists(unit) return party[unit] ~= nil end
function UnitIsConnected(unit) return not party[unit].offline end
local realUnitName = UnitName
function UnitName(unit)
    if party[unit] then return party[unit].name end
    return realUnitName(unit)
end
local realUnitClass = UnitClass
function UnitClass(unit)
    if party[unit] then return "Class", party[unit].class end
    return realUnitClass(unit)
end
'''


def party_game(markers=None) -> Game:
    if markers:
        bridge.set_markers(markers)
        g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    else:
        g = Game()
    g.lua.execute(FAKE_WORLD)
    g.lua.execute(FAKE_PARTY)
    g.login()
    return g


def test_party_members_show_on_the_compass():
    g = party_game()
    tick(g)
    [slot] = party_slots(g)
    assert slot.entry.kind == "party"
    assert slot.label.text == "Friend  200 yds"  # 200 yards due north
    assert slot.x == pytest.approx(BAR_CENTER)
    assert list(slot.entry.color.values()) == pytest.approx([0.25, 0.78, 0.92])


def test_party_members_who_cant_be_placed_are_left_off():
    g = party_game()
    g.lua.execute("party.party2 = { map = 48, x = 0.5, y = 0.5, name = 'Far', class = 'MAGE' }")
    g.lua.execute("party.party3 = { map = 37, x = 0.3, y = 0.3, name = 'Gone', class = 'MAGE', offline = true }")
    g.lua.execute("party.party4 = { map = nil, x = 0.3, y = 0.3, name = 'Inside', class = 'MAGE' }")
    tick(g)
    assert [s.entry.label for s in party_slots(g)] == ["Friend"]


def test_party_toggle_by_command_and_keybinding():
    g = party_game()
    g.g.SlashCmdList["WOWEYE"]("party")
    assert g.g.WowEyeDB.compassParty is False
    tick(g)
    assert party_slots(g) == []
    assert tick(g).IsShown()  # the compass itself stays
    g.g.WowEye_ToggleParty()
    tick(g)
    assert [s.entry.label for s in party_slots(g)] == ["Friend"]


def test_party_members_get_their_own_lane_above_the_targets(env):  # noqa: F811
    g = party_game([{**BOW_SHOP, "x": 25.0, "y": 30.2, "label": "Camp"}])
    tick(g)
    assert [s.entry.label for s in slots(g)] == ["Camp"]
    assert [s.entry.label for s in party_slots(g)] == ["Friend"]
    assert g.ns.compassPartyLane.IsShown()


def test_the_party_lane_hides_with_nobody_to_show():
    g = party_game()
    g.lua.execute("party = {}")
    tick(g)
    assert not g.ns.compassPartyLane.IsShown()
    assert g.ns.compass.IsShown()


def test_party_labels_that_would_overlap_are_left_off():
    g = party_game()
    # About 40 pixels left of Friend on the bar: separate pins, but the labels collide.
    g.lua.execute("party.party2 = { map = 37, x = 0.209, y = 0.30, name = 'Close', class = 'MAGE' }")
    tick(g)
    assert len(party_slots(g)) == 2
    shown = {s.entry.label: s.labelShown for s in party_slots(g)}
    assert True in shown.values() and False in shown.values()


def test_hovering_a_party_member_has_no_click_hint_and_clicking_does_nothing():
    g = party_game()
    g.g.last_waypoint = None
    tick(g)
    slot = party_slots(g)[0]
    slot.scripts.OnEnter(slot)
    lines = list(g.g.tooltip_lines.values())
    assert lines[0] == "Friend"
    assert not any("Click to track" in str(line) for line in lines)
    slot.scripts.OnClick(slot)
    assert g.g.last_waypoint is None


def test_party_names_are_shown_literally_and_secret_names_fall_back():
    g = party_game()
    g.lua.execute("party.party1.name = '|cffff0000Red|r'")
    tick(g)
    assert party_slots(g)[0].label.text.startswith("||cffff0000Red||r")
    g.lua.execute("party.party1.name = SECRET")
    tick(g)
    assert party_slots(g)[0].label.text.startswith("party1")


def test_party_pins_have_red_borders_and_the_leader_adds_gold():
    g = party_game()
    g.lua.execute("""
        party.party2 = { map = 37, x = 0.45, y = 0.30, name = 'Boss', class = 'MAGE', leader = true }
        function UnitIsGroupLeader(unit) return party[unit] and party[unit].leader == true end
    """)
    tick(g)
    borders = {s.entry.label: (s.hasPartyBorder, s.hasPartyLeader) for s in party_slots(g)}
    assert borders == {"Friend": (True, False), "Boss": (True, True)}
    boss = next(s for s in party_slots(g) if s.entry.label == "Boss")
    boss.scripts.OnEnter(boss)
    assert list(g.g.tooltip_lines.values())[0] == "Boss (party leader)"


def test_a_secret_leader_flag_means_no_border():
    g = party_game()
    g.lua.execute("function UnitIsGroupLeader() return SECRET end")
    tick(g)
    assert party_slots(g)[0].hasPartyLeader is False
