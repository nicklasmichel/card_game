from __future__ import annotations

import unittest

from multiplayer.server import DEFAULT_GAME_PORT
from ui.network_menu import parse_host_address


class NetworkMenuTests(unittest.TestCase):
    def test_address_without_port_uses_game_default(self) -> None:
        self.assertEqual(
            parse_host_address("25.10.20.30"),
            ("25.10.20.30", DEFAULT_GAME_PORT),
        )

    def test_address_accepts_explicit_port_and_hostname(self) -> None:
        self.assertEqual(parse_host_address("friend.local:50000"), ("friend.local", 50000))

    def test_address_rejects_missing_host_and_invalid_port(self) -> None:
        for value in ("", ":47621", "host:nope", "host:70000"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_host_address(value)


if __name__ == "__main__":
    unittest.main()
