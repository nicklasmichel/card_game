from __future__ import annotations

import unittest

from core.game_logic import GameEngine
from core.models import MatchMode
from multiplayer.lobby_protocol import (
    ClientHello,
    ServerError,
    ServerWelcome,
    decode_lobby_message,
)
from multiplayer.snapshot import GameStateSnapshot


class LobbyProtocolTests(unittest.TestCase):
    def test_hello_welcome_and_error_round_trip(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        snapshot = GameStateSnapshot.from_engine(engine, viewer_player_id=1, revision=2)
        messages = [
            ClientHello("Alice", client_id="client-1"),
            ServerWelcome("session-1", 1, "Bob", snapshot),
            ServerError("server_full", "Another player is connected."),
        ]

        for message in messages:
            with self.subTest(message=type(message).__name__):
                self.assertEqual(decode_lobby_message(message.to_json()), message)

    def test_welcome_rejects_snapshot_for_another_player(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        snapshot = GameStateSnapshot.from_engine(engine, viewer_player_id=0, revision=0)

        with self.assertRaises(ValueError):
            ServerWelcome("session-1", 1, "Host", snapshot)


if __name__ == "__main__":
    unittest.main()
