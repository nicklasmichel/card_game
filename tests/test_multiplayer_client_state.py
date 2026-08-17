from __future__ import annotations

import unittest

from core.game_logic import GameEngine
from core.models import (
    Ability,
    CardCost,
    CardInstance,
    CardTemplate,
    ControllerKind,
    Element,
    MatchMode,
    PendingBuilderCreatureBuild,
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

    def test_public_log_is_replaced_from_authoritative_snapshot(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        engine.public_log_messages = ["Alice starts.", "Bob adds a resource."]
        view = ClientGameView(local_player_id=1)

        view.apply_snapshot(GameStateSnapshot.from_engine(engine, 1, revision=2))

        self.assertEqual(view.log_messages, engine.public_log_messages)
        self.assertEqual(view.public_log_messages, engine.public_log_messages)

    def test_pending_vanilla_builder_stats_round_trip_to_remote_client(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        engine.active_player_index = 1
        engine.pending_builder_creature = PendingBuilderCreatureBuild(
            available_resources=5,
            sw=4,
            lw=2,
        )
        view = ClientGameView(local_player_id=1)

        view.apply_snapshot(GameStateSnapshot.from_engine(engine, 1, revision=1))

        pending = view.pending_builder_creature
        self.assertIsNotNone(pending)
        self.assertEqual((pending.aw, pending.vw, pending.sw, pending.lw), (0, 0, 4, 2))
        self.assertEqual(pending.spent_resources, 5)
        self.assertEqual(pending.ability_cost, 0)
        self.assertEqual(pending.selected_abilities, frozenset())
        self.assertFalse(pending.has_haste)

    def test_pending_haste_choice_round_trips_to_remote_client(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        engine.active_player_index = 1
        engine.pending_builder_creature = PendingBuilderCreatureBuild(
            available_resources=2,
            sw=2,
            has_haste=True,
        )
        view = ClientGameView(local_player_id=1)

        view.apply_snapshot(GameStateSnapshot.from_engine(engine, 1, revision=1))

        pending = view.pending_builder_creature
        self.assertIsNotNone(pending)
        self.assertTrue(pending.has_haste)
        self.assertEqual(pending.selected_abilities, frozenset({Ability.HASTE}))
        self.assertEqual(pending.spent_resources, 2)
        self.assertEqual(pending.total_cost, 3)


if __name__ == "__main__":
    unittest.main()
