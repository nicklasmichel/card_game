from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.models import MatchMode
from ui.layout_sidepanel import _visible_log_messages, get_action_panel_prompt
from ui.player_labels import format_player_names_for_ui, get_player_display_name


class PlayerLabelTests(unittest.TestCase):
    def test_pve_uses_human_and_ai_display_names(self) -> None:
        view = SimpleNamespace(session=SimpleNamespace(match_mode=MatchMode.PVE))
        human = SimpleNamespace(player_id=0, name="Player 1")
        ai = SimpleNamespace(player_id=1, name="Player 2")

        self.assertEqual(get_player_display_name(view, human), "Human")
        self.assertEqual(get_player_display_name(view, ai), "AI")
        self.assertEqual(
            format_player_names_for_ui(view, "Player 1 attacks Player 2."),
            "Human attacks AI.",
        )
        self.assertEqual(
            format_player_names_for_ui(view, "Player 2 (AI) adds a resource."),
            "AI adds a resource.",
        )

    def test_pvp_keeps_actual_player_names(self) -> None:
        view = SimpleNamespace(session=SimpleNamespace(match_mode=MatchMode.PVP))
        player = SimpleNamespace(player_id=0, name="Alice")

        self.assertEqual(get_player_display_name(view, player), "Alice")
        self.assertEqual(format_player_names_for_ui(view, "Alice attacks Bob."), "Alice attacks Bob.")

    def test_pve_action_prompt_and_visible_log_are_formatted(self) -> None:
        engine = SimpleNamespace(
            pending_ai_action={"description": "Player 2 (AI) adds a resource."},
            log_messages=["Player 1 ends the turn.", "Player 2 creates Creature 1."],
            use_public_log_for_display=False,
            is_ai_thinking=lambda: False,
            current_prompt=lambda: "Player 2 (AI) adds a resource.",
        )
        view = SimpleNamespace(
            session=SimpleNamespace(match_mode=MatchMode.PVE),
            engine=engine,
        )

        self.assertEqual(get_action_panel_prompt(view), "AI adds a resource.")
        self.assertEqual(
            _visible_log_messages(view),
            ["Human ends the turn.", "AI creates Creature 1."],
        )


if __name__ == "__main__":
    unittest.main()
