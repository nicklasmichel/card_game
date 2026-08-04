from __future__ import annotations

from unittest.mock import patch

from core.models import CardInstance, DieResult, PendingComparison, PendingDiceBattle, PHASE_DECLARE_ATTACKERS, PHASE_DICE_BATTLE, PHASE_REACTION, PHASE_RESOURCE, PHASE_SUMMONING, ReactionContext, ReactionTrigger
from tests.helpers import EngineTestCase


class AiConfirmationTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.active_player_index = self.engine.ai_player.player_id

    def _begin_ai_windstoss_window(self, *, own_roll: int, enemy_roll: int) -> tuple:
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=1,
            blocker_owner=0,
            attacker_dice=[DieResult(own_roll, attacker.aw)],
            blocker_dice=[DieResult(enemy_roll, blocker.aw)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        comparison = PendingComparison(
            attacker_die=battle.attacker_dice[0],
            blocker_die=battle.blocker_dice[0],
            human_is_attacker=False,
        )
        self.engine.pending_dice_battle = battle
        self.engine.phase = PHASE_DICE_BATTLE
        battle.pending_comparison = comparison
        self.engine.set_open_die_targets(
            [
                {
                    "die": comparison.attacker_die,
                    "player_id": 1,
                    "die_role": "attacker",
                    "die_index": 0,
                    "source_creature_id": attacker.unit_id,
                    "is_valid": lambda: self.engine.pending_dice_battle is battle and battle.pending_comparison is comparison,
                },
                {
                    "die": comparison.blocker_die,
                    "player_id": 0,
                    "die_role": "blocker",
                    "die_index": 0,
                    "source_creature_id": blocker.unit_id,
                    "is_valid": lambda: self.engine.pending_dice_battle is battle and battle.pending_comparison is comparison,
                },
            ]
        )
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.BEFORE_DICE_COMPARISON,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
                attacker_creature=attacker,
                blocker_creature=blocker,
                attacker_die=comparison.attacker_die,
                blocker_die=comparison.blocker_die,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_DICE_BATTLE,
        )
        return attacker, blocker, comparison

    def test_ai_resource_phase_waits_for_confirmation(self) -> None:
        self.engine.phase = PHASE_RESOURCE
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanfuerst"]),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
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

    def _legacy_test_ai_draws_from_summoner_passive_on_fourth_hand_card_play(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand_cards_played_this_turn = 2
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenkrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]

        self.engine.prepare_ai_turn_action()
        self.engine.execute_prepared_ai_action()
        self.assertNotIn("Gegner zieht 1 Karte durch den Beschwörer.", self.engine.log_messages)
        self.engine.prepare_ai_turn_action()
        self.engine.execute_prepared_ai_action()

        self.assertIn("Gegner zieht 1 Karte durch den Beschwörer.", self.engine.log_messages)

    def test_ai_summoning_phase_waits_for_confirmation(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
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
            self.make_creature("air_creature_windfalke", owner_id=1, ready=False),
        ]
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
            self.engine.execute_prepared_ai_action()
        else:
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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenkrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windkrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_himmelsfalke"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
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
        flyer = self.make_creature("air_creature_windfalke", owner_id=1)
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

    def test_ai_three_safe_attackers_trigger_summoner_passive_draw(self) -> None:
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        attacker_three = self.make_creature("air_creature_windkrieger", owner_id=1)

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
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        safe_flier = self.make_creature("air_creature_himmelsfalke", owner_id=1)
        self.make_creature("earth_creature_felsensoldat", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertEqual(
            set(self.engine.pending_ai_action["attacker_ids"]),
            {attacker_one.unit_id, attacker_two.unit_id, safe_flier.unit_id},
        )

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

    def test_ai_rerolls_its_own_very_low_decisive_die_with_windstoss(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windstoss"]),
        ]
        self.engine.ai_player.resources = [self.make_resource("air_creature_wolkenfalke")]
        _attacker, _blocker, comparison = self._begin_ai_windstoss_window(own_roll=2, enemy_roll=11)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()
        selected = self.engine.pending_ai_action["selected_targets"][0]

        self.assertIs(self.engine.resolve_target_open_die(selected), comparison.attacker_die)

    def test_ai_rerolls_high_enemy_die_with_windstoss(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windstoss"]),
        ]
        self.engine.ai_player.resources = [self.make_resource("air_creature_wolkenfalke")]
        _attacker, _blocker, comparison = self._begin_ai_windstoss_window(own_roll=14, enemy_roll=19)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()
        selected = self.engine.pending_ai_action["selected_targets"][0]

        self.assertIs(self.engine.resolve_target_open_die(selected), comparison.blocker_die)

    def test_ai_keeps_windstoss_when_comparison_is_already_good(self) -> None:
        windstoss = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windstoss"])
        self.engine.ai_player.hand = [windstoss]
        self.engine.ai_player.resources = [self.make_resource("air_creature_wolkenfalke")]
        self._begin_ai_windstoss_window(own_roll=18, enemy_roll=4)

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("card_id"), windstoss.instance_id)
        else:
            self.assertFalse(prepared)

    def test_ai_does_not_play_boeenschub_without_attackers(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.BEFORE_FIRST_COMBAT,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
        else:
            self.assertFalse(prepared)

    def test_ai_boeenschub_waits_until_blockers_are_known_when_blocks_are_possible(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        self.make_creature("earth_creature_felsensoldat", owner_id=0)
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.phase = PHASE_REACTION
        self.engine.reaction_priority_player_id = self.engine.ai_player.player_id
        self.engine.reaction_context = ReactionContext(
            trigger=ReactionTrigger.AFTER_ATTACKERS_DECLARED,
            active_player=self.engine.ai_player,
            source_player=self.engine.ai_player,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertNotEqual(self.engine.pending_ai_action["kind"], "cast_spell")

    def test_ai_boeenschub_prioritizes_lethal_unblocked_damage(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        self.engine.human_player.life = attacker.aw + 2
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.phase = PHASE_REACTION
        self.engine.reaction_priority_player_id = self.engine.ai_player.player_id
        self.engine.reaction_context = ReactionContext(
            trigger=ReactionTrigger.BEFORE_FIRST_COMBAT,
            active_player=self.engine.ai_player,
            source_player=self.engine.ai_player,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")

        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()

        self.assertEqual(self.engine.pending_ai_action["kind"], "spell_targeting")
        self.assertEqual(self.engine.pending_ai_action["selected_targets"][0].creature_id, attacker.unit_id)

    def test_ai_boeenschub_keeps_card_when_attack_is_already_lethal_without_it(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        attacker = self.make_creature("air_creature_himmelsfalke", owner_id=1)
        self.engine.human_player.life = attacker.aw
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.phase = PHASE_REACTION
        self.engine.reaction_priority_player_id = self.engine.ai_player.player_id
        self.engine.reaction_context = ReactionContext(
            trigger=ReactionTrigger.BEFORE_FIRST_COMBAT,
            active_player=self.engine.ai_player,
            source_player=self.engine.ai_player,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertNotEqual(self.engine.pending_ai_action["kind"], "cast_spell")

    def test_ai_boeenschub_targets_attacker_with_higher_actual_gain(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        low_gain = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        high_gain = self.make_creature("air_creature_orkanreiter", owner_id=1)
        self.engine.human_player.life = high_gain.aw + 2
        self.engine.block_assignments = {
            low_gain.unit_id: [],
            high_gain.unit_id: [],
        }
        self.engine.phase = PHASE_REACTION
        self.engine.reaction_priority_player_id = self.engine.ai_player.player_id
        self.engine.reaction_context = ReactionContext(
            trigger=ReactionTrigger.BEFORE_FIRST_COMBAT,
            active_player=self.engine.ai_player,
            source_player=self.engine.ai_player,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()

        self.assertEqual(self.engine.pending_ai_action["selected_targets"][0].creature_id, high_gain.unit_id)

    def test_ai_keeps_ausweichen_with_only_healthy_target_in_summoning_phase(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        ausweichen = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_ausweichen"])
        self.engine.ai_player.hand = [ausweichen]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.make_creature("air_creature_wolkenfalke", owner_id=1)

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("card_id"), ausweichen.instance_id)
        else:
            self.assertFalse(prepared)

    def test_ai_uses_ausweichen_on_damaged_haste_creature_and_replays_it(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        ausweichen = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_ausweichen"])
        self.engine.ai_player.hand = [ausweichen]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_brandstifter"),
        ]
        creature = self.make_creature("air_creature_orkanreiter", owner_id=1)
        creature.current_hp = 1

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], ausweichen.instance_id)

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

    def _legacy_test_ai_does_not_use_ausweichen_only_for_passive(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand_cards_played_this_turn = 2
        ausweichen = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_ausweichen"])
        self.engine.ai_player.hand = [ausweichen]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.make_creature("air_creature_wolkenkrieger", owner_id=1)

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("card_id"), ausweichen.instance_id)
        else:
            self.assertFalse(prepared)

    def test_ai_values_sturmformation_as_last_hand_card(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        sturmformation = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_sturmformation"])
        self.engine.ai_player.hand = [sturmformation]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], sturmformation.instance_id)

    def test_ai_turbulenz_prefers_two_enemy_blockers_for_attack(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        turbulenz = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"])
        self.engine.ai_player.hand = [turbulenz]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_brandstifter"),
        ]
        self.engine.ai_player.resources[0].tapped = True
        self.engine.ai_player.resources[1].tapped = True
        attacker_one = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        attacker_two = self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        blocker_one = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        blocker_two = self.make_creature("earth_creature_erdgolem", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], turbulenz.instance_id)

    def test_ai_does_not_play_windrausch_without_unblocked_attackers(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windrausch"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_BLOCKERS_DECLARED,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
        else:
            self.assertFalse(prepared)

    def test_ai_windrausch_prioritizes_lethal_with_multiple_unblocked_attackers(self) -> None:
        windrausch = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windrausch"])
        self.engine.ai_player.hand = [windrausch]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("fire_creature_brandstifter"),
        ]
        attacker_one = self.make_creature("air_creature_windfalke", owner_id=1)
        attacker_two = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        self.engine.human_player.life = attacker_one.aw + attacker_two.aw + 1
        self.engine.block_assignments = {
            attacker_one.unit_id: [],
            attacker_two.unit_id: [],
        }
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_BLOCKERS_DECLARED,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], windrausch.instance_id)

    def test_ai_does_not_play_nachwehen_without_deaths(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_nachwehen"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
        else:
            self.assertFalse(prepared)

    def test_ai_nachwehen_waits_when_more_combat_deaths_are_likely(self) -> None:
        nachwehen = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_nachwehen"])
        self.engine.ai_player.hand = [nachwehen]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        attacker = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        self.engine.creatures_died_this_turn = 1
        self.engine.combat_queue = [attacker.unit_id]
        self.engine.current_attack_index = 0
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_DICE_BATTLE,
        )

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
        else:
            self.assertFalse(prepared)

    def test_ai_nachwehen_plays_after_last_relevant_combat_with_three_deaths(self) -> None:
        nachwehen = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_nachwehen"])
        self.engine.ai_player.hand = [nachwehen]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("fire_creature_brandstifter"),
        ]
        self.engine.creatures_died_this_turn = 3
        self.engine.combat_queue = []
        self.engine.block_assignments = {}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], nachwehen.instance_id)

    def test_ai_nachwehen_uses_one_death_only_when_hand_is_empty_and_resources_are_stable(self) -> None:
        nachwehen = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_nachwehen"])
        self.engine.ai_player.hand = [nachwehen]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("fire_creature_brandstifter"),
        ]
        self.engine.creatures_died_this_turn = 1
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")

    def test_ai_nachwehen_keeps_card_for_one_death_with_two_resources_and_good_hand(self) -> None:
        nachwehen = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_nachwehen"])
        follow_up_one = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        follow_up_two = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"])
        self.engine.ai_player.hand = [nachwehen, follow_up_one, follow_up_two]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        self.engine.creatures_died_this_turn = 1
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("card_id"), nachwehen.instance_id)
        else:
            self.assertFalse(prepared)

    def test_ai_windrausch_keeps_card_when_damage_is_already_lethal(self) -> None:
        windrausch = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windrausch"])
        self.engine.ai_player.hand = [windrausch]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        attacker = self.make_creature("air_creature_himmelsfalke", owner_id=1)
        self.engine.human_player.life = attacker.aw
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_BLOCKERS_DECLARED,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
        else:
            self.assertFalse(prepared)

    def test_ai_windrausch_does_not_spend_last_two_resources_for_one_extra_damage(self) -> None:
        windrausch = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_windrausch"])
        self.engine.ai_player.hand = [windrausch]
        self.engine.ai_player.resources = [
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_funkenkobold"),
        ]
        attacker = self.make_creature("air_creature_windfalke", owner_id=1)
        self.engine.human_player.life = 20
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.AFTER_BLOCKERS_DECLARED,
                active_player=self.engine.ai_player,
                source_player=self.engine.ai_player,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_SUMMONING,
        )

        prepared = self.engine.prepare_ai_turn_action()

        if prepared:
            self.assertNotEqual(self.engine.pending_ai_action.get("kind"), "cast_spell")
        else:
            self.assertFalse(prepared)

    def test_ai_turbulenz_is_prioritized_for_lethal(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        self.engine.human_player.life = 2
        turbulenz = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"])
        self.engine.ai_player.hand = [turbulenz]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        self.make_creature("air_creature_wolkenfalke", owner_id=1)
        self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        self.make_creature("earth_creature_felsensoldat", owner_id=0)
        self.make_creature("earth_creature_steinkobold", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], turbulenz.instance_id)

    def test_ai_turbulenz_is_not_used_with_only_two_resources_without_major_gain(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        turbulenz = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"])
        creature = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        self.engine.ai_player.hand = [turbulenz, creature]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.make_creature("air_creature_wolkenfalke", owner_id=1)
        self.make_creature("earth_creature_steinkobold", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertNotEqual(self.engine.pending_ai_action["card_id"], turbulenz.instance_id)

    def test_ai_turbulenz_can_choose_enemy_and_own_creature_when_own_one_is_disposable(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        turbulenz = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"])
        self.engine.ai_player.hand = [turbulenz]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
        ]
        damaged_own = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        damaged_own.current_hp = 1
        enemy_threat = self.make_creature("earth_creature_erdgolem", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")

        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()

        selected_targets = {target.creature_id for target in self.engine.pending_ai_action["selected_targets"]}
        self.assertEqual(selected_targets, {damaged_own.unit_id, enemy_threat.unit_id})

    def test_ai_turbulenz_does_not_bounce_two_own_creatures_without_clear_gain(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        turbulenz = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"])
        self.engine.ai_player.hand = [turbulenz]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
        ]
        own_one = self.make_creature("air_creature_wolkenfalke", owner_id=1)
        own_two = self.make_creature("air_creature_wolkenkrieger", owner_id=1)

        prepared = self.engine.prepare_ai_turn_action()

        if prepared and self.engine.pending_ai_action["kind"] == "cast_spell":
            self.engine.execute_prepared_ai_action()
            self.engine.prepare_ai_turn_action()
            selected_targets = {target.creature_id for target in self.engine.pending_ai_action["selected_targets"]}
            self.assertNotEqual(selected_targets, {own_one.unit_id, own_two.unit_id})
        else:
            self.assertTrue(True)

    def test_ai_turbulenz_is_kept_when_result_is_close(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        turbulenz = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"])
        self.engine.ai_player.hand = [turbulenz]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        self.make_creature("air_creature_wolkenfalke", owner_id=1)

        without_plan = {
            "score": 5.0,
            "sequence": [],
            "cards_played": 0,
            "creatures_played": 0,
            "creature_value": 0.0,
            "ending_available_resources": 3,
            "ending_total_resources": 3,
        }
        with_plan = {
            "score": 4.8,
            "sequence": [],
            "cards_played": 0,
            "creatures_played": 0,
            "creature_value": 0.0,
            "ending_available_resources": 1,
            "ending_total_resources": 1,
        }
        without_attack = {
            "score": 4.0,
            "attacker_ids": [self.engine.ai_player.battlefield[0].unit_id],
            "direct_damage": 1,
            "enemy_kills": 0,
            "own_losses": 0,
            "is_lethal": False,
        }
        with_attack = {
            "score": 5.0,
            "attacker_ids": [self.engine.ai_player.battlefield[0].unit_id],
            "direct_damage": 2,
            "enemy_kills": 0,
            "own_losses": 0,
            "is_lethal": False,
        }

        def fake_main_phase_plan(_player, _engine, _hand, **kwargs):
            return without_plan if kwargs.get("total_resources") == 3 else with_plan

        def fake_attack_plan(_player, _enemy, _hand, _sequence, **kwargs):
            return without_attack if len(_player.battlefield) >= 2 else with_attack

        with patch.object(self.engine.ai, "_best_air_main_phase_plan", side_effect=fake_main_phase_plan), patch.object(
            self.engine.ai,
            "_estimate_best_air_attack_plan",
            side_effect=fake_attack_plan,
        ):
            comparison = self.engine.ai._evaluate_air_turbulenz_plan(
                self.engine.ai_player,
                self.engine,
                turbulenz,
                hand=list(self.engine.ai_player.hand),
                available_resources=self.engine.ai_player.available_resources(),
                total_resources=self.engine.ai_player.total_resources(),
                own_creature_count=len(self.engine.ai_player.battlefield),
                ready_attacker_count=len([creature for creature in self.engine.ai_player.battlefield if creature.is_ready()]),
                creature_discount=0,
            )

        self.assertFalse(comparison["is_useful"])

    def test_ai_turbulenz_can_be_played_after_other_card_uses_tapped_resources_for_recycle(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        creature = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanreiter"])
        turbulenz = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_turbulenz"])
        self.engine.ai_player.hand = [creature, turbulenz]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
            self.make_resource("fire_creature_brandstifter"),
        ]
        self.make_creature("air_creature_wolkenkrieger", owner_id=1)
        blocker_one = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        blocker_two = self.make_creature("earth_creature_erdgolem", owner_id=0)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_creature")

        self.engine.execute_prepared_ai_action()
        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], turbulenz.instance_id)

        self.engine.execute_prepared_ai_action()
        self.engine.prepare_ai_turn_action()

        selected_targets = {target.creature_id for target in self.engine.pending_ai_action["selected_targets"]}
        self.assertEqual(selected_targets, {blocker_one.unit_id, blocker_two.unit_id})
        recycle_ids = self.engine.pending_ai_action["recycle_resource_ids"]
        recycled = [resource for resource in self.engine.ai_player.resources if resource.resource_id in recycle_ids]
        self.assertTrue(any(resource.tapped for resource in recycled))

    def test_ai_plays_useful_card_before_sturmformation(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        sturmformation = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_sturmformation"])
        creature = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        useless = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        self.engine.ai_player.hand = [sturmformation, creature, useless]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenkrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_creature")
        self.assertNotEqual(self.engine.pending_ai_action["card_id"], sturmformation.instance_id)

        self.engine.execute_prepared_ai_action()

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], sturmformation.instance_id)

    def test_ai_keeps_sturmformation_when_current_hand_is_strong(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        sturmformation = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_sturmformation"])
        strong_one = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        strong_two = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenkrieger"])
        strong_three = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"])
        self.engine.ai_player.hand = [sturmformation, strong_one, strong_two, strong_three]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertNotEqual(self.engine.pending_ai_action["card_id"], sturmformation.instance_id)

    def test_ai_does_not_peek_real_draws_while_planning_sturmformation(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_sturmformation"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]

        with patch.object(self.engine, "draw_card_for_player", side_effect=AssertionError("AI must not draw while planning")):
            prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")

    def test_ai_does_not_play_useless_spell_just_to_shrink_hand_before_sturmformation(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        sturmformation = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_sturmformation"])
        useless = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        self.engine.ai_player.hand = [sturmformation, useless]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
            self.make_resource("air_creature_wolkenfalke"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], sturmformation.instance_id)

    def test_ai_prefers_sturmformation_for_large_redundant_weak_hand(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        sturmformation = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_sturmformation"])
        weak_one = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        weak_two = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_boeenschub"])
        weak_three = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_nachwehen"])
        weak_four = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_nachwehen"])
        self.engine.ai_player.hand = [sturmformation, weak_one, weak_two, weak_three, weak_four]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenkrieger"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], sturmformation.instance_id)

    def test_ai_keeps_sturmformation_when_it_would_consume_last_resources_for_no_current_gain(self) -> None:
        self.engine.phase = PHASE_SUMMONING
        self.engine.ai_player.summoner_key = "air"
        sturmformation = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_sturmformation"])
        creature = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_wolkenfalke"])
        follow_up = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windfalke"])
        self.engine.ai_player.hand = [sturmformation, creature, follow_up]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_funkenkobold"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_creature_steinkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_creature_wassertropfen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_funkenkobold"]),
        ]

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "play_creature")
        self.assertNotEqual(self.engine.pending_ai_action["card_id"], sturmformation.instance_id)

