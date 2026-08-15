from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.game_logic import GameEngine
from core.models import (
    Ability,
    MatchMode,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
)
from core.session import GameSession
from multiplayer.host import AuthoritativeHostSession
from multiplayer.protocol import EventKind, GameCommand
from multiplayer.snapshot import GameStateSnapshot


class AuthoritativeHostSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        engine.log_path = Path(self.temp_dir.name) / "host.log"
        self.host = AuthoritativeHostSession(engine)

    def tearDown(self) -> None:
        self.host.close()
        self.temp_dir.cleanup()

    def start_with_remote_player(self) -> None:
        event = self.host.start_new_game(starting_player_id=1)
        self.assertEqual(event.kind, EventKind.COMMAND_APPLIED)
        self.host.drain_events()
        self.host.drain_player_events(1)

    def test_exposes_game_session_contract_and_pvp_players(self) -> None:
        self.assertIsInstance(self.host, GameSession)
        self.assertEqual(self.host.match_mode, MatchMode.PVP)
        self.assertEqual(self.host.local_player_id, 0)
        self.assertEqual(self.host.remote_player_ids, (1,))

    def test_host_start_broadcasts_player_specific_snapshots(self) -> None:
        applied = self.host.start_new_game(starting_player_id=0)

        local_events = self.host.drain_events()
        remote_events = self.host.drain_player_events(1)

        self.assertEqual(applied.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(self.host.revision, 1)
        self.assertEqual([event.kind for event in local_events], [
            EventKind.COMMAND_APPLIED,
            EventKind.STATE_SNAPSHOT,
        ])
        self.assertEqual([event.kind for event in remote_events], [EventKind.STATE_SNAPSHOT])
        local_snapshot = GameStateSnapshot.from_dict(local_events[-1].payload["snapshot"])
        remote_snapshot = GameStateSnapshot.from_dict(remote_events[-1].payload["snapshot"])
        self.assertEqual(local_snapshot.viewer_player_id, 0)
        self.assertEqual(remote_snapshot.viewer_player_id, 1)
        self.assertEqual(local_snapshot.revision, 1)
        self.assertEqual(remote_snapshot.revision, 1)

    def test_authenticated_remote_player_can_act_on_their_turn(self) -> None:
        self.start_with_remote_player()
        command = GameCommand.action(1, "builder_add_resource", command_id="remote-resource")

        event = self.host.receive_command(command, authenticated_player_id=1)

        self.assertEqual(event.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(self.host.state.player_two.total_resources(), 1)
        self.assertEqual(self.host.revision, 2)
        remote_events = self.host.drain_player_events(1)
        self.assertEqual([item.kind for item in remote_events], [
            EventKind.COMMAND_APPLIED,
            EventKind.STATE_SNAPSHOT,
        ])

    def test_remote_player_can_select_their_own_attacker(self) -> None:
        self.start_with_remote_player()
        creature = self.host.state.create_builder_creature(
            self.host.state.player_two,
            aw=2,
            vw=1,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.VIGILANCE}),
        )
        creature.tapped = False
        creature.summoning_sick = False
        self.host.state.phase = PHASE_DECLARE_ATTACKERS
        command = GameCommand.click(
            1,
            "player_2_creatures",
            creature.unit_id,
            command_id="remote-attacker",
        )

        event = self.host.receive_command(command, authenticated_player_id=1)

        self.assertEqual(event.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(self.host.state.selected_attackers, [creature.unit_id])

    def test_remote_defender_can_assign_their_own_blocker(self) -> None:
        attacker = self.host.state.create_builder_creature(
            self.host.state.player_one,
            aw=2,
            vw=1,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.VIGILANCE}),
        )
        blocker = self.host.state.create_builder_creature(
            self.host.state.player_two,
            aw=1,
            vw=2,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.VIGILANCE}),
        )
        blocker.tapped = False
        self.host.state.active_player_index = 0
        self.host.state.phase = PHASE_DECLARE_BLOCKERS
        self.host.state.block_assignments = {attacker.unit_id: None}

        select_blocker = self.host.receive_command(
            GameCommand.click(1, "player_2_creatures", blocker.unit_id),
            authenticated_player_id=1,
        )
        assign_blocker = self.host.receive_command(
            GameCommand.click(1, "player_1_creatures", attacker.unit_id),
            authenticated_player_id=1,
        )

        self.assertEqual(select_blocker.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(assign_blocker.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(self.host.state.block_assignments[attacker.unit_id], blocker.unit_id)

    def test_active_player_can_assign_provoke_target_during_block_phase(self) -> None:
        attacker = self.host.state.create_builder_creature(
            self.host.state.player_one,
            aw=2,
            vw=1,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.PROVOKE}),
        )
        blocker = self.host.state.create_builder_creature(
            self.host.state.player_two,
            aw=1,
            vw=2,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.VIGILANCE}),
        )
        self.host.state.active_player_index = 0
        self.host.state.phase = PHASE_DECLARE_BLOCKERS
        self.host.state.block_assignments = {attacker.unit_id: None}

        select_attacker = self.host.submit_click("player_1_creatures", attacker.unit_id)
        force_blocker = self.host.submit_click("player_2_creatures", blocker.unit_id)

        self.assertEqual(select_attacker.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(force_blocker.kind, EventKind.COMMAND_APPLIED)
        self.assertEqual(self.host.state.block_assignments[attacker.unit_id], blocker.unit_id)
        self.assertIn(attacker.unit_id, self.host.state.enraged_forced_attackers)

    def test_pvp_attack_flow_does_not_let_ai_choose_human_provoke_target(self) -> None:
        attacker = self.host.state.create_builder_creature(
            self.host.state.player_one,
            aw=2,
            vw=1,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.PROVOKE}),
        )
        blocker = self.host.state.create_builder_creature(
            self.host.state.player_two,
            aw=1,
            vw=2,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.VIGILANCE}),
        )
        attacker.tapped = False
        attacker.summoning_sick = False
        blocker.tapped = False
        self.host.state.active_player_index = 0
        self.host.state.phase = PHASE_DECLARE_ATTACKERS
        self.host.state.selected_attackers = [attacker.unit_id]

        self.host.state.confirm_attackers()

        self.assertEqual(self.host.state.phase, PHASE_DECLARE_BLOCKERS)
        self.assertEqual(self.host.state.block_assignments, {attacker.unit_id: None})
        self.assertEqual(self.host.state.enraged_forced_attackers, set())

    def test_rejects_spoofed_player_identity_without_mutating_state(self) -> None:
        self.start_with_remote_player()
        command = GameCommand.action(0, "builder_add_resource", command_id="spoofed")

        event = self.host.receive_command(command, authenticated_player_id=1)

        self.assertEqual(event.kind, EventKind.COMMAND_REJECTED)
        self.assertEqual(event.payload["code"], "player_identity_mismatch")
        self.assertEqual(self.host.state.player_one.total_resources(), 0)
        self.assertEqual(self.host.revision, 1)

    def test_rejects_local_player_command_during_remote_turn(self) -> None:
        self.start_with_remote_player()

        event = self.host.submit_action("builder_add_resource")

        self.assertEqual(event.kind, EventKind.COMMAND_REJECTED)
        self.assertEqual(event.payload["code"], "not_your_turn")
        self.assertEqual(self.host.state.player_one.total_resources(), 0)

    def test_only_host_can_start_a_match(self) -> None:
        command = GameCommand.start_game(1, 1, command_id="remote-start")

        event = self.host.receive_command(command, authenticated_player_id=1)

        self.assertEqual(event.kind, EventKind.COMMAND_REJECTED)
        self.assertEqual(event.payload["code"], "host_only")
        self.assertEqual(self.host.revision, 0)

    def test_engine_no_op_is_reported_as_rejected_command(self) -> None:
        self.start_with_remote_player()
        command = GameCommand.action(1, "unknown_action", command_id="invalid-action")

        event = self.host.receive_command(command, authenticated_player_id=1)

        self.assertEqual(event.kind, EventKind.COMMAND_REJECTED)
        self.assertEqual(event.payload["code"], "command_not_applied")
        self.assertEqual(self.host.revision, 1)

    def test_retried_remote_command_is_only_applied_once(self) -> None:
        self.start_with_remote_player()
        command = GameCommand.action(1, "builder_add_resource", command_id="retry-resource")

        first_event = self.host.receive_command(command, authenticated_player_id=1)
        second_event = self.host.receive_command(command, authenticated_player_id=1)

        self.assertIs(second_event, first_event)
        self.assertEqual(self.host.state.player_two.total_resources(), 1)
        self.assertEqual(self.host.revision, 2)

    def test_queued_remote_command_waits_while_host_is_paused(self) -> None:
        self.start_with_remote_player()
        command = GameCommand.action(1, "builder_add_resource", command_id="paused-command")
        self.host.enqueue_remote_command(command, authenticated_player_id=1)

        self.host.update(allow_commands=False)

        self.assertEqual(self.host.state.player_two.total_resources(), 0)
        self.host.update(allow_commands=True)
        self.assertEqual(self.host.state.player_two.total_resources(), 1)


if __name__ == "__main__":
    unittest.main()
