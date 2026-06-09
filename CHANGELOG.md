# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

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
