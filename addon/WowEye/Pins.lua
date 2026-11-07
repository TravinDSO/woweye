-- Pins: draws the agent's markers from Inbox.lua on the world map and sets the
-- Blizzard waypoint. Marker coordinates are 0-1 fractions of the map.
local _, ns = ...

local TEMPLATE = "WowEyePinTemplate"

local function markers()
    return WowEyeInbox and WowEyeInbox.markers or {}
end

function ns.setWaypoint(m)
    if not C_Map.CanSetUserWaypointOnMap(m.mapID) then
        print("|cff66ccffWoW Eye:|r can't set a waypoint on map " .. tostring(m.mapID) .. ".")
        return false
    end
    C_Map.SetUserWaypoint(UiMapPoint.CreateFromCoordinates(m.mapID, m.x, m.y))
    C_SuperTrack.SetSuperTrackedUserWaypoint(true)
    return true
end

function ns.waypointToFirstMarker()
    local m = markers()[1]
    if m then
        return ns.setWaypoint(m)
    end
    print("|cff66ccffWoW Eye:|r no map markers.")
    return false
end

-- Global because Pins.xml refers to it by name.
WowEyePinMixin = CreateFromMixins(MapCanvasPinMixin)

function WowEyePinMixin:OnLoad()
    self:UseFrameLevelType("PIN_FRAME_LEVEL_AREA_POI")
    self:SetScalingLimits(1, 1.0, 1.2)
end

function WowEyePinMixin:OnAcquired(marker)
    self.marker = marker
    self:SetPosition(marker.x, marker.y)
end

function WowEyePinMixin:OnMouseEnter()
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(ns.literal(self.marker.label))
    if self.marker.note then
        GameTooltip:AddLine(ns.literal(self.marker.note), 1, 1, 1, true)
    end
    GameTooltip:AddLine("Click to set waypoint", 0.5, 0.8, 1)
    GameTooltip:Show()
end

function WowEyePinMixin:OnMouseLeave()
    GameTooltip:Hide()
end

-- Route steps move the route along; plain markers just become the waypoint.
function ns.activateMarker(m)
    if m.routeIndex then
        ns.routeGoTo(m.routeIndex)
    else
        ns.setWaypoint(m)
    end
end

function WowEyePinMixin:OnMouseUp()
    ns.activateMarker(self.marker)
end

local provider = CreateFromMixins(MapCanvasDataProviderMixin)

function provider:RemoveAllData()
    self:GetMap():RemoveAllPinsByTemplate(TEMPLATE)
end

function provider:RefreshAllData()
    self:RemoveAllData()
    local mapID = self:GetMap():GetMapID()
    for _, list in ipairs({ markers(), ns.routeMarkers() }) do
        for _, m in ipairs(list) do
            if m.mapID == mapID then
                self:GetMap():AcquirePin(TEMPLATE, m)
            end
        end
    end
end

function ns.refreshPins()
    if provider:GetMap() then
        provider:RefreshAllData()
    end
    ns.refreshMarkerList()
end

local function noteError(err)
    ns.markerError = tostring(err)
end

-- Beacon: a highlight in the 3D view. Addons can't place things at world positions,
-- but the game exposes a frame that follows the tracked waypoint on screen, so the
-- beacon anchors to that. There is only one, so it marks whatever is tracked: a WoW Eye
-- marker or the selected quest.
local BEACON_INTERVAL = 0.2
local WAYPOINT_MATCH = 0.001
local beacon, beaconAnchor

local function buildBeacon()
    local f = CreateFrame("Frame", nil, UIParent)
    f:SetSize(64, 64)
    f:SetFrameStrata("BACKGROUND")

    local ring = f:CreateTexture(nil, "ARTWORK")
    ring:SetTexture("Interface\\Cooldown\\star4")
    ring:SetBlendMode("ADD")
    ring:SetVertexColor(1, 0.82, 0)
    ring:SetAllPoints()

    local pillar = f:CreateTexture(nil, "BACKGROUND")
    pillar:SetTexture("Interface\\Buttons\\WHITE8X8")
    pillar:SetSize(4, 160)
    pillar:SetPoint("BOTTOM", f, "CENTER")
    pillar:SetGradient("VERTICAL", CreateColor(1, 0.82, 0, 0.9), CreateColor(1, 0.82, 0, 0))

    f.label = f:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    f.label:SetPoint("BOTTOM", pillar, "TOP", 0, 4)

    f:SetScript("OnUpdate", function()
        ring:SetAlpha(0.6 + 0.4 * math.sin(GetTime() * 4))
    end)
    return f
end

-- The route comes first, so a step's label wins if a marker shares its position.
function ns.activeMarker()
    if not C_SuperTrack.IsSuperTrackingUserWaypoint() then
        return nil
    end
    local point = C_Map.GetUserWaypoint()
    if not point then
        return nil
    end
    for _, list in ipairs({ ns.routeMarkers(), markers() }) do
        for _, m in ipairs(list) do
            if m.mapID == point.uiMapID
                and math.abs(m.x - point.position.x) < WAYPOINT_MATCH
                and math.abs(m.y - point.position.y) < WAYPOINT_MATCH then
                return m
            end
        end
    end
    return nil
end

-- What the navigation frame is pointing at, if it's something the beacon covers: a
-- WoW Eye marker or the quest selected in the tracker or quest log. Corpses, map pins
-- and other tracked things get no beacon.
local SUPER_TRACK = Enum and Enum.SuperTrackingType or {}
local QUEST = SUPER_TRACK.Quest or 0
local USER_WAYPOINT = SUPER_TRACK.UserWaypoint or 1

local function trackedQuestLabel()
    if not ns.try(C_SuperTrack.IsSuperTrackingQuest) then
        return nil
    end
    local questID = ns.try(C_SuperTrack.GetSuperTrackedQuestID)
    if type(questID) ~= "number" or questID <= 0 then
        return nil
    end
    local title = ns.try(C_QuestLog.GetTitleForQuestID, questID)
    return ns.literal(type(title) == "string" and title or "Quest")
end

-- Older clients without a priority API fall back to checking each kind in turn.
function ns.beaconLabel()
    local kind = ns.try(C_SuperTrack.GetHighestPrioritySuperTrackingType)
    if kind == nil or kind == USER_WAYPOINT then
        local m = ns.activeMarker()
        if m then
            return ns.literal(m.label)
        end
    end
    if kind == nil or kind == QUEST then
        return trackedQuestLabel()
    end
    return nil
end

local function beaconText(label)
    local text = label
    local ok, yards = pcall(C_Navigation.GetDistance)
    if ok and type(yards) == "number" and not (issecretvalue and issecretvalue(yards)) then
        text = text .. string.format(" (%d yds)", math.floor(yards))
    end
    return text
end

function ns.updateBeacon()
    local nav = C_Navigation.GetFrame()
    local label = WowEyeDB.beacon ~= false
        and not InCombatLockdown()
        and nav
        and C_Navigation.HasValidScreenPosition()
        and ns.beaconLabel()
    if not label then
        if beacon then
            beacon:Hide()
        end
        return
    end
    beacon = beacon or buildBeacon()
    ns.beacon = beacon
    if beaconAnchor ~= nav then
        beacon:ClearAllPoints()
        beacon:SetPoint("CENTER", nav, "CENTER")
        beaconAnchor = nav
    end
    beacon.label:SetText(beaconText(label))
    beacon:Show()
end

function ns.toggleBeacon()
    WowEyeDB.beacon = WowEyeDB.beacon == false
    print("|cff66ccffWoW Eye:|r beacon " .. (WowEyeDB.beacon and "on." or "off."))
    ns.updateBeacon()
    ns.refreshMarkerList()
end

local function startBeacon()
    local ticker
    ticker = C_Timer.NewTicker(BEACON_INTERVAL, function()
        local ok, err = pcall(ns.updateBeacon)
        if not ok then
            noteError(err)
            ticker:Cancel()
        end
    end)
end

-- Pins and the waypoint fail separately, and the chat line needs neither, so a
-- map API difference in Forever still leaves the location readable.
function ns.initMarkers()
    local list = markers()
    local ok, err = pcall(function()
        if not WorldMapFrame then
            C_AddOns.LoadAddOn("Blizzard_WorldMap")
        end
        WorldMapFrame:AddDataProvider(provider)
    end)
    if not ok then
        noteError(err)
    end
    startBeacon()

    for _, m in ipairs(list) do
        local where = m.zone and (ns.literal(m.zone) .. " ") or ""
        print(string.format("|cff66ccffWoW Eye:|r %s - %s(%.1f, %.1f)",
            ns.literal(m.label), where, m.x * 100, m.y * 100))
    end

    -- Only take over the player's waypoint when the agent sent something new.
    local seq = WowEyeInbox and WowEyeInbox.markerSeq or 0
    if #list > 0 and seq > WowEyeDB.lastMarkerSeq then
        WowEyeDB.lastMarkerSeq = seq
        local wayOk, wayErr = pcall(ns.waypointToFirstMarker)
        if not wayOk then
            noteError(wayErr)
        end
    end
    ns.refreshMarkerList()
    ns.startCompass()
    ns.guard("questMenus", ns.initQuestMenus)
end

-- Marker list: a "WoW Eye" section under the objective tracker that lists route steps
-- and markers, so they can be read and picked without opening the map.
--
-- It's our own frame, docked below Blizzard's tracker, not a tracker module. A module
-- would run addon code inside the tracker's layout pass, and that taints the
-- attributes on quest item buttons, which blocks UseQuestLogSpecialItem.
local LIST_WIDTH = 260
local LIST_HEADER_HEIGHT = 26
local LIST_ROW_HEIGHT = 30
local LIST_GAP = 6
local LIST_REFRESH_DELAY = 0.5
local EYE_BLUE = { 0.4, 0.8, 1 }
local GOLD = { 1, 0.82, 0 }
local WHITE = { 1, 1, 1 }

local markerList
local listRows = {}

local function setAtlas(texture, atlas)
    pcall(texture.SetAtlas, texture, atlas, true)
end

local function zoneName(m)
    if m.zone then
        return ns.literal(m.zone)
    end
    local info = ns.try(C_Map.GetMapInfo, m.mapID)
    return info and info.name and ns.literal(info.name) or ("map " .. tostring(m.mapID))
end

local function isActive(m, active)
    return active ~= nil
        and m.mapID == active.mapID and m.x == active.x and m.y == active.y
        and m.routeIndex == active.routeIndex
end

local function usable(...)
    for i = 1, select("#", ...) do
        local v = select(i, ...)
        if type(v) ~= "number" or ns.isSecret(v) then
            return false
        end
    end
    return true
end

-- Where a tracked quest goes next: the game's own waypoint when it leads elsewhere,
-- otherwise the quest's spot on the player's current map. Nil if the game gives neither.
local function questLocation(questID)
    local mapID, x, y = ns.try(C_QuestLog.GetNextWaypoint, questID)
    if usable(mapID, x, y) then
        return mapID, x, y
    end
    local playerMap = ns.try(C_Map.GetBestMapForUnit, "player")
    if not usable(playerMap) then
        return nil
    end
    for _, q in ipairs(ns.try(C_QuestLog.GetQuestsOnMap, playerMap) or {}) do
        if q.questID == questID and usable(q.x, q.y) then
            return playerMap, q.x, q.y
        end
    end
    return nil
end

local function selectedQuest()
    if ns.try(C_SuperTrack.IsSuperTrackingQuest) then
        return ns.try(C_SuperTrack.GetSuperTrackedQuestID)
    end
end

-- A quest as a direction target, if the game can place it.
local function questEntry(questID)
    local mapID, x, y = questLocation(questID)
    if not mapID then
        return nil
    end
    local title = ns.try(C_QuestLog.GetTitleForQuestID, questID)
    local target = { mapID = mapID, x = x, y = y }
    return {
        kind = "quest",
        questID = questID,
        key = "q:" .. questID,
        target = target,
        active = questID == selectedQuest(),
        label = ns.literal(type(title) == "string" and title or ("Quest " .. questID)),
        where = string.format("Quest - %s (%.1f, %.1f)", zoneName(target), x * 100, y * 100),
    }
end

-- Route steps, then markers: the order the beacon uses. Quests stay in Blizzard's own
-- lists, where their right-click menus switch their arrows on.
function ns.markerListEntries()
    local active = ns.activeMarker()
    local out = {}
    for _, source in ipairs({ ns.routeMarkers(), markers() }) do
        for _, m in ipairs(source) do
            out[#out + 1] = {
                kind = m.routeIndex and "route" or "marker",
                marker = m,
                key = string.format("p:%d:%.4f:%.4f", m.mapID, m.x, m.y),
                target = m,
                active = isActive(m, active),
                label = ns.literal(m.label),
                where = string.format("%s (%.1f, %.1f)", zoneName(m), m.x * 100, m.y * 100),
            }
        end
    end
    return out
end

-- Quests become the game's tracked target, so the beacon and Blizzard's own arrow
-- follow them; markers and route steps become the waypoint.
local function activateEntry(e)
    if e.kind == "quest" then
        ns.try(C_SuperTrack.SetSuperTrackedUserWaypoint, false)
        C_SuperTrack.SetSuperTrackedQuestID(e.questID)
    else
        ns.activateMarker(e.marker)
    end
    ns.refreshMarkerList()
end

-- Which targets the compass shows. By default: every WoW Eye entry, and every quest in
-- the player's tracker. The row buttons and quest menus override that per target, and
-- only overrides are saved, per character, by key.
local function compassPicks()
    local rec = ns.characterRecord()
    rec.compass = rec.compass or {}
    return rec.compass
end

local function questIDOf(key)
    return tonumber(key:match("^q:(%d+)$"))
end

local function isWatched(questID)
    return ns.try(C_QuestLog.GetQuestWatchType, questID) ~= nil
end

local function shownByDefault(key)
    local questID = questIDOf(key)
    if questID then
        return isWatched(questID)
    end
    return true
end

function ns.isOnCompass(key)
    local choice = compassPicks()[key]
    if choice == nil then
        return shownByDefault(key)
    end
    return choice == true
end

function ns.toggleCompass(key)
    local on = not ns.isOnCompass(key)
    if on == shownByDefault(key) then
        compassPicks()[key] = nil
    else
        compassPicks()[key] = on
    end
    ns.refreshMarkerList()
end

-- Quests for the compass: the tracker's quests in tracker order, then any others the
-- player switched on from the quest log, by ID. A quest the game can't place right now
-- is skipped, not forgotten.
local function compassQuestEntries()
    local ids, seen = {}, {}
    for i = 1, ns.try(C_QuestLog.GetNumQuestWatches) or 0 do
        local questID = ns.try(C_QuestLog.GetQuestIDForQuestWatchIndex, i)
        if usable(questID) and not seen[questID] then
            seen[questID] = true
            ids[#ids + 1] = questID
        end
    end
    local extra = {}
    for key, choice in pairs(compassPicks()) do
        local questID = questIDOf(key)
        if questID and choice == true and not seen[questID] then
            extra[#extra + 1] = questID
        end
    end
    table.sort(extra)
    for _, questID in ipairs(extra) do
        ids[#ids + 1] = questID
    end
    local out = {}
    for _, questID in ipairs(ids) do
        out[#out + 1] = questEntry(questID)
    end
    return out
end

-- Everything that can go on the compass: the list's entries, then quests.
local function compassEntries(listEntries)
    local out = {}
    for _, e in ipairs(listEntries) do
        out[#out + 1] = e
    end
    for _, e in ipairs(compassQuestEntries()) do
        out[#out + 1] = e
    end
    return out
end

-- A finished or abandoned quest drops its override.
function ns.forgetQuest(questID)
    compassPicks()["q:" .. tostring(questID)] = nil
end

local function paintRow(row, hovered)
    local color = (hovered and WHITE) or (row.entry.active and EYE_BLUE) or GOLD
    row.label:SetTextColor(color[1], color[2], color[3])
end

local function paintCompassButton(button, on)
    button.on = on
    button.icon:SetDesaturated(not on)
    if on then
        button.icon:SetVertexColor(1, 0.82, 0)
    else
        button.icon:SetVertexColor(0.5, 0.5, 0.5)
    end
end

local function showRowTooltip(row)
    local e = row.entry
    GameTooltip:SetOwner(row, "ANCHOR_LEFT")
    GameTooltip:SetText(e.label)
    GameTooltip:AddLine(e.where, 0.8, 0.8, 0.8)
    if e.marker and e.marker.note then
        GameTooltip:AddLine(ns.literal(e.marker.note), 1, 1, 1, true)
    end
    local action = e.kind == "quest" and "Click to track this quest" or "Click to set waypoint"
    GameTooltip:AddLine(e.active and "Currently tracked" or action, 0.5, 0.8, 1)
    GameTooltip:Show()
end

local function showCompassTooltip(button)
    local on = ns.isOnCompass(button.row.entry.key)
    GameTooltip:SetOwner(button, "ANCHOR_LEFT")
    GameTooltip:SetText("Compass: " .. (on and "shown" or "hidden"))
    GameTooltip:AddLine("Shows which way this is, and how far, on the WoW Eye compass at the top of the screen.", 1, 1, 1, true)
    GameTooltip:Show()
end

local function buildRow(i)
    local row = CreateFrame("Button", nil, markerList.content)
    row:SetHeight(LIST_ROW_HEIGHT)
    row:SetPoint("TOPLEFT", markerList.content, "TOPLEFT", 20, -(i - 1) * LIST_ROW_HEIGHT)
    row:SetPoint("TOPRIGHT", markerList.content, "TOPRIGHT", 0, -(i - 1) * LIST_ROW_HEIGHT)

    local compass = CreateFrame("Button", nil, row)
    compass.row = row
    compass:SetSize(16, 16)
    compass:SetPoint("TOPRIGHT", row, "TOPRIGHT", -2, -4)
    compass.icon = compass:CreateTexture(nil, "ARTWORK")
    compass.icon:SetAllPoints()
    compass.icon:SetTexture("Interface\\Icons\\Ability_Hunter_Pathfinding")
    compass:SetScript("OnClick", function(self)
        ns.toggleCompass(self.row.entry.key)
        showCompassTooltip(self)
    end)
    compass:SetScript("OnEnter", showCompassTooltip)
    compass:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)
    row.compass = compass

    row.label = row:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    row.label:SetPoint("TOPLEFT", 0, -2)
    row.label:SetPoint("TOPRIGHT", -22, -2)
    row.label:SetJustifyH("LEFT")
    row.label:SetWordWrap(false)

    row.where = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    row.where:SetPoint("TOPLEFT", row.label, "BOTTOMLEFT", 0, -2)
    row.where:SetPoint("TOPRIGHT", row.label, "BOTTOMRIGHT", 0, -2)
    row.where:SetJustifyH("LEFT")
    row.where:SetWordWrap(false)

    row:SetScript("OnClick", function(self)
        activateEntry(self.entry)
    end)
    row:SetScript("OnEnter", function(self)
        paintRow(self, true)
        showRowTooltip(self)
    end)
    row:SetScript("OnLeave", function(self)
        paintRow(self, false)
        GameTooltip:Hide()
    end)
    listRows[i] = row
    return row
end

-- Follows the bottom of the tracker's visible contents. Edit Mode can move the tracker,
-- and the anchors move with it.
local function anchorList()
    local tracker = ObjectiveTrackerFrame
    markerList:ClearAllPoints()
    if not tracker then
        markerList:SetWidth(LIST_WIDTH)
        markerList:SetPoint("TOPRIGHT", UIParent, "TOPRIGHT", -85, -240)
        return
    end
    local above = tracker
    local relativePoint = "TOP"
    if tracker:IsShown() then
        local collapsed = tracker.IsCollapsed and tracker:IsCollapsed()
        if not collapsed and tracker.NineSlice and tracker.NineSlice:IsShown() then
            above, relativePoint = tracker.NineSlice, "BOTTOM"
        elseif tracker.Header then
            above, relativePoint = tracker.Header, "BOTTOM"
        end
    end
    local gap = relativePoint == "BOTTOM" and -LIST_GAP or 0
    markerList:SetPoint("TOP", above, relativePoint, 0, gap)
    markerList:SetPoint("LEFT", tracker, "LEFT")
    markerList:SetPoint("RIGHT", tracker, "RIGHT")
end

-- Hooks only run after Blizzard's code returns, so they can't taint the tracker.
local function followTracker()
    local tracker = ObjectiveTrackerFrame
    if not tracker or not hooksecurefunc then
        return
    end
    local function reanchor()
        if markerList:IsShown() then
            pcall(anchorList)
        end
    end
    if tracker.Update then
        hooksecurefunc(tracker, "Update", reanchor)
    end
    if tracker.SetCollapsed then
        hooksecurefunc(tracker, "SetCollapsed", reanchor)
    end
    tracker:HookScript("OnShow", reanchor)
    tracker:HookScript("OnHide", reanchor)
end

-- The same background the tracker uses, at the opacity set in Edit Mode, so the two
-- read as one panel.
local function buildBackground()
    local bg = CreateFrame("Frame", nil, markerList)
    bg:SetFrameLevel(markerList:GetFrameLevel())
    bg:SetPoint("TOPLEFT", markerList, "TOPLEFT", -30, 4)
    bg:SetPoint("BOTTOMRIGHT", markerList, "BOTTOMRIGHT", 5, -10)
    local ok = NineSliceUtil ~= nil and pcall(NineSliceUtil.ApplyLayoutByName, bg,
        "UniqueCornersLayout", "common-opacity-background")
    if not ok then
        local plain = bg:CreateTexture(nil, "BACKGROUND")
        plain:SetAllPoints()
        plain:SetColorTexture(0, 0, 0, 0.6)
    end
    return bg
end

local function applyOpacity()
    if not markerList then
        return
    end
    local alpha = ObjectiveTrackerManager and ObjectiveTrackerManager.backgroundAlpha or 0
    if type(alpha) ~= "number" then
        alpha = 0
    end
    markerList.backgroundAlpha = alpha
    markerList.background:SetAlpha(alpha)
end

local function followOpacity()
    if ObjectiveTrackerManager and ObjectiveTrackerManager.SetOpacity and hooksecurefunc then
        hooksecurefunc(ObjectiveTrackerManager, "SetOpacity", function()
            pcall(applyOpacity)
        end)
    end
end

-- The beacon toggle in the list header: lit gold when on, dimmed when off.
local function paintBeaconButton(button)
    local on = WowEyeDB.beacon ~= false
    button.on = on
    button.icon:SetDesaturated(not on)
    if on then
        button.icon:SetVertexColor(1, 0.82, 0)
    else
        button.icon:SetVertexColor(0.5, 0.5, 0.5)
    end
end

local function showBeaconTooltip(button)
    GameTooltip:SetOwner(button, "ANCHOR_LEFT")
    GameTooltip:SetText("Beacon: " .. (WowEyeDB.beacon ~= false and "on" or "off"))
    GameTooltip:AddLine("Marks the tracked WoW Eye marker or selected quest in the world.", 1, 1, 1, true)
    GameTooltip:AddLine("Click to turn it " .. (WowEyeDB.beacon ~= false and "off." or "on."), 0.5, 0.8, 1)
    GameTooltip:Show()
end

local function buildBeaconButton(header)
    local button = CreateFrame("Button", nil, header)
    button:SetSize(18, 18)
    button:SetPoint("RIGHT", header.toggle, "LEFT", -6, 0)
    button.icon = button:CreateTexture(nil, "ARTWORK")
    button.icon:SetAllPoints()
    button.icon:SetTexture("Interface\\Cooldown\\star4")
    button.icon:SetBlendMode("ADD")
    local highlight = button:CreateTexture(nil, "HIGHLIGHT")
    highlight:SetAllPoints()
    highlight:SetTexture("Interface\\Cooldown\\star4")
    highlight:SetBlendMode("ADD")
    button:SetScript("OnClick", function(self)
        ns.toggleBeacon()
        showBeaconTooltip(self)
    end)
    button:SetScript("OnEnter", showBeaconTooltip)
    button:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)
    return button
end

local function toggleCollapsed()
    WowEyeDB.markerListCollapsed = not WowEyeDB.markerListCollapsed
    ns.refreshMarkerList()
end

local function buildList()
    markerList = CreateFrame("Frame", "WowEyeMarkerList", UIParent)
    markerList:SetFrameStrata("LOW")
    markerList:SetSize(LIST_WIDTH, LIST_HEADER_HEIGHT)
    markerList:Hide()
    markerList.background = buildBackground()

    local header = CreateFrame("Button", nil, markerList)
    header:SetHeight(LIST_HEADER_HEIGHT)
    header:SetPoint("TOPLEFT")
    header:SetPoint("TOPRIGHT")
    local background = header:CreateTexture(nil, "BACKGROUND")
    background:SetPoint("CENTER")
    setAtlas(background, "UI-QuestTracker-Secondary-Objective-Header")
    header.text = header:CreateFontString(nil, "ARTWORK", "GameFontNormalMed2")
    header.text:SetPoint("LEFT", 7, 0)
    header.toggle = header:CreateTexture(nil, "ARTWORK")
    header.toggle:SetPoint("RIGHT", 1, 0)
    header.beacon = buildBeaconButton(header)
    header:SetScript("OnClick", toggleCollapsed)
    markerList.header = header

    local content = CreateFrame("Frame", nil, markerList)
    content:SetPoint("TOPLEFT", header, "BOTTOMLEFT", 0, -4)
    content:SetPoint("TOPRIGHT", header, "BOTTOMRIGHT", 0, -4)
    content:SetHeight(1)
    markerList.content = content

    -- Tracking changes move the highlight at once. Quest and zone changes come in bursts
    -- (every kill updates the quest log), so those are gathered into one refresh.
    local pending = false
    markerList:SetScript("OnEvent", function(_, event, ...)
        if event == "QUEST_REMOVED" then
            ns.forgetQuest(...)
            ns.refreshMarkerList()
        elseif event == "USER_WAYPOINT_UPDATED" or event == "SUPER_TRACKING_CHANGED" then
            ns.refreshMarkerList()
        elseif not pending then
            pending = true
            C_Timer.After(LIST_REFRESH_DELAY, function()
                pending = false
                ns.refreshMarkerList()
            end)
        end
    end)
    for _, event in ipairs({ "USER_WAYPOINT_UPDATED", "SUPER_TRACKING_CHANGED", "QUEST_REMOVED", "QUEST_WATCH_LIST_CHANGED",
        "QUEST_LOG_UPDATE", "ZONE_CHANGED_NEW_AREA", "ZONE_CHANGED" }) do
        ns.register(markerList, event)
    end

    ns.markerList = markerList
    ns.markerListRows = listRows
    followTracker()
    followOpacity()
end

local function updateList()
    if not markerList then
        buildList()
    end
    local entries = ns.markerListEntries()
    ns.listEntries = entries
    ns.compassEntries = compassEntries(entries)
    if WowEyeDB.markerList == false or #entries == 0 then
        markerList:Hide()
        return
    end
    local collapsed = WowEyeDB.markerListCollapsed == true
    local header = markerList.header
    header.text:SetText(collapsed and ("WoW Eye (" .. #entries .. ")") or "WoW Eye")
    setAtlas(header.toggle, collapsed and "ui-questtrackerbutton-secondary-expand"
        or "ui-questtrackerbutton-secondary-collapse")
    paintBeaconButton(header.beacon)

    for i, e in ipairs(entries) do
        local row = listRows[i] or buildRow(i)
        row.entry = e
        row.label:SetText(e.label)
        row.where:SetText(e.where)
        paintRow(row, false)
        paintCompassButton(row.compass, ns.isOnCompass(e.key))
        row:Show()
    end
    for i = #entries + 1, #listRows do
        listRows[i]:Hide()
    end

    if collapsed then
        markerList.content:Hide()
        markerList:SetHeight(LIST_HEADER_HEIGHT)
    else
        markerList.content:Show()
        markerList:SetHeight(LIST_HEADER_HEIGHT + 4 + #entries * LIST_ROW_HEIGHT)
    end
    anchorList()
    applyOpacity()
    markerList:Show()
end

-- A failure here only costs the list, never the pins, waypoint or route.
function ns.refreshMarkerList()
    local ok, err = pcall(updateList)
    if not ok then
        ns.errors.markerList = tostring(err)
    end
end

function ns.toggleMarkerList()
    WowEyeDB.markerList = WowEyeDB.markerList == false
    print("|cff66ccffWoW Eye:|r marker list " .. (WowEyeDB.markerList and "on." or "off."))
    ns.refreshMarkerList()
end

-- Compass bar: a strip pinned to the top of the screen that turns with the character,
-- like a game compass. Headings (N, NE, E...) and tick marks scroll across it, and each
-- target sits on it as a pin, with its name and distance just below. Targets behind the
-- visible span are pinned to the end of the bar on the side to turn to.
--
-- The beacon can only mark one target, because the game exposes one world-following
-- frame. The bar works from map positions instead, so it can show many at once.
--
-- It needs the player's facing, which the game withholds in instances, and it hides in
-- combat like the beacon. With no facing it shows nothing rather than guess.
local COMPASS_INTERVAL = 0.05
local COMPASS_MAX = 12
local CLOSE_YARDS = 15
local BAR_WIDTH = 640
local BAR_HEIGHT = 26
local BAR_TOP = -4
local BAR_PADDING = 12
local HALF_SPAN = math.pi / 2 -- the bar shows 90 degrees either side of straight ahead
local LABEL_ROW_HEIGHT = 13
local LABEL_ROWS = 2
local LABEL_GAP = 8
local LABEL_NAME_MAX = 24 -- bytes of a name shown on the bar; the tooltip has it whole
local GROUP_PIXELS = 18 -- pins closer than this share one label
local PIN_HIT_WIDTH = 20
local QUEST_GOLD = { 1, 0.82, 0 }
local CLOSE_GREEN = { 0.3, 1, 0.3 }

-- Bearings are radians counter-clockwise from north, the way the game measures facing.
local HEADINGS = {
    { "N", 0, true }, { "NW", math.pi / 4 }, { "W", math.pi / 2, true }, { "SW", 3 * math.pi / 4 },
    { "S", math.pi, true }, { "SE", -3 * math.pi / 4 }, { "E", -math.pi / 2, true }, { "NE", -math.pi / 4 },
}
local TICK_STEP = math.pi / 12 -- every 15 degrees

local compass
local headingMarks, tickMarks = {}, {}
local compassSlots = {}

local function wrapAngle(a)
    while a > math.pi do
        a = a - 2 * math.pi
    end
    while a <= -math.pi do
        a = a + 2 * math.pi
    end
    return a
end

-- Where a turn of `angle` (positive is left) falls on the bar, and which end a target
-- is pinned to when it's outside the visible span.
function ns.compassBarX(angle)
    local half = BAR_WIDTH / 2
    if math.abs(angle) <= HALF_SPAN then
        return half - (angle / HALF_SPAN) * (half - BAR_PADDING), nil
    end
    if angle > 0 then
        return BAR_PADDING, "left"
    end
    return BAR_WIDTH - BAR_PADDING, "right"
end

local function solid(parent, layer, r, g, b, a)
    local t = parent:CreateTexture(nil, layer)
    t:SetColorTexture(r, g, b, a)
    return t
end

local function placeCompass()
    compass:ClearAllPoints()
    local p = WowEyeDB.compassPosition
    if type(p) == "table" and type(p.point) == "string" and type(p.x) == "number" and type(p.y) == "number" then
        compass:SetPoint(p.point, UIParent, p.relativePoint or p.point, p.x, p.y)
    else
        compass:SetPoint("TOP", UIParent, "TOP", 0, BAR_TOP)
    end
end

local function saveCompassPosition()
    local point, _, relativePoint, x, y = compass:GetPoint(1)
    if type(point) == "string" and type(x) == "number" and type(y) == "number" then
        WowEyeDB.compassPosition = { point = point, relativePoint = relativePoint, x = x, y = y }
    end
end

-- Edit Mode: addons can't join Blizzard's Edit Mode systems, but it announces when it
-- opens and closes. While it's open the bar is highlighted and can be dragged, and a
-- right-click puts it back at the top of the screen. The rest of the time the bar
-- ignores the mouse, so it can't get in the way of play.
local function showEditTooltip()
    GameTooltip:SetOwner(compass, "ANCHOR_BOTTOM")
    GameTooltip:SetText("WoW Eye compass")
    GameTooltip:AddLine("Drag to move. Right-click to put it back at the top.", 1, 1, 1, true)
    GameTooltip:Show()
end

function ns.setCompassEditing(editing)
    if not compass then
        return
    end
    ns.compassEditing = editing
    compass:EnableMouse(editing)
    if editing then
        compass.editHighlight:Show()
        compass.editLabel:Show()
    else
        compass.editHighlight:Hide()
        compass.editLabel:Hide()
        GameTooltip:Hide()
    end
    pcall(ns.updateCompass)
end

local function enableEditMode()
    compass:SetMovable(true)
    compass:SetClampedToScreen(true)
    compass:RegisterForDrag("LeftButton")
    compass:SetScript("OnDragStart", function(self)
        if ns.compassEditing then
            self:StartMoving()
        end
    end)
    compass:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        saveCompassPosition()
    end)
    compass:SetScript("OnMouseUp", function(_, button)
        if ns.compassEditing and button == "RightButton" then
            WowEyeDB.compassPosition = nil
            placeCompass()
        end
    end)
    compass:SetScript("OnEnter", function()
        if ns.compassEditing then
            showEditTooltip()
        end
    end)
    compass:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)

    compass.editHighlight = solid(compass, "OVERLAY", 0.25, 0.6, 1, 0.3)
    compass.editHighlight:SetAllPoints()
    compass.editHighlight:Hide()
    compass.editLabel = compass:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    compass.editLabel:SetPoint("TOP", compass, "BOTTOM", 0, -2)
    compass.editLabel:SetText("WoW Eye compass")
    compass.editLabel:Hide()

    if EventRegistry and EventRegistry.RegisterCallback then
        local owner = {}
        EventRegistry:RegisterCallback("EditMode.Enter", function()
            ns.setCompassEditing(true)
        end, owner)
        EventRegistry:RegisterCallback("EditMode.Exit", function()
            ns.setCompassEditing(false)
        end, owner)
    end
end

-- The bar itself only takes the mouse in Edit Mode; its pins and labels do, for tooltips.
local function buildCompass()
    compass = CreateFrame("Frame", "WowEyeCompass", UIParent)
    compass:SetFrameStrata("LOW")
    compass:SetSize(BAR_WIDTH, BAR_HEIGHT)
    compass:EnableMouse(false)
    compass:Hide()
    placeCompass()
    enableEditMode()

    local background = solid(compass, "BACKGROUND", 0, 0, 0, 0.55)
    background:SetAllPoints()
    for _, edge in ipairs({ "TOP", "BOTTOM" }) do
        local line = solid(compass, "BORDER", 1, 0.82, 0, 0.35)
        line:SetHeight(1)
        line:SetPoint(edge .. "LEFT")
        line:SetPoint(edge .. "RIGHT")
    end
    -- Straight ahead.
    local center = solid(compass, "OVERLAY", 1, 0.82, 0, 0.9)
    center:SetSize(2, 8)
    center:SetPoint("TOP", compass, "TOP", 0, 0)

    for _, h in ipairs(HEADINGS) do
        local text = compass:CreateFontString(nil, "ARTWORK", h[3] and "GameFontNormal" or "GameFontHighlightSmall")
        text:SetText(h[1])
        headingMarks[#headingMarks + 1] = { region = text, angle = h[2], text = h[1] }
    end
    for i = 0, 23 do
        local angle = i * TICK_STEP
        if i % 3 ~= 0 then -- headings sit on every third tick
            local tick = solid(compass, "ARTWORK", 1, 1, 1, 0.35)
            tick:SetSize(1, 6)
            tickMarks[#tickMarks + 1] = { region = tick, angle = angle }
        end
    end

    ns.compass = compass
    ns.compassSlots = compassSlots
    ns.compassHeadings = headingMarks
end

local function layoutScale(facing)
    for _, mark in ipairs(headingMarks) do
        local rel = wrapAngle(mark.angle - facing)
        if math.abs(rel) <= HALF_SPAN then
            mark.x = ns.compassBarX(rel)
            mark.region:ClearAllPoints()
            mark.region:SetPoint("CENTER", compass, "LEFT", mark.x, 0)
            mark.region:Show()
        else
            mark.x = nil
            mark.region:Hide()
        end
    end
    for _, mark in ipairs(tickMarks) do
        local rel = wrapAngle(mark.angle - facing)
        if math.abs(rel) <= HALF_SPAN then
            mark.region:ClearAllPoints()
            mark.region:SetPoint("BOTTOM", compass, "BOTTOMLEFT", ns.compassBarX(rel), 1)
            mark.region:Show()
        else
            mark.region:Hide()
        end
    end
end

-- World positions are in yards, with x pointing north and y pointing west.
local function worldPosition(mapID, x, y)
    if not CreateVector2D then
        return nil
    end
    local continent, pos = ns.try(C_Map.GetWorldPosFromMapPos, mapID, CreateVector2D(x, y))
    if not pos then
        return nil
    end
    local wx, wy = pos.x, pos.y
    if pos.GetXY then
        wx, wy = pos:GetXY()
    end
    if not usable(continent, wx, wy) then
        return nil
    end
    return continent, wx, wy
end

local function playerWorldPosition()
    local mapID = ns.try(C_Map.GetBestMapForUnit, "player")
    if not usable(mapID) then
        return nil
    end
    local pos = ns.try(C_Map.GetPlayerMapPosition, mapID, "player")
    if not pos then
        return nil
    end
    local x, y = pos:GetXY()
    if not usable(x, y) then
        return nil
    end
    return worldPosition(mapID, x, y)
end

-- Targets don't move, so each entry's world position is worked out once.
local function targetWorldPosition(e)
    if e.world == nil then
        local continent, x, y = worldPosition(e.target.mapID, e.target.x, e.target.y)
        e.world = continent and { continent = continent, x = x, y = y } or false
    end
    return e.world or nil
end

-- atan2(west, north) measures the bearing the same way the game measures facing, so
-- their difference is the turn to the target: positive to the left, negative to the
-- right. Nil when the target is on another continent or can't be placed.
function ns.compassReading(e, continent, px, py, facing)
    local w = targetWorldPosition(e)
    if not w or w.continent ~= continent then
        return nil
    end
    local north, west = w.x - px, w.y - py
    return wrapAngle(math.atan2(west, north) - facing), math.sqrt(north * north + west * west)
end

local function colorFor(e, yards)
    if yards <= CLOSE_YARDS then
        return CLOSE_GREEN
    end
    return e.kind == "quest" and QUEST_GOLD or EYE_BLUE
end

-- Shortens a label that has already been through ns.literal. It never cuts inside a
-- UTF-8 character, and never leaves half of an escaped "||" at the end.
local function shortName(s)
    if #s <= LABEL_NAME_MAX then
        return s
    end
    local cut = LABEL_NAME_MAX
    while cut > 1 do
        local nextByte = s:byte(cut + 1)
        if nextByte and nextByte >= 0x80 and nextByte < 0xC0 then
            cut = cut - 1
        else
            break
        end
    end
    local out = s:sub(1, cut)
    local pipes = #out:match("|*$")
    if pipes % 2 == 1 then
        out = out:sub(1, -2)
    end
    return out .. "..."
end

local function showGroupTooltip(slot, owner)
    local group = slot.group
    if not group then
        return
    end
    GameTooltip:SetOwner(owner, "ANCHOR_BOTTOM")
    local count = #group.items
    if count > 1 then
        GameTooltip:SetText(count .. " targets this way")
    end
    for i, item in ipairs(group.items) do
        local e = item.entry
        local c = colorFor(e, item.yards)
        if count > 1 or i > 1 then
            GameTooltip:AddLine(e.label, c[1], c[2], c[3])
        else
            GameTooltip:SetText(e.label, c[1], c[2], c[3])
        end
        GameTooltip:AddLine(string.format("%s - %d yds", e.where, math.floor(item.yards)), 0.8, 0.8, 0.8)
        if e.marker and e.marker.note then
            GameTooltip:AddLine(ns.literal(e.marker.note), 1, 1, 1, true)
        end
    end
    GameTooltip:AddLine("Click to track " .. group.leader.label, 0.5, 0.8, 1)
    GameTooltip:Show()
end

local function hookSlotMouse(slot, owner)
    owner:SetScript("OnEnter", function(self)
        showGroupTooltip(slot, self)
    end)
    owner:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)
    owner:SetScript("OnClick", function()
        if slot.group then
            activateEntry(slot.group.leader)
        end
    end)
end

-- One pin on the bar and one label below it. Both take the mouse for the tooltip; the
-- bar itself doesn't, so only these small areas can catch a click.
local function buildSlot(i)
    local slot = CreateFrame("Button", nil, compass)
    slot:SetSize(PIN_HIT_WIDTH, BAR_HEIGHT)

    slot.pin = solid(slot, "OVERLAY", 1, 1, 1, 1)
    slot.pin:SetSize(9, 9)
    slot.pin:SetPoint("CENTER")
    slot.pin:SetRotation(math.pi / 4)

    slot.labelHit = CreateFrame("Button", nil, compass)
    slot.labelHit:SetHeight(LABEL_ROW_HEIGHT)
    slot.label = slot.labelHit:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    slot.label:SetPoint("CENTER")
    slot.label:SetWordWrap(false)

    hookSlotMouse(slot, slot)
    hookSlotMouse(slot, slot.labelHit)
    compassSlots[i] = slot
    return slot
end

-- Targets whose pins would sit on top of each other share one pin and one label. The
-- label names the one being tracked, or else the nearest, and counts the rest.
local function groupTargets(placed)
    table.sort(placed, function(a, b)
        return a.x < b.x
    end)
    local groups, current = {}, nil
    for _, p in ipairs(placed) do
        if current and current.side == p.side and p.x - current.lastX <= GROUP_PIXELS then
            current.items[#current.items + 1] = p
            current.lastX = p.x
        else
            current = { items = { p }, side = p.side, lastX = p.x }
            groups[#groups + 1] = current
        end
    end
    for _, g in ipairs(groups) do
        table.sort(g.items, function(a, b)
            if a.entry.active ~= b.entry.active then
                return a.entry.active == true
            end
            return a.yards < b.yards
        end)
        g.leader = g.items[1].entry
        g.x, g.yards, g.angle = g.items[1].x, g.items[1].yards, g.items[1].angle
    end
    return groups
end

local function groupText(g)
    local text = string.format("%s  %d yds", shortName(g.leader.label), math.floor(g.yards))
    if #g.items > 1 then
        text = text .. "  +" .. (#g.items - 1)
    end
    if g.side == "left" then
        return "< " .. text
    elseif g.side == "right" then
        return text .. " >"
    end
    return text
end

local function textWidth(fontString, text)
    local width = fontString:GetStringWidth()
    if type(width) ~= "number" or width <= 0 then
        width = #text * 6
    end
    return width
end

-- Groups go left to right, and each label takes the first row where it clears the
-- labels already there. A label that fits nowhere is left off; its pin stays.
local function paintGroups(groups)
    local rowEnds = {}
    for i, g in ipairs(groups) do
        local slot = compassSlots[i] or buildSlot(i)
        slot.group, slot.entry = g, g.leader
        slot.x, slot.side, slot.angle, slot.yards, slot.count = g.x, g.side, g.angle, g.yards, #g.items

        local c = colorFor(g.leader, g.yards)
        slot.pin:SetVertexColor(c[1], c[2], c[3], g.leader.active and 1 or 0.8)
        slot:ClearAllPoints()
        slot:SetPoint("CENTER", compass, "LEFT", g.x, 0)
        slot:Show()

        local text = groupText(g)
        slot.label:SetText(text)
        slot.label:SetTextColor(c[1], c[2], c[3])
        local width = textWidth(slot.label, text)
        local center = math.max(width / 2, math.min(BAR_WIDTH - width / 2, g.x))
        local left, right = center - width / 2, center + width / 2
        slot.row = nil
        for row = 0, LABEL_ROWS - 1 do
            if not rowEnds[row] or left >= rowEnds[row] + LABEL_GAP then
                slot.row = row
                rowEnds[row] = right
                break
            end
        end
        if slot.row then
            slot.labelHit:SetWidth(width)
            slot.labelHit:ClearAllPoints()
            slot.labelHit:SetPoint("TOP", compass, "BOTTOMLEFT", center, -2 - slot.row * LABEL_ROW_HEIGHT)
            slot.labelHit:Show()
        else
            slot.labelHit:Hide()
        end
    end
    for i = #groups + 1, #compassSlots do
        compassSlots[i].group = nil
        compassSlots[i]:Hide()
        compassSlots[i].labelHit:Hide()
    end
end

function ns.updateCompass()
    if not compass then
        buildCompass()
    end
    local facing = ns.try(GetPlayerFacing)
    local hidden = WowEyeDB.compassBar == false or InCombatLockdown() or not usable(facing)
    -- In Edit Mode the bar stays up, so it can be placed even where it would hide.
    if hidden and not ns.compassEditing then
        compass:Hide()
        return
    end
    if not usable(facing) then
        paintGroups({})
        compass:Show()
        return
    end
    layoutScale(facing)

    local placed = {}
    local continent, px, py = playerWorldPosition()
    if continent then
        for _, e in ipairs(ns.compassEntries or {}) do
            if #placed >= COMPASS_MAX then
                break
            end
            if ns.isOnCompass(e.key) then
                local angle, yards = ns.compassReading(e, continent, px, py, facing)
                if angle then
                    local x, side = ns.compassBarX(angle)
                    placed[#placed + 1] = { entry = e, angle = angle, yards = yards, x = x, side = side }
                end
            end
        end
    end
    paintGroups(groupTargets(placed))
    compass:Show()
end

function ns.toggleCompassBar()
    WowEyeDB.compassBar = WowEyeDB.compassBar == false
    print("|cff66ccffWoW Eye:|r compass " .. (WowEyeDB.compassBar and "on." or "off."))
    pcall(ns.updateCompass)
end

function ns.startCompass()
    local ticker
    ticker = C_Timer.NewTicker(COMPASS_INTERVAL, function()
        local ok, err = pcall(ns.updateCompass)
        if not ok then
            ns.errors.compass = tostring(err)
            ticker:Cancel()
            if compass then
                compass:Hide()
            end
        end
    end)
end

-- Quest menus: a "Show on WoW Eye compass" checkbox in the right-click menus of Blizzard's quest
-- tracker and the map's quest log. Menu.ModifyMenu is Blizzard's supported way for addons
-- to extend menus, and it runs addon callbacks apart from Blizzard's code.
--
-- The quest log menu's owner carries its questID. The tracker's menu is owned by the
-- whole tracker, so the quest comes from the row under the mouse, which is what was
-- right-clicked. Its blocks keep the questID in .id and their module in .parentModule.
local MENU_PARENT_DEPTH = 5

local function trackerQuestUnderMouse()
    local foci = GetMouseFoci and GetMouseFoci()
    local frame = foci and foci[1] or (GetMouseFocus and GetMouseFocus())
    for _ = 1, MENU_PARENT_DEPTH do
        if type(frame) ~= "table" then
            return nil
        end
        if frame.parentModule and usable(frame.id) then
            return frame.id
        end
        frame = frame.GetParent and frame:GetParent()
    end
    return nil
end

local function addArrowCheckbox(rootDescription, questID)
    if not usable(questID) or questID <= 0 then
        return
    end
    local key = "q:" .. questID
    rootDescription:CreateDivider()
    rootDescription:CreateCheckbox("Show on WoW Eye compass", function()
        return ns.isOnCompass(key)
    end, function()
        ns.toggleCompass(key)
    end)
end

local function menuHandler(findQuest)
    return function(owner, rootDescription)
        local ok, err = pcall(function()
            addArrowCheckbox(rootDescription, findQuest(owner))
        end)
        if not ok then
            ns.errors.questMenus = tostring(err)
        end
    end
end

function ns.initQuestMenus()
    if not (Menu and Menu.ModifyMenu) then
        return
    end
    Menu.ModifyMenu("MENU_QUEST_OBJECTIVE_TRACKER", menuHandler(trackerQuestUnderMouse))
    Menu.ModifyMenu("MENU_QUEST_MAP_LOG_TITLE", menuHandler(function(owner)
        return type(owner) == "table" and owner.questID or nil
    end))
end
