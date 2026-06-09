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
 │  AudioWorklet → PCM16      │  20 ms / 640 B      │    /run/pulseaudio.fifo              │
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
| Sink          | FIFO at `/run/pulseaudio.fifo` (default; override with `c.VoiceCapture.sink_path` and the CLI `--sink-path`) |
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
# one-time: install stack + write client.conf + the Jupyter config line (does NOT start the daemon)
jupyterlab_voice_capture_extension install

# start the daemon + source (detached); run this after install and after every restart
jupyterlab_voice_capture_extension start -d

# check every component and print how to fix whatever is missing
jupyterlab_voice_capture_extension validate

# kill the daemon
jupyterlab_voice_capture_extension stop
```

- `install` - one-time provisioning (detailed below); installs via apt only and writes both config files; **does not start the daemon** - it ends by telling you to run `start`
- `start` - starts the daemon + loads + defaults the `voicein` source (step 3 below); `-d`/`--detached` returns immediately; run it after `install` and after every container restart
- `validate` - checks every component, prints fixes plus the `c.VoiceCapture.sink_path` line and the `AUDIODRIVER=pulseaudio` export; exits `0` when all present, `1` when anything is missing; add `--json` for a machine-readable report (no colour)
- `stop` - kills the userspace daemon (`pulseaudio --kill`)
- `--sink-path PATH` - overrides the FIFO path on `install`/`validate`/`start` (default `/run/pulseaudio.fifo`)

Output is coloured only for status - green OK, red missing, yellow warning - and only when stdout is an interactive terminal (`NO_COLOR` and `--json` disable it).

### What `install` does

`install` runs four idempotent steps and re-runs safely. It provisions and configures, but **does not start the daemon** - that is left to `start`:

- **installs packages** - `apt-get update` then `apt-get install -y pulseaudio pulseaudio-utils sox libsox-fmt-pulse`; uses `sudo` when not already root (the password prompt passes straight through). conda is not used: the conda-forge `sox` ships without the pulseaudio I/O driver, so the recorder must be the Debian `sox` + `libsox-fmt-pulse` build. If apt is absent or fails, it prints exactly which packages to install another way
- **provisions the runtime dir** - for a custom `--sink-path` under a subfolder, `sudo install -d` creates that dir owned by the Jupyter-server user; for the default `/run/pulseaudio.fifo` the parent `/run` already exists, so it is left untouched (never chowned)
- **writes `client.conf`** - appends `default-server = unix:/tmp/pulse-lab/native` to `/etc/pulse/client.conf` if absent, so env-less clients (Claude's `rec`) find the daemon
- **writes the Jupyter config line** - checks `~/.jupyter/jupyter_server_config.py` and, if no `c.VoiceCapture.sink_path` is set, appends `c.VoiceCapture.sink_path = "<sink>"` (restart the server to apply)

It ends by telling you to run `start -d`. The only thing it leaves to the operator is `AUDIODRIVER=pulseaudio` in the shell that launches `claude` - that must live in the claude process itself. Run `validate` afterwards to confirm.

## Prerequisites

- server extension enabled: `jupyter server extension list | grep voice`
- a Debian/Ubuntu base with `apt`, and a user with `sudo` (package install, `/etc/pulse/client.conf`)
- browser reaches JupyterLab over a secure context (https or `localhost`)

## Manual setup (what the CLI does)

### 1. Point the extension at the sink - CLI: `install` writes this

- set `c.VoiceCapture.sink_path = "/run/pulseaudio.fifo"` in `~/.jupyter/jupyter_server_config.py`, then restart the server (`install` writes this line for you if it is absent)
- the extension default is already `/run/pulseaudio.fifo`, so this only matters when you choose a different sink
- confirm in the log: `Registered jupyterlab_voice_capture_extension server extension (sink=/run/pulseaudio.fifo)`
- `FifoSink` creates the FIFO file but not its parent dir; `/run` always exists, so the writer (the Jupyter server) only needs permission to create a file there

### 2. Install the audio stack - CLI: `install`

```bash
sudo apt-get update
sudo apt-get install -y pulseaudio pulseaudio-utils sox libsox-fmt-pulse
```

- SoX needs the `pulseaudio` driver (`sox -h | grep -iA1 'AUDIO DEVICE DRIVERS'`); on Debian it comes from `libsox-fmt-pulse`
- conda is deliberately not used - the conda-forge `sox` build omits the pulseaudio driver, so installing it would only shadow a pulse-capable system sox on PATH

### 3. Start the userspace daemon + source - CLI: `start`

```bash
export PULSE_RUNTIME_PATH=/tmp/pulse-lab
mkdir -p "$PULSE_RUNTIME_PATH" && chmod 700 "$PULSE_RUNTIME_PATH"

pulseaudio --daemonize=yes --exit-idle-time=-1 -n --load="module-native-protocol-unix"

pactl load-module module-pipe-source \
  source_name=voicein file=/run/pulseaudio.fifo format=s16le rate=16000 channels=1
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

Runtime state is live-only and lost on container restart: the daemon, the FIFO, the packages. The `client.conf` and Jupyter config lines persist (they live on disk), but `/run` is tmpfs and the daemon is a process, so both vanish at boot. Persist with a start hook that each boot:

- installs packages if absent (or bake them into the image - the durable option)
- starts the daemon + `voicein` (`jupyterlab_voice_capture_extension start -d`); this recreates the FIFO at `/run/pulseaudio.fifo`
- exports `AUDIODRIVER=pulseaudio` via the shell rc (`~/.bashrc` / fish `config.fish`)

- `install` covers the one-time setup (packages + both config files); wire `start -d` into the boot hook for the parts that repeat each boot
- the sink lives directly in `/run` (always present), so no runtime dir needs recreating - only the FIFO, which `start` (via `module-pipe-source`) and the extension's `FifoSink` each create on demand
- avoid churning the daemon while the extension runs - reloading the pipe-source unlinks/recreates the FIFO, and the writer logs transient `cannot open sink …` until it reopens

## Troubleshooting

| Symptom                                                                                | Cause                                                           | Fix                                                                                                                        |
| -------------------------------------------------------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `/voice`: "could not find a working audio recorder"                                    | `rec --version` exits 1 (no default driver)                     | export `AUDIODRIVER=pulseaudio` in the claude shell (step 5)                                                               |
| `rec FAIL sox: Sorry, there is no default audio device configured`                     | same as above, seen directly                                    | same                                                                                                                       |
| Extension log: `cannot prepare sink /run/pulseaudio.fifo: … Permission denied`         | Jupyter-server user cannot create files in `/run`               | run the server as a user with write access to `/run`, or `start` the daemon first so `module-pipe-source` creates the FIFO |
| Capture is pure silence (Max ~0.0004)                                                  | browser mic toggle is off, or not streaming                     | toggle mic on; confirm a `101 GET …/stream` in the Jupyter log                                                             |
| Extension log loops `cannot open sink /run/pulseaudio.fifo: No such file or directory` | FIFO got unlinked/recreated by churning pulse                   | stop churning; it self-recovers once a stable reader is attached                                                           |
| `pactl` returns no sources after daemon start                                          | inline `--load=module-pipe-source …` was dropped by arg parsing | load it with `pactl load-module …` (step 3)                                                                                |
| Claude reaches a different/absent pulse                                                | a `PULSE_SERVER` in the claude env overrides `client.conf`      | unset it, or point it at `unix:/tmp/pulse-lab/native`                                                                      |

## Key facts

- `install` / `validate` / `start` / `stop` automate and check this guide; `validate` prints the remaining manual settings (`c.VoiceCapture.sink_path`, `AUDIODRIVER=pulseaudio`)
- Claude's `rec` reaches pulse via `/etc/pulse/client.conf` (no `/mnt/wslg/PulseServer` symlink required); the only blocker was the missing `AUDIODRIVER`
- diagnose the recorder with `strace -f -e trace=execve,connect -p <claude-pid>` while running `/voice` - the decisive lines are `execve("/usr/bin/rec", ["rec","--version"])` and its exit code
- the pulse default source must be `voicein`; SoX with `AUDIODRIVER=pulseaudio` records the default source
- everything downstream of the FIFO is container plumbing; the extension's responsibility ends at delivering correct PCM to the FIFO
