from __future__ import annotations

from unittest.mock import patch

from core.models import (
    DiceRoundRecord,
    DieResult,
    PendingComparison,
    PendingDiceBattle,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
)
from tests.helpers import EngineTestCase


class CombatFlowTests(EngineTestCase):
    def test_flying_attacker_can_only_be_blocked_by_flying_creature(self) -> None:
        attacker = self.make_creature("air_creature_sturmfalke", owner_id=1)
        ground_blocker = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        flying_blocker = self.make_creature("air_creature_himmelsgreif", owner_id=0)

        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {attacker.unit_id: []}
        self.engine.selected_attack_target_id = attacker.unit_id

        self.engine.toggle_blocker_assignment(ground_blocker.unit_id)

        self.assertEqual(self.engine.block_assignments[attacker.unit_id], [])

        self.engine.toggle_blocker_assignment(flying_blocker.unit_id)

        self.assertEqual(self.engine.block_assignments[attacker.unit_id], [flying_blocker.unit_id])

    def test_sturmfuerst_bonus_increases_only_attacker_die_results(self) -> None:
        attacker = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.make_creature("air_creature_sturmfuerst", owner_id=1)

        self.engine.active_player_index = 0

        with patch.object(self.engine.rng, "randint", side_effect=[10, 11, 12, 13, 14]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        battle = self.engine.pending_dice_battle

        self.assertIsNotNone(battle)
        self.assertEqual([die.aw_bonus for die in battle.attacker_dice], [attacker.aw + 2, attacker.aw + 2])
        self.assertEqual([die.aw_bonus for die in battle.blocker_dice], [blocker.aw, blocker.aw, blocker.aw])

    def test_human_provoke_assigns_selected_blocker_to_attacker(self) -> None:
        attacker = self.make_creature("earth_creature_granitkrieger", owner_id=0)
        blocker = self.make_creature("fire_creature_funkenkobold", owner_id=1)

        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.toggle_attacker(attacker.unit_id)
        self.engine.toggle_provoke_target(blocker.unit_id)
        self.engine.confirm_attackers()

        self.assertEqual(self.engine.provoke_assignments[attacker.unit_id], blocker.unit_id)
        self.assertEqual(self.engine.block_assignments[attacker.unit_id], [blocker.unit_id])
        self.assertEqual(self.engine.blocker_to_attackers[blocker.unit_id], [attacker.unit_id])

    def test_provoke_forced_block_cannot_be_removed(self) -> None:
        attacker = self.make_creature("earth_creature_granitkrieger", owner_id=1)
        blocker = self.make_creature("water_creature_flusskrieger", owner_id=0)

        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker.unit_id]
        self.engine.provoke_assignments = {attacker.unit_id: blocker.unit_id}
        self.engine.confirm_attackers()

        self.engine.selected_attack_target_id = attacker.unit_id
        self.engine.toggle_blocker_assignment(blocker.unit_id)

        self.assertEqual(self.engine.block_assignments[attacker.unit_id], [blocker.unit_id])
        self.assertIn("muss diesen Angreifer durch Provozieren blocken", self.engine.log_messages[-1])

    def test_ai_provoke_chooses_and_assigns_blocker(self) -> None:
        attacker = self.make_creature("earth_creature_granitkrieger", owner_id=1)
        blocker = self.make_creature("water_creature_flusskrieger", owner_id=0)

        self.engine.active_player_index = 1
        self.engine.ai_declare_attackers()

        self.assertEqual(self.engine.provoke_assignments[attacker.unit_id], blocker.unit_id)
        self.assertEqual(self.engine.block_assignments[attacker.unit_id], [blocker.unit_id])

    def test_defender_can_block_two_attackers_in_same_combat_phase(self) -> None:
        attacker_one = self.make_creature("fire_creature_funkenkobold", owner_id=1)
        attacker_two = self.make_creature("fire_creature_flammenrekrut", owner_id=1)
        defender = self.make_creature("earth_creature_schildwache", owner_id=0)

        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {
            attacker_one.unit_id: [],
            attacker_two.unit_id: [],
        }

        self.engine.selected_attack_target_id = attacker_one.unit_id
        self.engine.toggle_blocker_assignment(defender.unit_id)
        self.engine.selected_attack_target_id = attacker_two.unit_id
        self.engine.toggle_blocker_assignment(defender.unit_id)

        self.assertEqual(self.engine.block_assignments[attacker_one.unit_id], [defender.unit_id])
        self.assertEqual(self.engine.block_assignments[attacker_two.unit_id], [defender.unit_id])
        self.assertEqual(self.engine.blocker_to_attackers[defender.unit_id], [attacker_one.unit_id, attacker_two.unit_id])

    def test_human_adaptation_creates_choice_and_can_reroll_comparison(self) -> None:
        attacker = self.make_creature("fire_creature_lavakrieger", owner_id=1)
        blocker = self.make_creature("water_creature_wellenformer", owner_id=0)
        attacker.current_hp = attacker.vw
        blocker.current_hp = blocker.vw

        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=1,
            blocker_owner=0,
            attacker_dice=[DieResult(10, attacker.aw)],
            blocker_dice=[DieResult(1, blocker.aw)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.choose_human_die(0)

        self.assertIsNotNone(self.engine.pending_dice_battle)
        self.assertIsNotNone(battle.pending_comparison)
        self.assertTrue(battle.pending_comparison.human_can_adapt)
        self.assertEqual(len(battle.history), 0)

        with patch.object(self.engine.rng, "randint", return_value=20):
            self.engine.resolve_pending_comparison(use_human_adaptation=True)

        self.assertTrue(battle.blocker_used_adaptation)
        self.assertEqual(len(battle.history), 1)
        self.assertLess(attacker.current_hp, attacker.vw)
        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertTrue(battle.resolution_complete)

    def test_trample_deals_player_damage_from_remaining_attack_dice_after_last_blocker(self) -> None:
        attacker = self.make_creature("fire_creature_magmabestie", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        blocker.current_hp = 0

        self.engine.active_player_index = 0
        self.engine.defending_player.life = 20
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[
                DieResult(18, attacker.aw, used=True),
                DieResult(17, attacker.aw, used=True),
                DieResult(16, attacker.aw, used=False),
                DieResult(15, attacker.aw, used=False),
                DieResult(14, attacker.aw, used=False),
            ],
            blocker_dice=[
                DieResult(5, blocker.aw, used=True),
                DieResult(4, blocker.aw, used=True),
                DieResult(3, blocker.aw, used=True),
            ],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.finalize_or_continue_dice_battle(battle, attacker, blocker)

        self.assertEqual(self.engine.ai_player.life, 17)
        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertTrue(battle.resolution_complete)

    def test_dice_battle_must_be_closed_manually_after_resolution(self) -> None:
        attacker = self.make_creature("fire_creature_lavakrieger", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=True)],
            blocker_dice=[DieResult(1, blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.finalize_or_continue_dice_battle(battle, attacker, blocker)

        self.assertTrue(battle.resolution_complete)
        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertIn("Kampf abschließen", [spec.label for spec in self.engine.get_button_specs()])

        self.engine.end_dice_battle()

        self.assertIsNone(self.engine.pending_dice_battle)

    def test_dice_battle_button_shows_next_combat_when_another_battle_remains(self) -> None:
        attacker_one = self.make_creature("fire_creature_lavakrieger", owner_id=0)
        blocker_one = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        attacker_two = self.make_creature("fire_creature_funkenkobold", owner_id=0)
        blocker_two = self.make_creature("earth_creature_schildwache", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        self.engine.combat_queue = [attacker_one.unit_id, attacker_two.unit_id]
        self.engine.current_attack_index = 0
        self.engine.current_blocker_order = [blocker_one.unit_id]
        self.engine.current_blocker_index = 1
        self.engine.block_assignments = {
            attacker_one.unit_id: [blocker_one.unit_id],
            attacker_two.unit_id: [blocker_two.unit_id],
        }
        battle = PendingDiceBattle(
            attacker_id=attacker_one.unit_id,
            blocker_id=blocker_one.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker_one.aw, used=True)],
            blocker_dice=[DieResult(1, blocker_one.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker_one),
            blocker_snapshot=self.snapshot(blocker_one),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.finalize_or_continue_dice_battle(battle, attacker_one, blocker_one)

        self.assertTrue(battle.resolution_complete)
        self.assertIn("Nächster Kampf", [spec.label for spec in self.engine.get_button_specs()])

    def test_dice_battle_cannot_be_closed_early(self) -> None:
        attacker = self.make_creature("fire_creature_lavakrieger", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=False)],
            blocker_dice=[DieResult(1, blocker.aw, used=False)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.end_dice_battle()

        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertEqual(self.engine.log_messages, [])

    def test_ignite_attacker_deals_two_damage_on_first_won_comparison(self) -> None:
        attacker = self.make_creature("fire_creature_brandstifter", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=True)],
            blocker_dice=[DieResult(1, blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.apply_comparison_result(
            battle,
            PendingComparison(
                attacker_die=battle.attacker_dice[0],
                blocker_die=battle.blocker_dice[0],
                human_is_attacker=True,
            ),
        )

        self.assertEqual(blocker.current_hp, blocker.vw - 2)

    def test_ignite_has_no_effect_while_blocking(self) -> None:
        attacker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        blocker = self.make_creature("fire_creature_brandstifter", owner_id=0)

        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=1,
            blocker_owner=0,
            attacker_dice=[DieResult(1, attacker.aw, used=True)],
            blocker_dice=[DieResult(20, blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.apply_comparison_result(
            battle,
            PendingComparison(
                attacker_die=battle.attacker_dice[0],
                blocker_die=battle.blocker_dice[0],
                human_is_attacker=False,
            ),
        )

        self.assertEqual(attacker.current_hp, attacker.vw - 1)

    def test_ignite_has_no_effect_after_first_comparison_of_same_battle(self) -> None:
        attacker = self.make_creature("fire_creature_brandstifter", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=True), DieResult(19, attacker.aw, used=True)],
            blocker_dice=[DieResult(1, blocker.aw, used=True), DieResult(2, blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        battle.history.append(
            DiceRoundRecord(
                round_number=1,
                human_unit_name=attacker.name,
                human_result="20",
                enemy_unit_name=blocker.name,
                enemy_result="1",
                outcome_text="dummy",
            )
        )
        self.engine.pending_dice_battle = battle

        self.engine.apply_comparison_result(
            battle,
            PendingComparison(
                attacker_die=battle.attacker_dice[1],
                blocker_die=battle.blocker_dice[1],
                human_is_attacker=True,
            ),
        )

        self.assertEqual(blocker.current_hp, blocker.vw - 1)

    def test_ignite_can_trigger_again_in_new_single_combat_against_next_blocker(self) -> None:
        attacker = self.make_creature("fire_creature_brandstifter", owner_id=0)
        first_blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        second_blocker = self.make_creature("earth_creature_schildwache", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE

        first_battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=first_blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=True)],
            blocker_dice=[DieResult(1, first_blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(first_blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = first_battle
        self.engine.apply_comparison_result(
            first_battle,
            PendingComparison(
                attacker_die=first_battle.attacker_dice[0],
                blocker_die=first_battle.blocker_dice[0],
                human_is_attacker=True,
            ),
        )

        second_battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=second_blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(19, attacker.aw, used=True)],
            blocker_dice=[DieResult(2, second_blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(second_blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = second_battle
        self.engine.apply_comparison_result(
            second_battle,
            PendingComparison(
                attacker_die=second_battle.attacker_dice[0],
                blocker_die=second_battle.blocker_dice[0],
                human_is_attacker=True,
            ),
        )

        self.assertEqual(first_blocker.current_hp, first_blocker.vw - 2)
        self.assertEqual(second_blocker.current_hp, second_blocker.vw - 2)

    def test_battle_snapshot_keeps_last_hp_after_creature_removal(self) -> None:
        attacker = self.make_creature("fire_creature_lavakrieger", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        blocker.current_hp = 1

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=True)],
            blocker_dice=[DieResult(1, blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        comparison = PendingComparison(
            attacker_die=DieResult(20, attacker.aw, used=True),
            blocker_die=DieResult(1, blocker.aw, used=True),
            human_is_attacker=True,
        )
        self.engine.apply_comparison_result(battle, comparison)

        self.assertIsNone(self.engine.get_unit_by_id(blocker.unit_id))
        self.assertEqual(battle.blocker_snapshot.current_hp, 0)
