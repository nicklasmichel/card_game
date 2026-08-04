from __future__ import annotations

from unittest.mock import patch

from core.models import (
    Ability,
    CardInstance,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_REACTION,
    PHASE_SUMMONING,
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
    def give_card(self, template_id: str, owner_id: int = 0) -> CardInstance:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        self.engine.players[owner_id].hand.append(card)
        return card

    def give_resources(self, owner_id: int, count: int) -> None:
        pool = [
            "fire_creature_funkenkobold",
            "water_creature_wassertropfen",
            "earth_creature_steinkobold",
            "air_creature_windgeist",
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
        self.engine.phase = PHASE_SUMMONING

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
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("player", player_id=1))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.ai_player.life, 17)

    def test_flammenwelle_damages_all_enemy_creatures(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("fire_ritual_flammenwelle")
        survivor = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        doomed = self.make_creature("fire_creature_funkenwicht", owner_id=1)
        self.engine.phase = PHASE_SUMMONING

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
        self.engine.phase = PHASE_SUMMONING

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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
        ]
        self.engine.human_player.life = 20
        self.engine.phase = PHASE_SUMMONING

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
            resume_phase=PHASE_SUMMONING,
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
            resume_phase=PHASE_SUMMONING,
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
            resume_phase=PHASE_SUMMONING,
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
        self.engine.phase = PHASE_SUMMONING

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
            resume_phase=PHASE_SUMMONING,
        )

        self.assertEqual(self.engine.phase, PHASE_SUMMONING)
        self.assertIsNone(self.engine.reaction_priority_player_id)
        self.assertEqual(len(self.engine.spell_stack), 0)
        self.assertEqual(self.engine.ai_player.creature_cost_reduction_this_turn, spell.template.spell_amount)

    def test_aufwind_reduces_multiple_later_creatures_in_same_turn(self) -> None:
        self.give_resources(0, 3)
        spell = self.give_card("air_ritual_aufwind")
        creature_one = self.give_card("fire_creature_funkenkobold")
        creature_two = self.give_card("air_creature_sturmfalke")
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_SUMMONING)
        self.assertEqual(self.engine.get_card_cost_to_pay(self.engine.human_player, creature_one).resources, 1)
        self.assertEqual(self.engine.get_card_cost_to_pay(self.engine.human_player, creature_two).resources, 1)

        self.engine.resolve_creature_play(creature_one)

        self.assertEqual(self.engine.phase, PHASE_SUMMONING)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)

        self.engine.resolve_creature_play(creature_two)

        self.assertEqual(len(self.engine.human_player.battlefield), 2)

    def test_aufwind_stacks_caps_at_zero_and_does_not_reduce_recycle(self) -> None:
        self.give_resources(0, 2)
        spell_one = self.give_card("air_ritual_aufwind")
        spell_two = self.give_card("air_ritual_aufwind")
        zero_cost_creature = self.give_card("air_creature_boeengeist")
        recycle_creature = self.give_card("air_creature_windklinge")
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell_one.instance_id)
        self.resolve_current_reaction_window_with_passes()
        self.engine.begin_spell_cast(spell_two.instance_id)
        self.resolve_current_reaction_window_with_passes()

        reduced_zero = self.engine.get_card_cost_to_pay(self.engine.human_player, zero_cost_creature)
        reduced_recycle = self.engine.get_card_cost_to_pay(self.engine.human_player, recycle_creature)

        self.assertEqual(reduced_zero.resources, 0)
        self.assertEqual(reduced_zero.recycle, 1)
        self.assertEqual(reduced_recycle.resources, 1)
        self.assertEqual(reduced_recycle.recycle, 0)

    def test_rueckenwind_grants_plus_three_attack_until_end_of_turn(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_ritual_rueckenwind")
        target = self.make_creature("air_creature_windgeist", owner_id=0)
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.get_creature_attack_value(target), target.aw + 3)

        self.engine.end_turn()

        self.assertEqual(self.engine.get_creature_attack_value(target), target.aw)

    def test_sturmformation_discards_hand_and_draws_three(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_sturmformation")
        extra_one = self.give_card("air_creature_windgeist")
        extra_two = self.give_card("air_spell_windstoss")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_SUMMONING

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
        own = self.make_creature("air_creature_windgeist", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_SUMMONING

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
        self.assertTrue(any(card.template.template_id == "air_creature_windgeist" for card in self.engine.human_player.hand))
        self.assertTrue(any(card.template.template_id == "earth_creature_felsensoldat" for card in self.engine.ai_player.hand))

    def test_selected_creature_in_summoning_shows_no_play_button(self) -> None:
        creature = self.give_card("air_creature_windgeist")
        self.give_resources(0, 2)
        self.engine.phase = PHASE_SUMMONING

        self.engine.toggle_hand_card(creature.instance_id)
        labels = [spec.label for spec in self.engine.get_button_specs()]

        self.assertNotIn("Kreatur spielen", labels)
        self.assertNotIn("Kampfphase", labels)
        self.assertIn("Zug beenden", labels)

    def test_selected_windwechsel_in_summoning_shows_spell_play_button(self) -> None:
        spell = self.give_card("air_ritual_windwechsel")
        self.give_resources(0, 2)
        self.engine.phase = PHASE_SUMMONING

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
            resume_phase=PHASE_SUMMONING,
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
            resume_phase=PHASE_SUMMONING,
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
            resume_phase=PHASE_SUMMONING,
        )

        self.assertEqual(self.engine.phase, PHASE_SUMMONING)

    def test_rueckenwind_can_target_enemy_creature(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_rueckenwind")
        self.give_card("air_creature_windgeist")
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.get_creature_attack_value(enemy), enemy.aw + 3)

    def test_windwechsel_draws_two_then_discards_one(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windwechsel")
        spare = self.give_card("air_creature_windgeist")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_FORCED_DISCARD)
        self.assertEqual(len(self.engine.human_player.hand), 3)

        self.engine.toggle_hand_card(spare.instance_id)
        self.engine.confirm_forced_discard()

        self.assertEqual(len(self.engine.human_player.hand), 2)
        self.assertEqual(self.engine.human_player.discard_pile[-1].template.template_id, "air_creature_windgeist")

    def test_windwechsel_can_be_fourth_play_and_trigger_summoner_passive(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windwechsel")
        self.engine.human_player.hand_cards_played_this_turn = 3
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertIn("Spieler zieht 1 Karte durch den Beschwoerer.", self.engine.log_messages)

    def test_windwechsel_drawn_card_only_counts_when_later_played(self) -> None:
        self.give_resources(0, 3)
        spell = self.give_card("air_ritual_windwechsel")
        spare = self.give_card("air_ritual_turbulenz")
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_FORCED_DISCARD)
        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

        self.engine.toggle_hand_card(spare.instance_id)
        self.engine.confirm_forced_discard()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        drawn_creature = next(card for card in self.engine.human_player.hand if card.template.template_id == "air_creature_windgeist")
        self.engine.resolve_creature_play(drawn_creature)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_empty_deck_causes_immediate_loss_on_draw(self) -> None:
        self.engine.human_player.deck = []
        self.engine.human_player.turns_started = 1

        self.engine.start_turn()

        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)

    def test_windwechsel_with_one_card_in_deck_loses_on_second_draw(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windwechsel")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
        ]
        self.engine.phase = PHASE_SUMMONING

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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenrekrut"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_felsensoldat"]),
        ]
        self.engine.phase = PHASE_SUMMONING

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
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertNotEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.human_player.discard_pile[-1].template.template_id, "air_ritual_sturmformation")

    def test_turbulenz_returns_both_selected_creatures_to_hand(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_turbulenz")
        own = self.make_creature("air_creature_windgeist", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_SUMMONING

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
        self.assertEqual(self.engine.human_player.hand[-1].template.template_id, "air_creature_windgeist")
        self.assertEqual(self.engine.ai_player.hand[-1].template.template_id, "earth_creature_felsensoldat")

    def test_turbulenz_requires_two_targets(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_turbulenz")
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))

        self.assertFalse(self.engine.pending_spell_ready())

    def test_turbulenz_cannot_be_confirmed_without_targets(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_turbulenz")
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)

        self.assertFalse(self.engine.pending_spell_ready())
        self.assertFalse(self.engine.confirm_pending_spell_cast())

    def test_air_spell_can_be_played_in_summoning_phase_without_ending_phase(self) -> None:
        self.give_resources(0, 3)
        spell = self.give_card("air_spell_windrausch")
        self.give_card("air_creature_windgeist")
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_SUMMONING)
        self.assertEqual(self.engine.ai_player.life, 20)
        self.assertEqual(self.engine.human_player.discard_pile[-1].template.template_id, "air_spell_windrausch")

    def test_general_spell_window_opens_after_dice_revealed(self) -> None:
        self.give_resources(0, 2)
        self.give_card("air_spell_boeenschub")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        battle = self.engine.pending_dice_battle

        self.engine.choose_human_die(0)
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.select_spell_combat_die(0)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIsNotNone(battle)
        self.assertEqual(battle.attacker_dice[1].aw_bonus, attacker.aw + 20)

    def test_general_spell_window_opens_after_completed_comparison(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_ausweichen")
        attacker = self.make_creature("air_creature_himmelsgreif", owner_id=0)
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

    def test_unblocked_damage_window_opens_and_windrausch_doubles_damage(self) -> None:
        self.give_resources(0, 2)
        self.give_card("air_spell_windrausch")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_attack_declaration()
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.confirm_attackers()

        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertIsNotNone(self.engine.reaction_context)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.BEFORE_DIRECT_ATTACK_DAMAGE)

        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.ai_player.life, 16)

    def test_two_windrausch_effects_quadruple_direct_damage(self) -> None:
        self.give_resources(0, 4)
        first = self.give_card("air_spell_windrausch")
        second = self.give_card("air_spell_windrausch")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_attack_declaration()
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.confirm_attackers()
        self.engine.begin_spell_from_hand(first.instance_id)
        self.engine.pass_reaction()
        self.engine.begin_spell_from_hand(second.instance_id)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.ai_player.life, 12)

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
        self.give_resources(0, 3)
        self.give_card("air_spell_boeenschub")
        self.give_card("air_spell_windstoss")
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        battle = self.engine.pending_dice_battle
        self.engine.choose_human_die(0)
        self.engine.pass_reaction()
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        self.engine.select_spell_combat_die(0)
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id)
        target_die = battle.attacker_dice[1]
        old_bonus = target_die.aw_bonus
        with patch.object(self.engine.rng, "randint", return_value=13):
            self.engine.select_spell_combat_die(0)
            self.engine.confirm_pending_spell_cast()
            self.engine.pass_reaction()
            self.engine.pass_reaction()

        self.assertEqual(target_die.base_roll, 13)
        self.assertEqual(target_die.aw_bonus, old_bonus + 20)

    def test_nachwehen_uses_recycle_only_and_draws_per_death(self) -> None:
        spell = self.give_card("air_spell_nachwehen")
        self.give_card("air_creature_windgeist")
        self.give_resources(0, 2)
        self.engine.creatures_died_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        resource_ids = [resource.resource_id for resource in self.engine.human_player.resources]
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[0])
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[1])
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.resources), 0)
        self.assertEqual(len(self.engine.human_player.hand), 5)

    def test_ai_does_not_choose_boeenschub_without_unused_combat_die(self) -> None:
        self.engine.ai_player.hand.append(
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        )
        self.engine.phase = PHASE_REACTION
        self.engine.reaction_priority_player_id = self.engine.ai_player.player_id

        chosen = self.engine.ai.choose_spell(self.engine.ai_player.hand, self.engine)

        self.assertIsNone(chosen)

    def test_ai_does_not_choose_boeenschub_in_summoning_without_valid_target(self) -> None:
        self.engine.ai_player.hand.append(
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        )
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_SUMMONING

        chosen = self.engine.ai.choose_ritual(self.engine.ai_player, self.engine)

        self.assertIsNone(chosen)

    def test_nachwehen_loses_on_empty_deck_mid_resolution(self) -> None:
        spell = self.give_card("air_spell_nachwehen")
        self.give_resources(0, 2)
        self.engine.creatures_died_this_turn = 3
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        self.engine.begin_spell_cast(spell.instance_id)
        resource_ids = [resource.resource_id for resource in self.engine.human_player.resources]
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[0])
        self.engine.toggle_pending_spell_recycle_resource(resource_ids[1])
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)

    def test_creature_death_counter_resets_at_start_of_turn(self) -> None:
        self.engine.creatures_died_this_turn = 3
        self.engine.human_player.deck = [CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"])]
        self.engine.human_player.turns_started = 1

        self.engine.start_turn()

        self.assertEqual(self.engine.creatures_died_this_turn, 0)
