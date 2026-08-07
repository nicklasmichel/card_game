from __future__ import annotations

from cards import DECK_DEFINITIONS
from core.ai.fire.effects import choose_best_damage_target
from core.models import (
    Ability,
    CardCost,
    CardInstance,
    CardTemplate,
    CardType,
    Element,
    PHASE_MAIN_1,
    PHASE_REACTION,
    ReactionContext,
    ReactionTrigger,
    SpellEffect,
    SpellTargetMode,
    SpellTargetRef,
)
from tests.helpers import EngineTestCase


class EarthCreatureReworkTests(EngineTestCase):
    def give_card(self, template_id: str, owner_id: int = 0) -> CardInstance:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        self.engine.players[owner_id].hand.append(card)
        return card

    def give_resources(self, owner_id: int, count: int, *, tapped: bool = False) -> None:
        pool = [
            "fire_creature_gluthetzer",
            "water_creature_wassertropfen",
            "earth_creature_steinwesen",
            "air_creature_windschwinge",
        ]
        resources = [self.make_resource(pool[index % len(pool)]) for index in range(count)]
        for resource in resources:
            resource.tapped = tapped
        self.engine.players[owner_id].resources = resources

    def resolve_reaction_window(self) -> None:
        if self.engine.phase == "Reaktionsfenster":
            self.engine.pass_reaction()
            self.engine.pass_reaction()

    def open_combat_window_for_attacker(self, attacker) -> None:
        owner = self.engine.get_unit_owner(attacker.unit_id) if attacker is not None else None
        self.engine.active_player_index = owner.player_id if owner is not None else 0
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_START,
                active_player=self.engine.active_player,
                source_player=self.engine.active_player,
                attacker_creature=attacker,
            ),
            first_responder_id=self.engine.active_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

    def test_earth_creatures_match_final_card_table(self) -> None:
        expected = {
            "earth_creature_steinwesen": ("Steinwesen", 2, 0, 2, 2, 1, 2, frozenset()),
            "earth_creature_felswesen": ("Felswesen", 3, 0, 3, 3, 1, 3, frozenset()),
            "earth_creature_steinwaechter": ("Steinwaechter", 2, 0, 1, 3, 1, 2, frozenset({Ability.VIGILANT})),
            "earth_creature_granitwaechter": ("Granitwaechter", 4, 0, 2, 4, 1, 3, frozenset({Ability.VIGILANT})),
            "earth_creature_felsgolem": ("Felsgolem", 3, 1, 3, 3, 1, 3, frozenset({Ability.MAGIC_RESISTANT})),
            "earth_creature_granitgolem": ("Granitgolem", 4, 0, 2, 4, 1, 4, frozenset({Ability.MAGIC_RESISTANT})),
            "earth_creature_gebirgstitan": ("Gebirgstitan", 5, 0, 3, 4, 2, 4, frozenset({Ability.VIGILANT, Ability.MAGIC_RESISTANT})),
            "earth_creature_gebirgskoloss": ("Gebirgskoloss", 5, 1, 3, 6, 2, 5, frozenset({Ability.VIGILANT, Ability.MAGIC_RESISTANT})),
        }
        for template_id, (name, resources, recycle, aw, vw, sw, lw, abilities) in expected.items():
            template = self.engine.templates[template_id]
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost.resources, resources)
            self.assertEqual(template.cost.recycle, recycle)
            self.assertEqual(template.aw, aw)
            self.assertEqual(template.vw, vw)
            self.assertEqual(template.sw, sw)
            self.assertEqual(template.lw, lw)
            self.assertEqual(template.abilities, abilities)

    def test_vanilla_earth_creatures_have_no_abilities(self) -> None:
        self.assertEqual(self.engine.templates["earth_creature_steinwesen"].abilities, frozenset())
        self.assertEqual(self.engine.templates["earth_creature_felswesen"].abilities, frozenset())

    def test_all_earth_creatures_have_explicit_lw_and_sw(self) -> None:
        for template_id, _copies in DECK_DEFINITIONS["earth"]:
            template = self.engine.templates[template_id]
            self.assertIsNotNone(template.lw)
            self.assertIsNotNone(template.sw)
            self.assertEqual(template.effective_lw, template.lw)
            self.assertEqual(template.effective_sw, template.sw)

    def test_vigilant_creature_does_not_tap_when_attacking(self) -> None:
        attacker = self.make_creature("earth_creature_steinwaechter", owner_id=0, ready=True)
        self.engine.active_player_index = 0
        self.engine.block_assignments = {attacker.unit_id: None}

        self.engine.begin_combat_resolution()

        self.assertFalse(attacker.tapped)

    def test_non_vigilant_creature_still_taps_when_attacking(self) -> None:
        attacker = self.make_creature("earth_creature_felswesen", owner_id=0, ready=True)
        self.engine.active_player_index = 0
        self.engine.block_assignments = {attacker.unit_id: None}

        self.engine.begin_combat_resolution()

        self.assertTrue(attacker.tapped)

    def test_vigilant_creature_can_still_block_after_attacking(self) -> None:
        attacker = self.make_creature("earth_creature_granitwaechter", owner_id=0, ready=True)
        self.engine.active_player_index = 0
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.begin_combat_resolution()
        enemy_attacker = self.make_creature("fire_creature_gluthetzer", owner_id=1, ready=True)
        self.engine.active_player_index = 1

        self.assertTrue(self.engine.can_creature_block_attacker(attacker, enemy_attacker))

    def test_vigilant_is_not_haste(self) -> None:
        creature = self.make_creature("earth_creature_steinwaechter", owner_id=0, ready=False)

        self.assertFalse(creature.is_ready())
        self.assertNotIn(creature, self.engine.available_attackers(self.engine.human_player))

    def test_magic_resistant_creature_cannot_be_targeted_by_enemy_instant(self) -> None:
        spell = self.give_card("air_spell_verwehung", owner_id=0)
        self.give_resources(0, 1)
        target = self.make_creature("earth_creature_felsgolem", owner_id=1, ready=True)
        self.engine.phase = PHASE_MAIN_1

        self.assertFalse(self.engine.begin_spell_cast(spell.instance_id))
        self.assertTrue(target.current_hp > 0)

    def test_magic_resistant_creature_cannot_be_targeted_by_own_combat_spell(self) -> None:
        spell = self.give_card("fire_spell_wutanfall", owner_id=0)
        self.give_resources(0, 1, tapped=True)
        target = self.make_creature("earth_creature_gebirgstitan", owner_id=0, ready=True)
        self.open_combat_window_for_attacker(target)

        self.assertFalse(self.engine.begin_spell_from_hand(spell.instance_id))
        self.assertFalse(any(entry.source_card.instance_id == spell.instance_id for entry in self.engine.spell_stack))

    def test_magic_resistant_creature_cannot_be_targeted_by_generic_targeted_ritual(self) -> None:
        template = CardTemplate(
            template_id="test_ritual_targeted",
            name="Test Ritual",
            cost=CardCost(resources=1),
            aw=0,
            vw=0,
            element=Element.FIRE,
            card_type=CardType.RITUAL,
            spell_effect=SpellEffect.DRAW_CARDS,
            target_mode=SpellTargetMode.CREATURE,
        )
        self.engine.templates[template.template_id] = template
        card = CardInstance(self.engine.make_instance_id(), template)
        self.engine.human_player.hand.append(card)
        self.give_resources(0, 1)
        target = self.make_creature("earth_creature_granitgolem", owner_id=1, ready=True)
        self.engine.phase = PHASE_MAIN_1

        self.assertTrue(self.engine.begin_spell_cast(card.instance_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))

        self.assertEqual(self.engine.pending_spell_cast.selected_targets, [])

    def test_hitzewelle_still_hits_magic_resistant_creature(self) -> None:
        ritual = self.give_card("fire_ritual_hitzewelle", owner_id=0)
        self.give_resources(0, 3)
        target = self.make_creature("earth_creature_granitgolem", owner_id=1, ready=True)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(target.current_hp, 2)

    def test_feuerwelle_kills_full_health_magic_resistant_creature(self) -> None:
        ritual = self.give_card("fire_ritual_feuerwelle", owner_id=0)
        self.give_resources(0, 5)
        target = self.make_creature("earth_creature_granitgolem", owner_id=1, ready=True)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIsNone(self.engine.get_unit_by_id(target.unit_id))

    def test_combined_keyword_creature_stays_ready_and_cannot_be_targeted(self) -> None:
        spell = self.give_card("air_spell_verwehung", owner_id=0)
        self.give_resources(0, 1)
        titan = self.make_creature("earth_creature_gebirgskoloss", owner_id=0, ready=True)
        self.engine.active_player_index = 0
        self.engine.block_assignments = {titan.unit_id: None}

        self.engine.begin_combat_resolution()

        self.assertFalse(titan.tapped)
        self.engine.phase = PHASE_MAIN_1
        self.assertFalse(self.engine.begin_spell_cast(spell.instance_id))
        self.assertTrue(titan.is_ready())

    def test_earth_deck_contains_exactly_eight_active_creatures_twice(self) -> None:
        decklist = dict(DECK_DEFINITIONS["earth"])
        active_ids = [
            "earth_creature_steinwesen",
            "earth_creature_felswesen",
            "earth_creature_steinwaechter",
            "earth_creature_granitwaechter",
            "earth_creature_felsgolem",
            "earth_creature_granitgolem",
            "earth_creature_gebirgstitan",
            "earth_creature_gebirgskoloss",
        ]
        self.assertEqual(len(decklist), 8)
        self.assertEqual(sum(decklist.values()), 16)
        for template_id in active_ids:
            self.assertEqual(decklist.get(template_id), 2)

    def test_old_earth_creature_ids_are_gone_from_active_deck(self) -> None:
        active_ids = {template_id for template_id, _copies in DECK_DEFINITIONS["earth"]}
        self.assertTrue(active_ids.isdisjoint({
            "earth_creature_steinkobold",
            "earth_creature_felsensoldat",
            "earth_creature_erdgolem",
            "earth_creature_schildwache",
            "earth_creature_bastionshueter",
            "earth_creature_granitkrieger",
            "earth_creature_bergtroll",
            "earth_creature_uralter_koloss",
        }))

    def test_fire_ai_has_no_legal_burn_target_when_only_magic_resistant_creature_exists(self) -> None:
        self.make_creature("earth_creature_felsgolem", owner_id=0, ready=True)
        self.assertIsNone(choose_best_damage_target(self.engine, self.engine.ai_player, 2))
