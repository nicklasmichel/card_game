from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from multiplayer.server import DEFAULT_GAME_PORT
from multiplayer.server import ServerStatus
from ui.network_menu import parse_host_address, select_match_mode, update_network_state, validate_player_name


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

    def test_player_name_is_trimmed_and_bounded(self) -> None:
        self.assertEqual(validate_player_name("  Alice  "), "Alice")
        for value in ("", " " * 4, "x" * 33):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_player_name(value)

    def test_pve_starts_immediately_with_random_start_player(self) -> None:
        replacement = Mock()
        app = SimpleNamespace(
            network_error_text="",
            network_role="menu",
            match_mode_selection_open=True,
            join_address_input_open=False,
            _replace_session=Mock(),
        )

        with patch("ui.network_menu.LocalPveSession", return_value=replacement):
            select_match_mode(app, "pve")

        replacement.start_new_game.assert_called_once_with()
        self.assertFalse(app.match_mode_selection_open)

    def test_host_randomly_starts_game_when_friend_connects(self) -> None:
        session = Mock()
        app = SimpleNamespace(
            network_role="host",
            host_server=SimpleNamespace(status=ServerStatus.CONNECTED),
            network_peer_was_connected=False,
            engine=SimpleNamespace(turn_number=0),
            session=session,
        )

        update_network_state(app)

        self.assertTrue(app.network_peer_was_connected)
        session.start_new_game.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
