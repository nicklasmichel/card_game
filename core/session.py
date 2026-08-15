from __future__ import annotations

from collections import OrderedDict
from typing import Protocol, runtime_checkable

from core.command_dispatch import apply_game_command
from core.game_logic import GameEngine
from core.models import MatchMode
from multiplayer.protocol import GameCommand, GameEvent


MAX_REMEMBERED_COMMANDS = 4096
MAX_PENDING_EVENTS = 256


@runtime_checkable
class GameSession(Protocol):
    """Boundary between a game frontend and the authority running the match."""

    @property
    def state(self) -> GameEngine:
        """Return the latest state exposed to the frontend."""
        ...

    @property
    def match_mode(self) -> MatchMode:
        ...

    @property
    def local_player_id(self) -> int:
        ...

    @property
    def should_exit(self) -> bool:
        ...

    def start_new_game(self, starting_player_id: int | None = None) -> GameEvent:
        ...

    def submit_command(self, command: GameCommand) -> GameEvent:
        ...

    def submit_action(self, action: str) -> GameEvent:
        ...

    def submit_click(self, area: str, item_id: int) -> GameEvent:
        ...

    def submit_hand_card_play(self, card_id: int) -> GameEvent:
        ...

    def drain_events(self) -> list[GameEvent]:
        ...

    def update(
        self,
        *,
        allow_ai: bool = True,
        allow_automatic_rules: bool = True,
        allow_commands: bool = True,
    ) -> None:
        ...

    def close(self) -> None:
        ...


class LocalPveSession:
    """Runs a PvE match in-process while presenting the shared session API."""

    def __init__(
        self,
        engine: GameEngine | None = None,
        *,
        auto_start: bool = False,
        local_player_id: int = 0,
    ) -> None:
        self._state = engine or GameEngine(auto_start=auto_start, match_mode=MatchMode.PVE)
        if self._state.match_mode is not MatchMode.PVE:
            raise ValueError("LocalPveSession requires a PvE GameEngine.")
        if local_player_id not in {player.player_id for player in self._state.players}:
            raise ValueError(f"Unknown local_player_id: {local_player_id}")
        local_player = next(player for player in self._state.players if player.player_id == local_player_id)
        if not local_player.is_locally_controlled:
            raise ValueError(f"Player {local_player_id} is not locally controlled.")
        self._local_player_id = local_player_id
        self._closed = False
        self._event_sequence = 0
        self._pending_events: list[GameEvent] = []
        self._processed_commands: OrderedDict[str, tuple[GameCommand, GameEvent]] = OrderedDict()

    @property
    def state(self) -> GameEngine:
        return self._state

    @property
    def match_mode(self) -> MatchMode:
        return self._state.match_mode

    @property
    def local_player_id(self) -> int:
        return self._local_player_id

    @property
    def should_exit(self) -> bool:
        return self._state.exit_requested

    def start_new_game(self, starting_player_id: int | None = None) -> GameEvent:
        return self.submit_command(
            GameCommand.start_game(self.local_player_id, starting_player_id)
        )

    def submit_action(self, action: str) -> GameEvent:
        return self.submit_command(GameCommand.action(self.local_player_id, action))

    def submit_click(self, area: str, item_id: int) -> GameEvent:
        return self.submit_command(GameCommand.click(self.local_player_id, area, item_id))

    def submit_hand_card_play(self, card_id: int) -> GameEvent:
        return self.submit_command(GameCommand.play_hand_card(self.local_player_id, card_id))

    def submit_command(self, command: GameCommand) -> GameEvent:
        self._ensure_open()
        previous = self._processed_commands.get(command.command_id)
        if previous is not None:
            previous_command, previous_event = previous
            if previous_command == command:
                return previous_event
            return self._record_event(
                GameEvent.command_rejected(
                    command,
                    self._next_event_sequence(),
                    code="command_id_conflict",
                    message="The command_id was already used for different command data.",
                )
            )
        if command.player_id != self.local_player_id:
            event = self._record_event(
                GameEvent.command_rejected(
                    command,
                    self._next_event_sequence(),
                    code="unauthorized_player",
                    message=f"Player {command.player_id} is not controlled by this session.",
                )
            )
            self._remember_command(command, event)
            return event

        apply_game_command(self._state, command)
        event = self._record_event(
            GameEvent.command_applied(command, self._next_event_sequence())
        )
        self._remember_command(command, event)
        return event

    def drain_events(self) -> list[GameEvent]:
        events = self._pending_events[:]
        self._pending_events.clear()
        return events

    def update(
        self,
        *,
        allow_ai: bool = True,
        allow_automatic_rules: bool = True,
        allow_commands: bool = True,
    ) -> None:
        self._ensure_open()
        if allow_ai:
            self._state.poll_ai_thinking()
            if not self._state.has_pending_ai_action():
                self._state.start_ai_thinking()
        if allow_automatic_rules:
            self._state.auto_resolve_human_no_blockers_if_needed()
            self._state.resolve_stalled_dice_battle_if_needed()
        self._state.flush_log_file_writes(max_lines=24)

    def close(self) -> None:
        if self._closed:
            return
        self._state.cancel_ai_thinking()
        self._state.flush_log_file_writes()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Game session is already closed.")

    def _next_event_sequence(self) -> int:
        self._event_sequence += 1
        return self._event_sequence

    def _record_event(self, event: GameEvent) -> GameEvent:
        self._pending_events.append(event)
        if len(self._pending_events) > MAX_PENDING_EVENTS:
            del self._pending_events[: len(self._pending_events) - MAX_PENDING_EVENTS]
        return event

    def _remember_command(self, command: GameCommand, event: GameEvent) -> None:
        self._processed_commands[command.command_id] = (command, event)
        self._processed_commands.move_to_end(command.command_id)
        while len(self._processed_commands) > MAX_REMEMBERED_COMMANDS:
            self._processed_commands.popitem(last=False)
