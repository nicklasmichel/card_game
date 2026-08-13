from __future__ import annotations

import math
import unittest
from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.ai.builder import (
    build_builder_runtime_fingerprint,
    build_current_turn_projection,
    evaluate_main_action_horizon,
    evaluate_attack_assignment,
    evaluate_best_builder_attack,
    generate_builder_creature_candidates,
    plan_builder_turn,
    project_attack_to_next_turn,
    project_creature_action,
    score_builder_creature_candidate,
)
from core.ai.builder.cap_strategy import compute_builder_cap_context
from core.ai.builder.snapshot import build_builder_snapshot
from core.ai.builder.search_budget import FINAL_DECISION_SEARCH_BUDGET
from core.ai.builder.turn_policy import (
    _build_projected_candidates,
    _shortlist_projected_candidates,
    evaluate_builder_next_main_value,
)
from core.ai.builder.turn_types import BuilderTurnActionCandidate
from core.game_logic import GameEngine
from core.models import Ability, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1, ResourceCard


class BuilderTurnAITests(unittest.TestCase):
    def setUp(self) -> None:
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
            abilities=frozenset(abilities or (Ability.VIGILANCE,)),
        )
        creature.tapped = not ready
        creature.summoning_sick = not ready
        if current_hp is not None:
            creature.current_hp = current_hp
        return creature

    def test_build_candidates_include_haste_and_non_haste_variants(self) -> None:
        candidates = generate_builder_creature_candidates(build_builder_snapshot(self.engine.ai_player, self.engine), 5)
        self.assertTrue(candidates)
        self.assertTrue(all(len(candidate.abilities) == 1 for candidate in candidates))
        self.assertTrue(any(candidate.has_haste for candidate in candidates))
        self.assertTrue(any(not candidate.has_haste for candidate in candidates))
        self.assertTrue(any(candidate.has_ability(Ability.FLYING) for candidate in candidates))
        self.assertTrue(any(candidate.has_ability(Ability.VIGILANCE) for candidate in candidates))
        self.assertTrue(any(candidate.has_ability(Ability.TRAMPLE) for candidate in candidates))
        self.assertTrue(all(candidate.cost == candidate.aw + candidate.vw + candidate.sw + max(0, candidate.lw - 1) for candidate in candidates))

    def test_projected_non_haste_creature_is_tapped_and_not_immediately_available(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        candidate = next(
            candidate
            for candidate in generate_builder_creature_candidates(build_builder_snapshot(self.engine.ai_player, self.engine), 4)
            if candidate.cost == 4 and not candidate.has_haste
        )
        action = BuilderTurnActionCandidate("creature", candidate, 4, 0, "test")

        projection = project_creature_action(base, action)
        unit = projection.get_unit_by_id(projection.hypothetical_unit_id)

        self.assertEqual(len(unit.abilities), 1)
        self.assertTrue(unit.tapped)
        self.assertTrue(unit.summoning_sickness)
        self.assertNotIn(unit.unit_id, projection.available_attacker_ids)

    def test_projected_haste_creature_is_ready_and_available_immediately(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        candidate = next(
            candidate
            for candidate in generate_builder_creature_candidates(build_builder_snapshot(self.engine.ai_player, self.engine), 4)
            if candidate.cost == 4 and candidate.has_haste
        )
        action = BuilderTurnActionCandidate("creature", candidate, 4, 0, "test")

        projection = project_creature_action(base, action)
        unit = projection.get_unit_by_id(projection.hypothetical_unit_id)

        self.assertTrue(unit.has_ability(Ability.HASTE))
        self.assertFalse(unit.tapped)
        self.assertFalse(unit.summoning_sickness)
        self.assertIn(unit.unit_id, projection.available_attacker_ids)

    def test_projected_non_haste_creature_becomes_ready_on_controller_next_turn(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        candidate = next(
            candidate
            for candidate in generate_builder_creature_candidates(build_builder_snapshot(self.engine.ai_player, self.engine), 4)
            if candidate.cost == 4 and not candidate.has_haste
        )
        action = BuilderTurnActionCandidate("creature", candidate, 4, 0, "test")

        projection = project_creature_action(base, action)
        unit_id = projection.hypothetical_unit_id
        enemy_turn = project_attack_to_next_turn(projection, ())
        next_own_turn = project_attack_to_next_turn(enemy_turn, ())
        unit = next_own_turn.get_unit_by_id(unit_id)

        self.assertFalse(unit.tapped)
        self.assertFalse(unit.summoning_sickness)
        self.assertIn(unit.unit_id, next_own_turn.available_attacker_ids)

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

    def test_non_haste_new_creature_is_never_planned_as_attacker_in_creation_turn(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 3)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        if decision.action_candidate.action_kind == "creature" and not decision.action_candidate.creature_candidate.has_haste:
            self.assertFalse(any(attacker_id < 0 for attacker_id in decision.predicted_attack_decision.candidate.attacker_ids))
            self.assertEqual(decision.score.draw_value, 0.0)

    def test_ai_can_choose_haste_for_immediate_attack(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 2)
        self.engine.ai_player.life = 10
        self.engine.human_player.life = 1

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertTrue(decision.action_candidate.creature_candidate.has_haste)
        self.assertTrue(any(attacker_id < 0 for attacker_id in decision.predicted_attack_decision.candidate.attacker_ids))

    def test_ai_can_choose_haste_for_immediate_blocker_readiness(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.engine.ai_player.life = 1
        self.make_builder_creature(0, aw=1, vw=1, sw=3, lw=2, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertTrue(decision.action_candidate.creature_candidate.has_haste)
        self.assertGreater(decision.action_candidate.creature_candidate.vw, 0)
        self.assertFalse(any(attacker_id < 0 for attacker_id in decision.predicted_attack_decision.candidate.attacker_ids))

    def test_flying_build_projects_next_turn_lethal_without_timely_blocker(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 7)
        self.engine.human_player.life = 6
        for _ in range(4):
            self.make_builder_creature(1, aw=0, vw=1, sw=0, lw=2, ready=True)
        for _ in range(2):
            self.make_builder_creature(0, aw=0, vw=3, sw=0, lw=3, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertEqual(decision.action_candidate.creature_candidate.key, (0, 1, 6, 1, "FLYING"))
        self.assertTrue(decision.score.own_next_attack_lethal)
        self.assertEqual(decision.score.own_next_attack_damage, 6.0)
        self.assertEqual(decision.score.turns_to_own_lethal, 1)
        self.assertFalse(decision.score.enemy_blocker_ready_in_time)
        self.assertGreaterEqual(decision.score.future_offense_value, 100.0)
        self.assertGreaterEqual(decision.score.board_slot_opportunity_cost, 0.0)

    def test_existing_ready_flying_blocker_prevents_projected_next_turn_lethal(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 7)
        self.engine.human_player.life = 6
        for _ in range(4):
            self.make_builder_creature(1, aw=0, vw=1, sw=0, lw=2, ready=True)
        self.make_builder_creature(0, aw=0, vw=3, sw=0, lw=3, ready=True)
        self.make_builder_creature(0, aw=0, vw=1, sw=0, lw=2, ready=True, abilities=(Ability.FLYING,))

        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        candidate = next(
            current
            for current in generate_builder_creature_candidates(snapshot, 7)
            if current.key == (0, 1, 6, 1, "FLYING")
        )
        action = BuilderTurnActionCandidate("creature", candidate, 7, 0, "test")
        projection = project_creature_action(base, action)
        predicted_attack = evaluate_best_builder_attack(projection.players[projection.player_id], projection)
        report = evaluate_main_action_horizon(projection, predicted_attack)

        self.assertFalse(report.own_next_attack_lethal)
        self.assertIsNone(report.turns_to_own_lethal)

    def test_ai_can_choose_haste_when_it_removes_immediate_followup_damage(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 2)
        self.engine.ai_player.life = 2
        self.make_builder_creature(0, aw=2, vw=1, sw=3, lw=2, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertTrue(decision.action_candidate.creature_candidate.has_haste)
        self.assertEqual(decision.score.expected_enemy_followup_damage, 0.0)
        self.assertEqual(decision.score.enemy_lethal_risk, 0.0)

    def test_haste_candidate_does_not_count_as_future_flying_coverage(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 8)
        self.engine.ai_player.life = 10
        self.engine.human_player.life = 20
        self.make_builder_creature(0, aw=4, vw=0, sw=5, lw=1, ready=True, abilities=(Ability.FLYING,))
        for _ in range(2):
            self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=2, ready=True)

        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        candidate = next(
            current
            for current in generate_builder_creature_candidates(snapshot, 8)
            if current.key == (0, 1, 7, 1, "HASTE")
        )
        action = BuilderTurnActionCandidate("creature", candidate, 8, 0, "test")
        projection = project_creature_action(base, action)
        predicted_attack = evaluate_best_builder_attack(projection.players[projection.player_id], projection)
        report = evaluate_main_action_horizon(projection, predicted_attack)

        self.assertFalse(report.coverage_prevents_repeated_lethal)
        self.assertIsNone(report.coverage_ready_turn)
        self.assertEqual(report.second_attack_damage, 5.0)
        self.assertEqual(report.cumulative_unavoidable_damage, 10.0)

    def test_flying_build_can_prevent_repeated_known_flying_lethal(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 8)
        self.engine.ai_player.life = 10
        self.engine.human_player.life = 20
        self.make_builder_creature(0, aw=4, vw=0, sw=5, lw=1, ready=True, abilities=(Ability.FLYING,))
        for _ in range(2):
            self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=2, ready=True)
        for _ in range(2):
            self.make_builder_creature(0, aw=0, vw=3, sw=0, lw=3, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertEqual(decision.action_candidate.creature_candidate.key, (0, 1, 7, 1, "FLYING"))
        self.assertTrue(decision.score.coverage_prevents_repeated_lethal)
        self.assertEqual(decision.score.second_attack_damage, 5.0)
        self.assertEqual(decision.score.cumulative_unavoidable_damage, 5.0)
        self.assertEqual(decision.score.coverage_ready_turn, 1)
        self.assertTrue(decision.score.must_hold_as_blocker)

    def test_planning_with_haste_candidates_does_not_mutate_runtime_state(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        before = (
            build_builder_runtime_fingerprint(self.engine.ai_player, self.engine),
            self.engine.builder_creature_counter,
        )
        decision = plan_builder_turn(self.engine.ai_player, self.engine)
        after = (
            build_builder_runtime_fingerprint(self.engine.ai_player, self.engine),
            self.engine.builder_creature_counter,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(before, after)

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
        legal_attackers = set(decision.candidate.attacker_ids)
        legal_blockers = {creature.unit_id for creature in self.engine.human_player.battlefield}
        self.assertTrue(
            all(attacker_id in legal_attackers and blocker_id in legal_blockers for attacker_id, blocker_id in decision.score.chosen_block_assignment)
        )

    def test_cap_attack_assignment_remains_legal_without_meaningful_replacement(self) -> None:
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
        available_ids = {creature.unit_id for creature in self.engine.available_attackers(self.engine.ai_player)}
        self.assertTrue(set(decision.candidate.attacker_ids).issubset(available_ids))

    def test_defensive_build_values_real_kill_breakpoints_against_glass_cannon(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 9)
        self.engine.ai_player.life = 2
        self.make_builder_creature(0, aw=5, vw=0, sw=5, lw=1, ready=True)
        self.make_builder_creature(0, aw=5, vw=0, sw=5, lw=1, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        candidate = decision.action_candidate.creature_candidate
        self.assertGreaterEqual(candidate.sw, 1)
        self.assertGreaterEqual(candidate.vw, 2)
        self.assertFalse(any(attacker_id < 0 for attacker_id in decision.predicted_attack_decision.candidate.attacker_ids))
        self.assertNotEqual(candidate.signature, (0, 1, 0, 9))

    def test_life_only_wall_is_not_overvalued_against_real_threat(self) -> None:
        self.make_builder_creature(0, aw=5, vw=0, sw=5, lw=1, ready=True)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        wall = next(candidate for candidate in generate_builder_creature_candidates(snapshot, 10) if candidate.signature == (0, 1, 0, 10))
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

    def test_shortlist_retains_matchup_specific_high_defense_haste_blocker(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        self.set_builder_resources(self.engine.human_player, 4)
        for aw, sw in ((2, 3), (3, 2)):
            self.make_builder_creature(0, aw=aw, vw=0, sw=sw, lw=1, ready=True, abilities=(Ability.HASTE,))

        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        projected, _, _ = _build_projected_candidates(self.engine.ai_player, self.engine, snapshot)
        shortlisted = _shortlist_projected_candidates(projected, snapshot)

        self.assertIn((0, 3, 1, 1, "HASTE"), {current.candidate.key for current in shortlisted})

    def test_earlier_pressure_state_prefers_durable_haste_blocker(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        self.set_builder_resources(self.engine.human_player, 4)
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.life = 8
        for aw, sw in ((2, 3), (3, 2)):
            self.make_builder_creature(0, aw=aw, vw=0, sw=sw, lw=1, ready=True, abilities=(Ability.HASTE,))

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertEqual(decision.action_candidate.creature_candidate.key, (0, 3, 1, 1, "HASTE"))

    def test_forced_loss_state_logs_honest_width_based_loss(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 4)
        self.set_builder_resources(self.engine.human_player, 5)
        self.engine.phase = PHASE_MAIN_1
        self.engine.ai_player.life = 6
        self.engine.debug_log_to_messages = True
        self.make_builder_creature(1, aw=0, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(1, aw=1, vw=0, sw=1, lw=2, ready=True, abilities=(Ability.HASTE,))
        for stats in ((2, 0, 3, 1), (3, 0, 2, 1), (2, 0, 3, 1), (2, 0, 3, 1)):
            self.make_builder_creature(0, aw=stats[0], vw=stats[1], sw=stats[2], lw=stats[3], ready=True, abilities=(Ability.HASTE,))

        decision = plan_builder_turn(self.engine.ai_player, self.engine)
        logs = "\n".join(self.engine.log_messages)

        self.assertLess(decision.score.selection_score, -9000.0)
        self.assertEqual(decision.predicted_attack_decision.score.projected_counter_main_action, "build_haste")
        self.assertEqual(len(decision.predicted_attack_decision.score.projected_counter_attackers), 5)
        self.assertIn("forced_loss_all_actions=true", logs)

    def test_resource_can_beat_bad_early_build(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 2)
        self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "resource")

    def test_regression_curve_after_first_valid_haste_prefers_resource_over_redundant_second_body(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 2)
        self.set_builder_resources(self.engine.human_player, 3)
        self.engine.ai_player.life = 18
        self.make_builder_creature(1, aw=0, vw=0, sw=2, lw=1, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "resource")

    def test_regression_full_weak_board_values_open_response_slot_against_future_flyer(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.set_builder_resources(self.engine.human_player, 5)
        self.engine.ai_player.life = 10
        self.engine.human_player.life = 20
        self.make_builder_creature(1, aw=0, vw=0, sw=2, lw=1, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=1, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=1, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=2, ready=True, abilities=(Ability.HASTE,))
        flyer = self.make_builder_creature(0, aw=0, vw=1, sw=5, lw=1, ready=False, abilities=(Ability.FLYING,))

        open_projection = build_current_turn_projection(self.engine.ai_player, self.engine)
        open_value, open_action, open_stats = evaluate_builder_next_main_value(open_projection)

        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=2, ready=True, abilities=(Ability.HASTE,))
        full_projection = build_current_turn_projection(self.engine.ai_player, self.engine)
        full_value, full_action, _ = evaluate_builder_next_main_value(full_projection)

        self.assertEqual(open_action, "creature")
        self.assertIn("flying", open_stats)
        self.assertLess(full_value, open_value)
        self.assertIsNotNone(flyer)

    def test_horizon_includes_delayed_high_damage_flying_build_from_enemy_frontier(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.set_builder_resources(self.engine.human_player, 5)
        self.engine.ai_player.life = 10
        self.engine.human_player.life = 20
        self.make_builder_creature(1, aw=0, vw=0, sw=2, lw=1, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=1, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=1, ready=True, abilities=(Ability.HASTE,))
        self.make_builder_creature(1, aw=0, vw=1, sw=1, lw=2, ready=True, abilities=(Ability.HASTE,))

        base = build_current_turn_projection(self.engine.ai_player, self.engine)
        predicted_attack = evaluate_best_builder_attack(base.players[base.player_id], base)
        report = evaluate_main_action_horizon(base, predicted_attack)

        self.assertEqual(report.defense_response_main_action, "build_flying")
        self.assertTrue(report.known_enemy_attack_timeline)
        self.assertEqual(report.known_enemy_attack_timeline[0].first_attack_damage, 0.0)
        self.assertEqual(report.known_enemy_attack_timeline[0].second_attack_damage, 5.0)
        self.assertEqual(report.second_attack_damage, 5.0)

    def test_safe_state_can_prefer_resource_over_redundant_fifth_creature(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.set_builder_resources(self.engine.human_player, 4)
        for _ in range(4):
            self.make_builder_creature(1, aw=0, vw=1, sw=0, lw=2, ready=True)
        self.make_builder_creature(0, aw=0, vw=1, sw=1, lw=2, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "resource")

    def test_fifth_slot_can_be_used_for_necessary_haste_blocker(self) -> None:
        self.set_builder_resources(self.engine.ai_player, 5)
        self.engine.ai_player.life = 1
        for _ in range(4):
            self.make_builder_creature(1, aw=0, vw=1, sw=0, lw=2, ready=True)
        self.make_builder_creature(0, aw=1, vw=1, sw=3, lw=2, ready=True)

        decision = plan_builder_turn(self.engine.ai_player, self.engine)

        self.assertEqual(decision.action_candidate.action_kind, "creature")
        self.assertTrue(decision.action_candidate.creature_candidate.has_haste)
        self.assertEqual(self.engine.ai_player.total_resources(), 5)

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
