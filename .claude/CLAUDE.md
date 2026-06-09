<!-- @import /home/lab/workspace/.claude/CLAUDE.md -->

# Project-Specific Configuration

This file imports workspace-level configuration from `/home/lab/workspace/.claude/CLAUDE.md`.
All workspace rules apply. Project-specific rules below strengthen or extend them.

The workspace `/home/lab/workspace/.claude/` directory contains additional instruction files
(MERMAID.md, NOTEBOOK.md, DATASCIENCE.md, GIT.md, and others) referenced by CLAUDE.md.
Consult workspace CLAUDE.md and the .claude directory to discover all applicable standards.

## Mandatory Bans (Reinforced)

The following workspace rules are STRICTLY ENFORCED for this project:

- **No automatic git tags** - only create tags when user explicitly requests
- **No automatic version changes** - only modify version in package.json/pyproject.toml/etc. when user explicitly requests
- **No automatic publishing** - never run `make publish`, `npm publish`, `twine upload`, or similar without explicit user request
- **No manual package installs if Makefile exists** - use `make install` or equivalent Makefile targets, not direct `pip install`/`uv install`/`npm install`/`jlpm install`
- **No automatic git commits or pushes** - only when user explicitly requests

## Project Context

JupyterLab `frontend-and-server` extension that captures microphone audio in the browser and
streams it to a server-side bridge, exposing it as a virtual audio source so terminal
applications running in the container (such as Claude Code voice mode) can record from the
user's microphone.

**Architecture**: this extension is the browser + bridge half of a larger chain. The browser
captures mic audio, ships it over an authenticated websocket to a Jupyter server-extension
handler, and the handler writes raw PCM to a FIFO sink. A separate, out-of-scope plumbing
layer (PulseAudio `module-pipe-source` + SoX) turns that FIFO into the system default audio
source. The contract between the two halves is `docs/acc-crit-voice-capture.md`.

**Technology Stack**:
- TypeScript frontend against `@jupyterlab/application`, `@jupyterlab/services`, `@jupyterlab/coreutils` (JupyterLab >= 4.0.0)
- Python server extension on `jupyter_server>=2.4.0,<3`
- Build: `hatchling` + `hatch-nodejs-version` + `jupyter-builder`; npm via `jlpm`
- Tests: Jest (frontend), pytest + pytest-jupyter (server), Playwright (`ui-tests/`)
- CI/CD: `jupyter-releaser` (see `RELEASE.md`)

**Wire contract** (from `docs/acc-crit-voice-capture.md`): PCM = signed 16-bit little-endian,
16 kHz, mono; frame = one binary websocket message of PCM; default sink `/tmp/voice.fifo`.

**Conventions**:
- Generated from the `jupyterlab/extension-template` copier template (v4.6.0); `.copier-answers.yml` is machine-managed, NEVER edit manually
- Python package and npm package share the name `jupyterlab_voice_capture_extension`
- Build/install/test go through the `Makefile` targets, not raw `jlpm`/`pip` commands

## Project Standards (Reinforced)

- **Follow the `jupyterlab-extension` skill** for testing strategy, CI/CD, jupyter-releaser, TypeScript compatibility, and local development patterns
- Use `Makefile` targets (`make install`, `make build`, `make test`) for all local development
- Release operations only on explicit user request, via `jupyter-releaser` per `RELEASE.md`

## Journal Rules (Project-Specific)

- **APPEND ONLY**: New journal entries MUST be appended at the end of the file, never inserted between existing entries
- Entries maintain strict chronological order by position - the last entry in the file is always the most recent work
- Never reorder, move, or insert entries out of sequence
- The Stellars **journal plugin** is the canonical tool for this file: create via `/journal:create`, append via `/journal:update`, archive via `/journal:archive`. The `journal:journal` skill auto-triggers on any mention of "journal" and runs `journal-tools check` after every write
- Direct edits to `JOURNAL.md` are a last resort - prefer the plugin so modus secundis format, continuous numbering and append-only order are enforced automatically

## Strengthened Rules

- **No slop**: this is a fresh template scaffold - implement exactly what is asked against the acceptance criteria in `docs/acc-crit-voice-capture.md`; do not add features, fallbacks, or scaffolding the user did not request
- **Project boundary**: stay within this extension; the PulseAudio/SoX plumbing layer is out of scope
