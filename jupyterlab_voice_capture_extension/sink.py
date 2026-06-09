"""FIFO sink for raw PCM audio frames.

Writes binary PCM frames received from the browser to a FIFO (named pipe). A separate,
out-of-scope plumbing layer (PulseAudio ``module-pipe-source`` + SoX) reads that FIFO and
turns it into the system default audio source. This module only delivers correct PCM to
the pipe.

Tolerates an absent reader (PulseAudio not yet attached) without crashing or blocking the
Jupyter server: frames are buffered in a bounded queue and the oldest are dropped once the
bound is reached. A dedicated writer thread owns the FIFO file descriptor, so the server's
IOLoop is never blocked on a pipe write.
"""

import errno
import os
import queue
import stat
import threading

# Bound on the in-memory frame buffer. At 16 kHz mono s16le with ~20 ms frames (640 bytes),
# 256 frames is roughly five seconds of audio - enough to bridge a slow reader, small
# enough that a never-attached reader cannot grow memory without limit.
DEFAULT_MAX_QUEUED_FRAMES = 256


class FifoSink:
    """Owns a FIFO and writes PCM frames to it from a background thread."""

    def __init__(self, path, log, max_queued=DEFAULT_MAX_QUEUED_FRAMES):
        self._path = path
        self._log = log
        self._queue: queue.Queue = queue.Queue(maxsize=max_queued)
        self._stop = threading.Event()
        self._thread = None
        self._enabled = False

    @property
    def path(self):
        return self._path

    @property
    def enabled(self):
        return self._enabled

    def start(self):
        """Ensure the FIFO exists and launch the writer thread.

        Returns True when the sink is live, False when the configured path already exists
        as something other than a FIFO (a regular file is never written to).
        """
        try:
            self._ensure_fifo()
        except OSError as exc:
            self._log.error("voice-capture: cannot prepare sink %s: %s", self._path, exc)
            return False
        self._enabled = True
        self._thread = threading.Thread(
            target=self._run, name="voice-capture-fifo-writer", daemon=True
        )
        self._thread.start()
        return True

    def _ensure_fifo(self):
        """Create the FIFO if absent; refuse to touch a non-FIFO path (C5)."""
        if os.path.exists(self._path):
            mode = os.stat(self._path).st_mode
            if not stat.S_ISFIFO(mode):
                raise OSError(
                    errno.EEXIST,
                    f"path exists and is not a FIFO; refusing to write to it",
                    self._path,
                )
            return
        os.mkfifo(self._path, 0o600)
        self._log.info("voice-capture: created FIFO sink at %s", self._path)

    def write(self, data):
        """Enqueue a PCM frame, dropping the oldest frame when the buffer is full (C3)."""
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            try:
                self._queue.get_nowait()  # drop oldest
                self._queue.put_nowait(data)
            except (queue.Empty, queue.Full):
                pass
            self._log.debug("voice-capture: sink buffer full, dropped a frame")

    def close(self):
        """Stop the writer thread and release the FIFO."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._enabled = False

    # -- writer thread ----------------------------------------------------------------

    def _run(self):
        while not self._stop.is_set():
            fd = self._open_fifo()
            if fd is None:
                return  # stopped while waiting for a reader
            try:
                self._drain(fd)
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _open_fifo(self):
        """Open the FIFO write end, polling so a missing reader never blocks forever."""
        while not self._stop.is_set():
            try:
                # O_NONBLOCK write-open raises ENXIO until a reader attaches; poll rather
                # than block so the thread stays responsive to close().
                return os.open(self._path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                if exc.errno == errno.ENXIO:
                    self._stop.wait(0.2)
                    continue
                self._log.warning("voice-capture: cannot open sink %s: %s", self._path, exc)
                self._stop.wait(0.5)
        return None

    def _drain(self, fd):
        while not self._stop.is_set():
            try:
                data = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._write_frame(fd, data)

    def _write_frame(self, fd, data):
        """Write one frame; reopen on a vanished reader, drop the tail when the pipe is full."""
        view = memoryview(data)
        while view and not self._stop.is_set():
            try:
                view = view[os.write(fd, view):]
            except BrokenPipeError:
                self._log.info("voice-capture: sink reader disconnected, awaiting a new one")
                raise  # unwind to _run so the FIFO is reopened
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    self._log.debug("voice-capture: sink full, dropping frame tail")
                    return
                raise
