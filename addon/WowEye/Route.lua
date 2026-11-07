-- Route: an ordered plan from the agent that advances without a sync. Each step moves
-- on by arrival or quest state, or by the player's next/previous keys.
local _, ns = ...

local TICK_SECONDS = 1
local DEFAULT_RADIUS_YARDS = 12
local FALLBACK_RADIUS_FRACTION = 0.01

local function steps()
    return WowEyeInbox and WowEyeInbox.route or {}
end

local function routeSeq()
    return WowEyeInbox and WowEyeInbox.routeSeq or 0
end

-- Progress is per character. A new routeSeq from the agent starts over at step 1.
local function progress()
    local rec = ns.characterRecord()
    if not rec.route or rec.route.seq ~= routeSeq() then
        rec.route = { seq = routeSeq(), step = 1 }
        return rec.route, true
    end
    return rec.route, false
end

-- Read-only, so drawing the map at login can't use up the "new route" signal that
-- initRoute relies on.
local function currentStep()
    local saved = ns.characterRecord().route
    return (saved and saved.seq == routeSeq()) and saved.step or 1
end

local function stepLabel(i, step)
    return i .. ". " .. step.label
end

-- Current and remaining steps, as markers for the map and the beacon.
function ns.routeMarkers()
    local out = {}
    local list = steps()
    for i = currentStep(), #list do
        local s = list[i]
        out[#out + 1] = {
            mapID = s.mapID, x = s.x, y = s.y, note = s.note, zone = s.zone,
            label = stepLabel(i, s),
            routeIndex = i,
        }
    end
    return out
end

local function announce(i, step, total)
    local where = step.zone and (ns.literal(step.zone) .. " ") or ""
    print(string.format("|cff66ccffWoW Eye:|r step %d/%d: %s - %s(%.1f, %.1f)",
        i, total, ns.literal(step.label), where, step.x * 100, step.y * 100))
    if step.note then
        print("  " .. ns.literal(step.note))
    end
end

-- Moves to step i. Past the last step, the route is finished.
function ns.routeGoTo(i)
    local list = steps()
    if #list == 0 then
        print("|cff66ccffWoW Eye:|r no route.")
        return
    end
    local p = progress()
    i = math.max(i, 1)
    if i > #list then
        local wasOurs = ns.activeMarker()
        p.step = #list + 1
        p.done = true
        print("|cff66ccffWoW Eye:|r route complete.")
        if wasOurs then
            ns.try(C_Map.ClearUserWaypoint)
        end
    else
        p.step = i
        p.done = nil
        announce(i, list[i], #list)
        ns.setWaypoint(list[i])
    end
    ns.refreshPins()
end

function ns.routeNext()
    ns.routeGoTo(progress().step + 1)
end

function ns.routePrevious()
    ns.routeGoTo(progress().step - 1)
end

function ns.routeStatus()
    local list = steps()
    if #list == 0 then
        print("|cff66ccffWoW Eye:|r no route.")
    elseif progress().done then
        print("|cff66ccffWoW Eye:|r route complete.")
    else
        announce(progress().step, list[progress().step], #list)
    end
end

function ns.formatRoute()
    local list = steps()
    if #list == 0 then
        return nil
    end
    local current = currentStep()
    local goal = WowEyeInbox.routeGoal and (": " .. ns.literal(WowEyeInbox.routeGoal)) or ""
    local lines = { "|cff66ccffRoute" .. goal .. "|r" }
    for i, s in ipairs(list) do
        local mark = i < current and "done" or (i == current and ">>" or " ")
        lines[#lines + 1] = mark .. " " .. i .. ". " .. ns.literal(s.label)
    end
    return table.concat(lines, "\n")
end

-- False if the player isn't on the step's map (another continent, a cave with its own
-- map, an instance). Falls back to map distance if the map has no world size.
local function hasArrived(step)
    local pos = C_Map.GetPlayerMapPosition(step.mapID, "player")
    if not pos then
        return false
    end
    local x, y = pos:GetXY()
    if not x or ns.isSecret(x) or ns.isSecret(y) then
        return false
    end
    local dx, dy = x - step.x, y - step.y
    local width, height = ns.try(C_Map.GetMapWorldSize, step.mapID)
    if width and width > 0 and height and height > 0 then
        local yards = math.sqrt((dx * width) ^ 2 + (dy * height) ^ 2)
        return yards <= (step.radius or DEFAULT_RADIUS_YARDS)
    end
    return math.sqrt(dx ^ 2 + dy ^ 2) <= FALLBACK_RADIUS_FRACTION
end

local function turnedIn(id)
    return C_QuestLog.IsQuestFlaggedCompleted(id)
end

local completeChecks = {
    arrive = hasArrived,
    manual = function() return false end,
    quest_accepted = function(s) return turnedIn(s.questID) or C_QuestLog.IsOnQuest(s.questID) end,
    quest_complete = function(s) return turnedIn(s.questID) or C_QuestLog.IsComplete(s.questID) end,
    quest_turned_in = function(s) return turnedIn(s.questID) end,
}

local function tick()
    if InCombatLockdown() then
        return
    end
    local p = progress()
    local step = steps()[p.step]
    if not step or p.done then
        return
    end
    local check = completeChecks[step.completeOn or "arrive"] or completeChecks.manual
    if check(step) then
        ns.routeGoTo(p.step + 1)
    end
end

function ns.initRoute()
    local list = steps()
    if #list == 0 then
        return
    end
    local p, isNew = progress()
    if isNew then
        ns.routeGoTo(1)
    elseif not p.done then
        announce(p.step, list[p.step], #list)
        if not ns.try(C_Map.GetUserWaypoint) then
            ns.setWaypoint(list[p.step])
        end
    end
    local ticker
    ticker = C_Timer.NewTicker(TICK_SECONDS, function()
        local ok, err = pcall(tick)
        if not ok then
            ns.errors.route = tostring(err)
            ticker:Cancel()
        end
    end)
end
