-- Snapshot: read-only collectors for what the agent can see.
-- Each collector runs in a pcall, so an API that is missing or behaves differently
-- in Forever costs that one section and is reported in snapshot.errors.
-- API names here were checked against Blizzard's UI source for 1.60.1 (70840).
local _, ns = ...

local function pass(ok, ...)
    if ok then
        return ...
    end
end

-- Calls fn if it exists and returns its results, or nothing if it fails. For optional
-- detail inside a section, where one failure shouldn't cost the whole section.
local function try(fn, ...)
    if fn then
        return pass(pcall(fn, ...))
    end
end
ns.try = try

local collectors = {}

function collectors.identity()
    local _, classFile = UnitClass("player")
    local _, raceFile = UnitRace("player")
    local version, build, _, interface = GetBuildInfo()
    return {
        name = UnitName("player"),
        realm = GetRealmName(),
        level = UnitLevel("player"),
        class = classFile,
        race = raceFile,
        faction = UnitFactionGroup("player"),
        xp = UnitXP("player"),
        xpMax = UnitXPMax("player"),
        restedXP = try(GetXPExhaustion),
        isResting = try(IsResting),
        hearthstone = try(GetBindLocation),
        clientVersion = version,
        clientBuild = build,
        interface = interface,
    }
end

-- Returns mapID, x, y (0-1) or nothing. Values the game keeps secret count as unknown.
function ns.playerPosition()
    local mapID = C_Map.GetBestMapForUnit("player")
    if not mapID then
        return nil
    end
    local pos = C_Map.GetPlayerMapPosition(mapID, "player")
    if not pos then
        return mapID
    end
    local x, y = pos:GetXY()
    if ns.isSecret(x) or ns.isSecret(y) then
        return mapID
    end
    return mapID, x, y
end

function collectors.location()
    local mapID, x, y = ns.playerPosition()
    return {
        zone = GetRealZoneText(),
        subzone = GetSubZoneText(),
        mapID = mapID,
        x = x,
        y = y,
    }
end

function collectors.money()
    return GetMoney()
end

local function rewardItem(getInfo, i, questID)
    local name, _, count, quality, usable, itemID = try(getInfo, i, questID)
    return { name = name, count = count, quality = quality, usable = usable, id = itemID }
end

local function questRewards(questID)
    local rewards = {
        xp = try(GetQuestLogRewardXP, questID),
        money = try(GetQuestLogRewardMoney, questID),
        items = {},
        choices = {},
    }
    for i = 1, try(GetNumQuestLogRewards, questID) or 0 do
        rewards.items[i] = rewardItem(GetQuestLogRewardInfo, i, questID)
    end
    for i = 1, try(GetNumQuestLogChoices, questID) or 0 do
        rewards.choices[i] = rewardItem(GetQuestLogChoiceInfo, i, questID)
    end
    return rewards
end

-- Quest text doesn't change, and snapshots run often, so it's fetched once per quest.
local questText = {}
local function textFor(questID, logIndex)
    local cached = questText[questID]
    if not cached then
        local description, objectives = try(GetQuestLogQuestText, logIndex)
        if not description then
            return {}
        end
        cached = { description = description, objectives = objectives }
        questText[questID] = cached
    end
    return cached
end

-- The game's own guidance on where a quest goes next. May be on another map.
local function questWaypoint(questID)
    local mapID, x, y = try(C_QuestLog.GetNextWaypoint, questID)
    if mapID then
        return { mapID = mapID, x = x, y = y, text = try(C_QuestLog.GetNextWaypointText, questID) }
    end
end

local function pinsOnCurrentMap()
    local pins = {}
    local mapID = C_Map.GetBestMapForUnit("player")
    for _, q in ipairs(mapID and try(C_QuestLog.GetQuestsOnMap, mapID) or {}) do
        pins[q.questID] = { mapID = mapID, x = q.x, y = q.y }
    end
    return pins
end

function collectors.quests()
    local out = {}
    local pins = pinsOnCurrentMap()
    for i = 1, C_QuestLog.GetNumQuestLogEntries() do
        local info = C_QuestLog.GetInfo(i)
        if info and not info.isHeader then
            local id = info.questID
            local text = textFor(id, i)
            out[#out + 1] = {
                id = id,
                title = info.title,
                level = info.level,
                suggestedGroup = info.suggestedGroup,
                complete = C_QuestLog.IsComplete(id),
                objectives = C_QuestLog.GetQuestObjectives(id),
                description = text.description,
                objectiveText = text.objectives,
                rewards = questRewards(id),
                waypoint = questWaypoint(id),
                mapPin = pins[id],
            }
        end
    end
    return out
end

-- Item data can be uncached the first time. pending items fill in on a later snapshot.
function ns.itemDetails(link)
    if not link then
        return nil
    end
    local name, _, quality, itemLevel, minLevel, itemType, subType, _, equipLoc, _, sellPrice =
        try(C_Item.GetItemInfo, link)
    if not name then
        return { link = link, pending = true }
    end
    return {
        link = link,
        name = name,
        quality = quality,
        itemLevel = try(C_Item.GetDetailedItemLevelInfo, link) or itemLevel,
        minLevel = minLevel,
        type = itemType,
        subType = subType,
        equipLoc = equipLoc,
        sellPrice = sellPrice,
        stats = try(C_Item.GetItemStats, link),
    }
end

function collectors.equipment()
    local out = {}
    for slot = 1, 19 do
        local link = GetInventoryItemLink("player", slot)
        if link then
            local item = ns.itemDetails(link)
            item.id = try(GetInventoryItemID, "player", slot)
            item.durability, item.maxDurability = try(GetInventoryItemDurability, slot)
            out[tostring(slot)] = item
        end
    end
    return out
end

function collectors.bags()
    local items, free, total = {}, 0, 0
    for bag = 0, 4 do
        local slots = C_Container.GetContainerNumSlots(bag) or 0
        total = total + slots
        for slot = 1, slots do
            local info = C_Container.GetContainerItemInfo(bag, slot)
            if info then
                local item = ns.itemDetails(info.hyperlink) or {}
                item.id = info.itemID
                item.count = info.stackCount
                items[#items + 1] = item
            else
                free = free + 1
            end
        end
    end
    return { items = items, freeSlots = free, totalSlots = total }
end

-- Known spells, plus future ones with the level they become available. Trainer costs
-- only appear once a trainer has been visited (see Tracking.lua).
function collectors.spells()
    local known, future = {}, {}
    local bank = Enum.SpellBookSpellBank.Player
    for line = 1, C_SpellBook.GetNumSpellBookSkillLines() do
        local skill = C_SpellBook.GetSpellBookSkillLineInfo(line)
        if skill and not skill.shouldHide then
            for slot = skill.itemIndexOffset + 1, skill.itemIndexOffset + skill.numSpellBookItems do
                local item = C_SpellBook.GetSpellBookItemInfo(slot, bank)
                if item then
                    local entry = {
                        name = item.name,
                        rank = item.subName,
                        id = item.spellID or item.actionID,
                        tab = skill.name,
                        passive = item.isPassive,
                    }
                    if item.itemType == Enum.SpellBookItemType.FutureSpell then
                        entry.level = try(C_SpellBook.GetSpellBookItemLevelLearned, slot, bank)
                        future[#future + 1] = entry
                    elseif item.itemType == Enum.SpellBookItemType.Spell then
                        known[#known + 1] = entry
                    end
                end
            end
        end
    end
    return { known = known, future = future }
end

-- Only chosen talents, to keep the file small. Forever's talents use the trait-tree API.
function collectors.talents()
    local group = C_SpecializationInfo.GetActiveSpecGroup()
    local configID = C_SpecializationInfo.GetCombatConfigIDForSpecGroup(group)
    local out = { specGroup = group, chosen = {}, unspent = {} }
    local config = configID and C_Traits.GetConfigInfo(configID)
    if not config then
        return out
    end
    for _, treeID in ipairs(config.treeIDs) do
        for _, currency in ipairs(try(C_Traits.GetTreeCurrencyInfo, configID, treeID, false) or {}) do
            out.unspent[#out.unspent + 1] = currency.quantity
        end
        for _, nodeID in ipairs(C_Traits.GetTreeNodes(treeID)) do
            local node = C_Traits.GetNodeInfo(configID, nodeID)
            if node and node.currentRank and node.currentRank > 0 and node.activeEntry then
                local entry = C_Traits.GetEntryInfo(configID, node.activeEntry.entryID)
                local def = entry and entry.definitionID and C_Traits.GetDefinitionInfo(entry.definitionID)
                local spellID = def and def.spellID
                out.chosen[#out.chosen + 1] = {
                    name = spellID and try(C_Spell.GetSpellName, spellID),
                    spellID = spellID,
                    rank = node.currentRank,
                    maxRank = node.maxRanks,
                }
            end
        end
    end
    return out
end

function collectors.professions()
    local out = {}
    local slots = { GetProfessions() }
    for i = 1, select("#", GetProfessions()) do
        if slots[i] then
            local name, _, rank, maxRank = GetProfessionInfo(slots[i])
            out[#out + 1] = { name = name, rank = rank, maxRank = maxRank }
        end
    end
    return out
end

-- Factions under a header the player collapsed aren't listed by the game. Expanding
-- them would change the player's UI, so collapsedHeaders reports the gap instead.
function collectors.reputation()
    local factions, collapsed = {}, 0
    for i = 1, C_Reputation.GetNumFactions() do
        local f = C_Reputation.GetFactionDataByIndex(i)
        if f then
            if f.isHeader and f.isCollapsed then
                collapsed = collapsed + 1
            end
            if not f.isHeader or f.isHeaderWithRep then
                factions[#factions + 1] = {
                    id = f.factionID,
                    name = f.name,
                    reaction = f.reaction,
                    standing = f.currentStanding,
                    min = f.currentReactionThreshold,
                    max = f.nextReactionThreshold,
                    watched = f.isWatched,
                }
            end
        end
    end
    return { factions = factions, collapsedHeaders = collapsed }
end

-- Kept outside the snapshot because the list runs to thousands of IDs, and every reader
-- of a full snapshot shouldn't pay for it. The game's list also includes hidden quests
-- it uses to track state, so the count runs higher than the quests a player remembers.
function ns.captureCompletedQuests()
    ns.characterRecord().completedQuests = {
        at = time(),
        ids = ns.clean(C_QuestLog.GetAllCompletedQuestIDs()),
    }
end

function ns.captureSnapshot()
    ns.redacted = 0
    local snap = { schema = ns.SCHEMA, capturedAt = time() }
    local errors = {}
    for name, collect in pairs(collectors) do
        local ok, result = pcall(function()
            return ns.clean(collect())
        end)
        if ok then
            snap[name] = result
        else
            errors[name] = tostring(result)
        end
    end
    snap.redacted = ns.redacted
    errors.markers = ns.markerError
    for name, message in pairs(ns.errors) do
        errors[name] = message
    end
    if next(errors) then
        snap.errors = errors
    end
    if ns.unknownEvents then
        snap.unknownEvents = ns.unknownEvents
    end
    return snap
end
