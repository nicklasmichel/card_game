from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4


PROTOCOL_VERSION = 2
MAX_WIRE_MESSAGE_BYTES = 64 * 1024


class ProtocolValidationError(ValueError):
    """Raised when a wire message does not satisfy the GODAO protocol."""


class CommandKind(str, Enum):
    START_GAME = "start_game"
    ACTION = "action"
    CLICK = "click"
    PLAY_HAND_CARD = "play_hand_card"


class EventKind(str, Enum):
    COMMAND_APPLIED = "command_applied"
    COMMAND_REJECTED = "command_rejected"
    STATE_SNAPSHOT = "state_snapshot"


if TYPE_CHECKING:
    from multiplayer.snapshot import GameStateSnapshot


def _new_id() -> str:
    return uuid4().hex


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolValidationError(f"{label} must be a JSON object.")
    if any(not isinstance(key, str) for key in value):
        raise ProtocolValidationError(f"{label} keys must be strings.")
    return dict(value)


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing={missing}")
    if unexpected:
        details.append(f"unexpected={unexpected}")
    raise ProtocolValidationError(f"Invalid {label} fields ({', '.join(details)}).")


def _require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProtocolValidationError(f"{label} must be an integer >= {minimum}.")
    return value


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolValidationError(f"{label} must be a non-empty string.")
    return value


def _validate_json_value(value: Any, label: str) -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolValidationError(f"{label} contains a non-finite number.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolValidationError(f"{label} contains a non-string key.")
            _validate_json_value(item, f"{label}.{key}")
        return
    raise ProtocolValidationError(f"{label} contains a non-JSON value: {type(value).__name__}.")


def _coerce_enum(enum_type: type[Enum], value: Any, label: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolValidationError(f"Unsupported {label}: {value!r}.") from exc


def _decode_json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ProtocolValidationError("Wire message must be text.")
    if len(raw.encode("utf-8")) > MAX_WIRE_MESSAGE_BYTES:
        raise ProtocolValidationError("Wire message exceeds the size limit.")
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolValidationError("Wire message is not valid JSON.") from exc
    return _require_object(decoded, "wire message")


@dataclass(frozen=True, slots=True)
class GameCommand:
    kind: CommandKind
    player_id: int
    payload: dict[str, Any]
    command_id: str = field(default_factory=_new_id)
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        kind = _coerce_enum(CommandKind, self.kind, "command kind")
        object.__setattr__(self, "kind", kind)
        _require_int(self.player_id, "player_id")
        _require_non_empty_string(self.command_id, "command_id")
        _require_int(self.version, "version", minimum=1)
        if self.version != PROTOCOL_VERSION:
            raise ProtocolValidationError(
                f"Unsupported protocol version {self.version}; expected {PROTOCOL_VERSION}."
            )
        payload = _require_object(self.payload, "command payload")
        _validate_json_value(payload, "command payload")
        self._validate_payload(kind, payload)
        object.__setattr__(self, "payload", payload)

    @staticmethod
    def _validate_payload(kind: CommandKind, payload: dict[str, Any]) -> None:
        if kind is CommandKind.START_GAME:
            _require_exact_keys(payload, {"starting_player_id"}, "start_game payload")
            starting_player_id = payload["starting_player_id"]
            if starting_player_id is not None:
                _require_int(starting_player_id, "starting_player_id")
                if starting_player_id not in {0, 1}:
                    raise ProtocolValidationError("starting_player_id must be 0, 1, or null.")
            return
        if kind is CommandKind.ACTION:
            _require_exact_keys(payload, {"action"}, "action payload")
            _require_non_empty_string(payload["action"], "action")
            return
        if kind is CommandKind.CLICK:
            _require_exact_keys(payload, {"area", "item_id"}, "click payload")
            _require_non_empty_string(payload["area"], "area")
            _require_int(payload["item_id"], "item_id")
            return
        if kind is CommandKind.PLAY_HAND_CARD:
            _require_exact_keys(payload, {"card_id"}, "play_hand_card payload")
            _require_int(payload["card_id"], "card_id")
            return
        raise ProtocolValidationError(f"Unsupported command kind: {kind!r}.")

    @classmethod
    def start_game(
        cls,
        player_id: int,
        starting_player_id: int | None,
        *,
        command_id: str | None = None,
    ) -> GameCommand:
        return cls(
            kind=CommandKind.START_GAME,
            player_id=player_id,
            payload={"starting_player_id": starting_player_id},
            command_id=command_id or _new_id(),
        )

    @classmethod
    def action(
        cls,
        player_id: int,
        action: str,
        *,
        command_id: str | None = None,
    ) -> GameCommand:
        return cls(
            kind=CommandKind.ACTION,
            player_id=player_id,
            payload={"action": action},
            command_id=command_id or _new_id(),
        )

    @classmethod
    def click(
        cls,
        player_id: int,
        area: str,
        item_id: int,
        *,
        command_id: str | None = None,
    ) -> GameCommand:
        return cls(
            kind=CommandKind.CLICK,
            player_id=player_id,
            payload={"area": area, "item_id": item_id},
            command_id=command_id or _new_id(),
        )

    @classmethod
    def play_hand_card(
        cls,
        player_id: int,
        card_id: int,
        *,
        command_id: str | None = None,
    ) -> GameCommand:
        return cls(
            kind=CommandKind.PLAY_HAND_CARD,
            player_id=player_id,
            payload={"card_id": card_id},
            command_id=command_id or _new_id(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_type": "command",
            "version": self.version,
            "command_id": self.command_id,
            "player_id": self.player_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameCommand:
        data = _require_object(data, "command")
        _require_exact_keys(
            data,
            {"message_type", "version", "command_id", "player_id", "kind", "payload"},
            "command",
        )
        if data["message_type"] != "command":
            raise ProtocolValidationError("message_type must be 'command'.")
        return cls(
            kind=data["kind"],
            player_id=data["player_id"],
            payload=data["payload"],
            command_id=data["command_id"],
            version=data["version"],
        )

    @classmethod
    def from_json(cls, raw: str) -> GameCommand:
        return cls.from_dict(_decode_json_object(raw))


@dataclass(frozen=True, slots=True)
class GameEvent:
    kind: EventKind
    sequence: int
    payload: dict[str, Any]
    command_id: str | None = None
    event_id: str = field(default_factory=_new_id)
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        kind = _coerce_enum(EventKind, self.kind, "event kind")
        object.__setattr__(self, "kind", kind)
        _require_int(self.sequence, "sequence", minimum=1)
        _require_non_empty_string(self.event_id, "event_id")
        if self.command_id is not None:
            _require_non_empty_string(self.command_id, "command_id")
        _require_int(self.version, "version", minimum=1)
        if self.version != PROTOCOL_VERSION:
            raise ProtocolValidationError(
                f"Unsupported protocol version {self.version}; expected {PROTOCOL_VERSION}."
            )
        payload = _require_object(self.payload, "event payload")
        _validate_json_value(payload, "event payload")
        self._validate_payload(kind, payload)
        object.__setattr__(self, "payload", payload)

    @staticmethod
    def _validate_payload(kind: EventKind, payload: dict[str, Any]) -> None:
        if kind is EventKind.COMMAND_APPLIED:
            _require_exact_keys(payload, {"command_kind"}, "command_applied payload")
            _coerce_enum(CommandKind, payload["command_kind"], "command kind")
            return
        if kind is EventKind.COMMAND_REJECTED:
            _require_exact_keys(payload, {"code", "message"}, "command_rejected payload")
            _require_non_empty_string(payload["code"], "rejection code")
            _require_non_empty_string(payload["message"], "rejection message")
            return
        if kind is EventKind.STATE_SNAPSHOT:
            _require_exact_keys(payload, {"snapshot"}, "state_snapshot payload")
            from multiplayer.snapshot import GameStateSnapshot

            GameStateSnapshot.from_dict(payload["snapshot"])
            return
        raise ProtocolValidationError(f"Unsupported event kind: {kind!r}.")

    @classmethod
    def command_applied(cls, command: GameCommand, sequence: int) -> GameEvent:
        return cls(
            kind=EventKind.COMMAND_APPLIED,
            sequence=sequence,
            command_id=command.command_id,
            payload={"command_kind": command.kind.value},
        )

    @classmethod
    def command_rejected(
        cls,
        command: GameCommand,
        sequence: int,
        *,
        code: str,
        message: str,
    ) -> GameEvent:
        return cls(
            kind=EventKind.COMMAND_REJECTED,
            sequence=sequence,
            command_id=command.command_id,
            payload={"code": code, "message": message},
        )

    @classmethod
    def state_snapshot(
        cls,
        snapshot: GameStateSnapshot,
        sequence: int,
        *,
        command_id: str | None = None,
    ) -> GameEvent:
        return cls(
            kind=EventKind.STATE_SNAPSHOT,
            sequence=sequence,
            command_id=command_id,
            payload={"snapshot": snapshot.to_dict()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_type": "event",
            "version": self.version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "command_id": self.command_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameEvent:
        data = _require_object(data, "event")
        _require_exact_keys(
            data,
            {
                "message_type",
                "version",
                "event_id",
                "sequence",
                "command_id",
                "kind",
                "payload",
            },
            "event",
        )
        if data["message_type"] != "event":
            raise ProtocolValidationError("message_type must be 'event'.")
        return cls(
            kind=data["kind"],
            sequence=data["sequence"],
            payload=data["payload"],
            command_id=data["command_id"],
            event_id=data["event_id"],
            version=data["version"],
        )

    @classmethod
    def from_json(cls, raw: str) -> GameEvent:
        return cls.from_dict(_decode_json_object(raw))


def decode_wire_message(raw: str) -> GameCommand | GameEvent | GameStateSnapshot:
    data = _decode_json_object(raw)
    message_type = data.get("message_type")
    if message_type == "command":
        return GameCommand.from_dict(data)
    if message_type == "event":
        return GameEvent.from_dict(data)
    if message_type == "game_state_snapshot":
        from multiplayer.snapshot import GameStateSnapshot

        return GameStateSnapshot.from_dict(data)
    raise ProtocolValidationError(f"Unsupported message_type: {message_type!r}.")
