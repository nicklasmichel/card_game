from __future__ import annotations

import socket
import struct
import unittest

from multiplayer.transport import (
    MAX_FRAME_BYTES,
    FrameTooLarge,
    JsonFrameConnection,
)


class JsonFrameConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        left, right = socket.socketpair()
        self.left = JsonFrameConnection(left)
        self.right = JsonFrameConnection(right)

    def tearDown(self) -> None:
        self.left.close()
        self.right.close()

    def test_sends_multiple_unicode_messages_without_losing_boundaries(self) -> None:
        messages = ["first", "Grüße aus GODAO", "{\"value\":3}"]

        for message in messages:
            self.left.send(message)

        self.assertEqual(
            [self.right.receive(timeout=0.5) for _ in messages],
            messages,
        )

    def test_partial_frame_survives_receive_timeout(self) -> None:
        payload = "fragmented".encode("utf-8")
        raw_socket = self.left.socket
        raw_socket.sendall(struct.pack("!I", len(payload)) + payload[:3])

        self.assertIsNone(self.right.receive(timeout=0.01))

        raw_socket.sendall(payload[3:])
        self.assertEqual(self.right.receive(timeout=0.5), "fragmented")

    def test_rejects_oversized_outgoing_and_announced_frames(self) -> None:
        with self.assertRaises(FrameTooLarge):
            self.left.send("x" * (MAX_FRAME_BYTES + 1))

        self.left.socket.sendall(struct.pack("!I", MAX_FRAME_BYTES + 1))
        with self.assertRaises(FrameTooLarge):
            self.right.receive(timeout=0.5)


if __name__ == "__main__":
    unittest.main()
