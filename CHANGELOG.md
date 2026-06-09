# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

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
