from __future__ import annotations

from core.models import CardCost, CardInstance, PHASE_DECLARE_ATTACKERS, PHASE_FORCED_DISCARD, PHASE_REACTION, PHASE_RECYCLE_PAYMENT, PHASE_RESOURCE, PHASE_SUMMONING, PlayerState, ReactionTrigger
from tests.helpers import EngineTestCase


class ResourceAndRecycleTests(EngineTestCase):
    def test_mixed_cost_can_recycle_one_of_the_tapped_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_brandstifter"])
        self.engine.human_player.hand = [card]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        ]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        self.engine.phase = PHASE_SUMMONING

        started = self.engine.begin_recycle_payment(card.instance_id)

        self.assertTrue(started)
        self.assertEqual(self.engine.phase, PHASE_RECYCLE_PAYMENT)
        selected_resource_id = self.engine.human_player.resources[0].resource_id
        self.engine.toggle_recycle_resource_selection(selected_resource_id)
        self.engine.confirm_recycle_payment()

        self.assertEqual(self.engine.phase, PHASE_RESOURCE)
        self.assertEqual(self.engine.active_player.player_id, 1)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)
        self.assertEqual(len(self.engine.human_player.resources), 2)
        self.assertEqual(sum(1 for resource in self.engine.human_player.resources if resource.tapped), 1)
        self.assertEqual(len(self.engine.human_player.deck), 1)
        self.assertTrue(self.engine.human_player.deck[0].was_recycled)
        self.assertEqual(self.engine.statistics.player_stats[0].recycled_resources, 1)
        self.assertEqual(self.engine.statistics.player_stats[0].recycled_cards_played, 1)
        self.assertEqual(self.engine.statistics.player_stats[0].max_recycle_paid_once, 1)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "recycle_reveal")

    def test_recycle_play_requires_enough_total_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_lavakrieger"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.phase = PHASE_SUMMONING

        started = self.engine.begin_recycle_payment(card.instance_id)

        self.assertFalse(started)
        self.assertEqual(self.engine.phase, PHASE_SUMMONING)

    def test_human_can_play_two_resources_in_resource_phase(self) -> None:
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        self.engine.human_player.hand = [first, second, third]
        self.engine.phase = PHASE_RESOURCE

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.assertEqual(self.engine.phase, PHASE_RESOURCE)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 1)
        self.assertEqual(len(self.engine.human_player.resources), 1)

        self.engine.play_hand_card_as_resource(second.instance_id)
        self.assertEqual(self.engine.phase, PHASE_SUMMONING)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 2)
        self.assertEqual(len(self.engine.human_player.resources), 2)

        self.engine.phase = PHASE_RESOURCE
        self.engine.play_hand_card_as_resource(third.instance_id)
        self.assertEqual(len(self.engine.human_player.resources), 2)

    def _legacy_test_fourth_hand_card_play_no_longer_triggers_summoner_draw(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        fourth = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        self.engine.human_player.hand = [first, second, third, fourth]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_brandstifter"),
            self.make_resource("water_creature_flusskrieger"),
        ]

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.engine.play_hand_card_as_resource(second.instance_id)
        self.engine.phase = PHASE_SUMMONING
        self.engine.play_hand_card_in_summoning_zone(third.instance_id)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.engine.play_hand_card_in_summoning_zone(fourth.instance_id)

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_two_attackers_do_not_trigger_summoner_draw(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.phase = PHASE_RESOURCE
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        fourth = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        self.engine.human_player.hand = [first, second, third, fourth]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_brandstifter"),
            self.make_resource("water_creature_flusskrieger"),
        ]

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.engine.play_hand_card_as_resource(second.instance_id)
        self.engine.phase = PHASE_SUMMONING
        self.engine.play_hand_card_in_summoning_zone(third.instance_id)
        self.engine.play_hand_card_in_summoning_zone(fourth.instance_id)

        play_index = self.engine.log_messages.index("Spieler spielt Wolkenfalke (1/1) fÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¼r 1.")
        passive_index = self.engine.log_messages.index("Spieler zieht 1 Karte durch den Beschwörer.")

        self.assertLess(play_index, passive_index)

    def _legacy_test_resources_count_toward_summoner_passive(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.phase = PHASE_RESOURCE
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"])
        fourth = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        self.engine.human_player.hand = [first, second, third, fourth]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_brandstifter"),
            self.make_resource("water_creature_flusskrieger"),
        ]

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.engine.play_hand_card_as_resource(second.instance_id)
        self.engine.phase = PHASE_SUMMONING
        self.engine.play_hand_card_in_summoning_zone(third.instance_id)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.engine.play_hand_card_in_summoning_zone(fourth.instance_id)

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_summoner_passive_only_triggers_once_on_fourth_and_fifth_play(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        self.engine.phase = PHASE_RESOURCE
        self.engine.human_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windkrieger"]),
        ]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_brandstifter"),
            self.make_resource("water_creature_flusskrieger"),
            self.make_resource("earth_creature_felsensoldat"),
        ]

        self.engine.play_hand_card_as_resource(self.engine.human_player.hand[0].instance_id)
        self.engine.play_hand_card_as_resource(self.engine.human_player.hand[0].instance_id)
        self.engine.play_hand_card_in_summoning_zone(self.engine.human_player.hand[0].instance_id)
        cards_after_third = len(self.engine.human_player.hand)
        self.engine.play_hand_card_in_summoning_zone(self.engine.human_player.hand[0].instance_id)
        self.engine.play_hand_card_in_summoning_zone(self.engine.human_player.hand[0].instance_id)

        self.assertEqual(len(self.engine.human_player.hand), cards_after_third - 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_summoner_passive_resets_next_own_turn(self) -> None:
        self.engine.human_player.hand_cards_played_this_turn = 4
        self.engine.human_player.summoner_passive_draw_used_this_turn = True
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 1
        self.engine.human_player.turns_started = 1
        self.engine.turn_number = 2
        self.engine.start_turn()

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_opponent_turn_does_not_increase_human_summoner_counter(self) -> None:
        self.engine.human_player.hand_cards_played_this_turn = 2
        self.engine.active_player_index = 1

        self.engine.register_hand_card_played(self.engine.human_player)

        self.assertEqual(self.engine.human_player.hand_cards_played_this_turn, 2)

    def test_active_summoner_draw_is_no_longer_available(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.phase = PHASE_RESOURCE

        self.assertFalse(self.engine.can_activate_summoner_draw(self.engine.human_player))
        self.assertFalse(self.engine.activate_summoner_draw(self.engine.human_player))
        self.assertEqual(len(self.engine.human_player.hand), 0)

    def test_two_attackers_do_not_trigger_summoner_draw(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_three_attackers_trigger_summoner_draw_before_blockers(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=0)
        attacker_three = self.make_creature("air_creature_windkrieger", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertIn("Spieler zieht 1 Karte durch den Beschwörer.", self.engine.log_messages)

    def test_four_attackers_trigger_summoner_draw_only_once(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        attackers = [
            self.make_creature("air_creature_wolkenfalke", owner_id=0),
            self.make_creature("air_creature_wolkenkrieger", owner_id=0),
            self.make_creature("air_creature_windkrieger", owner_id=0),
            self.make_creature("air_creature_windfalke", owner_id=0),
        ]
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id for creature in attackers]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_summoner_passive_resets_next_own_turn(self) -> None:
        self.engine.human_player.summoner_passive_draw_used_this_turn = True
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 1
        self.engine.human_player.turns_started = 1
        self.engine.turn_number = 2

        self.engine.start_turn()

        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_opponent_attack_does_not_trigger_human_summoner_passive(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.active_player_index = 1
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        attacker_three = self.make_creature("air_creature_windkrieger", owner_id=1)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_spell_can_be_played_via_summoning_zone_drop(self) -> None:
        spell = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_windwechsel"])
        spare = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        self.engine.human_player.hand = [spell, spare]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        self.engine.play_hand_card_in_summoning_zone(spell.instance_id)
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        self.assertEqual(self.engine.phase, PHASE_FORCED_DISCARD)

    def test_orkanfuerst_is_payable_with_five_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanfuerst"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_flammenrekrut"),
        ]

        self.assertTrue(self.engine.can_play_card(self.engine.human_player, card))
        self.assertTrue(self.engine.human_player.can_pay(CardCost(resources=5, recycle=2)))

    def test_orkanfuerst_leaves_three_resources_after_recycle(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanfuerst"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_flammenrekrut"),
        ]
        self.engine.phase = PHASE_SUMMONING

        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        self.engine.resolve_creature_play(card, recycle_resource_ids=recycle_ids)

        self.assertEqual(len(self.engine.human_player.resources), 3)

    def test_tapped_resources_can_be_used_for_recycle(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanfuerst"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_flammenrekrut"),
            self.make_resource("water_creature_flusskrieger"),
        ]
        self.engine.phase = PHASE_SUMMONING
        self.engine.human_player.resources[0].tapped = True
        self.engine.human_player.resources[1].tapped = True

        recycle_ids = [resource.resource_id for resource in self.engine.human_player.resources[:2]]
        played = self.engine.resolve_creature_play(card, recycle_resource_ids=recycle_ids)

        self.assertTrue(played)
        self.assertEqual(len(self.engine.human_player.resources), 4)

    def test_recycle_costs_are_not_added_to_normal_play_costs(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanfuerst"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_flammenrekrut"),
        ]

        self.assertTrue(self.engine.can_play_card(self.engine.human_player, card))
        self.assertFalse(self.engine.human_player.can_pay(7))


class AiResourceStrategyTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.players = [
            PlayerState(0, "Spieler", True),
            PlayerState(1, "Gegner", False),
        ]
        self.engine.active_player_index = 1
        self.engine.reset_combat_state()
        self.engine.log_messages.clear()
        self.engine.ai_player.summoner_key = "air"

    def set_ai_resources(self, count: int) -> None:
        pool = [
            "fire_creature_funkenkobold",
            "water_creature_wassertropfen",
            "earth_creature_steinkobold",
            "air_creature_wolkenfalke",
            "fire_creature_flammenrekrut",
        ]
        self.engine.ai_player.resources = [self.make_resource(pool[index % len(pool)]) for index in range(count)]

    def set_ai_hand(self, template_ids: list[str]) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
            for template_id in template_ids
        ]

    def choose_resource_ids(self) -> list[str]:
        return [card.template.template_id for card in self.engine.ai.choose_resource_cards_to_play(self.engine.ai_player, self.engine)]

    def select_resource_ids(self, count: int) -> list[str]:
        return [
            card.template.template_id
            for card in self.engine.ai._select_air_resource_cards(self.engine.ai_player, self.engine, count)
        ]

    def test_ai_chooses_zero_resources_with_functional_three_resource_hand(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_creature_windkrieger",
            "air_creature_wolkenfalke",
            "air_spell_windstoss",
        ])

        self.assertEqual(self.choose_resource_ids(), [])

    def test_ai_chooses_one_resource_to_unlock_stronger_play(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_creature_windkrieger",
            "air_creature_wolkenfalke",
            "air_spell_windstoss",
            "air_spell_boeenschub",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 1)

    def test_ai_chooses_two_resources_in_early_air_setup(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_orkanfuerst",
            "air_creature_wolkenfalke",
            "air_creature_wolkenfalke",
            "air_ritual_aufwind",
            "air_ritual_sturmformation",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 2)

    def test_ai_avoids_second_resource_with_small_hand(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_wolkenfalke",
            "air_creature_orkanfuerst",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 1)

    def test_ai_avoids_unnecessary_resources_above_air_curve(self) -> None:
        self.set_ai_resources(5)
        self.set_ai_hand([
            "air_creature_wolkenfalke",
            "air_creature_wolkenfalke",
            "air_ritual_aufwind",
        ])

        self.assertEqual(self.choose_resource_ids(), [])

    def test_ai_card_draw_bias_is_only_slightly_aggressive(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_creature_orkanfuerst",
            "air_spell_windstoss",
            "air_spell_windstoss",
            "air_creature_wolkenfalke",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 1)

    def test_ai_prefers_fewer_sacrificed_cards_for_similar_play_value(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_creature_windkrieger",
            "air_spell_windstoss",
            "air_spell_boeenschub",
        ])

        self.assertEqual(self.choose_resource_ids(), [])

    def test_currently_needed_creature_is_not_used_as_resource(self) -> None:
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_creature_wolkenfalke",
            "air_ritual_sturmformation",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_sturmformation"])

    def test_only_creature_in_hand_is_protected(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_wolkenfalke",
            "air_ritual_turbulenz",
            "air_spell_windrausch",
        ])

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_creature_wolkenfalke", selected)

    def test_redundant_copy_is_preferred_as_resource(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_creature_orkanfuerst",
            "air_creature_orkanfuerst",
            "air_creature_wolkenfalke",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_creature_orkanfuerst"])

    def test_situational_dead_spell_is_low_value(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_turbulenz",
            "air_ritual_windwechsel",
            "air_creature_wolkenfalke",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_turbulenz"])

    def test_payable_but_useless_spell_is_not_automatically_protected(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_sturmformation",
            "air_ritual_windwechsel",
            "air_creature_wolkenfalke",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_sturmformation"])

    def test_expensive_finisher_is_not_automatically_sacrificed(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_creature_orkanfuerst",
            "air_ritual_sturmformation",
            "air_spell_windstoss",
        ])
        self.make_creature("air_creature_windfalke", owner_id=1)
        self.make_creature("air_creature_sturmfalke", owner_id=1)

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_creature_orkanfuerst", selected)

    def test_orkanfuerst_is_protected_when_fifth_resource_sets_up_attack(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_creature_orkanfuerst",
            "air_spell_windstoss",
            "air_spell_windstoss",
            "air_creature_wolkenfalke",
        ])
        self.make_creature("air_creature_windfalke", owner_id=1)
        self.make_creature("air_creature_sturmfalke", owner_id=1)

        self.assertEqual(self.select_resource_ids(1), ["air_spell_windstoss"])

    def test_aufwind_is_protected_with_multiple_creatures(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_creature_wolkenkrieger",
            "air_creature_windkrieger",
            "air_creature_himmelsfalke",
            "air_ritual_turbulenz",
        ])
        self.make_creature("air_creature_windfalke", owner_id=0)
        self.make_creature("air_creature_wolkenfalke", owner_id=1)

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_ritual_aufwind", selected)

    def test_aufwind_is_low_value_without_creatures(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_ritual_windwechsel",
            "air_spell_windstoss",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_aufwind"])

    def test_ai_does_not_choose_aufwind_without_real_follow_up_advantage(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_creature_wolkenfalke",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_creature_wolkenfalke")

    def test_ai_chooses_aufwind_when_it_enables_an_extra_creature(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_creature_wolkenkrieger",
            "air_creature_windkrieger",
            "air_creature_himmelsfalke",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_ritual_aufwind")

    def test_windwechsel_is_not_automatic_at_two_resources(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_windwechsel",
            "air_creature_wolkenfalke",
            "air_creature_wolkenkrieger",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertNotEqual(chosen.template.template_id, "air_ritual_windwechsel")

    def test_windwechsel_is_chosen_to_improve_multiple_dead_cards(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_windwechsel",
            "air_ritual_turbulenz",
            "air_spell_nachwehen",
            "air_creature_orkanfuerst",
        ])
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenkrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windstoss"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windkrieger"]),
        ]

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_ritual_windwechsel")

    def test_windwechsel_is_low_value_with_already_strong_hand(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_windwechsel",
            "air_creature_wolkenkrieger",
            "air_creature_wolkenfalke",
            "air_spell_windstoss",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertNotEqual(chosen.template.template_id, "air_ritual_windwechsel")

    def test_windwechsel_decision_does_not_depend_on_hidden_topdeck_order(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_windwechsel",
            "air_ritual_turbulenz",
            "air_spell_nachwehen",
            "air_creature_orkanfuerst",
        ])
        deck_templates = [
            "air_creature_wolkenfalke",
            "air_creature_wolkenkrieger",
            "air_spell_windstoss",
            "air_creature_windkrieger",
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
            for template_id in deck_templates
        ]
        first_choice = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
            for template_id in reversed(deck_templates)
        ]
        second_choice = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(first_choice)
        self.assertIsNotNone(second_choice)
        self.assertEqual(first_choice.template.template_id, second_choice.template.template_id)

    def test_windwechsel_discard_prefers_redundant_or_dead_card(self) -> None:
        self.set_ai_resources(1)
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windkrieger"]),
        ]

        discarded = self.engine.choose_cards_to_discard_for_ai(self.engine.ai_player, 1)

        self.assertEqual(len(discarded), 1)
        self.assertIn(discarded[0].template.template_id, {"air_ritual_turbulenz", "air_creature_wolkenfalke"})

    def test_rueckenwind_is_not_chosen_without_attackers(self) -> None:
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_ritual_rueckenwind",
            "air_ritual_windwechsel",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNone(chosen)

    def test_rueckenwind_is_chosen_for_clear_unblocked_flying_attack(self) -> None:
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_ritual_rueckenwind",
        ])
        flyer = self.make_creature("air_creature_windfalke", owner_id=1)

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        target = self.engine.ai.choose_spell_target_ref(self.engine.ai_player, self.engine, chosen, type("Pending", (), {"selected_targets": [], "selected_sacrifice_creature_id": None})())

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_ritual_rueckenwind")
        self.assertIsNotNone(target)
        self.assertEqual(target.creature_id, flyer.unit_id)

    def test_rueckenwind_is_not_chosen_when_same_attack_is_already_good_enough(self) -> None:
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_ritual_rueckenwind",
            "air_ritual_windwechsel",
        ])
        self.make_creature("air_creature_himmelsfalke", owner_id=1)
        self.engine.human_player.life = 1

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNone(chosen)

    def test_rueckenwind_target_is_not_just_highest_attack(self) -> None:
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_ritual_rueckenwind",
        ])
        high_aw_ground = self.make_creature("air_creature_himmelskrieger", owner_id=1)
        flyer = self.make_creature("air_creature_windfalke", owner_id=1)
        self.make_creature("earth_creature_felsensoldat", owner_id=0)

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        target = self.engine.ai.choose_spell_target_ref(self.engine.ai_player, self.engine, chosen, type("Pending", (), {"selected_targets": [], "selected_sacrifice_creature_id": None})())

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_ritual_rueckenwind")
        self.assertNotEqual(high_aw_ground.unit_id, target.creature_id)
        self.assertEqual(flyer.unit_id, target.creature_id)

    def test_sturmformation_is_low_value_without_attackers(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_sturmformation",
            "air_ritual_windwechsel",
            "air_creature_orkanfuerst",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_sturmformation"])

    def test_windrausch_is_protected_with_likely_unblocked_flyer(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_spell_windrausch",
            "air_ritual_turbulenz",
            "air_creature_wolkenfalke",
        ])
        self.make_creature("air_creature_windfalke", owner_id=1)

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_spell_windrausch", selected)

    def test_turbulenz_is_low_value_without_targets(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_turbulenz",
            "air_creature_wolkenfalke",
            "air_ritual_windwechsel",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_turbulenz"])

    def test_nachwehen_values_deaths_and_recycle(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_spell_nachwehen",
            "air_ritual_turbulenz",
            "air_creature_wolkenfalke",
        ])
        self.engine.creatures_died_this_turn = 2

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_spell_nachwehen", selected)

    def test_two_resource_selection_re_evaluates_after_first_pick(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_wolkenfalke",
            "air_creature_wolkenfalke",
            "air_ritual_turbulenz",
            "air_ritual_sturmformation",
        ])

        self.assertEqual(
            self.select_resource_ids(2),
            ["air_ritual_turbulenz", "air_ritual_sturmformation"],
        )

    def test_high_stats_alone_do_not_make_creature_a_resource_candidate(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_creature_windkrieger",
            "air_ritual_turbulenz",
            "air_ritual_windwechsel",
        ])

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_creature_windkrieger", selected)

    def _test_two_attackers_do_not_trigger_summoner_draw(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _test_three_attackers_trigger_summoner_draw_before_blockers(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=0)
        attacker_three = self.make_creature("air_creature_windkrieger", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.AFTER_ATTACKERS_DECLARED)

    def _test_four_attackers_trigger_summoner_draw_only_once(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        attackers = [
            self.make_creature("air_creature_wolkenfalke", owner_id=0),
            self.make_creature("air_creature_wolkenkrieger", owner_id=0),
            self.make_creature("air_creature_windkrieger", owner_id=0),
            self.make_creature("air_creature_himmelsfalke", owner_id=0),
        ]
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id for creature in attackers]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _test_summoner_passive_resets_next_own_turn(self) -> None:
        self.engine.human_player.summoner_passive_draw_used_this_turn = True
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 1
        self.engine.human_player.turns_started = 1
        self.engine.turn_number = 2

        self.engine.start_turn()

        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _test_opponent_attack_does_not_trigger_human_summoner_passive(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.active_player_index = 1
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        attacker_three = self.make_creature("air_creature_windkrieger", owner_id=1)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

