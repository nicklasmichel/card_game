from __future__ import annotations

import unittest
from unittest.mock import patch

from diagnostics.invariants import validate_prepared_action
from diagnostics.profile_benchmark import (
    PROFILE_NAMES,
    TARGET_PLAYER_ID,
    DecisionAudit,
    FixedOpponentProfile,
    ProfileBenchmarkConfig,
    ProfileBenchmarkSummary,
    ProfileGameResult,
    format_markdown_report,
    run_profile_benchmark,
    run_profile_game,
)
from diagnostics.soak import BuilderBuildSample, _create_soak_engine


def _result(
    profile: str,
    seed: int,
    starting_player_id: int,
    *,
    winner_id: int | None = TARGET_PLAYER_ID,
    audits: tuple[DecisionAudit, ...] = (),
) -> ProfileGameResult:
    return ProfileGameResult(
        profile=profile,
        seed=seed,
        starting_player_id=starting_player_id,
        completed=True,
        winner_id=winner_id,
        turns=10,
        steps=25,
        elapsed_ms=100.0,
        player_life=(0, 5),
        target_damage_to_player=15,
        opponent_damage_to_player=10,
        target_creature_kills=2,
        target_creature_deaths=1,
        target_attack_phases=4,
        target_no_attack_count=1,
        target_declared_attackers=5,
        target_full_board_passes=0,
        target_main_actions={"builder_create_creature": 2},
        target_builds=(BuilderBuildSample(3, 1, 2, 3, 1, 2, "NONE", False, 4, 4, False),),
        opponent_builds=(BuilderBuildSample(2, 0, 3, 1, 2, 1, "NONE", False, 3, 3, False),),
        resource_curve=(),
        dice_samples=(),
        decision_audits=audits,
        decision_timings=(),
    )


class ProfileBenchmarkTests(unittest.TestCase):
    def test_config_rejects_invalid_limits(self) -> None:
        with self.assertRaises(ValueError):
            ProfileBenchmarkConfig(starting_life=0)
        with self.assertRaises(ValueError):
            ProfileBenchmarkConfig(decision_timeout_seconds=0)
        with self.assertRaises(ValueError):
            ProfileBenchmarkConfig(game_timeout_seconds=0)
        with self.assertRaises(ValueError):
            ProfileBenchmarkConfig(max_turns=0)
        with self.assertRaises(ValueError):
            ProfileBenchmarkConfig(max_steps=0)
        with self.assertRaises(ValueError):
            ProfileBenchmarkConfig(slow_snapshot_threshold_ms=-1)
        with self.assertRaises(ValueError):
            run_profile_benchmark((1,), profiles=("balanced",), workers=0)

    def test_all_fixed_profiles_produce_legal_opening_actions(self) -> None:
        for profile_name in PROFILE_NAMES:
            with self.subTest(profile=profile_name):
                engine = _create_soak_engine(17, starting_player_id=0)
                profile = FixedOpponentProfile(profile_name, 17)

                action = profile.prepare_action(engine)

                validate_prepared_action(engine, action)
                self.assertEqual(action["kind"], "builder_create_creature")
                plan = action["plan"]
                self.assertGreaterEqual(min(plan[stat] for stat in ("aw", "vw", "sw", "lw")), 1)
                self.assertEqual(plan["cost"], engine.active_player.available_resources())

    def test_short_game_reports_step_limit_and_mirrored_starter(self) -> None:
        result = run_profile_game(
            "balanced",
            9,
            1,
            ProfileBenchmarkConfig(max_steps=1, game_timeout_seconds=30),
        )

        self.assertFalse(result.completed)
        self.assertEqual(result.starting_player_id, 1)
        self.assertEqual(result.failure_code, "step_limit")
        self.assertEqual(result.steps, 1)
        self.assertIsNotNone(result.final_snapshot)

    def test_batch_runs_each_seed_profile_with_both_starters(self) -> None:
        calls: list[tuple[str, int, int]] = []

        def fake_run(profile, seed, starter, config):
            calls.append((profile, seed, starter))
            return _result(profile, seed, starter)

        with patch("diagnostics.profile_benchmark.run_profile_game", side_effect=fake_run):
            summary = run_profile_benchmark((3, 4), profiles=("aggressive", "defensive"))

        self.assertTrue(summary.successful)
        self.assertEqual(len(summary.results), 8)
        self.assertEqual(
            set(calls),
            {
                (profile, seed, starter)
                for profile in ("aggressive", "defensive")
                for seed in (3, 4)
                for starter in (0, 1)
            },
        )

    def test_summary_reports_profiles_starter_split_and_repeated_findings(self) -> None:
        audit = DecisionAudit(6, "attackers", "high_margin_no_attack", "warning", "example", 1.0, 4.0)
        results = (
            _result("balanced", 1, 0, audits=(audit,)),
            _result("balanced", 1, 1, winner_id=0),
            _result("balanced", 2, 0, audits=(audit,)),
            _result("balanced", 2, 1, winner_id=0),
        )

        report = ProfileBenchmarkSummary(ProfileBenchmarkConfig(), results).to_dict()

        self.assertEqual(report["overall"]["games"], 4)
        self.assertEqual(report["overall"]["target_win_rate"], 0.5)
        self.assertEqual(report["profiles"]["balanced"]["attacks"]["no_attack_rate"], 0.25)
        self.assertEqual(report["starting_roles"]["opponent_starts"]["target_win_rate"], 1.0)
        self.assertEqual(report["starting_roles"]["target_starts"]["target_win_rate"], 0.0)
        self.assertEqual(report["reproducible_findings"][0]["code"], "high_margin_no_attack")
        self.assertEqual(report["reproducible_findings"][0]["seeds"], [1, 2])
        self.assertIn("AI win rate", format_markdown_report(report))

    def test_game_result_round_trip_preserves_nested_metrics(self) -> None:
        original = _result(
            "random",
            8,
            1,
            audits=(DecisionAudit(4, "main", "example", "info", "detail"),),
        )

        restored = ProfileGameResult.from_dict(original.to_dict())

        self.assertEqual(restored, original)


if __name__ == "__main__":
    unittest.main()
