from __future__ import annotations

import pygame

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
    pygame.draw.rect(self.screen, (248, 248, 244), rect, border_radius=self.scale_ui(5))
    pygame.draw.rect(self.screen, (24, 24, 26), rect, self.scale_ui(2), border_radius=self.scale_ui(5))
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
        max(self.scale_ui(24), (card_rect.width - self.scale_ui(24)) // max(1, widest_row)),
        max(self.scale_ui(24), (card_rect.height - self.scale_ui(24)) // max(1, len(rows))),
        self.scale_ui(34),
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
        inset = self.scale_ui(4)
        inner_rect = pygame.Rect(card_rect.x + inset, card_rect.y + inset, card_rect.width - inset * 2, card_rect.height - inset * 2)
        pygame.draw.rect(self.screen, HIGHLIGHT, inner_rect, self.scale_ui(2), border_radius=self.scale_ui(8))


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
        pygame.draw.rect(self.screen, HIGHLIGHT if battle.winner == "attacker" else CARD_BORDER, attacker_rect, self.scale_ui(3), border_radius=self.scale_ui(8))
        pygame.draw.rect(self.screen, HIGHLIGHT if battle.winner == "blocker" else CARD_BORDER, blocker_rect, self.scale_ui(3), border_radius=self.scale_ui(8))
        _draw_dice_row(self, attacker_rect, battle.attacker_rolls, winner=battle.winner == "attacker")
        _draw_dice_row(self, blocker_rect, battle.blocker_rolls, winner=battle.winner == "blocker")
        if battle.reroll_count > 0:
            reroll_rect = pygame.Rect(
                min(attacker_rect.centerx, blocker_rect.centerx) - self.scale_ui(46),
                min(attacker_rect.top, blocker_rect.top) - self.scale_ui(26),
                self.scale_ui(92),
                self.scale_ui(22),
            )
            pygame.draw.rect(self.screen, (36, 40, 48), reroll_rect, border_radius=self.scale_ui(6))
            pygame.draw.rect(self.screen, CARD_BORDER, reroll_rect, self.scale_ui(1), border_radius=self.scale_ui(6))
            self.blit_centered_text(self.small_font, f"Reroll {battle.reroll_count}", MUTED_TEXT, reroll_rect)


def draw_game_over_overlay(self) -> None:
    s = self.scale_ui
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 150))
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect((self.window_width - s(780)) // 2, (self.window_height - s(360)) // 2, s(780), s(360))
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=s(8))
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, s(2), border_radius=s(8))
    self.blit_centered_text(self.title_font, "Spielende", TEXT_COLOR, pygame.Rect(panel.x, panel.y + s(20), panel.width, s(30)))
    self.blit_centered_text(self.font, self.engine.game_over_text, TEXT_COLOR, pygame.Rect(panel.x + s(20), panel.y + s(60), panel.width - s(40), s(30)))
    y = panel.y + s(104)
    for line in self.engine.game_over_summary_lines[:8]:
        self.blit_text(self.font, line, MUTED_TEXT, panel.x + s(36), y)
        y += s(28)


def draw_pause_overlay(self) -> None:
    if not self.paused:
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    s = self.scale_ui
    panel = pygame.Rect((self.window_width - s(420)) // 2, (self.window_height - s(140)) // 2, s(420), s(140))
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=s(8))
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, s(2), border_radius=s(8))
    self.blit_centered_text(self.title_font, "Pausiert", TEXT_COLOR, pygame.Rect(panel.x, panel.y + s(22), panel.width, s(30)))
    self.blit_centered_text(self.font, "Enter setzt das Spiel fort.", MUTED_TEXT, pygame.Rect(panel.x + s(20), panel.y + s(68), panel.width - s(40), s(24)))


