from __future__ import annotations

from types import SimpleNamespace

from cards.registry import DECK_DEFINITIONS, build_test_deck
from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardTemplate, CardType, Element, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1
from tests.helpers import EngineTestCase
from ui.render_helpers import get_display_creature_stats, get_display_template_stats, normalize_rules_text


class CardEffectsTests(EngineTestCase):
    def test_air_creatures_match_final_card_table(self) -> None:
        expected = {
            "air_creature_windschwinge": ("Windschwinge", CardCost(resources=1, recycle=1), 1, 0, 1, 1, {Ability.FLYING}),
            "air_creature_sturmschwinge": ("Sturmschwinge", CardCost(resources=2, recycle=2), 2, 0, 2, 2, {Ability.FLYING}),
            "air_creature_orkanschwinge": ("Orkanschwinge", CardCost(resources=3, recycle=3), 3, 0, 3, 3, {Ability.FLYING}),
            "air_creature_windgeist": ("Windgeist", CardCost(resources=1), 2, 0, 1, 1, {Ability.HASTE}),
            "air_creature_sturmgeist": ("Sturmgeist", CardCost(resources=2), 3, 0, 2, 1, {Ability.HASTE}),
            "air_creature_orkangeist": ("Orkangeist", CardCost(resources=3), 4, 0, 3, 1, {Ability.HASTE}),
            "air_creature_windwesen": ("Windwesen", CardCost(resources=1), 1, 1, 1, 1, set()),
            "air_creature_sturmwesen": ("Sturmwesen", CardCost(resources=2), 2, 2, 2, 1, set()),
            "air_creature_orkanwesen": ("Orkanwesen", CardCost(resources=3), 3, 3, 3, 1, set()),
            "air_creature_luftelementar": ("Luftelementar", CardCost(resources=4, recycle=3), 3, 0, 3, 3, {Ability.FLYING, Ability.HASTE}),
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
            "air_creature_windschwinge",
            "air_creature_sturmschwinge",
            "air_creature_orkanschwinge",
            "air_creature_windgeist",
            "air_creature_sturmgeist",
            "air_creature_orkangeist",
            "air_creature_windwesen",
            "air_creature_sturmwesen",
            "air_creature_orkanwesen",
            "air_creature_luftelementar",
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
            "fire_creature_glutwesen": ("Glutwesen", CardCost(resources=2), 2, 2, 2, 1, set()),
            "fire_creature_flammenwesen": ("Flammenwesen", CardCost(resources=3), 3, 3, 3, 1, set()),
            "fire_creature_glutbrecher": ("Glutbrecher", CardCost(resources=2), 2, 0, 2, 2, {Ability.TRAMPLE}),
            "fire_creature_flammenbrecher": ("Flammenbrecher", CardCost(resources=4), 4, 2, 4, 2, {Ability.TRAMPLE}),
            "fire_creature_gluthetzer": ("Gluthetzer", CardCost(resources=3), 3, 0, 3, 1, {Ability.ENRAGED}),
            "fire_creature_flammenhetzer": ("Flammenhetzer", CardCost(resources=4), 4, 2, 4, 1, {Ability.ENRAGED}),
            "fire_creature_infernobestie": ("Infernobestie", CardCost(resources=5, recycle=1), 5, 3, 5, 3, {Ability.ENRAGED, Ability.TRAMPLE}),
            "fire_creature_hoellenbestie": ("Hoellenbestie", CardCost(resources=5, recycle=2), 6, 3, 6, 3, {Ability.ENRAGED, Ability.TRAMPLE}),
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
            self.assertFalse(template.must_attack_each_turn)

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
        creature = self.make_creature("air_creature_sturmgeist", owner_id=0)

        self.assertEqual(creature.vw, 0)
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

    def test_display_helpers_show_all_four_stats_and_current_lw(self) -> None:
        creature = self.make_creature("air_creature_orkangeist", owner_id=0)
        creature.current_hp = 1
        ui_stub = SimpleNamespace(engine=self.engine)

        self.assertEqual(get_display_creature_stats(ui_stub, creature), ("4", "0", "1", "1"))
        self.assertEqual(
            get_display_template_stats(ui_stub, self.engine.templates["fire_creature_flammenhetzer"]),
            ("4", "2", "4", "1"),
        )

    def test_air_vw_zero_and_blocking_split_match_final_roles(self) -> None:
        for template_id in (
            "air_creature_windschwinge",
            "air_creature_sturmschwinge",
            "air_creature_orkanschwinge",
            "air_creature_windgeist",
            "air_creature_sturmgeist",
            "air_creature_orkangeist",
            "air_creature_luftelementar",
        ):
            creature = self.make_creature(template_id, owner_id=0, ready=True)
            self.assertEqual(self.engine.get_creature_defense_value(creature), 0)
            self.assertNotIn(creature, self.engine.available_blockers(self.engine.human_player))
        for template_id in (
            "air_creature_windwesen",
            "air_creature_sturmwesen",
            "air_creature_orkanwesen",
        ):
            creature = self.make_creature(template_id, owner_id=0, ready=True)
            self.assertGreaterEqual(self.engine.get_creature_defense_value(creature), 1)
            self.assertIn(creature, self.engine.available_blockers(self.engine.human_player))

    def test_air_haste_creatures_can_attack_immediately(self) -> None:
        for template_id in (
            "air_creature_windgeist",
            "air_creature_sturmgeist",
            "air_creature_orkangeist",
            "air_creature_luftelementar",
        ):
            creature = self.make_creature(template_id, owner_id=0)
            self.assertTrue(creature.has_ability(Ability.HASTE))
            self.assertTrue(creature.is_ready())
        for template_id in (
            "air_creature_windwesen",
            "air_creature_sturmschwinge",
            "air_creature_orkanschwinge",
        ):
            creature = self.make_creature(template_id, owner_id=0, ready=False)
            self.assertFalse(creature.has_ability(Ability.HASTE))
            self.assertFalse(creature.is_ready())

    def test_final_fire_creatures_have_no_individual_effect_fields(self) -> None:
        for template_id in (
            "fire_creature_glutwesen",
            "fire_creature_flammenwesen",
            "fire_creature_glutbrecher",
            "fire_creature_gluthetzer",
            "fire_creature_flammenhetzer",
            "fire_creature_flammenbrecher",
            "fire_creature_infernobestie",
            "fire_creature_hoellenbestie",
        ):
            with self.subTest(template_id=template_id):
                template = self.engine.templates[template_id]
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
            "fire_creature_glutwesen",
            "fire_creature_flammenwesen",
            "fire_creature_glutbrecher",
            "fire_creature_gluthetzer",
            "fire_creature_flammenhetzer",
            "fire_creature_flammenbrecher",
            "fire_creature_infernobestie",
            "fire_creature_hoellenbestie",
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

    def test_glutwesen_and_flammenwesen_are_vanilla(self) -> None:
        self.assertEqual(set(self.engine.templates["fire_creature_glutwesen"].abilities), set())
        self.assertEqual(set(self.engine.templates["fire_creature_flammenwesen"].abilities), set())

    def test_trample_only_creatures_have_only_trample(self) -> None:
        self.assertEqual(set(self.engine.templates["fire_creature_glutbrecher"].abilities), {Ability.TRAMPLE})
        self.assertEqual(set(self.engine.templates["fire_creature_flammenbrecher"].abilities), {Ability.TRAMPLE})

    def test_enraged_only_creatures_have_only_enraged(self) -> None:
        self.assertEqual(set(self.engine.templates["fire_creature_gluthetzer"].abilities), {Ability.ENRAGED})
        self.assertEqual(set(self.engine.templates["fire_creature_flammenhetzer"].abilities), {Ability.ENRAGED})

    def test_combined_fire_finishers_have_enraged_and_trample(self) -> None:
        self.assertEqual(set(self.engine.templates["fire_creature_infernobestie"].abilities), {Ability.ENRAGED, Ability.TRAMPLE})
        self.assertEqual(set(self.engine.templates["fire_creature_hoellenbestie"].abilities), {Ability.ENRAGED, Ability.TRAMPLE})

    def test_enraged_no_longer_creates_mandatory_attackers(self) -> None:
        creature = self.make_creature("fire_creature_gluthetzer", owner_id=0)
        self.assertFalse(creature.must_attack_each_turn)
        self.assertEqual(self.engine.get_mandatory_attackers(self.engine.human_player), [])

    def test_rules_text_does_not_repeat_leading_ability_name(self) -> None:
        text = normalize_rules_text(
            "Schnell. Mische diese Kreatur am Ende deines Zuges zurÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ck in dein Deck.",
            ["Schnell"],
        )
        self.assertEqual(text, "Mische diese Kreatur am Ende deines Zuges zurÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼ck in dein Deck.")

    def test_air_haste_creatures_are_not_selected_as_mandatory_attackers(self) -> None:
        windgeist = self.make_creature("air_creature_windgeist", owner_id=0)

        self.engine.phase = PHASE_MAIN_1
        self.engine.begin_attack_declaration()

        self.assertEqual(self.engine.phase, PHASE_DECLARE_ATTACKERS)
        self.assertNotIn(windgeist.unit_id, self.engine.selected_attackers)




