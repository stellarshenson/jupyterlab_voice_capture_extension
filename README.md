# jupyterlab_voice_capture_extension

[![Github Actions Status](/workflows/Build/badge.svg)](/actions/workflows/build.yml)

JupyterLab extension that captures microphone audio in the browser and streams it to a server-side bridge, exposing it as a virtual audio source so terminal applications running in the container (such as Claude Code voice mode) can record from the user's microphone

This extension is composed of a Python package named `jupyterlab_voice_capture_extension`
for the server extension and a NPM package named `jupyterlab_voice_capture_extension`
for the frontend extension.

## Requirements

- JupyterLab >= 4.0.0

## Install

To install the extension, execute:

```bash
pip install jupyterlab_voice_capture_extension
```

## Uninstall

To remove the extension, execute:

```bash
pip uninstall jupyterlab_voice_capture_extension
```

## Troubleshoot

If you are seeing the frontend extension, but it is not working, check
that the server extension is enabled:

```bash
jupyter server extension list
```

If the server extension is installed and enabled, but you are not seeing
the frontend extension, check the frontend extension is installed:

```bash
jupyter labextension list
```

## Contributing

If you would like to contribute to this extension, please refer to the [Contributing Guide](CONTRIBUTING.md).
