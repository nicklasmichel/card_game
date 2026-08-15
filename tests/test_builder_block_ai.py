from __future__ import annotations

import math
import time
import unittest
from unittest.mock import patch

from core.ai.builder import (
    BuilderBlockCandidate,
    choose_builder_blocks,
    evaluate_block_horizon,
    generate_builder_block_candidates,
    score_builder_block_candidate,
)
from core.game_logic import GameEngine
from core.models import Ability, PHASE_DECLARE_BLOCKERS, PHASE_GAME_OVER, PHASE_MAIN_1, PlayerState, ResourceCard
from core.ai.builder.turn_projection import build_current_turn_projection
from core.ai.builder.attack_policy import BuilderAttackCandidate


class BuilderBlockAITests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine()
        self.engine.log_messages.clear()

    def make_builder_resource(self, engine: GameEngine | None = None, *, tapped: bool = False) -> ResourceCard:
        engine = self.engine if engine is None else engine
        return ResourceCard(
            template=engine.builder_resource_template(),
            resource_id=engine.make_instance_id(),
            tapped=tapped,
        )

    def make_builder_creature(
        self,
        owner_id: int,
        *,
        aw: int,
        vw: int,
        sw: int,
        lw: int,
        abilities: tuple[Ability, ...] = (),
        ready: bool = True,
        current_hp: int | None = None,
    ):
        player = self.engine.players[owner_id]
        creature = self.engine.create_builder_creature(
            player,
            aw=aw,
            vw=vw,
            sw=sw,
            lw=lw,
            abilities=frozenset(abilities),
        )
        creature.tapped = not ready
        creature.summoning_sick = not ready
        if current_hp is not None:
            creature.current_hp = current_hp
        return creature

    def set_attackers(self, *attackers) -> None:
        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {attacker.unit_id: None for attacker in attackers}
        self.engine.enraged_forced_attackers = set()

    def test_generate_block_candidates_includes_no_block_when_not_forced(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)
        self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        self.set_attackers(attacker)

        candidates = generate_builder_block_candidates(self.engine.human_player, self.engine)

        self.assertIn(BuilderBlockCandidate(assignments=tuple()), candidates)

    def test_forced_block_is_present_in_every_candidate_and_reserved(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True, abilities=(Ability.ENRAGED,))
        second = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        forced_blocker = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        self.set_attackers(attacker, second)
        self.engine.block_assignments[attacker.unit_id] = forced_blocker.unit_id
        self.engine.enraged_forced_attackers = {attacker.unit_id}

        candidates = generate_builder_block_candidates(self.engine.human_player, self.engine)

        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertIn((attacker.unit_id, forced_blocker.unit_id), candidate.assignments)
            self.assertLessEqual(sum(1 for _, blocker_id in candidate.assignments if blocker_id == forced_blocker.unit_id), 1)

    def test_flying_attacker_cannot_be_blocked_by_ground_creature(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.FLYING,))
        self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        self.set_attackers(attacker)

        candidates = generate_builder_block_candidates(self.engine.human_player, self.engine)

        self.assertEqual(candidates, [BuilderBlockCandidate(assignments=tuple(), unblocked_attacker_ids=(attacker.unit_id,), forced_assignments=())])

    def test_single_blocking_never_reuses_attacker_or_blocker(self) -> None:
        a1 = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        a2 = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        b1 = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        b2 = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        self.set_attackers(a1, a2)

        candidates = generate_builder_block_candidates(self.engine.human_player, self.engine)

        for candidate in candidates:
            attacker_ids = [attacker_id for attacker_id, _ in candidate.assignments]
            blocker_ids = [blocker_id for _, blocker_id in candidate.assignments]
            self.assertEqual(len(attacker_ids), len(set(attacker_ids)))
            self.assertEqual(len(blocker_ids), len(set(blocker_ids)))
        self.assertTrue(any(len(candidate.assignments) == 2 for candidate in candidates))

    def test_one_blocker_two_attackers_blocks_more_dangerous_attack(self) -> None:
        dangerous = self.make_builder_creature(1, aw=2, vw=1, sw=5, lw=3, ready=True)
        small = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        blocker = self.make_builder_creature(0, aw=2, vw=2, sw=3, lw=3, ready=True)
        self.set_attackers(dangerous, small)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(assignments[dangerous.unit_id], blocker.unit_id)
        self.assertIsNone(assignments[small.unit_id])

    def test_bad_block_prefers_no_block(self) -> None:
        attacker = self.make_builder_creature(1, aw=5, vw=1, sw=1, lw=2, ready=True)
        valuable_blocker = self.make_builder_creature(0, aw=5, vw=1, sw=5, lw=1, ready=True, abilities=(Ability.FLYING, Ability.LIFE_STEAL))
        self.set_attackers(attacker)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertIsNone(assignments[attacker.unit_id])
        block_score = score_builder_block_candidate(
            BuilderBlockCandidate(assignments=((attacker.unit_id, valuable_blocker.unit_id),)),
            self.engine.human_player,
            self.engine,
        )
        no_block_score = score_builder_block_candidate(BuilderBlockCandidate(assignments=tuple()), self.engine.human_player, self.engine)
        self.assertGreater(no_block_score.total, block_score.total)

    def test_good_trade_is_preferred_over_no_block(self) -> None:
        attacker = self.make_builder_creature(1, aw=1, vw=1, sw=3, lw=2, ready=True, abilities=(Ability.TRAMPLE, Ability.LIFE_STEAL))
        blocker = self.make_builder_creature(0, aw=4, vw=4, sw=3, lw=2, ready=True)
        self.set_attackers(attacker)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(assignments[attacker.unit_id], blocker.unit_id)

    def test_lethal_block_is_strongly_preferred(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=4, lw=3, ready=True)
        blocker = self.make_builder_creature(0, aw=1, vw=4, sw=1, lw=4, ready=True)
        self.engine.human_player.life = 4
        self.set_attackers(attacker)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(assignments[attacker.unit_id], blocker.unit_id)

    def test_defense_zero_chump_block_is_used_to_prevent_lethal(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=4, lw=3, ready=True, abilities=(Ability.FLYING,))
        blocker = self.make_builder_creature(0, aw=1, vw=0, sw=1, lw=1, ready=True, abilities=(Ability.FLYING,))
        self.engine.human_player.life = 4
        self.set_attackers(attacker)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(assignments[attacker.unit_id], blocker.unit_id)

    def test_trample_chump_can_be_worse_than_taking_damage(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=6, lw=4, ready=True, abilities=(Ability.TRAMPLE,))
        blocker = self.make_builder_creature(0, aw=10, vw=2, sw=10, lw=1, ready=True, abilities=(Ability.FLYING,))
        blocker.current_hp = 1
        self.engine.human_player.life = 10
        self.set_attackers(attacker)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertIsNone(assignments[attacker.unit_id])

    def test_trample_chump_is_used_when_it_prevents_lethal(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=6, lw=4, ready=True, abilities=(Ability.TRAMPLE,))
        blocker = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=2, ready=True)
        blocker.current_hp = 1
        self.engine.human_player.life = 5
        self.set_attackers(attacker)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(assignments[attacker.unit_id], blocker.unit_id)

    def test_own_lifesteal_blocker_healing_improves_block_score(self) -> None:
        attacker = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=3, ready=True)
        lifesteal_blocker = self.make_builder_creature(0, aw=3, vw=4, sw=3, lw=5, ready=True, abilities=(Ability.LIFE_STEAL,), current_hp=2)
        normal_blocker = self.make_builder_creature(0, aw=3, vw=4, sw=3, lw=5, ready=True, current_hp=2)
        self.set_attackers(attacker)

        lifesteal_score = score_builder_block_candidate(
            BuilderBlockCandidate(assignments=((attacker.unit_id, lifesteal_blocker.unit_id),)),
            self.engine.human_player,
            self.engine,
        )
        normal_score = score_builder_block_candidate(
            BuilderBlockCandidate(assignments=((attacker.unit_id, normal_blocker.unit_id),)),
            self.engine.human_player,
            self.engine,
        )

        self.assertGreater(lifesteal_score.own_lifesteal_value, normal_score.own_lifesteal_value)

    def test_enemy_lifesteal_can_make_bad_block_less_attractive(self) -> None:
        attacker = self.make_builder_creature(1, aw=4, vw=1, sw=4, lw=5, ready=True, abilities=(Ability.LIFE_STEAL,), current_hp=1)
        blocker = self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=1, ready=True)
        self.engine.human_player.life = 12
        self.set_attackers(attacker)

        block_score = score_builder_block_candidate(
            BuilderBlockCandidate(assignments=((attacker.unit_id, blocker.unit_id),)),
            self.engine.human_player,
            self.engine,
        )
        no_block_score = score_builder_block_candidate(BuilderBlockCandidate(assignments=tuple()), self.engine.human_player, self.engine)

        self.assertGreater(block_score.enemy_lifesteal_value, 0)
        self.assertLessEqual(block_score.expected_player_damage_taken, no_block_score.expected_player_damage_taken)

    def test_blocking_ground_attacker_prevents_known_next_flying_lethal(self) -> None:
        flying = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.FLYING,))
        ground = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        blocker = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        self.engine.human_player.life = 6
        self.set_attackers(flying, ground)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(assignments[ground.unit_id], blocker.unit_id)
        self.assertIsNone(assignments[flying.unit_id])

    def test_block_horizon_tracks_repeated_flying_damage(self) -> None:
        flyer = self.make_builder_creature(1, aw=4, vw=0, sw=5, lw=1, ready=True, abilities=(Ability.FLYING,))
        self.engine.human_player.life = 10
        self.set_attackers(flyer)

        projection = build_current_turn_projection(self.engine.ai_player, self.engine)
        report = evaluate_block_horizon(
            projection,
            BuilderAttackCandidate(attacker_ids=(flyer.unit_id,)),
            tuple(),
        )

        self.assertEqual(report.second_attack_damage, 5.0)
        self.assertEqual(report.cumulative_unavoidable_damage, 10.0)
        self.assertFalse(report.coverage_prevents_repeated_lethal)
        self.assertIsNone(report.coverage_ready_turn)

    def test_block_horizon_counts_future_flying_blocker_when_ready_in_time(self) -> None:
        flyer = self.make_builder_creature(1, aw=4, vw=0, sw=5, lw=1, ready=True, abilities=(Ability.FLYING,))
        blocker = self.make_builder_creature(0, aw=0, vw=1, sw=0, lw=2, ready=True, abilities=(Ability.FLYING,))
        self.engine.human_player.life = 10
        self.set_attackers(flyer)

        projection = build_current_turn_projection(self.engine.ai_player, self.engine)
        report = evaluate_block_horizon(
            projection,
            BuilderAttackCandidate(attacker_ids=(flyer.unit_id,)),
            tuple(),
        )

        self.assertEqual(report.second_attack_damage, 5.0)
        self.assertTrue(report.coverage_prevents_repeated_lethal)
        self.assertEqual(report.cumulative_unavoidable_damage, 5.0)
        self.assertEqual(report.coverage_ready_turn, 1)
        self.assertTrue(report.must_hold_as_blocker)
        self.assertIsNotNone(blocker)

    def test_assignment_pairing_prefers_better_overall_matching(self) -> None:
        a1 = self.make_builder_creature(1, aw=1, vw=1, sw=5, lw=2, ready=True)
        a2 = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=5, ready=True)
        b1 = self.make_builder_creature(0, aw=4, vw=4, sw=3, lw=5, ready=True)
        b2 = self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.set_attackers(a1, a2)

        assignments = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(assignments[a1.unit_id], b1.unit_id)
        self.assertEqual(assignments[a2.unit_id], b2.unit_id)

    def test_block_decision_is_deterministic(self) -> None:
        a1 = self.make_builder_creature(1, aw=2, vw=1, sw=4, lw=3, ready=True)
        a2 = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.FLYING,))
        self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True)
        self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True, abilities=(Ability.FLYING,))
        self.set_attackers(a1, a2)

        first = choose_builder_blocks(self.engine.human_player, self.engine)
        second = choose_builder_blocks(self.engine.human_player, self.engine)

        self.assertEqual(first, second)

    def test_block_selection_with_five_vs_five_is_fast(self) -> None:
        attackers = [self.make_builder_creature(1, aw=2, vw=1, sw=2 + (index % 3), lw=2, ready=True) for index in range(5)]
        for index in range(5):
            self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3 + (index % 2), ready=True)
        self.set_attackers(*attackers)

        start = time.perf_counter()
        choose_builder_blocks(self.engine.human_player, self.engine)
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 1.0)

    def test_engine_integration_applies_builder_block_assignments_through_normal_flow(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=5, lw=3, ready=True)
        blocker = self.make_builder_creature(0, aw=3, vw=4, sw=3, lw=4, ready=True)
        self.engine.human_player.is_human = False
        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.enraged_forced_attackers = set()

        self.engine.ai_assign_blocks()

        self.assertEqual(self.engine.block_assignments[attacker.unit_id], blocker.unit_id)

    def test_builder_block_smoke_games(self) -> None:
        no_block_decisions = 0
        chump_blocks = 0
        lethal_block_decisions = 0
        decision_times: list[float] = []
        for seed in range(30):
            with self.subTest(seed=seed):
                engine = GameEngine()
                engine.players = [
                    PlayerState(0, "Spieler", False, summoner_key="builder", life=4 + (seed % 7), resources=[self.make_builder_resource(engine)]),
                    PlayerState(1, "Gegner", False, summoner_key="builder", life=10, resources=[self.make_builder_resource(engine)]),
                ]
                engine.active_player_index = 1
                engine.phase = PHASE_DECLARE_BLOCKERS
                engine.reset_combat_state()
                attackers = []
                for index in range(1 + (seed % 3)):
                    attacker = engine.create_builder_creature(
                        engine.ai_player,
                        aw=1 + ((seed + index) % 4),
                        vw=1,
                        sw=2 + ((seed + index * 2) % 5),
                        lw=2 + ((seed + index) % 3),
                        abilities=frozenset(
                            ability
                            for ability, enabled in (
                                (Ability.TRAMPLE, (seed + index) % 4 == 0),
                                (Ability.FLYING, (seed + index) % 5 == 0),
                                (Ability.LIFE_STEAL, (seed + index) % 6 == 0),
                            )
                            if enabled
                        ),
                    )
                    attacker.tapped = False
                    attacker.summoning_sick = False
                    attackers.append(attacker)
                blockers = []
                for index in range(1 + ((seed + 1) % 3)):
                    blocker = engine.create_builder_creature(
                        engine.human_player,
                        aw=1 + ((seed + index) % 3),
                        vw=1 + ((seed + index * 3) % 4),
                        sw=1 + ((seed + index) % 4),
                        lw=2 + ((seed + index * 2) % 4),
                        abilities=frozenset({Ability.FLYING}) if (seed + index) % 4 == 0 else frozenset(),
                    )
                    blocker.tapped = False
                    blocker.summoning_sick = False
                    blockers.append(blocker)
                engine.block_assignments = {attacker.unit_id: None for attacker in attackers}
                if attackers and blockers and seed % 5 == 0:
                    forced_attacker = next((attacker for attacker in attackers if attacker.has_ability(Ability.FLYING)), attackers[0])
                    legal_blocker = next(
                        (
                            blocker for blocker in blockers
                            if engine.can_creature_be_forced_to_block_attacker(blocker, forced_attacker)
                        ),
                        None,
                    )
                    if legal_blocker is not None:
                        engine.block_assignments[forced_attacker.unit_id] = legal_blocker.unit_id
                        engine.enraged_forced_attackers = {forced_attacker.unit_id}
                start = time.perf_counter()
                planned = choose_builder_blocks(engine.human_player, engine)
                decision_times.append(time.perf_counter() - start)
                attacker_lookup = {attacker.unit_id: attacker for attacker in attackers}
                blocker_lookup = {blocker.unit_id: blocker for blocker in blockers}
                used_blockers = [blocker_id for blocker_id in planned.values() if blocker_id is not None]
                self.assertEqual(len(used_blockers), len(set(used_blockers)))
                self.assertTrue(all(math.isfinite(value) for value in getattr(engine.ai, "_last_builder_block_score").__dict__.values() if isinstance(value, float)))
                if not any(blocker_id is not None for blocker_id in planned.values()):
                    no_block_decisions += 1
                baseline_damage = sum(attacker.sw for attacker in attackers)
                if baseline_damage >= engine.human_player.life and any(blocker_id is not None for blocker_id in planned.values()):
                    lethal_block_decisions += 1
                for attacker_id, blocker_id in planned.items():
                    attacker = attacker_lookup.get(attacker_id)
                    blocker = blocker_lookup.get(blocker_id) if blocker_id is not None else None
                    if blocker_id is None:
                        continue
                    self.assertIsNotNone(attacker)
                    self.assertIsNotNone(blocker)
                    self.assertTrue(engine.can_creature_block_attacker(blocker, attacker))
                    if blocker.current_hp <= attacker.sw and blocker.sw < attacker.current_hp:
                        chump_blocks += 1
        self.assertTrue(decision_times)
        self.assertTrue(all(math.isfinite(value) for value in decision_times))
        self.assertGreaterEqual(no_block_decisions, 0)
        self.assertGreaterEqual(chump_blocks, 0)
        self.assertGreaterEqual(lethal_block_decisions, 0)


if __name__ == "__main__":
    unittest.main()
