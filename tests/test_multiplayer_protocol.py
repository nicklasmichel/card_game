from __future__ import annotations

import json
import unittest

from multiplayer.protocol import (
    MAX_WIRE_MESSAGE_BYTES,
    CommandKind,
    EventKind,
    GameCommand,
    GameEvent,
    PROTOCOL_VERSION,
    ProtocolValidationError,
    decode_wire_message,
)
from multiplayer.snapshot import GameStateSnapshot
from core.game_logic import GameEngine
from core.models import MatchMode


class GameCommandProtocolTests(unittest.TestCase):
    def test_all_command_kinds_survive_json_round_trip(self) -> None:
        commands = [
            GameCommand.start_game(0, None, command_id="start-1"),
            GameCommand.start_game(0, 1, command_id="start-2"),
            GameCommand.action(0, "end_turn", command_id="action-1"),
            GameCommand.click(0, "player_1_creatures", 17, command_id="click-1"),
            GameCommand.play_hand_card(0, 23, command_id="card-1"),
        ]

        for command in commands:
            with self.subTest(kind=command.kind):
                decoded = decode_wire_message(command.to_json())
                self.assertEqual(decoded, command)
                self.assertIsInstance(decoded, GameCommand)

    def test_wire_json_is_compact_versioned_and_self_describing(self) -> None:
        command = GameCommand.action(0, "builder_add_resource", command_id="known-id")

        data = json.loads(command.to_json())

        self.assertEqual(data["message_type"], "command")
        self.assertEqual(data["version"], PROTOCOL_VERSION)
        self.assertEqual(data["command_id"], "known-id")
        self.assertNotIn(" ", command.to_json())

    def test_rejects_unknown_version_kind_and_invalid_payload(self) -> None:
        valid = GameCommand.action(0, "end_turn", command_id="command-1").to_dict()

        invalid_messages = []
        wrong_version = dict(valid, version=PROTOCOL_VERSION + 1)
        invalid_messages.append(wrong_version)
        wrong_kind = dict(valid, kind="delete_everything")
        invalid_messages.append(wrong_kind)
        wrong_payload = dict(valid, payload={"action": ""})
        invalid_messages.append(wrong_payload)
        extra_payload_field = dict(valid, payload={"action": "end_turn", "extra": True})
        invalid_messages.append(extra_payload_field)

        for message in invalid_messages:
            with self.subTest(message=message):
                with self.assertRaises(ProtocolValidationError):
                    GameCommand.from_dict(message)

    def test_rejects_boolean_ids_and_non_json_values(self) -> None:
        with self.assertRaises(ProtocolValidationError):
            GameCommand.play_hand_card(0, True)
        with self.assertRaises(ProtocolValidationError):
            GameCommand(CommandKind.ACTION, 0, {"action": object()})
        with self.assertRaises(ProtocolValidationError):
            GameCommand.start_game(0, True)

    def test_rejects_invalid_and_oversized_wire_messages(self) -> None:
        with self.assertRaises(ProtocolValidationError):
            decode_wire_message("not-json")
        with self.assertRaises(ProtocolValidationError):
            decode_wire_message("[]")
        with self.assertRaises(ProtocolValidationError):
            decode_wire_message("x" * (MAX_WIRE_MESSAGE_BYTES + 1))


class GameEventProtocolTests(unittest.TestCase):
    def test_applied_and_rejected_events_survive_json_round_trip(self) -> None:
        command = GameCommand.action(0, "end_turn", command_id="command-1")
        events = [
            GameEvent.command_applied(command, sequence=1),
            GameEvent.command_rejected(
                command,
                sequence=2,
                code="unauthorized_player",
                message="Wrong player.",
            ),
        ]

        for event in events:
            with self.subTest(kind=event.kind):
                decoded = decode_wire_message(event.to_json())
                self.assertEqual(decoded, event)
                self.assertIsInstance(decoded, GameEvent)

        self.assertEqual(events[0].kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(events[1].kind, EventKind.COMMAND_REJECTED)

    def test_rejects_invalid_sequence_and_rejection_payload(self) -> None:
        with self.assertRaises(ProtocolValidationError):
            GameEvent(EventKind.COMMAND_APPLIED, 0, {"command_kind": "action"})
        with self.assertRaises(ProtocolValidationError):
            GameEvent(EventKind.COMMAND_REJECTED, 1, {"code": "missing-message"})

    def test_snapshot_event_survives_wire_round_trip(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        snapshot = GameStateSnapshot.from_engine(engine, viewer_player_id=0, revision=3)
        event = GameEvent.state_snapshot(snapshot, sequence=4, command_id="command-1")

        decoded = decode_wire_message(event.to_json())

        self.assertEqual(decoded, event)
        self.assertEqual(decoded.kind, EventKind.STATE_SNAPSHOT)
        decoded_snapshot = GameStateSnapshot.from_dict(decoded.payload["snapshot"])
        self.assertEqual(decoded_snapshot, snapshot)


if __name__ == "__main__":
    unittest.main()
