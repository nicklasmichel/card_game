from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from diagnostics.soak import SoakConfig, SoakGameResult, run_soak  # noqa: E402 - direct script bootstrap


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
        description="Run deterministic GODAO AI-vs-AI soak games with legality and timeout checks."
    )
    parser.add_argument("--games", type=_positive_int, default=100, help="number of games to run (default: 100)")
    parser.add_argument("--seed", type=int, default=0, help="first deterministic seed (default: 0)")
    parser.add_argument(
        "--decision-timeout",
        type=_positive_float,
        default=30.0,
        help="maximum seconds for one AI decision (default: 30)",
    )
    parser.add_argument(
        "--game-timeout",
        type=_positive_float,
        default=300.0,
        help="maximum wall-clock seconds for one game (default: 300)",
    )
    parser.add_argument("--max-turns", type=_positive_int, default=200, help="turn limit per game (default: 200)")
    parser.add_argument("--max-steps", type=_positive_int, default=2_000, help="engine-step limit per game (default: 2000)")
    parser.add_argument(
        "--slow-snapshot-ms",
        type=_non_negative_float,
        default=1_000.0,
        help="store board snapshots for decisions at least this slow (default: 1000)",
    )
    parser.add_argument(
        "--no-isolation",
        action="store_true",
        help="run in the current process; faster, but a stuck calculation cannot be terminated",
    )
    parser.add_argument("--json", type=Path, help="optional path for the complete JSON report")
    return parser


def _print_game_result(index: int, total: int, result: SoakGameResult) -> None:
    if result.completed:
        print(
            f"[{index}/{total}] PASS seed={result.seed} winner={result.winner} "
            f"turns={result.turns} decisions={len(result.decision_timings)} "
            f"max_decision={result.max_decision_ms:.1f}ms game={result.elapsed_ms:.1f}ms",
            flush=True,
        )
    else:
        print(
            f"[{index}/{total}] FAIL seed={result.seed} code={result.failure_code} "
            f"turn={result.turns} phase={result.last_phase}: {result.failure_message}",
            flush=True,
        )


def _print_summary(report: dict) -> None:
    games = report["games"]
    decisions = report["decisions"]
    builds = report["builder_builds"]
    print()
    print(
        f"Games: {games['completed']}/{games['requested']} completed, "
        f"{games['failed']} failed, average {games['average_turns']:.2f} turns"
    )
    print(
        f"AI decisions: {decisions['count']} total, avg {decisions['average_ms']:.2f}ms, "
        f"P95 {decisions['p95_ms']:.2f}ms, P99 {decisions['p99_ms']:.2f}ms, "
        f"max {decisions['max_ms']:.2f}ms"
    )
    for phase, phase_report in decisions["by_phase"].items():
        print(
            f"  {phase}: {phase_report['count']} decisions, avg {phase_report['average_ms']:.2f}ms, "
            f"P95 {phase_report['p95_ms']:.2f}ms, max {phase_report['max_ms']:.2f}ms"
        )
    print(f"Search stops: {decisions['search']['stop_reasons']}")
    print(
        f"Builder creatures: {builds['count']} total, Haste {builds['haste_count']} "
        f"({builds['haste_rate'] * 100:.1f}%), immediate Haste attacks "
        f"{builds['haste_immediate_attack_count']} ({builds['haste_immediate_attack_rate'] * 100:.1f}%)"
    )
    print(
        f"Haste defensive readiness: {builds['haste_immediate_block_count']} "
        f"({builds['haste_immediate_block_rate'] * 100:.1f}%), any immediate role "
        f"{builds['haste_immediate_role_count']} ({builds['haste_immediate_role_rate'] * 100:.1f}%)"
    )
    print(f"Primary abilities: {builds['primary_abilities']}")
    print(f"Ability combinations: {builds['combinations']}")
    print(f"Outcomes: {games['outcomes']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = SoakConfig(
        decision_timeout_seconds=args.decision_timeout,
        game_timeout_seconds=args.game_timeout,
        max_turns=args.max_turns,
        max_steps=args.max_steps,
        slow_snapshot_threshold_ms=args.slow_snapshot_ms,
    )
    seeds = range(args.seed, args.seed + args.games)
    isolation_label = "isolated" if not args.no_isolation else "in-process"
    print(
        f"Running {args.games} game(s), seeds {args.seed}..{args.seed + args.games - 1}, "
        f"decision timeout {args.decision_timeout:.1f}s ({isolation_label})",
        flush=True,
    )
    summary = run_soak(
        seeds,
        config,
        isolated=not args.no_isolation,
        result_callback=_print_game_result,
    )
    report = summary.to_dict()
    _print_summary(report)
    if args.json is not None:
        output_path = args.json.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {output_path}")
    return 0 if summary.successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
