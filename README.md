# jupyterlab_voice_capture_extension

[![GitHub Actions](https://github.com/stellarshenson/jupyterlab_voice_capture_extension/actions/workflows/build.yml/badge.svg)](https://github.com/stellarshenson/jupyterlab_voice_capture_extension/actions/workflows/build.yml)
[![npm version](https://img.shields.io/npm/v/jupyterlab_voice_capture_extension.svg)](https://www.npmjs.com/package/jupyterlab_voice_capture_extension)
[![PyPI version](https://img.shields.io/pypi/v/jupyterlab-voice-capture-extension.svg)](https://pypi.org/project/jupyterlab-voice-capture-extension/)
[![Total PyPI downloads](https://static.pepy.tech/badge/jupyterlab-voice-capture-extension)](https://pepy.tech/project/jupyterlab-voice-capture-extension)
[![JupyterLab 4](https://img.shields.io/badge/JupyterLab-4-orange.svg)](https://jupyterlab.readthedocs.io/en/stable/)
[![Brought To You By KOLOMOLO](https://img.shields.io/badge/Brought%20To%20You%20By-KOLOMOLO-00ffff?style=flat)](https://kolomolo.com)
[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-blue?style=flat)](https://www.paypal.com/donate/?hosted_button_id=B4KPBJDLLXTSA)

Capture microphone audio in the JupyterLab browser tab and stream it to a server-side FIFO, so terminal applications running inside the container - notably Claude Code voice mode - can record from a microphone the container itself has no access to.

The container has no capture device; the browser does. This extension bridges that gap: the browser captures the mic, ships the audio over an authenticated websocket to a Jupyter server handler, and the handler writes raw PCM to a named pipe. A separate, out-of-scope plumbing layer (PulseAudio `module-pipe-source` + SoX) turns that pipe into the system default audio source.

## How it works

- **Capture** - a microphone toggle in the status bar calls `getUserMedia`; an AudioWorklet resamples to 16 kHz mono and encodes signed 16-bit little-endian PCM off the UI thread
- **Transport** - 20 ms PCM frames (640 bytes) are sent as binary websocket messages to `…/jupyterlab-voice-capture-extension/stream`, which lives under the Jupyter base URL and inherits Jupyter token auth - no new port is opened
- **Sink** - the server handler writes each frame, in order, to a FIFO (default `/tmp/voice.fifo`); it creates the pipe if absent and tolerates a not-yet-attached reader without blocking the server
- **Out of scope** - the extension does not manage PulseAudio, invoke SoX or any recorder, or perform speech-to-text; its responsibility ends at delivering correct PCM to the FIFO

Chain: browser mic → AudioWorklet (16 kHz mono s16le) → websocket → server handler → FIFO → (PulseAudio + SoX, out of scope) → terminal app.

## Requirements

- JupyterLab >= 4.0.0
- A secure context (https or `localhost`) - browsers only expose the microphone over a secure origin

## Install

```bash
pip install jupyterlab-voice-capture-extension
```

## Usage

- Click the microphone icon in the status bar (or run **Toggle Voice Capture** from the command palette) to start capture
- On the first start the browser asks for microphone permission; while streaming the icon pulses red and the browser shows its active-microphone indicator
- Click again to stop - capture tracks are released and the browser indicator clears
- Only one tab streams at a time: starting capture in a second tab takes over and stops the first

## Configuration

The sink FIFO path defaults to `/tmp/voice.fifo` and is overridable via Jupyter server config:

```python
c.VoiceCapture.sink_path = "/run/voice/voice.fifo"
```

## Uninstall

```bash
pip uninstall jupyterlab-voice-capture-extension
```

## Troubleshoot

If you see the frontend extension but it is not working, check that the server extension is enabled:

```bash
jupyter server extension list
```

If the server extension is installed and enabled but you do not see the frontend extension, check the frontend extension is installed:

```bash
jupyter labextension list
```

## Contributing

If you would like to contribute to this extension, please refer to the [Contributing Guide](CONTRIBUTING.md).
