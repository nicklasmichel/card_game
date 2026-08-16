from __future__ import annotations

import unittest
from types import SimpleNamespace

import pygame

from core.config import STARTING_LIFE
from ui.layout_board import draw_life_bar, get_area_status_metrics, get_life_bar_labels, get_life_bar_rect
from ui.render_interaction import get_resource_background_segment_rects


class LifeBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.font.init()

    def test_life_bar_uses_bottom_ten_percent_of_creature_area(self) -> None:
        creature_area = pygame.Rect(20, 30, 1000, 400)

        life_bar = get_life_bar_rect(creature_area)
        segments = get_resource_background_segment_rects(creature_area.width, creature_area.height)

        self.assertEqual(life_bar.top, 390)
        self.assertEqual(life_bar.height, 40)
        self.assertEqual(life_bar.left, creature_area.x + segments[0].left)
        self.assertEqual(life_bar.right, creature_area.x + segments[-1].right)

    def test_player_two_life_bar_uses_top_ten_percent_of_creature_area(self) -> None:
        creature_area = pygame.Rect(20, 30, 1000, 400)

        life_bar = get_life_bar_rect(creature_area, at_top=True)
        segments = get_resource_background_segment_rects(creature_area.width, creature_area.height)

        self.assertEqual(life_bar.top, 30)
        self.assertEqual(life_bar.height, 40)
        self.assertEqual(life_bar.left, creature_area.x + segments[0].left)
        self.assertEqual(life_bar.right, creature_area.x + segments[-1].right)

    def test_life_bar_visually_fills_according_to_current_life(self) -> None:
        screen = pygame.Surface((1000, 400), pygame.SRCALPHA)
        app = SimpleNamespace(
            screen=screen,
            title_font=pygame.font.Font(None, 22),
            scale_ui=lambda value: value,
        )
        player = SimpleNamespace(name="Player 1", life=5, battlefield=[object(), object()])
        creature_area = pygame.Rect(0, 0, 1000, 400)

        bar_rect = draw_life_bar(app, player, creature_area)

        filled_pixel = screen.get_at((bar_rect.x + bar_rect.width // 4, bar_rect.centery))
        empty_pixel = screen.get_at((bar_rect.x + bar_rect.width * 3 // 4, bar_rect.centery))
        self.assertNotEqual(filled_pixel, empty_pixel)
        self.assertGreater(filled_pixel.r, empty_pixel.r)
        self.assertEqual(screen.get_at(bar_rect.topleft).a, 0)
        self.assertGreater(screen.get_at((bar_rect.left, bar_rect.centery)).a, 0)
        self.assertGreater(screen.get_at((bar_rect.right - 1, bar_rect.centery)).a, 0)

    def test_life_bar_contains_left_center_and_right_labels(self) -> None:
        player = SimpleNamespace(name="Player 1", life=10, battlefield=[object(), object(), object()])

        labels = get_life_bar_labels(player)

        self.assertEqual(labels, ("Player 1", f"Health 10 / {STARTING_LIFE}", "Creatures 3/5"))

    def test_status_block_no_longer_contains_life_text(self) -> None:
        font = pygame.font.Font(None, 24)
        app = SimpleNamespace(
            title_font=font,
            player_name_font=font,
            scale_ui=lambda value: value,
        )
        player = SimpleNamespace(name="Player 1", life=7, battlefield=[])

        metrics = get_area_status_metrics(app, player)

        self.assertNotIn("life_text", metrics)
        self.assertNotIn("life_width", metrics)
        self.assertNotIn("Life", " ".join(str(value) for value in metrics.values()))


if __name__ == "__main__":
    unittest.main()
