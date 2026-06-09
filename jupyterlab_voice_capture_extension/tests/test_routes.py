import asyncio
import os
import stat

import pytest


@pytest.fixture
def voice_sink_path(tmp_path):
    return str(tmp_path / "pulseaudio.fifo")


@pytest.fixture
def jp_server_config(jp_server_config, voice_sink_path):
    """Extend the base server config with a per-test FIFO sink path."""
    config = dict(jp_server_config)
    config["VoiceCapture"] = {"sink_path": voice_sink_path}
    return config


async def test_fifo_created_and_pcm_written_verbatim(jp_ws_fetch, voice_sink_path):
    # C4: the sink FIFO is created at extension load.
    assert os.path.exists(voice_sink_path)
    assert stat.S_ISFIFO(os.stat(voice_sink_path).st_mode)

    # Attach a reader before streaming so the writer thread can open the pipe.
    rfd = os.open(voice_sink_path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        ws = await jp_ws_fetch(
            "jupyterlab-voice-capture-extension", "stream"
        )
        payload = bytes(range(256)) + bytes(range(256))  # 512 bytes of known PCM
        await ws.write_message(payload, binary=True)

        received = b""
        for _ in range(60):
            await asyncio.sleep(0.05)
            try:
                received += os.read(rfd, 4096)
            except BlockingIOError:
                pass
            if len(received) >= len(payload):
                break
        ws.close()

        # C2: bytes written to the FIFO equal bytes received over the connection.
        assert received == payload
    finally:
        os.close(rfd)


async def test_multiframe_round_trip_in_order(jp_ws_fetch, voice_sink_path):
    # C2: many binary frames pushed from the browser end arrive at the FIFO end byte-for-byte
    # and in order. Each 640-byte frame carries a distinct marker so reordering is detectable.
    rfd = os.open(voice_sink_path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        ws = await jp_ws_fetch("jupyterlab-voice-capture-extension", "stream")
        frames = [bytes([i]) * 640 for i in range(20)]  # 20 frames, 12800 bytes total
        for frame in frames:
            await ws.write_message(frame, binary=True)

        expected = b"".join(frames)
        received = b""
        for _ in range(80):
            await asyncio.sleep(0.05)
            try:
                received += os.read(rfd, 65536)
            except BlockingIOError:
                pass
            if len(received) >= len(expected):
                break
        ws.close()

        assert received == expected  # exact bytes, exact order
    finally:
        os.close(rfd)


async def test_tolerates_absent_reader(jp_ws_fetch):
    # C3: streaming with no FIFO reader attached must not crash the server.
    ws = await jp_ws_fetch("jupyterlab-voice-capture-extension", "stream")
    for _ in range(10):
        await ws.write_message(b"\x00\x01" * 320, binary=True)  # 640-byte frames
    await asyncio.sleep(0.2)
    ws.close()

    # The server is still responsive: a fresh connection succeeds.
    ws2 = await jp_ws_fetch("jupyterlab-voice-capture-extension", "stream")
    ws2.close()


def test_endpoint_requires_authentication():
    # C1: the stream endpoint enforces Jupyter auth. @ws_authenticated stamps
    # __allow_unauthenticated = False on get, which is the flag jupyter_server's own
    # auth layer checks to reject anonymous connections before the websocket upgrade.
    from jupyterlab_voice_capture_extension.routes import (
        VoiceCaptureWebSocketHandler,
    )

    assert (
        getattr(VoiceCaptureWebSocketHandler.get, "__allow_unauthenticated", True)
        is False
    )
