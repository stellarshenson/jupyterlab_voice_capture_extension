import asyncio
import os
import stat

import pytest
import tornado.httpclient


@pytest.fixture
def voice_sink_path(tmp_path):
    return str(tmp_path / "pulseaudio.fifo")


@pytest.fixture
def jp_server_config(jp_server_config, voice_sink_path):
    """Extend the base server config with a per-test FIFO sink path."""
    config = dict(jp_server_config)
    config["VoiceCapture"] = {"sink_path": voice_sink_path}
    return config


async def test_pcm_written_verbatim(jp_ws_fetch, voice_sink_path):
    # The PulseAudio reader owns FIFO creation; create it here to play that role, then
    # attach as reader before streaming so the writer thread can open the pipe.
    os.mkfifo(voice_sink_path)
    assert stat.S_ISFIFO(os.stat(voice_sink_path).st_mode)
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
    os.mkfifo(voice_sink_path)  # reader owns FIFO creation
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


async def _read_at_least(rfd, n, attempts=80):
    """Read from a non-blocking FIFO until at least n bytes arrived or the attempts run out."""
    received = b""
    for _ in range(attempts):
        await asyncio.sleep(0.05)
        try:
            received += os.read(rfd, 65536)
        except BlockingIOError:
            pass
        if len(received) >= n:
            break
    return received


async def test_wrong_token_is_refused(jp_ws_fetch):
    # C1 live: a connection without a valid Jupyter token is refused before the upgrade.
    with pytest.raises(tornado.httpclient.HTTPClientError) as refused:
        await jp_ws_fetch(
            "jupyterlab-voice-capture-extension",
            "stream",
            headers={"Authorization": "token not-the-server-token"},
        )
    assert refused.value.code == 403


async def test_streaming_never_creates_the_fifo(jp_ws_fetch, voice_sink_path):
    # C4: the reader owns FIFO creation; streaming with no reader leaves the path absent.
    ws = await jp_ws_fetch("jupyterlab-voice-capture-extension", "stream")
    for _ in range(10):
        await ws.write_message(b"\x00\x01" * 320, binary=True)
    await asyncio.sleep(0.5)
    ws.close()
    assert not os.path.exists(voice_sink_path)


async def test_regular_file_at_sink_path_is_never_written(jp_ws_fetch, voice_sink_path):
    # C5: a regular file that appears at the sink path after startup is never written to.
    with open(voice_sink_path, "wb"):
        pass
    ws = await jp_ws_fetch("jupyterlab-voice-capture-extension", "stream")
    for _ in range(10):
        await ws.write_message(b"\x00\x01" * 320, binary=True)
    await asyncio.sleep(0.5)
    ws.close()
    assert os.path.getsize(voice_sink_path) == 0


async def test_new_reader_gets_audio_after_the_old_one_left(jp_ws_fetch, voice_sink_path):
    # DEF-BRIDGE-2: after the FIFO reader goes away (PulseAudio restart), the next reader
    # gets live audio again - the writer thread must survive the broken pipe.
    os.mkfifo(voice_sink_path)
    frame = b"\x01\x02" * 320
    rfd = os.open(voice_sink_path, os.O_RDONLY | os.O_NONBLOCK)
    ws = await jp_ws_fetch("jupyterlab-voice-capture-extension", "stream")
    await ws.write_message(frame, binary=True)
    assert len(await _read_at_least(rfd, len(frame))) >= len(frame)
    os.close(rfd)  # the reader goes away; the next write hits a broken pipe

    for _ in range(5):
        await ws.write_message(frame, binary=True)
        await asyncio.sleep(0.05)

    rfd = os.open(voice_sink_path, os.O_RDONLY | os.O_NONBLOCK)  # a new reader
    try:
        for _ in range(5):
            await ws.write_message(frame, binary=True)
        assert len(await _read_at_least(rfd, len(frame))) >= len(frame)
    finally:
        ws.close()
        os.close(rfd)


async def test_reader_never_gets_audio_from_before_it_attached(jp_ws_fetch, voice_sink_path):
    # A reader that attaches later gets live audio only, never frames that arrived while no
    # reader existed (PulseAudio stopped, or the FIFO not yet created).
    ws = await jp_ws_fetch("jupyterlab-voice-capture-extension", "stream")
    for _ in range(5):
        await ws.write_message(b"\xaa" * 640, binary=True)
    await asyncio.sleep(0.6)

    os.mkfifo(voice_sink_path)
    rfd = os.open(voice_sink_path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        for _ in range(5):
            await ws.write_message(b"\x01" * 640, binary=True)
        received = await _read_at_least(rfd, 640)
        assert received and b"\xaa" not in received
    finally:
        ws.close()
        os.close(rfd)
