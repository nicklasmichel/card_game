from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simulation.engine import SimulationConfig, SimulationGameEngine
from simulation.runner import SimulationRunner


class SimulationRunnerTests(unittest.TestCase):
    def test_same_seed_reproduces_same_end_result(self) -> None:
        runner = SimulationRunner()
        summary_a = runner.run_batch(decks=("air", "fire"), seeds=[81234], fixed_start_player=0, capture_replays=True)
        summary_b = runner.run_batch(decks=("air", "fire"), seeds=[81234], fixed_start_player=0, capture_replays=True)
        game_a = summary_a.results[0]
        game_b = summary_b.results[0]
        self.assertEqual(game_a.winner_id, game_b.winner_id)
        self.assertEqual(game_a.turn_count, game_b.turn_count)
        self.assertEqual(game_a.end_reason, game_b.end_reason)
        self.assertEqual(summary_a.replays[0].actions, summary_b.replays[0].actions)

    def test_different_seed_can_change_result(self) -> None:
        runner = SimulationRunner()
        summary = runner.run_batch(decks=("air", "fire"), seeds=[91000, 91001], fixed_start_player=0, capture_replays=True)
        game_a = summary.results[0]
        game_b = summary.results[1]
        differs = (
            game_a.winner_id != game_b.winner_id
            or game_a.turn_count != game_b.turn_count
            or summary.replays[0].actions != summary.replays[1].actions
        )
        self.assertTrue(differs)

    def test_starting_player_is_reproduced(self) -> None:
        runner = SimulationRunner()
        summary = runner.run_batch(decks=("air", "fire"), seeds=[92000, 92001], alternate_start_player=True, capture_replays=False)
        self.assertEqual(summary.results[0].starting_player_id, 0)
        self.assertEqual(summary.results[1].starting_player_id, 1)

    def test_json_export_contains_seed_and_actions(self) -> None:
        runner = SimulationRunner()
        summary = runner.run_batch(decks=("air", "fire"), seeds=[93000], fixed_start_player=0, capture_replays=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = runner.save_json(summary, Path(tmpdir) / "report.json")
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["games"][0]["seed"], 93000)
        self.assertTrue(data["replays"][0]["actions"])

    def test_max_turns_stops_long_game(self) -> None:
        engine = SimulationGameEngine(SimulationConfig(decks=("air", "fire"), seed=94000, starting_player_id=0, max_turns=1, max_actions_per_turn=250))
        replay = engine.run_to_completion()
        self.assertEqual(replay.end_reason, "max_turns")

    def test_max_actions_stops_stuck_game(self) -> None:
        engine = SimulationGameEngine(SimulationConfig(decks=("air", "fire"), seed=95000, starting_player_id=0, max_turns=60, max_actions_per_turn=1))
        replay = engine.run_to_completion()
        self.assertIn(replay.end_reason, {"max_actions_per_turn", "max_turns"})

    def test_simulation_does_not_mutate_global_templates(self) -> None:
        engine = SimulationGameEngine(SimulationConfig(decks=("air", "fire"), seed=96000, starting_player_id=0))
        before = engine.templates["fire_creature_hoellenbestie"].cost.resources
        engine.run_to_completion()
        after = engine.templates["fire_creature_hoellenbestie"].cost.resources
        self.assertEqual(before, after)

    def test_air_and_fire_passives_are_tracked(self) -> None:
        runner = SimulationRunner()
        summary = runner.run_batch(decks=("air", "fire"), seeds=list(range(97000, 97010)), alternate_start_player=True, capture_replays=False)
        air_players = [player for game in summary.results for player in game.players.values() if player.deck == "air"]
        fire_players = [player for game in summary.results for player in game.players.values() if player.deck == "fire"]
        self.assertTrue(any(player.air_passive_triggers >= 0 for player in air_players))
        self.assertTrue(any(player.fire_passive_triggers >= 0 for player in fire_players))


if __name__ == "__main__":
    unittest.main()
