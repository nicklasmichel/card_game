from __future__ import annotations

from core.models import CardInstance, PHASE_DECLARE_ATTACKERS, PHASE_SUMMONING
from tests.helpers import EngineTestCase
from ui.render_helpers import normalize_rules_text


class CardEffectsTests(EngineTestCase):
    def test_rules_text_does_not_repeat_leading_ability_name(self) -> None:
        text = normalize_rules_text(
            "Schnell. Mische diese Kreatur am Ende deines Zuges zurück in dein Deck.",
            ["Schnell"],
        )

        self.assertEqual(text, "Mische diese Kreatur am Ende deines Zuges zurück in dein Deck.")

    def test_self_damage_creature_hurts_controller_on_play(self) -> None:
        card_instance = CardInstance(
            self.engine.make_instance_id(),
            self.engine.templates["fire_creature_bombenwicht"],
        )
        self.engine.human_player.hand = [card_instance]
        self.engine.human_player.resources = [self.make_resource("fire_creature_funkenkobold")]
        self.engine.human_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card_instance)

        self.assertTrue(played)
        self.assertEqual(self.engine.human_player.life, 18)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "player_damage")
        self.assertEqual(self.engine.pending_visual_events[-1]["target_player_id"], self.engine.human_player.player_id)

    def test_cannot_block_creature_is_excluded_from_available_blockers(self) -> None:
        defender = self.make_creature("fire_creature_funkenwicht", owner_id=0)

        blockers = self.engine.available_blockers(self.engine.human_player)

        self.assertNotIn(defender, blockers)

    def test_flammenrekrut_deals_one_damage_to_opponent_on_play(self) -> None:
        card_instance = CardInstance(
            self.engine.make_instance_id(),
            self.engine.templates["fire_creature_flammenrekrut"],
        )
        self.engine.human_player.hand = [card_instance]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card_instance)

        self.assertTrue(played)
        self.assertEqual(self.engine.ai_player.life, 19)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "player_damage")
        self.assertEqual(self.engine.pending_visual_events[-1]["target_player_id"], self.engine.ai_player.player_id)

    def test_lavakrieger_deals_three_damage_to_both_players_on_play(self) -> None:
        card_instance = CardInstance(
            self.engine.make_instance_id(),
            self.engine.templates["fire_creature_lavakrieger"],
        )
        self.engine.human_player.hand = [card_instance]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_windgeist"),
        ]
        self.engine.human_player.life = 20
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card_instance)

        self.assertTrue(played)
        self.assertEqual(self.engine.human_player.life, 17)
        self.assertEqual(self.engine.ai_player.life, 17)
        self.assertEqual(len(self.engine.pending_visual_events), 2)
        self.assertTrue(all(event["type"] == "player_damage" for event in self.engine.pending_visual_events[-2:]))

    def test_himmelsspaeher_is_selected_as_mandatory_attacker(self) -> None:
        himmelsspaeher = self.make_creature("air_creature_himmelsspaeher", owner_id=0)

        self.engine.phase = PHASE_SUMMONING
        self.engine.begin_attack_declaration()

        self.assertEqual(self.engine.phase, PHASE_DECLARE_ATTACKERS)
        self.assertIn(himmelsspaeher.unit_id, self.engine.selected_attackers)

    def test_windhuscher_returns_to_deck_at_end_of_turn(self) -> None:
        creature = self.make_creature("air_creature_windhuscher", owner_id=0)
        self.engine.human_player.deck = []

        self.engine.resolve_end_of_turn_returns(self.engine.human_player)

        self.assertEqual(len(self.engine.human_player.battlefield), 0)
        self.assertEqual(len(self.engine.human_player.deck), 1)
        self.assertEqual(self.engine.human_player.deck[0].template.template_id, "air_creature_windhuscher")
