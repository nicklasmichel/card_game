from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.game_logic import GameEngine
from core.config import STARTING_LIFE
from core.models import MatchMode, PHASE_BUILDER_CREATURE, PHASE_DECLARE_ATTACKERS
from multiplayer.client import ClientStatus, NetworkClientSession
from multiplayer.host import AuthoritativeHostSession
from multiplayer.server import HostServer, ServerStatus


def wait_until(predicate, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class MultiplayerLoopbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        engine = GameEngine(auto_start=False, match_mode=MatchMode.PVP)
        engine.log_path = Path(self.temp_dir.name) / "loopback.log"
        self.host = AuthoritativeHostSession(engine)
        self.server = HostServer(
            self.host,
            bind_host="127.0.0.1",
            port=0,
            host_name="HostPlayer",
        )
        self.server.start()
        self.client = NetworkClientSession.connect(
            "127.0.0.1",
            port=self.server.bound_port,
            player_name="RemotePlayer",
            timeout=2.0,
        )
        self.assertTrue(wait_until(lambda: self.server.status is ServerStatus.CONNECTED))

    def tearDown(self) -> None:
        self.client.close()
        self.server.stop()
        self.host.close()
        self.temp_dir.cleanup()

    def pump_client_until(self, predicate, *, timeout: float = 3.0) -> bool:
        def updated_predicate() -> bool:
            self.host.update()
            self.client.update()
            return predicate()

        return wait_until(updated_predicate, timeout=timeout)

    def test_handshake_assigns_remote_identity_and_current_snapshot(self) -> None:
        self.assertEqual(self.client.status, ClientStatus.CONNECTED)
        self.assertEqual(self.client.local_player_id, 1)
        self.assertEqual(self.client.state.human_player.player_id, 1)
        self.assertEqual(self.host.state.player_one.name, "HostPlayer")
        self.assertEqual(self.host.state.player_two.name, "RemotePlayer")

    def test_host_start_and_remote_action_round_trip(self) -> None:
        self.host.start_new_game(starting_player_id=1)
        self.assertTrue(
            self.pump_client_until(
                lambda: self.client.state.snapshot_revision == self.host.revision
                and self.client.state.active_player.player_id == 1
            )
        )

        self.client.submit_action("builder_add_resource")

        self.assertTrue(
            self.pump_client_until(
                lambda: self.client.state.human_player.total_resources() == 1
            )
        )
        self.assertEqual(self.host.state.player_two.total_resources(), 1)
        self.assertEqual(self.client.state.snapshot_revision, self.host.revision)
        self.assertEqual(
            self.client.state.log_messages,
            self.host.state.public_log_messages,
        )
        self.assertTrue(
            any(
                message.startswith("RemotePlayer increases resources")
                for message in self.client.state.log_messages
            )
        )

    def test_client_detects_server_disconnect(self) -> None:
        self.server.stop()

        self.assertTrue(
            wait_until(
                lambda: self.client.status is ClientStatus.RECONNECTING,
                timeout=3.0,
            )
        )

    def test_remote_player_can_reconnect_to_current_revision(self) -> None:
        self.host.start_new_game(starting_player_id=0)
        self.assertTrue(
            self.pump_client_until(
                lambda: self.client.state.snapshot_revision == self.host.revision
            )
        )
        current_revision = self.host.revision
        connection = self.server._connection
        self.assertIsNotNone(connection)
        connection.close()
        self.assertTrue(wait_until(lambda: self.server.status is ServerStatus.LISTENING))
        self.assertTrue(
            wait_until(
                lambda: (
                    self.client.update() is None
                    and self.server.status is ServerStatus.CONNECTED
                    and self.client.status is ClientStatus.CONNECTED
                    and self.client.reconnect_count == 1
                ),
                timeout=5.0,
            )
        )
        self.assertGreaterEqual(self.client.state.snapshot_revision, current_revision)
        self.assertEqual(self.client.state.human_player.name, "RemotePlayer")

    def test_new_client_cannot_take_over_started_match(self) -> None:
        self.host.start_new_game(starting_player_id=0)
        self.client.close()
        self.assertTrue(wait_until(lambda: self.server.status is ServerStatus.LISTENING))

        with self.assertRaisesRegex(ConnectionError, "session_in_use"):
            NetworkClientSession.connect(
                "127.0.0.1",
                port=self.server.bound_port,
                player_name="Intruder",
                timeout=2.0,
            )

    def test_several_alternating_turns_stay_in_sync(self) -> None:
        self.host.start_new_game(starting_player_id=1)
        self.assertTrue(
            self.pump_client_until(lambda: self.client.state.active_player.player_id == 1)
        )

        for expected_resource_count in range(1, 4):
            self.client.submit_action("builder_add_resource")
            self.assertTrue(
                self.pump_client_until(
                    lambda: self.client.state.active_player.player_id == 0
                )
            )
            self.host.submit_action("builder_add_resource")
            self.assertTrue(
                self.pump_client_until(
                    lambda: self.client.state.active_player.player_id == 1
                    and self.client.state.ai_player.total_resources() == expected_resource_count
                    and self.client.state.human_player.total_resources() == expected_resource_count
                )
            )

        self.assertEqual(self.client.state.snapshot_revision, self.host.revision)
        self.assertEqual(self.host.state.player_one.total_resources(), 3)
        self.assertEqual(self.host.state.player_two.total_resources(), 3)

    def test_remote_builder_and_attack_flow_round_trips_rich_snapshots(self) -> None:
        self.host.start_new_game(starting_player_id=1)
        self.assertTrue(
            self.pump_client_until(lambda: self.client.state.active_player.player_id == 1)
        )
        for _ in range(2):
            self.client.submit_action("builder_add_resource")
            self.assertTrue(
                self.pump_client_until(lambda: self.client.state.active_player.player_id == 0)
            )
            self.host.submit_action("builder_add_resource")
            self.assertTrue(
                self.pump_client_until(lambda: self.client.state.active_player.player_id == 1)
            )

        self.client.submit_action("builder_open_creature")
        self.assertTrue(
            self.pump_client_until(
                lambda: self.client.state.phase == PHASE_BUILDER_CREATURE
                and self.client.state.pending_builder_creature is not None
            )
        )
        self.client.submit_action("builder_sw_up")
        self.client.submit_action("builder_sw_up")
        self.client.submit_action("builder_confirm_creature")
        self.assertTrue(
            self.pump_client_until(
                lambda: self.client.state.active_player.player_id == 0
                and len(self.client.state.human_player.battlefield) == 1
            )
        )
        self.host.submit_action("builder_add_resource")
        self.assertTrue(
            self.pump_client_until(lambda: self.client.state.active_player.player_id == 1)
        )
        self.client.submit_action("builder_add_resource")
        self.assertTrue(
            self.pump_client_until(lambda: self.client.state.phase == PHASE_DECLARE_ATTACKERS)
        )
        attacker_id = self.client.state.human_player.battlefield[0].unit_id

        self.client.submit_click("player_1_creatures", attacker_id)
        self.assertTrue(
            self.pump_client_until(
                lambda: attacker_id in self.client.state.selected_attackers
            )
        )
        self.client.submit_action("confirm_attackers")

        self.assertTrue(
            self.pump_client_until(
                lambda: self.client.state.ai_player.life < STARTING_LIFE
            )
        )
        self.assertLess(self.host.state.player_one.life, STARTING_LIFE)
        self.assertEqual(self.client.state.snapshot_revision, self.host.revision)


if __name__ == "__main__":
    unittest.main()
