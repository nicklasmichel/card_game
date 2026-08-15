from __future__ import annotations

import unittest
from unittest.mock import patch

from core.game_logic import GameEngine
from core.models import ControllerKind, MatchMode, PlayerState
from core.session import GameSession, LocalPveSession
from multiplayer.protocol import EventKind, GameCommand


class PlayerControllerTests(unittest.TestCase):
    def test_legacy_is_human_flag_infers_controller_kind(self) -> None:
        human = PlayerState(0, "Human", True)
        ai = PlayerState(1, "AI", False)

        self.assertEqual(human.controller_kind, ControllerKind.LOCAL_HUMAN)
        self.assertTrue(human.is_locally_controlled)
        self.assertEqual(ai.controller_kind, ControllerKind.AI)
        self.assertTrue(ai.is_ai_controlled)

    def test_explicit_remote_controller_is_a_human_but_not_local(self) -> None:
        remote = PlayerState(1, "Remote", False, controller_kind=ControllerKind.REMOTE_HUMAN)

        self.assertTrue(remote.is_human)
        self.assertTrue(remote.is_remotely_controlled)
        self.assertFalse(remote.is_locally_controlled)
        self.assertFalse(remote.is_ai_controlled)

    def test_set_controller_keeps_legacy_flag_in_sync(self) -> None:
        player = PlayerState(0, "Player", True)

        player.set_controller(ControllerKind.AI)

        self.assertFalse(player.is_human)
        self.assertTrue(player.is_ai_controlled)


class MatchModeTests(unittest.TestCase):
    def test_pve_assigns_local_human_and_ai(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVE)

        self.assertEqual(engine.player_one.controller_kind, ControllerKind.LOCAL_HUMAN)
        self.assertEqual(engine.player_two.controller_kind, ControllerKind.AI)

    def test_pvp_assigns_local_and_remote_humans_without_starting_ai(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        engine.active_player_index = 1

        self.assertEqual(engine.player_one.controller_kind, ControllerKind.LOCAL_HUMAN)
        self.assertEqual(engine.player_two.controller_kind, ControllerKind.REMOTE_HUMAN)
        self.assertTrue(engine.player_two.is_human)
        self.assertFalse(engine.start_ai_thinking())


class LocalPveSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine(auto_start=False, match_mode=MatchMode.PVE)
        self.session = LocalPveSession(self.engine)

    def tearDown(self) -> None:
        self.session.close()

    def test_exposes_shared_session_contract_and_engine_state(self) -> None:
        self.assertIsInstance(self.session, GameSession)
        self.assertIs(self.session.state, self.engine)
        self.assertEqual(self.session.match_mode, MatchMode.PVE)
        self.assertEqual(self.session.local_player_id, 0)

    def test_rejects_engine_with_incompatible_match_mode(self) -> None:
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)

        with self.assertRaises(ValueError):
            LocalPveSession(engine)

    def test_rejects_non_local_player_as_session_owner(self) -> None:
        with self.assertRaises(ValueError):
            LocalPveSession(self.engine, local_player_id=1)

    def test_forwards_frontend_commands_to_engine(self) -> None:
        with (
            patch.object(self.engine, "start_new_game") as start_new_game,
            patch.object(self.engine, "handle_action") as handle_action,
            patch.object(self.engine, "handle_click") as handle_click,
            patch.object(self.engine, "play_hand_card_in_summoning_zone") as play_card,
        ):
            self.session.start_new_game(starting_player_id=1)
            self.session.submit_action("end_turn")
            self.session.submit_click("hand", 17)
            self.session.submit_hand_card_play(17)

        start_new_game.assert_called_once_with(starting_player_id=1)
        handle_action.assert_called_once_with("end_turn")
        handle_click.assert_called_once_with("hand", 17)
        play_card.assert_called_once_with(17)

    def test_typed_command_emits_applied_event(self) -> None:
        command = GameCommand.action(0, "end_turn", command_id="command-1")
        with patch.object(self.engine, "handle_action") as handle_action:
            event = self.session.submit_command(command)

        handle_action.assert_called_once_with("end_turn")
        self.assertEqual(event.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(event.command_id, command.command_id)
        self.assertEqual(self.session.drain_events(), [event])
        self.assertEqual(self.session.drain_events(), [])

    def test_rejects_command_for_player_not_owned_by_session(self) -> None:
        command = GameCommand.action(1, "end_turn", command_id="remote-command")
        with patch.object(self.engine, "handle_action") as handle_action:
            event = self.session.submit_command(command)

        handle_action.assert_not_called()
        self.assertEqual(event.kind, EventKind.COMMAND_REJECTED)
        self.assertEqual(event.payload["code"], "unauthorized_player")

    def test_duplicate_command_is_idempotent(self) -> None:
        command = GameCommand.action(0, "end_turn", command_id="same-command")
        with patch.object(self.engine, "handle_action") as handle_action:
            first_event = self.session.submit_command(command)
            second_event = self.session.submit_command(command)

        handle_action.assert_called_once_with("end_turn")
        self.assertIs(second_event, first_event)
        self.assertEqual(self.session.drain_events(), [first_event])

    def test_rejects_reused_command_id_with_different_data(self) -> None:
        first = GameCommand.action(0, "end_turn", command_id="reused-id")
        conflicting = GameCommand.action(0, "pass", command_id="reused-id")
        with patch.object(self.engine, "handle_action") as handle_action:
            self.session.submit_command(first)
            event = self.session.submit_command(conflicting)

        handle_action.assert_called_once_with("end_turn")
        self.assertEqual(event.kind, EventKind.COMMAND_REJECTED)
        self.assertEqual(event.payload["code"], "command_id_conflict")

    def test_update_runs_ai_automatic_rules_and_bounded_log_flush(self) -> None:
        with (
            patch.object(self.engine, "poll_ai_thinking") as poll_ai,
            patch.object(self.engine, "has_pending_ai_action", return_value=False) as has_pending,
            patch.object(self.engine, "start_ai_thinking") as start_ai,
            patch.object(self.engine, "auto_resolve_human_no_blockers_if_needed") as auto_resolve,
            patch.object(self.engine, "resolve_stalled_dice_battle_if_needed") as resolve_stalled,
            patch.object(self.engine, "flush_log_file_writes") as flush_logs,
        ):
            self.session.update()

        poll_ai.assert_called_once_with()
        has_pending.assert_called_once_with()
        start_ai.assert_called_once_with()
        auto_resolve.assert_called_once_with()
        resolve_stalled.assert_called_once_with()
        flush_logs.assert_called_once_with(max_lines=24)

    def test_update_can_pause_gameplay_but_still_flush_logs(self) -> None:
        with (
            patch.object(self.engine, "poll_ai_thinking") as poll_ai,
            patch.object(self.engine, "auto_resolve_human_no_blockers_if_needed") as auto_resolve,
            patch.object(self.engine, "flush_log_file_writes") as flush_logs,
        ):
            self.session.update(allow_ai=False, allow_automatic_rules=False)

        poll_ai.assert_not_called()
        auto_resolve.assert_not_called()
        flush_logs.assert_called_once_with(max_lines=24)


if __name__ == "__main__":
    unittest.main()
