from __future__ import annotations

import unittest
from core.branding import APP_NAME, APP_TAGLINE, APP_WINDOW_TITLE
from core.config import STARTING_LIFE
from core.game_logic import GameEngine
from core.models import Element, PHASE_DICE_BATTLE


class GameStartTests(unittest.TestCase):
    def test_product_branding_is_godao(self) -> None:
        self.assertEqual(APP_NAME, "GODAO")
        self.assertEqual(APP_TAGLINE, "Game of Decisions and Odds")
        self.assertEqual(APP_WINDOW_TITLE, "GODAO — Game of Decisions and Odds")

    def test_engine_can_be_created_without_starting_a_game(self) -> None:
        engine = GameEngine(auto_start=False)

        self.assertEqual(engine.turn_number, 0)
        self.assertEqual(engine.log_messages, [])
        self.assertEqual(engine.active_player.name, "Player 1")

    def test_new_game_starts_builder_players_at_starting_life(self) -> None:
        engine = GameEngine()

        self.assertEqual(STARTING_LIFE, 15)
        self.assertEqual(engine.human_player.life, STARTING_LIFE)
        self.assertEqual(engine.ai_player.life, STARTING_LIFE)

    def test_builder_stall_counter_resets_on_player_damage(self) -> None:
        engine = GameEngine()
        engine.turn_number = 10
        engine.builder_last_combat_progress_turn = 3
        engine.builder_last_player_damage_turn = 3

        self.assertEqual(engine.builder_stalled_turns, 7)

        engine.queue_player_damage_event(
            target_player_id=0,
            amount=1,
            source_element=Element.FIRE,
        )

        self.assertEqual(engine.builder_stalled_turns, 0)
        self.assertEqual(engine.builder_player_damage_stalled_turns, 0)
        engine.turn_number = 12
        self.assertEqual(engine.builder_stalled_turns, 2)
        self.assertEqual(engine.builder_player_damage_stalled_turns, 2)

        engine.queue_creature_damage_event(
            target_role="attacker",
            amount=1,
            source_element=Element.FIRE,
        )

        self.assertEqual(engine.builder_stalled_turns, 2)
        self.assertEqual(engine.builder_player_damage_stalled_turns, 2)

    def test_start_test_combat_uses_builder_setup(self) -> None:
        engine = GameEngine()

        engine.start_test_combat()

        self.assertEqual(engine.phase, PHASE_DICE_BATTLE)
        self.assertEqual(len(engine.human_player.battlefield), 1)
        self.assertEqual(len(engine.ai_player.battlefield), 1)
        self.assertEqual(engine.human_player.hand, [])
        self.assertEqual(engine.ai_player.hand, [])
        self.assertIsNotNone(engine.pending_dice_battle)

    def test_new_game_can_force_player_1_to_start(self) -> None:
        engine = GameEngine()

        engine.start_new_game(starting_player_id=0)

        self.assertEqual(engine.starting_player_id, 0)
        self.assertEqual(engine.active_player_index, 0)
        self.assertEqual(engine.active_player.name, "Player 1")
        self.assertEqual(engine.turn_number, 1)

    def test_new_game_can_force_player_2_to_start(self) -> None:
        engine = GameEngine()

        engine.start_new_game(starting_player_id=1)

        self.assertEqual(engine.starting_player_id, 1)
        self.assertEqual(engine.active_player_index, 1)
        self.assertEqual(engine.active_player.name, "Player 2")
        self.assertEqual(engine.turn_number, 1)


if __name__ == "__main__":
    unittest.main()
