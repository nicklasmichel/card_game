from __future__ import annotations

import unittest
from core.config import STARTING_LIFE
from core.game_logic import GameEngine
from core.models import PHASE_DICE_BATTLE


class GameStartTests(unittest.TestCase):
    def test_new_game_starts_builder_players_at_starting_life(self) -> None:
        engine = GameEngine()

        self.assertEqual(engine.human_player.life, STARTING_LIFE)
        self.assertEqual(engine.ai_player.life, STARTING_LIFE)

    def test_start_test_combat_uses_builder_setup(self) -> None:
        engine = GameEngine()

        engine.start_test_combat()

        self.assertEqual(engine.phase, PHASE_DICE_BATTLE)
        self.assertEqual(len(engine.human_player.battlefield), 1)
        self.assertEqual(len(engine.ai_player.battlefield), 1)
        self.assertEqual(engine.human_player.hand, [])
        self.assertEqual(engine.ai_player.hand, [])
        self.assertIsNotNone(engine.pending_dice_battle)


if __name__ == "__main__":
    unittest.main()
