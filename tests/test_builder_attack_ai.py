from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import core.config as config
from core.ai.builder import (
    BuilderAttackCandidate,
    can_legally_be_forced_to_block,
    choose_builder_attack_candidate,
    choose_builder_attackers,
    evaluate_attack_assignment,
    generate_builder_attack_candidates,
    generate_builder_block_assignments,
    score_builder_attack_candidate,
)
from core.game_logic import GameEngine
from core.models import Ability, PHASE_BUILDER_ABILITY, PHASE_GAME_OVER, PHASE_MAIN_1, PlayerState, ResourceCard


class BuilderAttackAITests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(config, "GAME_MODE", "builder")
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_generate_attack_candidates_for_three_attackers_has_eight_attack_sets(self) -> None:
        a = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        b = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        c = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)

        candidates = generate_builder_attack_candidates(self.engine.ai_player, self.engine)
        attack_sets = {candidate.attacker_ids for candidate in candidates}

        self.assertEqual(len(attack_sets), 8)
        self.assertIn((), attack_sets)
        self.assertIn((a.unit_id, b.unit_id, c.unit_id), attack_sets)

    def test_only_legal_available_attackers_are_included(self) -> None:
        ready = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True)
        self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=False)
        haste = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.HASTE,))

        attack_sets = {candidate.attacker_ids for candidate in generate_builder_attack_candidates(self.engine.ai_player, self.engine)}

        self.assertIn((ready.unit_id,), attack_sets)
        self.assertIn((haste.unit_id,), attack_sets)
        self.assertNotIn(tuple(sorted(unit.unit_id for unit in self.engine.ai_player.battlefield if not unit.is_ready())), attack_sets)

    def test_flying_attacker_against_ground_only_board_has_no_block_assignment(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True, abilities=(Ability.FLYING,))
        self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        candidate = BuilderAttackCandidate(attacker_ids=(attacker.unit_id,))

        assignments = generate_builder_block_assignments(candidate, self.engine.ai_player, self.engine.human_player, self.engine)

        self.assertEqual(assignments, [tuple()])

    def test_single_blocking_assignments_never_reuse_blocker(self) -> None:
        a1 = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        a2 = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        blocker = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)
        candidate = BuilderAttackCandidate(attacker_ids=(a1.unit_id, a2.unit_id))

        assignments = generate_builder_block_assignments(candidate, self.engine.ai_player, self.engine.human_player, self.engine)

        self.assertTrue(all(len(assignment) <= 1 for assignment in assignments))
        self.assertTrue(all(sum(1 for _, blocker_id in assignment if blocker_id == blocker.unit_id) <= 1 for assignment in assignments))

    def test_basic_unblocked_attack_is_better_than_no_attack(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)

        candidate, score, _ = choose_builder_attack_candidate(self.engine.ai_player, self.engine)

        self.assertEqual(candidate.attacker_ids, (attacker.unit_id,))
        self.assertGreater(score.total, 0)

    def test_bad_trade_prefers_no_attack(self) -> None:
        self.make_builder_creature(1, aw=4, vw=1, sw=1, lw=1, ready=True, abilities=(Ability.FLYING, Ability.TRAMPLE))
        self.make_builder_creature(0, aw=1, vw=4, sw=4, lw=6, ready=True, abilities=(Ability.FLYING,))

        candidate, _, _ = choose_builder_attack_candidate(self.engine.ai_player, self.engine)

        self.assertEqual(candidate.attacker_ids, ())

    def test_vigilant_attack_gets_preservation_value(self) -> None:
        vigilant = self.make_builder_creature(1, aw=2, vw=2, sw=2, lw=3, ready=True, abilities=(Ability.VIGILANT,))
        non_vigilant = self.make_builder_creature(1, aw=2, vw=2, sw=2, lw=3, ready=True)
        self.make_builder_creature(0, aw=3, vw=1, sw=3, lw=3, ready=True)

        vigilant_score = score_builder_attack_candidate(BuilderAttackCandidate(attacker_ids=(vigilant.unit_id,)), self.engine.ai_player, self.engine)
        normal_score = score_builder_attack_candidate(BuilderAttackCandidate(attacker_ids=(non_vigilant.unit_id,)), self.engine.ai_player, self.engine)

        self.assertGreater(vigilant_score.vigilance_value, normal_score.vigilance_value)

    def test_trample_attack_uses_expected_overflow(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=5, lw=3, ready=True, abilities=(Ability.TRAMPLE,))
        blocker = self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=1, ready=True)

        score = evaluate_attack_assignment(
            BuilderAttackCandidate(attacker_ids=(attacker.unit_id,)),
            ((attacker.unit_id, blocker.unit_id),),
            self.engine.ai_player,
            self.engine.human_player,
            self.engine,
        )

        self.assertGreater(score.player_damage, 0)

    def test_lifesteal_attack_values_healing_only_when_damaged(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=4, lw=5, ready=True, abilities=(Ability.LIFE_STEAL,), current_hp=3)
        blocker = self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=True)
        candidate = BuilderAttackCandidate(attacker_ids=(attacker.unit_id,))
        assignment = ((attacker.unit_id, blocker.unit_id),)

        damaged = evaluate_attack_assignment(candidate, assignment, self.engine.ai_player, self.engine.human_player, self.engine)
        attacker.current_hp = attacker.lw
        full = evaluate_attack_assignment(candidate, assignment, self.engine.ai_player, self.engine.human_player, self.engine)

        self.assertGreater(damaged.lifesteal_value, full.lifesteal_value)

    def test_enraged_can_force_blocker_away_from_second_attacker(self) -> None:
        enraged = self.make_builder_creature(1, aw=3, vw=1, sw=3, lw=3, ready=True, abilities=(Ability.ENRAGED,))
        finisher = self.make_builder_creature(1, aw=2, vw=1, sw=4, lw=2, ready=True)
        blocker = self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True)
        no_forced = BuilderAttackCandidate(attacker_ids=(enraged.unit_id, finisher.unit_id))
        forced = BuilderAttackCandidate(attacker_ids=(enraged.unit_id, finisher.unit_id), enraged_targets=((enraged.unit_id, blocker.unit_id),))

        no_forced_score = score_builder_attack_candidate(no_forced, self.engine.ai_player, self.engine)
        forced_score = score_builder_attack_candidate(forced, self.engine.ai_player, self.engine)

        self.assertGreater(forced_score.player_damage, no_forced_score.player_damage)
        self.assertGreater(forced_score.total, no_forced_score.total)

    def test_enraged_target_is_optional(self) -> None:
        enraged = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=1, ready=True, abilities=(Ability.ENRAGED,))
        strong_blocker = self.make_builder_creature(0, aw=3, vw=4, sw=4, lw=5, ready=True)
        optional = BuilderAttackCandidate(attacker_ids=(enraged.unit_id,))
        forced = BuilderAttackCandidate(attacker_ids=(enraged.unit_id,), enraged_targets=((enraged.unit_id, strong_blocker.unit_id),))

        self.assertGreaterEqual(
            score_builder_attack_candidate(optional, self.engine.ai_player, self.engine).total,
            score_builder_attack_candidate(forced, self.engine.ai_player, self.engine).total,
        )

    def test_two_attackers_one_blocker_understands_only_one_can_be_blocked(self) -> None:
        a1 = self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)
        a2 = self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
        self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)

        score = score_builder_attack_candidate(BuilderAttackCandidate(attacker_ids=(a1.unit_id, a2.unit_id)), self.engine.ai_player, self.engine)

        self.assertGreater(score.player_damage, 0)

    def test_opponent_uses_worst_response_block(self) -> None:
        strong = self.make_builder_creature(1, aw=3, vw=1, sw=4, lw=3, ready=True)
        weak = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        tough = self.make_builder_creature(0, aw=1, vw=3, sw=3, lw=4, ready=True)
        cheap = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=2, ready=True)

        score = score_builder_attack_candidate(BuilderAttackCandidate(attacker_ids=(strong.unit_id, weak.unit_id)), self.engine.ai_player, self.engine)

        self.assertIn(score.chosen_block_assignment, {
            ((strong.unit_id, tough.unit_id), (weak.unit_id, cheap.unit_id)),
            ((strong.unit_id, tough.unit_id),),
        })

    def test_guaranteed_lethal_is_chosen(self) -> None:
        attacker = self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True, abilities=(Ability.FLYING,))
        self.engine.human_player.life = 3

        candidate, score, _ = choose_builder_attack_candidate(self.engine.ai_player, self.engine)

        self.assertEqual(candidate.attacker_ids, (attacker.unit_id,))
        self.assertGreaterEqual(score.guaranteed_player_damage, 3)

    def test_attack_decision_is_deterministic(self) -> None:
        self.make_builder_creature(1, aw=2, vw=1, sw=3, lw=2, ready=True)
        self.make_builder_creature(1, aw=3, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.ENRAGED,))
        self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=3, ready=True)

        first = choose_builder_attack_candidate(self.engine.ai_player, self.engine)[0]
        second = choose_builder_attack_candidate(self.engine.ai_player, self.engine)[0]

        self.assertEqual(first, second)

    def test_attack_selection_with_five_attackers_and_five_blockers_is_fast(self) -> None:
        for _ in range(5):
            self.make_builder_creature(1, aw=2, vw=1, sw=2, lw=2, ready=True)
            self.make_builder_creature(0, aw=2, vw=2, sw=2, lw=3, ready=True)

        start = time.perf_counter()
        choose_builder_attack_candidate(self.engine.ai_player, self.engine)
        self.assertLess(time.perf_counter() - start, 1.0)

    def test_builder_attack_smoke_games(self) -> None:
        attack_turns = 0
        skipped_attack_turns = 0
        eval_times = []
        for seed in range(20):
            with self.subTest(seed=seed):
                with patch.object(config, "GAME_MODE", "builder"):
                    engine = GameEngine()
                    engine.seed = seed
                    engine.players = [
                        PlayerState(0, "Spieler", False, summoner_key="builder", life=10, resources=[self.make_builder_resource(engine)]),
                        PlayerState(1, "Gegner", False, summoner_key="builder", life=10, resources=[self.make_builder_resource(engine)]),
                    ]
                    engine.active_player_index = 0
                    engine.phase = PHASE_MAIN_1
                    engine.turn_number = 0
                    engine.reset_combat_state()
                    steps = 0
                    while engine.phase != PHASE_GAME_OVER and steps < 160:
                        steps += 1
                        if engine.phase == "Angreifer waehlen" and not engine.active_player.is_human:
                            start = time.perf_counter()
                            candidate, score, _ = choose_builder_attack_candidate(engine.active_player, engine)
                            eval_times.append(time.perf_counter() - start)
                            self.assertFalse(score.total != score.total)
                            attackers = choose_builder_attackers(engine.active_player, engine)
                            planned = getattr(engine.ai, "_last_builder_enraged_targets", {})
                            for attacker_id, blocker_id in planned.items():
                                attacker = engine.get_unit_by_id(attacker_id)
                                blocker = engine.get_unit_by_id(blocker_id)
                                self.assertIsNotNone(attacker)
                                self.assertIsNotNone(blocker)
                                self.assertTrue(can_legally_be_forced_to_block(attacker, blocker, require_ready=True))
                            if attackers:
                                attack_turns += 1
                            else:
                                skipped_attack_turns += 1
                        if engine.phase in {PHASE_MAIN_1, PHASE_BUILDER_ABILITY}:
                            self.assertTrue(engine.prepare_ai_turn_action())
                            engine.execute_prepared_ai_action()
                            continue
                        if engine.phase in {"Angreifer waehlen", "Blocker waehlen"}:
                            engine.process_ai_turn()
                            continue
                        if engine.phase == "Wuerfelkampf":
                            engine.end_dice_battle()
                            continue
                        break
                    self.assertLess(steps, 160)
        self.assertGreaterEqual(attack_turns + skipped_attack_turns, 1)
        self.assertTrue(eval_times)
