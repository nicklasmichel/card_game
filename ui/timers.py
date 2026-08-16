from __future__ import annotations

import pygame

from core.models import PHASE_GAME_OVER


def format_elapsed_ms(elapsed_ms: int) -> str:
    total_seconds = max(0, int(elapsed_ms)) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def update_gameplay_timers(self, *, now_ms: int | None = None) -> None:
    now = pygame.time.get_ticks() if now_ms is None else now_ms
    engine = self.engine
    if engine.turn_number <= 0:
        self.timer_game_id = None
        self.timer_phase_marker = None
        self.game_elapsed_ms = 0
        self.phase_elapsed_ms = 0
        self.timer_last_update_ms = now
        return

    phase_marker = (
        engine.game_id,
        engine.turn_number,
        engine.active_player.player_id,
        engine.phase,
    )
    if getattr(self, "timer_game_id", None) != engine.game_id:
        self.timer_game_id = engine.game_id
        self.timer_phase_marker = phase_marker
        self.game_elapsed_ms = 0
        self.phase_elapsed_ms = 0
        self.timer_last_update_ms = now
        return

    last_update = getattr(self, "timer_last_update_ms", now)
    elapsed_since_update = max(0, now - last_update)
    phase_elapsed_since_update = elapsed_since_update
    self.timer_last_update_ms = now
    if getattr(self, "timer_phase_marker", None) != phase_marker:
        self.timer_phase_marker = phase_marker
        self.phase_elapsed_ms = 0
        phase_elapsed_since_update = 0

    network_blocked = False
    network_check = getattr(self, "network_blocks_gameplay", None)
    if callable(network_check):
        network_blocked = network_check()
    timer_paused = (
        getattr(self, "paused", False)
        or getattr(self, "match_mode_selection_open", False)
        or network_blocked
        or engine.phase == PHASE_GAME_OVER
    )
    if timer_paused:
        return

    self.game_elapsed_ms += elapsed_since_update
    self.phase_elapsed_ms += phase_elapsed_since_update
