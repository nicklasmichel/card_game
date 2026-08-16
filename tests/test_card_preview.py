from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from ui.assets import draw_card_preview_overlay


class CardPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_zoomed_card_has_no_additional_outer_frame(self) -> None:
        app = SimpleNamespace(
            preview_builder=None,
            preview_surface=pygame.Surface((120, 180), pygame.SRCALPHA),
            preview_info_builder=lambda: [],
            window_width=1000,
            window_height=700,
            side_panel_width=250,
            screen=pygame.Surface((1000, 700), pygame.SRCALPHA),
        )

        with patch("ui.assets.pygame.draw.rect") as draw_rect:
            draw_card_preview_overlay(app)

        draw_rect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
