from __future__ import annotations

import unittest

from core.models import Ability
from ui.render_helpers import ABILITY_DISPLAY_NAMES, get_card_art_key


class UICardArtTests(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = type(
            "Renderer",
            (),
            {
                "card_art_images": {
                    "flying": object(),
                    "haste": object(),
                    "trample": object(),
                    "vigilance": object(),
                }
            },
        )()

    @staticmethod
    def source(*abilities: Ability):
        return type(
            "Source",
            (),
            {
                "template_id": "builder_creature_test",
                "abilities": frozenset(abilities),
            },
        )()

    def test_paid_haste_uses_primary_builder_ability_art(self) -> None:
        for primary, expected_art in (
            (Ability.FLYING, "flying"),
            (Ability.TRAMPLE, "trample"),
            (Ability.VIGILANCE, "vigilance"),
        ):
            with self.subTest(primary=primary):
                creature = self.source(Ability.HASTE, primary)
                self.assertEqual(get_card_art_key(self.renderer, creature), expected_art)

    def test_haste_only_creature_keeps_haste_art_as_fallback(self) -> None:
        creature = self.source(Ability.HASTE)

        self.assertEqual(get_card_art_key(self.renderer, creature), "haste")

    def test_haste_display_name_is_capitalized(self) -> None:
        self.assertEqual(ABILITY_DISPLAY_NAMES[Ability.HASTE], "Haste")


if __name__ == "__main__":
    unittest.main()
