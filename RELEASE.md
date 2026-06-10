# Release v1.0.8 - first release

The inaugural release of `jupyterlab_voice_capture_extension`, a JupyterLab 4
`frontend-and-server` extension that routes a browser microphone into a sealed
JupyterLab container. The browser captures audio, ships it over an authenticated
websocket to a Jupyter server handler, and the handler writes raw PCM to a FIFO so
terminal applications in the container - such as Claude Code voice mode - can record
from the user's microphone where no capture device otherwise exists.

This release is feature-complete against the acceptance criteria in
`docs/acc-crit-voice-capture.md` and verified end-to-end, including the full
FIFO → PulseAudio → SoX recording round-trip.

## What it does

The extension is the browser + bridge half of a larger voice chain. It captures the
microphone in the page, resamples to 16 kHz mono signed-16-bit PCM, and streams 20 ms
frames over a websocket that lives under the Jupyter base URL and inherits Jupyter
token auth - no new port is opened. The server handler forwards every frame, in order,
to a FIFO sink. A separate operator CLI provisions the out-of-scope PulseAudio + SoX
plumbing that turns that FIFO into the system default audio source.

## Capture and UI

- Status-bar microphone toggle plus a **Toggle Voice Capture** command-palette entry
- `getUserMedia` capture with an AudioWorklet that downmixes to mono and encodes s16le off the UI thread
- Four states with distinct status-bar styling - Disconnected, Connecting, Connected, Error - the icon glows green while streaming
- Reconnect with capped exponential backoff; the toggle stays on across a dropped connection and recovers automatically
- Last-writer-wins concurrency - opening capture in a second tab takes over and stops the first
- **Auto-connect on startup** setting (`autoConnect`, default off) starts capture as JupyterLab loads
- Settings menu shows the microphone icon

## Transport and server bridge

- 20 ms PCM frames (640 bytes) sent as binary websocket messages to `…/jupyterlab-voice-capture-extension/stream`
- Authenticated websocket handler under `base_url` - inherits Jupyter token auth, rejects anonymous connections
- `FifoSink` runs a background writer thread with a bounded queue, tolerating an absent reader without crashing or blocking the server IOLoop
- The PulseAudio reader (`module-pipe-source`) owns FIFO creation; the server attaches as writer and waits for the pipe to appear

## Operator CLI

A separate console-script tool, `jupyterlab_voice_capture`, provisions and verifies the
container plumbing. The extension itself never manages PulseAudio or SoX (acceptance
group F); the CLI is the operator's hand tool.

- `install` - apt packages, the lab-owned `/run/voice` runtime dir, `/etc/pulse/client.conf`, and the `c.VoiceCapture.sink_path` line; does not start the daemon
- `start` / `stop` - manage the userspace PulseAudio daemon and the `voicein` pipe-source
- `validate` - checks every component and prints how to fix what is missing; `--json` emits a machine-readable report; the source reads connected only when its FIFO is real
- Conservative status colour (green OK, orange warning, red missing) on a capable terminal; honours `NO_COLOR` and `--json`

## Wire contract

- PCM - signed 16-bit little-endian, 16 kHz, mono
- Frame - one binary websocket message of 20 ms (640 bytes)
- Sink - FIFO at `/run/voice/pulseaudio.fifo` by default, overridable via `c.VoiceCapture.sink_path` and the CLI `--sink-path`
- Endpoint - `…/jupyterlab-voice-capture-extension/stream`, Jupyter token auth

## Requirements

- JupyterLab >= 4.0.0 and `jupyter_server` 2.x
- A secure context (https or `localhost`) - browsers only expose the microphone over a secure origin
- For the full voice chain into a terminal app: a Debian/Ubuntu base with PulseAudio + SoX (provisioned by the CLI)

## Install

```bash
pip install jupyterlab-voice-capture-extension
```

See `README.md` for usage and `docs/jupyterlab-enable-claude-voice.md` for the full
container setup, the operator CLI, and troubleshooting.

## Out of scope

The extension does not manage PulseAudio, invoke SoX or any recorder, or perform
speech-to-text. Its responsibility ends at delivering correct PCM to the FIFO; the
PulseAudio + SoX plumbing is handled by the separate operator CLI.
