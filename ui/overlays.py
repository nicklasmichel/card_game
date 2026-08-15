from __future__ import annotations

import pygame

from core.branding import APP_NAME, APP_TAGLINE

from ui.style import CARD_BORDER, HIGHLIGHT, MUTED_TEXT, OVERLAY_COLOR, PANEL_COLOR, TEXT_COLOR


def _die_pip_offsets(value: int) -> list[tuple[float, float]]:
    positions = {
        1: [(0.5, 0.5)],
        2: [(0.28, 0.28), (0.72, 0.72)],
        3: [(0.28, 0.28), (0.5, 0.5), (0.72, 0.72)],
        4: [(0.28, 0.28), (0.72, 0.28), (0.28, 0.72), (0.72, 0.72)],
        5: [(0.28, 0.28), (0.72, 0.28), (0.5, 0.5), (0.28, 0.72), (0.72, 0.72)],
        6: [(0.28, 0.26), (0.72, 0.26), (0.28, 0.5), (0.72, 0.5), (0.28, 0.74), (0.72, 0.74)],
    }
    return positions.get(value, positions[1])


def _draw_rendered_die(self, rect: pygame.Rect, value: int) -> None:
    pygame.draw.rect(self.screen, (248, 248, 244), rect, border_radius=5)
    pygame.draw.rect(self.screen, (24, 24, 26), rect, 2, border_radius=5)
    pip_radius = max(2, rect.width // 10)
    for rel_x, rel_y in _die_pip_offsets(max(1, min(6, value))):
        center = (rect.x + int(rect.width * rel_x), rect.y + int(rect.height * rel_y))
        pygame.draw.circle(self.screen, (24, 24, 26), center, pip_radius)


def _draw_dice_row(self, card_rect: pygame.Rect, rolls: list[int], *, winner: bool) -> None:
    if not rolls:
        return
    rows = [rolls[index:index + 3] for index in range(0, len(rolls), 3)]
    widest_row = max((len(row) for row in rows), default=1)
    die_size = min(
        max(24, (card_rect.width - 24) // max(1, widest_row)),
        max(24, (card_rect.height - 24) // max(1, len(rows))),
        34,
    )
    gap = max(3, die_size // 6)
    total_height = len(rows) * die_size + max(0, len(rows) - 1) * gap
    start_y = card_rect.y + (card_rect.height - total_height) // 2
    for row_index, row in enumerate(rows):
        row_width = len(row) * die_size + max(0, len(row) - 1) * gap
        start_x = card_rect.x + (card_rect.width - row_width) // 2
        for die_index, roll in enumerate(row):
            die_rect = pygame.Rect(
                start_x + die_index * (die_size + gap),
                start_y + row_index * (die_size + gap),
                die_size,
                die_size,
            )
            _draw_rendered_die(self, die_rect, roll)
    if winner:
        inner_rect = pygame.Rect(card_rect.x + 4, card_rect.y + 4, card_rect.width - 8, card_rect.height - 8)
        pygame.draw.rect(self.screen, HIGHLIGHT, inner_rect, 2, border_radius=8)


def draw_dice_battle_overlay(self) -> None:
    battles = list(
        getattr(self.engine, "pending_dice_battles", [])
        or ([] if self.engine.pending_dice_battle is None else [self.engine.pending_dice_battle])
    )
    if not battles:
        return
    for battle in battles:
        attacker_rect = self.creature_rects.get(battle.attacker_id)
        blocker_rect = self.creature_rects.get(battle.blocker_id)
        if attacker_rect is None or blocker_rect is None:
            continue
        self.combat_overlay_card_rects["attacker"] = attacker_rect
        self.combat_overlay_card_rects["blocker"] = blocker_rect
        pygame.draw.rect(self.screen, HIGHLIGHT if battle.winner == "attacker" else CARD_BORDER, attacker_rect, 3, border_radius=8)
        pygame.draw.rect(self.screen, HIGHLIGHT if battle.winner == "blocker" else CARD_BORDER, blocker_rect, 3, border_radius=8)
        _draw_dice_row(self, attacker_rect, battle.attacker_rolls, winner=battle.winner == "attacker")
        _draw_dice_row(self, blocker_rect, battle.blocker_rolls, winner=battle.winner == "blocker")
        if battle.reroll_count > 0:
            reroll_rect = pygame.Rect(
                min(attacker_rect.centerx, blocker_rect.centerx) - 46,
                min(attacker_rect.top, blocker_rect.top) - 26,
                92,
                22,
            )
            pygame.draw.rect(self.screen, (36, 40, 48), reroll_rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, reroll_rect, 1, border_radius=6)
            self.blit_centered_text(self.small_font, f"Reroll {battle.reroll_count}", MUTED_TEXT, reroll_rect)


def draw_game_over_overlay(self) -> None:
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 150))
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(max(40, (self.window_width - 780) // 2), max(40, (self.window_height - 360) // 2), 780, 360)
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    self.blit_centered_text(self.title_font, "Spielende", TEXT_COLOR, pygame.Rect(panel.x, panel.y + 20, panel.width, 30))
    self.blit_centered_text(self.font, self.engine.game_over_text, TEXT_COLOR, pygame.Rect(panel.x + 20, panel.y + 60, panel.width - 40, 30))
    y = panel.y + 104
    for line in self.engine.game_over_summary_lines[:8]:
        self.blit_text(self.font, line, MUTED_TEXT, panel.x + 36, y)
        y += 28


def draw_pause_overlay(self) -> None:
    if not self.paused:
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(max(40, (self.window_width - 420) // 2), max(40, (self.window_height - 140) // 2), 420, 140)
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    self.blit_centered_text(self.title_font, "Pausiert", TEXT_COLOR, pygame.Rect(panel.x, panel.y + 22, panel.width, 30))
    self.blit_centered_text(self.font, "Enter setzt das Spiel fort.", MUTED_TEXT, pygame.Rect(panel.x + 20, panel.y + 68, panel.width - 40, 24))


def draw_start_player_overlay(self) -> None:
    if not getattr(self, "start_player_selection_open", False):
        return
    title_font = pygame.font.SysFont("arial", 38, bold=True)
    button_font = pygame.font.SysFont("arial", 34, bold=True)
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    panel_width = min(920, self.window_width - 80)
    panel_height = 360
    panel = pygame.Rect(
        max(40, (self.window_width - panel_width) // 2),
        max(40, (self.window_height - panel_height) // 2),
        panel_width,
        panel_height,
    )
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    self.blit_centered_text(title_font, APP_NAME, TEXT_COLOR, pygame.Rect(panel.x, panel.y + 16, panel.width, 44))
    self.blit_centered_text(self.font, APP_TAGLINE, MUTED_TEXT, pygame.Rect(panel.x, panel.y + 62, panel.width, 28))
    self.blit_centered_text(self.font, "Who starts?", TEXT_COLOR, pygame.Rect(panel.x, panel.y + 96, panel.width, 28))

    choices = [
        ("Player 1", "player_1"),
        ("Player 2", "player_2"),
        ("Random", "random"),
    ]
    gap = 24
    button_width = (panel.width - 48 - gap * 2) // 3
    button_height = 150
    button_y = panel.y + 142
    start_x = panel.x + 24
    self.start_player_option_rects = []
    for index, (label, selection) in enumerate(choices):
        button_rect = pygame.Rect(
            start_x + index * (button_width + gap),
            button_y,
            button_width,
            button_height,
        )
        pygame.draw.rect(self.screen, PANEL_COLOR, button_rect, border_radius=8)
        pygame.draw.rect(self.screen, HIGHLIGHT, button_rect, 2, border_radius=8)
        self.blit_centered_text(button_font, label, TEXT_COLOR, button_rect)
        self.start_player_option_rects.append((button_rect, selection))
