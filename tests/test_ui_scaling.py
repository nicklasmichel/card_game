from __future__ import annotations

import unittest

from ui.scaling import build_layout_metrics, calculate_layout_scale


class UIScalingTests(unittest.TestCase):
    def test_reference_resolution_uses_reduced_design_sizes(self) -> None:
        metrics = build_layout_metrics(1920, 1080)

        self.assertEqual(metrics.scale, 0.9)
        self.assertEqual(metrics.font_scale, 0.8)
        self.assertEqual(metrics.card_width, 155)
        self.assertEqual(metrics.card_height, 195)
        self.assertEqual(metrics.side_panel_width, 423)
        self.assertEqual(metrics.font_size, 16)

    def test_4k_resolution_doubles_the_complete_layout(self) -> None:
        reference = build_layout_metrics(1920, 1080)
        metrics_4k = build_layout_metrics(3840, 2160)

        self.assertEqual(metrics_4k.scale, 1.8)
        self.assertEqual(metrics_4k.font_scale, 1.6)
        self.assertEqual(metrics_4k.card_width, reference.card_width * 2)
        self.assertAlmostEqual(metrics_4k.card_height, reference.card_height * 2, delta=1)
        self.assertEqual(metrics_4k.side_panel_width, reference.side_panel_width * 2)
        self.assertEqual(metrics_4k.font_size, reference.font_size * 2)

    def test_laptop_resolution_reduces_cards_and_sidebar(self) -> None:
        reference = build_layout_metrics(1920, 1080)
        laptop = build_layout_metrics(1366, 768)

        self.assertLess(laptop.scale, 1.0)
        self.assertLess(laptop.card_width, reference.card_width)
        self.assertLess(laptop.card_height, reference.card_height)
        self.assertLess(laptop.side_panel_width, reference.side_panel_width)

    def test_ultrawide_resolution_is_limited_by_available_height(self) -> None:
        self.assertAlmostEqual(calculate_layout_scale(3440, 1440), 1440 / 1080)


if __name__ == "__main__":
    unittest.main()
