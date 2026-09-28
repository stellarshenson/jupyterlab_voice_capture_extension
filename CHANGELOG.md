# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

## [1.0.13] - 2026-09-28

### Added

- Galata functional test suite (`ui-tests/tests/voice_capture.spec.ts`): a real JupyterLab and Chromium with a fake microphone, with a FIFO reader standing in for PulseAudio, covering capture on and off, the 16 kHz mono s16le wire format, error handling, reconnect, tab close, tab takeover and main-thread cost
- Acceptance-criteria and defect trackers in `docs/` (`acc-crit-voice-capture.md`, `defects-voice-capture.md`)

### Changed

- `jupyterlab_voice_capture start` loads a `voicedrain` null sink and a loopback from `voicein`, so PulseAudio keeps reading the FIFO while nothing records
- `jupyterlab_voice_capture start` removes a leftover FIFO before loading the pipe-source and exits 1 when the `voicein` source did not load
- The endpoint-unreachable error says that capture keeps retrying with the microphone on and that a click stops it

### Fixed

- A recording could start with old audio: up to 2 s left in the pipe while nothing recorded, and up to 5 s queued in the server while no reader was attached
- A second click while the microphone permission prompt was open left the microphone running after the prompt was granted
- A tab replaced by another tab took the stream back; the server now closes the replaced connection with code 4001 and that tab turns capture off
- The server stopped writing to the FIFO for good after its reader went away once
- A regular file placed at the sink path after startup received the audio

## [1.0.10] - 2026-09-28

### Changed

- A click on the status-bar icon in the Error state (blinking) always disconnects and returns the control to Disconnected; previously the permission, microphone and secure-context errors started capture again on click
- Makefile updated to the shared version 1.43: `make test` also runs pytest, `make publish` runs the tests before the version moves, and `make install` installs missing `node_modules`

## [1.0.8] - 2026-06-09

### Changed

- Maintenance re-release of 1.0.7 with no functional changes (version bump only)

## [1.0.7] - 2026-06-09

### Changed

- Default sink path moved to a lab-owned subfolder `/run/voice/pulseaudio.fifo` (was flat `/run/pulseaudio.fifo`); `install` provisions that dir owned by the Jupyter-server user
- FIFO creation flipped to the reader: `module-pipe-source` creates the FIFO (it refuses a pre-existing one), and the server `FifoSink` now only attaches as writer and waits - it never creates the FIFO
- Operator CLI console script renamed `jupyterlab_voice_capture_extension` → `jupyterlab_voice_capture`
- `validate` marks the `voicein` source connected only when its FIFO exists and is a real FIFO

### Fixed

- Claude Code `/voice` could not enable - the flat `/run` sink was uncreatable by the userspace daemon (runs as a non-root user, `/run` is root-owned) and `module-pipe-source` aborted with "Module initialization failed" on the FIFO the server pre-created at boot

## [1.0.6] - 2026-06-09

### Added

- Settings menu icon - the Voice Capture entry in Settings now shows the microphone icon (`jupyter.lab.setting-icon`)
- `install` now writes the `c.VoiceCapture.sink_path` line into `~/.jupyter/jupyter_server_config.py` when it is absent

### Changed

- `install` no longer starts the PulseAudio daemon - it installs, provisions, and writes config, then advises `start -d`; daemon lifecycle is owned by `start`/`stop`
- Default sink path is now a flat `/run/pulseaudio.fifo` everywhere (CLI default and the extension's `c.VoiceCapture.sink_path` default), replacing `/run/voice/voice.fifo` and `/tmp/voice.fifo`
- Runtime-dir provisioning is guarded so the default `/run` parent is never chowned

## [1.0.4] - 2026-06-09

### Added

- Conservative status colour in operator CLI output - green OK, red missing, yellow warning - shown only on a capable interactive terminal (honours `NO_COLOR`, `TERM=dumb`)
- `validate --json` emits a machine-readable component report (no colour), keeping the 0/1 exit code

### Changed

- Operator CLI `install` is now apt-only; conda support removed because the conda-forge `sox` build ships without the pulseaudio I/O driver and would shadow a pulse-capable system sox
- `install` falls back to printing what to install by other means when apt is absent or fails
- `docs/jupyterlab-enable-claude-voice.md` simplified to the apt-only flow with a "What install does" section

<!-- <END NEW CHANGELOG ENTRY> -->
