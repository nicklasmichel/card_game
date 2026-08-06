from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulation.runner import SimulationRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="KI-vs-KI Matchup-Simulation fuer cardgame")
    parser.add_argument("--deck-a", default="air")
    parser.add_argument("--deck-b", default="fire")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--start-player", type=int, choices=[0, 1], default=None)
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--max-actions-per-turn", type=int, default=250)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--no-replays", action="store_true")
    args = parser.parse_args()

    seeds = [args.seed_start + offset for offset in range(args.games)]
    runner = SimulationRunner()
    summary = runner.run_batch(
        decks=(args.deck_a, args.deck_b),
        seeds=seeds,
        alternate_start_player=args.start_player is None,
        fixed_start_player=args.start_player,
        max_turns=args.max_turns,
        max_actions_per_turn=args.max_actions_per_turn,
        capture_replays=not args.no_replays,
    )
    print(summary.console_report())
    if args.json_out:
        output = runner.save_json(summary, Path(args.json_out))
        print(f"JSON: {output}")


if __name__ == "__main__":
    main()
