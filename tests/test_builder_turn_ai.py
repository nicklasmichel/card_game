from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import core.config as config
from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.ai.builder import (
    build_builder_runtime_fingerprint,
    build_current_turn_projection,
    evaluate_attack_assignment,
    evaluate_best_builder_attack,
    generate_builder_creature_candidates,
    plan_builder_turn,
    project_creature_action,
    score_builder_creature_candidate,
)
from core.ai.builder.cap_strategy import compute_builder_cap_context
from core.ai.builder.snapshot import build_builder_snapshot
from core.ai.builder.search_budget import FINAL_DECISION_SEARCH_BUDGET
from core.ai.builder.turn_types import BuilderTurnActionCandidate
from core.game_logic import GameEngine
from core.models import PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1, ResourceCard


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
            abilities=frozenset(),
        )
        creature.tapped = not ready
        creature.summoning_sick = not ready
        if current_hp is not None:
            creature.current_hp = current_hp
        return creature

    def test_build_candidates_are_stats_only(self) -> None:
        candidates = generate_builder_creature_candidates(build_builder_snapshot(self.engine.ai_player, self.engine), 5)
        self.assertTrue(candidates)
        self.assertTrue(all(not candidate.abilities for candidate in candidates))
        self.assertTrue(all(candidate.cost == candidate.aw + candidate.vw + candidate.sw + max(0, candidate.lw - 1) for candidate in candidates))

    def test_projected_creature_is_tapped_and_has_no_hypothetical_abilities(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        candidate = next(candidate for candidate in generate_builder_creature_candidates(build_builder_snapshot(self.engine.ai_player, self.engine), 4) if candidate.cost == 4)
        action = BuilderTurnActionCandidate("creature", candidate, 4, 0, "test")

        projection = project_creature_action(base, action)
        unit = projection.get_unit_by_id(projection.hypothetical_unit_id)

        self.assertEqual(unit.abilities, frozenset())
        self.assertTrue(unit.tapped)
        self.assertTrue(unit.summoning_sickness)
        self.assertNotIn(unit.unit_id, projection.available_attacker_ids)

    def test_runtime_fingerprint_ignores_builder_hand_when_abilities_are_disabled(self) -> None:
        self.assertFalse(BUILDER_ABILITIES_ENABLED)
        template = type("T", (), {"template_id": "builder_ability_flying"})()
        fake_card = type("X", (), {"instance_id": self.engine.make_instance_id(), "template": template})()

        first = build_builder_runtime_fingerprint(self.engine.ai_player, self.engine)
        self.engine.ai_player.hand = [fake_card]
        second = build_builder_runtime_fingerprint(self.engine.ai_player, self.engine)

        self.assertEqual(first, second)

    def test_turn_plan_ignores_fake_builder_hand_and_always_uses_skip_ability(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        first = plan_builder_turn(self.engine.ai_player, self.engine)
        template = type("T", (), {"template_id": "builder_ability_haste"})()
        self.engine.ai_player.hand = [type("X", (), {"instance_id": self.engine.make_instance_id(), "template": template})()]
        second = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(first.action_candidate, second.action_candidate)
        self.assertEqual(first.predicted_attack_decision.candidate, second.predicted_attack_decision.candidate)
        self.assertEqual(first.ability_action.action_kind, "skip")
        self.assertEqual(second.ability_action.action_kind, "skip")

    def test_new_creature_is_never_planned_as_attacker_in_creation_turn(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 3)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        if decision.action_candidate.action_kind == "creature":
            created_signature = decision.action_candidate.creature_candidate.signature
            self.assertNotIn(created_signature, [attacker_id for attacker_id in decision.predicted_attack_decision.candidate.attacker_ids if attacker_id < 0])
            self.assertEqual(decision.score.draw_value, 0.0)

    def test_turn_planner_does_not_offer_creature_action_at_cap(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 7)
        for _ in range(self.engine.BUILDER_CREATURE_CAP):
            self.make_builder_creature(1, aw=2, vw=2, sw=2, lw=3, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertNotEqual(decision.action_candidate.action_kind, "creature")

    def test_planning_does_not_mutate_runtime_state(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)
        before = (
            build_builder_runtime_fingerprint(self.engine.ai_player, self.engine),
            self.engine.builder_creature_counter,
            tuple(card.instance_id for card in self.engine.ai_player.hand),
        )

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        after = (
            build_builder_runtime_fingerprint(self.engine.ai_player, self.engine),
            self.engine.builder_creature_counter,
            tuple(card.instance_id for card in self.engine.ai_player.hand),
        )
        self.assertIsNotNone(decision)
        self.assertEqual(before, after)

    def test_suicide_attack_without_trade_or_damage_is_not_chosen(self) -> None:
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.is_human = False
        attacker = self.make_builder_creature(1, aw=0, vw=0, sw=5, lw=1, ready=True)
        self.make_builder_creature(0, aw=0, vw=1, sw=1, lw=6, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.predicted_attack_decision.candidate.attacker_ids, ())
        self.assertEqual(decision.score.draw_value, 0.0)
        self.assertIsNotNone(attacker)

    def test_damage_glass_cannon_is_devalued_without_real_hit_line(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=3, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertNotEqual(decision.action_candidate.creature_candidate.signature, (0, 0, 5, 1))

    def test_attack_at_cap_values_block_and_nonblock_for_weak_damage_body(self) -> None:
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.is_human = False
        self.set_builder_resources(self.engine.ai_player, 10)
        weak = self.make_builder_creature(1, aw=0, vw=0, sw=4, lw=1, ready=True)
        self.make_builder_creature(1, aw=0, vw=1, sw=0, lw=5, ready=True)
        self.make_builder_creature(1, aw=0, vw=1, sw=0, lw=5, ready=True)
        self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=False)
        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=3, ready=True)

        blocker = self.make_builder_creature(0, aw=0, vw=1, sw=1, lw=3, ready=True)
        self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=True)

        cap_context = compute_builder_cap_context(
            self.engine.ai_player,
            self.engine,
            creature_cap=self.engine.BUILDER_CREATURE_CAP,
            resource_budget=self.engine.ai_player.total_resources(),
        )
        self.assertTrue(cap_context.at_cap)
        self.assertGreater(cap_context.replacement_value, 0.0)

        empty_block = evaluate_attack_assignment(
            type("C", (), {"attacker_ids": (weak.unit_id,), "enraged_targets": ()})(),
            (),
            self.engine.ai_player,
            self.engine.human_player,
            self.engine,
            cap_context=cap_context,
        )
        blocked = evaluate_attack_assignment(
            type("C", (), {"attacker_ids": (weak.unit_id,), "enraged_targets": ()})(),
            ((weak.unit_id, blocker.unit_id),),
            self.engine.ai_player,
            self.engine.human_player,
            self.engine,
            cap_context=cap_context,
        )

        self.assertEqual(empty_block.player_damage, 4.0)
        self.assertEqual(blocked.player_damage, 0.0)
        self.assertGreaterEqual(blocked.own_death_risk, 0.0)

        decision = evaluate_best_builder_attack(
            self.engine.ai_player,
            self.engine,
            search_budget=FINAL_DECISION_SEARCH_BUDGET,
        )
        self.assertIn(weak.unit_id, decision.candidate.attacker_ids)
        self.assertEqual(decision.score.chosen_block_assignment, ((weak.unit_id, blocker.unit_id),))

    def test_cap_attack_is_not_forced_without_meaningful_replacement(self) -> None:
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.is_human = False
        self.set_builder_resources(self.engine.ai_player, 4)
        weak = self.make_builder_creature(1, aw=0, vw=0, sw=4, lw=1, ready=True)
        self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.make_builder_creature(0, aw=0, vw=1, sw=1, lw=3, ready=True)

        decision = evaluate_best_builder_attack(
            self.engine.ai_player,
            self.engine,
            search_budget=FINAL_DECISION_SEARCH_BUDGET,
        )
        self.assertNotIn(weak.unit_id, decision.candidate.attacker_ids)

    def test_defensive_build_values_real_kill_breakpoints_against_glass_cannon(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 9)
        self.make_builder_creature(0, aw=5, vw=0, sw=5, lw=1, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        candidate = decision.action_candidate.creature_candidate
        self.assertGreaterEqual(candidate.sw, 1)
        self.assertGreaterEqual(candidate.vw, 2)
        self.assertNotEqual(candidate.signature, (0, 1, 0, 9))

    def test_life_only_wall_is_not_overvalued_against_real_threat(self) -> None:
        self.make_builder_creature(0, aw=5, vw=0, sw=5, lw=1, ready=True)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        wall = next(candidate for candidate in generate_builder_creature_candidates(snapshot, 10) if candidate.signature == (0, 1, 0, 9))
        breaker = next(candidate for candidate in generate_builder_creature_candidates(snapshot, 10) if candidate.signature == (0, 3, 1, 7))

        wall_score = score_builder_creature_candidate(
            wall,
            snapshot,
            available_resources=10,
            enemy_creatures=list(self.engine.human_player.battlefield),
            own_creatures=list(self.engine.ai_player.battlefield),
        )
        breaker_score = score_builder_creature_candidate(
            breaker,
            snapshot,
            available_resources=10,
            enemy_creatures=list(self.engine.human_player.battlefield),
            own_creatures=list(self.engine.ai_player.battlefield),
        )

        self.assertGreater(breaker_score.matchup_defense, wall_score.matchup_defense)
        self.assertGreater(breaker_score.total, wall_score.total)

    def test_resource_can_beat_bad_early_build(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 2)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "resource")

    def test_creature_is_built_under_pressure(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        self.make_builder_creature(0, aw=2, vw=1, sw=3, lw=2, ready=True)
        self.make_builder_creature(0, aw=2, vw=1, sw=2, lw=2, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")

    def test_draw_value_is_always_zero_in_vanilla_builder(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.make_builder_creature(1, aw=2, vw=2, sw=3, lw=3, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.score.draw_value, 0.0)

    def test_scores_remain_finite_and_deterministic(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.set_builder_resources(self.engine.human_player, 5)
        self.make_builder_creature(1, aw=2, vw=2, sw=2, lw=3, ready=True)
        self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True)

        first = plan_builder_turn(self.engine.ai_player, self.engine)
        second = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(first.action_candidate, second.action_candidate)
        self.assertEqual(first.predicted_attack_decision.candidate, second.predicted_attack_decision.candidate)
        self.assertEqual(first.ability_action.action_kind, "skip")
        self.assertTrue(all(math.isfinite(value) for value in first.score.__dict__.values() if isinstance(value, float)))

    def test_builder_attack_phase_uses_planned_attack(self) -> None:
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.ai_player.is_human = False
        attacker = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True)

        self.assertTrue(self.engine.prepare_ai_turn_action())
        pending = self.engine.pending_ai_action
        self.assertEqual(pending["kind"], "declare_attackers")
        self.assertEqual(pending["attacker_ids"], [attacker.unit_id])


if __name__ == "__main__":
    unittest.main()
