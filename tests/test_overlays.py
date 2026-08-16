from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from ui.overlays import draw_dice_battle_overlay, draw_game_over_overlay


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_combat_overlay_draws_roll_sums_on_the_cards(self) -> None:
        attacker_rect = pygame.Rect(20, 20, 120, 170)
        blocker_rect = pygame.Rect(180, 20, 120, 170)
        battle = SimpleNamespace(
            attacker_id=1,
            blocker_id=2,
            attacker_rolls=[6, 5, 4],
            blocker_rolls=[4, 3, 2],
            attack_sum=15,
            defense_sum=9,
            winner="attacker",
            reroll_count=0,
        )
        app = SimpleNamespace(
            engine=SimpleNamespace(pending_dice_battles=[battle], pending_dice_battle=None),
            creature_rects={1: attacker_rect, 2: blocker_rect},
            combat_overlay_card_rects={},
            screen=pygame.Surface((340, 210)),
            scale_ui=lambda value: value,
        )

        with patch("ui.overlays._draw_combat_sum") as draw_sum:
            draw_dice_battle_overlay(app)

        self.assertEqual(
            draw_sum.call_args_list,
            [
                call(app, attacker_rect, 15, winner=True),
                call(app, blocker_rect, 9, winner=False),
            ],
        )

    def test_game_over_overlay_uses_english_title(self) -> None:
        app = SimpleNamespace(
            window_width=1000,
            window_height=700,
            screen=pygame.Surface((1000, 700)),
            scale_ui=lambda value: value,
            title_font=pygame.font.Font(None, 28),
            font=pygame.font.Font(None, 20),
            engine=SimpleNamespace(game_over_text="Player 1 wins.", game_over_summary_lines=[]),
            blit_centered_text=Mock(),
            blit_text=Mock(),
        )

        draw_game_over_overlay(app)

        self.assertEqual(app.blit_centered_text.call_args_list[0].args[1], "Game Over")


if __name__ == "__main__":
    unittest.main()
