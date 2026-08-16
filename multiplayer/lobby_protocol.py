from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from multiplayer.protocol import PROTOCOL_VERSION, ProtocolValidationError
from multiplayer.snapshot import GameStateSnapshot


def _new_id() -> str:
    return uuid4().hex


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolValidationError(f"{label} must be a JSON object.")
    return dict(value)


def _require_exact_fields(data: dict[str, Any], fields: set[str], label: str) -> None:
    if set(data) != fields:
        raise ProtocolValidationError(f"{label} fields do not match the protocol schema.")


def _require_text(value: Any, label: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ProtocolValidationError(
            f"{label} must be non-empty text with at most {max_length} characters."
        )
    return value.strip()


def _encode(data: dict[str, Any]) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ProtocolValidationError("Lobby message must be text.")
    try:
        return _require_object(json.loads(raw), "lobby message")
    except json.JSONDecodeError as exc:
        raise ProtocolValidationError("Lobby message is not valid JSON.") from exc


@dataclass(frozen=True, slots=True)
class ClientHello:
    player_name: str
    client_id: str = field(default_factory=_new_id)
    resume_session_id: str | None = None
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "player_name", _require_text(self.player_name, "player_name", max_length=32))
        _require_text(self.client_id, "client_id", max_length=64)
        if self.resume_session_id is not None:
            object.__setattr__(
                self,
                "resume_session_id",
                _require_text(self.resume_session_id, "resume_session_id", max_length=64),
            )
        if isinstance(self.version, bool) or self.version != PROTOCOL_VERSION:
            raise ProtocolValidationError(
                f"Unsupported protocol version {self.version}; expected {PROTOCOL_VERSION}."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_type": "client_hello",
            "version": self.version,
            "client_id": self.client_id,
            "player_name": self.player_name,
            "resume_session_id": self.resume_session_id,
        }

    def to_json(self) -> str:
        return _encode(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClientHello:
        data = _require_object(data, "client_hello")
        _require_exact_fields(
            data,
            {
                "message_type",
                "version",
                "client_id",
                "player_name",
                "resume_session_id",
            },
            "client_hello",
        )
        if data["message_type"] != "client_hello":
            raise ProtocolValidationError("Invalid client_hello message_type.")
        return cls(
            player_name=data["player_name"],
            client_id=data["client_id"],
            resume_session_id=data["resume_session_id"],
            version=data["version"],
        )

    @classmethod
    def from_json(cls, raw: str) -> ClientHello:
        return cls.from_dict(_decode(raw))


@dataclass(frozen=True, slots=True)
class ServerWelcome:
    session_id: str
    assigned_player_id: int
    host_name: str
    snapshot: GameStateSnapshot
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_text(self.session_id, "session_id", max_length=64)
        _require_text(self.host_name, "host_name", max_length=32)
        if (
            isinstance(self.assigned_player_id, bool)
            or not isinstance(self.assigned_player_id, int)
            or self.assigned_player_id < 0
        ):
            raise ProtocolValidationError("assigned_player_id must be an integer >= 0.")
        if not isinstance(self.snapshot, GameStateSnapshot):
            raise ProtocolValidationError("snapshot must be a GameStateSnapshot.")
        if self.snapshot.viewer_player_id != self.assigned_player_id:
            raise ProtocolValidationError("Welcome snapshot belongs to another player.")
        if isinstance(self.version, bool) or self.version != PROTOCOL_VERSION:
            raise ProtocolValidationError(
                f"Unsupported protocol version {self.version}; expected {PROTOCOL_VERSION}."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_type": "server_welcome",
            "version": self.version,
            "session_id": self.session_id,
            "assigned_player_id": self.assigned_player_id,
            "host_name": self.host_name,
            "snapshot": self.snapshot.to_dict(),
        }

    def to_json(self) -> str:
        return _encode(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerWelcome:
        data = _require_object(data, "server_welcome")
        _require_exact_fields(
            data,
            {
                "message_type",
                "version",
                "session_id",
                "assigned_player_id",
                "host_name",
                "snapshot",
            },
            "server_welcome",
        )
        if data["message_type"] != "server_welcome":
            raise ProtocolValidationError("Invalid server_welcome message_type.")
        return cls(
            session_id=data["session_id"],
            assigned_player_id=data["assigned_player_id"],
            host_name=data["host_name"],
            snapshot=GameStateSnapshot.from_dict(data["snapshot"]),
            version=data["version"],
        )

    @classmethod
    def from_json(cls, raw: str) -> ServerWelcome:
        return cls.from_dict(_decode(raw))


@dataclass(frozen=True, slots=True)
class ServerError:
    code: str
    message: str
    fatal: bool = True
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_text(self.code, "error code", max_length=64)
        _require_text(self.message, "error message", max_length=512)
        if not isinstance(self.fatal, bool):
            raise ProtocolValidationError("fatal must be a boolean.")
        if isinstance(self.version, bool) or self.version != PROTOCOL_VERSION:
            raise ProtocolValidationError(
                f"Unsupported protocol version {self.version}; expected {PROTOCOL_VERSION}."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_type": "server_error",
            "version": self.version,
            "code": self.code,
            "message": self.message,
            "fatal": self.fatal,
        }

    def to_json(self) -> str:
        return _encode(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerError:
        data = _require_object(data, "server_error")
        _require_exact_fields(
            data,
            {"message_type", "version", "code", "message", "fatal"},
            "server_error",
        )
        if data["message_type"] != "server_error":
            raise ProtocolValidationError("Invalid server_error message_type.")
        return cls(
            code=data["code"],
            message=data["message"],
            fatal=data["fatal"],
            version=data["version"],
        )

    @classmethod
    def from_json(cls, raw: str) -> ServerError:
        return cls.from_dict(_decode(raw))


def decode_lobby_message(raw: str) -> ClientHello | ServerWelcome | ServerError:
    data = _decode(raw)
    message_type = data.get("message_type")
    if message_type == "client_hello":
        return ClientHello.from_dict(data)
    if message_type == "server_welcome":
        return ServerWelcome.from_dict(data)
    if message_type == "server_error":
        return ServerError.from_dict(data)
    raise ProtocolValidationError(f"Unsupported lobby message_type: {message_type!r}.")
