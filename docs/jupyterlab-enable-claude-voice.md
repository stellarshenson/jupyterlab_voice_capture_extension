# Enabling Claude Code `/voice` inside a JupyterLab container

Routes a browser microphone into a sealed JupyterLab container so Claude Code `/voice` can record. The extension delivers PCM to a FIFO; this guide is the PulseAudio + SoX plumbing that turns that FIFO into the default audio source.

## Problem

- Claude `/voice` records via SoX (`rec`); the container has no `/dev/snd`, no PulseAudio, no WSLg → `rec` fails with "could not find a working audio recorder in WSL"
- kernel is `microsoft-standard-WSL2` (`/proc/version`), so Claude takes its WSL branch and expects PulseAudio
- the only real microphone is in the browser (secure context + `getUserMedia`); the bridge carries that audio in and presents it to SoX as the default PulseAudio source

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

- **Extension half** - browser capture + server-extension websocket writing raw PCM to a FIFO; already built, not changed here
- **Container plumbing** (this guide) - PulseAudio reads the FIFO, exposes it as the default source, SoX records it

## Wire contract (fixed by the extension)

| Property      | Value                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| Sink          | FIFO at `/run/voice/voice.fifo` (set via `c.VoiceCapture.sink_path`; extension default is `/tmp/voice.fifo`) |
| Sample format | signed 16-bit little-endian PCM                                                                              |
| Sample rate   | 16000 Hz                                                                                                     |
| Channels      | 1 (mono)                                                                                                     |
| Frame         | 20 ms = 640 bytes, binary websocket messages                                                                 |
| WS endpoint   | `…/jupyterlab-voice-capture-extension/stream` (inherits Jupyter token auth)                                  |

- extension is the FIFO **writer**, the plumbing is the **reader**; the writer opens `O_WRONLY|O_NONBLOCK` and polls (ENXIO until a reader attaches), so PulseAudio opening the read end unblocks it
- sink lives under `/run`, not `/tmp` - `/run` is runtime state, never age-reaped mid-session; it is tmpfs, recreated empty at boot (see Durability)
- the path is a private rendezvous (`c.VoiceCapture.sink_path` must equal `module-pipe-source file=`), not an OS-standard location

## CLI (the fast path)

The extension ships an operator CLI that performs and verifies all the plumbing below. The extension itself never touches PulseAudio or SoX (acceptance group F); the CLI is a separate tool you run by hand.

```bash
# one-time: install stack, provision /run/voice, start PulseAudio, expose + default the source
jupyterlab_voice_capture_extension install

# check every component and print how to fix whatever is missing
jupyterlab_voice_capture_extension validate

# bring the daemon + source back up after a restart, without re-installing
jupyterlab_voice_capture_extension start -d

# kill the daemon
jupyterlab_voice_capture_extension stop
```

- `install` - provisions the whole bridge in four steps (detailed below); installs via apt only
- `validate` - checks every component, prints fixes plus the `c.VoiceCapture.sink_path` line and the `AUDIODRIVER=pulseaudio` export; exits `0` when all present, `1` when anything is missing; add `--json` for a machine-readable report (no colour)
- `start` - (re)starts only the daemon + source (step 3 below); `-d`/`--detached` returns immediately; use after a restart once packages exist
- `stop` - kills the userspace daemon (`pulseaudio --kill`)
- `--sink-path PATH` - overrides the FIFO path on `install`/`validate`/`start` (default `/run/voice/voice.fifo`)

Output is coloured only for status - green OK, red missing, yellow warning - and only when stdout is an interactive terminal (`NO_COLOR` and `--json` disable it).

### What `install` does

`install` runs four idempotent steps and re-runs safely (it skips a daemon or source already up):

- **installs packages** - `apt-get update` then `apt-get install -y pulseaudio pulseaudio-utils sox libsox-fmt-pulse`; uses `sudo` when not already root (the password prompt passes straight through). conda is not used: the conda-forge `sox` ships without the pulseaudio I/O driver, so the recorder must be the Debian `sox` + `libsox-fmt-pulse` build. If apt is absent or fails, it prints exactly which packages to install another way
- **provisions the runtime dir** - `sudo install -d` creates the sink's parent dir (`/run/voice`) owned by the Jupyter-server user
- **starts PulseAudio + the source** - launches the userspace daemon (`-n`, no card scan), loads `module-pipe-source` reading the sink FIFO, and sets it as the default source `voicein`
- **makes the daemon discoverable** - appends `default-server = unix:/tmp/pulse-lab/native` to `/etc/pulse/client.conf` so env-less clients (Claude's `rec`) find it

It does **not** change two things, by design - those stay the operator's: `c.VoiceCapture.sink_path` in the Jupyter config, and `AUDIODRIVER=pulseaudio` in the shell that launches `claude`. Run `validate` afterwards to confirm.

## Prerequisites

- server extension enabled: `jupyter server extension list | grep voice`
- a Debian/Ubuntu base with `apt`, and a user with `sudo` (package install, `/run/voice`, `/etc/pulse/client.conf`)
- browser reaches JupyterLab over a secure context (https or `localhost`)

## Manual setup (what the CLI does)

### 1. Point the extension at the sink - operator step, no CLI

- create the runtime dir owned by the Jupyter-server user: `sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" /run/voice`
- set `c.VoiceCapture.sink_path = "/run/voice/voice.fifo"` in `jupyter_server_config.py`, then restart the server
- confirm in the log: `Registered jupyterlab_voice_capture_extension server extension (sink=/run/voice/voice.fifo)`
- `FifoSink` creates the FIFO file but not its parent dir, so the dir must exist before capture starts

### 2. Install the audio stack - CLI: `install`

```bash
sudo apt-get update
sudo apt-get install -y pulseaudio pulseaudio-utils sox libsox-fmt-pulse
```

- SoX needs the `pulseaudio` driver (`sox -h | grep -iA1 'AUDIO DEVICE DRIVERS'`); on Debian it comes from `libsox-fmt-pulse`
- conda is deliberately not used - the conda-forge `sox` build omits the pulseaudio driver, so installing it would only shadow a pulse-capable system sox on PATH

### 3. Start the userspace daemon + source - CLI: `install` or `start`

```bash
export PULSE_RUNTIME_PATH=/tmp/pulse-lab
mkdir -p "$PULSE_RUNTIME_PATH" && chmod 700 "$PULSE_RUNTIME_PATH"

pulseaudio --daemonize=yes --exit-idle-time=-1 -n --load="module-native-protocol-unix"

pactl load-module module-pipe-source \
  source_name=voicein file=/run/voice/voice.fifo format=s16le rate=16000 channels=1
pactl set-default-source voicein
```

- `-n` skips the default config so the daemon does not scan for non-existent sound cards
- verify: `pactl list short sources` shows `voicein … s16le 1ch 16000Hz`; `pactl info | grep 'Default Source'` shows `voicein`
- load the pipe-source with `pactl` after the daemon is up - an inline `--load=module-pipe-source …` with spaces is silently dropped by argument parsing

### 4. Make the daemon discoverable env-less - CLI: `install`

- `/voice` runs in a separate `claude` process with no `PULSE_*` env, so set a system-wide default server: `echo "default-server = unix:/tmp/pulse-lab/native" | sudo tee -a /etc/pulse/client.conf`
- verify env-less: `env -u PULSE_RUNTIME_PATH -u PULSE_SERVER -u XDG_RUNTIME_DIR pactl info` → `Server String: unix:/tmp/pulse-lab/native`, `Default Source: voicein`

### 5. Export `AUDIODRIVER` for the claude process - operator step, no CLI

- `rec` has no compiled-in default device; without a driver hint it exits 1 and Claude's `rec --version` probe reads "no working recorder"
- bash: `export AUDIODRIVER=pulseaudio` · fish: `set -gx AUDIODRIVER pulseaudio`, then launch `claude`
- must be set in the claude process itself; `AUDIODEV` is not needed (the pulse driver resolves to the default source `voicein`)

## Verification gate

Run `jupyterlab_voice_capture_extension validate`, or by hand:

```bash
# 1. Claude's exact probe must exit 0
AUDIODRIVER=pulseaudio rec --version >/dev/null 2>&1; echo "exit=$?"

# 2. real capture (toggle the browser mic on and speak)
AUDIODRIVER=pulseaudio timeout 4 rec -c1 -r16000 -b16 /tmp/t.wav trim 0 2
sox /tmp/t.wav -n stat 2>&1 | grep -iE 'Maximum amplitude|RMS'
```

- (1) must be 0; (2) silence ≈ Max 0.0004, real speech ≈ Max 0.2 (a ~500x jump)
- both pass → `/voice` works; run `/voice tap` in a claude session launched with `AUDIODRIVER=pulseaudio`

## Operation

- click the status-bar mic (or palette **Toggle Voice Capture**) → Connecting, then a subtle green glow (Connected) while streaming; the browser shows its active-mic indicator
- `/voice` (hold or tap) records from `voicein`; one browser tab streams at a time (last-writer-wins)
- speak at normal-to-firm volume - RMS < 0.01 transcribes poorly
- setting **Auto-connect on startup** (`autoConnect`, Settings → Voice Capture) starts capture as JupyterLab loads; off by default

## Durability

Runtime state is live-only and lost on container restart: `/run/voice`, the daemon, the `client.conf` line, the packages, the `AUDIODRIVER` export. Persist with a start hook that each boot:

- installs packages if absent (or bake them into the image - the durable option)
- recreates `/run/voice` owned by the Jupyter-server user (`/run` is wiped at boot)
- starts the daemon + `voicein` (`jupyterlab_voice_capture_extension start -d`)
- writes the `client.conf` default-server line if missing
- exports `AUDIODRIVER=pulseaudio` via the shell rc (`~/.bashrc` / fish `config.fish`)

- `install` covers the one-time setup; wire `start -d` into the boot hook for the parts that repeat each boot
- systemd host: declare the dir with `/etc/tmpfiles.d/voice.conf` → `d /run/voice 0755 <jupyter-user> <jupyter-user> -`
- avoid churning the daemon while the extension runs - reloading the pipe-source unlinks/recreates the FIFO, and the writer logs transient `cannot open sink …` until it reopens

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

## Key facts

- `install` / `validate` / `start` / `stop` automate and check this guide; `validate` prints the remaining manual settings (`c.VoiceCapture.sink_path`, `AUDIODRIVER=pulseaudio`)
- Claude's `rec` reaches pulse via `/etc/pulse/client.conf` (no `/mnt/wslg/PulseServer` symlink required); the only blocker was the missing `AUDIODRIVER`
- diagnose the recorder with `strace -f -e trace=execve,connect -p <claude-pid>` while running `/voice` - the decisive lines are `execve("/usr/bin/rec", ["rec","--version"])` and its exit code
- the pulse default source must be `voicein`; SoX with `AUDIODRIVER=pulseaudio` records the default source
- everything downstream of the FIFO is container plumbing; the extension's responsibility ends at delivering correct PCM to the FIFO
