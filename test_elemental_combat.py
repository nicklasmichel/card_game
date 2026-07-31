from __future__ import annotations

import unittest
from unittest.mock import patch

from game_logic import GameEngine
from models import (
    BattlefieldCreature,
    CardInstance,
    DieResult,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PendingDiceBattle,
    PlayerState,
)


class ElementalCombatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine()
        self.engine.players = [
            PlayerState(0, "Spieler", True),
            PlayerState(1, "Gegner", False),
        ]
        self.engine.active_player_index = 0
        self.engine.reset_combat_state()
        self.engine.log_messages.clear()

    def make_creature(self, template_id: str, owner_id: int, ready: bool = True) -> BattlefieldCreature:
        template = self.engine.templates[template_id]
        creature = BattlefieldCreature.from_card(CardInstance(self.engine.make_instance_id(), template))
        if ready:
            creature.tapped = False
            creature.summoning_sick = False
        self.engine.players[owner_id].battlefield.append(creature)
        return creature

    def test_defender_can_block_two_attackers_in_same_combat_phase(self) -> None:
        attacker_one = self.make_creature("fire_funkenkobold", owner_id=1)
        attacker_two = self.make_creature("fire_flammenrekrut", owner_id=1)
        defender = self.make_creature("earth_schildwache", owner_id=0)

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
        self.assertEqual(
            self.engine.blocker_to_attackers[defender.unit_id],
            [attacker_one.unit_id, attacker_two.unit_id],
        )

    def test_human_adaptation_creates_choice_and_can_reroll_comparison(self) -> None:
        attacker = self.make_creature("fire_lavakrieger", owner_id=1)
        blocker = self.make_creature("water_wellenformer", owner_id=0)
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
        self.assertIsNone(self.engine.pending_dice_battle)

    def test_trample_deals_player_damage_from_remaining_attack_dice_after_last_blocker(self) -> None:
        attacker = self.make_creature("fire_magmabestie", owner_id=0)
        blocker = self.make_creature("earth_felsensoldat", owner_id=1)
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
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.finalize_or_continue_dice_battle(battle, attacker, blocker)

        self.assertEqual(self.engine.ai_player.life, 17)
        self.assertIsNone(self.engine.pending_dice_battle)


if __name__ == "__main__":
    unittest.main()
