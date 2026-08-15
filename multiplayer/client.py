from __future__ import annotations

import socket
from enum import Enum
from threading import Lock, Thread, current_thread

from core.models import MatchMode
from multiplayer.client_state import ClientGameView
from multiplayer.lobby_protocol import (
    ClientHello,
    ServerError,
    ServerWelcome,
    decode_lobby_message,
)
from multiplayer.protocol import EventKind, GameCommand, GameEvent, decode_wire_message
from multiplayer.server import DEFAULT_GAME_PORT
from multiplayer.snapshot import GameStateSnapshot
from multiplayer.transport import ConnectionClosed, JsonFrameConnection


class ClientStatus(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    CLOSED = "closed"


class NetworkClientSession:
    """GameSession implementation backed by a remote authoritative host."""

    def __init__(
        self,
        connection: JsonFrameConnection,
        welcome: ServerWelcome,
        *,
        player_name: str,
    ) -> None:
        self._connection = connection
        self._local_player_id = welcome.assigned_player_id
        self._state = ClientGameView(self._local_player_id)
        self._state.apply_snapshot(welcome.snapshot)
        self._state.log_messages = [
            f"Connected to {welcome.host_name} as {player_name}."
        ]
        self.session_id = welcome.session_id
        self.host_name = welcome.host_name
        self.player_name = player_name
        self._status = ClientStatus.CONNECTED
        self._last_error: str | None = None
        self._incoming_lock = Lock()
        self._incoming_messages: list[GameEvent | ServerError] = []
        self._processed_events: list[GameEvent] = []
        self._closed = False
        self._receiver_thread = Thread(
            target=self._receive_loop,
            name="godao-network-client",
            daemon=True,
        )
        self._receiver_thread.start()

    @classmethod
    def connect(
        cls,
        host: str,
        *,
        port: int = DEFAULT_GAME_PORT,
        player_name: str = "Guest",
        timeout: float = 10.0,
    ) -> NetworkClientSession:
        sock = socket.create_connection((host, port), timeout=timeout)
        connection = JsonFrameConnection(sock)
        try:
            connection.send(ClientHello(player_name=player_name).to_json())
            raw_response = connection.receive(timeout=timeout)
            if raw_response is None:
                raise TimeoutError("Host did not complete the handshake in time.")
            response = decode_lobby_message(raw_response)
            if isinstance(response, ServerError):
                raise ConnectionError(f"{response.code}: {response.message}")
            if not isinstance(response, ServerWelcome):
                raise ConnectionError("Host returned an unexpected handshake message.")
            return cls(connection, response, player_name=player_name)
        except Exception:
            connection.close()
            raise

    @property
    def state(self) -> ClientGameView:
        return self._state

    @property
    def match_mode(self) -> MatchMode:
        return MatchMode.PVP

    @property
    def local_player_id(self) -> int:
        return self._local_player_id

    @property
    def should_exit(self) -> bool:
        return self._state.exit_requested

    @property
    def status(self) -> ClientStatus:
        return self._status

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start_new_game(self, starting_player_id: int | None = None) -> None:
        self.submit_command(
            GameCommand.start_game(self.local_player_id, starting_player_id)
        )

    def submit_action(self, action: str) -> None:
        self.submit_command(GameCommand.action(self.local_player_id, action))

    def submit_click(self, area: str, item_id: int) -> None:
        self.submit_command(GameCommand.click(self.local_player_id, area, item_id))

    def submit_hand_card_play(self, card_id: int) -> None:
        self.submit_command(GameCommand.play_hand_card(self.local_player_id, card_id))

    def submit_command(self, command: GameCommand) -> None:
        if command.player_id != self.local_player_id:
            raise ValueError("Client may only submit commands for its assigned player.")
        if self._status is not ClientStatus.CONNECTED:
            self._state.log_messages.append("Command not sent: no connection to host.")
            return
        try:
            self._connection.send(command.to_json())
        except ConnectionClosed as exc:
            self._mark_disconnected(str(exc), error=True)

    def drain_events(self) -> list[GameEvent]:
        events = self._processed_events[:]
        self._processed_events.clear()
        return events

    def update(
        self,
        *,
        allow_ai: bool = True,
        allow_automatic_rules: bool = True,
        allow_commands: bool = True,
    ) -> None:
        with self._incoming_lock:
            messages = self._incoming_messages[:]
            self._incoming_messages.clear()
        for message in messages:
            if isinstance(message, ServerError):
                self._state.log_messages.append(
                    f"Network error ({message.code}): {message.message}"
                )
                if message.fatal:
                    self._mark_disconnected(message.message, error=True)
                continue
            self._processed_events.append(message)
            if message.kind is EventKind.STATE_SNAPSHOT:
                snapshot = GameStateSnapshot.from_dict(message.payload["snapshot"])
                self._state.apply_snapshot(snapshot)
            elif message.kind is EventKind.COMMAND_REJECTED:
                self._state.log_messages.append(
                    f"Action rejected: {message.payload['message']}"
                )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._status = ClientStatus.CLOSED
        self._connection.close()
        thread = self._receiver_thread
        if thread.is_alive() and thread is not current_thread():
            thread.join(timeout=2.0)

    def _receive_loop(self) -> None:
        try:
            while not self._closed:
                raw_message = self._connection.receive(timeout=0.2)
                if raw_message is None:
                    continue
                try:
                    message = decode_wire_message(raw_message)
                    if not isinstance(message, GameEvent):
                        raise ValueError("Client expected a GameEvent from the host.")
                    self._queue_incoming(message)
                except Exception as wire_error:
                    try:
                        lobby_message = decode_lobby_message(raw_message)
                    except Exception:
                        self._mark_disconnected(str(wire_error), error=True)
                        return
                    if not isinstance(lobby_message, ServerError):
                        self._mark_disconnected("Unexpected host message.", error=True)
                        return
                    self._queue_incoming(lobby_message)
                    if lobby_message.fatal:
                        return
        except ConnectionClosed as exc:
            if not self._closed:
                self._mark_disconnected(str(exc), error=False)
        except Exception as exc:
            if not self._closed:
                self._mark_disconnected(f"{type(exc).__name__}: {exc}", error=True)

    def _queue_incoming(self, message: GameEvent | ServerError) -> None:
        with self._incoming_lock:
            self._incoming_messages.append(message)

    def _mark_disconnected(self, message: str, *, error: bool) -> None:
        if self._closed:
            return
        self._last_error = message
        self._status = ClientStatus.ERROR if error else ClientStatus.DISCONNECTED
