from __future__ import annotations

from core.models import MatchMode


PVE_PLAYER_LABELS = {
    0: "Human",
    1: "AI",
}


def get_ui_match_mode(view) -> MatchMode | None:
    session = getattr(view, "session", None)
    value = getattr(session, "match_mode", None)
    if value is None:
        value = getattr(getattr(view, "engine", None), "match_mode", None)
    try:
        return MatchMode(value) if value is not None else None
    except ValueError:
        return None


def get_player_display_name(view, player) -> str:
    if get_ui_match_mode(view) is MatchMode.PVE:
        label = PVE_PLAYER_LABELS.get(getattr(player, "player_id", None))
        if label is not None:
            return label
    return player.name


def format_player_names_for_ui(view, text: str) -> str:
    if get_ui_match_mode(view) is not MatchMode.PVE:
        return text
    return (
        text.replace("Player 2 (AI)", "AI")
        .replace("Player 1", "Human")
        .replace("Player 2", "AI")
    )
