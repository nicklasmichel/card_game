from __future__ import annotations

from types import SimpleNamespace

from cards.registry import DECK_DEFINITIONS, build_test_deck
from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardTemplate, CardType, Element, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1, PlayerState
from tests.helpers import EngineTestCase
from ui.render_helpers import get_display_creature_stats, get_display_template_stats, normalize_rules_text


class CardEffectsTests(EngineTestCase):
    def test_air_creatures_match_final_card_table(self) -> None:
        expected = {
            "air_creature_sturmschwinge": ("Sturmschwinge", CardCost(resources=0, recycle=1), 1, 1, 1, 1, {Ability.FLYING}),
            "air_creature_sturmgeist": ("Sturmgeist", CardCost(resources=0, recycle=2), 2, 2, 2, 1, {Ability.HASTE}),
            "air_creature_wolkenschwinge": ("Wolkenschwinge", CardCost(resources=1), 1, 1, 1, 1, {Ability.FLYING}),
            "air_creature_wolkengeist": ("Wolkengeist", CardCost(resources=1), 1, 1, 1, 1, {Ability.HASTE}),
            "air_creature_windgeist": ("Windgeist", CardCost(resources=2), 2, 1, 2, 1, {Ability.HASTE}),
            "air_creature_windschwinge": ("Windschwinge", CardCost(resources=2), 1, 2, 2, 1, {Ability.FLYING}),
            "air_creature_himmelsgeist": ("Himmelsgeist", CardCost(resources=3), 3, 1, 2, 2, {Ability.HASTE}),
            "air_creature_himmelsschwinge": ("Himmelsschwinge", CardCost(resources=3), 1, 3, 2, 1, {Ability.FLYING}),
            "air_creature_orkanschwinge": ("Orkanschwinge", CardCost(resources=4, recycle=1), 2, 4, 3, 2, {Ability.FLYING}),
            "air_creature_orkangeist": ("Orkangeist", CardCost(resources=4, recycle=1), 4, 2, 3, 2, {Ability.HASTE}),
        }
        for template_id, (name, cost, aw, vw, lw, sw, abilities) in expected.items():
            template = self.engine.templates[template_id]
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost, cost)
            self.assertEqual(template.aw, aw)
            self.assertEqual(template.vw, vw)
            self.assertEqual(template.lw, lw)
            self.assertEqual(template.sw, sw)
            self.assertEqual(template.effective_lw, lw)
            self.assertEqual(template.effective_sw, sw)
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
            "fire_creature_aschebestie": ("Aschebestie", CardCost(resources=2), 2, 1, 2, 1, {Ability.ENRAGED}, True),
            "fire_creature_aschebrecher": ("Aschebrecher", CardCost(resources=2), 1, 1, 2, 1, {Ability.TRAMPLE}, False),
            "fire_creature_glutbestie": ("Glutbestie", CardCost(resources=3), 3, 2, 3, 2, {Ability.ENRAGED}, True),
            "fire_creature_glutbrecher": ("Glutbrecher", CardCost(resources=3), 3, 1, 2, 2, {Ability.TRAMPLE}, False),
            "fire_creature_flammenbestie": ("Flammenbestie", CardCost(resources=4), 4, 3, 4, 2, {Ability.ENRAGED}, True),
            "fire_creature_flammenbrecher": ("Flammenbrecher", CardCost(resources=4), 4, 2, 3, 2, {Ability.TRAMPLE}, False),
            "fire_creature_infernobestie": ("Infernobestie", CardCost(resources=5, recycle=1), 5, 4, 5, 3, {Ability.ENRAGED}, True),
            "fire_creature_infernobrecher": ("Infernobrecher", CardCost(resources=5, recycle=1), 5, 3, 4, 3, {Ability.TRAMPLE}, False),
        }
        for template_id, (name, cost, aw, vw, lw, sw, abilities, must_attack) in expected.items():
            template = self.engine.templates[template_id]
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost, cost)
            self.assertEqual(template.aw, aw)
            self.assertEqual(template.vw, vw)
            self.assertEqual(template.lw, lw)
            self.assertEqual(template.sw, sw)
            self.assertEqual(template.effective_lw, lw)
            self.assertEqual(template.effective_sw, sw)
            self.assertEqual(set(template.abilities), abilities)
            self.assertEqual(template.must_attack_each_turn, must_attack)

    def test_non_creature_templates_remain_valid_without_lw_and_sw(self) -> None:
        template = CardTemplate(
            template_id="test_ritual",
            name="Testritual",
            cost=CardCost(resources=1),
            aw=0,
            vw=0,
            element=Element.AIR,
            card_type=CardType.RITUAL,
        )

        self.assertIsNone(template.lw)
        self.assertIsNone(template.sw)

    def test_water_and_earth_creatures_use_temporary_lw_sw_fallbacks(self) -> None:
        water = self.engine.templates["water_creature_wellenformer"]
        earth = self.engine.templates["earth_creature_felsensoldat"]

        self.assertIsNone(water.lw)
        self.assertIsNone(water.sw)
        self.assertEqual(water.effective_lw, water.vw)
        self.assertEqual(water.effective_sw, water.aw)
        self.assertIsNone(earth.lw)
        self.assertIsNone(earth.sw)
        self.assertEqual(earth.effective_lw, earth.vw)
        self.assertEqual(earth.effective_sw, earth.aw)

    def test_creature_enters_with_current_hp_from_lw_not_vw(self) -> None:
        creature = self.make_creature("air_creature_himmelsgeist", owner_id=0)

        self.assertEqual(creature.vw, 1)
        self.assertEqual(creature.lw, 2)
        self.assertEqual(creature.current_hp, 2)
        self.assertEqual(self.engine.get_creature_max_lw(creature), 2)
        self.assertEqual(self.engine.get_creature_current_lw(creature), 2)

    def test_healing_cap_uses_lw_even_when_vw_is_higher(self) -> None:
        template = CardTemplate(
            template_id="test_heal_creature",
            name="Heal Test",
            cost=CardCost(resources=1),
            aw=1,
            vw=4,
            lw=2,
            sw=1,
            element=Element.WATER,
        )
        creature = BattlefieldCreature.from_card(CardInstance(999, template))
        creature.current_hp = 1

        creature.current_hp = min(creature.lw, creature.current_hp + 5)

        self.assertEqual(creature.current_hp, 2)
        self.assertEqual(creature.lw, 2)
        self.assertEqual(creature.vw, 4)

    def test_display_helpers_show_all_four_stats_and_lw_ratio(self) -> None:
        creature = self.make_creature("air_creature_orkangeist", owner_id=0)
        creature.current_hp = 1
        ui_stub = SimpleNamespace(engine=self.engine)

        self.assertEqual(get_display_creature_stats(ui_stub, creature), ("4", "2", "1/3", "2"))
        self.assertEqual(
            get_display_template_stats(ui_stub, self.engine.templates["fire_creature_flammenbestie"]),
            ("4", "3", "4/4", "2"),
        )

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
        self.assertEqual(len(deck), 40)

    def test_fire_deck_contains_each_new_ritual_exactly_twice(self) -> None:
        fire_ritual_ids = [
            template_id
            for template_id, copies in DECK_DEFINITIONS["fire"]
            if template_id.startswith("fire_ritual_")
            for _ in range(copies)
        ]
        self.assertEqual(len(fire_ritual_ids), 12)
        for template_id in (
            "fire_ritual_holzvorrat",
            "fire_ritual_kohlevorrat",
            "fire_ritual_glutvision",
            "fire_ritual_flammenvision",
            "fire_ritual_hitzewelle",
            "fire_ritual_feuerwelle",
        ):
            self.assertEqual(fire_ritual_ids.count(template_id), 2)

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



