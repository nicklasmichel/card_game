from __future__ import annotations

import unittest

from core.game_logic import GameEngine
from core.models import (
    CardCost,
    CardInstance,
    CardTemplate,
    Element,
    MatchMode,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
)
from domain.builder import PendingBuilderCreatureBuild
from multiplayer.protocol import decode_wire_message
from multiplayer.snapshot import GameStateSnapshot, SnapshotValidationError


def make_secret_card(instance_id: int, template_id: str, name: str) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        template=CardTemplate(
            template_id=template_id,
            name=name,
            cost=CardCost(resources=1),
            aw=1,
            vw=1,
            element=Element.WATER,
        ),
    )


class GameStateSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        self.engine.player_one.hand = [make_secret_card(101, "p1_secret", "Player One Secret")]
        self.engine.player_two.hand = [make_secret_card(202, "p2_secret", "Player Two Secret")]

    def test_snapshot_survives_json_and_wire_decoder_round_trip(self) -> None:
        snapshot = GameStateSnapshot.from_engine(self.engine, viewer_player_id=0, revision=7)

        decoded = decode_wire_message(snapshot.to_json())

        self.assertEqual(decoded, snapshot)
        self.assertEqual(decoded.revision, 7)
        self.assertEqual(len(decoded.state_hash), 64)

    def test_each_player_only_receives_their_own_hand(self) -> None:
        player_one_snapshot = GameStateSnapshot.from_engine(self.engine, 0, revision=0)
        player_two_snapshot = GameStateSnapshot.from_engine(self.engine, 1, revision=0)

        p1_view = {player["player_id"]: player for player in player_one_snapshot.state["players"]}
        p2_view = {player["player_id"]: player for player in player_two_snapshot.state["players"]}

        self.assertEqual(p1_view[0]["hand_cards"][0]["template"]["template_id"], "p1_secret")
        self.assertIsNone(p1_view[1]["hand_cards"])
        self.assertNotIn("p2_secret", player_one_snapshot.to_json())
        self.assertEqual(p2_view[1]["hand_cards"][0]["template"]["template_id"], "p2_secret")
        self.assertIsNone(p2_view[0]["hand_cards"])
        self.assertNotIn("p1_secret", player_two_snapshot.to_json())

    def test_private_builder_and_attacker_selections_are_hidden(self) -> None:
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [99]
        self.engine.pending_builder_creature = PendingBuilderCreatureBuild(aw=3, vw=2)

        active_view = GameStateSnapshot.from_engine(self.engine, 0, revision=0)
        opponent_view = GameStateSnapshot.from_engine(self.engine, 1, revision=0)

        self.assertEqual(active_view.state["selected_attackers"], [99])
        self.assertEqual(opponent_view.state["selected_attackers"], [])
        self.assertIsNotNone(active_view.state["pending_builder_creature"])
        self.assertIsNone(opponent_view.state["pending_builder_creature"])

    def test_unconfirmed_block_choices_are_hidden_from_attacker(self) -> None:
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {11: 21, 12: 22}
        self.engine.enraged_forced_attackers = {11}

        attacker_view = GameStateSnapshot.from_engine(self.engine, 0, revision=0)
        defender_view = GameStateSnapshot.from_engine(self.engine, 1, revision=0)

        self.assertEqual(attacker_view.state["block_assignments"], {"11": 21})
        self.assertEqual(defender_view.state["block_assignments"], {"11": 21, "12": 22})

    def test_tampered_state_fails_hash_validation(self) -> None:
        snapshot = GameStateSnapshot.from_engine(self.engine, 0, revision=0)
        data = snapshot.to_dict()
        data["state"] = dict(data["state"], turn_number=999)

        with self.assertRaises(SnapshotValidationError):
            GameStateSnapshot.from_dict(data)


if __name__ == "__main__":
    unittest.main()
