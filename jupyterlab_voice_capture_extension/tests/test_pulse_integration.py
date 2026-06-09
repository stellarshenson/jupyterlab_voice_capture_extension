"""Integration tests for the out-of-scope PulseAudio + SoX recording path.

These exercise the real recorder Claude Code's /voice uses - `rec` (SoX) with
`AUDIODRIVER=pulseaudio` - against a live PulseAudio daemon whose `module-pipe-source`
reads the FIFO the extension writes. They are skipped whenever the audio stack is not
present (e.g. CI), so they never break the unit-test gate; run them on a box where
`jupyterlab_voice_capture install` has set up the bridge.
"""

import os
import re
import shutil
import stat
import subprocess
import time
import wave

import pytest


def _pulse_up() -> bool:
    if shutil.which("pactl") is None:
        return False
    return subprocess.run(["pactl", "info"], capture_output=True).returncode == 0


def _pipe_source_fifo():
    """Return the FIFO path the module-pipe-source reads from, or None."""
    res = subprocess.run(
        ["pactl", "list", "modules"], capture_output=True, text=True
    )
    if res.returncode != 0:
        return None
    in_pipe = False
    for line in res.stdout.splitlines():
        s = line.strip()
        if s.startswith("Name: module-pipe-source"):
            in_pipe = True
        elif in_pipe and s.startswith("Argument:"):
            m = re.search(r"file=(\S+)", s)
            return m.group(1) if m else None
        elif s.startswith("Name:"):
            in_pipe = False
    return None


def _max_amplitude(wav_path: str) -> float:
    res = subprocess.run(
        ["sox", wav_path, "-n", "stat"], capture_output=True, text=True
    )
    m = re.search(r"Maximum amplitude:\s+([0-9.]+)", res.stderr)
    return float(m.group(1)) if m else 0.0


requires_pulse = pytest.mark.skipif(
    shutil.which("rec") is None or shutil.which("sox") is None or not _pulse_up(),
    reason="PulseAudio daemon and SoX (rec/sox) required",
)


@requires_pulse
def test_rec_probe_with_audiodriver_pulseaudio():
    # Exactly the probe Claude runs: `rec --version`. With AUDIODRIVER=pulseaudio it must
    # exit 0, otherwise /voice reports "could not find a working audio recorder".
    env = dict(os.environ, AUDIODRIVER="pulseaudio")
    result = subprocess.run(
        ["rec", "--version"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@requires_pulse
def test_fifo_exists_where_the_source_reads_it():
    # The module-pipe-source declares a FIFO path; that file must actually exist and be a
    # FIFO - i.e. the sink was created in the place the recording side reads from. The
    # extension's c.VoiceCapture.sink_path must point at this same path to deliver audio.
    fifo = _pipe_source_fifo()
    assert fifo is not None, "no module-pipe-source loaded"
    assert os.path.exists(fifo), f"sink FIFO {fifo} does not exist"
    assert stat.S_ISFIFO(os.stat(fifo).st_mode), f"{fifo} is not a FIFO"


@requires_pulse
def test_round_trip_fifo_to_recorder(tmp_path):
    # Full chain: push a loud tone into the sink FIFO (the browser/server end) and record
    # from the default PulseAudio source with AUDIODRIVER=pulseaudio (the /voice end).
    # The captured audio must be clearly non-silent, proving data crosses FIFO -> pulse ->
    # SoX. Silence is ~0.0004 max amplitude; a tone is orders of magnitude higher.
    fifo = _pipe_source_fifo()
    if fifo is None or not stat.S_ISFIFO(os.stat(fifo).st_mode):
        pytest.skip("no pipe-source FIFO available")

    writer = subprocess.Popen(
        [
            "sox", "-n",
            "-t", "raw", "-r", "16000", "-e", "signed", "-b", "16", "-c", "1", fifo,
            "synth", "3", "sine", "440", "vol", "0.8",
        ],
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)  # let the tone start filling the pipe before recording
        out = tmp_path / "cap.wav"
        env = dict(os.environ, AUDIODRIVER="pulseaudio")
        proc = subprocess.run(
            ["rec", "-c", "1", "-r", "16000", "-b", "16", str(out), "trim", "0", "1"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        with wave.open(str(out)) as w:
            assert w.getframerate() == 16000
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2  # s16le
        assert _max_amplitude(str(out)) > 0.01, "captured audio is silent - chain broken"
    finally:
        writer.terminate()
        writer.wait(timeout=5)
