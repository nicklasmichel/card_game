from __future__ import annotations

import unittest

from diagnostics.soak import BuilderBuildSample, DecisionTiming, SoakConfig, SoakGameResult, SoakSummary, run_single_game


class SoakRunnerTests(unittest.TestCase):
    def test_config_rejects_non_positive_limits(self) -> None:
        with self.assertRaises(ValueError):
            SoakConfig(starting_life=0)
        with self.assertRaises(ValueError):
            SoakConfig(decision_timeout_seconds=0)
        with self.assertRaises(ValueError):
            SoakConfig(game_timeout_seconds=0)
        with self.assertRaises(ValueError):
            SoakConfig(max_turns=0)
        with self.assertRaises(ValueError):
            SoakConfig(max_steps=0)
        with self.assertRaises(ValueError):
            SoakConfig(slow_snapshot_threshold_ms=-1)

    def test_short_direct_run_advances_and_reports_step_limit(self) -> None:
        result = run_single_game(
            7,
            SoakConfig(
                decision_timeout_seconds=30,
                game_timeout_seconds=60,
                max_turns=20,
                max_steps=1,
                slow_snapshot_threshold_ms=0,
            ),
        )

        self.assertFalse(result.completed)
        self.assertEqual(result.failure_code, "step_limit")
        self.assertEqual(result.steps, 1)
        self.assertEqual(len(result.decision_timings), 1)
        self.assertGreaterEqual(result.decision_timings[0].elapsed_ms, 0)
        self.assertIsNotNone(result.decision_timings[0].state_snapshot)
        self.assertIsNotNone(result.decision_timings[0].search_metrics)
        self.assertIsNotNone(result.final_snapshot)
        self.assertNotEqual(result.last_phase, "unknown")

    def test_direct_run_uses_configured_starting_life(self) -> None:
        result = run_single_game(
            7,
            SoakConfig(
                starting_life=15,
                decision_timeout_seconds=30,
                game_timeout_seconds=60,
                max_turns=20,
                max_steps=1,
            ),
        )

        self.assertEqual(
            [player["life"] for player in result.final_snapshot["players"]],
            [15, 15],
        )

    def test_summary_calculates_decision_percentiles_and_failures(self) -> None:
        samples = tuple(
            DecisionTiming(turn=index, player_id=0, phase="main", action="test", elapsed_ms=value)
            for index, value in enumerate((10.0, 20.0, 30.0, 40.0), start=1)
        )
        completed = SoakGameResult(
            seed=1,
            completed=True,
            winner="Player 1",
            turns=8,
            steps=24,
            elapsed_ms=100,
            decision_timings=samples,
            last_phase="game_over",
            player_life=(3, 0),
        )
        failed = SoakGameResult(
            seed=2,
            completed=False,
            winner=None,
            turns=4,
            steps=10,
            elapsed_ms=200,
            decision_timings=(),
            last_phase="main",
            player_life=(0, 0),
            failure_code="decision_timeout",
            failure_message="too slow",
        )

        report = SoakSummary(SoakConfig(), (completed, failed)).to_dict()

        self.assertEqual(report["games"]["completed"], 1)
        self.assertEqual(report["games"]["failed"], 1)
        self.assertEqual(report["decisions"]["average_ms"], 25.0)
        self.assertEqual(report["decisions"]["p95_ms"], 38.5)
        self.assertEqual(report["decisions"]["max_ms"], 40.0)
        self.assertEqual(report["decisions"]["by_phase"]["main"]["count"], 4)
        self.assertEqual(report["decisions"]["search"]["stop_reasons"], {"unavailable": 4})
        self.assertEqual(report["decisions"]["slowest"][0]["elapsed_ms"], 40.0)
        self.assertEqual(report["failures"][0]["seed"], 2)

    def test_game_result_round_trip_preserves_metrics(self) -> None:
        original = SoakGameResult(
            seed=5,
            completed=True,
            winner="Draw",
            turns=12,
            steps=40,
            elapsed_ms=123.5,
            decision_timings=(DecisionTiming(2, 1, "attackers", "declare_attackers", 7.25),),
            last_phase="game_over",
            player_life=(0, 0),
            builder_builds=(
                BuilderBuildSample(3, 1, 1, 0, 2, 2, "FLYING", True, 4, 5, True, False, 0.0),
            ),
        )

        restored = SoakGameResult.from_dict(original.to_dict())

        self.assertEqual(restored, original)

    def test_summary_reports_paid_haste_usage_and_build_profiles(self) -> None:
        result = SoakGameResult(
            seed=3,
            completed=True,
            winner="Player 2",
            turns=9,
            steps=30,
            elapsed_ms=100,
            decision_timings=(),
            last_phase="game_over",
            player_life=(0, 4),
            builder_builds=(
                BuilderBuildSample(3, 0, 2, 1, 0, 2, "VIGILANCE", False, 4, 4, False),
                BuilderBuildSample(4, 1, 1, 0, 2, 2, "FLYING", True, 4, 5, True, False, 0.0),
                BuilderBuildSample(6, 1, 0, 1, 3, 1, "TRAMPLE", True, 4, 5, False, True, 2.0),
            ),
        )

        builds = SoakSummary(SoakConfig(), (result,)).to_dict()["builder_builds"]

        self.assertEqual(builds["count"], 3)
        self.assertEqual(builds["haste_count"], 2)
        self.assertEqual(builds["haste_rate"], 0.6667)
        self.assertEqual(builds["haste_immediate_attack_rate"], 0.5)
        self.assertEqual(builds["haste_immediate_block_rate"], 0.5)
        self.assertEqual(builds["haste_immediate_role_rate"], 1.0)
        self.assertEqual(builds["haste_without_immediate_role_count"], 0)
        self.assertEqual(builds["primary_abilities"], {"FLYING": 1, "TRAMPLE": 1, "VIGILANCE": 1})
        self.assertEqual(builds["profiles"]["haste"]["average_stat_cost"], 4.0)
        self.assertEqual(builds["by_result"]["winner"]["haste_rate"], 1.0)
        self.assertEqual(builds["by_result"]["loser"]["haste_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
