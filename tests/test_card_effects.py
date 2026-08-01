from __future__ import annotations

from core.models import CardInstance, PHASE_FORCED_DISCARD, PHASE_SUMMONING
from tests.helpers import EngineTestCase


class CardEffectsTests(EngineTestCase):
    def test_self_damage_creature_hurts_controller_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_bombenwicht"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [self.make_resource("fire_funkenkobold")]
        self.engine.human_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.human_player.life, 18)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "player_damage")
        self.assertEqual(self.engine.pending_visual_events[-1]["target_player_id"], self.engine.human_player.player_id)

    def test_cannot_block_creature_is_excluded_from_available_blockers(self) -> None:
        defender = self.make_creature("fire_funkenwicht", owner_id=0)

        blockers = self.engine.available_blockers(self.engine.human_player)

        self.assertNotIn(defender, blockers)

    def test_flammenrekrut_deals_one_damage_to_opponent_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_flammenrekrut"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
            self.make_resource("earth_steinkobold"),
        ]
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.ai_player.life, 19)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "player_damage")
        self.assertEqual(self.engine.pending_visual_events[-1]["target_player_id"], self.engine.ai_player.player_id)

    def test_lavakrieger_deals_three_damage_to_both_players_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_lavakrieger"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
            self.make_resource("earth_steinkobold"),
            self.make_resource("air_windgeist"),
        ]
        self.engine.human_player.life = 20
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.human_player.life, 17)
        self.assertEqual(self.engine.ai_player.life, 17)
        self.assertEqual(len(self.engine.pending_visual_events), 2)
        self.assertTrue(all(event["type"] == "player_damage" for event in self.engine.pending_visual_events[-2:]))

    def test_windgeist_forces_human_discard_selection_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_windgeist"])
        spare = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_funkenkobold"])
        self.engine.human_player.hand = [card, spare]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
        ]
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.phase, PHASE_FORCED_DISCARD)
        self.assertIsNotNone(self.engine.pending_forced_discard)
        self.assertEqual(self.engine.pending_forced_discard.required_count, 1)

    def test_sturmfalke_forces_ai_to_discard_one_card_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_sturmfalke"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
            self.make_resource("earth_steinkobold"),
            self.make_resource("air_windgeist"),
        ]
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_wassertropfen"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(len(self.engine.ai_player.hand), 1)
        self.assertEqual(len(self.engine.ai_player.discard_pile), 1)

    def test_windhuscher_returns_to_deck_at_end_of_turn(self) -> None:
        creature = self.make_creature("air_windhuscher", owner_id=0)
        self.engine.human_player.deck = []

        self.engine.resolve_end_of_turn_returns(self.engine.human_player)

        self.assertEqual(len(self.engine.human_player.battlefield), 0)
        self.assertEqual(len(self.engine.human_player.deck), 1)
        self.assertEqual(self.engine.human_player.deck[0].template.template_id, "air_windhuscher")
