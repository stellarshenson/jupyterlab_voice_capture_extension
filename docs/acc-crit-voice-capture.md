# Acceptance Criteria - jupyterlab_voice_capture_extension

Project-wide acceptance criteria for the voice-capture extension. Each criterion is
measurable - a frame on the wire, a DOM/state effect, a file written - so a build is
"done" only when checked against a real measurement, not asserted.

This extension is the **browser + bridge half** of a larger chain that lets terminal
applications inside the container (notably Claude Code `/voice`) record the user's
microphone. The container has no capture device; the browser does. The extension captures
mic audio in the browser, ships it over an authenticated websocket to a Jupyter
server-extension handler, and the handler writes raw PCM to an agreed sink (a FIFO). A
separate, **out-of-scope** plumbing layer (PulseAudio `module-pipe-source` + SoX) turns
that FIFO into the system default audio source. This document is the contract between the
two halves.

Conventions: "PCM" means signed 16-bit little-endian, 16 kHz, mono unless stated. "frame"
= one binary websocket message of PCM. The websocket path is served by the extension's own
server endpoint under the Jupyter base URL and inherits Jupyter token auth. "sink" = the
FIFO path the handler writes to (`/tmp/voice.fifo` by default). All measurements assume the
page is served over a secure context (https or `localhost`).

## A. Mic capture (frontend)

- **A1 - explicit toggle**: a command (palette + a toolbar or status-bar button) toggles
  capture on/off; nothing captures audio until the user turns it on
- **A2 - getUserMedia on enable**: turning capture on calls
  `navigator.mediaDevices.getUserMedia({ audio: true })` and, on grant, begins streaming;
  the browser shows its active-microphone indicator
- **A3 - release on disable**: turning capture off stops every `MediaStreamTrack`
  (`track.stop()`), closes the AudioContext, and the browser mic indicator clears within
  ~1 s; no tracks remain live
- **A4 - visible state**: the control reflects exactly one of idle / streaming / error at
  all times; the streaming state is visually distinct from idle

## B. Audio format - the wire contract (frontend)

- **B1 - resample to 16 kHz mono**: regardless of the hardware sample rate, audio reaching
  the websocket is resampled/downmixed to 16 kHz, mono (verified by decoding a captured
  frame: sample rate 16000, single channel)
- **B2 - s16le encoding**: each frame is signed 16-bit little-endian PCM (not Float32, not
  WebM/Opus); a known tone produces sample values in the expected `int16` range
- **B3 - fixed frame size**: frames carry a consistent payload of ~20-40 ms of audio
  (e.g. 320-640 samples → 640-1280 bytes); frame byte length is constant during a stream
- **B4 - binary frames only**: frames are sent as binary websocket messages
  (`ArrayBuffer`), never base64/text; no JSON wrapping around the PCM payload

## C. Server bridge (server extension)

- **C1 - authenticated endpoint**: the websocket handler is registered under the Jupyter
  server base URL and rejects connections lacking a valid Jupyter token (401/403); no new
  externally exposed port is opened
- **C2 - PCM → sink**: every binary frame received is written verbatim to the sink FIFO in
  order; bytes written equal bytes received over the connection
- **C3 - consumer-absent tolerance**: if nothing is reading the FIFO yet (PulseAudio not
  attached), the handler does not crash the server and does not block indefinitely - it
  drops or buffers within a bounded window and logs, so a later reader gets live audio
- **C4 - configurable sink, safe default**: the sink path defaults to `/tmp/voice.fifo`
  and is overridable via server config; the handler creates the FIFO if absent
- **C5 - no disk capture**: audio is never written to a regular file or persisted; only the
  FIFO (a pipe) is touched

## D. Lifecycle and robustness

- **D1 - reconnect**: if the websocket drops while capture is on, the frontend retries with
  backoff and resumes streaming without user action; the toggle stays "on"
- **D2 - clean teardown**: closing or reloading the tab stops tracks and closes the
  websocket; the server-side connection closes and stops writing to the sink
- **D3 - single producer**: concurrent capture from two tabs does not corrupt the stream -
  either the second is refused or streams are not interleaved into the sink (define and
  enforce one behaviour)
- **D4 - light footprint**: streaming holds the main thread free (capture/encoding runs in
  an AudioWorklet, not on the UI thread); idle extension adds no measurable CPU

## E. Error handling

- **E1 - permission denied**: a denied `getUserMedia` shows a clear message and returns the
  toggle to a safe off state; no retry storm
- **E2 - no device**: absence of any input device is reported distinctly from a permission
  denial
- **E3 - insecure context**: when served without a secure context, capture is disabled with
  an explanatory message rather than a silent failure
- **E4 - endpoint unreachable**: failure to open the websocket surfaces an error state and
  does not leave the UI claiming "streaming"

## F. Boundary - out of scope (do not implement here)

- **F1**: the extension does **not** start, configure, or manage PulseAudio
- **F2**: the extension does **not** invoke SoX, `/voice`, or any recorder
- **F3**: the extension does **not** perform speech-to-text or transcription
- **F4**: the extension's sole downstream responsibility ends at delivering correct PCM
  (B1-B4) to the sink (C2); everything past the FIFO is the separate plumbing layer
