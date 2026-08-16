from __future__ import annotations

import socket
from enum import Enum
from threading import Event, Lock, Thread, current_thread
from uuid import uuid4

from multiplayer.host import AuthoritativeHostSession
from multiplayer.lobby_protocol import ClientHello, ServerError, ServerWelcome
from multiplayer.protocol import GameCommand, ProtocolValidationError, decode_wire_message
from multiplayer.transport import ConnectionClosed, FrameTooLarge, JsonFrameConnection


DEFAULT_GAME_PORT = 47621
HANDSHAKE_TIMEOUT_SECONDS = 10.0


class ServerStatus(str, Enum):
    STOPPED = "stopped"
    LISTENING = "listening"
    CONNECTED = "connected"
    ERROR = "error"


class HostServer:
    """Accepts one remote player and bridges TCP frames to the host session."""

    def __init__(
        self,
        session: AuthoritativeHostSession,
        *,
        bind_host: str = "0.0.0.0",
        port: int = DEFAULT_GAME_PORT,
        host_name: str = "Host",
    ) -> None:
        if len(session.remote_player_ids) != 1:
            raise ValueError("HostServer currently supports exactly one remote player.")
        self.session = session
        self.bind_host = bind_host
        self.requested_port = port
        self.host_name = host_name.strip() or "Host"
        self.session_id = uuid4().hex
        self._remote_player_id = session.remote_player_ids[0]
        self._listener: socket.socket | None = None
        self._connection: JsonFrameConnection | None = None
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._state_lock = Lock()
        self._status = ServerStatus.STOPPED
        self._bound_port = 0
        self._remote_name: str | None = None
        self._last_remote_name: str | None = None
        self._remote_client_id: str | None = None
        self._has_connected = False
        self._last_error: str | None = None

    @property
    def status(self) -> ServerStatus:
        with self._state_lock:
            return self._status

    @property
    def bound_port(self) -> int:
        with self._state_lock:
            return self._bound_port

    @property
    def remote_name(self) -> str | None:
        with self._state_lock:
            return self._remote_name

    @property
    def last_remote_name(self) -> str | None:
        with self._state_lock:
            return self._last_remote_name

    @property
    def has_connected(self) -> bool:
        with self._state_lock:
            return self._has_connected

    @property
    def last_error(self) -> str | None:
        with self._state_lock:
            return self._last_error

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.bind_host, self.requested_port))
            listener.listen(1)
            listener.settimeout(0.2)
        except OSError:
            listener.close()
            raise
        self._listener = listener
        self._stop_event.clear()
        with self._state_lock:
            self._bound_port = listener.getsockname()[1]
            self._status = ServerStatus.LISTENING
            self._last_error = None
        self.session.set_player_name(self.session.local_player_id, self.host_name)
        self._thread = Thread(target=self._run, name="godao-host-server", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        connection = self._connection
        if connection is not None:
            connection.close()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._listener = None
        with self._state_lock:
            self._status = ServerStatus.STOPPED
            self._remote_name = None

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                listener = self._listener
                if listener is None:
                    break
                try:
                    client_socket, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise
                self._handle_client(JsonFrameConnection(client_socket))
        except Exception as exc:
            if not self._stop_event.is_set():
                with self._state_lock:
                    self._status = ServerStatus.ERROR
                    self._last_error = f"{type(exc).__name__}: {exc}"

    def _handle_client(self, connection: JsonFrameConnection) -> None:
        self._connection = connection
        try:
            raw_hello = connection.receive(timeout=HANDSHAKE_TIMEOUT_SECONDS)
            if raw_hello is None:
                connection.send(
                    ServerError("handshake_timeout", "Client did not send a hello message in time.").to_json()
                )
                return
            hello = ClientHello.from_json(raw_hello)
            identity_error = self._client_identity_error(hello)
            if identity_error is not None:
                code, message = identity_error
                connection.send(ServerError(code, message).to_json())
                return
            self.session.set_player_name(self._remote_player_id, hello.player_name)
            self.session.drain_player_events(self._remote_player_id)
            welcome = ServerWelcome(
                session_id=self.session_id,
                assigned_player_id=self._remote_player_id,
                host_name=self.host_name,
                snapshot=self.session.snapshot_for_player(self._remote_player_id),
            )
            connection.send(welcome.to_json())
            with self._state_lock:
                self._status = ServerStatus.CONNECTED
                self._remote_name = hello.player_name
                self._last_remote_name = hello.player_name
                self._remote_client_id = hello.client_id
                self._has_connected = True
                self._last_error = None

            while not self._stop_event.is_set():
                raw_message = connection.receive(timeout=0.05)
                if raw_message is not None:
                    self._handle_client_message(connection, raw_message)
                self._flush_remote_events(connection)
        except (ConnectionClosed, FrameTooLarge):
            pass
        except ProtocolValidationError as exc:
            try:
                connection.send(ServerError("invalid_handshake", str(exc)).to_json())
            except ConnectionClosed:
                pass
        finally:
            connection.close()
            self._connection = None
            with self._state_lock:
                self._remote_name = None
                if not self._stop_event.is_set() and self._status is not ServerStatus.ERROR:
                    self._status = ServerStatus.LISTENING

    def _handle_client_message(self, connection: JsonFrameConnection, raw_message: str) -> None:
        try:
            message = decode_wire_message(raw_message)
            if not isinstance(message, GameCommand):
                raise ProtocolValidationError("The host only accepts GameCommand messages from clients.")
            self.session.enqueue_remote_command(
                message,
                authenticated_player_id=self._remote_player_id,
            )
        except (ProtocolValidationError, ValueError) as exc:
            connection.send(
                ServerError("invalid_command", str(exc), fatal=False).to_json()
            )

    def _client_identity_error(self, hello: ClientHello) -> tuple[str, str] | None:
        existing_client_id = self._remote_client_id
        if existing_client_id is None:
            if hello.resume_session_id is not None:
                return "unknown_session", "The requested match is no longer available."
            return None
        if (
            hello.client_id == existing_client_id
            and hello.resume_session_id == self.session_id
        ):
            return None
        if self.session.state.turn_number == 0 and hello.resume_session_id is None:
            return None
        return (
            "session_in_use",
            "This match is reserved for the original guest. Reconnect from the same game instance.",
        )

    def _flush_remote_events(self, connection: JsonFrameConnection) -> None:
        for event in self.session.drain_player_events(self._remote_player_id):
            connection.send(event.to_json())
