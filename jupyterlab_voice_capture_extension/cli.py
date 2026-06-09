"""Operator CLI for the voice-capture container plumbing.

The extension itself never starts or configures PulseAudio or SoX - per the acceptance
criteria (group F) that plumbing is out of scope of the browser + bridge halves. This CLI
is a separate operator convenience for provisioning and verifying that plumbing inside the
container, exactly as documented in ``docs/jupyterlab-enable-claude-voice.md``.

Commands:
  install   - install packages, provision the FIFO directory, start a userspace PulseAudio
              daemon, expose the pipe-source as the default source, and make it discoverable
  validate  - check every component is in place and print how to configure what is missing,
              including the AUDIODRIVER=pulseaudio setting the claude process needs
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys

DEFAULT_SINK_PATH = "/run/voice/voice.fifo"
SOURCE_NAME = "voicein"
PULSE_RUNTIME_PATH = "/tmp/pulse-lab"
PULSE_SOCKET = f"{PULSE_RUNTIME_PATH}/native"
PULSE_CLIENT_CONF = "/etc/pulse/client.conf"
RATE = 16000
CHANNELS = 1
SAMPLE_FORMAT = "s16le"
APT_PACKAGES = ["pulseaudio", "pulseaudio-utils", "sox", "libsox-fmt-pulse"]

# ------------------------------------------------------------------------------ colour

# conservative palette: status only - success / failure / warning
_ANSI = {"green": "32", "red": "31", "yellow": "33"}
# colour only when the terminal is capable: a real TTY, not a dumb terminal, and NO_COLOR
# unset (https://no-color.org); machine consumers should use --json, which never colours
_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("TERM") != "dumb"
    and os.environ.get("NO_COLOR") is None
)


def _color(enabled: bool) -> None:
    """Override colour output (used to silence colour in --json mode)."""
    global _COLOR
    _COLOR = enabled


def _c(text: str, name: str) -> str:
    return f"\033[{_ANSI[name]}m{text}\033[0m" if _COLOR else text


def _ok() -> str:
    return _c("[ OK ]", "green")


def _miss() -> str:
    return _c("[MISS]", "red")


def _current_user() -> str:
    import getpass

    return getpass.getuser()


def _pulse_env() -> dict:
    env = dict(os.environ)
    env["PULSE_RUNTIME_PATH"] = PULSE_RUNTIME_PATH
    return env


def _run(cmd, *, dry: bool = False, sudo: bool = False) -> int:
    if sudo and os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    print(f"  $ {' '.join(cmd)}")
    if dry:
        return 0
    return subprocess.run(cmd, env=_pulse_env()).returncode


def _pactl(*args) -> tuple[int, str]:
    try:
        res = subprocess.run(
            ["pactl", *args],
            env=_pulse_env(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return res.returncode, (res.stdout or "")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""


def _sox_has_pulse() -> bool:
    try:
        res = subprocess.run(
            ["sox", "-h"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return "pulseaudio" in (res.stdout + res.stderr).lower()


def _client_conf_has_default_server() -> bool:
    try:
        with open(PULSE_CLIENT_CONF, encoding="utf-8") as handle:
            return any(
                line.strip().startswith("default-server")
                and "default-server" in line
                and not line.strip().startswith(";")
                and not line.strip().startswith("#")
                for line in handle
            )
    except OSError:
        return False


def _is_fifo(path: str) -> bool:
    try:
        return stat.S_ISFIFO(os.stat(path).st_mode)
    except OSError:
        return False


def _daemon_running() -> bool:
    rc, _ = _pactl("info")
    return rc == 0


def _source_loaded() -> bool:
    _, sources = _pactl("list", "short", "sources")
    return SOURCE_NAME in sources


def _start_pulse_and_source(sink: str, dry: bool) -> None:
    """Start the userspace PulseAudio daemon (if needed) and expose the pipe-source."""
    if not dry and _daemon_running():
        print("  PulseAudio already running")
    else:
        if not dry:
            os.makedirs(PULSE_RUNTIME_PATH, exist_ok=True)
            os.chmod(PULSE_RUNTIME_PATH, 0o700)
        _run(
            [
                "pulseaudio",
                "--daemonize=yes",
                "--exit-idle-time=-1",
                "-n",
                "--load=module-native-protocol-unix",
            ],
            dry=dry,
        )
    if not dry and _source_loaded():
        print(f"  source '{SOURCE_NAME}' already loaded")
    else:
        _run(
            [
                "pactl",
                "load-module",
                "module-pipe-source",
                f"source_name={SOURCE_NAME}",
                f"file={sink}",
                f"format={SAMPLE_FORMAT}",
                f"rate={RATE}",
                f"channels={CHANNELS}",
            ],
            dry=dry,
        )
    _run(["pactl", "set-default-source", SOURCE_NAME], dry=dry)


def _stop_daemon() -> int:
    return _run(["pulseaudio", "--kill"])


# --------------------------------------------------------------------------- install


def _install_packages(dry: bool) -> None:
    """Install the audio stack via apt (``apt-get update`` + ``install``), using sudo when
    not already root.

    conda is intentionally not used: the conda-forge ``sox`` build ships without the
    pulseaudio I/O driver, so a sox that can record from pulse must come from the Debian
    ``sox`` + ``libsox-fmt-pulse`` build. When apt needs root, sudo prompts the operator
    for a password interactively; this CLI does not capture stdio, so the prompt passes
    straight through to the user's terminal.
    """
    if not dry and shutil.which("apt-get") is None:
        print("  apt-get not found - install these with your platform's package manager:")
        print(f"    {' '.join(APT_PACKAGES)}")
        print("    (sox must include the pulseaudio driver; Debian: libsox-fmt-pulse)")
        return

    need_sudo = os.geteuid() != 0
    if need_sudo and not dry:
        print("  apt needs root - sudo will prompt for your password")
    _run(["apt-get", "update"], dry=dry, sudo=need_sudo)
    rc = _run(["apt-get", "install", "-y", *APT_PACKAGES], dry=dry, sudo=need_sudo)
    if not dry and rc != 0:
        print("  apt install failed - install these another way:")
        print(f"    {' '.join(APT_PACKAGES)}")
        print("    (sox must include the pulseaudio driver; Debian: libsox-fmt-pulse)")


def cmd_install(args) -> int:
    sink = args.sink_path
    sink_dir = os.path.dirname(sink) or "/"
    dry = args.dry_run
    user = _current_user()

    print("Provisioning voice-capture plumbing (operator tool; the extension never does this).")
    if dry:
        print(_c("DRY RUN - nothing will be executed.", "yellow") + "\n")

    print("1) Install packages")
    _install_packages(dry)

    print(f"\n2) Provision runtime dir {sink_dir} (owned by {user})")
    _run(
        ["install", "-d", "-m", "0755", "-o", user, "-g", user, sink_dir],
        dry=dry,
        sudo=True,
    )

    print(f"\n3) Start PulseAudio and expose '{SOURCE_NAME}' -> {sink}")
    _start_pulse_and_source(sink, dry)

    print(f"\n4) Make the daemon discoverable in {PULSE_CLIENT_CONF}")
    line = f"default-server = unix:{PULSE_SOCKET}"
    _run(
        [
            "sh",
            "-c",
            f'grep -qF "{line}" {PULSE_CLIENT_CONF} 2>/dev/null '
            f'|| echo "{line}" >> {PULSE_CLIENT_CONF}',
        ],
        dry=dry,
        sudo=True,
    )

    print("\nDone. Two manual steps remain (intentionally not automated):\n")
    _print_manual_steps(sink)
    print(
        "\nThen verify with:\n"
        "  jupyterlab_voice_capture_extension validate"
    )
    return 0


# -------------------------------------------------------------------------- validate


def cmd_validate(args) -> int:
    sink = args.sink_path
    sink_dir = os.path.dirname(sink) or "/"
    rc_info, info = _pactl("info")
    _, sources = _pactl("list", "short", "sources")

    default_source = ""
    for ln in info.splitlines():
        if ln.startswith("Default Source:"):
            default_source = ln.split(":", 1)[1].strip()

    checks = [
        ("pulseaudio on PATH", shutil.which("pulseaudio") is not None,
         "apt install pulseaudio"),
        ("pactl on PATH", shutil.which("pactl") is not None,
         "apt install pulseaudio-utils"),
        ("sox / rec on PATH", shutil.which("rec") is not None,
         "apt install sox"),
        ("sox pulseaudio driver", _sox_has_pulse(),
         "apt install libsox-fmt-pulse"),
        (f"runtime dir {sink_dir}", os.path.isdir(sink_dir),
         f"sudo install -d -m 0755 -o $(id -un) -g $(id -gn) {sink_dir}"),
        (f"FIFO {sink}", _is_fifo(sink),
         "created by the extension or module-pipe-source once both are running"),
        ("PulseAudio daemon reachable", rc_info == 0,
         "jupyterlab_voice_capture_extension start"),
        (f"source '{SOURCE_NAME}' loaded", SOURCE_NAME in sources,
         "jupyterlab_voice_capture_extension start"),
        (f"default source is '{SOURCE_NAME}'", default_source == SOURCE_NAME,
         f"jupyterlab_voice_capture_extension start  (or: pactl set-default-source {SOURCE_NAME})"),
        ("default-server in client.conf", _client_conf_has_default_server(),
         f'echo "default-server = unix:{PULSE_SOCKET}" | sudo tee -a {PULSE_CLIENT_CONF}'),
        ("AUDIODRIVER=pulseaudio in this env", os.environ.get("AUDIODRIVER") == "pulseaudio",
         "export AUDIODRIVER=pulseaudio  (must be set in the claude process)"),
    ]

    missing = [(label, fix) for label, ok, fix in checks if not ok]
    ok_all = not missing
    sink_line = f'c.VoiceCapture.sink_path = "{sink}"'

    if args.json:
        _color(False)
        payload = {
            "ok": ok_all,
            "sink_path": sink,
            "checks": [
                {"name": label, "ok": ok, "fix": (None if ok else fix)}
                for label, ok, fix in checks
            ],
            "missing": [{"name": label, "fix": fix} for label, fix in missing],
            "config": {
                "sink_path_line": sink_line,
                "audiodriver": "AUDIODRIVER=pulseaudio",
            },
        }
        print(json.dumps(payload, indent=2))
        return 0 if ok_all else 1

    print("Voice-capture component check\n")
    for label, ok, _fix in checks:
        print(f"  {_ok() if ok else _miss()}  {label}")

    if missing:
        print("\n" + _c("How to configure what is missing:", "yellow"))
        for label, fix in missing:
            print(f"  - {label}:")
            print(f"      {fix}")

    print("\nExtension sink path (set in jupyter_server_config.py, then restart the server):")
    print(f"  {sink_line}")

    print("\nMake PulseAudio the SoX driver in the shell that launches claude:")
    print("  bash:  export AUDIODRIVER=pulseaudio")
    print("  fish:  set -gx AUDIODRIVER pulseaudio")

    if ok_all:
        print("\n" + _c("All components in place.", "green"))
    else:
        print("\n" + _c("Some components are missing (see above).", "yellow"))
    return 0 if ok_all else 1


# ----------------------------------------------------------------------- start / stop


def cmd_start(args) -> int:
    sink = args.sink_path
    print(f"Starting PulseAudio voice bridge (source '{SOURCE_NAME}' -> {sink})")
    _start_pulse_and_source(sink, dry=False)
    if not _daemon_running():
        print("Failed to start the PulseAudio daemon.")
        return 1
    if args.detached:
        print(
            "Daemon running (detached). Stop it with: "
            "jupyterlab_voice_capture_extension stop"
        )
        return 0
    print("Daemon running. Press Ctrl-C to stop.")
    try:
        import time

        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping...")
        _stop_daemon()
    return 0


def cmd_stop(args) -> int:
    if not _daemon_running():
        print("PulseAudio daemon is not running.")
        return 0
    print("Stopping PulseAudio daemon...")
    rc = _stop_daemon()
    print("Stopped." if rc == 0 else "Stop command returned non-zero.")
    return rc


def _print_manual_steps(sink: str) -> None:
    print("  a) point the extension at the sink (jupyter_server_config.py), then restart:")
    print(f'       c.VoiceCapture.sink_path = "{sink}"')
    print("  b) set the SoX driver in the shell that launches claude:")
    print("       bash:  export AUDIODRIVER=pulseaudio")
    print("       fish:  set -gx AUDIODRIVER pulseaudio")


# ------------------------------------------------------------------------------ main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="jupyterlab_voice_capture_extension",
        description="Provision and verify the voice-capture container plumbing "
        "(PulseAudio + SoX bridge for the FIFO the extension writes).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser(
        "install", help="install and configure the audio plumbing"
    )
    p_install.add_argument(
        "--sink-path", default=DEFAULT_SINK_PATH, help="FIFO path (default: %(default)s)"
    )
    p_install.add_argument(
        "--dry-run", action="store_true", help="print the commands without running them"
    )
    p_install.set_defaults(func=cmd_install)

    p_validate = sub.add_parser(
        "validate", help="verify components and print how to configure them"
    )
    p_validate.add_argument(
        "--sink-path", default=DEFAULT_SINK_PATH, help="FIFO path (default: %(default)s)"
    )
    p_validate.add_argument(
        "--json", action="store_true", help="emit the component check as JSON (no colour)"
    )
    p_validate.set_defaults(func=cmd_validate)

    p_start = sub.add_parser(
        "start", help="start the PulseAudio daemon and expose the pipe-source"
    )
    p_start.add_argument(
        "--sink-path", default=DEFAULT_SINK_PATH, help="FIFO path (default: %(default)s)"
    )
    p_start.add_argument(
        "-d",
        "--detached",
        action="store_true",
        help="leave the daemon running in the background and return immediately",
    )
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="kill the running PulseAudio daemon")
    p_stop.set_defaults(func=cmd_stop)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
