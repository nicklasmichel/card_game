from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ui.runtime import handle_ui_action


class UIRuntimeTests(unittest.TestCase):
    def test_new_game_starts_immediately_without_start_player_selection(self) -> None:
        session = Mock()
        app = SimpleNamespace(session=session)

        handled = handle_ui_action(app, "new_game")

        self.assertTrue(handled)
        session.start_new_game.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
