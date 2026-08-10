from __future__ import annotations

import unittest
from unittest.mock import patch

import core.config as config
from core.ai.builder import (
    build_builder_snapshot,
    choose_builder_creature_candidate,
    choose_builder_main_action,
    generate_builder_creature_candidates,
    is_legal_builder_candidate,
    score_builder_creature_candidate,
)
from core.ai.builder.candidates import candidate_cost
from core.ai.builder.main_policy import score_builder_resource_action
from core.ai.builder.types import BuilderCreatureCandidate
from core.game_logic import GameEngine
from core.models import Ability, PHASE_GAME_OVER, PHASE_MAIN_1, PlayerState, ResourceCard


class BuilderAITests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(config, "GAME_MODE", "builder")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = GameEngine()
        self.engine.log_messages.clear()

    def make_builder_resource(self, *, tapped: bool = False) -> ResourceCard:
        return ResourceCard(
            template=self.engine.builder_resource_template(),
            resource_id=self.engine.make_instance_id(),
            tapped=tapped,
        )

    def set_builder_resources(self, player, total: int, *, tapped: int = 0) -> None:
        player.resources = [self.make_builder_resource(tapped=index < tapped) for index in range(total)]

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

    def test_snapshot_aggregates_relevant_builder_state(self) -> None:
        self.set_builder_resources(self.engine.human_player, 5, tapped=1)
        self.set_builder_resources(self.engine.ai_player, 4, tapped=2)
        self.engine.human_player.life = 8
        self.engine.ai_player.life = 11
        self.make_builder_creature(0, aw=2, vw=1, sw=3, lw=4, abilities=(Ability.FLYING,), ready=True, current_hp=3)
        self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=2, ready=False, current_hp=2)
        self.make_builder_creature(1, aw=3, vw=1, sw=2, lw=3, abilities=(Ability.FLYING,), ready=True, current_hp=2)

        snapshot = build_builder_snapshot(self.engine.human_player, self.engine)

        self.assertEqual(snapshot.own_life, 8)
        self.assertEqual(snapshot.enemy_life, 11)
        self.assertEqual(snapshot.own_total_resources, 5)
        self.assertEqual(snapshot.own_ready_resources, 4)
        self.assertEqual(snapshot.enemy_total_resources, 4)
        self.assertEqual(snapshot.enemy_ready_resources, 2)
        self.assertEqual(snapshot.own_creature_count, 2)
        self.assertEqual(snapshot.enemy_creature_count, 1)
        self.assertEqual(snapshot.own_total_aw, 3)
        self.assertEqual(snapshot.own_total_vw, 3)
        self.assertEqual(snapshot.own_total_sw, 4)
        self.assertEqual(snapshot.own_total_current_hp, 5)
        self.assertEqual(snapshot.enemy_total_aw, 3)
        self.assertEqual(snapshot.enemy_total_vw, 1)
        self.assertEqual(snapshot.enemy_total_sw, 2)
        self.assertEqual(snapshot.enemy_total_current_hp, 2)
        self.assertEqual(snapshot.own_flying_count, 1)
        self.assertEqual(snapshot.enemy_flying_count, 1)
        self.assertEqual(snapshot.own_ready_attacker_count, 1)
        self.assertEqual(snapshot.enemy_potential_attacker_count, 1)
        self.assertAlmostEqual(snapshot.board_value_difference, snapshot.own_board_value - snapshot.enemy_board_value, places=3)

    def test_candidate_cost_formula_matches_builder_rules(self) -> None:
        candidate = BuilderCreatureCandidate(
            aw=2,
            vw=1,
            sw=2,
            lw=3,
            abilities=frozenset({Ability.FLYING, Ability.TRAMPLE}),
            cost=9,
        )

        self.assertEqual(candidate_cost(aw=2, vw=1, sw=2, lw=3, abilities_count=2), 9)
        self.assertTrue(is_legal_builder_candidate(candidate, 9))

    def test_candidate_legality_rejects_invalid_values_and_budget_overflow(self) -> None:
        valid = BuilderCreatureCandidate(aw=1, vw=1, sw=1, lw=2, abilities=frozenset({Ability.HASTE}), cost=5)
        overflow = BuilderCreatureCandidate(aw=1, vw=1, sw=1, lw=2, abilities=frozenset({Ability.HASTE}), cost=6)
        invalid_life = BuilderCreatureCandidate(aw=0, vw=0, sw=0, lw=0, abilities=frozenset(), cost=0)
        invalid_cost = BuilderCreatureCandidate(aw=1, vw=0, sw=0, lw=1, abilities=frozenset(), cost=0)

        self.assertTrue(is_legal_builder_candidate(valid, 5))
        self.assertFalse(is_legal_builder_candidate(overflow, 5))
        self.assertFalse(is_legal_builder_candidate(invalid_life, 5))
        self.assertFalse(is_legal_builder_candidate(invalid_cost, 5))

    def test_candidate_generation_is_exhaustive_and_legal_for_small_budgets(self) -> None:
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        for budget in range(1, 5):
            candidates = generate_builder_creature_candidates(snapshot, budget)
            self.assertGreater(len(candidates), 3)
            self.assertEqual(len(candidates), len({candidate.signature for candidate in candidates}))
            self.assertTrue(all(is_legal_builder_candidate(candidate, budget) for candidate in candidates))

    def test_candidate_generation_for_large_budgets_contains_varied_builds_and_sub_budgets(self) -> None:
        self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, abilities=(Ability.FLYING,), ready=True)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        candidates = generate_builder_creature_candidates(snapshot, 10)

        self.assertTrue(any(candidate.aw >= 4 for candidate in candidates))
        self.assertTrue(any(candidate.vw >= 4 for candidate in candidates))
        self.assertTrue(any(candidate.sw >= 4 for candidate in candidates))
        self.assertTrue(any(candidate.lw >= 5 for candidate in candidates))
        self.assertTrue(any({Ability.HASTE, Ability.TRAMPLE}.issubset(candidate.abilities) for candidate in candidates))
        self.assertTrue(any({Ability.VIGILANT, Ability.LIFE_STEAL}.issubset(candidate.abilities) for candidate in candidates))
        self.assertTrue(any(candidate.cost < 10 for candidate in candidates))

    def test_scoring_rewards_contextual_ability_value(self) -> None:
        candidate_trample_low = BuilderCreatureCandidate(aw=1, vw=0, sw=0, lw=1, abilities=frozenset({Ability.TRAMPLE}), cost=2)
        candidate_trample_high = BuilderCreatureCandidate(aw=1, vw=0, sw=4, lw=1, abilities=frozenset({Ability.TRAMPLE}), cost=6)
        candidate_lifesteal_low = BuilderCreatureCandidate(aw=0, vw=0, sw=0, lw=3, abilities=frozenset({Ability.LIFE_STEAL}), cost=3)
        candidate_lifesteal_high = BuilderCreatureCandidate(aw=0, vw=0, sw=4, lw=3, abilities=frozenset({Ability.LIFE_STEAL}), cost=7)

        empty_snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        no_flying_score = score_builder_creature_candidate(
            BuilderCreatureCandidate(aw=2, vw=1, sw=2, lw=2, abilities=frozenset({Ability.FLYING}), cost=6),
            empty_snapshot,
            available_resources=6,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.make_builder_creature(0, aw=2, vw=1, sw=2, lw=2, abilities=(Ability.FLYING,), ready=True)
        self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, abilities=(Ability.FLYING,), ready=True)
        crowded_flying_snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        many_flying_score = score_builder_creature_candidate(
            BuilderCreatureCandidate(aw=2, vw=1, sw=2, lw=2, abilities=frozenset({Ability.FLYING}), cost=6),
            crowded_flying_snapshot,
            available_resources=6,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.make_builder_creature(0, aw=2, vw=1, sw=2, lw=2, ready=True)
        board_snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        empty_board_snapshot = build_builder_snapshot(self.engine.human_player, self.engine)
        empty_board_score = score_builder_creature_candidate(
            BuilderCreatureCandidate(aw=2, vw=1, sw=2, lw=2, abilities=frozenset({Ability.ENRAGED}), cost=6),
            empty_board_snapshot,
            available_resources=6,
            enemy_creatures=list(self.engine.ai_player.battlefield),
        )
        board_score = score_builder_creature_candidate(
            BuilderCreatureCandidate(aw=2, vw=1, sw=2, lw=2, abilities=frozenset({Ability.ENRAGED}), cost=6),
            board_snapshot,
            available_resources=6,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )
        vigilant_low = score_builder_creature_candidate(
            BuilderCreatureCandidate(aw=0, vw=0, sw=0, lw=1, abilities=frozenset({Ability.VIGILANT}), cost=1),
            board_snapshot,
            available_resources=4,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )
        vigilant_good = score_builder_creature_candidate(
            BuilderCreatureCandidate(aw=2, vw=2, sw=1, lw=3, abilities=frozenset({Ability.VIGILANT}), cost=8),
            board_snapshot,
            available_resources=8,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.assertGreater(
            score_builder_creature_candidate(candidate_trample_high, empty_snapshot, available_resources=6).total,
            score_builder_creature_candidate(candidate_trample_low, empty_snapshot, available_resources=2).total,
        )
        self.assertGreater(
            score_builder_creature_candidate(candidate_lifesteal_high, empty_snapshot, available_resources=7).total,
            score_builder_creature_candidate(candidate_lifesteal_low, empty_snapshot, available_resources=3).total,
        )
        self.assertGreater(no_flying_score.total, many_flying_score.total)
        self.assertGreater(board_score.total, empty_board_score.total)
        self.assertGreater(vigilant_good.total, vigilant_low.total)

    def test_synergy_build_scores_above_bad_ability_stack(self) -> None:
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        strong = BuilderCreatureCandidate(
            aw=1,
            vw=1,
            sw=4,
            lw=3,
            abilities=frozenset({Ability.TRAMPLE, Ability.LIFE_STEAL}),
            cost=9,
        )
        weak = BuilderCreatureCandidate(
            aw=1,
            vw=1,
            sw=4,
            lw=3,
            abilities=frozenset({Ability.VIGILANT, Ability.ENRAGED}),
            cost=9,
        )

        self.assertGreater(
            score_builder_creature_candidate(strong, snapshot, available_resources=9).total,
            score_builder_creature_candidate(weak, snapshot, available_resources=9).total,
        )

    def test_build_policy_returns_highest_scored_legal_candidate(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 6)
        best_candidate, best_score, snapshot, scored_candidates = choose_builder_creature_candidate(self.engine.ai_player, self.engine)
        plan = self.engine.ai.choose_builder_creature_plan(self.engine.ai_player, self.engine)

        self.assertIsNotNone(best_candidate)
        self.assertIsNotNone(best_score)
        self.assertTrue(scored_candidates)
        self.assertEqual(plan["aw"], best_candidate.aw)
        self.assertEqual(plan["vw"], best_candidate.vw)
        self.assertEqual(plan["sw"], best_candidate.sw)
        self.assertEqual(plan["lw"], best_candidate.lw)
        self.assertEqual(set(plan["abilities"]), set(best_candidate.abilities))
        recomputed_best = max(
            (
                score_builder_creature_candidate(candidate, snapshot, available_resources=6).total,
                candidate.signature,
            )
            for candidate in generate_builder_creature_candidates(snapshot, 6)
            if is_legal_builder_candidate(candidate, 6)
        )
        self.assertEqual((best_score.total, best_candidate.signature), recomputed_best)

    def test_main_policy_never_chooses_resource_at_ten_resources(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 10)

        self.assertEqual(choose_builder_main_action(self.engine.ai_player, self.engine), "creature")

    def test_main_policy_prefers_creature_when_board_is_empty_and_enemy_is_ahead(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.set_builder_resources(self.engine.human_player, 5)
        self.make_builder_creature(0, aw=3, vw=2, sw=3, lw=4, abilities=(Ability.FLYING,), ready=True)
        self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True)

        self.assertEqual(choose_builder_main_action(self.engine.ai_player, self.engine), "creature")

    def test_main_policy_can_prefer_resource_in_safe_early_state(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 2)
        self.set_builder_resources(self.engine.human_player, 2)

        self.assertEqual(choose_builder_main_action(self.engine.ai_player, self.engine), "resource")
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        self.assertGreater(score_builder_resource_action(snapshot, self.engine.BUILDER_MAX_RESOURCES), 0)

    def test_builder_ai_smoke_games_run_without_illegal_actions(self) -> None:
        for seed in range(3):
            with self.subTest(seed=seed):
                patcher = patch.object(config, "GAME_MODE", "builder")
                patcher.start()
                self.addCleanup(patcher.stop)
                engine = GameEngine()
                engine.seed = seed
                engine.players = [
                    PlayerState(0, "Spieler", False, summoner_key="builder", life=10, resources=[self.make_builder_resource()]),
                    PlayerState(1, "Gegner", False, summoner_key="builder", life=10, resources=[self.make_builder_resource()]),
                ]
                engine.active_player_index = 0
                engine.phase = PHASE_MAIN_1
                engine.turn_number = 0
                engine.reset_combat_state()

                steps = 0
                while engine.phase != PHASE_GAME_OVER and steps < 120:
                    steps += 1
                    if engine.phase == PHASE_MAIN_1:
                        self.assertTrue(engine.prepare_ai_turn_action())
                        pending = engine.pending_ai_action
                        if pending["kind"] == "builder_add_resource":
                            self.assertLess(engine.active_player.total_resources(), engine.BUILDER_MAX_RESOURCES)
                        if pending["kind"] == "builder_create_creature":
                            plan = pending["plan"]
                            self.assertGreaterEqual(plan["cost"], 0)
                            self.assertLessEqual(plan["cost"], engine.active_player.available_resources())
                        engine.execute_prepared_ai_action()
                        continue
                    if engine.phase in {"Angreifer waehlen", "Blocker waehlen"}:
                        engine.process_ai_turn()
                        continue
                    if engine.phase == "Wuerfelkampf":
                        engine.end_dice_battle()
                        continue
                    break

                self.assertLess(steps, 120)
                self.assertGreater(
                    engine.human_player.total_resources() + engine.ai_player.total_resources()
                    + len(engine.human_player.battlefield) + len(engine.ai_player.battlefield),
                    2,
                )
