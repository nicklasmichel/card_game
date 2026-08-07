from __future__ import annotations

import unittest

from core.config import STARTING_LIFE
from core.game_logic import GameEngine


class GameStartTests(unittest.TestCase):
    def test_new_game_starts_both_summoners_at_starting_life(self) -> None:
        engine = GameEngine()

        self.assertEqual(engine.human_player.life, STARTING_LIFE)
        self.assertEqual(engine.ai_player.life, STARTING_LIFE)


if __name__ == "__main__":
    unittest.main()
