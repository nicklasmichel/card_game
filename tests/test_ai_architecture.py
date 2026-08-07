from __future__ import annotations

from dataclasses import dataclass

from core.ai.air.registry import get_air_card_handler, get_air_creature_handler
from core.ai import ActionCandidate, BoundPlan, DecisionReason, build_ai_context
from core.ai.plan_manager import PlanManager
from core.ai.plans import PLAN_STATUS_DISCARDED, PlanStep, TurnPlan
from core.ai.simple_ai import HeuristicStrategicAI, SimpleAI, StrategicAI
from core.ai.strategies.base import StrategyDecision, StrategyMetric, StrategyWeights
from core.ai.strategies.generic import DefaultDeckStrategy
from core.models import CardInstance
from tests.helpers import EngineTestCase


@dataclass(slots=True)
class DummyStrategy:
    mode: str = "DUMMY"

    def evaluate(self, ai, player, engine, *, hand, available_resources: int, total_resources: int, phase: str) -> StrategyDecision:
        return StrategyDecision(
            mode=self.mode,
            primary_goal="dummy_goal",
            reason_codes=("dummy_strategy",),
            weights=StrategyWeights(player_damage=1.1),
            metrics=(StrategyMetric("phase", phase),),
        )


class RecordingReactionPlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def choose_spell(self, ai, hand, engine):
        self.calls.append(("choose_spell", tuple(card.instance_id for card in hand)))
        return None

    def choose_spell_target_ref(self, ai, player, engine, card, pending):
        self.calls.append(("choose_spell_target_ref", card.instance_id))
        return None


class RecordingAssessmentComponent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def estimate_best_attack_plan(self, ai, player, enemy, hand, sequence, *, engine=None, attack_bonus_amount: int = 0):
        self.calls.append(("estimate_best_attack_plan", tuple(sequence)))
        return {
            "score": 0.0,
            "attacker_ids": [],
            "target_id": None,
            "direct_damage": 0,
            "enemy_kills": 0,
            "own_losses": 0,
            "is_lethal": False,
        }


class RecordingEffectEvaluatorComponent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def evaluate_bounce_plan(self, ai, player, engine, card, **kwargs):
        self.calls.append(("evaluate_bounce_plan", card.instance_id))
        return {"is_useful": False, "value": -4.0, "target_ids": [], "recast_target": False}


class RecordingTurnPlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def build_turn_plan_payload(self, ai, player, engine, *, hand, available_resources: int, total_resources: int, phase: str) -> dict:
        self.calls.append(("build_turn_plan_payload", phase))
        return {
            "main1_resource_card_ids": [],
            "sequence": [],
            "attacker_ids": [],
            "expected_attack_damage": 0,
            "graveyard_target_ids": [],
            "bounce_target_ids": [],
            "himmelswende_target_ids": [],
            "main2_resource_card_ids": [],
            "main2_sequence": [],
            "main2_graveyard_target_ids": [],
            "main2_bounce_target_ids": [],
            "reason_codes": (),
            "strategy_mode": "TEST",
            "primary_goal": "test_goal",
            "strategy_reason_codes": (),
            "strategy_weights": StrategyWeights(),
            "strategy_metrics": (),
            "reserved_resources": 0,
            "reaction_intents": (),
            "combat_started": False,
            "_plan_total": 0.0,
        }

    def choose_attackers_for_player(self, ai, player, engine, creatures):
        self.calls.append(("choose_attackers_for_player", len(creatures)))
        return []

    def choose_resource_card_for_main_phase(self, ai, player, engine, phase: str):
        self.calls.append(("choose_resource_card_for_main_phase", phase))
        return None

    def choose_main_phase_card(self, ai, player, engine):
        self.calls.append(("choose_main_phase_card", engine.phase))
        return None

    def clear_active_turn_plan(self, ai) -> None:
        self.calls.append(("clear_active_turn_plan", None))


class AiArchitectureTests(EngineTestCase):
    def test_public_ai_entrypoints_are_importable(self) -> None:
        self.assertIsNotNone(SimpleAI)
        self.assertIs(SimpleAI, HeuristicStrategicAI)
        self.assertIs(StrategicAI, HeuristicStrategicAI)
        self.assertIsNotNone(ActionCandidate)
        self.assertIsNotNone(BoundPlan)
        self.assertIsNotNone(DecisionReason)

    def test_air_registry_exposes_specialized_handlers(self) -> None:
        for template_id in (
            "air_ritual_aufwind",
            "air_ritual_rueckenwind",
            "air_ritual_windruf",
            "air_ritual_sturmruf",
            "air_ritual_himmelswende",
            "air_spell_verwirbelung",
            "air_spell_verwehung",
            "air_spell_jagdwind",
            "air_spell_sturmjagd",
            "air_ritual_orkanwende",
        ):
            with self.subTest(template_id=template_id):
                self.assertIsNotNone(get_air_card_handler(template_id))

    def test_air_creature_registry_exposes_final_air_creature_handlers(self) -> None:
        for template_id in (
            "air_creature_windschwinge",
            "air_creature_sturmschwinge",
            "air_creature_orkanschwinge",
            "air_creature_windgeist",
            "air_creature_sturmgeist",
            "air_creature_orkangeist",
            "air_creature_windwesen",
            "air_creature_sturmwesen",
            "air_creature_orkanwesen",
            "air_creature_luftelementar",
        ):
            with self.subTest(template_id=template_id):
                self.assertIsNotNone(get_air_creature_handler(template_id))

    def test_build_ai_context_exposes_visible_state_only(self) -> None:
        self.engine.phase = "summoning"
        self.engine.creatures_died_this_turn = 3
        wolkenschwinge_resource = self.make_resource("air_creature_windschwinge")
        wolkenschwinge_resource.tapped = True
        self.engine.ai_player.resources = [wolkenschwinge_resource]

        context = build_ai_context(self.engine, self.engine.ai_player)

        self.assertEqual(context.player, self.engine.ai_player)
        self.assertEqual(context.enemy, self.engine.human_player)
        self.assertEqual(context.phase, "summoning")
        self.assertEqual(context.available_resources, 0)
        self.assertEqual(context.total_resources, 1)
        self.assertEqual(context.tapped_resource_ids, (wolkenschwinge_resource.resource_id,))
        self.assertEqual(context.creatures_died_this_turn, 3)

    def test_action_candidate_can_hold_structured_reason(self) -> None:
        reason = DecisionReason("resource_loss_too_high", {"remaining_resources": 1, "draw_count": 2})
        candidate = ActionCandidate(
            action_type="cast_spell",
            card_instance_id=42,
            reserved_resources=1,
            recycle_cost=2,
            score=3.5,
            reason=reason,
        )
        plan = BoundPlan(sequence=(42,), reserved_resources=1, reason=reason)

        self.assertEqual(candidate.reason.reason_code, "resource_loss_too_high")
        self.assertEqual(candidate.reason.metrics["remaining_resources"], 1)
        self.assertEqual(plan.sequence, (42,))

    def test_plan_manager_is_single_owner_of_turn_plan(self) -> None:
        ai = self.engine.ai
        self.assertIsInstance(ai.plan_manager, PlanManager)
        self.assertFalse(hasattr(ai, "_active_turn_plan"))
        self.assertIsNone(ai._get_active_turn_plan())

    def test_air_strategy_is_loaded_from_registry(self) -> None:
        self.engine.ai_player.summoner_key = "air"
        strategy = self.engine.ai._current_strategy(self.engine.ai_player, self.engine)
        self.assertEqual(strategy.__class__.__name__, "AirStrategy")

    def test_unknown_strategy_uses_generic_fallback(self) -> None:
        self.engine.ai_player.summoner_key = "void"
        strategy = self.engine.ai._current_strategy(self.engine.ai_player, self.engine)
        self.assertIsInstance(strategy, DefaultDeckStrategy)

    def test_registry_can_register_dummy_strategy_without_touching_air_modules(self) -> None:
        dummy = DummyStrategy()
        self.engine.ai.strategy_registry.register("fire", dummy)
        self.engine.ai_player.summoner_key = "fire"

        decision = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertEqual(decision.mode, "DUMMY")
        self.assertEqual(decision.primary_goal, "dummy_goal")

    def test_prepare_next_action_is_planning_only(self) -> None:
        self.engine.ai_player.summoner_key = "air"
        self.engine.ai_player.hand = []
        self.engine.ai_player.resources = []
        before_phase = self.engine.phase
        before_resources = len(self.engine.ai_player.resources)

        payload = self.engine.ai.prepare_next_action(self.engine.ai_player, self.engine)

        self.assertIsInstance(payload, dict)
        self.assertEqual(self.engine.phase, before_phase)
        self.assertEqual(len(self.engine.ai_player.resources), before_resources)

    def test_air_prepare_next_action_delegates_to_turn_planner(self) -> None:
        planner = RecordingTurnPlanner()
        self.engine.ai.turn_planner = planner
        self.engine.ai_player.summoner_key = "air"

        payload = self.engine.ai.prepare_next_action(self.engine.ai_player, self.engine)

        self.assertEqual(payload["strategy_mode"], "TEST")
        self.assertEqual(planner.calls, [("build_turn_plan_payload", self.engine.phase)])

    def test_choose_spell_delegates_to_reaction_planner(self) -> None:
        planner = RecordingReactionPlanner()
        self.engine.ai.reaction_planner = planner

        result = self.engine.ai.choose_spell(list(self.engine.ai_player.hand), self.engine)

        self.assertIsNone(result)
        self.assertEqual(planner.calls, [("choose_spell", tuple())])

    def test_choose_spell_target_ref_delegates_to_reaction_planner(self) -> None:
        planner = RecordingReactionPlanner()
        self.engine.ai.reaction_planner = planner
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"])

        result = self.engine.ai.choose_spell_target_ref(self.engine.ai_player, self.engine, card, pending=None)

        self.assertIsNone(result)
        self.assertEqual(planner.calls, [("choose_spell_target_ref", card.instance_id)])

    def test_estimate_best_attack_plan_delegates_to_assessment_component(self) -> None:
        component = RecordingAssessmentComponent()
        self.engine.ai.assessment = component

        result = self.engine.ai._estimate_best_air_attack_plan(self.engine.ai_player, self.engine.human_player, [], [])

        self.assertEqual(result["attacker_ids"], [])
        self.assertEqual(component.calls, [("estimate_best_attack_plan", tuple())])

    def test_bounce_evaluation_delegates_to_effect_component(self) -> None:
        component = RecordingEffectEvaluatorComponent()
        self.engine.ai.effect_evaluator = component
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_verwehung"])

        result = self.engine.ai._evaluate_air_bounce_plan(
            self.engine.ai_player,
            self.engine,
            card,
            hand=[],
            available_resources=0,
            total_resources=0,
        )

        self.assertFalse(result["is_useful"])
        self.assertEqual(component.calls, [("evaluate_bounce_plan", card.instance_id)])

    def test_air_attacker_selection_delegates_to_turn_planner(self) -> None:
        planner = RecordingTurnPlanner()
        self.engine.ai.turn_planner = planner
        self.engine.ai_player.summoner_key = "air"

        result = self.engine.ai.choose_attackers_for_player(self.engine.ai_player, self.engine, [])

        self.assertEqual(result, [])
        self.assertEqual(planner.calls, [("choose_attackers_for_player", 0)])

    def test_air_main_phase_selection_delegates_to_turn_planner(self) -> None:
        planner = RecordingTurnPlanner()
        self.engine.ai.turn_planner = planner
        self.engine.ai_player.summoner_key = "air"

        result = self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNone(result)
        self.assertEqual(planner.calls, [("choose_main_phase_card", self.engine.phase)])

    def test_reset_for_turn_delegates_to_turn_planner(self) -> None:
        planner = RecordingTurnPlanner()
        self.engine.ai.turn_planner = planner

        self.engine.ai.reset_for_turn()

        self.assertEqual(planner.calls, [("clear_active_turn_plan", None)])

    def test_notify_action_resolved_marks_plan_progress_via_plan_manager(self) -> None:
        plan = TurnPlan(
            plan_id=1,
            revision=1,
            player_id=self.engine.ai_player.player_id,
            turn_number=self.engine.turn_number,
            created_phase=self.engine.phase,
            steps=(PlanStep(action_type="play_resource", card_instance_id=123),),
        )
        self.engine.ai.plan_manager.activate(plan)

        self.engine.ai.notify_action_resolved("play_resource", card_instance_id=123)

        self.assertIsNone(self.engine.ai._get_active_turn_plan())
        self.assertIsNotNone(self.engine.ai._last_turn_plan)

    def test_reset_for_turn_discards_active_plan(self) -> None:
        plan = TurnPlan(
            plan_id=1,
            revision=1,
            player_id=self.engine.ai_player.player_id,
            turn_number=self.engine.turn_number,
            created_phase=self.engine.phase,
            steps=(PlanStep(action_type="end_turn"),),
        )
        self.engine.ai.plan_manager.activate(plan)

        self.engine.ai.reset_for_turn()

        self.assertIsNone(self.engine.ai._get_active_turn_plan())
        self.assertEqual(self.engine.ai._last_turn_plan.status, PLAN_STATUS_DISCARDED)


