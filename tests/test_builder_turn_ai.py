from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import core.config as config
from core.ai.builder import (
    BuilderAttackCandidate,
    BuilderAttackDecision,
    BuilderAttackScore,
    BuilderProjectedCandidate,
    BuilderSearchMetadata,
    TURN_LOOKAHEAD_SEARCH_BUDGET,
    build_current_turn_projection,
    build_builder_snapshot,
    evaluate_best_builder_attack,
    plan_builder_turn,
    project_creature_action,
    project_resource_action,
)
from core.ai.builder.attack_policy import GUARANTEED_LETHAL_BONUS
from core.ai.builder.scoring import score_builder_creature_candidate
from core.ai.builder.turn_policy import _build_action_decision, _shortlist_projected_candidates, extract_candidate_future_value
from core.ai.builder.turn_types import BuilderTurnActionCandidate
from core.game_logic import GameEngine
from core.models import Ability, PHASE_MAIN_1, ResourceCard


class BuilderTurnAITests(unittest.TestCase):
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

    def _static_projected_candidate(self, candidate):
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        static_score = score_builder_creature_candidate(
            candidate,
            snapshot,
            available_resources=self.engine.ai_player.available_resources(),
            enemy_creatures=list(self.engine.human_player.battlefield),
            own_creatures=list(self.engine.ai_player.battlefield),
        )
        return BuilderProjectedCandidate(
            candidate=candidate,
            static_score=static_score,
            future_value=extract_candidate_future_value(static_score, candidate, snapshot),
            shortlist_reasons=("test",),
        )

    def _dummy_attack_decision(self, *, total: float, player_damage: float = 0.0, lethal_value: float = 0.0, attack_ids=(), exact=True):
        return BuilderAttackDecision(
            candidate=BuilderAttackCandidate(attacker_ids=tuple(attack_ids)),
            score=BuilderAttackScore(
                player_damage=player_damage,
                enemy_creature_damage=0.0,
                own_creature_damage=0.0,
                enemy_kill_value=0.0,
                own_death_risk=0.0,
                lifesteal_value=0.0,
                board_position_value=0.0,
                vigilance_value=0.0,
                lethal_value=lethal_value,
                total=total,
                lethal_probability=1.0 if lethal_value >= GUARANTEED_LETHAL_BONUS else 0.0,
                guaranteed_player_damage=player_damage,
                chosen_block_assignment=(),
            ),
            defensive_response=(),
            search_metadata=BuilderSearchMetadata(
                exact_search=exact,
                generated_attack_candidates=1,
                evaluated_attack_candidates=1,
                generated_block_assignments=1,
                evaluated_block_assignments=1,
                pruned_candidates=0,
                search_budget_name="test",
            ),
        )

    def test_resource_projection_adds_resource_and_keeps_board_read_only(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4, tapped=1)
        self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)
        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        projected = project_resource_action(base)

        self.assertEqual(projected.own_total_resources, 5)
        self.assertEqual(projected.own_ready_resources, 4)
        self.assertEqual(tuple(unit.unit_id for unit in projected.own_units), tuple(unit.unit_id for unit in base.own_units))
        self.assertEqual(self.engine.ai_player.total_resources(), 4)
        self.assertEqual(self.engine.ai_player.available_resources(), 3)

    def test_creature_projection_is_projection_only_and_tracks_haste_legality(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        non_haste = BuilderTurnActionCandidate(
            action_kind="creature",
            creature_candidate=self._static_projected_candidate(
                self.engine.ai.choose_builder_creature_plan(self.engine.ai_player, self.engine)  # type: ignore[arg-type]
            ).candidate if False else None,
            projected_total_resources=5,
            projected_ready_resources=0,
        )
        candidate = next(
            projected.candidate
            for projected in _shortlist_projected_candidates(
                [
                    self._static_projected_candidate(candidate)
                    for candidate in __import__("core.ai.builder.candidates", fromlist=["generate_builder_creature_candidates"]).generate_builder_creature_candidates(  # noqa: E501
                        build_builder_snapshot(self.engine.ai_player, self.engine),
                        self.engine.ai_player.available_resources(),
                    )
                    if candidate.cost == 5 and Ability.HASTE not in candidate.abilities
                ],
                5,
            )
        )
        haste_candidate = next(
            projected.candidate
            for projected in [
                self._static_projected_candidate(candidate)
                for candidate in __import__("core.ai.builder.candidates", fromlist=["generate_builder_creature_candidates"]).generate_builder_creature_candidates(
                    build_builder_snapshot(self.engine.ai_player, self.engine),
                    self.engine.ai_player.available_resources(),
                )
                if candidate.cost == 5 and Ability.HASTE in candidate.abilities
            ]
        )
        non_haste_action = BuilderTurnActionCandidate("creature", candidate, 5, 0, "test")
        haste_action = BuilderTurnActionCandidate("creature", haste_candidate, 5, 0, "test")

        non_haste_projection = project_creature_action(base, non_haste_action)
        haste_projection = project_creature_action(base, haste_action)

        self.assertEqual(self.engine.ai_player.total_resources(), 5)
        self.assertEqual(len(self.engine.ai_player.battlefield), 0)
        self.assertIsNotNone(non_haste_projection.hypothetical_unit_id)
        self.assertNotIn(non_haste_projection.hypothetical_unit_id, non_haste_projection.available_attacker_ids)
        self.assertIn(haste_projection.hypothetical_unit_id, haste_projection.available_attacker_ids)
        self.assertTrue(non_haste_projection.get_unit_by_id(non_haste_projection.hypothetical_unit_id).tapped)
        self.assertFalse(haste_projection.get_unit_by_id(haste_projection.hypothetical_unit_id).tapped)

    def test_resource_projection_keeps_existing_attackers_available(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)
        self.set_builder_resources(self.engine.ai_player, 3)
        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        resource_projection = project_resource_action(base)

        self.assertIn(attacker.unit_id, base.available_attacker_ids)
        self.assertEqual(base.available_attacker_ids, resource_projection.available_attacker_ids)

    def test_non_haste_candidates_reuse_baseline_attack(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        candidates = __import__("core.ai.builder.candidates", fromlist=["generate_builder_creature_candidates"]).generate_builder_creature_candidates(
            snapshot,
            self.engine.ai_player.available_resources(),
        )
        non_haste = [candidate for candidate in candidates if candidate.cost == 5 and Ability.HASTE not in candidate.abilities][:2]
        haste = next(candidate for candidate in candidates if candidate.cost == 5 and Ability.HASTE in candidate.abilities)
        projected = [self._static_projected_candidate(candidate) for candidate in non_haste + [haste]]
        calls = []

        def spy(player, context, search_budget):
            calls.append((context.action_kind, context.hypothetical_unit_id))
            if context.hypothetical_unit_id is not None:
                return self._dummy_attack_decision(total=3.0, player_damage=2.0, attack_ids=(context.hypothetical_unit_id,))
            return self._dummy_attack_decision(total=1.0, player_damage=0.0)

        with patch("core.ai.builder.turn_policy._build_projected_candidates", return_value=(projected, False)), patch(
            "core.ai.builder.turn_policy._shortlist_projected_candidates",
            side_effect=lambda values, _: values,
        ), patch("core.ai.builder.turn_policy.evaluate_best_builder_attack", side_effect=spy):
            plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(len(calls), 2)
        self.assertEqual(sum(1 for action_kind, _ in calls if action_kind == "current"), 1)
        self.assertEqual(sum(1 for action_kind, _ in calls if action_kind == "creature"), 1)

    def test_haste_lethal_is_preferred_over_resource_and_non_haste(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 3)
        self.engine.human_player.life = 1

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertIsNotNone(decision.action_candidate.creature_candidate)
        self.assertIn(Ability.HASTE, decision.action_candidate.creature_candidate.abilities)
        self.assertGreaterEqual(decision.predicted_attack_decision.score.lethal_value, GUARANTEED_LETHAL_BONUS)

    def test_resource_can_be_preferred_on_safe_low_resource_board(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 2)
        self.set_builder_resources(self.engine.human_player, 2)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "resource")

    def test_creature_is_preferred_under_pressure(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.set_builder_resources(self.engine.human_player, 5)
        self.engine.ai_player.life = 5
        self.make_builder_creature(0, aw=3, vw=2, sw=3, lw=4, abilities=(Ability.FLYING,), ready=True)
        self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")

    def test_full_budget_build_is_preferred(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertEqual(decision.action_candidate.creature_candidate.cost, 5)

    def test_prepare_ai_turn_action_uses_same_creature_candidate_as_turn_plan(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.ai_player.is_human = False
        self.engine.phase = PHASE_MAIN_1
        decision = self.engine.ai.choose_builder_turn_plan(self.engine.ai_player, self.engine)
        self.assertTrue(self.engine.prepare_ai_turn_action())
        pending = self.engine.pending_ai_action
        if decision.action_candidate.action_kind == "creature":
            self.assertEqual(pending["kind"], "builder_create_creature")
            self.assertEqual(pending["plan"]["candidate_signature"], decision.action_candidate.creature_candidate.signature)
        else:
            self.assertEqual(pending["kind"], "builder_add_resource")

    def test_turn_decision_is_deterministic_and_read_only(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)
        self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True)
        before = (
            self.engine.ai_player.life,
            self.engine.ai_player.total_resources(),
            self.engine.ai_player.available_resources(),
            tuple((creature.unit_id, creature.current_hp, creature.tapped, creature.summoning_sick) for creature in self.engine.ai_player.battlefield),
            self.engine.builder_creature_counter,
            self.engine.phase,
        )

        first = plan_builder_turn(self.engine.ai_player, self.engine)
        second = plan_builder_turn(self.engine.ai_player, self.engine)
        after = (
            self.engine.ai_player.life,
            self.engine.ai_player.total_resources(),
            self.engine.ai_player.available_resources(),
            tuple((creature.unit_id, creature.current_hp, creature.tapped, creature.summoning_sick) for creature in self.engine.ai_player.battlefield),
            self.engine.builder_creature_counter,
            self.engine.phase,
        )

        self.assertEqual(first.action_candidate, second.action_candidate)
        self.assertAlmostEqual(first.score.total, second.score.total, places=6)
        self.assertEqual(before, after)

    def test_turn_lookahead_uses_heuristic_budget_on_six_vs_six(self) -> None:
        for index in range(6):
            self.make_builder_creature(1, aw=2, vw=1, sw=2 + (index % 2), lw=2, ready=True)
            self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3 + (index % 2), ready=True)

        projection = build_current_turn_projection(self.engine.ai_player, self.engine)
        decision = evaluate_best_builder_attack(
            projection.players[self.engine.ai_player.player_id],
            projection,
            search_budget=TURN_LOOKAHEAD_SEARCH_BUDGET,
        )

        self.assertFalse(decision.search_metadata.exact_search)
        self.assertGreater(decision.search_metadata.pruned_candidates, 0)

    def test_turn_scores_remain_finite(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 10)
        self.set_builder_resources(self.engine.human_player, 10)
        self.make_builder_creature(1, aw=0, vw=1, sw=0, lw=1, ready=True, abilities=(Ability.FLYING,))
        self.make_builder_creature(0, aw=0, vw=1, sw=0, lw=1, ready=True, abilities=(Ability.FLYING, Ability.ENRAGED))

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertTrue(all(math.isfinite(value) for value in decision.score.__dict__.values() if isinstance(value, float)))


if __name__ == "__main__":
    unittest.main()
