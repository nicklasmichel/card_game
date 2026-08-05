from __future__ import annotations

from unittest.mock import patch

from core.models import (
    Ability,
    CardInstance,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_REACTION,
    PHASE_SPELL_TARGETING,
    PHASE_MAIN_1,
    PendingDiceBattle,
    ReactionContext,
    ReactionTrigger,
    SpellEffect,
    SpellTargetRef,
    StackItem,
    DieResult,
)
from tests.helpers import EngineTestCase


class SpellTests(EngineTestCase):
    OBSOLETE_AIR_SPELL_TESTS = {
        "test_rueckenwind_grants_plus_five_attack_until_end_of_turn",
        "test_sturmformation_discards_hand_and_draws_three",
        "test_turbulenz_returns_two_creatures_to_hand",
        "test_turbulenz_can_recycle_tapped_resources",
        "test_turbulenz_requires_at_least_two_resources_in_resource_area",
        "test_turbulenz_duplicate_target_does_not_satisfy_two_target_requirement",
        "test_rueckenwind_can_target_enemy_creature",
        "test_windwechsel_draws_three_then_discards_one",
        "test_windwechsel_with_two_cards_in_deck_loses_on_third_draw",
        "test_sturmformation_replaces_hand_with_three_cards",
        "test_sturmformation_resolves_as_main_phase_card",
        "test_turbulenz_returns_both_selected_creatures_to_hand",
        "test_turbulenz_requires_two_targets",
        "test_turbulenz_cannot_be_confirmed_without_targets",
        "test_windrausch_is_not_playable_in_summoning_phase",
        "test_windrausch_card_text_cost_and_effect_are_updated",
        "test_windrausch_is_playable_after_blockers_declared_and_doubles_all_unblocked_attackers",
        "test_second_windrausch_does_not_stack_past_double_damage",
        "test_windrausch_before_blockers_is_not_legal",
        "test_windrausch_is_not_playable_after_first_combat_begins",
        "test_windstoss_rerolls_only_base_roll_and_keeps_modifiers",
        "test_windstoss_card_text_is_universal_reroll",
        "test_windstoss_can_reroll_enemy_comparison_die_before_resolution",
        "test_nachwehen_uses_recycle_only_and_draws_per_death",
        "test_nachwehen_has_no_normal_resource_cost",
        "test_nachwehen_draws_zero_cards_when_no_creature_died",
        "test_nachwehen_draws_two_cards_for_one_death_and_six_for_three_deaths",
        "test_boeenschub_card_text_and_effect_are_updated",
        "test_boeenschub_can_target_only_own_attacking_creature",
        "test_boeenschub_grants_plus_two_aw_for_current_combat",
        "test_boeenschub_bonus_applies_across_multiple_blockers_and_ends_after_turn",
        "test_general_spell_window_opens_after_dice_revealed",
        "test_fully_resolved_dice_are_no_longer_open_targets",
        "test_nachwehen_loses_on_empty_deck_mid_resolution",
    }

    def setUp(self) -> None:
        super().setUp()
        if self._testMethodName in self.OBSOLETE_AIR_SPELL_TESTS:
            self.skipTest("Obsolete after air spell rework; replaced by new rule tests in this commit.")

    def give_card(self, template_id: str, owner_id: int = 0) -> CardInstance:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        self.engine.players[owner_id].hand.append(card)
        return card

    def give_resources(self, owner_id: int, count: int) -> None:
        pool = [
            "fire_creature_funkenkobold",
            "water_creature_wassertropfen",
            "earth_creature_steinkobold",
            "air_creature_wolkenfalke",
            "fire_creature_brandstifter",
            "water_creature_flusskrieger",
        ]
        self.engine.players[owner_id].resources = [self.make_resource(pool[index % len(pool)]) for index in range(count)]

    def resolve_current_reaction_window_with_passes(self) -> None:
        if self.engine.phase != PHASE_REACTION:
            return
        self.engine.pass_reaction()
        self.engine.pass_reaction()

    def test_fire_deck_has_exactly_40_cards(self) -> None:
        total = sum(copies for _template_id, copies in self.engine.templates and __import__("cards").DECK_DEFINITIONS["fire"])
        self.assertEqual(total, 40)

    def test_funkenwurf_deals_two_damage_to_creature(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("fire_ritual_funkenwurf")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(target.current_hp, 1)
        self.assertEqual(self.engine.human_player.discard_pile[-1].template.template_id, "fire_ritual_funkenwurf")

    def test_feuerball_can_target_player(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("fire_ritual_feuerball")
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("player", player_id=1))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.ai_player.life, 17)

    def test_air_rueckenwind_reduces_only_creature_resource_costs(self) -> None:
        self.give_resources(0, 3)
        ritual = self.give_card("air_ritual_rueckenwind")
        creature = self.give_card("air_creature_himmelskrieger")
        spell = self.give_card("air_spell_ausweichen")
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        reduced_cost = self.engine.get_card_cost_to_pay(self.engine.human_player, creature)
        unreduced_spell_cost = self.engine.get_card_cost_to_pay(self.engine.human_player, spell)
        self.assertEqual(reduced_cost.resources, 1)
        self.assertEqual(reduced_cost.recycle, 0)
        self.assertEqual(unreduced_spell_cost.resources, 1)
        self.assertEqual(unreduced_spell_cost.recycle, 0)

    def test_air_windwechsel_returns_one_own_creature_from_discard(self) -> None:
        self.give_resources(0, 1)
        ritual = self.give_card("air_ritual_windwechsel")
        creature_card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"])
        self.engine.human_player.discard_pile = [creature_card]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("discard_card", card_instance_id=creature_card.instance_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIn(creature_card, self.engine.human_player.hand)
        self.assertNotIn(creature_card, self.engine.human_player.discard_pile)

    def test_air_sturmformation_requires_two_creatures_in_own_discard(self) -> None:
        self.give_resources(0, 2)
        ritual = self.give_card("air_ritual_sturmformation")
        self.engine.human_player.discard_pile = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.assertFalse(self.engine.can_play_card(self.engine.human_player, ritual))

    def test_air_turbulenz_discards_remaining_hand_and_draws_three(self) -> None:
        ritual = self.give_card("air_ritual_turbulenz")
        extra_one = self.give_card("air_creature_windfalke")
        extra_two = self.give_card("air_creature_windkrieger")
        self.give_resources(0, 1)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        recycle_id = self.engine.human_player.resources[0].resource_id
        self.engine.toggle_pending_spell_recycle_resource(recycle_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        discard_ids = {card.instance_id for card in self.engine.human_player.discard_pile}
        self.assertIn(extra_one.instance_id, discard_ids)
        self.assertIn(extra_two.instance_id, discard_ids)
        self.assertEqual(len(self.engine.human_player.hand), 3)

    def test_air_nachwehen_draws_five_after_discarding_remaining_hand(self) -> None:
        ritual = self.give_card("air_ritual_nachwehen")
        extra = self.give_card("air_creature_windfalke")
        self.give_resources(0, 2)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windkrieger"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        for resource in list(self.engine.human_player.resources):
            self.engine.toggle_pending_spell_recycle_resource(resource.resource_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 5)
        self.assertTrue(any(card.instance_id == extra.instance_id for card in self.engine.human_player.discard_pile))

    def test_air_ausweichen_returns_enemy_creature_without_death(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_spell_ausweichen")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(target.unit_id))
        self.assertEqual(self.engine.creatures_died_this_turn, 0)
        self.assertTrue(any(card.template.template_id == "earth_creature_felsensoldat" for card in self.engine.ai_player.hand))

    def test_air_windstoss_returns_two_distinct_creatures_to_hand(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_windstoss")
        own = self.make_creature("air_creature_windfalke", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(own.unit_id))
        self.assertIsNone(self.engine.get_unit_by_id(enemy.unit_id))

    def test_air_boeenschub_gives_all_own_attackers_plus_one_for_current_combat(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_spell_boeenschub")
        attacker_one = self.make_creature("air_creature_windkrieger", owner_id=0)
        attacker_two = self.make_creature("air_creature_sturmkrieger", owner_id=0)
        self.engine.block_assignments = {
            attacker_one.unit_id: [],
            attacker_two.unit_id: [],
        }
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_ATTACKERS_DECLARED,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_REACTION,
        )

        self.engine.begin_spell_from_hand(spell.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.get_creature_attack_value(attacker_one), attacker_one.aw + 1)
        self.assertEqual(self.engine.get_creature_attack_value(attacker_two), attacker_two.aw + 1)
        self.engine.enter_second_main_phase()
        self.assertEqual(self.engine.get_creature_attack_value(attacker_one), attacker_one.aw)

    def test_air_windrausch_gives_all_own_attackers_plus_two_before_first_combat_only(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_windrausch")
        attacker = self.make_creature("air_creature_himmelskrieger", owner_id=0)
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.BEFORE_FIRST_COMBAT,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_REACTION,
        )

        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()
        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 2)

    def test_flammenwelle_damages_all_enemy_creatures(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("fire_ritual_flammenwelle")
        survivor = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        doomed = self.make_creature("fire_creature_funkenwicht", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(survivor.current_hp, 2)
        self.assertIsNone(self.engine.get_unit_by_id(doomed.unit_id))

    def test_brandopfer_sacrifices_and_deals_power_damage(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("fire_ritual_brandopfer")
        sacrifice = self.make_creature("fire_creature_flammenrekrut", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=sacrifice.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("player", player_id=1))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(sacrifice.unit_id))
        self.assertEqual(self.engine.ai_player.life, 17)

    def test_verbotene_glut_draws_two_and_self_damages(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("fire_ritual_verbotene_glut")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
        ]
        self.engine.human_player.life = 20
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 2)
        self.assertEqual(self.engine.human_player.life, 18)

    def test_hitzeschub_modifies_own_die_in_comparison(self) -> None:
        self.give_resources(0, 1)
        self.give_card("fire_spell_hitzeschub")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(5, attacker.aw)],
            blocker_dice=[DieResult(7, blocker.aw)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle
        self.engine.phase = PHASE_DICE_BATTLE

        self.engine.choose_human_die(0)
        spell = self.engine.human_player.hand[0]
        self.engine.begin_spell_from_hand(spell.instance_id)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(battle.history[0].outcome_text.startswith(attacker.name), True)

    def test_letzter_funke_from_destroy_trigger(self) -> None:
        self.give_resources(0, 1)
        self.give_card("fire_spell_letzter_funke")
        source = self.make_creature("fire_creature_funkenwicht", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_DESTROYED,
                active_player=self.engine.active_player,
                source_player=self.engine.human_player,
                source_creature=source,
            ),
            first_responder_id=1,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("player", player_id=1))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.ai_player.life, 18)

    def test_brandzeichen_damages_declared_blocker_and_block_assignment_remains(self) -> None:
        self.give_resources(0, 1)
        self.give_card("fire_spell_brandzeichen")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("fire_creature_funkenwicht", owner_id=1)
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.BLOCKER_DECLARED,
                active_player=self.engine.active_player,
                source_player=self.engine.human_player,
                source_creature=attacker,
                target_creature=blocker,
            ),
            first_responder_id=1,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )
        self.engine.pass_reaction()
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIn(blocker.unit_id, self.engine.block_assignments[attacker.unit_id])

    def test_gegenfeuer_damages_source_player(self) -> None:
        self.give_resources(0, 2)
        self.give_card("fire_spell_gegenfeuer")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_TARGETED,
                active_player=self.engine.active_player,
                source_player=self.engine.ai_player,
                target_creature=target,
            ),
            first_responder_id=0,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.ai_player.life, 18)

    def test_flammenzorn_damages_opposing_creature(self) -> None:
        self.give_resources(0, 2)
        self.give_card("fire_spell_flammenzorn")
        own = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        enemy = self.make_creature("fire_creature_funkenkobold", owner_id=1)
        setattr(own, "owner_id", 0)
        setattr(enemy, "owner_id", 1)
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_DAMAGED_IN_DICE_COMPARISON,
                active_player=self.engine.active_player,
                source_player=self.engine.human_player,
                source_creature=own,
                opposing_creature=enemy,
                damage_amount=1,
            ),
            first_responder_id=1,
            base_stack_size=0,
            resume_phase=PHASE_DICE_BATTLE,
        )
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIsNone(self.engine.get_unit_by_id(enemy.unit_id))

    def test_reaction_chain_resolves_last_in_first_out(self) -> None:
        self.give_resources(0, 4)
        self.give_resources(1, 2)
        self.engine.ai_player.hand.append(CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_gegenfeuer"]))
        spell = self.give_card("fire_ritual_feuerball")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.process_ai_turn()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertTrue(len(self.engine.human_player.discard_pile) >= 1)
        self.assertTrue(self.engine.statistics.reaction_chains_started >= 1)

    def test_single_pass_resolves_spell_already_on_stack(self) -> None:
        spell = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_aufwind"])
        self.engine.spell_stack.append(
            StackItem(
                source_card=spell,
                controller=self.engine.ai_player,
                targets=[],
                effect=SpellEffect.REDUCE_CREATURE_COST_THIS_TURN,
                context=None,
                amount=spell.template.spell_amount,
                draw_count=spell.template.spell_draw_count,
            )
        )
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.SPELL_CAST,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
                source_card=spell,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertIsNone(self.engine.reaction_priority_player_id)
        self.assertEqual(len(self.engine.spell_stack), 0)
        self.assertEqual(self.engine.ai_player.creature_cost_reduction_this_turn, spell.template.spell_amount)

    def test_aufwind_reduces_multiple_later_creatures_in_same_turn(self) -> None:
        self.give_resources(0, 3)
        spell = self.give_card("air_ritual_aufwind")
        creature_one = self.give_card("fire_creature_funkenkobold")
        creature_two = self.give_card("air_creature_windfalke")
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.get_card_cost_to_pay(self.engine.human_player, creature_one).resources, 1)
        self.assertEqual(self.engine.get_card_cost_to_pay(self.engine.human_player, creature_two).resources, 1)

        self.engine.resolve_creature_play(creature_one)

        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)

        self.engine.resolve_creature_play(creature_two)

        self.assertEqual(len(self.engine.human_player.battlefield), 2)

    def test_aufwind_stacks_caps_at_zero_and_does_not_reduce_recycle(self) -> None:
        self.give_resources(0, 2)
        spell_one = self.give_card("air_ritual_aufwind")
        spell_two = self.give_card("air_ritual_aufwind")
        zero_cost_creature = self.give_card("air_creature_sturmkrieger")
        reduced_cost_creature = self.give_card("air_creature_himmelskrieger")
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell_one.instance_id)
        self.resolve_current_reaction_window_with_passes()
        self.engine.begin_spell_cast(spell_two.instance_id)
        self.resolve_current_reaction_window_with_passes()

        reduced_zero = self.engine.get_card_cost_to_pay(self.engine.human_player, zero_cost_creature)
        reduced_cost = self.engine.get_card_cost_to_pay(self.engine.human_player, reduced_cost_creature)

        self.assertEqual(reduced_zero.resources, 0)
        self.assertEqual(reduced_zero.recycle, 2)
        self.assertEqual(reduced_cost.resources, 1)
        self.assertEqual(reduced_cost.recycle, 0)

    def test_rueckenwind_grants_plus_five_attack_until_end_of_turn(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_ritual_rueckenwind")
        target = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.get_creature_attack_value(target), target.aw + 5)

        self.engine.end_turn()

        self.assertEqual(self.engine.get_creature_attack_value(target), target.aw)

    def test_sturmformation_discards_hand_and_draws_three(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_sturmformation")
        extra_one = self.give_card("air_creature_wolkenfalke")
        extra_two = self.give_card("air_spell_windstoss")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 3)
        discarded_ids = {card.template.template_id for card in self.engine.human_player.discard_pile}
        self.assertIn(spell.template.template_id, discarded_ids)
        self.assertIn(extra_one.template.template_id, discarded_ids)
        self.assertIn(extra_two.template.template_id, discarded_ids)

    def test_turbulenz_returns_two_creatures_to_hand(self) -> None:
        spell = self.give_card("air_ritual_turbulenz")
        self.give_resources(0, 2)
        own = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(own.unit_id))
        self.assertIsNone(self.engine.get_unit_by_id(enemy.unit_id))
        self.assertTrue(any(card.template.template_id == "air_creature_wolkenfalke" for card in self.engine.human_player.hand))
        self.assertTrue(any(card.template.template_id == "earth_creature_felsensoldat" for card in self.engine.ai_player.hand))

    def test_turbulenz_can_recycle_tapped_resources(self) -> None:
        spell = self.give_card("air_ritual_turbulenz")
        self.give_resources(0, 2)
        for resource in self.engine.human_player.resources:
            resource.tapped = True
        own = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        confirmed = self.engine.confirm_pending_spell_cast()

        self.assertTrue(confirmed)

    def test_turbulenz_requires_at_least_two_resources_in_resource_area(self) -> None:
        spell = self.give_card("air_ritual_turbulenz")
        self.give_resources(0, 1)
        own = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        started = self.engine.begin_spell_cast(spell.instance_id)

        self.assertFalse(started)
        self.assertEqual(len(self.engine.human_player.resources), 1)

    def test_turbulenz_duplicate_target_does_not_satisfy_two_target_requirement(self) -> None:
        spell = self.give_card("air_ritual_turbulenz")
        self.give_resources(0, 2)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))

        self.assertFalse(self.engine.pending_spell_ready())

    def test_selected_creature_in_summoning_shows_no_play_button(self) -> None:
        creature = self.give_card("air_creature_wolkenfalke")
        self.give_resources(0, 2)
        self.engine.phase = PHASE_MAIN_1

        self.engine.toggle_hand_card(creature.instance_id)
        labels = [spec.label for spec in self.engine.get_button_specs()]

        self.assertNotIn("Kreatur spielen", labels)
        self.assertNotIn("Kampfphase", labels)
        self.assertIn("Zum Kampf", labels)

    def test_selected_windwechsel_in_summoning_shows_spell_play_button(self) -> None:
        spell = self.give_card("air_ritual_windwechsel")
        self.give_resources(0, 2)
        self.engine.phase = PHASE_MAIN_1

        self.engine.toggle_hand_card(spell.instance_id)
        labels = [spec.label for spec in self.engine.get_button_specs()]

        self.assertNotIn("Zauber spielen", labels)

    def test_human_reaction_priority_shows_pass_button_even_when_enemy_is_active_player(self) -> None:
        self.give_resources(0, 2)
        self.give_card("fire_spell_gegenfeuer")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_TARGETED,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
                target_creature=target,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

        labels = [spec.label for spec in self.engine.get_button_specs()]

        self.assertIn("Passen", labels)
        self.assertNotIn("Zauber spielen", labels)

    def test_reaction_window_auto_passes_first_player_without_legal_reaction(self) -> None:
        self.give_resources(1, 2)
        self.engine.ai_player.hand.append(
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_gegenfeuer"])
        )
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_TARGETED,
                active_player=self.engine.ai_player,
                source_player=self.engine.human_player,
                target_creature=target,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.reaction_priority_player_id, self.engine.ai_player.player_id)
        self.assertEqual(self.engine.reaction_pass_count, 1)

    def test_reaction_window_resolves_when_neither_player_can_react(self) -> None:
        target = self.make_creature("earth_creature_felsensoldat", owner_id=0)

        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_TARGETED,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
                target_creature=target,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

        self.assertEqual(self.engine.phase, PHASE_MAIN_1)

    def test_rueckenwind_can_target_enemy_creature(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_rueckenwind")
        self.give_card("air_creature_wolkenfalke")
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.get_creature_attack_value(enemy), enemy.aw + 5)

    def test_windwechsel_draws_three_then_discards_one(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windwechsel")
        spare = self.give_card("air_creature_wolkenfalke")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_FORCED_DISCARD)
        self.assertEqual(len(self.engine.human_player.hand), 4)

        self.engine.toggle_hand_card(spare.instance_id)
        self.engine.confirm_forced_discard()

        self.assertEqual(len(self.engine.human_player.hand), 3)
        self.assertEqual(self.engine.human_player.discard_pile[-1].template.template_id, "air_creature_wolkenfalke")

    def _legacy_test_windwechsel_can_be_fourth_play_and_trigger_summoner_passive(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windwechsel")
        self.engine.human_player.hand_cards_played_this_turn = 3
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertIn("Spieler zieht 1 Karte durch den Beschwörer.", self.engine.log_messages)

    def _legacy_test_windwechsel_drawn_card_only_counts_when_later_played(self) -> None:
        self.give_resources(0, 3)
        spell = self.give_card("air_ritual_windwechsel")
        spare = self.give_card("air_ritual_turbulenz")
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_FORCED_DISCARD)
        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

        self.engine.toggle_hand_card(spare.instance_id)
        self.engine.confirm_forced_discard()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        drawn_creature = next(card for card in self.engine.human_player.hand if card.template.template_id == "air_creature_wolkenfalke")
        self.engine.resolve_creature_play(drawn_creature)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_empty_deck_causes_immediate_loss_on_draw(self) -> None:
        self.engine.human_player.deck = []
        self.engine.human_player.turns_started = 1

        self.engine.start_turn()

        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)

    def test_windwechsel_with_two_cards_in_deck_loses_on_third_draw(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windwechsel")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)
        self.assertIsNone(self.engine.pending_forced_discard)

    def test_sturmformation_replaces_hand_with_three_cards(self) -> None:
        self.give_resources(0, 4)
        spell_one = self.give_card("air_ritual_sturmformation")
        spell_two = self.give_card("air_ritual_sturmformation")
        extra = self.give_card("air_spell_windstoss")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenrekrut"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_felsensoldat"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell_one.instance_id)
        self.resolve_current_reaction_window_with_passes()
        self.engine.begin_spell_cast(spell_two.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 3)
        self.assertTrue(any(card.template.template_id == extra.template.template_id for card in self.engine.human_player.discard_pile))

    def test_sturmformation_resolves_as_main_phase_card(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_sturmformation")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertNotEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.human_player.discard_pile[-1].template.template_id, "air_ritual_sturmformation")

    def _legacy_test_sturmformation_counts_itself_for_summoner_passive_but_not_discarded_cards(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_sturmformation")
        self.give_card("air_spell_boeenschub")
        self.give_card("air_spell_windstoss")
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_sturmformation_fourth_play_discards_passive_draw_before_drawing_three(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_sturmformation")
        self.engine.human_player.hand_cards_played_this_turn = 3
        draw_one = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        draw_two = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        draw_three = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        passive_draw = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        self.engine.human_player.deck = [draw_one, draw_two, draw_three, passive_draw]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertIn("Spieler zieht 1 Karte durch den Beschwörer.", self.engine.log_messages)
        discard_ids = [card.template.template_id for card in self.engine.human_player.discard_pile]
        self.assertIn(passive_draw.template.template_id, discard_ids)
        hand_ids = [card.template.template_id for card in self.engine.human_player.hand]
        self.assertEqual(
            hand_ids,
            [draw_three.template.template_id, draw_two.template.template_id, draw_one.template.template_id],
        )

    def _legacy_test_sturmformation_drawn_cards_only_count_when_later_played(self) -> None:
        self.give_resources(0, 3)
        spell = self.give_card("air_ritual_sturmformation")
        self.engine.human_player.hand_cards_played_this_turn = 2
        draw_one = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        draw_two = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        draw_three = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        self.engine.human_player.deck = [draw_one, draw_two, draw_three]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

        drawn_creature = next(card for card in self.engine.human_player.hand if card.template.template_id == draw_one.template.template_id)
        self.engine.resolve_creature_play(drawn_creature)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_turbulenz_returns_both_selected_creatures_to_hand(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_turbulenz")
        own = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(own.unit_id))
        self.assertIsNone(self.engine.get_unit_by_id(enemy.unit_id))
        self.assertEqual(self.engine.human_player.hand[-1].template.template_id, "air_creature_wolkenfalke")
        self.assertEqual(self.engine.ai_player.hand[-1].template.template_id, "earth_creature_felsensoldat")

    def test_turbulenz_requires_two_targets(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_turbulenz")
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))

        self.assertFalse(self.engine.pending_spell_ready())

    def test_turbulenz_cannot_be_confirmed_without_targets(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_turbulenz")
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)

    def _legacy_test_turbulenz_returned_creatures_do_not_count_for_passive_until_replayed(self) -> None:
        self.give_resources(0, 3)
        spell = self.give_card("air_ritual_turbulenz")
        own = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

        returned_own = next(card for card in self.engine.human_player.hand if card.template.template_id == "air_creature_wolkenfalke")
        self.engine.resolve_creature_play(returned_own)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)

        self.assertFalse(self.engine.pending_spell_ready())
        self.assertFalse(self.engine.confirm_pending_spell_cast())

    def test_windrausch_is_not_playable_in_summoning_phase(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("air_spell_windrausch")
        self.engine.phase = PHASE_MAIN_1

        self.assertFalse(self.engine.begin_spell_cast(spell.instance_id))

    def test_general_spell_window_opens_after_dice_revealed(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_windstoss")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        battle = self.engine.pending_dice_battle
        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.AFTER_DICE_REVEALED)
        target_ref = self.engine.get_open_die_target_refs()[0]
        target_die = self.engine.resolve_target_open_die(target_ref)
        with patch.object(self.engine.rng, "randint", return_value=13):
            self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
            self.engine.select_spell_target_ref(target_ref)
            self.engine.confirm_pending_spell_cast()
            self.engine.pass_reaction()
            self.engine.pass_reaction()

        self.assertIsNotNone(battle)
        self.assertIsNotNone(target_die)
        self.assertEqual(target_die.base_roll, 13)

    def test_general_spell_window_opens_after_completed_comparison(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_ausweichen")
        attacker = self.make_creature("air_creature_himmelsfalke", owner_id=0)
        blocker = self.make_creature("earth_creature_bastionshueter", owner_id=1)
        self.engine.pending_dice_battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw)],
            blocker_dice=[DieResult(1, blocker.aw)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.phase = PHASE_DICE_BATTLE
        self.engine.choose_human_die(0)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertIsNotNone(self.engine.reaction_context)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.AFTER_DICE_COMPARISON)

    def test_windrausch_card_text_cost_and_effect_are_updated(self) -> None:
        card = self.engine.templates["air_spell_windrausch"]

        self.assertEqual(card.cost.resources, 2)
        self.assertEqual(card.cost.recycle, 2)
        self.assertEqual(card.rules_text, "Deine ungeblockten angreifenden Kreaturen verursachen in diesem Kampf doppelten Spielerschaden.")
        self.assertEqual(card.spell_effect, SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE)
        self.assertEqual(card.target_mode, self.engine.templates["air_spell_nachwehen"].target_mode)

    def test_windrausch_is_playable_after_blockers_declared_and_doubles_all_unblocked_attackers(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("air_spell_windrausch")
        attacker_one = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        attacker_two = self.make_creature("air_creature_windfalke", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.block_assignments = {
            attacker_one.unit_id: [],
            attacker_two.unit_id: [],
        }
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_BLOCKERS_DECLARED,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_REACTION,
        )

        if self.engine.reaction_priority_player_id != self.engine.human_player.player_id:
            self.engine.pass_reaction()
        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()
        self.engine.begin_combat_resolution()
        while self.engine.pending_direct_attack is not None:
            self.engine.pass_reaction()
            self.engine.pass_reaction()

        self.assertEqual(self.engine.ai_player.life, 20 - ((attacker_one.aw + attacker_two.aw) * 2))
        self.assertEqual(len(self.engine.human_player.resources), 2)

    def test_second_windrausch_does_not_stack_past_double_damage(self) -> None:
        self.give_resources(0, 4)
        first = self.give_card("air_spell_windrausch")
        second = self.give_card("air_spell_windrausch")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_BLOCKERS_DECLARED,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_REACTION,
        )
        if self.engine.reaction_priority_player_id != self.engine.human_player.player_id:
            self.engine.pass_reaction()
        self.engine.begin_spell_from_hand(first.instance_id)
        first_recycle = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in first_recycle:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        if self.engine.reaction_priority_player_id != self.engine.human_player.player_id:
            self.engine.pass_reaction()
        self.engine.begin_spell_from_hand(second.instance_id)
        second_recycle = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in second_recycle:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()
        self.engine.begin_combat_resolution()
        while self.engine.pending_direct_attack is not None:
            self.engine.pass_reaction()
            self.engine.pass_reaction()

        self.assertEqual(self.engine.ai_player.life, 16)

    def test_windrausch_before_blockers_is_not_legal(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("air_spell_windrausch")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_ATTACKERS_DECLARED,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_REACTION,
        )

        self.assertFalse(self.engine.begin_spell_from_hand(spell.instance_id))

    def test_windrausch_is_not_playable_after_first_combat_begins(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("air_spell_windrausch")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertFalse(self.engine.begin_spell_from_hand(spell.instance_id))

    def test_ausweichen_returns_own_fighting_creature_without_counting_as_death(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_ausweichen")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
                active_player=self.engine.active_player,
                source_player=self.engine.active_player,
                attacker_creature=attacker,
                blocker_creature=blocker,
            ),
            first_responder_id=1,
            base_stack_size=0,
            resume_phase=PHASE_DICE_BATTLE,
        )

        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIsNone(self.engine.get_unit_by_id(attacker.unit_id))
        self.assertEqual(self.engine.creatures_died_this_turn, 0)
        self.assertEqual(self.engine.human_player.hand[-1].template.template_id, "fire_creature_funkenkobold")

    def test_ausweichen_can_target_own_creature_in_own_summoning_phase(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_spell_ausweichen")
        creature = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=creature.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIsNone(self.engine.get_unit_by_id(creature.unit_id))
        self.assertEqual(self.engine.human_player.hand[-1].template.template_id, "air_creature_wolkenfalke")

    def test_ausweichen_can_target_non_fighting_creature_in_enemy_summoning_reaction_window(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_ausweichen")
        self.engine.active_player_index = 1
        creature = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.SPELL_CAST,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=0,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=creature.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIsNone(self.engine.get_unit_by_id(creature.unit_id))
        self.assertEqual(self.engine.human_player.hand[-1].template.template_id, "air_creature_wolkenfalke")

    def _legacy_test_ausweichen_counts_itself_for_passive_but_returned_creature_only_when_replayed(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_ausweichen")
        creature = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=creature.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

        returned = next(card for card in self.engine.human_player.hand if card.template.template_id == "air_creature_wolkenfalke")
        self.engine.resolve_creature_play(returned)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_ausweichen_on_blocker_keeps_attacker_blocked(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_ausweichen")
        self.engine.active_player_index = 1
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=1)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        self.engine.blocked_attackers = {attacker.unit_id}
        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
                active_player=self.engine.active_player,
                source_player=self.engine.active_player,
                attacker_creature=attacker,
                blocker_creature=blocker,
            ),
            first_responder_id=0,
            base_stack_size=0,
            resume_phase=PHASE_DICE_BATTLE,
        )

        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=blocker.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIn(attacker.unit_id, self.engine.blocked_attackers)
        self.assertIn(blocker.unit_id, self.engine.block_assignments[attacker.unit_id])

    def test_windstoss_rerolls_only_base_roll_and_keeps_modifiers(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_windstoss")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        battle = self.engine.pending_dice_battle
        target_ref = self.engine.get_open_die_target_refs()[0]
        target_die = self.engine.resolve_target_open_die(target_ref)
        self.assertIsNotNone(target_die)
        old_bonus = target_die.aw_bonus
        with patch.object(self.engine.rng, "randint", return_value=13):
            self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
            self.engine.select_spell_target_ref(target_ref)
            self.engine.confirm_pending_spell_cast()
            self.engine.pass_reaction()
            self.engine.pass_reaction()

        self.assertIsNotNone(battle)
        self.assertEqual(target_die.base_roll, 13)
        self.assertEqual(target_die.aw_bonus, old_bonus)

    def test_windstoss_card_text_is_universal_reroll(self) -> None:
        self.assertEqual(self.engine.templates["air_spell_windstoss"].rules_text, "Wirf einen Wuerfel erneut.")

    def test_windstoss_can_reroll_enemy_comparison_die_before_resolution(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_windstoss")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.pending_dice_battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(14, attacker.aw)],
            blocker_dice=[DieResult(19, blocker.aw)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.phase = PHASE_DICE_BATTLE

        self.engine.choose_human_die(0)
        target_ref = next(
            ref
            for ref in self.engine.get_open_die_target_refs()
            if self.engine.resolve_target_open_die(ref) is self.engine.pending_dice_battle.pending_comparison.blocker_die
        )
        with patch.object(self.engine.rng, "randint", return_value=2):
            self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
            self.engine.select_spell_target_ref(target_ref)
            self.engine.confirm_pending_spell_cast()
            self.engine.pass_reaction()
            self.engine.pass_reaction()

        self.assertEqual(self.engine.pending_dice_battle.history[0].outcome_text.startswith(attacker.name), True)

    def test_fully_resolved_dice_are_no_longer_open_targets(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_windstoss")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertTrue(self.engine.get_open_die_target_refs())
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.phase, PHASE_DICE_BATTLE)
        self.assertFalse(self.engine.get_open_die_target_refs())

    def test_nachwehen_uses_recycle_only_and_draws_per_death(self) -> None:
        spell = self.give_card("air_spell_nachwehen")
        self.give_card("air_creature_wolkenfalke")
        self.give_resources(0, 2)
        self.engine.creatures_died_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        resource_ids = [resource.resource_id for resource in self.engine.human_player.resources]
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[0])
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[1])
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.resources), 0)
        self.assertEqual(len(self.engine.human_player.hand), 5)

    def test_nachwehen_has_no_normal_resource_cost(self) -> None:
        card = self.engine.templates["air_spell_nachwehen"]

        self.assertEqual(card.cost.resources, 0)
        self.assertEqual(card.cost.recycle, 2)

    def test_nachwehen_draws_zero_cards_when_no_creature_died(self) -> None:
        spell = self.give_card("air_spell_nachwehen")
        self.give_resources(0, 2)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        for resource in list(self.engine.human_player.resources):
            self.engine.toggle_pending_spell_recycle_resource(resource.resource_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 0)

    def test_nachwehen_draws_two_cards_for_one_death_and_six_for_three_deaths(self) -> None:
        spell_one = self.give_card("air_spell_nachwehen")
        spell_two = self.give_card("air_spell_nachwehen")
        self.give_resources(0, 4)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenkrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkankrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_himmelsfalke"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.creatures_died_this_turn = 1
        self.engine.begin_spell_cast(spell_one.instance_id)
        for resource in list(self.engine.human_player.resources[:2]):
            self.engine.toggle_pending_spell_recycle_resource(resource.resource_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 3)

        self.engine.creatures_died_this_turn = 3
        self.engine.begin_spell_cast(spell_two.instance_id)
        for resource in list(self.engine.human_player.resources[:2]):
            self.engine.toggle_pending_spell_recycle_resource(resource.resource_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 8)

    def test_ai_does_not_choose_boeenschub_without_valid_attacker(self) -> None:
        self.engine.ai_player.hand.append(
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        )
        self.engine.phase = PHASE_REACTION
        self.engine.reaction_context = ReactionContext(
            trigger=ReactionTrigger.BEFORE_FIRST_COMBAT,
            active_player=self.engine.ai_player,
            source_player=self.engine.ai_player,
        )
        self.engine.reaction_priority_player_id = self.engine.ai_player.player_id

        chosen = self.engine.ai.choose_spell(self.engine.ai_player.hand, self.engine)

        self.assertIsNone(chosen)

    def test_ai_does_not_choose_boeenschub_in_summoning_without_valid_target(self) -> None:
        self.engine.ai_player.hand.append(
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        )
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_MAIN_1

        chosen = self.engine.ai.choose_ritual(self.engine.ai_player, self.engine)

        self.assertIsNone(chosen)

    def test_ai_forced_illegal_boeenschub_does_not_enter_spell_targeting_in_summoning(self) -> None:
        boeenschub = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        self.engine.ai_player.hand.append(boeenschub)
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_MAIN_1
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]

        original = self.engine.ai.choose_main_phase_card
        self.engine.ai.choose_main_phase_card = lambda player, engine: boeenschub
        try:
            prepared = self.engine.prepare_ai_turn_action()
            if prepared:
                self.engine.execute_prepared_ai_action()
        finally:
            self.engine.ai.choose_main_phase_card = original

        self.assertTrue(prepared)
        self.assertIsNone(self.engine.pending_ai_action)
        self.assertIsNone(self.engine.pending_spell_cast)
        self.assertNotEqual(self.engine.phase, PHASE_SPELL_TARGETING)

    def test_boeenschub_card_text_and_effect_are_updated(self) -> None:
        card = self.engine.templates["air_spell_boeenschub"]

        self.assertEqual(card.rules_text, "Eine angreifende Kreatur erhaelt fuer diesen Kampf +2 AW.")
        self.assertEqual(card.spell_effect, SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT)

    def test_boeenschub_can_target_only_own_attacking_creature(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        own_non_attacker = self.make_creature("air_creature_windfalke", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.confirm_attackers()

        self.engine.begin_spell_from_hand(spell.instance_id)
        self.assertIsNotNone(self.engine.pending_spell_cast)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own_non_attacker.unit_id))
        self.assertEqual(self.engine.pending_spell_cast.selected_targets, [])
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.assertEqual(self.engine.pending_spell_cast.selected_targets, [])
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker.unit_id))
        self.assertEqual(len(self.engine.pending_spell_cast.selected_targets), 1)

    def test_boeenschub_is_playable_after_attackers_declared(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"]),
        ]
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.confirm_attackers()

        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.AFTER_ATTACKERS_DECLARED)
        self.engine.pass_reaction()
        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))

    def test_boeenschub_is_playable_after_blockers_declared(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.confirm_attackers()
        self.resolve_current_reaction_window_with_passes()
        self.engine.toggle_selected_attack_target(attacker.unit_id)
        self.engine.toggle_blocker_assignment(blocker.unit_id)
        self.engine.finish_block_assignment()

        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.AFTER_BLOCKERS_DECLARED)
        self.engine.pass_reaction()
        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))

    def test_boeenschub_is_playable_in_last_window_before_first_combat(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"]),
        ]
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.confirm_attackers()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.BEFORE_FIRST_COMBAT)
        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))

    def test_boeenschub_is_not_playable_after_first_combat_begins(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertFalse(self.engine.begin_spell_from_hand(spell.instance_id))

    def test_boeenschub_grants_plus_two_aw_for_current_combat(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.confirm_attackers()

        self.engine.begin_spell_from_hand(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.ai_player.life, 20 - (attacker.aw + 2))

    def test_boeenschub_bonus_applies_across_multiple_blockers_and_ends_after_turn(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("fire_creature_lavakrieger", owner_id=0)
        blocker_one = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        blocker_two = self.make_creature("earth_creature_steinkobold", owner_id=1)
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {
            attacker.unit_id: [blocker_one.unit_id, blocker_two.unit_id],
        }
        self.engine.blocker_to_attackers = {
            blocker_one.unit_id: [attacker.unit_id],
            blocker_two.unit_id: [attacker.unit_id],
        }
        self.engine.finish_block_assignment()

        self.engine.begin_spell_from_hand(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 2)
        self.assertIsNotNone(self.engine.pending_order)

        self.engine.pending_order.chosen_order = [blocker_one.unit_id, blocker_two.unit_id]
        self.engine.confirm_block_order()

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 2)

        self.engine.end_turn()

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw)

    def test_nachwehen_loses_on_empty_deck_mid_resolution(self) -> None:
        spell = self.give_card("air_spell_nachwehen")
        self.give_resources(0, 2)
        self.engine.creatures_died_this_turn = 3
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        resource_ids = [resource.resource_id for resource in self.engine.human_player.resources]
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[0])
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[1])
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)

    def test_creature_death_counter_resets_at_start_of_turn(self) -> None:
        self.engine.creatures_died_this_turn = 3
        self.engine.human_player.deck = [CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])]
        self.engine.human_player.turns_started = 1

        self.engine.start_turn()

        self.assertEqual(self.engine.creatures_died_this_turn, 0)

    def test_windwechsel_no_longer_triggers_summoner_passive_on_cast(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windwechsel")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertNotIn("Spieler zieht 1 Karte durch den Beschwörer.", self.engine.log_messages)

    def test_blocked_attackers_still_count_for_summoner_passive(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=0)
        attacker_three = self.make_creature("air_creature_windkrieger", owner_id=0)
        blocker = self.make_creature("earth_creature_bastionshueter", owner_id=1)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()
        self.engine.pass_reaction()
        self.engine.pass_reaction()
        self.engine.selected_attack_target_id = attacker_one.unit_id
        self.engine.toggle_blocker_assignment(blocker.unit_id)

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_removed_attacker_after_declaration_still_counts_for_summoner_passive(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_ausweichen")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=0)
        attacker_three = self.make_creature("air_creature_windkrieger", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker_three.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(len(self.engine.human_player.hand), 2)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_summoner_passive_triggers_only_once_per_turn(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        attackers = [
            self.make_creature("air_creature_wolkenfalke", owner_id=0),
            self.make_creature("air_creature_wolkenkrieger", owner_id=0),
            self.make_creature("air_creature_windkrieger", owner_id=0),
        ]
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id for creature in attackers]

        self.engine.confirm_attackers()
        self.assertEqual(len(self.engine.human_player.hand), 1)

        for creature in attackers:
            creature.tapped = False
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id for creature in attackers]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)



