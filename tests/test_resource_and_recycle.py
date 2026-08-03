from __future__ import annotations

from core.models import CardInstance, PHASE_RECYCLE_PAYMENT, PHASE_RESOURCE, PHASE_SUMMONING
from tests.helpers import EngineTestCase


class ResourceAndRecycleTests(EngineTestCase):
    def test_mixed_cost_can_recycle_one_of_the_tapped_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_brandstifter"])
        self.engine.human_player.hand = [card]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"])
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

    def test_summoner_can_tap_to_draw_once_per_turn(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"])
        ]
        self.engine.human_player.hand = []
        self.engine.human_player.summoner_tapped = False
        self.engine.phase = PHASE_RESOURCE

        activated = self.engine.activate_summoner_draw(self.engine.human_player)

        self.assertTrue(activated)
        self.assertTrue(self.engine.human_player.summoner_tapped)
        self.assertEqual(len(self.engine.human_player.hand), 1)

        second_activation = self.engine.activate_summoner_draw(self.engine.human_player)

        self.assertFalse(second_activation)
        self.assertEqual(len(self.engine.human_player.hand), 1)
