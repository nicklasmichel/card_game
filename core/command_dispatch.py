from __future__ import annotations

from core.game_logic import GameEngine
from multiplayer.protocol import CommandKind, GameCommand


def apply_game_command(
    engine: GameEngine,
    command: GameCommand,
    *,
    acting_player_id: int | None = None,
) -> None:
    """Apply an already authenticated and validated command to an engine."""
    if command.kind is CommandKind.START_GAME:
        engine.start_new_game(starting_player_id=command.payload["starting_player_id"])
        return
    if command.kind is CommandKind.ACTION:
        engine.handle_action(command.payload["action"])
        return
    if command.kind is CommandKind.CLICK:
        if acting_player_id is None:
            engine.handle_click(command.payload["area"], command.payload["item_id"])
        else:
            engine.handle_click(
                command.payload["area"],
                command.payload["item_id"],
                acting_player_id=acting_player_id,
            )
        return
    if command.kind is CommandKind.PLAY_HAND_CARD:
        engine.play_hand_card_in_summoning_zone(command.payload["card_id"])
        return
    raise ValueError(f"Unsupported command kind: {command.kind!r}")
