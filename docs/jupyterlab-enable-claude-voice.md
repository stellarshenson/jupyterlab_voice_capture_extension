# Enabling Claude Code `/voice` inside a JupyterLab container

Setup guide for routing a browser microphone into a sealed JupyterLab container so Claude Code's `/voice` mode can record. Written so another agent can reproduce and diagnose the bridge end to end.

## Problem

Claude Code runs inside the JupyterLab single-user container. That container is sealed: no `/dev/snd` capture device, no WSLg, no PulseAudio. Claude's `/voice` records by shelling out to SoX (`rec`), which needs a working audio input. With nothing to record from, `/voice` fails:

```
Voice mode could not find a working audio recorder in WSL.
```

The container's kernel is `microsoft-standard-WSL2` (check `/proc/version`), so Claude takes its **WSL branch** and expects PulseAudio. The microphone that actually exists is in the user's **browser**, which has a secure context and `getUserMedia`. The bridge carries browser audio into the container and presents it to SoX as the default PulseAudio source.

## Architecture

```
 Browser tab (JupyterLab)                         Container
 ┌────────────────────────────┐   ws (token auth)  ┌─────────────────────────────────────┐
 │ jupyterlab_voice_capture   │───────────────────▶│ server extension (routes.py)         │
 │  getUserMedia              │  s16le 16k mono     │  FifoSink writer thread →           │
 │  AudioWorklet → PCM16      │  20 ms / 640 B      │    /run/voice/voice.fifo             │
 │  status-bar mic toggle     │                     │            │                         │
 └────────────────────────────┘                     │            ▼                         │
                                                    │ PulseAudio (userspace daemon)        │
                                                    │  module-pipe-source "voicein"        │
                                                    │  = default source                    │
                                                    │            │                         │
                                                    │            ▼                         │
                                                    │ Claude /voice → rec (SoX)            │
                                                    │  AUDIODRIVER=pulseaudio → default src │
                                                    └─────────────────────────────────────┘
```

Two halves:

- **Extension half** (`jupyterlab_voice_capture_extension`) - browser capture + a Jupyter server-extension websocket that writes raw PCM to a FIFO. Already built; out of scope to change here
- **Container plumbing** (this guide) - PulseAudio reads that FIFO, exposes it as the default source, and SoX records it

## The wire contract (fixed by the extension)

| Property      | Value                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| Sink          | FIFO at `/run/voice/voice.fifo` (set via `c.VoiceCapture.sink_path`; extension default is `/tmp/voice.fifo`) |
| Sample format | signed 16-bit little-endian PCM                                                                              |
| Sample rate   | 16000 Hz                                                                                                     |
| Channels      | 1 (mono)                                                                                                     |
| Frame         | 20 ms = 640 bytes, binary websocket messages                                                                 |
| WS endpoint   | `…/jupyterlab-voice-capture-extension/stream` (inherits Jupyter token auth)                                  |

The extension is the FIFO **writer**; the plumbing is the **reader**. The writer opens `O_WRONLY|O_NONBLOCK` and polls (ENXIO until a reader attaches), so PulseAudio opening the read end is what unblocks it.

This guide uses a **system-wide** sink under `/run` rather than `/tmp`. `/run` (the modern `/var/run`) is reserved for runtime state and, unlike `/tmp`, is never subject to the periodic age-based cleanup that can reap an idle pipe mid-session. It is tmpfs, so it is recreated empty at every boot - the setup provisions it and the durability section keeps it provisioned across restarts. The path is a private rendezvous (`c.VoiceCapture.sink_path` must equal `module-pipe-source file=`), not an OS-standard location.

## Quick start (CLI)

The extension ships an operator CLI that performs and verifies all the plumbing below. The extension itself never touches PulseAudio or SoX (acceptance criteria group F); this CLI is a separate convenience that you run by hand.

```bash
# install packages, provision /run/voice, start PulseAudio, expose + default the source
jupyterlab_voice_capture_extension install

# check every component and print how to fix whatever is missing
jupyterlab_voice_capture_extension validate
```

- `install` prefers **conda** (`conda install -c conda-forge pulseaudio sox` - no root) and falls back to **`sudo apt`** when conda is absent; if apt needs root, sudo prompts you for a password interactively
- `install --dry-run` prints the exact commands without running them
- `--sink-path PATH` overrides the FIFO location for both commands (default `/run/voice/voice.fifo`)
- `validate` prints the `c.VoiceCapture.sink_path` line and the `AUDIODRIVER=pulseaudio` export you still need to set by hand

Two steps are intentionally **not** automated (they belong to the operator): setting `c.VoiceCapture.sink_path` in the Jupyter config, and exporting `AUDIODRIVER=pulseaudio` in the shell that launches `claude`. The sections below document everything the CLI does, for manual setup or debugging.

## Prerequisites

- The `jupyterlab_voice_capture_extension` server extension enabled: `jupyter server extension list | grep voice`
- conda available, or a user with `sudo` (package install, creating `/run/voice`, writing `/etc/pulse/client.conf`)
- The browser reaches JupyterLab over a secure context (https or `localhost`) - required for `getUserMedia`

## Setup (manual equivalent of the CLI)

### 1. Point the extension at a system-wide sink

The sink path is a private contract between the extension (writer) and `module-pipe-source` (reader) - both must reference the same path. Create a runtime directory owned by the user the Jupyter server runs as, then set the path in the server config.

```bash
# create the runtime dir (owned by the Jupyter-server user; /run needs root to create in)
sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" /run/voice
```

```python
# jupyter_server_config.py  (e.g. ~/.jupyter/jupyter_server_config.py
#                                  or /etc/jupyter/jupyter_server_config.py)
c.VoiceCapture.sink_path = "/run/voice/voice.fifo"
```

Restart the Jupyter server so the extension picks up the path. Confirm in the server log:

```
Registered jupyterlab_voice_capture_extension server extension (sink=/run/voice/voice.fifo)
```

`/run` is tmpfs and is wiped at boot, so the `/run/voice` directory must be recreated on each container start - see Durability. `FifoSink` creates the FIFO file itself but not the parent directory, so the directory must exist before capture starts.

### 2. Install the audio stack

Prefer conda (no root); fall back to apt.

```bash
# conda (no root)
conda install -y -c conda-forge pulseaudio sox

# or apt (sudo prompts for a password if needed)
sudo apt-get update
sudo apt-get install -y pulseaudio pulseaudio-utils sox libsox-fmt-pulse
```

SoX needs the `pulseaudio` device driver (verify: `sox -h | grep -iA1 'AUDIO DEVICE DRIVERS'` lists `pulseaudio`). On Debian that driver comes from `libsox-fmt-pulse`; the conda-forge `sox` build includes pulse support.

### 3. Start a userspace PulseAudio daemon

No systemd, no hardware probing. `-n` skips the default config (which would scan for non-existent sound cards); load only the unix socket, then attach the pipe-source.

```bash
export PULSE_RUNTIME_PATH=/tmp/pulse-lab
mkdir -p "$PULSE_RUNTIME_PATH" && chmod 700 "$PULSE_RUNTIME_PATH"

pulseaudio --daemonize=yes --exit-idle-time=-1 -n \
  --load="module-native-protocol-unix"

# Load the pipe-source EXPLICITLY (an inline --load with spaces is silently dropped by
# argument parsing - load it with pactl after the daemon is up).
pactl load-module module-pipe-source \
  source_name=voicein file=/run/voice/voice.fifo format=s16le rate=16000 channels=1
pactl set-default-source voicein
```

Verify: `pactl list short sources` shows `voicein  module-pipe-source.c  s16le 1ch 16000Hz`, and `pactl info | grep 'Default Source'` shows `voicein`.

### 4. Make the daemon discoverable to the claude process (env-less)

`/voice` runs in a **separate** `claude` process that has no `PULSE_*` env pointing at the custom socket. Set a system-wide default server so any libpulse client finds it:

```bash
echo "default-server = unix:/tmp/pulse-lab/native" | sudo tee -a /etc/pulse/client.conf
```

Verify env-less discovery (mimics what `/voice`'s SoX sees):

```bash
env -u PULSE_RUNTIME_PATH -u PULSE_SERVER -u XDG_RUNTIME_DIR \
  pactl info | grep -E 'Server String|Default Source'
# → Server String: unix:/tmp/pulse-lab/native ; Default Source: voicein
```

### 5. The critical env var: `AUDIODRIVER` for the claude process

`rec` (SoX in record mode) has no compiled-in default device in this build; without a driver hint it fails with _"Sorry, there is no default audio device configured"_ and exits 1. Claude's probe runs `rec --version` and treats a non-zero exit as "no working recorder". The fix is to give SoX its driver via env in the shell that launches claude:

```bash
# bash
export AUDIODRIVER=pulseaudio
claude --dangerously-skip-permissions -c
```

```fish
# fish
set -gx AUDIODRIVER pulseaudio
claude --dangerously-skip-permissions -c
```

`AUDIODEV` is not needed - the pulse driver's default device resolves to the default source (`voicein`). This env var **must be present in the claude process**; setting it only in an unrelated shell has no effect.

## Verification gate

```bash
# or just: jupyterlab_voice_capture_extension validate

# 1. Claude's exact probe must return 0:
AUDIODRIVER=pulseaudio rec --version >/dev/null 2>&1; echo "exit=$?"   # need 0

# 2. Real capture through the same path SoX/voice uses (toggle the browser mic on and speak):
AUDIODRIVER=pulseaudio timeout 4 rec -c1 -r16000 -b16 /tmp/t.wav trim 0 2
sox /tmp/t.wav -n stat 2>&1 | grep -iE 'Maximum amplitude|RMS'
# silence ≈ Max 0.0004 ; real speech ≈ Max 0.2 (a ~500x jump)
```

If (1) is 0 and (2) shows a real signal, `/voice` will work. Run `/voice tap` in a claude session launched with `AUDIODRIVER=pulseaudio`.

## Operation

- Click the status-bar microphone (or palette **Toggle Voice Capture**) - the icon shows Connecting then a subtle green glow (Connected) while streaming; the browser shows its active-mic indicator
- In the terminal, `/voice` (hold or tap) records from `voicein`
- One browser tab streams at a time (last-writer-wins); speak at normal-to-firm volume - very quiet input (RMS < 0.01) transcribes poorly

### Auto-connect setting (default off)

The extension exposes one setting (Settings → **Voice Capture**, or Advanced Settings Editor): **Auto-connect on startup** (`autoConnect`). When enabled, capture starts automatically as soon as JupyterLab loads - so the mic is live without a click. It is **off by default** because always-on capture is usually not what you want; leave it off and toggle the status-bar mic when you need it.

## Durability

All of the runtime state is **live-only** and is lost on container restart: the `/run/voice` directory, the daemon, the `client.conf` line, the apt/conda packages, and the `AUDIODRIVER` export. To persist, place a startup hook (e.g. alongside other container-start scripts) that, on each start:

1. Installs the packages if absent (or bake them into the image - the durable option, done in the image build, not here)
2. Creates `/run/voice` owned by the Jupyter-server user (step 1) - `/run` is wiped at boot, so this must run every start
3. Starts the userspace daemon and loads `voicein` as the default source (steps 3-4)
4. Writes the `client.conf` default-server line if missing
5. Exports `AUDIODRIVER=pulseaudio` for launched shells via the shell rc (`~/.bashrc` / fish `config.fish`)

`jupyterlab_voice_capture_extension install` performs 1-4; wire it into the start hook for steps that must repeat each boot. On a systemd host (rather than a container), recreate the directory at boot declaratively instead:

```
# /etc/tmpfiles.d/voice.conf
d /run/voice 0755 <jupyter-user> <jupyter-user> -
```

The FIFO is shared: whichever side starts first creates it (extension at mode 0600, `module-pipe-source` at 0666); both tolerate the other having created it. Avoid churning the daemon while the extension server runs - reloading the pipe-source can briefly unlink/recreate the FIFO and make the extension's writer log transient `cannot open sink … No such file or directory` until it reopens.

## Troubleshooting

| Symptom                                                                                 | Cause                                                           | Fix                                                              |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------- |
| `/voice`: "could not find a working audio recorder"                                     | `rec --version` exits 1 (no default driver)                     | export `AUDIODRIVER=pulseaudio` in the claude shell (step 5)     |
| `rec FAIL sox: Sorry, there is no default audio device configured`                      | same as above, seen directly                                    | same                                                             |
| Extension log: `cannot prepare sink /run/voice/voice.fifo: … No such file or directory` | `/run/voice` directory missing (e.g. after a restart)           | recreate it (step 1); add to the startup hook                    |
| Capture is pure silence (Max ~0.0004)                                                   | browser mic toggle is off, or not streaming                     | toggle mic on; confirm a `101 GET …/stream` in the Jupyter log   |
| Extension log loops `cannot open sink /run/voice/voice.fifo: No such file or directory` | FIFO got unlinked/recreated by churning pulse                   | stop churning; it self-recovers once a stable reader is attached |
| `pactl` returns no sources after daemon start                                           | inline `--load=module-pipe-source …` was dropped by arg parsing | load it with `pactl load-module …` (step 3)                      |
| Claude reaches a different/absent pulse                                                 | a `PULSE_SERVER` in the claude env overrides `client.conf`      | unset it, or point it at `unix:/tmp/pulse-lab/native`            |

Notes confirmed by tracing the live probe: Claude's `rec` reaches pulse via `/etc/pulse/client.conf` (not via any `/mnt/wslg/PulseServer` path - a WSLg symlink is **not** required), and the only blocker was the missing `AUDIODRIVER`.

## Key facts

- `jupyterlab_voice_capture_extension install` / `validate` automate and check this guide; `validate` prints the remaining manual settings (`c.VoiceCapture.sink_path`, `AUDIODRIVER=pulseaudio`)
- Diagnose the recorder with `strace -f -e trace=execve,connect -p <claude-pid>` while running `/voice` - the decisive lines are `execve("/usr/bin/rec", ["rec","--version"])` and its `+++ exited with N +++`
- `rec` is SoX record mode; it honors `AUDIODRIVER` (driver) and `AUDIODEV` (device)
- The pulse default source must be `voicein`; SoX with `AUDIODRIVER=pulseaudio` records the default source
- The sink path is a configured rendezvous (`c.VoiceCapture.sink_path` = `module-pipe-source file=`), not an OS-standard path; `/run/voice/voice.fifo` is chosen because `/run` is runtime state that is not age-reaped like `/tmp`
- Everything downstream of the FIFO is container plumbing; the extension's responsibility ends at delivering correct PCM to the FIFO

```

```
