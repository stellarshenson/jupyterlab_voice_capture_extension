import jupyterlab_voice_capture_extension.cli as cli


def test_install_dry_run_prints_commands_without_executing(capsys, monkeypatch):
    # conda present -> install prefers conda; --dry-run only prints, never executes
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: "/usr/bin/conda" if name == "conda" else None
    )
    rc = cli.main(["install", "--dry-run", "--sink-path", "/run/voice/voice.fifo"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "DRY RUN" in out
    assert "conda install" in out and "pulseaudio" in out
    assert "module-pipe-source" in out
    assert "/run/voice/voice.fifo" in out
    assert "set-default-source voicein" in out


def test_install_dry_run_falls_back_to_apt_without_conda(capsys, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # no conda
    rc = cli.main(["install", "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "apt-get install" in out
    assert "libsox-fmt-pulse" in out


def test_validate_reports_missing_and_prints_config(capsys, monkeypatch):
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
