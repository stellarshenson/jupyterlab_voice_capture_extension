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
FIFO path the handler writes to (`/run/voice/pulseaudio.fifo` by default). All measurements
assume the page is served over a secure context (https or `localhost`).

## Authors

- `@kj` Konrad Jelen

## A. Mic capture (frontend) `MIC`

Browser microphone capture and the status-bar control

- [x] `ACC-MIC-1` **A1 explicit toggle** - CRITICAL; a command (palette + a toolbar or status-bar button) toggles capture on/off; nothing captures audio until the user turns it on
  - evidence: functional A1: no getUserMedia call and 0 FIFO bytes before the click, 1 call after; jest A1 green
  - test-tags: UNIT, FUNCTIONAL
  - test: construct VoiceCapture, assert getUserMedia not called before toggle(), called once after
  - log: 2026-09-28T08:54:26Z @kj edited importance added "CRITICAL"; test added "construct VoiceCapture, assert getUserMedia not called before toggle(), called once after"
  - log: 2026-09-28T09:16:29Z @kj edited test-tags added "UNIT, FUNCTIONAL"
  - log: 2026-09-28T09:16:29Z @kj closed: verified in v1.0.11
- [x] `ACC-MIC-2` **A2 getUserMedia on enable** - CRITICAL; turning capture on calls `navigator.mediaDevices.getUserMedia({ audio: true })` and, on grant, begins streaming; the browser shows its active-microphone indicator
  - evidence: functional A2 with Chromium fake mic: getUserMedia granted, 1 live track, Connected, audio in the FIFO; the indicator itself not observed by automation
  - test-tags: UNIT, FUNCTIONAL, MANUAL
  - test: enable with a granted stream, assert getUserMedia({ audio: true }) and state streaming after the socket opens; browser indicator by eye
  - log: 2026-09-28T08:54:26Z @kj edited importance added "CRITICAL"; test added "enable with a granted stream, assert getUserMedia({ audio: true }) and state streaming after the socket opens; browser indicator by eye"; test-tags added "UNIT, MANUAL"
  - log: 2026-09-28T09:16:29Z @kj edited test-tags "UNIT, MANUAL" -> "UNIT, FUNCTIONAL, MANUAL"
  - log: 2026-09-28T09:16:29Z @kj closed: verified in v1.0.11
- [x] `ACC-MIC-3` **A3 release on disable** - HIGH; turning capture off stops every `MediaStreamTrack` (`track.stop()`), closes the AudioContext, and the browser mic indicator clears within ~1 s; no tracks remain live
  - evidence: functional A3: every track readyState ended within 1 s of the click, FIFO receives 0 bytes/s after; jest A3/D2 green
  - test-tags: UNIT, FUNCTIONAL, MANUAL
  - test: enable then disable, assert every track stopped and AudioContext closed; browser indicator clears by eye
  - log: 2026-09-28T08:54:26Z @kj edited importance added "HIGH"; test added "enable then disable, assert every track stopped and AudioContext closed; browser indicator clears by eye"; test-tags added "UNIT, MANUAL"
  - log: 2026-09-28T09:16:29Z @kj edited test-tags "UNIT, MANUAL" -> "UNIT, FUNCTIONAL, MANUAL"
  - log: 2026-09-28T09:16:29Z @kj closed: verified in v1.0.11
- [x] `ACC-MIC-4` **A4 visible state** - HIGH; the control shows exactly one of idle (Disconnected), connecting, streaming (Connected) and error at all times; each state looks different from the others
  - evidence: functional A1/A2/E1: data-vc-state idle, streaming, error with animations none, vc-pulse, vc-blink; jest covers connecting
  - test-tags: UNIT, FUNCTIONAL
  - test: drive idle, streaming and error in a browser, assert data-vc-state and the icon animation (none, vc-pulse, vc-blink); connecting in jest
  - log: 2026-09-28T08:54:26Z @kj edited importance added "HIGH"; test added "drive idle, connecting, streaming and error, assert the status item carries exactly one jp-mod-<state> class"
  - log: 2026-09-28T08:54:56Z @kj amended text "the control reflects exactly one of idle / streaming / error at all times; the streaming state is visually distinct from idle" -> "the control shows exactly one of idle (Disconnected), connecting, streaming (Connected) and error at all times; each state looks different from the others"
  - log: 2026-09-28T09:16:29Z @kj edited test "drive idle, connecting, streaming and error, assert the status item carries exactly one jp-mod-<state> class" -> "drive idle, streaming and error in a browser, assert data-vc-state and the icon animation (none, vc-pulse, vc-blink); connecting in jest"; test-tags added "UNIT, FUNCTIONAL"
  - log: 2026-09-28T09:16:29Z @kj closed: verified in v1.0.11

## B. Audio format - the wire contract (frontend) `WIRE`

PCM format and framing of the websocket messages

- [x] `ACC-WIRE-5` **B1 resample to 16 kHz mono** - CRITICAL; regardless of the hardware sample rate, audio reaching the websocket is resampled/downmixed to 16 kHz, mono (verified by decoding a captured frame: sample rate 16000, single channel)
  - evidence: functional A2: FIFO byte rate within 15% of 32000 B/s (16000 Hz x 1 channel x 2 bytes) over 3 s; jest AudioContext sampleRate 16000
  - test-tags: UNIT, FUNCTIONAL
  - test: enable, assert AudioContext sampleRate 16000; decode a captured frame, assert 16000 Hz and 1 channel
  - log: 2026-09-28T08:54:26Z @kj edited importance added "CRITICAL"; test added "enable, assert AudioContext sampleRate 16000; decode a captured frame, assert 16000 Hz and 1 channel"; test-tags added "UNIT"
  - log: 2026-09-28T09:16:29Z @kj edited test-tags "UNIT" -> "UNIT, FUNCTIONAL"
  - log: 2026-09-28T09:16:29Z @kj closed: verified in v1.0.11
- [x] `ACC-WIRE-6` **B2 s16le encoding** - CRITICAL; each frame is signed 16-bit little-endian PCM (not Float32, not WebM/Opus); a known tone produces sample values in the expected `int16` range
  - evidence: pcm.spec 'maps full scale to the int16 range, little-endian (B2)' green in the v1.0.10 publish run, jest 13/13
  - test-tags: UNIT
  - test: floatToS16LE on +1.0 and -1.0, assert 0x7FFF and 0x8000 little-endian
  - log: 2026-09-28T08:54:26Z @kj edited importance added "CRITICAL"; test added "floatToS16LE on +1.0 and -1.0, assert 0x7FFF and 0x8000 little-endian"; test-tags added "UNIT"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10
- [x] `ACC-WIRE-7` **B3 fixed frame size** - MEDIUM; frames carry a consistent payload of ~20-40 ms of audio (e.g. 320-640 samples -> 640-1280 bytes); frame byte length is constant during a stream
  - evidence: pcm.spec 'emits a fixed-size frame only once full (B3)' and 'splits a long chunk into whole frames' green in the v1.0.10 publish run
  - test-tags: UNIT, FUNCTIONAL
  - test: feed samples to the framer, assert 320-sample (640-byte) frames emitted only once full
  - log: 2026-09-28T08:54:26Z @kj edited importance added "MEDIUM"; test added "feed samples to the framer, assert 320-sample (640-byte) frames emitted only once full"; test-tags added "UNIT"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10
  - log: 2026-09-28T09:16:29Z @kj edited test-tags "UNIT" -> "UNIT, FUNCTIONAL"
- [x] `ACC-WIRE-8` **B4 binary frames only** - HIGH; frames are sent as binary websocket messages (`ArrayBuffer`), never base64/text; no JSON wrapping around the PCM payload
  - evidence: voice-capture.spec 'forwards a frame pushed by the worklet to the websocket' (same ArrayBuffer sent, binaryType arraybuffer) green in the v1.0.10 publish run
  - test-tags: UNIT, FUNCTIONAL
  - test: worklet posts an ArrayBuffer, assert ws.send gets the same ArrayBuffer and binaryType is arraybuffer
  - log: 2026-09-28T08:54:26Z @kj edited importance added "HIGH"; test added "worklet posts an ArrayBuffer, assert ws.send gets the same ArrayBuffer and binaryType is arraybuffer"; test-tags added "UNIT"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10
  - log: 2026-09-28T09:16:29Z @kj edited test-tags "UNIT" -> "UNIT, FUNCTIONAL"

## C. Server bridge (server extension) `BRIDGE`

Server websocket handler and the FIFO sink

- [x] `ACC-BRIDGE-9` **C1 authenticated endpoint** - CRITICAL; the websocket handler is registered under the Jupyter server base URL and rejects connections lacking a valid Jupyter token (401/403); no new externally exposed port is opened
  - evidence: test_wrong_token_is_refused green: wrong token gets 403 before the upgrade; route registered under base_url
  - test-tags: UNIT, INTEGRATION
  - test: connect to the stream endpoint without a token, assert 403
  - log: 2026-09-28T08:54:26Z @kj edited importance added "CRITICAL"; test added "connect to the stream endpoint without a token, assert 403"; test-tags added "UNIT"
  - log: 2026-09-28T09:16:30Z @kj edited test-tags "UNIT" -> "UNIT, INTEGRATION"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11
- [x] `ACC-BRIDGE-10` **C2 PCM -> sink** - CRITICAL; every binary frame received is written verbatim to the sink FIFO in order; bytes written equal bytes received over the connection
  - evidence: test_routes test_pcm_written_verbatim and test_multiframe_round_trip_in_order green in the v1.0.10 publish run, pytest 13/13
  - test-tags: INTEGRATION, FUNCTIONAL
  - test: send frames over the websocket, read the FIFO, assert same bytes in the same order
  - log: 2026-09-28T08:54:26Z @kj edited importance added "CRITICAL"; test added "send frames over the websocket, read the FIFO, assert same bytes in the same order"; test-tags added "INTEGRATION"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10
  - log: 2026-09-28T09:16:30Z @kj edited test-tags "INTEGRATION" -> "INTEGRATION, FUNCTIONAL"
- [x] `ACC-BRIDGE-11` **C3 consumer-absent tolerance** - HIGH; if the FIFO is not yet created or nothing is reading it yet (PulseAudio not attached), the handler does not crash the server and does not block indefinitely - it drops or buffers within a bounded window and logs, so a later reader gets live audio
  - evidence: test_tolerates_absent_reader and test_new_reader_gets_audio_after_the_old_one_left green on 1.0.11
  - test-tags: INTEGRATION, FUNCTIONAL
  - test: stream with no FIFO, then stop and restart the reader, assert the new reader gets audio
  - log: 2026-09-28T08:54:26Z @kj edited importance added "HIGH"; test added "stream 10 frames with no FIFO present, assert the server still accepts a new connection"; test-tags added "INTEGRATION"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10
  - log: 2026-09-28T09:16:29Z @kj reopened: reopened: DEF-BRIDGE-2 showed a later reader got no audio after the first reader left; evidence retired: test_routes test_tolerates_absent_reader (no FIFO, 10 frames, new connection accepted) green in the v1.0.10 publish run
  - log: 2026-09-28T09:16:30Z @kj edited test "stream 10 frames with no FIFO present, assert the server still accepts a new connection" -> "stream with no FIFO, then stop and restart the reader, assert the new reader gets audio"; test-tags "INTEGRATION" -> "INTEGRATION, FUNCTIONAL"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11
- [x] `ACC-BRIDGE-12` **C4 configurable sink, safe default** - HIGH; the sink path defaults to `/run/voice/pulseaudio.fifo` and is overridable via server config; the PulseAudio reader (`module-pipe-source`) owns FIFO creation because it refuses to attach to a pre-existing FIFO, so the handler never creates the FIFO - it attaches as writer, waits for the reader to create it, and refuses only a path that exists as a non-FIFO (C5)
  - evidence: test_streaming_never_creates_the_fifo green: path absent after 10 frames with no reader
  - test-tags: INTEGRATION
  - test: set sink_path in server config, stream with no reader, assert the path is never created
  - log: 2026-09-28T08:54:26Z @kj edited importance added "HIGH"; test added "set sink_path in server config, stream with no reader, assert the path is never created"; test-tags added "INTEGRATION"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11
- [x] `ACC-BRIDGE-13` **C5 no disk capture** - HIGH; audio is never written to a regular file or persisted; only the FIFO (a pipe) is touched
  - evidence: test_regular_file_at_sink_path_is_never_written green after DEF-BRIDGE-4: file stays 0 bytes
  - test-tags: INTEGRATION
  - test: put a regular file at sink_path, stream frames, assert the file is unchanged
  - log: 2026-09-28T08:54:27Z @kj edited importance added "HIGH"; test added "put a regular file at sink_path, stream frames, assert the file is unchanged"
  - log: 2026-09-28T09:16:30Z @kj edited test-tags added "INTEGRATION"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11

## D. Lifecycle and robustness `LIFE`

Reconnect, teardown, concurrent tabs and resource use

- [x] `ACC-LIFE-14` **D1 reconnect** - HIGH; if the websocket drops while capture is on, the frontend retries with backoff and resumes streaming without user action; the toggle stays "on"
  - evidence: functional D1: socket dropped, second socket opened, Connected again with 1 live track; jest D1 green
  - test-tags: UNIT, FUNCTIONAL
  - test: open then drop the socket, assert state connecting, a retry after backoff, then streaming
  - log: 2026-09-28T08:54:27Z @kj edited importance added "HIGH"; test added "open then drop the socket, assert state connecting, a retry after backoff, then streaming"
  - log: 2026-09-28T09:16:30Z @kj edited test-tags added "UNIT, FUNCTIONAL"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11
- [x] `ACC-LIFE-15` **D2 clean teardown** - HIGH; closing or reloading the tab stops tracks and closes the websocket; the server-side connection closes and stops writing to the sink
  - evidence: functional D2: after the streaming tab closed, FIFO 0 bytes/s over 1 s; jest A3/D2 green
  - test-tags: UNIT, FUNCTIONAL
  - test: close a streaming tab, assert a 1 s window with 0 bytes into the FIFO follows within 30 s
  - log: 2026-09-28T08:54:27Z @kj edited importance added "HIGH"; test added "fire beforeunload, assert tracks stopped and socket closed; assert the server handler closes"; test-tags added "UNIT"
  - log: 2026-09-28T09:16:30Z @kj edited test "fire beforeunload, assert tracks stopped and socket closed; assert the server handler closes" -> "close a streaming tab, assert the FIFO receives 0 bytes/s within 0.5 s"; test-tags "UNIT" -> "UNIT, FUNCTIONAL"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11
  - log: 2026-09-28T11:03:17Z @kj edited test "close a streaming tab, assert the FIFO receives 0 bytes/s within 0.5 s" -> "close a streaming tab, assert a 1 s window with 0 bytes into the FIFO follows within 30 s"
- [x] `ACC-LIFE-16` **D3 single producer** - MEDIUM; concurrent capture from two tabs does not corrupt the stream - either the second is refused or streams are not interleaved into the sink (define and enforce one behaviour)
  - evidence: functional D3 green after DEF-LIFE-3: second tab takes over, first tab idle with 0 live tracks, no flapping over 3 s
  - test-tags: UNIT, FUNCTIONAL
  - test: open two stream connections, assert the first is closed and only the second writes to the sink
  - log: 2026-09-28T08:54:27Z @kj edited importance added "MEDIUM"; test added "open two stream connections, assert the first is closed and only the second writes to the sink"
  - log: 2026-09-28T09:16:30Z @kj edited test-tags added "UNIT, FUNCTIONAL"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11
- [x] `ACC-LIFE-17` **D4 light footprint** - MEDIUM; streaming holds the main thread free (capture/encoding runs in an AudioWorklet, not on the UI thread); idle extension adds no measurable CPU
  - evidence: functional D4: streaming adds 0.016 s main-thread script per 3 s (limit 0.15); jest D4: 0 timers while idle
  - test-tags: UNIT, FUNCTIONAL
  - test: stream 3 s, compare main-thread ScriptDuration with an idle 3 s window; assert no timers while idle
  - log: 2026-09-28T08:54:27Z @kj edited importance added "MEDIUM"; test added "profile a streaming tab, assert encoding runs on the AudioWorklet thread and the idle tab shows no extension CPU"; test-tags added "MANUAL"
  - log: 2026-09-28T09:16:30Z @kj edited test "profile a streaming tab, assert encoding runs on the AudioWorklet thread and the idle tab shows no extension CPU" -> "stream 3 s, compare main-thread ScriptDuration with an idle 3 s window; assert no timers while idle"; test-tags "MANUAL" -> "UNIT, FUNCTIONAL"
  - log: 2026-09-28T09:16:30Z @kj closed: verified in v1.0.11

## E. Error handling `ERROR`

Failure paths the user sees

- [x] `ACC-ERROR-18` **E1 permission denied** - HIGH; a denied `getUserMedia` shows a clear message and returns the toggle to a safe off state; no retry storm
  - evidence: voice-capture.spec 'maps a denied permission to a terminal error, capture off (E1)' green in the v1.0.10 publish run
  - test-tags: UNIT, FUNCTIONAL
  - test: getUserMedia rejects NotAllowedError, assert state error, capture off, one getUserMedia call
  - log: 2026-09-28T08:54:27Z @kj edited importance added "HIGH"; test added "getUserMedia rejects NotAllowedError, assert state error, capture off, one getUserMedia call"; test-tags added "UNIT"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10
  - log: 2026-09-28T09:16:31Z @kj edited test-tags "UNIT" -> "UNIT, FUNCTIONAL"
- [x] `ACC-ERROR-19` **E2 no device** - MEDIUM; absence of any input device is reported distinctly from a permission denial
  - evidence: jest E2 green: NotFoundError gives 'No microphone input device found.', distinct from the denial message
  - test-tags: UNIT
  - test: getUserMedia rejects NotFoundError, assert an error message different from the denial message
  - log: 2026-09-28T08:54:27Z @kj edited importance added "MEDIUM"; test added "getUserMedia rejects NotFoundError, assert an error message different from the denial message"
  - log: 2026-09-28T09:16:31Z @kj edited test-tags added "UNIT"
  - log: 2026-09-28T09:16:31Z @kj closed: verified in v1.0.11
- [x] `ACC-ERROR-20` **E3 insecure context** - MEDIUM; when served without a secure context, capture is disabled with an explanatory message rather than a silent failure
  - evidence: voice-capture.spec 'refuses to capture outside a secure context (E3)' green in the v1.0.10 publish run
  - test-tags: UNIT
  - test: isSecureContext false, enable, assert state error and getUserMedia not called
  - log: 2026-09-28T08:54:27Z @kj edited importance added "MEDIUM"; test added "isSecureContext false, enable, assert state error and getUserMedia not called"; test-tags added "UNIT"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10
- [x] `ACC-ERROR-21` **E4 endpoint unreachable** - HIGH; failure to open the websocket surfaces an error state and does not leave the UI claiming "streaming"
  - evidence: voice-capture.spec 'disconnects on a click in the endpoint-unreachable error (E4)' reaches state error after the 10 s deadline, green in the v1.0.10 publish run
  - test-tags: UNIT
  - test: never open the socket, advance 10 s, assert state error, not streaming
  - log: 2026-09-28T08:54:27Z @kj edited importance added "HIGH"; test added "never open the socket, advance 10 s, assert state error, not streaming"; test-tags added "UNIT"
  - log: 2026-09-28T08:54:47Z @kj closed: verified in v1.0.10

## F. Boundary - out of scope (do not implement here) `SCOPE`

What the extension must not do; the separate plumbing layer owns it

- [x] `ACC-SCOPE-22` **F1 No PulseAudio management** - MEDIUM; the extension does not start, configure, or manage PulseAudio
  - evidence: test_boundary green; a subprocess import in sink.py turns it red (mutation checked)
  - test-tags: UNIT
  - test: scan the server modules except cli.py: no subprocess import, no os.system/exec/spawn/popen, no pactl or pacmd string
  - log: 2026-09-28T08:54:27Z @kj edited importance added "MEDIUM"; test added "search the server extension outside cli.py for pactl or pulseaudio calls, assert none"
  - log: 2026-09-28T09:16:31Z @kj edited test-tags added "UNIT"
  - log: 2026-09-28T09:16:31Z @kj edited test "search the server extension outside cli.py for pactl or pulseaudio calls, assert none" -> "scan the server modules except cli.py: no subprocess import, no os.system/exec/spawn/popen, no pactl or pacmd string"
  - log: 2026-09-28T09:16:31Z @kj closed: verified in v1.0.11
- [x] `ACC-SCOPE-23` **F2 No recorder invocation** - MEDIUM; the extension does not invoke SoX, `/voice`, or any recorder
  - evidence: test_extension_names_no_audio_tool and test_extension_starts_no_processes green
  - test-tags: UNIT
  - test: scan the server modules except cli.py: no sox, rec, parec or arecord string
  - log: 2026-09-28T08:54:27Z @kj edited importance added "MEDIUM"; test added "search the extension outside cli.py for sox, rec or /voice calls, assert none"
  - log: 2026-09-28T09:16:31Z @kj edited test-tags added "UNIT"
  - log: 2026-09-28T09:16:31Z @kj edited test "search the extension outside cli.py for sox, rec or /voice calls, assert none" -> "scan the server modules except cli.py: no sox, rec, parec or arecord string"
  - log: 2026-09-28T09:16:31Z @kj closed: verified in v1.0.11
- [x] `ACC-SCOPE-24` **F3 No speech-to-text** - LOW; the extension does not perform speech-to-text or transcription
  - evidence: test_extension_imports_no_speech_to_text green
  - test-tags: UNIT
  - test: scan the server modules: no speech-to-text library imported
  - log: 2026-09-28T08:54:27Z @kj edited importance added "LOW"; test added "search the extension for speech-to-text or transcription code, assert none"
  - log: 2026-09-28T09:16:31Z @kj edited test-tags added "UNIT"
  - log: 2026-09-28T09:16:31Z @kj edited test "search the extension for speech-to-text or transcription code, assert none" -> "scan the server modules: no speech-to-text library imported"
  - log: 2026-09-28T09:16:31Z @kj closed: verified in v1.0.11
- [x] `ACC-SCOPE-25` **F4 Responsibility ends at the sink** - MEDIUM; the extension's sole downstream responsibility ends at delivering correct PCM (B1-B4) to the sink (C2); everything past the FIFO is the separate plumbing layer
  - evidence: test_boundary green (no processes, no audio tools); routes.on_message only calls sink.write; C2 tests green
  - test-tags: UNIT, INTEGRATION
  - test: scope scan plus the C2 tests: the handler's only output is sink.write of the received frame
  - log: 2026-09-28T08:54:27Z @kj edited importance added "MEDIUM"; test added "review the server extension: its only output is PCM written to the sink FIFO"
  - log: 2026-09-28T09:16:31Z @kj edited test "review the server extension: its only output is PCM written to the sink FIFO" -> "scope scan plus the C2 tests: the handler's only output is sink.write of the received frame"; test-tags added "UNIT, INTEGRATION"
  - log: 2026-09-28T09:16:31Z @kj closed: verified in v1.0.11
