from __future__ import annotations

import unittest
from types import SimpleNamespace

import pygame

from ui.render_interaction import (
    draw_playfield_section_box,
    get_resource_background_segment_rects,
)


class ResourceBackgroundTests(unittest.TestCase):
    def test_layout_creates_ten_vertical_non_overlapping_segments(self) -> None:
        segments = get_resource_background_segment_rects(1000, 400)

        self.assertEqual(len(segments), 10)
        self.assertTrue(all(segment.height > segment.width for segment in segments))
        self.assertTrue(all(left.right < right.left for left, right in zip(segments, segments[1:])))
        self.assertTrue(all(pygame.Rect(0, 0, 1000, 400).contains(segment) for segment in segments))

    def test_one_background_segment_is_lit_per_total_resource(self) -> None:
        player_one = SimpleNamespace(player_id=0, total_resources=lambda: 3)
        player_two = SimpleNamespace(player_id=1, total_resources=lambda: 0)
        screen = pygame.Surface((1000, 400), pygame.SRCALPHA)
        app = SimpleNamespace(
            screen=screen,
            engine=SimpleNamespace(player_one=player_one, player_two=player_two),
            resource_background_counts={},
            resource_background_pulses={},
            get_zone_fill_color=lambda _zone: (100, 120, 140, 54),
            dragged_hand_card_id=None,
        )

        draw_playfield_section_box(app, pygame.Rect(0, 0, 1000, 400), "player_1_creatures")

        segments = get_resource_background_segment_rects(1000, 400)
        lit_colors = [tuple(screen.get_at(segment.center)) for segment in segments[:3]]
        unlit_colors = [tuple(screen.get_at(segment.center)) for segment in segments[3:]]
        self.assertEqual(len(set(lit_colors)), 1)
        self.assertEqual(len(set(unlit_colors)), 1)
        self.assertNotEqual(lit_colors[0], unlit_colors[0])


if __name__ == "__main__":
    unittest.main()
