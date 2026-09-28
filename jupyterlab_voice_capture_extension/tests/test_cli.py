import json
import os

import jupyterlab_voice_capture_extension.cli as cli


def test_install_dry_run_uses_apt_never_conda(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", False)
    # even when conda is present, install must never use it: conda-forge sox lacks the
    # pulseaudio driver, so the recorder always comes from the Debian sox + libsox-fmt-pulse
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
    rc = cli.main(["install", "--dry-run", "--sink-path", "/run/voice/pulseaudio.fifo"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "DRY RUN" in out
    assert "conda" not in out.lower()
    assert "apt-get update" in out
    assert "apt-get install" in out and "libsox-fmt-pulse" in out
    assert "/run/voice/pulseaudio.fifo" in out
    # install must NOT start the daemon or load the source - it advises `start` instead
    assert "module-pipe-source" not in out
    assert "set-default-source" not in out
    assert "start" in out


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
    assert 'c.VoiceCapture.sink_path = "/run/voice/pulseaudio.fifo"' in out
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
    assert data["sink_path"] == "/run/voice/pulseaudio.fifo"
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


def _record_runs(monkeypatch):
    """Record the commands start would run, without running any of them."""
    runs = []
    monkeypatch.setattr(cli, "_run", lambda cmd, **kw: runs.append(cmd) or 0)
    return runs


def test_start_removes_a_leftover_fifo_before_loading_the_source(tmp_path, monkeypatch):
    # DEF-CLI-6: module-pipe-source refuses an existing path, so a FIFO left by a killed
    # daemon is removed before the source is loaded.
    sink = str(tmp_path / "pulseaudio.fifo")
    os.mkfifo(sink)
    runs = _record_runs(monkeypatch)
    monkeypatch.setattr(cli, "_daemon_running", lambda: True)
    monkeypatch.setattr(cli, "_source_loaded", lambda: False)

    cli._start_pulse_and_source(sink, dry=False)

    load = next(i for i, cmd in enumerate(runs) if "load-module" in cmd)
    assert ["rm", "-f", sink] in runs[:load]


def test_start_exits_1_when_the_source_did_not_load(tmp_path, capsys, monkeypatch):
    # DEF-CLI-6: a daemon without voicein is a failed start, not exit 0.
    _record_runs(monkeypatch)
    monkeypatch.setattr(cli, "_daemon_running", lambda: True)
    monkeypatch.setattr(cli, "_source_loaded", lambda: False)

    rc = cli.main(["start", "-d", "--sink-path", str(tmp_path / "pulseaudio.fifo")])

    assert rc == 1
    assert "validate" in capsys.readouterr().out



def test_start_keeps_voicein_reading_through_a_drain(tmp_path, monkeypatch):
    # DEF-BRIDGE-7: a loopback from voicein into the voicedrain null sink keeps the
    # pipe-source reading, so no old audio waits in the FIFO for /voice.
    runs = _record_runs(monkeypatch)
    monkeypatch.setattr(cli, "_daemon_running", lambda: True)
    monkeypatch.setattr(cli, "_source_loaded", lambda: False)

    cli._start_pulse_and_source(str(tmp_path / "pulseaudio.fifo"), dry=False)

    loads = [cmd for cmd in runs if "load-module" in cmd]
    assert [cmd[2] for cmd in loads] == ["module-pipe-source", "module-null-sink", "module-loopback"]
    assert "sink_name=voicedrain" in loads[1]
    assert f"source={cli.SOURCE_NAME}" in loads[2] and "sink=voicedrain" in loads[2]
    assert cli.SOURCE_NAME not in "voicedrain"  # _source_loaded matches by substring
