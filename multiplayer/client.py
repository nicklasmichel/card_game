from __future__ import annotations

import socket
from enum import Enum
from threading import Event, Lock, Thread, current_thread
from uuid import uuid4

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


RECONNECT_MIN_DELAY_SECONDS = 0.35
RECONNECT_MAX_DELAY_SECONDS = 4.0
RECONNECT_CONNECT_TIMEOUT_SECONDS = 2.0


class ClientStatus(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
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
        host: str,
        port: int,
        player_name: str,
        client_id: str,
    ) -> None:
        self._connection = connection
        self._connection_lock = Lock()
        self._local_player_id = welcome.assigned_player_id
        self._state = ClientGameView(self._local_player_id)
        self._state.apply_snapshot(welcome.snapshot)
        self.session_id = welcome.session_id
        self.host_name = welcome.host_name
        self.host = host
        self.port = port
        self.player_name = player_name
        self.client_id = client_id
        self._status = ClientStatus.CONNECTED
        self._last_error: str | None = None
        self._reconnect_attempt = 0
        self._reconnect_count = 0
        self._incoming_lock = Lock()
        self._incoming_messages: list[GameEvent | ServerError | ServerWelcome] = []
        self._processed_events: list[GameEvent] = []
        self._closed = False
        self._stop_event = Event()
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
        client_id = uuid4().hex
        connection, welcome = cls._perform_handshake(
            host,
            port,
            player_name=player_name,
            client_id=client_id,
            resume_session_id=None,
            timeout=timeout,
        )
        return cls(
            connection,
            welcome,
            host=host,
            port=port,
            player_name=player_name,
            client_id=client_id,
        )

    @staticmethod
    def _perform_handshake(
        host: str,
        port: int,
        *,
        player_name: str,
        client_id: str,
        resume_session_id: str | None,
        timeout: float,
    ) -> tuple[JsonFrameConnection, ServerWelcome]:
        sock = socket.create_connection((host, port), timeout=timeout)
        connection = JsonFrameConnection(sock)
        try:
            connection.send(
                ClientHello(
                    player_name=player_name,
                    client_id=client_id,
                    resume_session_id=resume_session_id,
                ).to_json()
            )
            raw_response = connection.receive(timeout=timeout)
            if raw_response is None:
                raise TimeoutError("Host did not complete the handshake in time.")
            response = decode_lobby_message(raw_response)
            if isinstance(response, ServerError):
                raise ConnectionError(f"{response.code}: {response.message}")
            if not isinstance(response, ServerWelcome):
                raise ConnectionError("Host returned an unexpected handshake message.")
            return connection, response
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

    @property
    def reconnect_attempt(self) -> int:
        return self._reconnect_attempt

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

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
            return
        with self._connection_lock:
            connection = self._connection
        try:
            connection.send(command.to_json())
        except ConnectionClosed as exc:
            self._start_reconnecting(str(exc))
            connection.close()

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
            if isinstance(message, ServerWelcome):
                self._state.apply_snapshot(message.snapshot)
                self._last_error = None
                self._status = ClientStatus.CONNECTED
                continue
            if isinstance(message, ServerError):
                self._state.log_messages.append(
                    f"Network error ({message.code}): {message.message}"
                )
                if message.fatal:
                    self._mark_terminal_error(message.message)
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
        self._stop_event.set()
        self._status = ClientStatus.CLOSED
        with self._connection_lock:
            connection = self._connection
        connection.close()
        thread = self._receiver_thread
        if thread.is_alive() and thread is not current_thread():
            thread.join(timeout=3.0)

    def _receive_loop(self) -> None:
        while not self._closed:
            with self._connection_lock:
                connection = self._connection
            try:
                raw_message = connection.receive(timeout=0.2)
                if raw_message is None:
                    continue
                self._handle_host_message(raw_message)
            except ConnectionClosed as exc:
                if self._closed or self._status is ClientStatus.ERROR:
                    return
                if not self._reconnect(str(exc)):
                    return
            except Exception as exc:
                if self._closed or self._status is ClientStatus.ERROR:
                    return
                if not self._reconnect(f"{type(exc).__name__}: {exc}"):
                    return

    def _handle_host_message(self, raw_message: str) -> None:
        try:
            message = decode_wire_message(raw_message)
            if not isinstance(message, GameEvent):
                raise ValueError("Client expected a GameEvent from the host.")
            self._queue_incoming(message)
            return
        except Exception as wire_error:
            try:
                lobby_message = decode_lobby_message(raw_message)
            except Exception:
                raise wire_error
        if not isinstance(lobby_message, ServerError):
            raise ValueError("Unexpected host message.")
        self._queue_incoming(lobby_message)
        if lobby_message.fatal:
            self._mark_terminal_error(lobby_message.message)
            raise ConnectionClosed(lobby_message.message)

    def _reconnect(self, reason: str) -> bool:
        self._start_reconnecting(reason)
        with self._connection_lock:
            old_connection = self._connection
        old_connection.close()
        delay = RECONNECT_MIN_DELAY_SECONDS
        while not self._closed:
            self._reconnect_attempt += 1
            if self._stop_event.wait(delay):
                return False
            try:
                connection, welcome = self._perform_handshake(
                    self.host,
                    self.port,
                    player_name=self.player_name,
                    client_id=self.client_id,
                    resume_session_id=self.session_id,
                    timeout=RECONNECT_CONNECT_TIMEOUT_SECONDS,
                )
                if welcome.session_id != self.session_id:
                    connection.close()
                    raise ConnectionError("The host is running a different match.")
                if welcome.assigned_player_id != self.local_player_id:
                    connection.close()
                    raise ConnectionError("The host assigned a different player slot.")
            except Exception as exc:
                self._last_error = str(exc)
                delay = min(RECONNECT_MAX_DELAY_SECONDS, delay * 1.7)
                continue
            with self._connection_lock:
                self._connection = connection
            self._queue_incoming(welcome)
            self._last_error = None
            self._reconnect_attempt = 0
            self._reconnect_count += 1
            return True
        return False

    def _queue_incoming(self, message: GameEvent | ServerError | ServerWelcome) -> None:
        with self._incoming_lock:
            self._incoming_messages.append(message)

    def _start_reconnecting(self, message: str) -> None:
        if self._closed or self._status is ClientStatus.ERROR:
            return
        self._last_error = message
        self._status = ClientStatus.RECONNECTING

    def _mark_terminal_error(self, message: str) -> None:
        if self._closed:
            return
        self._last_error = message
        self._status = ClientStatus.ERROR
