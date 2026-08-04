from __future__ import annotations

from core.ai.air.registry import get_air_card_handler
from core.ai import ActionCandidate, BoundPlan, DecisionReason, build_ai_context
from core.ai_logic import SimpleAI
from tests.helpers import EngineTestCase


class AiArchitectureTests(EngineTestCase):
    def test_public_ai_entrypoints_are_importable(self) -> None:
        self.assertIsNotNone(SimpleAI)
        self.assertIsNotNone(ActionCandidate)
        self.assertIsNotNone(BoundPlan)
        self.assertIsNotNone(DecisionReason)

    def test_air_registry_exposes_specialized_handlers(self) -> None:
        self.assertIsNotNone(get_air_card_handler("air_spell_windstoss"))
        self.assertIsNotNone(get_air_card_handler("air_spell_ausweichen"))
        self.assertIsNotNone(get_air_card_handler("air_ritual_turbulenz"))

    def test_build_ai_context_exposes_visible_state_only(self) -> None:
        self.engine.phase = "summoning"
        self.engine.creatures_died_this_turn = 3
        wolkenfalke_resource = self.make_resource("air_creature_windgeist")
        wolkenfalke_resource.tapped = True
        self.engine.ai_player.resources = [wolkenfalke_resource]

        context = build_ai_context(self.engine, self.engine.ai_player)

        self.assertEqual(context.player, self.engine.ai_player)
        self.assertEqual(context.enemy, self.engine.human_player)
        self.assertEqual(context.phase, "summoning")
        self.assertEqual(context.available_resources, 0)
        self.assertEqual(context.total_resources, 1)
        self.assertEqual(context.tapped_resource_ids, (wolkenfalke_resource.resource_id,))
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
