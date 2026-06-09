try:
    from ._version import __version__
except ImportError:
    # Fallback when using the package in dev mode without installing
    # in editable mode with pip. It is highly recommended to install
    # the package from a stable release or in editable mode: https://pip.pypa.io/en/stable/topics/local-project-installs/#editable-installs
    import warnings
    warnings.warn("Importing 'jupyterlab_voice_capture_extension' outside a proper installation.")
    __version__ = "dev"
from traitlets import Unicode
from traitlets.config import Configurable

from .routes import setup_route_handlers
from .sink import FifoSink


class VoiceCapture(Configurable):
    """Configuration for the voice-capture server extension."""

    sink_path = Unicode(
        "/run/voice/pulseaudio.fifo",
        config=True,
        help="Path to the FIFO sink that receives raw PCM audio frames.",
    )


def _jupyter_labextension_paths():
    return [{
        "src": "labextension",
        "dest": "jupyterlab_voice_capture_extension"
    }]


def _jupyter_server_extension_points():
    return [{
        "module": "jupyterlab_voice_capture_extension"
    }]


def _load_jupyter_server_extension(server_app):
    """Registers the API handler to receive HTTP requests from the frontend extension.

    Parameters
    ----------
    server_app: jupyterlab.labapp.LabApp
        JupyterLab application instance
    """
    config = VoiceCapture(config=server_app.config)
    sink = FifoSink(config.sink_path, server_app.log)
    sink.start()
    server_app.web_app.settings["voice_capture_sink"] = sink
    setup_route_handlers(server_app.web_app, sink)
    name = "jupyterlab_voice_capture_extension"
    server_app.log.info(f"Registered {name} server extension (sink={config.sink_path})")
