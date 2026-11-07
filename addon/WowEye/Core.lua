-- Core: saved data, event wiring, the event log and slash commands.
local ADDON, ns = ...

ns.SCHEMA = 2
ns.MAX_EVENTS = 200
ns.CAPTURE_DELAY = 2
ns.MAX_DEPTH = 8
ns.redacted = 0
ns.errors = {}

local function isSecret(v)
    return issecretvalue ~= nil and issecretvalue(v)
end
ns.isSecret = isSecret

-- Runs fn and reports any failure in snapshot.errors under this name.
function ns.guard(name, fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok then
        ns.errors[name] = tostring(err)
    end
end

local function isLockedTable(v)
    if issecrettable ~= nil and issecrettable(v) then
        return true
    end
    return canaccesstable ~= nil and not canaccesstable(v)
end

-- Copies a value into something safe to persist. Secret values are dropped and
-- counted: the addon must never try to read, guess or reconstruct them.
function ns.clean(v, depth)
    depth = depth or 0
    if isSecret(v) then
        ns.redacted = ns.redacted + 1
        return nil
    end
    local t = type(v)
    if t == "string" or t == "number" or t == "boolean" then
        return v
    end
    if t ~= "table" then
        return nil
    end
    if depth >= ns.MAX_DEPTH or isLockedTable(v) then
        ns.redacted = ns.redacted + 1
        return nil
    end
    local out = {}
    for k, val in pairs(v) do
        if isSecret(k) then
            ns.redacted = ns.redacted + 1
        elseif type(k) == "string" or type(k) == "number" then
            out[k] = ns.clean(val, depth + 1)
        end
    end
    return out
end

local function characterKey()
    return UnitName("player") .. "-" .. GetNormalizedRealmName()
end

local function characterRecord()
    local key = characterKey()
    local rec = WowEyeDB.characters[key]
    if not rec then
        rec = { events = {} }
        WowEyeDB.characters[key] = rec
    end
    rec.vendors = rec.vendors or {}
    rec.trainers = rec.trainers or {}
    rec.flightPaths = rec.flightPaths or {}
    rec.sessions = rec.sessions or {}
    WowEyeDB.lastCharacter = key
    return rec
end
ns.characterRecord = characterRecord

function ns.logEvent(event, ...)
    local events = characterRecord().events
    events[#events + 1] = { t = time(), e = event, args = ns.clean({ ... }) }
    while #events > ns.MAX_EVENTS do
        table.remove(events, 1)
    end
end

-- Returns false during combat: snapshots only ever run out of combat.
function ns.capture()
    if InCombatLockdown() then
        return false
    end
    ns.guard("session", ns.sessionTouch)
    ns.guard("completedQuests", ns.captureCompletedQuests)
    characterRecord().snapshot = ns.captureSnapshot()
    return true
end

local pending = false
local function scheduleCapture()
    if pending then
        return
    end
    pending = true
    C_Timer.After(ns.CAPTURE_DELAY, function()
        pending = false
        ns.capture()
    end)
end

-- SavedVariables only reach disk on reload or logout, so this is how the
-- external agent gets fresh data.
function ns.sync()
    if InCombatLockdown() then
        print("|cff66ccffWoW Eye:|r can't sync during combat.")
        return false
    end
    ns.capture()
    ReloadUI()
    return true
end

local LOGGED_EVENTS = {
    "PLAYER_LEVEL_UP",
    "PLAYER_DEAD",
    "QUEST_ACCEPTED",
    "QUEST_TURNED_IN",
    "ZONE_CHANGED_NEW_AREA",
}

local CAPTURE_EVENTS = {
    "PLAYER_ENTERING_WORLD",
    "PLAYER_REGEN_ENABLED",
    "ZONE_CHANGED_NEW_AREA",
    "QUEST_LOG_UPDATE",
    "BAG_UPDATE_DELAYED",
    "PLAYER_EQUIPMENT_CHANGED",
    "PLAYER_MONEY",
    "PLAYER_LEVEL_UP",
}

local isLogged, isCapture = {}, {}
for _, e in ipairs(LOGGED_EVENTS) do isLogged[e] = true end
for _, e in ipairs(CAPTURE_EVENTS) do isCapture[e] = true end

local frame = CreateFrame("Frame")
ns.eventFrame = frame

local function onAddonLoaded()
    WowEyeDB = WowEyeDB or {}
    WowEyeDB.schema = ns.SCHEMA
    WowEyeDB.characters = WowEyeDB.characters or {}
    WowEyeDB.lastInboxSeq = WowEyeDB.lastInboxSeq or 0
    WowEyeDB.lastMarkerSeq = WowEyeDB.lastMarkerSeq or 0
    WowEyeDB.npcs = WowEyeDB.npcs or {}
end

local function onLogin()
    characterRecord()
    ns.initMarkers()
    ns.guard("route", ns.initRoute)
    local seq = WowEyeInbox and WowEyeInbox.seq or 0
    if seq > WowEyeDB.lastInboxSeq then
        print("|cff66ccffWoW Eye:|r new messages from your agent. Type /eye to read them.")
    end
end

frame:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        if ... == ADDON then
            onAddonLoaded()
        end
        return
    end
    if event == "PLAYER_LOGIN" then
        onLogin()
        return
    end
    if isLogged[event] then
        ns.logEvent(event, ...)
    end
    if isCapture[event] then
        scheduleCapture()
    end
end)

-- Registering an event the client doesn't know raises an error. Forever's event
-- list isn't documented anywhere we can check, so one bad name must not stop the rest.
function ns.register(target, event)
    local ok = pcall(target.RegisterEvent, target, event)
    if not ok then
        ns.unknownEvents = ns.unknownEvents or {}
        table.insert(ns.unknownEvents, event)
    end
end

local function register(event)
    ns.register(frame, event)
end

register("ADDON_LOADED")
register("PLAYER_LOGIN")
for e in pairs(isLogged) do register(e) end
for e in pairs(isCapture) do
    if not isLogged[e] then register(e) end
end

-- Called from Bindings.xml. The labels appear in the game's Keybindings menu, under
-- AddOns. Bindings.xml has no header: Forever's menu shows a header as a stray
-- "HEADER_WOWEYE" row rather than a title.
BINDING_NAME_WOWEYE_SYNC = "WoW Eye Sync (reloadUI)"
BINDING_NAME_WOWEYE_PANEL = "Open or close panel"
function WowEye_Sync() ns.sync() end
function WowEye_TogglePanel() ns.togglePanel() end
BINDING_NAME_WOWEYE_ROUTE_NEXT = "Route: next step"
BINDING_NAME_WOWEYE_ROUTE_PREVIOUS = "Route: previous step"
function WowEye_RouteNext() ns.routeNext() end
function WowEye_RoutePrevious() ns.routePrevious() end
BINDING_NAME_WOWEYE_BEACON = "WoW Eye Beacon (toggle)"
function WowEye_ToggleBeacon() ns.toggleBeacon() end
BINDING_NAME_WOWEYE_PARTY = "WoW Eye Party Markers (toggle)"
function WowEye_ToggleParty() ns.toggleCompassParty() end

SLASH_WOWEYE1 = "/eye"
SLASH_WOWEYE2 = "/woweye"
SlashCmdList["WOWEYE"] = function(msg)
    local cmd = (msg or ""):lower():match("^%s*(%S*)")
    if cmd == "sync" then
        ns.sync()
    elseif cmd == "snap" then
        if ns.capture() then
            print("|cff66ccffWoW Eye:|r snapshot captured. /eye sync writes it to disk.")
        else
            print("|cff66ccffWoW Eye:|r no snapshot during combat.")
        end
    elseif cmd == "way" then
        ns.waypointToFirstMarker()
    elseif cmd == "beacon" then
        ns.toggleBeacon()
    elseif cmd == "next" then
        ns.routeNext()
    elseif cmd == "prev" then
        ns.routePrevious()
    elseif cmd == "route" then
        ns.routeStatus()
    elseif cmd == "list" then
        ns.toggleMarkerList()
    elseif cmd == "compass" then
        ns.toggleCompassBar()
    elseif cmd == "party" then
        ns.toggleCompassParty()
    else
        ns.togglePanel()
    end
end
