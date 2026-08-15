from __future__ import annotations

import socket
import struct
from threading import Lock


FRAME_HEADER_BYTES = 4
MAX_FRAME_BYTES = 1024 * 1024


class ConnectionClosed(ConnectionError):
    """Raised when a peer closes a framed connection."""


class FrameTooLarge(ValueError):
    """Raised before allocating or sending an oversized frame."""


class JsonFrameConnection:
    """Thread-safe sender and incremental length-prefixed UTF-8 receiver."""

    def __init__(self, sock: socket.socket) -> None:
        self.socket = sock
        self._receive_buffer = bytearray()
        self._expected_payload_bytes: int | None = None
        self._send_lock = Lock()
        self._closed = False

    def send(self, message: str) -> None:
        if self._closed:
            raise ConnectionClosed("Connection is closed.")
        if not isinstance(message, str):
            raise TypeError("Framed message must be text.")
        payload = message.encode("utf-8")
        if len(payload) > MAX_FRAME_BYTES:
            raise FrameTooLarge(f"Frame exceeds {MAX_FRAME_BYTES} bytes.")
        frame = struct.pack("!I", len(payload)) + payload
        with self._send_lock:
            try:
                self.socket.sendall(frame)
            except OSError as exc:
                raise ConnectionClosed(str(exc)) from exc

    def receive(self, *, timeout: float | None = None) -> str | None:
        if self._closed:
            raise ConnectionClosed("Connection is closed.")
        previous_timeout = self.socket.gettimeout()
        self.socket.settimeout(timeout)
        try:
            while True:
                message = self._pop_complete_message()
                if message is not None:
                    return message
                try:
                    chunk = self.socket.recv(65536)
                except socket.timeout:
                    return None
                except OSError as exc:
                    raise ConnectionClosed(str(exc)) from exc
                if not chunk:
                    raise ConnectionClosed("Peer closed the connection.")
                self._receive_buffer.extend(chunk)
        finally:
            try:
                self.socket.settimeout(previous_timeout)
            except OSError:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()

    def _pop_complete_message(self) -> str | None:
        if self._expected_payload_bytes is None:
            if len(self._receive_buffer) < FRAME_HEADER_BYTES:
                return None
            self._expected_payload_bytes = struct.unpack(
                "!I",
                self._receive_buffer[:FRAME_HEADER_BYTES],
            )[0]
            del self._receive_buffer[:FRAME_HEADER_BYTES]
            if self._expected_payload_bytes > MAX_FRAME_BYTES:
                raise FrameTooLarge(f"Peer announced a frame larger than {MAX_FRAME_BYTES} bytes.")
        if len(self._receive_buffer) < self._expected_payload_bytes:
            return None
        payload_size = self._expected_payload_bytes
        payload = bytes(self._receive_buffer[:payload_size])
        del self._receive_buffer[:payload_size]
        self._expected_payload_bytes = None
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Frame payload is not valid UTF-8.") from exc
