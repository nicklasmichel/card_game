from __future__ import annotations

from collections import OrderedDict

from core.command_dispatch import apply_game_command
from core.game_logic import GameEngine
from core.models import (
    ControllerKind,
    MatchMode,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
)
from multiplayer.protocol import CommandKind, GameCommand, GameEvent
from multiplayer.snapshot import GameStateSnapshot, authoritative_state_hash


MAX_REMEMBERED_HOST_COMMANDS = 4096
MAX_PENDING_PLAYER_EVENTS = 256


class AuthoritativeHostSession:
    """Owns the canonical PvP engine and mediates commands from both players."""

    def __init__(
        self,
        engine: GameEngine | None = None,
        *,
        auto_start: bool = False,
        local_player_id: int = 0,
    ) -> None:
        self._state = engine or GameEngine(auto_start=auto_start, match_mode=MatchMode.PVP)
        if self._state.match_mode is not MatchMode.PVP:
            raise ValueError("AuthoritativeHostSession requires a PvP GameEngine.")
        self._players = {player.player_id: player for player in self._state.players}
        if local_player_id not in self._players:
            raise ValueError(f"Unknown local_player_id: {local_player_id}")
        if self._players[local_player_id].controller_kind is not ControllerKind.LOCAL_HUMAN:
            raise ValueError(f"Player {local_player_id} is not the local host player.")
        self._local_player_id = local_player_id
        self._closed = False
        self._revision = 0
        self._unassigned_event_sequence = 0
        self._event_sequences = {player_id: 0 for player_id in self._players}
        self._pending_events = {player_id: [] for player_id in self._players}
        self._processed_commands: OrderedDict[
            str,
            tuple[int, GameCommand, GameEvent],
        ] = OrderedDict()

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
    def revision(self) -> int:
        return self._revision

    @property
    def should_exit(self) -> bool:
        return self._state.exit_requested

    @property
    def remote_player_ids(self) -> tuple[int, ...]:
        return tuple(
            player_id
            for player_id, player in self._players.items()
            if player.controller_kind is ControllerKind.REMOTE_HUMAN
        )

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
        return self.receive_command(command, authenticated_player_id=self.local_player_id)

    def receive_command(
        self,
        command: GameCommand,
        *,
        authenticated_player_id: int,
    ) -> GameEvent:
        self._ensure_open()
        previous = self._processed_commands.get(command.command_id)
        if previous is not None:
            previous_player_id, previous_command, previous_event = previous
            if previous_player_id == authenticated_player_id and previous_command == command:
                return previous_event
            return self._reject(
                command,
                authenticated_player_id,
                code="command_id_conflict",
                message="The command_id was already used for different command data.",
                remember=False,
            )

        authorization_error = self._authorization_error(command, authenticated_player_id)
        if authorization_error is not None:
            code, message = authorization_error
            return self._reject(
                command,
                authenticated_player_id,
                code=code,
                message=message,
                remember=code != "unknown_player",
            )

        before_hash = authoritative_state_hash(self._state)
        apply_game_command(
            self._state,
            command,
            acting_player_id=authenticated_player_id,
        )
        after_hash = authoritative_state_hash(self._state)
        if before_hash == after_hash:
            return self._reject(
                command,
                authenticated_player_id,
                code="command_not_applied",
                message="The command is not legal in the current game state.",
                remember=True,
            )

        self._revision += 1
        event = GameEvent.command_applied(
            command,
            self._next_event_sequence(authenticated_player_id),
        )
        self._record_player_event(authenticated_player_id, event)
        self._remember_command(authenticated_player_id, command, event)
        self._broadcast_snapshots(command_id=command.command_id)
        return event

    def snapshot_for_player(self, player_id: int) -> GameStateSnapshot:
        self._require_known_player(player_id)
        return GameStateSnapshot.from_engine(self._state, player_id, self._revision)

    def queue_snapshot(self, player_id: int) -> GameEvent:
        self._ensure_open()
        self._require_known_player(player_id)
        event = GameEvent.state_snapshot(
            self.snapshot_for_player(player_id),
            self._next_event_sequence(player_id),
        )
        self._record_player_event(player_id, event)
        return event

    def drain_events(self) -> list[GameEvent]:
        return self.drain_player_events(self.local_player_id)

    def drain_player_events(self, player_id: int) -> list[GameEvent]:
        self._require_known_player(player_id)
        events = self._pending_events[player_id][:]
        self._pending_events[player_id].clear()
        return events

    def update(
        self,
        *,
        allow_ai: bool = True,
        allow_automatic_rules: bool = True,
    ) -> None:
        self._ensure_open()
        can_advance_automatically = (
            allow_automatic_rules
            and self._state.phase in {PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE}
        )
        before_hash = authoritative_state_hash(self._state) if can_advance_automatically else None
        if can_advance_automatically:
            self._state.auto_resolve_human_no_blockers_if_needed()
            self._state.resolve_stalled_dice_battle_if_needed()
        after_hash = authoritative_state_hash(self._state) if can_advance_automatically else None
        if before_hash is not None and before_hash != after_hash:
            self._revision += 1
            self._broadcast_snapshots(command_id=None)
        self._state.flush_log_file_writes(max_lines=24)

    def close(self) -> None:
        if self._closed:
            return
        self._state.cancel_ai_thinking()
        self._state.flush_log_file_writes()
        self._closed = True

    def _authorization_error(
        self,
        command: GameCommand,
        authenticated_player_id: int,
    ) -> tuple[str, str] | None:
        if authenticated_player_id not in self._players:
            return "unknown_player", f"Unknown authenticated player: {authenticated_player_id}."
        if command.player_id != authenticated_player_id:
            return "player_identity_mismatch", "Command player_id does not match the authenticated player."
        if not self._players[authenticated_player_id].is_human:
            return "unauthorized_player", "AI-controlled players cannot submit network commands."
        if command.kind is CommandKind.START_GAME:
            if authenticated_player_id != self.local_player_id:
                return "host_only", "Only the host may start a game."
            return None
        if command.kind is CommandKind.ACTION and command.payload["action"] in {
            "exit_game",
            "new_game",
        }:
            if authenticated_player_id != self.local_player_id:
                return "host_only", "Only the host may control the match lifecycle."
            return None
        if self._state.phase == PHASE_GAME_OVER:
            return "game_over", "No gameplay commands are accepted after game over."
        if self._state.phase == PHASE_DECLARE_BLOCKERS:
            if command.kind is CommandKind.CLICK:
                allowed_players = {
                    self._state.active_player.player_id,
                    self._state.defending_player.player_id,
                }
                if authenticated_player_id in allowed_players:
                    return None
            elif authenticated_player_id == self._state.defending_player.player_id:
                return None
            return "not_your_decision", "The defending player controls block confirmation."
        if authenticated_player_id != self._state.active_player.player_id:
            return "not_your_turn", "The authenticated player is not the active player."
        return None

    def _reject(
        self,
        command: GameCommand,
        player_id: int,
        *,
        code: str,
        message: str,
        remember: bool,
    ) -> GameEvent:
        if player_id in self._players:
            sequence = self._next_event_sequence(player_id)
        else:
            self._unassigned_event_sequence += 1
            sequence = self._unassigned_event_sequence
        event = GameEvent.command_rejected(
            command,
            sequence,
            code=code,
            message=message,
        )
        if player_id in self._players:
            self._record_player_event(player_id, event)
        if remember:
            self._remember_command(player_id, command, event)
        return event

    def _broadcast_snapshots(self, *, command_id: str | None) -> None:
        for player_id in self._players:
            event = GameEvent.state_snapshot(
                self.snapshot_for_player(player_id),
                self._next_event_sequence(player_id),
                command_id=command_id,
            )
            self._record_player_event(player_id, event)

    def _next_event_sequence(self, player_id: int) -> int:
        self._event_sequences[player_id] += 1
        return self._event_sequences[player_id]

    def _record_player_event(self, player_id: int, event: GameEvent) -> None:
        events = self._pending_events[player_id]
        events.append(event)
        if len(events) > MAX_PENDING_PLAYER_EVENTS:
            del events[: len(events) - MAX_PENDING_PLAYER_EVENTS]

    def _remember_command(
        self,
        authenticated_player_id: int,
        command: GameCommand,
        event: GameEvent,
    ) -> None:
        self._processed_commands[command.command_id] = (
            authenticated_player_id,
            command,
            event,
        )
        self._processed_commands.move_to_end(command.command_id)
        while len(self._processed_commands) > MAX_REMEMBERED_HOST_COMMANDS:
            self._processed_commands.popitem(last=False)

    def _require_known_player(self, player_id: int) -> None:
        if player_id not in self._players:
            raise ValueError(f"Unknown player_id: {player_id}")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Host session is already closed.")
