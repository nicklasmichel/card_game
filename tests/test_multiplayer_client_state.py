from __future__ import annotations

import unittest

from core.game_logic import GameEngine
from core.models import (
    CardCost,
    CardInstance,
    CardTemplate,
    ControllerKind,
    Element,
    MatchMode,
)
from multiplayer.client_state import ClientGameView
from multiplayer.snapshot import GameStateSnapshot


class ClientGameViewTests(unittest.TestCase):
    def test_remote_player_is_oriented_as_local_human(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        engine.player_two.hand = [
            CardInstance(
                77,
                CardTemplate(
                    "known_remote_card",
                    "Known Remote Card",
                    CardCost(resources=1),
                    1,
                    1,
                    Element.WATER,
                ),
            )
        ]
        snapshot = GameStateSnapshot.from_engine(engine, viewer_player_id=1, revision=3)
        view = ClientGameView(local_player_id=1)

        changed = view.apply_snapshot(snapshot)

        self.assertTrue(changed)
        self.assertEqual(view.human_player.player_id, 1)
        self.assertEqual(view.player_one.player_id, 1)
        self.assertEqual(view.ai_player.player_id, 0)
        self.assertEqual(view.human_player.controller_kind, ControllerKind.LOCAL_HUMAN)
        self.assertEqual(view.human_player.hand[0].template.template_id, "known_remote_card")
        self.assertEqual(view.snapshot_revision, 3)

    def test_older_snapshot_does_not_roll_back_client_state(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        view = ClientGameView(local_player_id=1)
        current = GameStateSnapshot.from_engine(engine, 1, revision=5)
        old = GameStateSnapshot.from_engine(engine, 1, revision=4)

        self.assertTrue(view.apply_snapshot(current))
        self.assertFalse(view.apply_snapshot(old))
        self.assertEqual(view.snapshot_revision, 5)


if __name__ == "__main__":
    unittest.main()
