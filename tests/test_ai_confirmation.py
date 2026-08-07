from __future__ import annotations

from unittest.mock import patch

from core.ai.plans import TurnPlan
from core.models import CardInstance, PendingDiceBattle, PHASE_DECLARE_ATTACKERS, PHASE_DICE_BATTLE, PHASE_REACTION, PHASE_MAIN_1, PHASE_MAIN_2, PHASE_SPELL_TARGETING, ReactionContext, ReactionTrigger
from tests.helpers import EngineTestCase


class AiConfirmationTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.active_player_index = self.engine.ai_player.player_id


    def test_ai_resource_phase_waits_for_confirmation(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"]),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertTrue(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(len(self.engine.ai_player.resources), 0)
        self.assertEqual(self.engine.get_button_specs()[0].action, "confirm_ai_action")

        self.engine.execute_prepared_ai_action()

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertGreaterEqual(len(self.engine.ai_player.resources), 1)

    def test_air_planning_creates_central_turn_plan_object(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_aufwind"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
        ]

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        plan = self.engine.ai._get_active_turn_plan()

        self.assertIsNotNone(chosen)
        self.assertIsInstance(plan, TurnPlan)
        self.assertGreaterEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].card_instance_id, chosen.instance_id)

    def test_air_turn_plan_stores_combat_spell_reservation(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]
        attacker = self.make_creature("air_creature_windgeist", owner_id=1)
        attacker.tapped = False
        attacker.summoning_sick = False
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
        ]

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        plan = self.engine.ai._get_active_turn_plan()

        self.assertIsNone(chosen)
        self.assertIsNotNone(plan)
        self.assertEqual(sum(item.amount for item in plan.resource_reservations), 1)
        self.assertEqual(plan.attack.attacker_ids, (attacker.unit_id,))

    def test_air_turn_plan_is_discarded_on_wrong_turn(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
        ]

        self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        original_plan = self.engine.ai._get_active_turn_plan()
        self.assertIsNotNone(original_plan)

        self.engine.turn_number += 1
        self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(self.engine.ai._last_turn_plan)
        self.assertEqual(self.engine.ai._last_turn_plan.invalid_reason_codes, ("wrong_turn",))
        self.assertEqual(self.engine.ai._last_turn_plan.plan_id, original_plan.plan_id)
        self.assertIsNotNone(self.engine.ai._get_active_turn_plan())
        self.assertNotEqual(self.engine.ai._get_active_turn_plan().plan_id, original_plan.plan_id)

    def _legacy_test_ai_draws_from_summoner_passive_on_fourth_hand_card_play(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand_cards_played_this_turn = 2
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]

        self.engine.prepare_ai_turn_action()
        self.engine.execute_prepared_ai_action()
        self.assertNotIn("Gegner zieht 1 Karte durch den BeschwÃƒÆ’Ã‚Â¶rer.", self.engine.log_messages)
        self.engine.prepare_ai_turn_action()
        self.engine.execute_prepared_ai_action()

        self.assertIn("Gegner zieht 1 Karte durch den BeschwÃƒÆ’Ã‚Â¶rer.", self.engine.log_messages)

    def test_ai_summoning_phase_waits_for_confirmation(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
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
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = 1
        self.engine.turn_number = 2
        self.engine.ai_player.hand = []
        self.engine.ai_player.battlefield = [
            self.make_creature("air_creature_windschwinge", owner_id=1, ready=False),
        ]
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
            self.engine.execute_prepared_ai_action()
        else:
            self.assertFalse(prepared)
        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.turn_number, 3)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.active_player, self.engine.human_player)

    def test_ai_main_one_without_attackers_prepares_end_turn_not_to_combat(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = 1
        self.engine.ai_player.hand = []
        self.engine.ai_player.battlefield = [
            self.make_creature("air_creature_windschwinge", owner_id=1, ready=False),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "end_turn")

    def test_air_ai_with_zero_resources_prioritizes_playing_a_resource_before_combat(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = 1
        self.engine.ai_player.summoner_key = "air"
        self.make_creature("air_creature_sturmschwinge", owner_id=1, ready=True)
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkangeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        self.engine.ai_player.resources = []

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_resource")
        self.assertEqual(self.engine.ai_player.total_resources(), 0)
        self.assertIn(
            self.engine.pending_ai_action["card_id"],
            {card.instance_id for card in self.engine.ai_player.hand},
        )

    def test_ai_does_not_prepare_unplayable_creature_and_spam_resource_error(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = 1
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkangeist"]),
        ]
        self.engine.ai_player.resources = []
        original = self.engine.ai.choose_main_phase_card
        self.engine.ai.choose_main_phase_card = lambda player, engine: self.engine.ai_player.hand[0]
        try:
            prepared = self.engine.prepare_ai_turn_action()
        finally:
            self.engine.ai.choose_main_phase_card = original

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "end_turn")
        self.assertNotIn(
            "Nicht genuegend Ressourcen oder Recyclekosten koennen nicht bezahlt werden.",
            self.engine.log_messages,
        )

    def test_ai_uses_planned_aufwind_follow_up_in_summoning_phase(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_aufwind"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
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




    def test_ai_three_safe_attackers_trigger_summoner_passive_draw(self) -> None:
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
        ]
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=1)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=1)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=1)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertEqual(
            set(self.engine.pending_ai_action["attacker_ids"]),
            {attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id},
        )

        self.engine.execute_prepared_ai_action()

        self.assertEqual(len(self.engine.ai_player.hand), 1)
        self.assertTrue(self.engine.ai_player.summoner_passive_draw_used_this_turn)

    def test_ai_prefers_safe_third_flier_for_summoner_passive_draw(self) -> None:
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.summoner_key = "air"
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=1)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=1)
        safe_flier = self.make_creature("air_creature_orkanschwinge", owner_id=1)
        self.make_creature("earth_creature_felswesen", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertEqual(
            set(self.engine.pending_ai_action["attacker_ids"]),
            {attacker_one.unit_id, attacker_two.unit_id, safe_flier.unit_id},
        )

    def test_ai_does_not_attack_all_when_that_opens_lethal_counterattack(self) -> None:
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.life = 5
        keep_back_blocker = self.make_creature("air_creature_orkanwesen", owner_id=1)
        expendable_attacker = self.make_creature("air_creature_sturmgeist", owner_id=1)
        self.make_creature("air_creature_orkangeist", owner_id=0)
        self.make_creature("air_creature_orkangeist", owner_id=0)
        self.engine.human_player.life = 10

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertNotEqual(
            set(self.engine.pending_ai_action["attacker_ids"]),
            {keep_back_blocker.unit_id, expendable_attacker.unit_id},
        )

    def test_ai_attacks_past_tapped_flying_creature_that_cannot_block(self) -> None:
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.summoner_key = "air"
        attacker = self.make_creature("air_creature_sturmgeist", owner_id=1)
        tapped_flier = self.make_creature("air_creature_sturmschwinge", owner_id=0)
        tapped_flier.tapped = True
        tapped_flier.summoning_sick = False

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertEqual(self.engine.pending_ai_action["attacker_ids"], [attacker.unit_id])

    def test_ai_reaction_spell_waits_for_confirmation(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_wutanfall"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
        ]
        attacker = self.make_creature("fire_creature_gluthetzer", owner_id=1)
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_START,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
                attacker_creature=attacker,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.phase, PHASE_REACTION)
        self.assertTrue(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.hand), 1)

        self.engine.execute_prepared_ai_action()

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.hand), 1)
        self.assertIsNotNone(self.engine.pending_spell_cast)









    def test_ai_keeps_verwehung_with_only_healthy_target_in_summoning_phase(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        verwehung = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"])
        self.engine.ai_player.hand = [verwehung]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.make_creature("air_creature_windschwinge", owner_id=1)

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("card_id"), verwehung.instance_id)
        else:
            self.assertFalse(prepared)

    def test_ai_uses_verwehung_on_damaged_haste_creature_and_replays_it(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        verwehung = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"])
        self.engine.ai_player.hand = [verwehung]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
            self.make_resource("fire_creature_infernobestie"),
        ]
        creature = self.make_creature("air_creature_orkangeist", owner_id=1)
        creature.current_hp = 1

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], verwehung.instance_id)

        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()

        self.assertEqual(self.engine.pending_ai_action["kind"], "spell_targeting")
        selected_targets = self.engine.pending_ai_action["selected_targets"]
        self.assertEqual(len(selected_targets), 1)
        self.assertEqual(selected_targets[0].creature_id, creature.unit_id)

        self.engine.execute_prepared_ai_action()
        self.engine.pass_reaction()
        self.engine.pass_reaction()
        prepared_follow_up = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared_follow_up)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_creature")

    def test_bounce_target_ids_are_stored_in_turn_plan(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        verwehung = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"])
        self.engine.ai_player.hand = [verwehung]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
            self.make_resource("air_creature_windschwinge"),
            self.make_resource("fire_creature_infernobestie"),
        ]
        creature = self.make_creature("air_creature_orkangeist", owner_id=1)
        creature.current_hp = 1

        chosen = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        plan = self.engine.ai._get_active_turn_plan()

        self.assertIsNotNone(chosen)
        self.assertIsNotNone(plan)
        spell_step = next(step for step in plan.steps if step.card_instance_id == chosen.instance_id)
        self.assertEqual(spell_step.target_ids, (creature.unit_id,))

    def _legacy_test_ai_does_not_use_verwehung_only_for_passive(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand_cards_played_this_turn = 2
        verwehung = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"])
        self.engine.ai_player.hand = [verwehung]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.make_creature("air_creature_windgeist", owner_id=1)

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("card_id"), verwehung.instance_id)
        else:
            self.assertFalse(prepared)

























