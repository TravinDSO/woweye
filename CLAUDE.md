# CLAUDE.md

WoW Eye: an AI UI mod for World of Warcraft: Forever, plus a way for an AI agent to read game data. See `README.md` for setup and usage.

## Layout

- `addon/WowEye/`: the addon. `Core.lua` (data, events, slash commands), `Snapshot.lua` (collectors), `Panel.lua` (UI), `Pins.lua` + `Pins.xml` (map markers, beacon, the marker list under the quest tracker), `Route.lua` (multi-step routes), `Tracking.lua` (NPCs, vendors, trainers, flight paths, session stats), `Bindings.xml` (keybindings, loaded automatically, so not in the TOC), `Inbox.lua` (generated, gitignored).
- `src/wow_eye/`: `savedvars.py` (Lua data parser and writer), `bridge.py` (shared logic), `cli.py`, `mcp_server.py`.
- `tests/`: `conftest.py` runs the real addon files in Lua 5.1 (via `lupa`) against a fake WoW API.

```powershell
uv run pytest
uv run wow-eye status
```

## Product direction

The goal is to help the user answer questions, get directed where needed and move through the game faster. The user talks to the agent in their external harness, so don't build in-game text input or a separate chat window. The addon's job is to supply data and show guidance.

## Target client

- Product `wowf`, build 1.60.1.70840 (checked 2026-11-06). The game folder comes from `WOW_EYE_GAME_DIR`, then `game_dir` in `wow-eye.local.toml` (written by `wow-eye game-dir <folder>`), then the standard install folders. Never commit a real path: the local config and `CLAUDE.local.md` are gitignored for machine-specific details.
- `## Interface: 16001` is confirmed by a real snapshot from this client (2026-11-06). Re-check after patches in `wow-eye snapshot --section identity`.
- Sync, map markers and the in-view beacon have been confirmed in the real client. Combat and instance behavior hasn't been tried yet.
- Forever uses the modern retail API, including Midnight's addon restrictions. Classic Era addon code and docs don't apply. Per the wiki, `_Forever` works as a TOC suffix. Its game type in Blizzard's code is `camelot`.
- **Check APIs against the source, not memory.** The `forever` branch of `github.com/Gethe/wow-ui-source` mirrors this client's UI code. `Blizzard_APIDocumentationGenerated` has signatures, and older globals are only visible through how Blizzard's UI calls them. Forever mixes eras: talents use the modern `C_Traits` tree, while trainers and merchants use older globals and Classic-style play.
- Prefer real game data over wikis when locating things: `wow_npcs`, then each quest's `waypoint` and `mapPin`, and only then wikis, saying which source was used.
- Blizzard says restrictions added to retail carry over to Forever, so re-check the API change pages after each patch.

## How data moves

An addon has no file or network access, so these are the only channels:

- **Game to agent:** `WowEyeDB` in `WTF/Account/<ACCOUNT>/SavedVariables/WowEye.lua`. The client writes it only on UI reload or logout. `/eye sync` forces this.
- **Agent to game:** `addon/WowEye/Inbox.lua`, rewritten by the bridge and read by the client on UI reload. Keep the file in the TOC and on disk at game start, because the client won't pick up a new file without a restart.

The client rewrites SavedVariables on reload and logout, so never edit them from outside the game. They would be overwritten.

## Rules

- **Read-only toward the game.** No input automation, memory reading, DLL injection or game-file patching. These risk the user's account.
- **No screen-pixel data channels.** Encoding data in on-screen pixels for an external reader is a known bot technique and sidesteps the restrictions below. Don't add one without an explicit decision from the user.
- **Never work around secret values.** `ns.clean` drops them and counts them in `snapshot.redacted`. Addons may display combat information, but may not calculate or infer it. Don't reconstruct hidden data or solve encounter mechanics.
- **No snapshots in combat.** `ns.capture` refuses during `InCombatLockdown()`.
- **Parse saved data, never execute it.** `savedvars.py` is a data-only parser.
- **Agent text is untrusted in the UI.** Inbox text goes through `savedvars._quote` when written and `literal()` in `Panel.lua` when shown, which stops Lua injection and UI escape codes (`|c`, `|T`, `|H`). Keep both.

## Map markers

- Markers travel in `Inbox.lua`. The bridge takes x and y as percentages (0-100) and stores 0-1 fractions, which is what the map APIs use.
- Pins only show on the exact `mapID` they were set for, not on parent maps such as the continent view. The chat line and waypoint cover that gap.
- Only mark locations with a source, and tell the user the source. Vendor coordinates from wikis can be out of date for Forever, so confirm them with the user.
- Markers are for navigation and questing. Never use them to direct players through encounter mechanics.
- The compass bar (`ns.updateCompass`) is the way to follow several targets at once. Headings and targets are placed by bearing relative to `GetPlayerFacing`, with world positions from `C_Map.GetWorldPosFromMapPos`. Facing is nil in instances, so the bar hides there. It also hides in combat, and it shows nothing rather than guessing when a value is missing or secret. It shows WoW Eye entries and tracked quests by default. It can only be moved while Blizzard's Edit Mode is open: it follows the `EditMode.Enter` and `EditMode.Exit` events from `EventRegistry`, because addon frames can't join Edit Mode itself. Its position is saved in `WowEyeDB.compassPosition`. Per-target overrides are saved in `characterRecord().compass`, where only differences from the default are stored. Quests are toggled from Blizzard's quest menus through `Menu.ModifyMenu` (`MENU_QUEST_OBJECTIVE_TRACKER`, `MENU_QUEST_MAP_LOG_TITLE`). Quest positions come only from the game (`GetNextWaypoint`, then `GetQuestsOnMap` for the player's map).
- The marker list is WoW Eye's own frame docked below `ObjectiveTrackerFrame`, not a tracker module. A module runs addon code inside the tracker's layout pass, which taints quest item button attributes and blocks `UseQuestLogSpecialItem`. Keep it outside the tracker and only touch Blizzard frames through `hooksecurefunc`/`HookScript`.
- The in-view beacon anchors to `C_Navigation.GetFrame()`, the only world-following frame the API offers, so one beacon at a time is a hard limit. It covers WoW Eye markers and the super-tracked quest, picking by `C_SuperTrack.GetHighestPrioritySuperTrackingType` so its label matches what the frame follows. It hides in combat.
- Prefer adding to existing addon files during a play session. New files and TOC edits need a full game restart, while edits to existing files only need a UI reload.
- A new `markerSeq` takes over the player's waypoint once. Reloads must not take it over again, which is what `lastMarkerSeq` is for.

## Routes and tracking

- Route progress lives per character in `WowEyeDB`. A new `routeSeq` restarts at step 1. `ns.routeMarkers` must stay read-only, because the map draws before `ns.initRoute` and would otherwise use up the "new route" signal.
- Use a quest `complete_on` for steps with work to do, so walking past doesn't skip them.
- **Check `wow_completed_quests` before recommending any quest from outside the player's log.** The list is saved on every snapshot, is per character and holds IDs only. It's fresh as of the last sync, and `set_route` warns when a step's quest is already done. Quests from wikis or Classic may have different IDs in Forever, so a "not completed" result only counts if the ID is Forever's own.
- `Tracking.lua` only records windows the player opened and their own character's events. A vendor's stock depends on the game's filter, and a trainer's list on the window's filter buttons, so both are saved next to the data.
- NPC positions are the player's position at the time, which is within interaction range rather than exact.
- A session spans UI reloads and ends at the next real login, which `PLAYER_ENTERING_WORLD`'s `isInitialLogin` tells apart.

## Writing addon code

- Wrap anything that might differ in Forever: collectors run in `pcall`, and `register()` tolerates unknown events. Failures surface in `snapshot.errors` and `snapshot.unknownEvents`, so check `wow-eye status` after a patch.
- New collector: add a function to `collectors` in `Snapshot.lua`. Its result goes through `ns.clean` automatically. Add it to the fake API in `tests/conftest.py` and add a test.
- The fake API doesn't validate frame templates, widget methods or real API behavior. UI changes need checking in the real client, using `/reload` after edits. The install is a junction, so edits to `addon/WowEye` apply directly.
- Turn on Lua errors while developing: `/console scriptErrors 1`.
- While the game is running, a code change takes two syncs to show in saved data. The first still captures with the old code and then loads the new code, and only the second saves what the new code captured.
