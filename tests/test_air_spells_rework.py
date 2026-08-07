from __future__ import annotations

from dataclasses import dataclass

from core.models import CardInstance, PHASE_MAIN_1, PHASE_MAIN_2, PHASE_REACTION, ReactionContext, ReactionTrigger, SpellEffect, SpellTargetRef, SpellTiming
from tests.helpers import EngineTestCase


@dataclass
class _PendingDirectAttackStub:
    attacker_id: int
    base_damage: int
    damage_multiplier: int


class AirSpellReworkTests(EngineTestCase):
    def give_card(self, template_id: str, owner_id: int = 0) -> CardInstance:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        self.engine.players[owner_id].hand.append(card)
        return card

    def give_resources(self, owner_id: int, count: int, *, tapped: bool = False) -> None:
        pool = [
            "fire_creature_gluthetzer",
            "water_creature_wassertropfen",
            "earth_creature_steinkobold",
            "air_creature_windschwinge",
        ]
        resources = [self.make_resource(pool[index % len(pool)]) for index in range(count)]
        for resource in resources:
            resource.tapped = tapped
        self.engine.players[owner_id].resources = resources

    def resolve_reaction_window(self) -> None:
        if self.engine.phase == PHASE_REACTION:
            self.engine.pass_reaction()
            self.engine.pass_reaction()

    def open_main_window(self, phase: str, active_player_id: int) -> None:
        self.engine.active_player_index = active_player_id
        self.engine.phase = phase
        self.engine.begin_main_phase_priority_window(phase, lambda: None)

    def open_combat_start_window(self, attacker_ids: list[int], *, active_player_id: int = 0, first_responder_id: int | None = None) -> None:
        self.engine.active_player_index = active_player_id
        self.engine.block_assignments = {attacker_id: None for attacker_id in attacker_ids}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_START,
                active_player=self.engine.players[active_player_id],
                source_player=self.engine.players[active_player_id],
            ),
            first_responder_id=active_player_id if first_responder_id is None else first_responder_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

    def cast_air_spell(self, template_id: str, *, owner_id: int = 0, targets: list[SpellTargetRef] | None = None) -> None:
        card = self.give_card(template_id, owner_id=owner_id)
        self.assertTrue(self.engine.begin_spell_from_hand(card.instance_id))
        if self.engine.pending_spell_cast is None:
            self.resolve_reaction_window()
            return
        for target in targets or []:
            self.engine.select_spell_target_ref(target)
        self.assertTrue(self.engine.confirm_pending_spell_cast())
        self.resolve_reaction_window()

    def test_air_spell_cards_match_final_table(self) -> None:
        expected = {
            "air_spell_verwehung": ("Verwehung", 1, 0, SpellTiming.INSTANT, SpellEffect.RETURN_CREATURES_TO_HAND, 1, 0, 0, ()),
            "air_spell_verwirbelung": ("Verwirbelung", 2, 0, SpellTiming.INSTANT, SpellEffect.RETURN_CREATURES_TO_HAND, 2, 0, 0, ()),
            "air_spell_jagdwind": ("Jagdwind", 1, 0, SpellTiming.COMBAT, SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT, 1, 0, 1, (ReactionTrigger.COMBAT_START,)),
            "air_spell_sturmjagd": ("Sturmjagd", 2, 0, SpellTiming.COMBAT, SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT, 2, 0, 2, (ReactionTrigger.COMBAT_START,)),
        }
        for template_id, (name, resources, recycle, timing, effect, amount, aw_bonus, sw_bonus, legal_windows) in expected.items():
            template = self.engine.templates[template_id]
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost.resources, resources)
            self.assertEqual(template.cost.recycle, recycle)
            self.assertEqual(template.spell_timing, timing)
            self.assertEqual(template.spell_effect, effect)
            self.assertEqual(template.spell_amount, amount)
            self.assertEqual(getattr(template, "combat_aw_bonus", 0), aw_bonus)
            self.assertEqual(getattr(template, "combat_sw_bonus", 0), sw_bonus)
            self.assertEqual(tuple(getattr(template, "legal_reaction_windows", ())), legal_windows)
            self.assertNotIn("Deine", template.rules_text)
            self.assertNotIn("Eigene", template.rules_text)

    def test_verwehung_is_playable_in_main_phases_and_not_in_combat_windows(self) -> None:
        spell = self.give_card("air_spell_verwehung")
        self.give_resources(0, 1)
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1
        self.assertTrue(self.engine.can_play_card(self.engine.human_player, spell))
        self.engine.phase = PHASE_MAIN_2
        self.assertTrue(self.engine.can_play_card(self.engine.human_player, spell))

        self.open_main_window(PHASE_MAIN_1, active_player_id=1)
        self.assertTrue(self.engine.can_react_with_card(self.engine.human_player, spell))
        self.resolve_reaction_window()

        self.open_main_window(PHASE_MAIN_2, active_player_id=1)
        self.assertTrue(self.engine.can_react_with_card(self.engine.human_player, spell))
        self.assertIsNotNone(target)
        self.resolve_reaction_window()

        self.open_combat_start_window([], active_player_id=0)
        self.assertFalse(self.engine.can_react_with_card(self.engine.human_player, spell))
        self.resolve_reaction_window()

        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_END,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
            ),
            first_responder_id=0,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_2,
        )
        self.assertFalse(self.engine.can_react_with_card(self.engine.human_player, spell))

    def test_verwehung_returns_any_creature_without_death(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_spell_verwehung")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.open_main_window(PHASE_MAIN_1, active_player_id=1)
        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.assertTrue(self.engine.confirm_pending_spell_cast())
        self.resolve_reaction_window()

        self.assertIsNone(self.engine.get_unit_by_id(target.unit_id))
        self.assertEqual(self.engine.creatures_died_this_turn, 0)
        self.assertTrue(any(card.template.template_id == "earth_creature_felsensoldat" for card in self.engine.ai_player.hand))

    def test_verwirbelung_requires_two_distinct_creatures(self) -> None:
        spell = self.give_card("air_spell_verwirbelung")
        self.give_resources(0, 2)
        only_target = self.make_creature("air_creature_windschwinge", owner_id=0)
        self.engine.phase = PHASE_MAIN_1
        self.assertFalse(self.engine.can_play_card(self.engine.human_player, spell))

        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.assertTrue(self.engine.can_play_card(self.engine.human_player, spell))
        self.assertTrue(self.engine.begin_spell_cast(spell.instance_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=only_target.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=only_target.unit_id))
        self.assertEqual(len(self.engine.pending_spell_cast.selected_targets), 1)
        self.assertFalse(self.engine.pending_spell_ready())
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.assertTrue(self.engine.pending_spell_ready())

    def test_jagdwind_and_sturmjagd_are_only_legal_at_combat_start(self) -> None:
        jagdwind = self.give_card("air_spell_jagdwind")
        sturmjagd = self.give_card("air_spell_sturmjagd")
        self.give_resources(0, 2)
        attacker = self.make_creature("air_creature_windschwinge", owner_id=0)
        self.engine.phase = PHASE_MAIN_1
        self.assertFalse(self.engine.can_play_card(self.engine.human_player, jagdwind))
        self.assertFalse(self.engine.can_play_card(self.engine.human_player, sturmjagd))

        self.open_combat_start_window([attacker.unit_id], active_player_id=0)
        self.assertTrue(self.engine.can_react_with_card(self.engine.human_player, jagdwind))
        self.assertTrue(self.engine.can_react_with_card(self.engine.human_player, sturmjagd))
        self.resolve_reaction_window()

        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_END,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
            ),
            first_responder_id=0,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_2,
        )
        self.assertFalse(self.engine.can_react_with_card(self.engine.human_player, jagdwind))
        self.assertFalse(self.engine.can_react_with_card(self.engine.human_player, sturmjagd))

    def test_defending_player_cannot_cast_attack_buffs_on_enemy_attackers(self) -> None:
        jagdwind = self.give_card("air_spell_jagdwind")
        sturmjagd = self.give_card("air_spell_sturmjagd")
        self.give_resources(0, 2)
        attacker = self.make_creature("air_creature_windschwinge", owner_id=1)
        self.open_combat_start_window([attacker.unit_id], active_player_id=1, first_responder_id=0)

        self.assertFalse(self.engine.can_react_with_card(self.engine.human_player, jagdwind))
        self.assertFalse(self.engine.can_react_with_card(self.engine.human_player, sturmjagd))

    def test_jagdwind_buffs_all_attackers_but_not_other_creatures_and_ends_after_combat(self) -> None:
        self.give_resources(0, 1)
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=0)
        resting = self.make_creature("air_creature_windschwinge", owner_id=0)
        self.open_combat_start_window([attacker_one.unit_id, attacker_two.unit_id], active_player_id=0)

        self.cast_air_spell("air_spell_jagdwind")

        self.assertEqual(self.engine.get_creature_damage_value(attacker_one), attacker_one.sw + 1)
        self.assertEqual(self.engine.get_creature_damage_value(attacker_two), attacker_two.sw + 1)
        self.assertEqual(self.engine.get_creature_damage_value(resting), resting.sw)

        self.engine.enter_second_main_phase()
        self.assertEqual(self.engine.get_creature_damage_value(attacker_one), attacker_one.sw)
        self.assertEqual(self.engine.get_creature_damage_value(attacker_two), attacker_two.sw)

    def test_sturmjagd_stacks_and_increases_direct_damage(self) -> None:
        self.give_resources(0, 3)
        attacker = self.make_creature("air_creature_windschwinge", owner_id=0)
        self.open_combat_start_window([attacker.unit_id], active_player_id=0)

        self.cast_air_spell("air_spell_jagdwind")
        self.open_combat_start_window([attacker.unit_id], active_player_id=0)
        self.cast_air_spell("air_spell_sturmjagd")

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw)
        self.assertEqual(self.engine.get_creature_damage_value(attacker), attacker.sw + 3)
        self.engine.ai_player.life = 20
        self.engine.pending_direct_attack = _PendingDirectAttackStub(attacker.unit_id, self.engine.get_creature_damage_value(attacker), 1)
        self.engine.resolve_pending_direct_attack_after_reaction()
        self.assertEqual(self.engine.ai_player.life, 20 - (attacker.sw + 3))

    def test_ai_does_not_reserve_verwehung_for_combat(self) -> None:
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.ai_player.summoner_key = "air"
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"]),
        ]
        self.engine.ai_player.resources = [self.make_resource("fire_creature_gluthetzer")]
        self.make_creature("air_creature_windgeist", owner_id=1, ready=True)

        payload = self.engine.ai.turn_planner.build_turn_plan_payload(
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertEqual(payload.get("reserved_resources", 0), 0)
        self.assertFalse(any(intent["card_instance_id"] == self.engine.ai_player.hand[0].instance_id for intent in payload.get("reaction_intents", ())))

    def test_ai_defending_player_passes_instead_of_casting_jagdwind(self) -> None:
        self.engine.active_player_index = self.engine.human_player.player_id
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]
        self.engine.ai_player.resources = [self.make_resource("fire_creature_gluthetzer")]
        attacker = self.make_creature("air_creature_windschwinge", owner_id=0)
        self.open_combat_start_window([attacker.unit_id], active_player_id=0, first_responder_id=1)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "reaction_pass")

    def test_ai_casts_sw_buffs_when_only_unblocked_sw_damage_matters(self) -> None:
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_sturmjagd"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        attacker = self.make_creature("air_creature_windschwinge", owner_id=1)
        self.engine.human_player.life = attacker.sw + 2
        self.open_combat_start_window([attacker.unit_id], active_player_id=1)

        chosen = self.engine.ai.choose_spell(self.engine.ai_player.hand, self.engine)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_spell_sturmjagd")

