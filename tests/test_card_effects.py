from __future__ import annotations

from cards.registry import DECK_DEFINITIONS, build_test_deck
from core.models import Ability, CardCost, CardInstance, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1
from tests.helpers import EngineTestCase
from ui.render_helpers import normalize_rules_text


class CardEffectsTests(EngineTestCase):
    def test_air_creatures_match_final_card_table(self) -> None:
        expected = {
            "air_creature_sturmschwinge": ("Sturmschwinge", CardCost(resources=0, recycle=1), 1, 1, {Ability.FLYING}),
            "air_creature_sturmgeist": ("Sturmgeist", CardCost(resources=0, recycle=2), 2, 2, {Ability.HASTE}),
            "air_creature_wolkenschwinge": ("Wolkenschwinge", CardCost(resources=1), 1, 1, {Ability.FLYING}),
            "air_creature_wolkengeist": ("Wolkengeist", CardCost(resources=1), 1, 1, {Ability.HASTE}),
            "air_creature_windgeist": ("Windgeist", CardCost(resources=2), 2, 1, {Ability.HASTE}),
            "air_creature_windschwinge": ("Windschwinge", CardCost(resources=2), 1, 2, {Ability.FLYING}),
            "air_creature_himmelsgeist": ("Himmelsgeist", CardCost(resources=3), 3, 1, {Ability.HASTE}),
            "air_creature_himmelsschwinge": ("Himmelsschwinge", CardCost(resources=3), 1, 3, {Ability.FLYING}),
            "air_creature_orkanschwinge": ("Orkanschwinge", CardCost(resources=4, recycle=1), 2, 4, {Ability.FLYING}),
            "air_creature_orkangeist": ("Orkangeist", CardCost(resources=4, recycle=1), 4, 2, {Ability.HASTE}),
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

    def test_final_air_creatures_have_no_individual_effect_fields(self) -> None:
        for template_id in (
            "air_creature_sturmschwinge",
            "air_creature_sturmgeist",
            "air_creature_wolkenschwinge",
            "air_creature_wolkengeist",
            "air_creature_windschwinge",
            "air_creature_windgeist",
            "air_creature_himmelsschwinge",
            "air_creature_himmelsgeist",
            "air_creature_orkanschwinge",
            "air_creature_orkangeist",
        ):
            with self.subTest(template_id=template_id):
                template = self.engine.templates[template_id]
                self.assertEqual(template.rules_text, "")
                self.assertFalse(template.must_attack_each_turn)
                self.assertFalse(template.cannot_block)
                self.assertEqual(template.draw_on_play, 0)
                self.assertEqual(template.draw_on_attack, 0)
                self.assertEqual(template.draw_on_death, 0)
                self.assertEqual(template.draw_on_player_damage, 0)
                self.assertEqual(template.tap_enemy_creature_on_play, 0)
                self.assertFalse(template.return_other_own_haste_on_combat_death)
                self.assertEqual(template.own_flying_attack_aura, 0)

    def test_fire_creatures_match_final_card_table(self) -> None:
        expected = {
            "fire_creature_aschebestie": ("Aschebestie", CardCost(resources=2), 2, 1, {Ability.ENRAGED}, True),
            "fire_creature_aschebrecher": ("Aschebrecher", CardCost(resources=2), 1, 1, {Ability.TRAMPLE}, False),
            "fire_creature_glutbestie": ("Glutbestie", CardCost(resources=3), 3, 2, {Ability.ENRAGED}, True),
            "fire_creature_glutbrecher": ("Glutbrecher", CardCost(resources=3), 3, 1, {Ability.TRAMPLE}, False),
            "fire_creature_flammenbestie": ("Flammenbestie", CardCost(resources=4), 4, 3, {Ability.ENRAGED}, True),
            "fire_creature_flammenbrecher": ("Flammenbrecher", CardCost(resources=4), 4, 2, {Ability.TRAMPLE}, False),
            "fire_creature_infernobestie": ("Infernobestie", CardCost(resources=5, recycle=1), 5, 4, {Ability.ENRAGED}, True),
            "fire_creature_infernobrecher": ("Infernobrecher", CardCost(resources=5, recycle=1), 5, 3, {Ability.TRAMPLE}, False),
        }
        for template_id, (name, cost, aw, vw, abilities, must_attack) in expected.items():
            template = self.engine.templates[template_id]
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost, cost)
            self.assertEqual(template.aw, aw)
            self.assertEqual(template.vw, vw)
            self.assertEqual(set(template.abilities), abilities)
            self.assertEqual(template.must_attack_each_turn, must_attack)

    def test_final_fire_creatures_have_no_individual_effect_fields(self) -> None:
        for template_id in (
            "fire_creature_aschebestie",
            "fire_creature_aschebrecher",
            "fire_creature_glutbestie",
            "fire_creature_glutbrecher",
            "fire_creature_flammenbestie",
            "fire_creature_flammenbrecher",
            "fire_creature_infernobestie",
            "fire_creature_infernobrecher",
        ):
            with self.subTest(template_id=template_id):
                template = self.engine.templates[template_id]
                self.assertEqual(template.rules_text, "")
                self.assertEqual(template.self_damage_on_play, 0)
                self.assertEqual(template.opponent_damage_on_play, 0)
                self.assertFalse(template.cannot_block)
                self.assertEqual(template.draw_on_play, 0)
                self.assertEqual(template.draw_on_attack, 0)
                self.assertEqual(template.draw_on_death, 0)
                self.assertEqual(template.draw_on_player_damage, 0)
                self.assertEqual(template.tap_enemy_creature_on_play, 0)
                self.assertFalse(template.return_other_own_haste_on_combat_death)
                self.assertEqual(template.own_flying_attack_aura, 0)

    def test_fire_deck_contains_each_new_creature_exactly_twice(self) -> None:
        fire_creature_ids = [
            template_id
            for template_id, copies in DECK_DEFINITIONS["fire"]
            if template_id.startswith("fire_creature_")
            for _ in range(copies)
        ]
        self.assertEqual(len(fire_creature_ids), 16)
        for template_id in (
            "fire_creature_aschebestie",
            "fire_creature_aschebrecher",
            "fire_creature_glutbestie",
            "fire_creature_glutbrecher",
            "fire_creature_flammenbestie",
            "fire_creature_flammenbrecher",
            "fire_creature_infernobestie",
            "fire_creature_infernobrecher",
        ):
            self.assertEqual(fire_creature_ids.count(template_id), 2)

    def test_fire_deck_builds_with_intermediate_size(self) -> None:
        deck = build_test_deck("fire", self.engine.templates, self.engine.make_instance_id)
        self.assertEqual(len(deck), 36)

    def test_enraged_creatures_are_selected_as_mandatory_attackers(self) -> None:
        glutbestie = self.make_creature("fire_creature_aschebestie", owner_id=0)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_attack_declaration()

        self.assertEqual(self.engine.phase, PHASE_DECLARE_ATTACKERS)
        self.assertIn(glutbestie.unit_id, self.engine.selected_attackers)

    def test_enraged_creatures_cannot_be_deselected_while_ready(self) -> None:
        glutbestie = self.make_creature("fire_creature_aschebestie", owner_id=0)
        self.engine.phase = PHASE_MAIN_1
        self.engine.begin_attack_declaration()

        self.engine.toggle_attacker(glutbestie.unit_id)

        self.assertIn(glutbestie.unit_id, self.engine.selected_attackers)

    def test_enraged_creatures_are_not_mandatory_when_not_attack_eligible(self) -> None:
        tapped = self.make_creature("fire_creature_aschebestie", owner_id=0)
        tapped.tapped = True
        sick = self.make_creature("fire_creature_glutbestie", owner_id=0)
        sick.summoning_sick = True
        sick.tapped = False

        mandatory = self.engine.get_mandatory_attackers(self.engine.human_player)

        self.assertEqual(mandatory, [])

    def test_trampling_creatures_do_not_gain_attack_duty(self) -> None:
        aschebrecher = self.engine.templates["fire_creature_aschebrecher"]
        self.assertIn(Ability.TRAMPLE, aschebrecher.abilities)
        self.assertFalse(aschebrecher.must_attack_each_turn)

    def test_rules_text_does_not_repeat_leading_ability_name(self) -> None:
        text = normalize_rules_text(
            "Schnell. Mische diese Kreatur am Ende deines Zuges zurÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¼ck in dein Deck.",
            ["Schnell"],
        )
        self.assertEqual(text, "Mische diese Kreatur am Ende deines Zuges zurÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¼ck in dein Deck.")

    def test_wolkengeist_is_not_selected_as_mandatory_attacker(self) -> None:
        wolkengeist = self.make_creature("air_creature_wolkengeist", owner_id=0)

        self.engine.phase = PHASE_MAIN_1
        self.engine.begin_attack_declaration()

        self.assertEqual(self.engine.phase, PHASE_DECLARE_ATTACKERS)
        self.assertNotIn(wolkengeist.unit_id, self.engine.selected_attackers)



