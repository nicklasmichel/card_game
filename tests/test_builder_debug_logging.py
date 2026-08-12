from __future__ import annotations

import unittest
from unittest.mock import patch

import core.config as config
from core.ai.builder import choose_builder_blocks, evaluate_best_builder_attack, plan_builder_turn
from core.game_logic import GameEngine
from core.models import Ability, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_MAIN_1, ResourceCard


class BuilderDebugLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.multiple(
            config,
            AI_DEBUG=0,
            AI_DEBUG_TOP_N=3,
            AI_DEBUG_BUILD_TOP_N=3,
            AI_DEBUG_FLOAT_PRECISION=2,
            AI_DEBUG_INCLUDE_WEIGHTS=1,
            AI_DEBUG_INCLUDE_FINGERPRINTS=1,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_engine(self) -> GameEngine:
        engine = GameEngine()
        engine.debug_log_to_messages = True
        engine.log_messages.clear()
        return engine

    def make_builder_resource(self, engine: GameEngine, *, tapped: bool = False) -> ResourceCard:
        return ResourceCard(
            template=engine.builder_resource_template(),
            resource_id=engine.make_instance_id(),
            tapped=tapped,
        )

    def set_builder_resources(self, engine: GameEngine, player, total: int, *, tapped: int = 0) -> None:
        player.resources = [self.make_builder_resource(engine, tapped=index < tapped) for index in range(total)]

    def make_builder_creature(
        self,
        engine: GameEngine,
        owner_id: int,
        *,
        aw: int,
        vw: int,
        sw: int,
        lw: int,
        ready: bool = True,
    ):
        player = engine.players[owner_id]
        creature = engine.create_builder_creature(
            player,
            aw=aw,
            vw=vw,
            sw=sw,
            lw=lw,
            abilities=frozenset({Ability.VIGILANCE}),
        )
        creature.tapped = not ready
        creature.summoning_sick = not ready
        return creature

    def set_debug(self, level: int, *, top_n: int = 3, build_top_n: int = 3, include_weights: int = 1, include_fingerprints: int = 1) -> None:
        config.AI_DEBUG = level
        config.AI_DEBUG_TOP_N = top_n
        config.AI_DEBUG_BUILD_TOP_N = build_top_n
        config.AI_DEBUG_INCLUDE_WEIGHTS = include_weights
        config.AI_DEBUG_INCLUDE_FINGERPRINTS = include_fingerprints

    def debug_lines(self, logs: list[str], prefix: str | None = None) -> list[str]:
        lines = [line for line in logs if line.startswith("[AI ") or line.startswith("[RUNTIME]")]
        if prefix is None:
            return lines
        return [line for line in lines if line.startswith(prefix)]

    def line_containing(self, logs: list[str], needle: str) -> str:
        return next(line for line in logs if needle in line)

    def make_plan_engine(self) -> GameEngine:
        engine = self.make_engine()
        engine.phase = PHASE_MAIN_1
        self.set_builder_resources(engine, engine.ai_player, 4)
        self.make_builder_creature(engine, 1, aw=2, vw=0, sw=2, lw=1, ready=True)
        self.make_builder_creature(engine, 0, aw=1, vw=1, sw=1, lw=1, ready=True)
        return engine

    def make_pass_engine(self) -> GameEngine:
        engine = self.make_engine()
        engine.phase = PHASE_MAIN_1
        self.set_builder_resources(engine, engine.ai_player, engine.BUILDER_MAX_RESOURCES)
        for _ in range(engine.BUILDER_CREATURE_CAP):
            self.make_builder_creature(engine, 1, aw=1, vw=1, sw=1, lw=2, ready=True)
        return engine

    def make_attack_engine(self) -> GameEngine:
        engine = self.make_engine()
        engine.phase = PHASE_DECLARE_ATTACKERS
        engine.active_player_index = engine.ai_player.player_id
        engine.ai_player.is_human = False
        self.set_builder_resources(engine, engine.ai_player, 4)
        engine.ai_player.life = 1
        engine.human_player.life = 5
        self.make_builder_creature(engine, 1, aw=0, vw=3, sw=1, lw=1, ready=True)
        self.make_builder_creature(engine, 1, aw=0, vw=3, sw=1, lw=1, ready=True)
        self.make_builder_creature(engine, 1, aw=0, vw=2, sw=2, lw=1, ready=True)
        self.make_builder_creature(engine, 0, aw=2, vw=1, sw=2, lw=1, ready=True)
        self.make_builder_creature(engine, 0, aw=2, vw=0, sw=2, lw=1, ready=True)
        return engine

    def make_block_engine(self) -> GameEngine:
        engine = self.make_engine()
        engine.phase = PHASE_DECLARE_BLOCKERS
        engine.active_player_index = engine.human_player.player_id
        self.set_builder_resources(engine, engine.ai_player, 4)
        blocker = self.make_builder_creature(engine, 1, aw=0, vw=3, sw=1, lw=1, ready=True)
        self.make_builder_creature(engine, 1, aw=2, vw=0, sw=2, lw=1, ready=True)
        attacker = self.make_builder_creature(engine, 0, aw=1, vw=1, sw=2, lw=1, ready=True)
        engine.block_assignments = {attacker.unit_id: None}
        blocker.tapped = False
        return engine

    def make_cap_attack_engine(self) -> GameEngine:
        engine = self.make_engine()
        engine.phase = PHASE_DECLARE_ATTACKERS
        engine.active_player_index = engine.ai_player.player_id
        engine.ai_player.is_human = False
        self.set_builder_resources(engine, engine.ai_player, 10)
        self.make_builder_creature(engine, 1, aw=0, vw=0, sw=4, lw=1, ready=True)
        self.make_builder_creature(engine, 1, aw=0, vw=1, sw=0, lw=5, ready=True)
        self.make_builder_creature(engine, 1, aw=0, vw=1, sw=0, lw=5, ready=True)
        self.make_builder_creature(engine, 1, aw=1, vw=1, sw=1, lw=2, ready=False)
        self.make_builder_creature(engine, 1, aw=0, vw=1, sw=1, lw=3, ready=True)
        self.make_builder_creature(engine, 0, aw=0, vw=1, sw=1, lw=3, ready=True)
        self.make_builder_creature(engine, 0, aw=1, vw=1, sw=1, lw=2, ready=True)
        return engine

    def plan_signature(self, decision) -> tuple:
        return (
            decision.action_candidate.action_kind,
            None if decision.action_candidate.creature_candidate is None else decision.action_candidate.creature_candidate.key,
            decision.ability_action.action_kind,
            tuple() if decision.predicted_attack_decision is None else decision.predicted_attack_decision.candidate.attacker_ids,
        )

    def attack_signature(self, decision) -> tuple:
        return (
            tuple(decision.candidate.attacker_ids),
            tuple(decision.defensive_response or ()),
        )

    def block_signature(self, result: dict[int, int | None]) -> tuple:
        return tuple(sorted(result.items()))

    def test_debug_zero_emits_no_builder_debug_lines(self) -> None:
        self.set_debug(0)

        plan_engine = self.make_plan_engine()
        plan_builder_turn(plan_engine.ai_player, plan_engine)
        attack_engine = self.make_attack_engine()
        evaluate_best_builder_attack(attack_engine.ai_player, attack_engine)
        block_engine = self.make_block_engine()
        choose_builder_blocks(block_engine.ai_player, block_engine)

        self.assertEqual(self.debug_lines(plan_engine.log_messages), [])
        self.assertEqual(self.debug_lines(attack_engine.log_messages), [])
        self.assertEqual(self.debug_lines(block_engine.log_messages), [])

    def test_debug_level_one_emits_compact_plan_build_attack_block_and_runtime_lines(self) -> None:
        self.set_debug(1, top_n=1, build_top_n=1)

        plan_engine = self.make_plan_engine()
        plan_builder_turn(plan_engine.ai_player, plan_engine)
        self.assertTrue(self.debug_lines(plan_engine.log_messages, "[AI BUILD]"))
        self.assertTrue(self.debug_lines(plan_engine.log_messages, "[AI PLAN]"))
        self.assertIn("candidate=resource", "\n".join(plan_engine.log_messages))
        self.assertIn("candidate=creature", "\n".join(plan_engine.log_messages))

        runtime_engine = self.make_plan_engine()
        runtime_engine.active_player_index = runtime_engine.ai_player.player_id
        runtime_engine.ai_player.is_human = False
        runtime_engine.prepare_ai_turn_action()
        runtime_engine.execute_prepared_ai_action()
        self.assertTrue(self.debug_lines(runtime_engine.log_messages, "[RUNTIME]"))

        attack_engine = self.make_attack_engine()
        evaluate_best_builder_attack(attack_engine.ai_player, attack_engine)
        attack_logs = "\n".join(attack_engine.log_messages)
        self.assertTrue(self.debug_lines(attack_engine.log_messages, "[AI ATTACK]"))
        self.assertIn("attackers=[]", attack_logs)
        self.assertIn("response_policy=adversarial_worst_for_attacker", attack_logs)

        block_engine = self.make_block_engine()
        choose_builder_blocks(block_engine.ai_player, block_engine)
        block_logs = "\n".join(block_engine.log_messages)
        self.assertTrue(self.debug_lines(block_engine.log_messages, "[AI BLOCK]"))
        self.assertIn("blocks=[]", block_logs)
        self.assertIn("blocks=[[", block_logs)

    def test_debug_level_two_emits_weights_state_contributions_and_fingerprints(self) -> None:
        self.set_debug(2, top_n=1, build_top_n=1)

        plan_engine = self.make_plan_engine()
        self.make_builder_creature(plan_engine, 1, aw=2, vw=0, sw=2, lw=1, ready=True)
        plan_builder_turn(plan_engine.ai_player, plan_engine)
        plan_logs = "\n".join(plan_engine.log_messages)
        self.assertIn("[AI WEIGHTS]", plan_logs)
        self.assertIn("[AI STATE]", plan_logs)
        self.assertIn("fingerprint_before=", plan_logs)
        self.assertIn("future_raw=", plan_logs)
        self.assertIn("ability=", plan_logs)
        self.assertIn("ability_cost=", plan_logs)
        self.assertIn("haste_cost=", plan_logs)
        self.assertIn("enters_tapped=", plan_logs)
        self.assertIn("block_reason=defense_zero", plan_logs)
        self.assertNotIn("forced=", plan_logs.lower())

        attack_engine = self.make_attack_engine()
        evaluate_best_builder_attack(attack_engine.ai_player, attack_engine)
        self.assertIn("player_damage_raw=", "\n".join(attack_engine.log_messages))

        block_engine = self.make_block_engine()
        choose_builder_blocks(block_engine.ai_player, block_engine)
        self.assertIn("prevented_player_damage_raw=", "\n".join(block_engine.log_messages))

    def test_decisions_match_across_debug_levels_for_plan_attack_and_block(self) -> None:
        plan_signatures = []
        attack_signatures = []
        block_signatures = []
        for level in (0, 1, 2):
            self.set_debug(level, top_n=2, build_top_n=2)

            plan_engine = self.make_plan_engine()
            plan_signatures.append(self.plan_signature(plan_builder_turn(plan_engine.ai_player, plan_engine)))

            attack_engine = self.make_attack_engine()
            attack_signatures.append(self.attack_signature(evaluate_best_builder_attack(attack_engine.ai_player, attack_engine)))

            block_engine = self.make_block_engine()
            block_signatures.append(self.block_signature(choose_builder_blocks(block_engine.ai_player, block_engine)))

        self.assertEqual(plan_signatures[0], plan_signatures[1])
        self.assertEqual(plan_signatures[0], plan_signatures[2])
        self.assertEqual(attack_signatures[0], attack_signatures[1])
        self.assertEqual(attack_signatures[0], attack_signatures[2])
        self.assertEqual(block_signatures[0], block_signatures[1])
        self.assertEqual(block_signatures[0], block_signatures[2])

    def test_attack_logging_always_shows_no_attack_all_out_and_runner_up_even_when_top_n_is_one(self) -> None:
        self.set_debug(1, top_n=1)
        engine = self.make_attack_engine()

        decision = evaluate_best_builder_attack(engine.ai_player, engine)
        logs = "\n".join(engine.log_messages)
        available_ids = [creature.unit_id for creature in engine.available_attackers(engine.ai_player)]
        self.assertIn("attackers=[]", logs)
        self.assertIn(f"attackers=[{','.join(str(current) for current in available_ids)}]", logs)
        self.assertIn("runner_up=", logs)
        self.assertIn(f"choose=[{','.join(str(current) for current in decision.candidate.attacker_ids)}]", logs)

    def test_main_action_logging_shows_resource_creature_and_pass_when_legal(self) -> None:
        self.set_debug(1, top_n=1, build_top_n=1)

        main_engine = self.make_plan_engine()
        plan_builder_turn(main_engine.ai_player, main_engine)
        main_logs = "\n".join(main_engine.log_messages)
        self.assertIn("candidate=resource", main_logs)
        self.assertIn("candidate=creature", main_logs)

        pass_engine = self.make_pass_engine()
        plan_builder_turn(pass_engine.ai_player, pass_engine)
        self.assertIn("candidate=pass", "\n".join(pass_engine.log_messages))

    def test_build_and_plan_logs_show_ability_and_readiness_fields(self) -> None:
        self.set_debug(1, top_n=3, build_top_n=3)

        engine = self.make_plan_engine()
        plan_builder_turn(engine.ai_player, engine)
        logs = "\n".join(engine.log_messages)

        self.assertIn("ability=", logs)
        self.assertIn("ability_cost=0", logs)
        self.assertIn("haste_cost=0", logs)
        self.assertIn("haste=true", logs)
        self.assertIn("enters_tapped=false", logs)

    def test_gap_matches_winner_minus_runner_up(self) -> None:
        self.set_debug(1, top_n=2, build_top_n=2)

        plan_engine = self.make_plan_engine()
        plan_builder_turn(plan_engine.ai_player, plan_engine)
        choose_line = self.line_containing(plan_engine.log_messages, "choose=")
        parts = dict(token.split("=", 1) for token in choose_line.split() if "=" in token)
        self.assertAlmostEqual(float(parts["total"]) - float(parts["runner_up_total"]), float(parts["gap"]), places=2)

        attack_engine = self.make_attack_engine()
        evaluate_best_builder_attack(attack_engine.ai_player, attack_engine)
        choose_line = self.line_containing(attack_engine.log_messages, "choose=")
        parts = dict(token.split("=", 1) for token in choose_line.split() if "=" in token)
        self.assertAlmostEqual(float(parts["total"]) - float(parts["runner_up_total"]), float(parts["gap"]), places=2)

        block_engine = self.make_block_engine()
        choose_builder_blocks(block_engine.ai_player, block_engine)
        choose_line = self.line_containing(block_engine.log_messages, "choose=")
        parts = dict(token.split("=", 1) for token in choose_line.split() if "=" in token)
        self.assertAlmostEqual(float(parts["total"]) - float(parts["runner_up_total"]), float(parts["gap"]), places=2)

    def test_low_life_attack_logging_contains_all_required_diagnostics(self) -> None:
        self.set_debug(1, top_n=5)
        engine = self.make_attack_engine()

        evaluate_best_builder_attack(engine.ai_player, engine)
        logs = "\n".join(engine.log_messages)

        self.assertIn("attackers=[]", logs)
        self.assertIn("lost_block_value=", logs)
        self.assertIn("projected_counter_damage=", logs)
        self.assertIn("enemy_lethal_risk=", logs)
        self.assertIn("held=[", logs)
        self.assertIn("gap=", logs)
        self.assertTrue(any("attackers=[" in line and "attackers=[]" not in line for line in engine.log_messages))

    def test_attack_logging_marks_counter_search_and_projected_enemy_action(self) -> None:
        self.set_debug(1, top_n=3)
        engine = self.make_engine()
        engine.phase = PHASE_DECLARE_ATTACKERS
        engine.active_player_index = engine.ai_player.player_id
        engine.ai_player.is_human = False
        self.set_builder_resources(engine, engine.human_player, 2)
        self.make_builder_creature(engine, 1, aw=1, vw=1, sw=1, lw=2, ready=True)

        evaluate_best_builder_attack(engine.ai_player, engine)
        logs = "\n".join(engine.log_messages)

        self.assertIn("counter_search_exact=", logs)
        self.assertIn("counter_fallback_used=", logs)
        self.assertIn("projected_enemy_main_action=", logs)
        self.assertIn("projected_enemy_attackers=", logs)

    def test_cap_attack_logging_shows_slot_and_cap_context_without_guaranteeing_release(self) -> None:
        self.set_debug(1, top_n=4)
        engine = self.make_cap_attack_engine()

        evaluate_best_builder_attack(engine.ai_player, engine)
        logs = "\n".join(engine.log_messages)

        self.assertIn("cap_pressure=", logs)
        self.assertIn("replacement_value=", logs)
        self.assertIn("response_policy=adversarial_worst_for_attacker", logs)
        self.assertIn("slot_release_guaranteed=false", logs)
        self.assertTrue("slot_status_if_no_block=occupied" in logs or "slot_release_possible=true" in logs)

    def test_verbose_state_logs_defense_zero_and_new_unit_readiness(self) -> None:
        self.set_debug(2, top_n=1, build_top_n=1)
        engine = self.make_plan_engine()
        self.make_builder_creature(engine, 1, aw=3, vw=0, sw=1, lw=1, ready=True)

        plan_builder_turn(engine.ai_player, engine)
        logs = "\n".join(engine.log_messages)

        self.assertIn("can_block=false", logs)
        self.assertIn("block_reason=defense_zero", logs)
        self.assertIn("new_unit_tapped=", logs)
        self.assertIn("new_unit_can_attack=", logs)
        self.assertIn("new_unit_can_block=", logs)

    def test_simulation_source_is_marked_in_debug_output(self) -> None:
        self.set_debug(1)

        simulation_engine = self.make_attack_engine()
        simulation_engine.simulation_mode = True
        evaluate_best_builder_attack(simulation_engine.ai_player, simulation_engine)
        self.assertIn("source=simulation", "\n".join(simulation_engine.log_messages))

    def test_debug_output_is_deterministic_for_identical_state(self) -> None:
        self.set_debug(1, top_n=2, build_top_n=2)

        first_engine = self.make_attack_engine()
        evaluate_best_builder_attack(first_engine.ai_player, first_engine)
        first_logs = list(first_engine.log_messages)

        second_engine = self.make_attack_engine()
        evaluate_best_builder_attack(second_engine.ai_player, second_engine)
        second_logs = list(second_engine.log_messages)

        self.assertEqual(first_logs, second_logs)


if __name__ == "__main__":
    unittest.main()
