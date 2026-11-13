"""Private, per-tab shell IPC. NUL-delimited; no eval and no output scraping."""
from __future__ import annotations
import os
import tempfile
from pathlib import Path

FIELD_COUNTS = {b"P": 5, b"S": 4, b"B": 0}
MAX_BUFFER = 2 * 1024 * 1024

class Decoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[tuple[str, list[str]]]:
        self.buffer.extend(data)
        if len(self.buffer) > MAX_BUFFER:
            self.buffer.clear()
            return []
        events = []
        while True:
            end = self.buffer.find(0)
            if end < 0:
                break
            tag = bytes(self.buffer[:end])
            count = FIELD_COUNTS.get(tag)
            if count is None:
                del self.buffer[:end + 1]
                continue
            cuts = [end]
            pos = end + 1
            for _ in range(count):
                end = self.buffer.find(0, pos)
                if end < 0:
                    return events
                cuts.append(end)
                pos = end + 1
            fields = [bytes(self.buffer[cuts[i] + 1:cuts[i + 1]]).decode("utf-8", "replace") for i in range(count)]
            del self.buffer[:pos]
            events.append((tag.decode("ascii"), fields))
        return events

class SessionIPC:
    def __init__(self):
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        base = None
        if runtime:
            try:
                st = os.stat(runtime)
                if st.st_uid == os.getuid() and not st.st_mode & 0o077 and os.path.isdir(runtime):
                    base = runtime
            except OSError:
                pass
        self._tmp = tempfile.TemporaryDirectory(prefix="auralyn-", dir=base)
        self.directory = Path(self._tmp.name)
        os.chmod(self.directory, 0o700)
        self.fifo = self.directory / "events"
        self.replacement = self.directory / "replacement"
        os.mkfifo(self.fifo, 0o600)
        # The read/write open means the interactive shell never blocks on open.
        self.fd = os.open(self.fifo, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        self.decoder = Decoder()

    def receive(self):
        messages = []
        while True:
            try:
                data = os.read(self.fd, 65536)
                if not data:
                    break
                messages.extend(self.decoder.feed(data))
            except BlockingIOError:
                break
            except InterruptedError:
                continue
        return messages

    def write_replacement(self, old_line: str, old_point: int, new_line: str, new_point: int):
        fields = [old_line, str(old_point), new_line, str(new_point)]
        if any("\0" in field for field in fields):
            raise ValueError("NUL characters are not allowed in shell input")
        fd, name = tempfile.mkstemp(prefix=".replace-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"\0".join(field.encode("utf-8") for field in fields) + b"\0")
            os.replace(name, self.replacement)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        self._tmp.cleanup()
