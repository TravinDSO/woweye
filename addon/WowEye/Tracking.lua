-- Tracking: what the player finds while playing. Verified NPC locations, vendor stock,
-- trainer offers, flight paths and session statistics. All recorded from windows the
-- player opened or events on their own character, never from combat data.
local _, ns = ...

local MAX_NPCS = 3000
local MAX_VENDORS = 40
local MAX_TRAINERS = 40
local MAX_SESSIONS = 20
local MAX_TOUCH_GAP = 300
local SESSION_TOUCH_SECONDS = 30

local frame = CreateFrame("Frame")

local function plain(v)
    if not ns.isSecret(v) then
        return v
    end
end

local function dropOldest(map, limit, stamp)
    local count, oldestKey, oldestTime = 0, nil, nil
    for key, value in pairs(map) do
        count = count + 1
        if not oldestTime or value[stamp] < oldestTime then
            oldestKey, oldestTime = key, value[stamp]
        end
    end
    if count > limit then
        map[oldestKey] = nil
    end
end

-- NPC GUIDs look like Creature-0-server-instance-zone-npcID-spawn. Forever hides the
-- server and spawn parts but keeps the format, so the ID still identifies the NPC.
local function npcID(guid)
    guid = plain(guid)
    if guid then
        return tonumber(guid:match("^%a+%-[^-]*%-[^-]*%-[^-]*%-[^-]*%-(%d+)"))
    end
end

-- The second tooltip line of an NPC is its title ("Bowyer") unless it's the level line.
local function npcTitle()
    local data = ns.try(C_TooltipInfo.GetUnit, "npc")
    local line = data and data.lines and data.lines[2]
    local text = line and plain(line.leftText)
    if text and not text:find(LEVEL or "Level", 1, true) then
        return text
    end
end

-- Records who the player is talking to and where. The position is the player's, which
-- is within interaction range of the NPC. Returns the key for this NPC.
local function recordNPC(role)
    local name = plain(UnitName("npc"))
    if not name then
        return nil
    end
    local id = npcID(UnitGUID("npc"))
    local key = id and ("id:" .. id) or ("name:" .. name)
    local now = time()
    local mapID, x, y = ns.playerPosition()
    local npc = WowEyeDB.npcs[key] or { firstSeen = now, roles = {} }
    npc.id = id
    npc.name = name
    npc.title = npcTitle() or npc.title
    npc.lastSeen = now
    npc.roles[role] = true
    if x then
        npc.mapID, npc.x, npc.y = mapID, x, y
        npc.zone = GetRealZoneText()
        npc.subzone = GetSubZoneText()
    end
    WowEyeDB.npcs[key] = npc
    dropOldest(WowEyeDB.npcs, MAX_NPCS, "lastSeen")
    return key, npc
end

local function recordVendor()
    local key, npc = recordNPC("merchant")
    local count = GetMerchantNumItems()
    if not key or count == 0 then
        return
    end
    local items = {}
    for i = 1, count do
        local info = C_MerchantFrame.GetItemInfo(i)
        if info then
            local item = ns.itemDetails(GetMerchantItemLink(i)) or {}
            item.name = item.name or info.name
            item.price = info.price
            item.stack = info.stackCount
            item.available = info.numAvailable
            item.usable = info.isUsable
            item.purchasable = info.isPurchasable
            item.hasExtendedCost = info.hasExtendedCost
            items[#items + 1] = item
        end
    end
    local vendors = ns.characterRecord().vendors
    vendors[key] = ns.clean({
        npc = key,
        name = npc.name,
        title = npc.title,
        at = time(),
        canRepair = ns.try(CanMerchantRepair),
        repairAllCost = ns.try(GetRepairAllCost),
        itemFilter = ns.try(GetMerchantFilter),
        items = items,
    })
    dropOldest(vendors, MAX_VENDORS, "at")
end

-- The list respects the trainer window's filter buttons, which are recorded alongside
-- so the agent knows when something may be hidden.
local function recordTrainer()
    local key, npc = recordNPC("trainer")
    if not key then
        return
    end
    local services = {}
    for i = 1, GetNumTrainerServices() do
        local name, serviceType, _, levelReq, subText = GetTrainerServiceInfo(i)
        if serviceType and serviceType ~= "header" then
            -- Profession recipes are locked by skill, not level.
            local skill, skillRank, meetsSkill = ns.try(GetTrainerServiceSkillReq, i)
            services[#services + 1] = {
                name = name,
                rank = subText,
                state = serviceType,
                level = levelReq,
                cost = ns.try(GetTrainerServiceCost, i),
                skill = skill,
                skillRank = skillRank,
                meetsSkill = meetsSkill,
            }
        end
    end
    local trainers = ns.characterRecord().trainers
    trainers[key] = ns.clean({
        npc = key,
        name = npc.name,
        title = npc.title,
        at = time(),
        showing = {
            available = ns.try(GetTrainerServiceTypeFilter, "available"),
            unavailable = ns.try(GetTrainerServiceTypeFilter, "unavailable"),
            used = ns.try(GetTrainerServiceTypeFilter, "used"),
        },
        services = services,
    })
    dropOldest(trainers, MAX_TRAINERS, "at")
end

local function flightState(state)
    for name, value in pairs(Enum.FlightPathState) do
        if value == state then
            return name
        end
    end
end

local function recordFlightPaths()
    recordNPC("flight")
    local mapID = GetTaxiMapID()
    local nodes = {}
    for _, node in ipairs(C_TaxiMap.GetAllTaxiNodes(mapID)) do
        if not node.isMapLayerTransition then
            local x, y = node.position:GetXY()
            nodes[#nodes + 1] = {
                id = node.nodeID,
                name = node.name,
                x = x,
                y = y,
                state = flightState(node.state),
            }
        end
    end
    ns.characterRecord().flightPaths["map:" .. tostring(mapID)] =
        ns.clean({ mapID = mapID, at = time(), nodes = nodes })
end

-- Session statistics. A session runs from login to logout, across UI reloads.
local function newSession(rec)
    if rec.session then
        table.insert(rec.sessions, rec.session)
        while #rec.sessions > MAX_SESSIONS do
            table.remove(rec.sessions, 1)
        end
    end
    local now = time()
    rec.session = {
        startedAt = now,
        lastSeen = now,
        startLevel = UnitLevel("player"),
        startMoney = GetMoney(),
        xpGained = 0,
        levelsGained = 0,
        deaths = 0,
        questsAccepted = 0,
        questsTurnedIn = 0,
        combatSeconds = 0,
        zoneSeconds = {},
    }
end

local lastXP, lastXPMax, combatStart

local function rememberXP()
    lastXP, lastXPMax = plain(UnitXP("player")), plain(UnitXPMax("player"))
end

local function onXP()
    local xp = plain(UnitXP("player"))
    local xpMax = plain(UnitXPMax("player"))
    local session = ns.characterRecord().session
    if session and xp and lastXP and lastXPMax then
        -- XP going down means a level-up: the rest of the old bar, plus the new amount.
        local gained = xp >= lastXP and (xp - lastXP) or (lastXPMax - lastXP + xp)
        session.xpGained = session.xpGained + gained
    end
    lastXP, lastXPMax = xp, xpMax
end

-- Adds elapsed time to the current zone. A long gap means the game wasn't running or
-- was stalled, so it's skipped rather than counted as play time.
function ns.sessionTouch()
    local session = ns.characterRecord().session
    if not session then
        return
    end
    local now = time()
    local gap = now - session.lastSeen
    session.lastSeen = now
    session.endMoney = GetMoney()
    session.endLevel = UnitLevel("player")
    local zone = plain(GetRealZoneText())
    if zone and zone ~= "" and gap > 0 and gap <= MAX_TOUCH_GAP then
        session.zoneSeconds[zone] = (session.zoneSeconds[zone] or 0) + gap
    end
end

local function startSession(isInitialLogin)
    local rec = ns.characterRecord()
    if isInitialLogin or not rec.session then
        newSession(rec)
    end
    rememberXP()
end

local function bump(field)
    local session = ns.characterRecord().session
    if session then
        session[field] = session[field] + 1
    end
end

local vendorUpdatePending = false
local function scheduleVendorUpdate()
    if vendorUpdatePending then
        return
    end
    vendorUpdatePending = true
    C_Timer.After(0.5, function()
        vendorUpdatePending = false
        ns.guard("vendors", recordVendor)
    end)
end

local handlers = {
    MERCHANT_SHOW = function() ns.guard("vendors", recordVendor) end,
    MERCHANT_UPDATE = scheduleVendorUpdate,
    TRAINER_SHOW = function() ns.guard("trainers", recordTrainer) end,
    TRAINER_UPDATE = function() ns.guard("trainers", recordTrainer) end,
    TAXIMAP_OPENED = function() ns.guard("flightPaths", recordFlightPaths) end,
    GOSSIP_SHOW = function() ns.guard("npcs", recordNPC, "gossip") end,
    QUEST_GREETING = function() ns.guard("npcs", recordNPC, "quest") end,
    QUEST_DETAIL = function() ns.guard("npcs", recordNPC, "quest") end,
    QUEST_PROGRESS = function() ns.guard("npcs", recordNPC, "quest") end,
    QUEST_COMPLETE = function() ns.guard("npcs", recordNPC, "quest") end,
    BANKFRAME_OPENED = function() ns.guard("npcs", recordNPC, "banker") end,

    PLAYER_ENTERING_WORLD = function(isInitialLogin)
        ns.guard("session", startSession, isInitialLogin)
    end,
    PLAYER_XP_UPDATE = function() ns.guard("session", onXP) end,
    PLAYER_LEVEL_UP = function() ns.guard("session", bump, "levelsGained") end,
    PLAYER_DEAD = function() ns.guard("session", bump, "deaths") end,
    QUEST_ACCEPTED = function() ns.guard("session", bump, "questsAccepted") end,
    QUEST_TURNED_IN = function() ns.guard("session", bump, "questsTurnedIn") end,
    PLAYER_REGEN_DISABLED = function() combatStart = time() end,
    PLAYER_REGEN_ENABLED = function()
        local session = ns.characterRecord().session
        if combatStart and session then
            session.combatSeconds = session.combatSeconds + (time() - combatStart)
        end
        combatStart = nil
    end,
}

frame:SetScript("OnEvent", function(_, event, ...)
    local handler = handlers[event]
    if handler then
        ns.guard("tracking", handler, ...)
    end
end)

for event in pairs(handlers) do
    ns.register(frame, event)
end

C_Timer.NewTicker(SESSION_TOUCH_SECONDS, function()
    ns.guard("session", ns.sessionTouch)
end)
