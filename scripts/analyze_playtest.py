from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from diagnostics.playtest import analyze_latest_playtest, format_playtest_report  # noqa: E402 - direct script bootstrap
from stats.paths import LOG_PATH  # noqa: E402 - direct script bootstrap


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze the latest GODAO playtest from log.txt.")
    parser.add_argument("--log", type=Path, default=LOG_PATH, help="log file to analyze")
    parser.add_argument("--json", type=Path, help="optional output path for the complete JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = analyze_latest_playtest(args.log.resolve())
    print(format_playtest_report(report))
    if args.json is not None:
        output_path = args.json.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
