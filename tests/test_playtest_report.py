from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.game_logic import GameEngine
from diagnostics.playtest import analyze_latest_playtest, format_playtest_report


class PlaytestReportTests(unittest.TestCase):
    def test_analyzes_only_latest_game_including_aborted_session(self) -> None:
        lines = [
            "[GAME START] id=old seed=1 mode=pve",
            "Player 1 creates Creature 1 (A 0 / D 0 / DMG 2 / Life 1 / Flying) for 2 resource(s).",
            "[GAME END] id=old status=completed winner=Player_1 turn=4",
            "[GAME START] id=current seed=27 mode=pve",
            "New game started in builder mode. Player 2 begins.",
            "Turn 7: Player 1 is active.",
            "Player 1 creates Creature 4 (A 2 / D 1 / DMG 3 / Life 2 / Trample + Haste) for 8 resource(s).",
            "Player 2 creates Creature 5 (A 1 / D 4 / DMG 1 / Life 1 / Flying) for 6 resource(s).",
            "[COMBAT ATTACKERS] turn=7 player=Player_1 creatures=Creature_4",
            "Turn 8: Player 2 is active.",
            "Player 2 creates Creature 6 (A 1 / D 2 / DMG 2 / Life 1 / Vigilance + Haste) for 6 resource(s).",
            "[AI PERF] turn=8 actor=p1:Player_2 phase=main decision=turn_search source=game elapsed_ms=1250 stop_reason=complete",
            "[AI PERF] turn=8 actor=p1:Player_2 phase=attack decision=turn_search source=game elapsed_ms=31000 stop_reason=deadline",
            "Turn 9: Player 1 is active.",
            "[COMBAT BLOCKS] turn=9 defender=Player_2 assignments=Creature_6>Creature_4",
        ]
        with TemporaryDirectory() as directory_name:
            log_path = Path(directory_name) / "log.txt"
            log_path.write_text("\n".join(lines), encoding="utf-8")

            report = analyze_latest_playtest(log_path)

        self.assertEqual(report["game"]["id"], "current")
        self.assertFalse(report["game"]["completed"])
        self.assertEqual(report["game"]["last_turn"], 9)
        self.assertEqual(report["builds"]["count"], 3)
        self.assertEqual(report["builds"]["haste_count"], 2)
        self.assertEqual(report["builds"]["invalid_cost_count"], 0)
        self.assertEqual(report["builds"]["haste_creation_turn_attack_count"], 1)
        self.assertEqual(report["builds"]["haste_next_turn_block_count"], 1)
        self.assertEqual(report["builds"]["haste_immediate_use_count"], 2)
        self.assertEqual(report["builds"]["haste_immediate_use_rate"], 1.0)
        self.assertEqual(report["builds"]["by_player"]["Player 1"]["primary_abilities"], {"Trample": 1})
        self.assertEqual(report["builds"]["by_player"]["Player 2"]["haste_immediate_use_rate"], 1.0)
        self.assertEqual(report["ai_decisions"]["count"], 2)
        self.assertEqual(report["ai_decisions"]["p95_ms"], 29512.5)
        self.assertEqual(report["ai_decisions"]["over_30_seconds"], 1)
        self.assertEqual(report["ai_decisions"]["stop_reasons"], {"complete": 1, "deadline": 1})
        self.assertIn("incomplete/aborted", format_playtest_report(report))

    def test_completed_marker_exposes_winner(self) -> None:
        with TemporaryDirectory() as directory_name:
            log_path = Path(directory_name) / "log.txt"
            log_path.write_text(
                "\n".join(
                    (
                        "[GAME START] id=finished seed=3 mode=pve",
                        "Turn 12: Player 2 is active.",
                        "[GAME END] id=finished status=completed winner=Player_2 turn=12",
                    )
                ),
                encoding="utf-8",
            )

            report = analyze_latest_playtest(log_path)

        self.assertTrue(report["game"]["completed"])
        self.assertEqual(report["game"]["winner"], "Player 2")
        self.assertEqual(report["game"]["last_turn"], 12)

    def test_new_game_queues_structured_log_marker(self) -> None:
        engine = GameEngine(auto_start=False)

        engine.start_new_game(starting_player_id=0)

        marker = next(line for line in engine.pending_log_file_lines if line.startswith("[GAME START] "))
        self.assertIn(f"id={engine.game_id}", marker)
        self.assertIn(f"seed={engine.seed}", marker)
        self.assertIn("mode=pve", marker)


if __name__ == "__main__":
    unittest.main()
