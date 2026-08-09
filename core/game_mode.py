from __future__ import annotations

import core.config as config


GAME_MODE_NORMAL = "normal"
GAME_MODE_BUILDER = "builder"


def get_game_mode() -> str:
    return getattr(config, "GAME_MODE", GAME_MODE_NORMAL)


def is_builder_mode() -> bool:
    return get_game_mode() == GAME_MODE_BUILDER

