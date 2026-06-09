import json

import jupyterlab_voice_capture_extension.cli as cli


def test_install_dry_run_uses_apt_never_conda(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", False)
    # even when conda is present, install must never use it: conda-forge sox lacks the
    # pulseaudio driver, so the recorder always comes from the Debian sox + libsox-fmt-pulse
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    rc = cli.main(["install", "--dry-run", "--sink-path", "/run/voice/voice.fifo"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "DRY RUN" in out
    assert "conda" not in out.lower()
    assert "apt-get update" in out
    assert "apt-get install" in out and "libsox-fmt-pulse" in out
    assert "module-pipe-source" in out
    assert "/run/voice/voice.fifo" in out
    assert "set-default-source voicein" in out


def test_install_dry_run_lists_all_apt_packages(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    rc = cli.main(["install", "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    for pkg in ("pulseaudio", "pulseaudio-utils", "sox", "libsox-fmt-pulse"):
        assert pkg in out


def test_validate_reports_missing_and_prints_config(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli, "_pactl", lambda *a: (1, ""))
    monkeypatch.setattr(cli, "_sox_has_pulse", lambda: False)
    monkeypatch.setattr(cli.os.path, "isdir", lambda p: False)
    monkeypatch.setattr(cli, "_is_fifo", lambda p: False)
    monkeypatch.setattr(cli, "_client_conf_has_default_server", lambda: False)
    monkeypatch.delenv("AUDIODRIVER", raising=False)

    rc = cli.main(["validate"])
    out = capsys.readouterr().out

    assert rc == 1  # something missing
    assert "[MISS]" in out
    assert 'c.VoiceCapture.sink_path = "/run/voice/voice.fifo"' in out
    assert "AUDIODRIVER=pulseaudio" in out


def test_validate_passes_when_everything_present(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", False)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(cli, "_sox_has_pulse", lambda: True)
    monkeypatch.setattr(cli.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(cli, "_is_fifo", lambda p: True)
    monkeypatch.setattr(cli, "_client_conf_has_default_server", lambda: True)
    monkeypatch.setenv("AUDIODRIVER", "pulseaudio")

    def fake_pactl(*args):
        if args and args[0] == "info":
            return 0, f"Server String: x\nDefault Source: {cli.SOURCE_NAME}\n"
        return 0, f"1\t{cli.SOURCE_NAME}\tmodule-pipe-source.c\ts16le 1ch 16000Hz\n"

    monkeypatch.setattr(cli, "_pactl", fake_pactl)

    rc = cli.main(["validate"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[MISS]" not in out
    assert "All components in place." in out


def test_validate_json_is_machine_readable(capsys, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli, "_pactl", lambda *a: (1, ""))
    monkeypatch.setattr(cli, "_sox_has_pulse", lambda: False)
    monkeypatch.setattr(cli.os.path, "isdir", lambda p: False)
    monkeypatch.setattr(cli, "_is_fifo", lambda p: False)
    monkeypatch.setattr(cli, "_client_conf_has_default_server", lambda: False)
    monkeypatch.delenv("AUDIODRIVER", raising=False)

    rc = cli.main(["validate", "--json"])
    out = capsys.readouterr().out

    data = json.loads(out)  # must parse cleanly - no colour codes, no surrounding prose
    assert rc == 1
    assert data["ok"] is False
    assert data["sink_path"] == "/run/voice/voice.fifo"
    assert any(
        c["name"] == "sox pulseaudio driver" and c["ok"] is False for c in data["checks"]
    )
    assert data["missing"]  # at least one missing entry
    assert "\x1b[" not in out  # no ANSI escape sequences in JSON output


def test_validate_json_all_present_exits_zero(capsys, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(cli, "_sox_has_pulse", lambda: True)
    monkeypatch.setattr(cli.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(cli, "_is_fifo", lambda p: True)
    monkeypatch.setattr(cli, "_client_conf_has_default_server", lambda: True)
    monkeypatch.setenv("AUDIODRIVER", "pulseaudio")

    def fake_pactl(*args):
        if args and args[0] == "info":
            return 0, f"Default Source: {cli.SOURCE_NAME}\n"
        return 0, f"1\t{cli.SOURCE_NAME}\tmodule-pipe-source.c\ts16le 1ch 16000Hz\n"

    monkeypatch.setattr(cli, "_pactl", fake_pactl)

    rc = cli.main(["validate", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert data["ok"] is True
    assert data["missing"] == []
