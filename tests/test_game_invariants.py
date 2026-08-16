from __future__ import annotations

import unittest

from core.game_logic import GameEngine
from core.models import Ability, PHASE_DECLARE_ATTACKERS, PHASE_GAME_OVER
from diagnostics.invariants import (
    collect_game_invariant_violations,
    collect_prepared_action_violations,
    validate_game_invariants,
)


class GameInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine()
        self.engine.statistics = None
        self.engine.pending_log_file_lines.clear()

    def make_creature(
        self,
        owner_id: int,
        *,
        aw: int = 1,
        vw: int = 1,
        sw: int = 1,
        lw: int = 2,
        ability: Ability = Ability.HASTE,
        ready: bool = True,
    ):
        creature = self.engine.create_builder_creature(
            self.engine.players[owner_id],
            aw=aw,
            vw=vw,
            sw=sw,
            lw=lw,
            ability=ability,
        )
        self.assertIsNotNone(creature)
        creature.tapped = not ready
        creature.summoning_sick = not ready
        return creature

    def test_fresh_builder_game_satisfies_all_invariants(self) -> None:
        validate_game_invariants(self.engine)

    def test_ready_creature_with_zero_attack_can_attack(self) -> None:
        creature = self.make_creature(0, aw=0, vw=1, ready=True)

        self.assertIn(creature, self.engine.available_attackers(self.engine.players[0]))

    def test_ready_creature_with_zero_defense_can_block(self) -> None:
        attacker = self.make_creature(0, aw=2, vw=1, ready=True)
        blocker = self.make_creature(1, aw=1, vw=0, ready=True)

        self.assertTrue(self.engine.can_creature_block_attacker(blocker, attacker))

    def test_tapped_creature_cannot_block(self) -> None:
        attacker = self.make_creature(0, ready=True)
        blocker = self.make_creature(1, ready=True)
        blocker.tapped = True

        self.assertFalse(self.engine.can_creature_block_attacker(blocker, attacker))

    def test_destroyed_declared_attacker_is_only_invalid_before_resolution(self) -> None:
        attacker = self.make_creature(0, ready=True)
        self.engine.selected_attackers = [attacker.unit_id]
        self.engine.players[0].battlefield.remove(attacker)

        self.engine.phase = PHASE_DECLARE_ATTACKERS
        violations = collect_game_invariant_violations(self.engine)
        self.assertIn(
            f"selected attacker {attacker.unit_id} is not controlled by the active player",
            violations,
        )

        self.engine.players[1].life = 0
        self.engine.phase = PHASE_GAME_OVER
        violations = collect_game_invariant_violations(self.engine)
        self.assertNotIn(
            f"selected attacker {attacker.unit_id} is not controlled by the active player",
            violations,
        )

    def test_only_flying_creature_can_block_flying_attacker(self) -> None:
        attacker = self.make_creature(0, ability=Ability.FLYING, ready=True)
        ground_blocker = self.make_creature(1, ability=Ability.HASTE, ready=True)
        flying_blocker = self.make_creature(1, ability=Ability.FLYING, ready=True)

        self.assertFalse(self.engine.can_creature_block_attacker(ground_blocker, attacker))
        self.assertTrue(self.engine.can_creature_block_attacker(flying_blocker, attacker))

    def test_invariants_report_invalid_stats_dead_units_and_duplicate_ids(self) -> None:
        first = self.make_creature(0)
        second = self.make_creature(1)
        first.current_hp = 0
        second.unit_id = first.unit_id
        second.vw = -1

        violations = "\n".join(collect_game_invariant_violations(self.engine))

        self.assertIn("invalid current life", violations)
        self.assertIn("negative combat stats", violations)
        self.assertIn("duplicate object id", violations)

    def test_prepared_creature_action_must_have_legal_cost_and_ability(self) -> None:
        action = {
            "kind": "builder_create_creature",
            "plan": {
                "aw": 1,
                "vw": 0,
                "sw": 1,
                "lw": 1,
                "cost": 99,
                "ability": None,
            },
        }

        violations = "\n".join(collect_prepared_action_violations(self.engine, action))

        self.assertIn("does not match expected cost", violations)
        self.assertIn("only 0 ready resources", violations)
        self.assertIn("invalid abilities", violations)


if __name__ == "__main__":
    unittest.main()
