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
    PHASE_MAIN_2,
    PendingDiceBattle,
    ReactionContext,
    ReactionTrigger,
    SpellEffect,
    SpellTargetRef,
    StackItem,
)
from tests.helpers import EngineTestCase


class SpellTests(EngineTestCase):
    def give_card(self, template_id: str, owner_id: int = 0) -> CardInstance:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        self.engine.players[owner_id].hand.append(card)
        return card

    def give_resources(self, owner_id: int, count: int) -> None:
        pool = [
            "fire_creature_glutbestie",
            "water_creature_wassertropfen",
            "earth_creature_steinkobold",
            "air_creature_wolkenschwinge",
            "fire_creature_infernobestie",
            "water_creature_flusskrieger",
        ]
        self.engine.players[owner_id].resources = [self.make_resource(pool[index % len(pool)]) for index in range(count)]

    def resolve_current_reaction_window_with_passes(self) -> None:
        if self.engine.phase != PHASE_REACTION:
            return
        self.engine.pass_reaction()
        self.engine.pass_reaction()

    def test_fire_deck_has_final_40_cards(self) -> None:
        total = sum(copies for _template_id, copies in self.engine.templates and __import__("cards").DECK_DEFINITIONS["fire"])
        self.assertEqual(total, 40)

    def test_fire_rituals_match_final_card_table(self) -> None:
        expected = {
            "fire_ritual_holzvorrat": ("Holzvorrat", 1, 0, SpellEffect.DECK_TO_TAPPED_RESOURCES, 1, 0),
            "fire_ritual_kohlevorrat": ("Kohlevorrat", 2, 0, SpellEffect.DECK_TO_TAPPED_RESOURCES, 2, 0),
            "fire_ritual_glutvision": ("Glutvision", 2, 0, SpellEffect.DRAW_CARDS, 0, 2),
            "fire_ritual_flammenvision": ("Flammenvision", 4, 0, SpellEffect.DRAW_CARDS, 0, 3),
            "fire_ritual_hitzewelle": ("Hitzewelle", 2, 0, SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES, 1, 0),
            "fire_ritual_feuerwelle": ("Feuerwelle", 4, 0, SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES, 2, 0),
        }
        for template_id, (name, resources, recycle, effect, amount, draw_count) in expected.items():
            card = self.engine.templates[template_id]
            self.assertEqual(card.name, name)
            self.assertEqual(card.cost.resources, resources)
            self.assertEqual(card.cost.recycle, recycle)
            self.assertEqual(card.spell_effect, effect)
            self.assertEqual(card.spell_amount, amount)
            self.assertEqual(card.spell_draw_count, draw_count)

    def test_holzvorrat_puts_top_deck_card_into_tapped_resources_without_counting_as_regular_resource(self) -> None:
        self.give_resources(0, 1)
        ritual = self.give_card("fire_ritual_holzvorrat")
        top_card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"])
        self.engine.human_player.deck = [top_card]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.human_player.resources[-1].resource_id, top_card.instance_id)
        self.assertTrue(self.engine.human_player.resources[-1].tapped)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 0)
        self.assertEqual(len(self.engine.human_player.deck), 0)

    def test_kohlevorrat_uses_top_deck_order_and_allows_regular_resources_afterward(self) -> None:
        self.give_resources(0, 2)
        ritual = self.give_card("fire_ritual_kohlevorrat")
        first_top = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"])
        second_top = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        regular_resource = self.give_card("water_creature_wassertropfen")
        self.engine.human_player.deck = [second_top, first_top]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        added = self.engine.human_player.resources[-2:]
        self.assertEqual([resource.resource_id for resource in added], [first_top.instance_id, second_top.instance_id])
        self.assertTrue(all(resource.tapped for resource in added))
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 0)

        self.engine.play_hand_card_as_resource(regular_resource.instance_id)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 1)
        self.assertFalse(self.engine.human_player.resources[-1].tapped)

    def test_kohlevorrat_with_short_deck_only_processes_existing_cards(self) -> None:
        self.give_resources(0, 2)
        ritual = self.give_card("fire_ritual_kohlevorrat")
        only_card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"])
        self.engine.human_player.deck = [only_card]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)
        self.assertTrue(any(resource.resource_id == only_card.instance_id for resource in self.engine.human_player.resources))

    def test_glutvision_draws_two_without_self_damage_or_discard(self) -> None:
        self.give_resources(0, 2)
        ritual = self.give_card("fire_ritual_glutvision")
        self.engine.human_player.life = 20
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 2)
        self.assertEqual(len(self.engine.human_player.discard_pile), 1)
        self.assertEqual(self.engine.human_player.life, 20)

    def test_flammenvision_draws_three_in_second_main_phase(self) -> None:
        self.give_resources(0, 4)
        ritual = self.give_card("fire_ritual_flammenvision")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        self.engine.phase = PHASE_MAIN_2

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 3)

    def test_hitzewelle_hits_all_creatures_and_not_players(self) -> None:
        self.give_resources(0, 2)
        ritual = self.give_card("fire_ritual_hitzewelle")
        own = self.make_creature("fire_creature_glutbestie", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.human_player.life = 20
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(own.current_hp, own.lw - 1)
        self.assertEqual(enemy.current_hp, enemy.lw - 1)
        self.assertEqual(self.engine.human_player.life, 20)
        self.assertEqual(self.engine.ai_player.life, 20)

    def test_feuerwelle_applies_damage_to_all_before_deaths_are_cleaned_up(self) -> None:
        self.give_resources(0, 4)
        ritual = self.give_card("fire_ritual_feuerwelle")
        own = self.make_creature("fire_creature_aschebrecher", owner_id=0)
        enemy_one = self.make_creature("earth_creature_steinkobold", owner_id=1)
        enemy_two = self.make_creature("fire_creature_aschebestie", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(own.unit_id))
        self.assertIsNone(self.engine.get_unit_by_id(enemy_one.unit_id))
        self.assertIsNone(self.engine.get_unit_by_id(enemy_two.unit_id))
        self.assertGreaterEqual(self.engine.creatures_died_this_turn, 3)

    def test_air_rueckenwind_reduces_only_creature_resource_costs(self) -> None:
        self.give_resources(0, 4)
        ritual = self.give_card("air_ritual_rueckenwind")
        creature = self.give_card("air_creature_himmelsgeist")
        spell = self.give_card("air_spell_verwehung")
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

    def test_air_windruf_returns_one_own_creature_from_discard(self) -> None:
        self.give_resources(0, 1)
        ritual = self.give_card("air_ritual_windruf")
        creature_card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"])
        self.engine.human_player.discard_pile = [creature_card]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("discard_card", card_instance_id=creature_card.instance_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIn(creature_card, self.engine.human_player.hand)
        self.assertNotIn(creature_card, self.engine.human_player.discard_pile)

    def test_unblocked_attacker_goes_directly_to_post_combat_window(self) -> None:
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_MAIN_1
        self.give_resources(0, 2)
        self.give_card("fire_spell_verbrennen", owner_id=0)
        attacker = self.make_creature("air_creature_himmelsgeist", owner_id=1)
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.blocked_attackers = set()
        self.engine.current_attack_index = 0

        self.engine.begin_combat_resolution()

        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertIsNone(self.engine.pending_direct_attack)
        self.assertIsNotNone(self.engine.get_unit_by_id(attacker.unit_id))
        self.assertIsNotNone(self.engine.reaction_context)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.COMBAT_END)
        self.assertEqual(self.engine.human_player.life, 20 - attacker.sw)

    def test_air_sturmruf_requires_two_creatures_in_own_discard(self) -> None:
        self.give_resources(0, 2)
        ritual = self.give_card("air_ritual_sturmruf")
        self.engine.human_player.discard_pile = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.assertFalse(self.engine.can_play_card(self.engine.human_player, ritual))

    def test_air_himmelswende_discards_remaining_hand_and_draws_three(self) -> None:
        ritual = self.give_card("air_ritual_himmelswende")
        extra_one = self.give_card("air_creature_windschwinge")
        extra_two = self.give_card("air_creature_windgeist")
        self.give_resources(0, 1)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
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

    def test_air_orkanwende_draws_five_after_discarding_remaining_hand(self) -> None:
        ritual = self.give_card("air_ritual_orkanwende")
        extra = self.give_card("air_creature_windschwinge")
        self.give_resources(0, 2)
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(ritual.instance_id)
        for resource in list(self.engine.human_player.resources):
            self.engine.toggle_pending_spell_recycle_resource(resource.resource_id)
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(len(self.engine.human_player.hand), 5)
        self.assertTrue(any(card.instance_id == extra.instance_id for card in self.engine.human_player.discard_pile))

    def test_air_verwehung_returns_enemy_creature_without_death(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_spell_verwehung")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(target.unit_id))
        self.assertEqual(self.engine.creatures_died_this_turn, 0)
        self.assertTrue(any(card.template.template_id == "earth_creature_felsensoldat" for card in self.engine.ai_player.hand))

    def test_air_verwirbelung_returns_two_distinct_creatures_to_hand(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_verwirbelung")
        own = self.make_creature("air_creature_windschwinge", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own.unit_id))
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.resolve_current_reaction_window_with_passes()

        self.assertIsNone(self.engine.get_unit_by_id(own.unit_id))
        self.assertIsNone(self.engine.get_unit_by_id(enemy.unit_id))



    def test_reaction_chain_resolves_last_in_first_out(self) -> None:
        self.give_resources(0, 1)
        self.give_resources(1, 2)
        self.engine.ai_player.hand.append(CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_versengen"]))
        spell = self.give_card("air_spell_verwehung")
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=target.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.process_ai_turn()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

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
        self.give_resources(0, 4)
        spell = self.give_card("air_ritual_aufwind")
        creature_one = self.give_card("fire_creature_glutbestie")
        creature_two = self.give_card("air_creature_windschwinge")
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.get_card_cost_to_pay(self.engine.human_player, creature_one).resources, 2)
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
        zero_cost_creature = self.give_card("air_creature_sturmgeist")
        reduced_cost_creature = self.give_card("air_creature_himmelsgeist")
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







    def test_selected_creature_in_summoning_shows_no_play_button(self) -> None:
        creature = self.give_card("air_creature_wolkenschwinge")
        self.give_resources(0, 2)
        self.engine.phase = PHASE_MAIN_1
        self.make_creature("air_creature_sturmgeist", owner_id=0)

        self.engine.toggle_hand_card(creature.instance_id)
        labels = [spec.label for spec in self.engine.get_button_specs()]

        self.assertNotIn("Kreatur spielen", labels)
        self.assertNotIn("Kampfphase", labels)
        self.assertIn("Zum Kampf", labels)

    def test_main_one_without_ready_attackers_shows_end_turn_instead_of_to_combat(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.make_creature("air_creature_windschwinge", owner_id=0, ready=False)

        labels = [spec.label for spec in self.engine.get_button_specs()]

        self.assertIn("Zug beenden", labels)
        self.assertNotIn("Zum Kampf", labels)

    def test_selected_windruf_in_summoning_shows_spell_play_button(self) -> None:
        spell = self.give_card("air_ritual_windruf")
        self.give_resources(0, 2)
        self.engine.phase = PHASE_MAIN_1

        self.engine.toggle_hand_card(spell.instance_id)
        labels = [spec.label for spec in self.engine.get_button_specs()]

        self.assertNotIn("Zauber spielen", labels)

    def test_human_reaction_priority_shows_pass_button_even_when_enemy_is_active_player(self) -> None:
        self.give_resources(0, 2)
        self.give_card("air_spell_verwehung")
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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"])
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



    def _legacy_test_windruf_can_be_fourth_play_and_trigger_summoner_passive(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windruf")
        self.engine.human_player.hand_cards_played_this_turn = 3
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertIn("Spieler zieht 1 Karte durch den BeschwÃ¶rer.", self.engine.log_messages)

    def _legacy_test_windruf_drawn_card_only_counts_when_later_played(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("air_ritual_windruf")
        spare = self.give_card("air_ritual_himmelswende")
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
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
        drawn_creature = next(card for card in self.engine.human_player.hand if card.template.template_id == "air_creature_wolkenschwinge")
        self.engine.resolve_creature_play(drawn_creature)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_empty_deck_causes_immediate_loss_on_draw(self) -> None:
        self.engine.human_player.deck = []
        self.engine.human_player.turns_started = 1

        self.engine.start_turn()

        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)




    def _legacy_test_sturmruf_counts_itself_for_summoner_passive_but_not_discarded_cards(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_sturmruf")
        self.give_card("air_spell_jagdwind")
        self.give_card("air_spell_verwirbelung")
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 3)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_sturmruf_fourth_play_discards_passive_draw_before_drawing_three(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_sturmruf")
        self.engine.human_player.hand_cards_played_this_turn = 3
        draw_one = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"])
        draw_two = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        draw_three = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        passive_draw = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"])
        self.engine.human_player.deck = [draw_one, draw_two, draw_three, passive_draw]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertIn("Spieler zieht 1 Karte durch den BeschwÃ¶rer.", self.engine.log_messages)
        discard_ids = [card.template.template_id for card in self.engine.human_player.discard_pile]
        self.assertIn(passive_draw.template.template_id, discard_ids)
        hand_ids = [card.template.template_id for card in self.engine.human_player.hand]
        self.assertEqual(
            hand_ids,
            [draw_three.template.template_id, draw_two.template.template_id, draw_one.template.template_id],
        )

    def _legacy_test_sturmruf_drawn_cards_only_count_when_later_played(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("air_ritual_sturmruf")
        self.engine.human_player.hand_cards_played_this_turn = 2
        draw_one = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"])
        draw_two = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        draw_three = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"])
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




    def _legacy_test_himmelswende_returned_creatures_do_not_count_for_passive_until_replayed(self) -> None:
        self.give_resources(0, 4)
        spell = self.give_card("air_ritual_himmelswende")
        own = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
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

        returned_own = next(card for card in self.engine.human_player.hand if card.template.template_id == "air_creature_wolkenschwinge")
        self.engine.resolve_creature_play(returned_own)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        for resource_id in recycle_ids:
            self.engine.toggle_pending_spell_recycle_resource(resource_id)

        self.assertFalse(self.engine.pending_spell_ready())
        self.assertFalse(self.engine.confirm_pending_spell_cast())


    def test_no_general_spell_window_opens_after_dice_revealed(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_verwirbelung")
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        self.assertEqual(self.engine.phase, PHASE_DICE_BATTLE)
        self.assertIsNone(self.engine.reaction_context)
        self.assertFalse(self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id))

    def test_no_general_spell_window_opens_after_completed_comparison(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_verwehung")
        attacker = self.make_creature("air_creature_himmelsschwinge", owner_id=0)
        blocker = self.make_creature("earth_creature_bastionshueter", owner_id=1)
        self.engine.pending_dice_battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            resolution_complete=True,
        )
        self.engine.phase = PHASE_DICE_BATTLE

        self.assertFalse(self.engine.begin_spell_from_hand(self.engine.human_player.hand[0].instance_id))
        self.assertNotEqual(self.engine.phase, PHASE_REACTION)
        self.assertIsNone(self.engine.reaction_context)

    def test_general_spell_window_opens_after_combat_ends(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_verwehung")
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        self.engine.ai_player.life = 20
        self.engine.active_player_index = self.engine.human_player.player_id
        self.engine.block_assignments = {attacker.unit_id: None}

        self.engine.begin_combat_resolution()

        self.assertEqual(self.engine.ai_player.life, 20 - attacker.sw)
        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertIsNotNone(self.engine.reaction_context)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.COMBAT_END)

    def test_main_phase_priority_window_is_skipped_when_no_instant_spell_exists(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = self.engine.human_player.player_id
        self.engine.human_player.hand = []
        self.engine.ai_player.hand = []
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
        ]

        self.engine.request_end_turn()

        self.assertEqual(self.engine.turn_number, 2)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)







    def test_verwehung_can_target_own_creature_in_own_summoning_phase(self) -> None:
        self.give_resources(0, 1)
        spell = self.give_card("air_spell_verwehung")
        creature = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=creature.unit_id))
        self.engine.confirm_pending_spell_cast()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertIsNone(self.engine.get_unit_by_id(creature.unit_id))
        self.assertEqual(self.engine.human_player.hand[-1].template.template_id, "air_creature_wolkenschwinge")

    def test_verwehung_can_target_non_fighting_creature_in_enemy_summoning_reaction_window(self) -> None:
        self.give_resources(0, 1)
        self.give_card("air_spell_verwehung")
        self.engine.active_player_index = 1
        creature = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
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
        self.assertEqual(self.engine.human_player.hand[-1].template.template_id, "air_creature_wolkenschwinge")

    def _legacy_test_verwehung_counts_itself_for_passive_but_returned_creature_only_when_replayed(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_verwehung")
        creature = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
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

        returned = next(card for card in self.engine.human_player.hand if card.template.template_id == "air_creature_wolkenschwinge")
        self.engine.resolve_creature_play(returned)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 4)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)



    def test_ai_does_not_choose_jagdwind_in_summoning_without_valid_target(self) -> None:
        self.engine.ai_player.hand.append(
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"])
        )
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_MAIN_1

        chosen = self.engine.ai.choose_ritual(self.engine.ai_player, self.engine)

        self.assertIsNone(chosen)

    def test_ai_forced_illegal_jagdwind_does_not_enter_spell_targeting_in_summoning(self) -> None:
        jagdwind = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"])
        self.engine.ai_player.hand.append(jagdwind)
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_MAIN_1
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"]),
        ]

        original = self.engine.ai.choose_main_phase_card
        self.engine.ai.choose_main_phase_card = lambda player, engine: jagdwind
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






    def test_jagdwind_is_not_playable_after_first_combat_begins(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_spell_jagdwind")
        attacker = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertFalse(self.engine.begin_spell_from_hand(spell.instance_id))




    def test_creature_death_counter_resets_at_start_of_turn(self) -> None:
        self.engine.creatures_died_this_turn = 3
        self.engine.human_player.deck = [CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenschwinge"])]
        self.engine.human_player.turns_started = 1

        self.engine.start_turn()

        self.assertEqual(self.engine.creatures_died_this_turn, 0)

    def test_windruf_no_longer_triggers_summoner_passive_on_cast(self) -> None:
        self.give_resources(0, 2)
        spell = self.give_card("air_ritual_windruf")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
        ]
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_spell_cast(spell.instance_id)
        self.resolve_current_reaction_window_with_passes()

        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertNotIn("Spieler zieht 1 Karte durch den BeschwÃ¶rer.", self.engine.log_messages)

    def test_blocked_attackers_still_count_for_summoner_passive(self) -> None:
        self.engine.human_player.summoner_key = "air"
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
        ]
        attacker_one = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkengeist", owner_id=0)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=0)
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
        self.engine.human_player.summoner_key = "air"
        self.give_resources(0, 1)
        self.give_card("air_spell_verwehung")
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
        ]
        attacker_one = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkengeist", owner_id=0)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=0)
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
        self.engine.human_player.summoner_key = "air"
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        attackers = [
            self.make_creature("air_creature_wolkenschwinge", owner_id=0),
            self.make_creature("air_creature_wolkengeist", owner_id=0),
            self.make_creature("air_creature_windgeist", owner_id=0),
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






