from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from diagnostics.profile_benchmark import (  # noqa: E402
    ProfileBenchmarkConfig,
    ProfileBenchmarkSummary,
    ProfileGameResult,
    format_markdown_report,
    run_profile_game,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retry only failed games from a profile benchmark report.")
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "stats" / "data" / "profile_benchmark_latest.json",
    )
    parser.add_argument("--game-timeout", type=float, default=300.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--markdown", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = args.input.resolve()
    source = json.loads(input_path.read_text(encoding="utf-8"))
    config = replace(
        ProfileBenchmarkConfig(**source["config"]),
        game_timeout_seconds=float(args.game_timeout),
    )
    results = [ProfileGameResult.from_dict(game) for game in source["games"]]
    failed_indexes = [index for index, result in enumerate(results) if not result.completed]
    if not failed_indexes:
        print("No failed games to retry.")
        return 0
    if args.workers <= 0:
        raise ValueError("workers must be positive")
    with ProcessPoolExecutor(max_workers=min(args.workers, len(failed_indexes))) as executor:
        pending = {}
        for result_index in failed_indexes:
            previous = results[result_index]
            future = executor.submit(
                run_profile_game,
                previous.profile,
                previous.seed,
                previous.starting_player_id,
                config,
            )
            pending[future] = result_index
        for retry_index, future in enumerate(as_completed(pending), start=1):
            result_index = pending[future]
            retried = future.result()
            results[result_index] = retried
            print(
                f"[{retry_index}/{len(failed_indexes)}] {'PASS' if retried.completed else 'FAIL'} "
                f"profile={retried.profile} seed={retried.seed} starter=P{retried.starting_player_id + 1} "
                f"turns={retried.turns} elapsed={retried.elapsed_ms:.0f}ms code={retried.failure_code}",
                flush=True,
            )

    summary = ProfileBenchmarkSummary(config=config, results=tuple(results))
    report = summary.to_dict()
    markdown_path = (
        args.markdown.resolve()
        if args.markdown is not None
        else input_path.with_suffix(".md")
    )
    input_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(format_markdown_report(report), encoding="utf-8")
    print(f"Completed {report['overall']['completed']}/{report['overall']['games']}")
    print(f"JSON: {input_path}")
    print(f"Markdown: {markdown_path}")
    return 0 if summary.successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
