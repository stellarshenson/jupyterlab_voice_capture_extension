# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

## [1.0.4] - 2026-06-09

### Added

- Conservative status colour in operator CLI output - green OK, red missing, yellow warning - shown only on a capable interactive terminal (honours `NO_COLOR`, `TERM=dumb`)
- `validate --json` emits a machine-readable component report (no colour), keeping the 0/1 exit code

### Changed

- Operator CLI `install` is now apt-only; conda support removed because the conda-forge `sox` build ships without the pulseaudio I/O driver and would shadow a pulse-capable system sox
- `install` falls back to printing what to install by other means when apt is absent or fails
- `docs/jupyterlab-enable-claude-voice.md` simplified to the apt-only flow with a "What install does" section

<!-- <END NEW CHANGELOG ENTRY> -->
