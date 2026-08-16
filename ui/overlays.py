from __future__ import annotations

import pygame

from ui.player_labels import format_player_names_for_ui
from ui.style import CARD_BORDER, HIGHLIGHT, MUTED_TEXT, OVERLAY_COLOR, PANEL_COLOR, TEXT_COLOR


def _draw_combat_sum(self, card_rect: pygame.Rect, total: int, *, winner: bool) -> None:
    padding = self.scale_ui(16)
    badge_size = min(
        card_rect.width - padding,
        card_rect.height - padding,
        self.scale_ui(92),
    )
    badge_size = max(self.scale_ui(40), badge_size)
    badge = pygame.Surface((badge_size, badge_size), pygame.SRCALPHA)
    badge_rect = badge.get_rect()
    radius = badge_size // 2
    pygame.draw.circle(badge, (18, 20, 24, 210), badge_rect.center, radius)
    border_color = HIGHLIGHT if winner else CARD_BORDER
    pygame.draw.circle(
        badge,
        border_color,
        badge_rect.center,
        max(1, radius - self.scale_ui(1)),
        max(1, self.scale_ui(2)),
    )

    font_size = max(self.scale_ui(28), round(badge_size * 0.68))
    font_cache = getattr(self, "_combat_sum_fonts", {})
    sum_font = font_cache.get(font_size)
    if sum_font is None:
        sum_font = pygame.font.SysFont("arial", font_size, bold=True)
        font_cache[font_size] = sum_font
        self._combat_sum_fonts = font_cache

    value_surface = sum_font.render(str(total), True, TEXT_COLOR)
    value_rect = value_surface.get_rect(center=badge_rect.center)
    badge.blit(value_surface, value_rect)
    self.screen.blit(badge, badge.get_rect(center=card_rect.center))


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
        _draw_combat_sum(self, attacker_rect, battle.attack_sum, winner=battle.winner == "attacker")
        _draw_combat_sum(self, blocker_rect, battle.defense_sum, winner=battle.winner == "blocker")
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
    self.blit_centered_text(self.title_font, "Game Over", TEXT_COLOR, pygame.Rect(panel.x, panel.y + s(20), panel.width, s(30)))
    self.blit_centered_text(
        self.font,
        format_player_names_for_ui(self, self.engine.game_over_text),
        TEXT_COLOR,
        pygame.Rect(panel.x + s(20), panel.y + s(60), panel.width - s(40), s(30)),
    )
    y = panel.y + s(104)
    for line in self.engine.game_over_summary_lines[:8]:
        self.blit_text(self.font, format_player_names_for_ui(self, line), MUTED_TEXT, panel.x + s(36), y)
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


