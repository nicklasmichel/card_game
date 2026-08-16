from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.models import PHASE_DECLARE_ATTACKERS, PHASE_GAME_OVER, PHASE_MAIN_1
from ui.layout_sidepanel import get_action_panel_title
from ui.timers import format_elapsed_ms, update_gameplay_timers


class GameplayTimerTests(unittest.TestCase):
    def make_app(self):
        player = SimpleNamespace(player_id=0)
        engine = SimpleNamespace(
            game_id="game-1",
            turn_number=1,
            active_player=player,
            phase=PHASE_MAIN_1,
        )
        return SimpleNamespace(
            engine=engine,
            paused=False,
            match_mode_selection_open=False,
            start_player_selection_open=False,
            network_blocks_gameplay=lambda: False,
            timer_game_id=None,
            timer_phase_marker=None,
            timer_last_update_ms=0,
            game_elapsed_ms=0,
            phase_elapsed_ms=0,
        )

    def test_formats_minutes_and_hours(self) -> None:
        self.assertEqual(format_elapsed_ms(0), "00:00")
        self.assertEqual(format_elapsed_ms(125_000), "02:05")
        self.assertEqual(format_elapsed_ms(3_661_000), "1:01:01")

    def test_action_header_shortens_main_phase_label(self) -> None:
        app = SimpleNamespace(engine=SimpleNamespace(phase=PHASE_MAIN_1))
        self.assertEqual(get_action_panel_title(app), "Main")

    def test_game_and_phase_timers_advance_and_phase_resets(self) -> None:
        app = self.make_app()
        update_gameplay_timers(app, now_ms=1_000)
        update_gameplay_timers(app, now_ms=3_500)
        self.assertEqual(app.game_elapsed_ms, 2_500)
        self.assertEqual(app.phase_elapsed_ms, 2_500)

        app.engine.phase = PHASE_DECLARE_ATTACKERS
        update_gameplay_timers(app, now_ms=4_000)
        self.assertEqual(app.game_elapsed_ms, 3_000)
        self.assertEqual(app.phase_elapsed_ms, 0)
        update_gameplay_timers(app, now_ms=5_000)
        self.assertEqual(app.phase_elapsed_ms, 1_000)

    def test_timers_pause_for_overlay_network_and_game_over(self) -> None:
        app = self.make_app()
        update_gameplay_timers(app, now_ms=1_000)
        update_gameplay_timers(app, now_ms=2_000)
        app.paused = True
        update_gameplay_timers(app, now_ms=5_000)
        self.assertEqual(app.game_elapsed_ms, 1_000)
        self.assertEqual(app.phase_elapsed_ms, 1_000)

        app.paused = False
        app.engine.phase = PHASE_GAME_OVER
        update_gameplay_timers(app, now_ms=7_000)
        self.assertEqual(app.game_elapsed_ms, 1_000)
        self.assertEqual(app.phase_elapsed_ms, 0)

    def test_new_game_resets_both_timers(self) -> None:
        app = self.make_app()
        update_gameplay_timers(app, now_ms=1_000)
        update_gameplay_timers(app, now_ms=4_000)
        app.engine.game_id = "game-2"
        update_gameplay_timers(app, now_ms=5_000)
        self.assertEqual(app.game_elapsed_ms, 0)
        self.assertEqual(app.phase_elapsed_ms, 0)


if __name__ == "__main__":
    unittest.main()
