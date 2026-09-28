# Defects - jupyterlab_voice_capture_extension

Defects found in the voice-capture extension, its operator CLI and its tests. The criteria they break are in `acc-crit-voice-capture.md`.

## Authors

- `@kj` Konrad Jelen

## Test suite `TEST`

Automated tests and the state they leave behind

- [x] `DEF-TEST-1` **Round-trip test leaves tone in the FIFO** - MAJOR; test_round_trip_fifo_to_recorder writes 3 s of tone but rec reads 1 s; the rest stays in /run/voice/pulseaudio.fifo, builds up over runs until the 64 KB pipe is full, then the sox writer blocks and the test fails; the leftover tone plays at the start of the next /voice recording
  - evidence: round-trip test passed 3 runs in a row on 1.0.11 with 0 bytes left in the FIFO after each (FIONREAD); make test 21 pytest green
  - related: ACC-BRIDGE-10 - the round trip this test proves
  - repro: run test_round_trip_fifo_to_recorder repeatedly against the live daemon; FIONREAD on the FIFO grows per pass (9984 bytes after one); at 65536 the test raises TimeoutExpired
  - test-tags: INTEGRATION
  - root-cause: 2026-09-28T08:55:28Z @kj PulseAudio 16.1 module-pipe-source did not read the pipe while voicein was IDLE (observed: sox blocked 38 s, 65536 bytes buffered); sox blocked in write() did not exit on SIGTERM within 5 s
  - log: 2026-09-28T08:55:28Z @kj added
  - log: 2026-09-28T09:16:28Z @kj closed: fixed: test drains the FIFO before and after, stops sox with SIGKILL

## Server bridge `BRIDGE`

Server websocket handler and the FIFO sink

- [x] `DEF-BRIDGE-2` **Sink stops writing after the FIFO reader goes away once** - MAJOR; after the FIFO reader closes once (PulseAudio restart, jupyterlab_voice_capture stop/start), no audio reaches the FIFO again until Jupyter restarts, while the control still shows Connected; `jupyterlab_voice_capture_extension/sink.py`
  - evidence: test_new_reader_gets_audio_after_the_old_one_left green; functional suite 8/8 on 1.0.11, each spec with a new FIFO reader
  - related: ACC-BRIDGE-11 - a later reader must get live audio
  - repro: stream into the FIFO, stop and restart the reader, stream again; the new reader gets 0 bytes and the server log shows BrokenPipeError: [Errno 32] Broken pipe
  - test-tags: INTEGRATION, FUNCTIONAL
  - root-cause: 2026-09-28T09:06:06Z @kj \_write_frame re-raises BrokenPipeError and \_run has try/finally with no except, so the error ends the voice-capture-fifo-writer thread; nothing drains the queue after that
  - log: 2026-09-28T09:06:06Z @kj added
  - log: 2026-09-28T09:16:29Z @kj closed: fixed: \_run catches BrokenPipeError and other OSError and reopens the FIFO
- [x] `DEF-BRIDGE-4` **Audio written into a regular file at the sink path** - MAJOR; a regular file that appears at the sink path after the server started receives the microphone audio, growing without limit; `jupyterlab_voice_capture_extension/sink.py`
  - evidence: test_regular_file_at_sink_path_is_never_written green: file stays 0 bytes (6400 before the fix)
  - related: ACC-BRIDGE-13 - audio never written to a regular file
  - repro: start the server with no FIFO, create a regular file at the sink path, stream; the file grows (6400 bytes after 10 frames)
  - test-tags: INTEGRATION
  - root-cause: 2026-09-28T09:08:33Z @kj \_guard_path runs only in start(); \_open_fifo opens whatever is at the path with O_WRONLY and never checks that it is a FIFO
  - log: 2026-09-28T09:08:33Z @kj added
  - log: 2026-09-28T09:16:29Z @kj closed: fixed: \_open_fifo fstats the opened path and refuses a non-FIFO
- [x] `DEF-BRIDGE-7` **Old speech plays at the start of the next /voice recording** - MAJOR; while capture is on and nothing records, the FIFO fills with up to 64 KB (2 s) of audio that PulseAudio reads first when /voice starts recording, so the recording opens with stale speech; `jupyterlab_voice_capture_extension/cli.py`
  - evidence: isolated PulseAudio 16.1 with the drain: 0 bytes waiting after 250 idle frames, a recorder attached at frame 250 first got frame 251, 0 of 250 frames dropped over ten 500 ms stalls, 0.4% CPU; test_start_keeps_voicein_reading_through_a_drain green
  - repro: turn capture on, speak, wait a minute, start /voice; the first 2 s carry the earlier speech
  - test-tags: UNIT
  - root-cause: 2026-09-28T09:55:14Z @kj module-pipe-source does not read the FIFO while voicein is IDLE; the default 64 KB pipe capacity bounds how much old audio waits in it
  - log: 2026-09-28T09:55:14Z @kj added
  - log: 2026-09-28T10:21:11Z @kj closed: fixed: start sets the FIFO capacity to 8192 bytes (256 ms) with F_SETPIPE_SZ
  - log: 2026-09-28T11:03:17Z @kj attempted: 8192-byte pipe cap with F_SETPIPE_SZ - reverted in review round 2; it dropped 95-100 of 250 frames after a 500 ms stall while recording (isolated PulseAudio 16.1)
  - log: 2026-09-28T11:03:17Z @kj fixed: start loads a voicedrain null sink and a loopback from voicein, so the pipe-source keeps reading while nothing records
  - log: 2026-09-28T11:03:17Z @kj edited evidence "test_start_shrinks_the_fifo_buffer green: a pipe held open read-write accepts at most 8192 bytes after start (65536 before); scratch FIFO measured 7680 bytes accepted" -> "isolated PulseAudio 16.1 with the drain: 0 bytes waiting after 250 idle frames, a recorder attached at frame 250 first got frame 251, 0 of 250 frames dropped over ten 500 ms stalls, 0.4% CPU; test_start_keeps_voicein_reading_through_a_drain green"
- [x] `DEF-BRIDGE-8` **Reader gets audio from before it attached** - MEDIUM; frames that arrive while no reader holds the FIFO stay in the sink queue (up to 256 frames, 5 s) and are written to the next reader however much later it attaches; found by Galata A1 after D4 in a --repeat-each run; `jupyterlab_voice_capture_extension/sink.py`
  - evidence: test_reader_never_gets_audio_from_before_it_attached red before the fix, green after; pytest 22/22 three runs; Galata --repeat-each 2 18/18 incl. A1 after D4
  - repro: stream with no FIFO, create the FIFO 0.6 s later and read: the old frames arrive before the live ones
  - test-tags: INTEGRATION, FUNCTIONAL
  - root-cause: 2026-09-28T11:59:26Z @kj FifoSink.\_open_fifo waits for a reader without touching the queue, so \_drain first writes every frame queued during the wait
  - log: 2026-09-28T11:59:26Z @kj added
  - log: 2026-09-28T12:05:43Z @kj closed: fixed: \_open_fifo discards the queue on every poll while no reader is attached

## Lifecycle `LIFE`

Reconnect, teardown and concurrent tabs

- [x] `DEF-LIFE-3` **First tab takes the stream back after a second tab takes over** - MAJOR; with capture on in two tabs, the first tab stays or returns to Connected after the second takes over, so both tabs keep taking the stream from each other and their audio alternates in the FIFO; `src/voice-capture.ts`
  - evidence: functional D3 green on 1.0.11: first tab idle, second tab 1 socket over 3 s; jest 'stops without reconnecting when another tab takes over (D3)' green
  - related: ACC-LIFE-16 - single producer
  - repro: turn capture on in tab 1, then in tab 2; 5 s later tab 1 still shows Connected
  - test-tags: FUNCTIONAL
  - root-cause: 2026-09-28T09:06:07Z @kj the server closes the old producer with code 1000; the frontend onclose does not check the close code, treats it as a dropped connection and reconnects, which takes the stream back
  - log: 2026-09-28T09:06:07Z @kj added
  - log: 2026-09-28T09:16:29Z @kj closed: fixed: server closes a replaced producer with code 4001, the tab disables capture on it
- [x] `DEF-LIFE-5` **A second click during Connecting leaves the microphone running** - MAJOR; clicking again while the permission prompt or audio start is pending shows Disconnected, but when getUserMedia resolves the capture pipeline starts anyway and the stream is never released; `src/voice-capture.ts`
  - evidence: jest 'a second click during the permission prompt releases the late stream' green on 1.0.12, red without the fix; jest 19/19; functional 9/9 twice
  - repro: click the mic, click again before granting the permission prompt, grant it; the mic indicator stays on with the control Disconnected
  - test-tags: UNIT
  - root-cause: 2026-09-28T09:55:14Z @kj disable() cannot cancel a pending getUserMedia or \_startAudioGraph, and enable() does not check after its awaits that it still owns the capture
  - log: 2026-09-28T09:55:14Z @kj added
  - log: 2026-09-28T10:21:11Z @kj closed: fixed: enable() takes an epoch token that disable() advances; a stale call stops its late stream and returns

## Operator CLI `CLI`

jupyterlab_voice_capture install, start, stop and validate

- [x] `DEF-CLI-6` **start fails silently after a container restart** - MAJOR; after a container restart the old FIFO is still at the sink path (/run here is on the overlay root, not tmpfs); start then fails to load voicein because module-pipe-source refuses an existing path, yet exits 0; `jupyterlab_voice_capture_extension/cli.py`
  - evidence: test_start_removes_a_leftover_fifo_before_loading_the_source and test_start_exits_1_when_the_source_did_not_load green, both red without the fix
  - repro: stop the daemon without unloading the source (or restart the container), run jupyterlab_voice_capture start -d; exit 0, pactl shows no voicein
  - test-tags: UNIT
  - root-cause: 2026-09-28T09:55:14Z @kj \_start_pulse_and_source loads module-pipe-source without removing a leftover FIFO, and cmd_start checks only that the daemon runs, not that the source loaded
  - log: 2026-09-28T09:55:14Z @kj added
  - log: 2026-09-28T10:21:11Z @kj closed: fixed: start removes a leftover FIFO before loading module-pipe-source and exits 1 when voicein is not loaded
