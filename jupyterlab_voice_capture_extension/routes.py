"""Server routes for the voice-capture extension.

Registers a single authenticated websocket endpoint under the Jupyter base URL that
receives binary PCM frames from the browser and forwards them, in order, to the FIFO sink.
No new externally exposed port is opened - the endpoint inherits Jupyter token auth.
"""

from jupyter_server.auth.decorator import ws_authenticated
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.base.websocket import WebSocketMixin
from jupyter_server.utils import url_path_join
from tornado.websocket import WebSocketHandler


class VoiceCaptureWebSocketHandler(WebSocketMixin, WebSocketHandler, JupyterHandler):
    """Receives binary PCM frames and writes them to the FIFO sink.

    Auth is enforced by ``@ws_authenticated`` on ``get`` (C1). Only one producer streams
    at a time: a new connection takes over and closes the previous one (last-writer-wins,
    D3).
    """

    # Class-level reference to the currently streaming handler (single producer).
    _active: "VoiceCaptureWebSocketHandler | None" = None

    def initialize(self, sink=None):
        self._sink = sink

    def set_default_headers(self):
        """Undo JupyterHandler's default headers, which are meaningless for websockets."""

    @ws_authenticated
    async def get(self, *args, **kwargs):
        return await super().get(*args, **kwargs)

    def open(self, *args, **kwargs):
        # Last-writer takeover (D3): close any existing producer before taking over.
        existing = VoiceCaptureWebSocketHandler._active
        if existing is not None and existing is not self:
            try:
                existing.close(1000, "superseded by a new producer")
            except Exception:  # noqa: BLE001 - never let a stale socket block the new one
                pass
        VoiceCaptureWebSocketHandler._active = self
        # super().open() starts the keep-alive ping-pong loop (WebSocketMixin).
        super().open()
        self.log.info("voice-capture: producer connected")

    def on_message(self, message):
        # Only binary PCM frames are expected (B4); ignore any text message.
        if isinstance(message, (bytes, bytearray, memoryview)) and self._sink is not None:
            self._sink.write(bytes(message))

    def on_close(self):
        if VoiceCaptureWebSocketHandler._active is self:
            VoiceCaptureWebSocketHandler._active = None
        self.log.info("voice-capture: producer disconnected")


def setup_route_handlers(web_app, sink):
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]

    stream_route = url_path_join(
        base_url, "jupyterlab-voice-capture-extension", "stream"
    )
    handlers = [(stream_route, VoiceCaptureWebSocketHandler, {"sink": sink})]
    web_app.add_handlers(host_pattern, handlers)
