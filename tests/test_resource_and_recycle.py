from __future__ import annotations

from core.ai.plans import TurnPlan
from core.models import CardCost, CardInstance, PHASE_DECLARE_ATTACKERS, PHASE_FORCED_DISCARD, PHASE_REACTION, PHASE_RECYCLE_PAYMENT, PHASE_MAIN_1, PlayerState, ReactionTrigger
from tests.helpers import EngineTestCase


class ResourceAndRecycleTests(EngineTestCase):
    def test_resource_logs_use_slot_counter_format(self) -> None:
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        self.engine.human_player.hand = [first, second]
        self.engine.phase = PHASE_MAIN_1

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.engine.play_hand_card_as_resource(second.instance_id)

        self.assertIn("Spieler legt Ressource 1/2 (Gluthetzer).", self.engine.log_messages)
        self.assertIn("Spieler legt Ressource 2/2 (Wassertropfen).", self.engine.log_messages)

    def test_creature_play_log_is_shortened(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [self.make_resource("fire_creature_gluthetzer")]
        self.engine.phase = PHASE_MAIN_1

        self.engine.resolve_creature_play(card, recycle_resource_ids=[self.engine.human_player.resources[0].resource_id])

        self.assertIn("Spieler spielt Windschwinge.", self.engine.log_messages)
        self.assertFalse(any("AW " in message and "Windschwinge" in message for message in self.engine.log_messages))

    def test_mixed_cost_can_recycle_one_of_the_tapped_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_infernobestie"])
        self.engine.human_player.hand = [card]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"])
        ]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
            self.make_resource("water_creature_flusskrieger"),
            self.make_resource("earth_creature_felswesen"),
        ]
        self.engine.phase = PHASE_MAIN_1

        started = self.engine.begin_recycle_payment(card.instance_id)

        self.assertTrue(started)
        self.assertEqual(self.engine.phase, PHASE_RECYCLE_PAYMENT)
        selected_resource_id = self.engine.human_player.resources[0].resource_id
        self.engine.toggle_recycle_resource_selection(selected_resource_id)
        self.engine.confirm_recycle_payment()

        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.active_player.player_id, 0)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)
        self.assertEqual(len(self.engine.human_player.resources), 5)
        self.assertEqual(sum(1 for resource in self.engine.human_player.resources if resource.tapped), 4)
        self.assertEqual(len(self.engine.human_player.deck), 1)
        self.assertTrue(self.engine.human_player.deck[0].was_recycled)
        self.assertEqual(self.engine.statistics.player_stats[0].recycled_resources, 1)
        self.assertEqual(self.engine.statistics.player_stats[0].recycled_cards_played, 1)
        self.assertEqual(self.engine.statistics.player_stats[0].max_recycle_paid_once, 1)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "recycle_reveal")

    def test_recycle_play_requires_enough_total_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_hoellenbestie"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.phase = PHASE_MAIN_1

        started = self.engine.begin_recycle_payment(card.instance_id)

        self.assertFalse(started)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)

    def test_human_can_play_two_resources_in_resource_phase(self) -> None:
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinwesen"])
        self.engine.human_player.hand = [first, second, third]
        self.engine.phase = PHASE_MAIN_1

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 1)
        self.assertEqual(len(self.engine.human_player.resources), 1)

        self.engine.play_hand_card_as_resource(second.instance_id)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 2)
        self.assertEqual(len(self.engine.human_player.resources), 2)

        self.engine.phase = PHASE_MAIN_1
        self.engine.play_hand_card_as_resource(third.instance_id)
        self.assertEqual(len(self.engine.human_player.resources), 2)

    def _legacy_test_fourth_hand_card_play_no_longer_triggers_summoner_draw(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=0)
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinwesen"])
        fourth = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"])
        self.engine.human_player.hand = [first, second, third, fourth]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_infernobestie"),
            self.make_resource("water_creature_flusskrieger"),
        ]

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.engine.play_hand_card_as_resource(second.instance_id)
        self.engine.phase = PHASE_MAIN_1
        self.engine.play_hand_card_in_summoning_zone(third.instance_id)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.engine.play_hand_card_in_summoning_zone(fourth.instance_id)

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_two_attackers_do_not_trigger_summoner_draw(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        self.engine.phase = PHASE_MAIN_1
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinwesen"])
        fourth = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"])
        self.engine.human_player.hand = [first, second, third, fourth]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_infernobestie"),
            self.make_resource("water_creature_flusskrieger"),
        ]

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.engine.play_hand_card_as_resource(second.instance_id)
        self.engine.phase = PHASE_MAIN_1
        self.engine.play_hand_card_in_summoning_zone(third.instance_id)
        self.engine.play_hand_card_in_summoning_zone(fourth.instance_id)

        play_index = self.engine.log_messages.index("Spieler spielt Windschwinge (1/1) fÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¼r 1.")
        passive_index = self.engine.log_messages.index("Spieler zieht 1 Karte durch den BeschwÃƒÆ’Ã‚Â¶rer.")

        self.assertLess(play_index, passive_index)

    def _legacy_test_resources_count_toward_summoner_passive(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        self.engine.phase = PHASE_MAIN_1
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinwesen"])
        fourth = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"])
        self.engine.human_player.hand = [first, second, third, fourth]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_infernobestie"),
            self.make_resource("water_creature_flusskrieger"),
        ]

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.engine.play_hand_card_as_resource(second.instance_id)
        self.engine.phase = PHASE_MAIN_1
        self.engine.play_hand_card_in_summoning_zone(third.instance_id)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.engine.play_hand_card_in_summoning_zone(fourth.instance_id)

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _legacy_test_summoner_passive_only_triggers_once_on_fourth_and_fifth_play(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        self.engine.phase = PHASE_MAIN_1
        self.engine.human_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinwesen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_infernobestie"),
            self.make_resource("water_creature_flusskrieger"),
            self.make_resource("earth_creature_felswesen"),
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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        self.engine.phase = PHASE_MAIN_1

        self.assertFalse(self.engine.can_activate_summoner_draw(self.engine.human_player))
        self.assertFalse(self.engine.activate_summoner_draw(self.engine.human_player))
        self.assertEqual(len(self.engine.human_player.hand), 0)

    def test_two_attackers_do_not_trigger_summoner_draw(self) -> None:
        self.engine.human_player.summoner_key = "air"
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_three_attackers_trigger_summoner_draw_before_blockers(self) -> None:
        self.engine.human_player.summoner_key = "air"
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=0)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertIn("Spieler zieht 1 Karte durch den Beschwoerer.", self.engine.log_messages)

    def test_four_attackers_trigger_summoner_draw_only_once(self) -> None:
        self.engine.human_player.summoner_key = "air"
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        attackers = [
            self.make_creature("air_creature_windschwinge", owner_id=0),
            self.make_creature("air_creature_windgeist", owner_id=0),
            self.make_creature("air_creature_windgeist", owner_id=0),
            self.make_creature("air_creature_windschwinge", owner_id=0),
        ]
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id for creature in attackers]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_summoner_passive_resets_next_own_turn(self) -> None:
        self.engine.human_player.summoner_key = "air"
        self.engine.human_player.summoner_passive_draw_used_this_turn = True
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 1
        self.engine.human_player.turns_started = 1
        self.engine.turn_number = 2

        self.engine.start_turn()

        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_opponent_attack_does_not_trigger_human_summoner_passive(self) -> None:
        self.engine.human_player.summoner_key = "air"
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        self.engine.starting_player_id = 0
        self.engine.turn_number = 1
        self.engine.active_player_index = 1
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=1)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=1)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=1)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)


    def test_orkanschwinge_is_payable_with_six_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
            self.make_resource("fire_creature_glutbrecher"),
            self.make_resource("water_creature_flusskrieger"),
        ]

        self.assertTrue(self.engine.can_play_card(self.engine.human_player, card))
        self.assertTrue(self.engine.human_player.can_pay(CardCost(resources=3, recycle=3)))

    def test_orkanschwinge_leaves_three_resources_after_recycle(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
            self.make_resource("fire_creature_glutbrecher"),
            self.make_resource("water_creature_flusskrieger"),
        ]
        self.engine.phase = PHASE_MAIN_1

        recycle_ids = [
            self.engine.human_player.resources[0].resource_id,
            self.engine.human_player.resources[1].resource_id,
            self.engine.human_player.resources[2].resource_id,
        ]
        played = self.engine.resolve_creature_play(card, recycle_resource_ids=recycle_ids)

        self.assertTrue(played)
        self.assertEqual(len(self.engine.human_player.resources), 3)

    def test_tapped_resources_can_be_used_for_recycle(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
            self.make_resource("fire_creature_glutbrecher"),
            self.make_resource("water_creature_flusskrieger"),
        ]
        self.engine.phase = PHASE_MAIN_1
        self.engine.human_player.resources[0].tapped = True
        self.engine.human_player.resources[1].tapped = True

        recycle_ids = [
            self.engine.human_player.resources[0].resource_id,
            self.engine.human_player.resources[1].resource_id,
            self.engine.human_player.resources[2].resource_id,
        ]
        played = self.engine.resolve_creature_play(card, recycle_resource_ids=recycle_ids)

        self.assertTrue(played)
        self.assertEqual(len(self.engine.human_player.resources), 3)

    def test_recycle_costs_are_not_added_to_normal_play_costs(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
            self.make_resource("fire_creature_glutbrecher"),
        ]

        self.assertTrue(self.engine.can_play_card(self.engine.human_player, card))
        self.assertFalse(self.engine.human_player.can_pay(7))

    def test_start_turn_logs_turn_begin_before_draw(self) -> None:
        self.engine.active_player_index = 1
        self.engine.starting_player_id = 0
        self.engine.ai_player.turns_started = 1
        self.engine.turn_number = 2
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"])
        ]

        self.engine.start_turn()

        turn_index = self.engine.log_messages.index("Zug 3: Gegner ist am Zug.")
        draw_index = self.engine.log_messages.index("Gegner zieht eine Karte.")
        self.assertLess(turn_index, draw_index)


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
            "fire_creature_gluthetzer",
            "water_creature_wassertropfen",
            "earth_creature_steinwesen",
            "air_creature_windschwinge",
            "fire_creature_glutbrecher",
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
            for card in self.engine.ai.turn_planner.select_air_resource_cards(
                self.engine.ai,
                self.engine.ai_player,
                self.engine,
                count,
            )
        ]

    def test_ai_chooses_zero_resources_with_functional_three_resource_hand(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_creature_windgeist",
            "air_creature_windschwinge",
            "air_spell_verwirbelung",
        ])

        self.assertEqual(self.choose_resource_ids(), [])

    def test_ai_chooses_one_resource_to_unlock_stronger_play(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_creature_windgeist",
            "air_creature_windschwinge",
            "air_spell_verwirbelung",
            "air_spell_jagdwind",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 1)

    def test_ai_chooses_two_resources_in_early_air_setup(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_orkanschwinge",
            "air_creature_windschwinge",
            "air_creature_windschwinge",
            "air_ritual_aufwind",
            "air_ritual_sturmruf",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 2)

    def test_ai_avoids_second_resource_with_small_hand(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_windschwinge",
            "air_creature_orkanschwinge",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 1)

    def test_ai_avoids_unnecessary_resources_above_air_curve(self) -> None:
        self.set_ai_resources(5)
        self.set_ai_hand([
            "air_creature_windschwinge",
            "air_creature_windschwinge",
            "air_ritual_aufwind",
        ])

        self.assertEqual(self.choose_resource_ids(), [])

    def test_ai_card_draw_bias_is_only_slightly_aggressive(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_creature_orkanschwinge",
            "air_spell_verwirbelung",
            "air_spell_verwirbelung",
            "air_creature_windschwinge",
        ])

        self.assertEqual(len(self.choose_resource_ids()), 0)

    def test_ai_prefers_fewer_sacrificed_cards_for_similar_play_value(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_creature_windgeist",
            "air_spell_verwirbelung",
            "air_spell_jagdwind",
        ])

        self.assertEqual(self.choose_resource_ids(), [])

    def test_currently_needed_creature_is_not_used_as_resource(self) -> None:
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_creature_windschwinge",
            "air_ritual_sturmruf",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_sturmruf"])

    def test_only_creature_in_hand_is_protected(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_windschwinge",
            "air_ritual_himmelswende",
            "air_spell_sturmjagd",
        ])

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_creature_windschwinge", selected)

    def test_redundant_copy_is_preferred_as_resource(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_creature_orkanschwinge",
            "air_creature_orkanschwinge",
            "air_creature_windschwinge",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_creature_orkanschwinge"])

    def test_situational_dead_spell_is_low_value(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_himmelswende",
            "air_ritual_windruf",
            "air_creature_windschwinge",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_himmelswende"])

    def test_payable_but_useless_spell_is_not_automatically_protected(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_sturmruf",
            "air_ritual_windruf",
            "air_creature_windschwinge",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_sturmruf"])

    def test_expensive_finisher_is_not_automatically_sacrificed(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_creature_orkanschwinge",
            "air_ritual_sturmruf",
            "air_spell_verwirbelung",
        ])
        self.make_creature("air_creature_windschwinge", owner_id=1)
        self.make_creature("air_creature_sturmschwinge", owner_id=1)

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_creature_orkanschwinge", selected)

    def test_orkanschwinge_can_be_used_as_resource_when_aufwind_line_is_better(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_creature_orkanschwinge",
            "air_spell_verwirbelung",
            "air_spell_verwirbelung",
            "air_creature_windschwinge",
        ])
        self.make_creature("air_creature_windschwinge", owner_id=1)
        self.make_creature("air_creature_sturmschwinge", owner_id=1)

        self.assertEqual(self.select_resource_ids(1), ["air_spell_verwirbelung"])

    def test_aufwind_is_kept_with_multiple_creatures(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_creature_windgeist",
            "air_creature_windgeist",
            "air_creature_orkanschwinge",
            "air_ritual_himmelswende",
        ])
        self.make_creature("air_creature_windschwinge", owner_id=0)
        self.make_creature("air_creature_windschwinge", owner_id=1)

        selected = self.select_resource_ids(1)

        self.assertEqual(selected, ["air_ritual_himmelswende"])

    def test_aufwind_is_low_value_without_creatures(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_ritual_windruf",
            "air_spell_verwirbelung",
        ])

        self.assertEqual(self.select_resource_ids(1), ["air_ritual_aufwind"])

    def test_ai_does_not_choose_aufwind_without_real_follow_up_advantage(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_creature_windschwinge",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_creature_windschwinge")

    def test_ai_chooses_aufwind_when_it_enables_an_extra_creature(self) -> None:
        self.set_ai_resources(4)
        self.set_ai_hand([
            "air_ritual_aufwind",
            "air_creature_windgeist",
            "air_creature_windgeist",
            "air_creature_orkanschwinge",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_ritual_aufwind")

    def test_ai_plays_one_resource_before_combat_for_haste_creature(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.resources_played_this_turn = 0
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_creature_sturmgeist",
            "air_spell_verwirbelung",
        ])

        chosen_resource = self.engine.ai.choose_resource_card_for_main_phase(
            self.engine.ai_player,
            self.engine,
            PHASE_MAIN_1,
        )

        self.assertIsNotNone(chosen_resource)
        self.assertEqual(chosen_resource.template.template_id, "air_spell_verwirbelung")

        self.engine.ai_play_resource(chosen_resource)
        chosen_card = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen_card)
        self.assertEqual(chosen_card.template.template_id, "air_creature_sturmgeist")

    def test_resource_first_plan_tracks_step_progress(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.resources_played_this_turn = 0
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_creature_sturmgeist",
            "air_spell_verwirbelung",
        ])

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_resource")

        self.engine.execute_prepared_ai_action()
        plan = self.engine.ai._get_active_turn_plan()

        self.assertIsInstance(plan, TurnPlan)
        self.assertEqual(plan.completed_step_indices, (0,))
        self.assertEqual(plan.current_step().action_type, "play_creature")

    def test_ai_plays_first_resource_even_if_himmelswende_is_legally_playable_but_bad(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_creature_windschwinge",
            "air_ritual_rueckenwind",
            "air_ritual_rueckenwind",
            "air_creature_orkangeist",
            "air_ritual_himmelswende",
        ])

        chosen_resource = self.engine.ai.choose_resource_card_for_main_phase(
            self.engine.ai_player,
            self.engine,
            PHASE_MAIN_1,
        )

        self.assertIsNotNone(chosen_resource)
        self.assertEqual(self.engine.ai_player.resources_played_this_turn, 0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertIsNotNone(self.engine.pending_ai_action)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_resource")

    def test_graveyard_target_ids_are_stored_in_turn_plan(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.set_ai_resources(1)
        self.set_ai_hand([
            "air_ritual_windruf",
        ])
        discarded = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_sturmgeist"])
        self.engine.ai_player.discard_pile = [discarded]
        spell_id = self.engine.ai_player.hand[0].instance_id
        candidate = {
            "sequence": [spell_id],
            "attacker_ids": [],
            "graveyard_target_ids": [discarded.instance_id],
            "bounce_target_ids": [],
            "himmelswende_target_ids": [],
            "reason_codes": ("valuable_graveyard_targets",),
            "reserved_resources": 0,
            "reaction_intents": (),
        }
        plan = self.engine.ai._build_air_turn_plan_from_candidate(self.engine.ai_player, self.engine, candidate)

        spell_step = next(step for step in plan.steps if step.card_instance_id == spell_id)
        self.assertEqual(spell_step.target_ids, (discarded.instance_id,))


    def test_ai_plays_dead_windruf_as_second_resource_on_opening_turn(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.set_ai_resources(1)
        self.engine.ai_player.resources_played_this_turn = 1
        self.set_ai_hand([
            "air_ritual_windruf",
            "air_creature_orkangeist",
            "air_creature_orkanschwinge",
            "air_creature_windgeist",
        ])

        chosen_resource = self.engine.ai.choose_resource_card_for_main_phase(
            self.engine.ai_player,
            self.engine,
            PHASE_MAIN_1,
        )

        self.assertIsNotNone(chosen_resource)
        self.assertEqual(chosen_resource.template.template_id, "air_ritual_windruf")










    def test_rueckenwind_is_not_chosen_when_it_only_pays_for_one_normal_creature(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_ritual_rueckenwind",
            "air_creature_windgeist",
        ])

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.template.template_id, "air_creature_windgeist")


    def test_sturmjagd_is_protected_with_likely_unblocked_flyer(self) -> None:
        self.set_ai_resources(2)
        self.set_ai_hand([
            "air_spell_sturmjagd",
            "air_ritual_himmelswende",
            "air_creature_windschwinge",
        ])
        self.make_creature("air_creature_windschwinge", owner_id=1)

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_spell_sturmjagd", selected)



    def test_two_resource_selection_re_evaluates_after_first_pick(self) -> None:
        self.set_ai_resources(0)
        self.set_ai_hand([
            "air_creature_windschwinge",
            "air_creature_windschwinge",
            "air_ritual_himmelswende",
            "air_ritual_sturmruf",
        ])

        self.assertEqual(
            self.select_resource_ids(2),
            ["air_ritual_himmelswende", "air_ritual_sturmruf"],
        )

    def test_high_stats_alone_do_not_make_creature_a_resource_candidate(self) -> None:
        self.set_ai_resources(3)
        self.set_ai_hand([
            "air_creature_windgeist",
            "air_ritual_himmelswende",
            "air_ritual_windruf",
        ])

        selected = self.select_resource_ids(1)

        self.assertNotIn("air_creature_windgeist", selected)

    def _test_two_attackers_do_not_trigger_summoner_draw(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _test_three_attackers_trigger_summoner_draw_before_blockers(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=0)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)
        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertEqual(self.engine.reaction_context.trigger, ReactionTrigger.AFTER_ATTACKERS_DECLARED)

    def _test_four_attackers_trigger_summoner_draw_only_once(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]
        attackers = [
            self.make_creature("air_creature_windschwinge", owner_id=0),
            self.make_creature("air_creature_windgeist", owner_id=0),
            self.make_creature("air_creature_windgeist", owner_id=0),
            self.make_creature("air_creature_orkanschwinge", owner_id=0),
        ]
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id for creature in attackers]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _test_summoner_passive_resets_next_own_turn(self) -> None:
        self.engine.human_player.summoner_passive_draw_used_this_turn = True
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 1
        self.engine.human_player.turns_started = 1
        self.engine.turn_number = 2

        self.engine.start_turn()

        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def _test_opponent_attack_does_not_trigger_human_summoner_passive(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"])
        ]
        self.engine.active_player_index = 1
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=1)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=1)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=1)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertFalse(self.engine.human_player.summoner_passive_draw_used_this_turn)







