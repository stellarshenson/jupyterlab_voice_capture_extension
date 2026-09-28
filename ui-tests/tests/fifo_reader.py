"""Stand-in for PulseAudio's module-pipe-source in the UI tests.

Creates the sink FIFO (the reader owns creation, as in production), reads everything the
server writes, and prints one JSON line every 200 ms: seconds since start, total bytes
read, and the peak absolute s16le sample seen so far. SIGTERM removes the FIFO and exits.
"""

import json
import os
import select
import signal
import stat
import sys
import time

path = sys.argv[1]
if os.path.exists(path) and stat.S_ISFIFO(os.stat(path).st_mode):
    os.unlink(path)  # stale FIFO from an interrupted run
os.mkfifo(path)
fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)


def stop(*_):
    os.close(fd)
    os.unlink(path)
    sys.exit(0)


signal.signal(signal.SIGTERM, stop)

start = time.monotonic()
total, peak, carry, last_report = 0, 0, b"", 0.0
while True:
    ready, _, _ = select.select([fd], [], [], 0.05)
    chunk = b""
    if ready:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            pass
    if chunk:
        total += len(chunk)
        data = carry + chunk
        even = len(data) - len(data) % 2
        carry = data[even:]
        for i in range(0, even, 2):
            peak = max(peak, abs(int.from_bytes(data[i : i + 2], "little", signed=True)))
    else:
        time.sleep(0.02)  # no writer attached: the FIFO reads as EOF, do not spin
    now = time.monotonic() - start
    if now - last_report >= 0.2:
        print(json.dumps({"t": round(now, 3), "bytes": total, "peak": peak}), flush=True)
        last_report = now
