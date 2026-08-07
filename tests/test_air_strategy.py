from __future__ import annotations

from core.ai.strategies.air import (
    AIR_MODE_BUILD_SWARM,
    AIR_MODE_LETHAL,
    AIR_MODE_PRESSURE,
    AIR_MODE_RECOVER,
    AIR_MODE_RELOAD,
    AIR_MODE_STABILIZE,
)
from core.ai.plans import TurnPlan
from core.models import CardInstance, PHASE_MAIN_1
from tests.helpers import EngineTestCase


class AirStrategyTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.ai_player.summoner_key = "air"

    def test_strategy_selects_lethal_over_reload(self) -> None:
        self.engine.human_player.life = 1
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_himmelswende"]),
        ]
        attacker = self.make_creature("air_creature_windschwinge", owner_id=1)
        attacker.tapped = False
        attacker.summoning_sick = False

        decision = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertEqual(decision.mode, AIR_MODE_LETHAL)
        self.assertEqual(decision.primary_goal, "deal_lethal_damage")
        self.assertIn("lethal_available", decision.reason_codes)

    def test_strategy_selects_stabilize_for_opponent_lethal(self) -> None:
        self.engine.ai_player.life = 3
        threat = self.make_creature("air_creature_orkangeist", owner_id=0)
        threat.tapped = False
        threat.summoning_sick = False
        threat.sw = 3

        decision = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertEqual(decision.mode, AIR_MODE_STABILIZE)
        self.assertEqual(decision.primary_goal, "prevent_opponent_lethal")

    def test_strategy_selects_reload_for_small_hand(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_himmelswende"]),
        ]
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]

        decision = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertEqual(decision.mode, AIR_MODE_RELOAD)
        self.assertEqual(decision.primary_goal, "reload_hand")

    def test_strategy_selects_recover_for_valuable_graveyard_targets(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_windruf"]),
        ]
        self.engine.ai_player.discard_pile = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"]),
        ]

        decision = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertEqual(decision.mode, AIR_MODE_RECOVER)
        self.assertEqual(decision.primary_goal, "recover_creatures")

    def test_strategy_selects_build_swarm_for_small_board_and_creature_hand(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]

        decision = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertEqual(decision.mode, AIR_MODE_BUILD_SWARM)
        self.assertEqual(decision.primary_goal, "build_wide_board")

    def test_strategy_defaults_to_pressure(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        attacker_one = self.make_creature("air_creature_windgeist", owner_id=1)
        attacker_two = self.make_creature("air_creature_windschwinge", owner_id=1)
        attacker_one.tapped = False
        attacker_one.summoning_sick = False
        attacker_two.tapped = False
        attacker_two.summoning_sick = False

        decision = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertEqual(decision.mode, AIR_MODE_PRESSURE)
        self.assertEqual(decision.primary_goal, "maximize_player_damage")

    def test_strategy_weights_change_by_mode(self) -> None:
        self.engine.human_player.life = 1
        self.make_creature("air_creature_windschwinge", owner_id=1, ready=True)
        lethal = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.setUp()
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
        ]
        build_swarm = self.engine.ai._evaluate_air_strategy(self.engine.ai_player, self.engine)

        self.assertLess(lethal.weights.recycle_penalty, build_swarm.weights.recycle_penalty)
        self.assertLess(lethal.weights.counterattack_risk, build_swarm.weights.counterattack_risk)

    def test_new_air_turn_plan_stores_strategy_mode_and_goal(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
        ]

        self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        plan = self.engine.ai._get_active_turn_plan()

        self.assertIsInstance(plan, TurnPlan)
        self.assertTrue(plan.strategy_mode)
        self.assertTrue(plan.primary_goal)
        self.assertTrue(plan.strategy_reason_codes)

    def test_strategy_mode_change_invalidates_existing_plan(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
        ]

        self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)
        original_plan = self.engine.ai._get_active_turn_plan()
        self.assertIsNotNone(original_plan)

        self.engine.human_player.life = 1
        self.make_creature("air_creature_windschwinge", owner_id=1, ready=True)
        self.engine.ai.choose_main_phase_card(self.engine.ai_player, self.engine)

        self.assertIsNotNone(self.engine.ai._last_turn_plan)
        self.assertEqual(self.engine.ai._last_turn_plan.invalid_reason_codes, ("strategy_mode_changed",))
        self.assertIsNotNone(self.engine.ai._get_active_turn_plan())
        self.assertNotEqual(self.engine.ai._get_active_turn_plan().plan_id, original_plan.plan_id)


