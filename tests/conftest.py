"""Runs the real addon files in Lua 5.1 (the game's Lua version) against a fake WoW API."""

from __future__ import annotations

from pathlib import Path

import pytest
from lupa import lua51

ADDON_DIR = Path(__file__).resolve().parents[1] / "addon" / "WowEye"

FAKE_WOW = r'''
SECRET = setmetatable({}, {__tostring = function() error("read a secret") end})
function issecretvalue(v) return v == SECRET end
function issecrettable(v) return false end
function canaccesstable(v) return true end

in_combat = false
reload_count = 0
printed = {}
timers = {}
frames = {}
known_events = nil

now = 1000
function print(s) printed[#printed + 1] = s end
function time() return now end
function InCombatLockdown() return in_combat end
function ReloadUI() reload_count = reload_count + 1 end
C_Timer = { After = function(_, fn) timers[#timers + 1] = fn end }
function run_timers()
    local t = timers
    timers = {}
    for _, fn in ipairs(t) do fn() end
end

local function stub()
    local f = {}
    return setmetatable(f, { __index = function(t, k)
        if k == "TitleText" then
            local s = stub(); rawset(t, k, s); return s
        end
        if k == "GetStringHeight" then
            return function() return 40 end
        end
        if k == "SetText" then
            return function(self, s) rawset(self, "text", s) end
        end
        if k == "SetPoint" then
            return function(self, _, anchor) rawset(self, "anchor", anchor) end
        end
        return function() return stub() end
    end })
end

function CreateFrame()
    local f = stub()
    f.scripts = {}
    f.registered = {}
    f.SetScript = function(self, name, fn) self.scripts[name] = fn end
    f.RegisterEvent = function(self, e)
        if known_events and not known_events[e] then error("unknown event " .. e) end
        self.registered[e] = true
    end
    local shown = false
    f.Show = function() shown = true end
    f.Hide = function() shown = false end
    f.IsShown = function() return shown end
    frames[#frames + 1] = f
    return f
end

function fire(event, ...)
    for _, f in ipairs(frames) do
        if f.registered[event] then f.scripts.OnEvent(f, event, ...) end
    end
end

UIParent = {}
UISpecialFrames = {}
SlashCmdList = {}

npc_name = "Rallic Finn"
npc_guid = "Creature-0-1-0-12-1198-000000"
function UnitName(unit)
    if unit == "npc" then return npc_name end
    return "Tester"
end
function UnitGUID(unit) if unit == "npc" then return npc_guid end end
C_TooltipInfo = {
    GetUnit = function()
        return { lines = { { leftText = npc_name }, { leftText = npc_title }, { leftText = "Level 30" } } }
    end,
}
npc_title = "Bowyer"
LEVEL = "Level"
function GetRealmName() return "Test Realm" end
function GetNormalizedRealmName() return "TestRealm" end
function UnitClass() return "Mage", "MAGE" end
function UnitRace() return "Human", "Human" end
function UnitLevel() return 12 end
function UnitFactionGroup() return "Alliance" end
function UnitXP() return SECRET end
function UnitXPMax() return 900 end
function GetBuildInfo() return "1.60.1", "70840", "Nov 1 2026", 16001 end
function GetRealZoneText() return "Elwynn Forest" end
function GetSubZoneText() return "Goldshire" end
function GetMoney() return 12345 end
function GetInventoryItemLink(_, slot) if slot == 16 then return "|Hitem:25|h[Sword]|h" end end
player_map, player_x, player_y = 37, 0.25, 0.5
C_Map = {
    GetBestMapForUnit = function() return player_map end,
    GetPlayerMapPosition = function(mapID)
        if mapID == player_map then
            return { GetXY = function() return player_x, player_y end }
        end
    end,
    GetMapWorldSize = function() return 1000, 1000 end,
}
quests_on, quests_ready, quests_done = {}, {}, {}
completed_ids = { 7, 62, 91775 }
C_QuestLog = {
    GetNumQuestLogEntries = function() return 2 end,
    GetInfo = function(i)
        if i == 1 then return { isHeader = true, title = "Elwynn" } end
        return { questID = 7, title = 'Kill "Wolves"', level = 5, suggestedGroup = 0 }
    end,
    IsComplete = function(id) return quests_ready[id] == true end,
    IsOnQuest = function(id) return quests_on[id] == true end,
    IsQuestFlaggedCompleted = function(id) return quests_done[id] == true end,
    GetQuestObjectives = function() return { { text = "Wolves: 2/8", finished = false } } end,
    GetAllCompletedQuestIDs = function() return completed_ids end,
    GetNextWaypoint = function() return 37, 0.4, 0.6 end,
    GetNextWaypointText = function() return "Go to the forest" end,
    GetQuestsOnMap = function() return { { questID = 7, x = 0.41, y = 0.61 } } end,
}
quest_text_calls = 0
function GetQuestLogQuestText()
    quest_text_calls = quest_text_calls + 1
    return "Wolves are a problem.", "Kill 8 wolves."
end
function GetQuestLogRewardXP() return 250 end
function GetQuestLogRewardMoney() return 75 end
function GetNumQuestLogRewards() return 1 end
function GetQuestLogRewardInfo() return "Cloak", 1, 1, 2, true, 99 end
function GetNumQuestLogChoices() return 2 end
function GetQuestLogChoiceInfo(i) return "Choice" .. i, 1, 1, 2, i == 1, 100 + i end
C_Item = {
    GetItemInfo = function(link)
        if link:find("Uncached") then return nil end
        return "Sword", link, 2, 11, 5, "Weapon", "One-Handed Swords", 1, "INVTYPE_WEAPON", 1, 150
    end,
    GetDetailedItemLevelInfo = function() return 12 end,
    GetItemStats = function() return { ITEM_MOD_STAMINA_SHORT = 2 } end,
}
function GetInventoryItemID() return 25 end
function GetInventoryItemDurability() return 40, 50 end
function GetXPExhaustion() return 600 end
function IsResting() return true end
function GetBindLocation() return "Goldshire" end
Enum = {
    SpellBookSpellBank = { Player = 0 },
    SpellBookItemType = { Spell = 1, FutureSpell = 2 },
    FlightPathState = { Current = 0, Reachable = 1, Unreachable = 2 },
}
C_SpellBook = {
    GetNumSpellBookSkillLines = function() return 2 end,
    GetSpellBookSkillLineInfo = function(i)
        if i == 2 then return { shouldHide = true, itemIndexOffset = 2, numSpellBookItems = 1, name = "Hidden" } end
        return { name = "Affliction", itemIndexOffset = 0, numSpellBookItems = 2 }
    end,
    GetSpellBookItemInfo = function(slot)
        if slot == 1 then
            return { name = "Corruption", subName = "Rank 1", spellID = 172, actionID = 172, itemType = 1, isPassive = false }
        end
        return { name = "Drain Soul", subName = "", actionID = 1120, itemType = 2, isPassive = false }
    end,
    GetSpellBookItemLevelLearned = function() return 10 end,
}
C_SpecializationInfo = {
    GetActiveSpecGroup = function() return 1 end,
    GetCombatConfigIDForSpecGroup = function() return 5 end,
}
C_Traits = {
    GetConfigInfo = function() return { treeIDs = { 9 } } end,
    GetTreeCurrencyInfo = function() return { { quantity = 3 } } end,
    GetTreeNodes = function() return { 1, 2 } end,
    GetNodeInfo = function(_, nodeID)
        if nodeID == 1 then
            return { currentRank = 2, maxRanks = 5, activeEntry = { entryID = 50, rank = 2 } }
        end
        return { currentRank = 0, maxRanks = 3 }
    end,
    GetEntryInfo = function() return { definitionID = 60 } end,
    GetDefinitionInfo = function() return { spellID = 700 } end,
}
C_Spell = { GetSpellName = function() return "Improved Corruption" end }
function GetProfessions() return nil, 3, nil, nil, 4 end
function GetProfessionInfo(i)
    if i == 3 then return "Tailoring", 1, 25, 75 end
    return "Cooking", 1, 1, 75
end
C_Reputation = {
    GetNumFactions = function() return 3 end,
    GetFactionDataByIndex = function(i)
        if i == 1 then return { isHeader = true, isCollapsed = false, name = "Alliance" } end
        if i == 2 then
            return { factionID = 72, name = "Stormwind", reaction = 5, currentStanding = 300,
                     currentReactionThreshold = 0, nextReactionThreshold = 3000, isWatched = true }
        end
        return { isHeader = true, isCollapsed = true, name = "Other" }
    end,
}
merchant_items = 1
function GetMerchantNumItems() return merchant_items end
function GetMerchantItemLink() return "|Hitem:25|h[Sword]|h" end
C_MerchantFrame = {
    GetItemInfo = function()
        return { name = "Sword", price = 300, stackCount = 1, numAvailable = -1,
                 isUsable = true, isPurchasable = true, hasExtendedCost = false }
    end,
}
function CanMerchantRepair() return true end
function GetRepairAllCost() return 42, true end
function GetMerchantFilter() return 1 end
function GetNumTrainerServices() return 2 end
function GetTrainerServiceInfo(i)
    if i == 1 then return "Affliction", "header" end
    return "Corruption", "available", 1, 10, "Rank 2", 2
end
function GetTrainerServiceCost() return 500, false end
function GetTrainerServiceSkillReq() return "Tailoring", 40, false end
function GetTrainerServiceTypeFilter(name) return name ~= "used" end
function GetTaxiMapID() return 1415 end
C_TaxiMap = {
    GetAllTaxiNodes = function()
        return {
            { nodeID = 2, name = "Stormwind", state = 1, isMapLayerTransition = false,
              position = { GetXY = function() return 0.4, 0.5 end } },
            { nodeID = 3, name = "Layer", state = 1, isMapLayerTransition = true,
              position = { GetXY = function() return 0, 0 end } },
            { nodeID = 4, name = "Sentinel Hill", state = 2, isMapLayerTransition = false,
              position = { GetXY = function() return 0.3, 0.7 end } },
        }
    end,
}
C_Container = {
    GetContainerNumSlots = function(bag) return bag == 0 and 2 or 0 end,
    GetContainerItemInfo = function(_, slot)
        if slot == 1 then return { itemID = 25, stackCount = 3, hyperlink = "|Hitem:25|h[Sword]|h" } end
    end,
}

function CreateFromMixins(...)
    local out = {}
    for _, mixin in ipairs({ ... }) do
        for k, v in pairs(mixin) do out[k] = v end
    end
    return out
end

local function noop() end
MapCanvasPinMixin = {
    UseFrameLevelType = noop,
    SetScalingLimits = noop,
    SetPosition = function(self, x, y) self.x, self.y = x, y end,
}
MapCanvasDataProviderMixin = {
    GetMap = function(self) return self.owningMap end,
    OnMapChanged = function(self) self:RefreshAllData() end,
}
WorldMapFrame = {
    mapID = 37,
    pins = {},
    GetMapID = function(self) return self.mapID end,
    AcquirePin = function(self, template, ...)
        assert(template == "WowEyePinTemplate")
        local pin = CreateFromMixins(WowEyePinMixin)
        pin:OnLoad()
        pin:OnAcquired(...)
        self.pins[#self.pins + 1] = pin
        return pin
    end,
    RemoveAllPinsByTemplate = function(self) self.pins = {} end,
    AddDataProvider = function(self, provider)
        self.provider = provider
        provider.owningMap = self
        provider:RefreshAllData()
    end,
}
tooltip_lines = {}
GameTooltip = {
    SetOwner = noop,
    SetText = function(_, s) tooltip_lines[#tooltip_lines + 1] = s end,
    AddLine = function(_, s) tooltip_lines[#tooltip_lines + 1] = s end,
    Show = noop,
    Hide = noop,
}
waypoint_calls = 0
last_waypoint = nil
supertracked = false
C_Map.CanSetUserWaypointOnMap = function(mapID) return mapID ~= 999 end
C_Map.SetUserWaypoint = function(point)
    waypoint_calls = waypoint_calls + 1
    last_waypoint = point
end
C_Map.ClearUserWaypoint = function() last_waypoint = nil end
UiMapPoint = {
    CreateFromCoordinates = function(mapID, x, y) return { mapID = mapID, x = x, y = y } end,
}
C_SuperTrack = {
    SetSuperTrackedUserWaypoint = function(v) supertracked = v end,
    IsSuperTrackingUserWaypoint = function() return supertracked end,
}
C_Map.GetUserWaypoint = function()
    if last_waypoint then
        return {
            uiMapID = last_waypoint.mapID,
            position = { x = last_waypoint.x, y = last_waypoint.y },
        }
    end
end
nav_frame = {}
nav_valid = true
nav_distance = 42.7
C_Navigation = {
    GetFrame = function() return nav_frame end,
    HasValidScreenPosition = function() return nav_valid end,
    GetDistance = function() return nav_distance end,
}
function CreateColor(r, g, b, a) return { r = r, g = g, b = b, a = a } end
function GetTime() return 1 end
tickers = {}
C_Timer.NewTicker = function(_, fn)
    local t = { fn = fn, cancelled = false }
    t.Cancel = function(self) self.cancelled = true end
    tickers[#tickers + 1] = t
    return t
end
function run_tickers()
    for _, t in ipairs(tickers) do
        if not t.cancelled then t.fn() end
    end
end

-- Writes tables in the same shape as the client's SavedVariables files.
local function write(v, out)
    local t = type(v)
    if t == "table" then
        out[#out + 1] = "{\n"
        local n = #v
        for i = 1, n do
            write(v[i], out)
            out[#out + 1] = ", -- [" .. i .. "]\n"
        end
        for k, val in pairs(v) do
            if not (type(k) == "number" and k >= 1 and k <= n) then
                out[#out + 1] = "[" .. (type(k) == "string" and string.format("%q", k) or k) .. "] = "
                write(val, out)
                out[#out + 1] = ",\n"
            end
        end
        out[#out + 1] = "}"
    elseif t == "string" then
        out[#out + 1] = string.format("%q", v)
    else
        out[#out + 1] = tostring(v)
    end
end

function dump_saved_variables(name)
    local out = { "\n", name, " = " }
    write(_G[name], out)
    out[#out + 1] = "\n"
    return table.concat(out)
end
'''

ORDER = ["Core.lua", "Snapshot.lua", "Panel.lua", "Pins.lua", "Route.lua", "Tracking.lua"]


class Game:
    def __init__(self, known_events=None, inbox_source: str | None = None):
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FAKE_WOW)
        self.g = self.lua.globals()
        self.ns = self.lua.eval("{}")
        if known_events is not None:
            self.g.known_events = self.lua.table_from({e: True for e in known_events})
        if inbox_source:
            self.lua.execute(inbox_source)
        for name in ORDER:
            source = (ADDON_DIR / name).read_text(encoding="utf-8")
            chunk = self.lua.eval("loadstring")(source, name)
            assert chunk is not None, f"{name} failed to compile"
            chunk("WowEye", self.ns)

    def login(self, initial=True):
        self.g.fire("ADDON_LOADED", "WowEye")
        self.g.fire("PLAYER_LOGIN")
        self.g.fire("PLAYER_ENTERING_WORLD", initial, not initial)

    def saved_text(self) -> str:
        return self.g.dump_saved_variables("WowEyeDB")


@pytest.fixture
def game():
    g = Game()
    g.login()
    return g
