-- Panel: shows what the agent wrote to Inbox.lua. Built on first open so a template
-- problem can't break data capture at load time.
local _, ns = ...

local panel, bodyText

-- "|" starts WoW's UI escape codes (colors, textures, links). Agent text is shown
-- literally, so it can't draw anything but plain text.
local function literal(s)
    return (tostring(s or ""):gsub("|", "||"))
end
ns.literal = literal

function ns.formatInbox(inbox)
    local messages = inbox and inbox.messages
    local parts = {}
    local route = ns.formatRoute()
    if route then
        parts[1] = route
    end
    if (not messages or #messages == 0) and not route then
        return "No messages yet.\n\nYour agent's notes appear here after /eye sync."
    end
    for i = #(messages or {}), 1, -1 do
        local m = messages[i]
        parts[#parts + 1] = "|cffffd100" .. literal(m.title) .. "|r\n" .. literal(m.body)
    end
    return table.concat(parts, "\n\n")
end

local function markRead()
    WowEyeDB.lastInboxSeq = WowEyeInbox and WowEyeInbox.seq or 0
end

local function build()
    panel = CreateFrame("Frame", "WowEyePanel", UIParent, "BasicFrameTemplateWithInset")
    panel:SetSize(420, 480)
    panel:SetPoint("CENTER")
    panel:SetMovable(true)
    panel:SetClampedToScreen(true)
    panel:EnableMouse(true)
    panel:RegisterForDrag("LeftButton")
    panel:SetScript("OnDragStart", panel.StartMoving)
    panel:SetScript("OnDragStop", panel.StopMovingOrSizing)
    panel:Hide()
    panel.TitleText:SetText("WoW Eye")

    local scroll = CreateFrame("ScrollFrame", nil, panel, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", 12, -32)
    scroll:SetPoint("BOTTOMRIGHT", -32, 44)

    local content = CreateFrame("Frame", nil, scroll)
    content:SetSize(370, 1)
    scroll:SetScrollChild(content)

    bodyText = content:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    bodyText:SetPoint("TOPLEFT")
    bodyText:SetWidth(370)
    bodyText:SetJustifyH("LEFT")
    bodyText:SetJustifyV("TOP")
    content.body = bodyText
    panel.content = content

    local sync = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    sync:SetSize(150, 24)
    sync:SetPoint("BOTTOM", 0, 12)
    sync:SetText("Sync (reload UI)")
    sync:SetScript("OnClick", ns.sync)

    table.insert(UISpecialFrames, "WowEyePanel")
end

function ns.togglePanel()
    if not panel then
        build()
    end
    if panel:IsShown() then
        panel:Hide()
        return
    end
    bodyText:SetText(ns.formatInbox(WowEyeInbox))
    panel.content:SetHeight(math.max(1, bodyText:GetStringHeight()))
    markRead()
    panel:Show()
end
