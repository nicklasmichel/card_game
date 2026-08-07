from __future__ import annotations

from core.ai.turn_planner import AIR_MAX_TOTAL_TURN_CANDIDATES
from core.ai.candidates import TurnPlanCandidate
from core.models import CardInstance, PHASE_MAIN_1
from tests.helpers import EngineTestCase


class AirTurnCandidateTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.ai_player.summoner_key = "air"

    def test_resource_variants_cover_zero_one_and_two_resource_lines(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]

        variants = self.engine.ai.turn_planner.get_air_resource_variants(
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            list(self.engine.ai_player.hand),
            phase=PHASE_MAIN_1,
        )

        counts = {(len(main_1), len(main_2)) for main_1, main_2 in variants}
        self.assertIn((0, 0), counts)
        self.assertTrue(any(total == 1 for total, _ignored in {(len(main_1) + len(main_2), 0) for main_1, main_2 in variants}))
        self.assertTrue(any(len(main_1) + len(main_2) == 2 for main_1, main_2 in variants))

    def test_turn_candidates_include_combat_and_second_main_when_attack_is_possible(self) -> None:
        attacker = self.make_creature("air_creature_windgeist", owner_id=1, ready=True)
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]

        candidates = self.engine.ai.turn_planner.build_turn_candidates(
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertTrue(candidates)
        self.assertTrue(any(candidate.attack.combat_started for candidate in candidates))
        self.assertTrue(any(candidate.main_2 is not None for candidate in candidates))

    def test_turn_candidates_capture_main_two_resource_and_follow_up_line(self) -> None:
        self.make_creature("air_creature_windgeist", owner_id=1, ready=True)
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_sturmschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]

        candidates = self.engine.ai.turn_planner.build_turn_candidates(
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=0,
            total_resources=0,
            phase=PHASE_MAIN_1,
        )

        self.assertTrue(
            any(
                candidate.main_2 is not None
                and candidate.main_2.resource_card_ids
                and candidate.main_2.card_sequence_ids
                for candidate in candidates
            )
        )

    def test_candidate_limit_is_enforced(self) -> None:
        self.make_creature("air_creature_windgeist", owner_id=1, ready=True)
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windgeist"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_orkanschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_aufwind"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_ritual_windruf"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
        ]

        candidates = self.engine.ai.turn_planner.build_turn_candidates(
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertLessEqual(len(candidates), AIR_MAX_TOTAL_TURN_CANDIDATES)
        self.assertLessEqual(self.engine.ai._last_air_candidate_stats["after_filter"], AIR_MAX_TOTAL_TURN_CANDIDATES)

    def test_best_candidate_payload_transfers_main_one_attack_and_main_two_steps(self) -> None:
        self.make_creature("air_creature_windgeist", owner_id=1, ready=True)
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_windschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_creature_sturmschwinge"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]

        payload = self.engine.ai.turn_planner.build_turn_plan_payload(
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=0,
            total_resources=0,
            phase=PHASE_MAIN_1,
        )
        plan = self.engine.ai._build_air_turn_plan_from_candidate(self.engine.ai_player, self.engine, payload)

        self.assertIsNotNone(plan)
        action_types = [step.action_type for step in plan.steps]
        self.assertIn("to_combat", action_types)
        self.assertIn("declare_attackers", action_types)
        self.assertIn("end_turn", action_types)

    def test_counterattack_estimate_is_present_on_candidates(self) -> None:
        self.make_creature("air_creature_windgeist", owner_id=1, ready=True)
        enemy_attacker = self.make_creature("earth_creature_erdgolem", owner_id=0, ready=True)
        enemy_attacker.tapped = False
        enemy_attacker.summoning_sick = False
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["air_spell_jagdwind"]),
        ]

        candidates = self.engine.ai.turn_planner.build_turn_candidates(
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=0,
            total_resources=0,
            phase=PHASE_MAIN_1,
        )

        self.assertTrue(candidates)
        self.assertTrue(all(isinstance(candidate, TurnPlanCandidate) for candidate in candidates))
        self.assertTrue(any(candidate.attack.expected_counterattack_damage >= 0 for candidate in candidates))


