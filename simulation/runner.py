from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from simulation.engine import SimulationConfig, SimulationGameEngine
from simulation.telemetry import BatchSummary, ReplayRecord


class SimulationRunner:
    def run_batch(
        self,
        *,
        decks: tuple[str, str] = ("air", "fire"),
        seeds: list[int],
        alternate_start_player: bool = True,
        fixed_start_player: int | None = None,
        max_turns: int = 60,
        max_actions_per_turn: int = 250,
        capture_replays: bool = True,
    ) -> BatchSummary:
        started = perf_counter()
        results = []
        replays: list[ReplayRecord] = []
        for index, seed in enumerate(seeds):
            if fixed_start_player is not None:
                start_player = fixed_start_player
            elif alternate_start_player:
                start_player = index % 2
            else:
                start_player = None
            engine = SimulationGameEngine(
                SimulationConfig(
                    decks=decks,
                    seed=seed,
                    starting_player_id=start_player,
                    max_turns=max_turns,
                    max_actions_per_turn=max_actions_per_turn,
                    capture_replay=capture_replays,
                    fixed_start_player=fixed_start_player is not None,
                )
            )
            replay = engine.run_to_completion()
            results.append(engine.telemetry)
            if capture_replays:
                replays.append(replay)
        runtime = perf_counter() - started
        return BatchSummary(
            total_games=len(results),
            total_runtime_seconds=runtime,
            results=results,
            replays=replays,
            config={
                "decks": list(decks),
                "seeds": seeds,
                "alternate_start_player": alternate_start_player,
                "fixed_start_player": fixed_start_player,
                "max_turns": max_turns,
                "max_actions_per_turn": max_actions_per_turn,
            },
        )

    @staticmethod
    def save_json(summary: BatchSummary, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    @staticmethod
    def format_baseline_answers(summary: BatchSummary) -> dict[str, object]:
        games = summary.results
        air_wins = sum(1 for game in games if game.winner_id is not None and game.players[game.winner_id].deck == "air")
        fire_wins = sum(1 for game in games if game.winner_id is not None and game.players[game.winner_id].deck == "fire")
        start_groups: dict[int, list] = {0: [], 1: []}
        for game in games:
            start_groups[game.starting_player_id].append(game)
        def winrate(deck: str, grouped: list) -> float:
            if not grouped:
                return 0.0
            wins = sum(1 for game in grouped if game.winner_id is not None and game.players[game.winner_id].deck == deck)
            return wins / len(grouped)
        air_metrics = []
        fire_metrics = []
        for game in games:
            for player in game.players.values():
                if player.deck == "air":
                    air_metrics.append(player)
                elif player.deck == "fire":
                    fire_metrics.append(player)
        return {
            "air_win_rate": air_wins / len(games) if games else 0.0,
            "fire_win_rate": fire_wins / len(games) if games else 0.0,
            "start_player_air_win_rate_when_air_starts": winrate("air", start_groups[0]),
            "start_player_fire_win_rate_when_fire_starts": winrate("fire", start_groups[1]),
            "average_turns": mean(game.turn_count for game in games) if games else 0.0,
            "air_average_attackers": mean(mean(player.air_attacker_counts) if player.air_attacker_counts else 0.0 for player in air_metrics) if air_metrics else 0.0,
            "fire_average_resources": mean(mean(player.resource_counts) if player.resource_counts else 0.0 for player in fire_metrics) if fire_metrics else 0.0,
        }
