from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import STARTING_LIFE  # noqa: E402
from diagnostics.profile_benchmark import (  # noqa: E402
    PROFILE_NAMES,
    ProfileBenchmarkConfig,
    ProfileGameResult,
    format_markdown_report,
    run_profile_benchmark,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the production AI against four independent fixed opponent profiles."
    )
    parser.add_argument(
        "--seeds",
        type=_positive_int,
        default=5,
        help="number of seeds; every seed is played with both starting players (default: 5)",
    )
    parser.add_argument("--seed", type=int, default=0, help="first deterministic seed (default: 0)")
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=PROFILE_NAMES,
        default=list(PROFILE_NAMES),
        help="profiles to include (default: all four)",
    )
    parser.add_argument("--starting-life", type=_positive_int, default=STARTING_LIFE)
    parser.add_argument("--decision-timeout", type=_positive_float, default=30.0)
    parser.add_argument("--game-timeout", type=_positive_float, default=300.0)
    parser.add_argument("--max-turns", type=_positive_int, default=200)
    parser.add_argument("--max-steps", type=_positive_int, default=2_000)
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=1,
        help="number of isolated game processes to run in parallel (default: 1)",
    )
    parser.add_argument("--slow-snapshot-ms", type=_non_negative_float, default=1_000.0)
    parser.add_argument(
        "--json",
        type=Path,
        default=PROJECT_ROOT / "stats" / "data" / "profile_benchmark_latest.json",
        help="JSON report path",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=PROJECT_ROOT / "stats" / "data" / "profile_benchmark_latest.md",
        help="Markdown summary path",
    )
    return parser


def _print_result(index: int, total: int, result: ProfileGameResult) -> None:
    if result.completed:
        outcome = "AI" if result.target_won else ("draw" if result.winner_id is None else "profile")
        print(
            f"[{index}/{total}] PASS profile={result.profile} seed={result.seed} "
            f"starter=P{result.starting_player_id + 1} winner={outcome} turns={result.turns} "
            f"game={result.elapsed_ms:.0f}ms",
            flush=True,
        )
    else:
        print(
            f"[{index}/{total}] FAIL profile={result.profile} seed={result.seed} "
            f"starter=P{result.starting_player_id + 1} code={result.failure_code}: "
            f"{result.failure_message}",
            flush=True,
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ProfileBenchmarkConfig(
        starting_life=args.starting_life,
        decision_timeout_seconds=args.decision_timeout,
        game_timeout_seconds=args.game_timeout,
        max_turns=args.max_turns,
        max_steps=args.max_steps,
        slow_snapshot_threshold_ms=args.slow_snapshot_ms,
    )
    games = args.seeds * len(args.profiles) * 2
    print(
        f"Running {games} games: {args.seeds} seed(s), {len(args.profiles)} profile(s), "
        "both starting-player positions.",
        flush=True,
    )
    summary = run_profile_benchmark(
        range(args.seed, args.seed + args.seeds),
        config,
        profiles=args.profiles,
        workers=args.workers,
        result_callback=_print_result,
    )
    report = summary.to_dict()
    overall = report["overall"]
    print()
    print(
        f"Completed {overall['completed']}/{overall['games']}; AI wins "
        f"{overall['target_wins']} ({overall['target_win_rate'] * 100:.1f}%); "
        f"average {overall['average_turns']:.2f} turns."
    )
    print(
        f"Audits: {overall['decision_quality']['error_count']} error(s), "
        f"{overall['decision_quality']['warning_count']} warning(s); "
        f"reproducible findings: {len(report['reproducible_findings'])}."
    )

    json_path = args.json.resolve()
    markdown_path = args.markdown.resolve()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(format_markdown_report(report), encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0 if summary.successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
