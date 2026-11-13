"""Short-lived, process-bound sudo askpass broker.

The password never goes in argv, env, a file, a VTE input buffer or a log.
Only a direct child of the currently armed sudo PID can receive it, once per
sudo command. A private AF_UNIX socket carries the secret to that askpass child.
This does not protect against arbitrary malicious code already running as the
same user (which can also access an unlocked desktop keyring).
"""
from __future__ import annotations
import os
from pathlib import Path
import socket
import stat
import struct
import tempfile
import threading
import time

from .update_secrets import MAX_PASSWORD_BYTES

SOCKET_ENV = 'AURALYN_UPDATE_AUTH_SOCKET'
BROKER_PID_ENV = 'AURALYN_UPDATE_BROKER_PID'
REQUEST = b'AURALYN-UPDATE-ASKPASS-1\n'


def parent_pid(pid: int) -> int:
    try:
        # status is not confused by a process name containing spaces or ')'.
        with open(f'/proc/{int(pid)}/status', encoding='ascii', errors='replace') as f:
            for line in f:
                if line.startswith('PPid:'):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return -1


def wipe(value: bytearray) -> None:
    value[:] = b'\x00' * len(value)
    value.clear()


class PasswordBroker:
    def __init__(self, password: bytearray):
        if not password or len(password) > MAX_PASSWORD_BYTES or any(x in password for x in (0, 10, 13)):
            raise ValueError('Ungültiger Passwortpuffer.')
        self._password = bytearray(password)
        self._directory = tempfile.TemporaryDirectory(prefix='auralyn-update-auth-', dir='/tmp')
        os.chmod(self._directory.name, 0o700)
        self.path = str(Path(self._directory.name) / 'askpass.sock')
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.path)
        os.chmod(self.path, 0o600)
        self._server.listen(4)
        self._server.settimeout(0.2)
        self._stop = threading.Event()
        self._armed = threading.Event()
        self._lock = threading.Lock()
        self._pid = None
        self._served = False
        self._thread = threading.Thread(target=self._serve, name='auralyn-update-auth', daemon=True)
        self._thread.start()

    def prepare(self):
        with self._lock:
            self._armed.clear()
            self._pid = None
            self._served = False

    def arm(self, sudo_pid: int):
        with self._lock:
            self._pid = sudo_pid
            self._armed.set()

    def disarm(self):
        with self._lock:
            self._pid = None
            self._armed.clear()

    @property
    def supplied(self):
        with self._lock:
            return self._served

    def environment(self, base: dict, helper: str) -> dict:
        return {**base, 'SUDO_ASKPASS': helper, SOCKET_ENV: self.path,
                BROKER_PID_ENV: str(os.getpid())}

    def _serve(self):
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                try:
                    connection.settimeout(2)
                    pid, uid, _ = struct.unpack('3i', connection.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                    # sudo may invoke askpass with real-user or root credentials.
                    if uid not in (os.getuid(), 0):
                        continue
                    if connection.recv(64) != REQUEST:
                        continue
                    # Popen has just exec'd sudo; give the parent time to arm.
                    if not self._armed.wait(2) or self._stop.is_set():
                        continue
                    with self._lock:
                        if (self._pid is None or self._served or
                                parent_pid(pid) != self._pid):
                            continue
                        self._served = True
                        connection.sendall(struct.pack('!I', len(self._password)))
                        connection.sendall(self._password)
                except (OSError, ValueError):
                    # Intentionally no exception text or request data in logs.
                    continue

    def close(self):
        self.disarm()
        self._stop.set()
        self._armed.set()
        self._server.close()
        self._thread.join(timeout=3)
        with self._lock:
            wipe(self._password)
        self._directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _read_exact(sock, length):
    result = bytearray()
    while len(result) < length:
        part = sock.recv(length - len(result))
        if not part:
            wipe(result)
            raise OSError('Askpass-Kanal geschlossen.')
        result.extend(part)
    return result


def askpass_main() -> int:
    """Called by sudo, never directly from a user's shell; no keyring access."""
    password = bytearray()
    try:
        path = os.environ.get(SOCKET_ENV, '')
        expected_pid = int(os.environ.get(BROKER_PID_ENV, '0'))
        if expected_pid <= 0 or not path.startswith('/tmp/auralyn-update-auth-'):
            return 1
        info = os.lstat(path)
        directory = os.lstat(os.path.dirname(path))
        if (not stat.S_ISSOCK(info.st_mode) or info.st_mode & 0o077 or
                not stat.S_ISDIR(directory.st_mode) or directory.st_mode & 0o077 or
                info.st_uid != directory.st_uid):
            return 1
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(path)
            pid, uid, _ = struct.unpack('3i', sock.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
            if pid != expected_pid or uid != info.st_uid:
                return 1
            sock.sendall(REQUEST)
            length = struct.unpack('!I', _read_exact(sock, 4))[0]
            if not 0 < length <= MAX_PASSWORD_BYTES:
                return 1
            password = _read_exact(sock, length)
        if any(x in password for x in (0, 10, 13)):
            return 1
        # Only sudo's stdout pipe, never the terminal. Handle short writes.
        data = password + b'\n'
        try:
            offset = 0
            while offset < len(data):
                count = os.write(1, memoryview(data)[offset:])
                if count <= 0:
                    return 1
                offset += count
        finally:
            wipe(data)
        return 0
    except (OSError, ValueError, struct.error):
        return 1
    finally:
        wipe(password)
