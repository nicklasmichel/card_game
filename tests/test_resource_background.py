from __future__ import annotations

import unittest
from types import SimpleNamespace

import pygame

from ui.render_interaction import (
    draw_playfield_section_box,
    get_resource_background_segment_rects,
)
from ui.layout_board import get_area_status_metrics


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

    def test_locked_segments_use_distinct_player_tints(self) -> None:
        player_one = SimpleNamespace(player_id=0, total_resources=lambda: 0)
        player_two = SimpleNamespace(player_id=1, total_resources=lambda: 0)

        def render_zone(zone_key: str) -> pygame.Color:
            screen = pygame.Surface((1000, 400), pygame.SRCALPHA)
            app = SimpleNamespace(
                screen=screen,
                engine=SimpleNamespace(player_one=player_one, player_two=player_two),
                get_zone_fill_color=lambda _zone: (100, 120, 140, 54),
                dragged_hand_card_id=None,
            )
            draw_playfield_section_box(app, pygame.Rect(0, 0, 1000, 400), zone_key)
            return screen.get_at(get_resource_background_segment_rects(1000, 400)[0].center)

        player_one_color = render_zone("player_1_creatures")
        player_two_color = render_zone("player_2_creatures")

        self.assertGreater(player_one_color.b, player_two_color.b)
        self.assertGreater(player_two_color.r, player_one_color.r)

    def test_status_block_no_longer_contains_resource_counter(self) -> None:
        pygame.font.init()
        font = pygame.font.Font(None, 24)
        app = SimpleNamespace(title_font=font, player_name_font=font, scale_ui=lambda value: value)
        player = SimpleNamespace(
            name="Player 1",
            life=20,
            battlefield=[],
            total_resources=lambda: 1,
        )

        metrics = get_area_status_metrics(app, player)

        self.assertNotIn("resources_text", metrics)
        self.assertNotIn("1/10", " ".join(str(value) for value in metrics.values()))


if __name__ == "__main__":
    unittest.main()
