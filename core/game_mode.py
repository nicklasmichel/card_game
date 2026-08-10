from __future__ import annotations

import core.config as config


GAME_MODE_NORMAL = "deck"
GAME_MODE_BUILDER = "builder"
GAME_MODE_NORMAL_ALIASES = {"deck", "normal"}


def get_game_mode() -> str:
    mode = getattr(config, "GAME_MODE", GAME_MODE_NORMAL)
    return GAME_MODE_NORMAL if mode in GAME_MODE_NORMAL_ALIASES else mode


def is_builder_mode() -> bool:
    return get_game_mode() == GAME_MODE_BUILDER
