import json
import os
import time

import pytest
from conftest import Game

from wow_eye import bridge, cli, savedvars

SAVED = """
WowEyeDB = {
["schema"] = 1,
["lastCharacter"] = "Tester-TestRealm",
["lastInboxSeq"] = 2,
["characters"] = {
["Tester-TestRealm"] = {
["snapshot"] = {
["capturedAt"] = %d,
["money"] = 500,
["redacted"] = 1,
},
["events"] = {
{
["e"] = "PLAYER_DEAD",
}, -- [1]
{
["e"] = "PLAYER_LEVEL_UP",
}, -- [2]
},
},
},
}
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    source = tmp_path / "source" / "WowEye"
    source.mkdir(parents=True)
    (source / "WowEye.toc").write_text("x")
    monkeypatch.setenv("WOW_EYE_GAME_DIR", str(game))
    monkeypatch.setattr(bridge, "ADDON_SOURCE", source)
    return game


def write_saved(game):
    path = game / "WTF" / "Account" / "ACCT" / "SavedVariables" / "WowEye.lua"
    path.parent.mkdir(parents=True)
    path.write_text(SAVED % int(time.time()))


def test_status_before_any_data(env):
    s = bridge.status()
    assert s["game_dir_exists"] and not s["addon_installed"] and not s["has_data"]


def test_reads_snapshot_section_and_events(env):
    write_saved(env)
    assert bridge.snapshot()["money"] == 500
    assert bridge.snapshot(section="money") == 500
    assert [e["e"] for e in bridge.events(limit=1)] == ["PLAYER_LEVEL_UP"]
    s = bridge.status()
    assert s["snapshot_age_seconds"] < 60
    assert s["panel_messages_read_through"] == 2


def test_helpful_errors(env):
    with pytest.raises(bridge.BridgeError, match="No WowEye data"):
        bridge.snapshot()
    write_saved(env)
    with pytest.raises(bridge.BridgeError, match="Unknown character"):
        bridge.snapshot(character="Nobody-Nowhere")
    with pytest.raises(bridge.BridgeError, match="Unknown section"):
        bridge.snapshot(section="nope")


def test_messages_accumulate_and_cap(env):
    for i in range(60):
        result = bridge.send_message(f"t{i}", "b")
    assert result["seq"] == 60
    inbox = savedvars.load(bridge.inbox_path())["WowEyeInbox"]
    assert len(inbox["messages"]) == bridge.MAX_INBOX_MESSAGES
    assert inbox["messages"][-1]["title"] == "t59"
    bridge.clear_messages()
    inbox = savedvars.load(bridge.inbox_path())["WowEyeInbox"]
    assert inbox["seq"] == 60 and inbox["messages"] == {}


def test_hostile_message_stays_data_in_real_lua(env):
    body = 'end" os.exit() --\n\\"]] |cffff0000red|r |TInterface:0|t \x01 café'
    bridge.send_message("t", body)
    g = Game(inbox_source=bridge.inbox_path().read_text(encoding="utf-8"))
    g.login()
    assert g.g.WowEyeInbox.messages[1].body == body
    shown = g.ns.formatInbox(g.g.WowEyeInbox)
    assert "||cffff0000red||r" in shown
    assert "||TInterface:0||t" in shown


def test_install_and_uninstall(env):
    assert "Linked" in bridge.install()
    link = bridge.addon_link()
    assert os.path.isjunction(link)
    assert (link / "WowEye.toc").exists()
    assert (link / "Inbox.lua").exists()
    assert "Already" in bridge.install()
    assert "Removed" in bridge.uninstall()
    assert not link.exists()
    assert (bridge.ADDON_SOURCE / "WowEye.toc").exists()


def test_install_never_replaces_a_real_folder(env):
    real = bridge.addon_link()
    real.mkdir(parents=True)
    (real / "mine.txt").write_text("keep")
    with pytest.raises(bridge.BridgeError, match="Move it away"):
        bridge.install()
    assert "Nothing to remove" in bridge.uninstall()
    assert (real / "mine.txt").read_text() == "keep"


def test_cli_prints_json_and_reports_errors(env, capsys):
    assert cli.main(["snapshot"]) == 1
    assert "No WowEye data" in capsys.readouterr().err
    write_saved(env)
    assert cli.main(["snapshot", "--section", "money"]) == 0
    assert json.loads(capsys.readouterr().out) == 500


@pytest.fixture
def no_settings(tmp_path, monkeypatch):
    """No environment variable and an empty config, so nothing on this PC leaks in."""
    monkeypatch.delenv("WOW_EYE_GAME_DIR", raising=False)
    monkeypatch.setattr(bridge, "config_path", lambda: tmp_path / "wow-eye.local.toml")
    return tmp_path


def make_game(root):
    game = root / "World of Warcraft" / "_forever_"
    (game / "Interface").mkdir(parents=True)
    return game


def test_game_folder_is_found_in_a_standard_install(no_settings, monkeypatch):
    missing = no_settings / "a" / "World of Warcraft" / "_forever_"
    found = make_game(no_settings / "b")
    monkeypatch.setattr(bridge, "game_dir_candidates", lambda: [missing, found])
    assert bridge.game_dir() == found


def test_without_an_install_the_first_candidate_is_reported(no_settings, monkeypatch):
    first = no_settings / "x" / "World of Warcraft" / "_forever_"
    monkeypatch.setattr(bridge, "game_dir_candidates", lambda: [first, no_settings / "y"])
    assert bridge.game_dir() == first
    with pytest.raises(bridge.BridgeError, match="game-dir"):
        bridge.install()


def test_saved_game_folder_beats_detection(no_settings, monkeypatch):
    detected = make_game(no_settings / "detected")
    chosen = make_game(no_settings / "chosen")
    monkeypatch.setattr(bridge, "game_dir_candidates", lambda: [detected])
    assert "Saved" in bridge.set_game_dir(str(chosen))
    assert bridge.game_dir() == chosen
    assert cli.main(["game-dir"]) == 0


def test_environment_beats_the_saved_folder(no_settings, monkeypatch):
    bridge.set_game_dir(str(make_game(no_settings / "chosen")))
    monkeypatch.setenv("WOW_EYE_GAME_DIR", str(no_settings / "mine"))
    assert bridge.game_dir() == no_settings / "mine"


def test_saving_a_wrong_folder_is_refused(no_settings):
    with pytest.raises(bridge.BridgeError, match="not found"):
        bridge.set_game_dir(str(no_settings / "nope"))
    (no_settings / "empty").mkdir()
    with pytest.raises(bridge.BridgeError, match="_forever_"):
        bridge.set_game_dir(str(no_settings / "empty"))
    assert not bridge.config_path().exists()


def test_paths_with_backslashes_spaces_and_apostrophes_survive_the_file(no_settings):
    odd = make_game(no_settings / "Bob's Games")
    bridge.set_game_dir(str(odd))
    assert bridge.game_dir() == odd


def test_candidates_cover_program_files_and_drive_roots(monkeypatch):
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates = [str(p) for p in bridge.game_dir_candidates()]
    assert candidates[0] == r"C:\Program Files (x86)\World of Warcraft\_forever_"
    assert r"E:\Games\World of Warcraft\_forever_" in candidates
    assert len(candidates) == len(set(candidates))
