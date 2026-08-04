from __future__ import annotations

from core.models import CardInstance, PHASE_REACTION, PHASE_RESOURCE, PHASE_SUMMONING, ReactionContext, ReactionTrigger
from tests.helpers import EngineTestCase


class AiConfirmationTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.active_player_index = self.engine.ai_player.player_id

    def test_ai_resource_phase_waits_for_confirmation(self) -> None:
        self.engine.phase = PHASE_RESOURCE
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_sturmfuerst"]),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertTrue(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.phase, PHASE_RESOURCE)
        self.assertEqual(len(self.engine.ai_player.resources), 0)
        self.assertEqual(self.engine.get_button_specs()[0].action, "confirm_ai_action")

        self.engine.execute_prepared_ai_action()

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.phase, PHASE_SUMMONING)
        self.assertGreaterEqual(len(self.engine.ai_player.resources), 1)

    def test_ai_draws_from_summoner_passive_on_fourth_hand_card_play(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand_cards_played_this_turn = 2
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windhuscher"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]

        self.engine.prepare_ai_turn_action()
        self.engine.execute_prepared_ai_action()
        self.assertNotIn("Gegner zieht 1 Karte durch den Beschwoerer.", self.engine.log_messages)
        self.engine.prepare_ai_turn_action()
        self.engine.execute_prepared_ai_action()

        self.assertIn("Gegner zieht 1 Karte durch den Beschwoerer.", self.engine.log_messages)

    def test_ai_summoning_phase_waits_for_confirmation(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertTrue(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.battlefield), 0)
        self.assertEqual(len(self.engine.ai_player.hand), 1)

        self.engine.execute_prepared_ai_action()

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.battlefield), 1)
        self.assertEqual(len(self.engine.ai_player.hand), 0)

    def test_ai_summoning_without_attackers_skips_combat_confirmation(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.turn_number = 2
        self.engine.ai_player.hand = []
        self.engine.ai_player.battlefield = [
            self.make_creature("air_creature_boeenreiter", owner_id=1, ready=False),
        ]
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertFalse(prepared)
        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.turn_number, 3)
        self.assertEqual(self.engine.phase, PHASE_RESOURCE)
        self.assertEqual(self.engine.active_player, self.engine.human_player)

    def test_ai_uses_planned_aufwind_follow_up_in_summoning_phase(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_aufwind"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windhuscher"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_himmelsspaeher"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_himmelsgreif"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_windgeist"),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["card_id"], self.engine.ai_player.hand[0].instance_id)

        self.engine.execute_prepared_ai_action()
        self.engine.pass_reaction()
        self.engine.pass_reaction()

        prepared_follow_up = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared_follow_up)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_creature")

    def test_ai_uses_planned_rueckenwind_target_and_attacker(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_rueckenwind"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
        ]
        flyer = self.make_creature("air_creature_sturmfalke", owner_id=1)
        self.make_creature("earth_creature_felsensoldat", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")

        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()

        self.assertEqual(self.engine.pending_ai_action["kind"], "spell_targeting")
        selected_targets = self.engine.pending_ai_action["selected_targets"]
        self.assertEqual(len(selected_targets), 1)
        self.assertEqual(selected_targets[0].creature_id, flyer.unit_id)

        self.engine.execute_prepared_ai_action()
        self.engine.pass_reaction()
        self.engine.pass_reaction()
        self.engine.begin_attack_declaration()
        prepared_attack = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared_attack)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertEqual(self.engine.pending_ai_action["attacker_ids"], [flyer.unit_id])

    def test_ai_reaction_spell_waits_for_confirmation(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_gegenfeuer"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_TARGETED,
                active_player=self.engine.ai_player,
                source_player=self.engine.human_player,
                target_creature=target,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertTrue(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.hand), 1)

        self.engine.execute_prepared_ai_action()

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.hand), 0)
