from __future__ import annotations

from cards.registry import DECK_DEFINITIONS
from core.models import Ability, CardCost, CardInstance, PHASE_DECLARE_ATTACKERS, PHASE_SUMMONING
from tests.helpers import EngineTestCase
from ui.render_helpers import normalize_rules_text


class CardEffectsTests(EngineTestCase):
    def test_air_creatures_match_final_card_table(self) -> None:
        expected = {
            "air_creature_sturmkrieger": ("Sturmkrieger", CardCost(resources=0, recycle=1), 2, 1, {Ability.HASTE}),
            "air_creature_sturmfalke": ("Sturmfalke", CardCost(resources=0, recycle=2), 2, 2, {Ability.FLYING, Ability.HASTE}),
            "air_creature_wolkenkrieger": ("Wolkenkrieger", CardCost(resources=1), 1, 1, {Ability.HASTE}),
            "air_creature_wolkenfalke": ("Wolkenfalke", CardCost(resources=1), 1, 1, {Ability.FLYING}),
            "air_creature_windkrieger": ("Windkrieger", CardCost(resources=2), 2, 1, {Ability.HASTE}),
            "air_creature_windfalke": ("Windfalke", CardCost(resources=2), 1, 2, {Ability.FLYING}),
            "air_creature_himmelskrieger": ("Himmelskrieger", CardCost(resources=3), 3, 1, {Ability.HASTE}),
            "air_creature_himmelsfalke": ("Himmelsfalke", CardCost(resources=3, recycle=1), 1, 3, {Ability.FLYING}),
            "air_creature_orkanreiter": ("Orkanreiter", CardCost(resources=4, recycle=2), 3, 2, {Ability.HASTE}),
            "air_creature_orkanfuerst": ("Orkanfürst", CardCost(resources=4, recycle=2), 2, 3, {Ability.FLYING}),
        }
        for template_id, (name, cost, aw, vw, abilities) in expected.items():
            template = self.engine.templates[template_id]
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost, cost)
            self.assertEqual(template.aw, aw)
            self.assertEqual(template.vw, vw)
            self.assertEqual(set(template.abilities), abilities)
        air_creature_ids = [
            template_id
            for template_id, copies in DECK_DEFINITIONS["air"]
            if template_id.startswith("air_creature_")
            for _ in range(copies)
        ]
        self.assertEqual(len(air_creature_ids), 20)
        for template_id in expected:
            self.assertEqual(air_creature_ids.count(template_id), 2)

    def test_rules_text_does_not_repeat_leading_ability_name(self) -> None:
        text = normalize_rules_text(
            "Schnell. Mische diese Kreatur am Ende deines Zuges zurÃƒÆ’Ã‚Â¼ck in dein Deck.",
            ["Schnell"],
        )
        self.assertEqual(text, "Mische diese Kreatur am Ende deines Zuges zurÃƒÆ’Ã‚Â¼ck in dein Deck.")

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
            self.make_resource("air_creature_wolkenfalke"),
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

    def test_wolkenkrieger_is_selected_as_mandatory_attacker(self) -> None:
        wolkenkrieger = self.make_creature("air_creature_wolkenkrieger", owner_id=0)

        self.engine.phase = PHASE_SUMMONING
        self.engine.begin_attack_declaration()

        self.assertEqual(self.engine.phase, PHASE_DECLARE_ATTACKERS)
        self.assertIn(wolkenkrieger.unit_id, self.engine.selected_attackers)

    def test_himmelskrieger_draws_one_card_on_play(self) -> None:
        card_instance = CardInstance(
            self.engine.make_instance_id(),
            self.engine.templates["air_creature_himmelskrieger"],
        )
        self.engine.human_player.hand = [card_instance]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card_instance)

        self.assertTrue(played)
        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertEqual(self.engine.human_player.hand[0].template.template_id, "air_creature_wolkenfalke")

    def test_windfalke_draws_one_card_on_death(self) -> None:
        creature = self.make_creature("air_creature_windfalke", owner_id=0)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]

        self.engine.destroy_creature_immediately(self.engine.human_player, creature, "Test")

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertEqual(self.engine.human_player.hand[0].template.template_id, "air_creature_wolkenfalke")

    def test_windkrieger_taps_relevant_enemy_creature_on_play(self) -> None:
        card_instance = CardInstance(
            self.engine.make_instance_id(),
            self.engine.templates["air_creature_windkrieger"],
        )
        own_creature = self.make_creature("air_creature_wolkenkrieger", owner_id=0)
        tapped_enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        tapped_enemy.tapped = True
        ready_enemy = self.make_creature("fire_creature_flammenrekrut", owner_id=1)
        self.engine.human_player.hand = [card_instance]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card_instance)

        self.assertTrue(played)
        self.assertFalse(own_creature.tapped)
        self.assertTrue(ready_enemy.tapped)
        self.assertTrue(tapped_enemy.tapped)

    def test_windkrieger_can_be_played_without_enemy_target(self) -> None:
        card_instance = CardInstance(
            self.engine.make_instance_id(),
            self.engine.templates["air_creature_windkrieger"],
        )
        self.engine.human_player.hand = [card_instance]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card_instance)

        self.assertTrue(played)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)
