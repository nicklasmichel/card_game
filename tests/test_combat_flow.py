from __future__ import annotations

from unittest.mock import patch

from core.models import PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_MAIN_1
from tests.helpers import EngineTestCase


class CombatFlowTests(EngineTestCase):
    def test_unblocked_attack_uses_sw_not_aw(self) -> None:
        attacker = self.make_creature("fire_creature_infernobrecher", owner_id=0)
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker.unit_id]

        self.engine.confirm_attackers()
        self.engine.begin_combat_resolution()
        self.engine.end_dice_battle()

        self.assertEqual(self.engine.ai_player.life, 20 - attacker.sw)
        self.assertEqual(attacker.sw, 3)
        self.assertEqual(attacker.aw, 5)

    def test_blocked_combat_uses_aw_and_vw_as_w6_pool_sizes(self) -> None:
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        blocker = self.make_creature("water_creature_kuestenkaempfer", owner_id=1)

        with patch.object(self.engine.rng, "randint", side_effect=[3, 2, 5, 5, 6]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        battle = self.engine.pending_dice_battle
        self.assertIsNotNone(battle)
        self.assertEqual(battle.attacker_rolls, [3, 2, 5])
        self.assertEqual(battle.blocker_rolls, [5, 6])
        self.assertEqual(battle.attack_sum, 10)
        self.assertEqual(battle.defense_sum, 11)
        self.assertEqual(battle.winner, "blocker")
        self.assertEqual(attacker.current_hp, attacker.lw - blocker.sw)

    def test_tie_rerolls_full_pools_until_resolved(self) -> None:
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        with patch.object(self.engine.rng, "randint", side_effect=[3, 3, 3, 3, 3, 3, 6, 6, 6, 1, 1, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        battle = self.engine.pending_dice_battle
        self.assertEqual(battle.reroll_count, 1)
        self.assertEqual(len(battle.history), 2)
        self.assertIn("Gleichstand", battle.history[0].outcome_text)
        self.assertNotEqual(battle.attack_sum, battle.defense_sum)

    def test_winner_deals_own_sw_damage_and_lethal_removes_creature(self) -> None:
        attacker = self.make_creature("fire_creature_infernobestie", owner_id=0)
        blocker = self.make_creature("air_creature_sturmschwinge", owner_id=1)

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 6, 6, 6, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertIsNone(self.engine.get_unit_by_id(blocker.unit_id))
        self.assertEqual(self.engine.pending_dice_battle.creature_damage, attacker.sw)

    def test_human_block_assignment_is_one_to_one_only(self) -> None:
        attacker_one = self.make_creature("fire_creature_glutbestie", owner_id=0)
        attacker_two = self.make_creature("fire_creature_glutbrecher", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=0)

        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.active_player_index = 1
        self.engine.block_assignments = {
            attacker_one.unit_id: None,
            attacker_two.unit_id: None,
        }

        self.engine.toggle_blocker_assignment(blocker.unit_id)
        self.engine.toggle_selected_attack_target(attacker_one.unit_id)
        self.assertEqual(self.engine.block_assignments[attacker_one.unit_id], blocker.unit_id)

        self.engine.toggle_blocker_assignment(blocker.unit_id)
        self.engine.toggle_selected_attack_target(attacker_two.unit_id)
        self.assertIsNone(self.engine.block_assignments[attacker_two.unit_id])

    def test_flying_still_restricts_blockers(self) -> None:
        attacker = self.make_creature("air_creature_windschwinge", owner_id=0)
        ground_blocker = self.make_creature("earth_creature_felsensoldat", owner_id=0)
        flying_blocker = self.make_creature("air_creature_himmelsschwinge", owner_id=0)

        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.active_player_index = 1
        self.engine.block_assignments = {attacker.unit_id: None}

        self.engine.toggle_blocker_assignment(ground_blocker.unit_id)
        self.engine.toggle_selected_attack_target(attacker.unit_id)
        self.assertIsNone(self.engine.block_assignments[attacker.unit_id])

        self.engine.toggle_blocker_assignment(flying_blocker.unit_id)
        self.engine.toggle_selected_attack_target(attacker.unit_id)
        self.assertEqual(self.engine.block_assignments[attacker.unit_id], flying_blocker.unit_id)

    def test_trample_uses_difference_divided_by_six(self) -> None:
        attacker = self.make_creature("fire_creature_infernobrecher", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 4, 2, 2, 3, 3, 2]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        battle = self.engine.pending_dice_battle
        self.assertEqual(battle.attack_sum, 20)
        self.assertEqual(battle.defense_sum, 8)
        self.assertEqual(battle.trample_damage, 2)
        self.assertEqual(self.engine.ai_player.life, 18)
        self.assertEqual(battle.creature_damage, attacker.sw)

    def test_begin_combat_resolution_keeps_battlefield_attacker_order(self) -> None:
        left = self.make_creature("fire_creature_glutbestie", owner_id=0)
        right = self.make_creature("fire_creature_glutbrecher", owner_id=0)
        blocker = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.block_assignments = {
            right.unit_id: None,
            left.unit_id: blocker.unit_id,
        }

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 6, 1, 1, 1]):
            self.engine.begin_combat_resolution()

        self.assertEqual(self.engine.combat_queue, [left.unit_id, right.unit_id])
        self.assertEqual(self.engine.phase, PHASE_DICE_BATTLE)

    def test_enraged_creature_remains_mandatory_attacker(self) -> None:
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        self.engine.phase = PHASE_MAIN_1

        self.engine.begin_attack_declaration()
        self.engine.toggle_attacker(attacker.unit_id)

        self.assertIn(attacker.unit_id, self.engine.selected_attackers)
