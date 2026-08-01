from __future__ import annotations

import pygame

from ui.style import BUTTON_COLOR, CARD_BORDER, ENEMY_CARD_COLOR, HIGHLIGHT, MUTED_TEXT, OVERLAY_COLOR, PANEL_COLOR, TEXT_COLOR


def draw_mulligan_overlay(self) -> None:
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    _, _, _, action_rect, _ = self.get_side_panel_layout()
    pygame.draw.rect(overlay, (0, 0, 0, 0), action_rect)
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(max(40, (self.window_width - 1240) // 2), max(40, (self.window_height - 520) // 2), 1240, 520)
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    self.blit_text(self.title_font, "Starthand und Mulligan", TEXT_COLOR, panel.x + 30, panel.y + 26)
    self.blit_text(self.font, "Klicke beliebige Karten an, um sie einmalig ins Deck zurückzumischen und neu zu ziehen.", MUTED_TEXT, panel.x + 30, panel.y + 58)
    for index, card in enumerate(self.engine.human_player.hand):
        mulligan_step = self.card_width + 32
        rect = self.draw_hand_card(card, panel.x + 30 + index * mulligan_step, panel.y + 140, card.instance_id in self.engine.selected_hand_ids)
        self.click_targets["mulligan_hand"].append((rect, card.instance_id))


def draw_block_order_overlay(self) -> None:
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(max(40, (self.window_width - 780) // 2), max(40, (self.window_height - 420) // 2), 780, 420)
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    attacker = self.engine.get_unit_by_id(self.engine.pending_order.attacker_id)
    name = attacker.name if attacker is not None else "Angreifer"
    self.blit_text(self.title_font, f"Blockreihenfolge für {name}", TEXT_COLOR, panel.x + 26, panel.y + 28)
    self.blit_text(self.font, "Klicke die Blocker in der gewünschten Reihenfolge an.", MUTED_TEXT, panel.x + 26, panel.y + 62)
    for index, blocker_id in enumerate(self.engine.pending_order.blocker_ids):
        blocker = self.engine.get_unit_by_id(blocker_id)
        if blocker is None:
            continue
        rect = pygame.Rect(panel.x + 30, panel.y + 100 + index * 62, 720, 48)
        pygame.draw.rect(self.screen, ENEMY_CARD_COLOR, rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=6)
        if blocker_id in self.engine.pending_order.chosen_order:
            pygame.draw.rect(self.screen, HIGHLIGHT, rect, 3, border_radius=6)
            prefix = f"{self.engine.pending_order.chosen_order.index(blocker_id) + 1}."
        else:
            prefix = f"{index + 1}."
        self.blit_text(self.font, prefix, TEXT_COLOR, rect.x + 10, rect.y + 14)
        self.blit_text(self.font, f"{blocker.name} - {blocker.aw_vw} - noch {blocker.current_hp} LP", TEXT_COLOR, rect.x + 56, rect.y + 14)
        self.click_targets["order_blockers"].append((rect, blocker_id))


def draw_dice_battle_overlay(self) -> None:
    battle = self.engine.pending_dice_battle
    if battle is None:
        return

    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    _, _, log_rect, action_rect, _ = self.get_side_panel_layout()
    pygame.draw.rect(overlay, (0, 0, 0, 0), log_rect)
    pygame.draw.rect(overlay, (0, 0, 0, 0), action_rect)
    self.screen.blit(overlay, (0, 0))

    panel_width = min(self.window_width - 100, 1560)
    panel_height = min(self.window_height - 100, 920)
    panel = pygame.Rect(
        max(40, (self.window_width - panel_width) // 2),
        max(40, (self.window_height - panel_height) // 2),
        panel_width,
        panel_height,
    )
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)

    attacker = self.engine.get_unit_by_id(battle.attacker_id) or battle.attacker_snapshot
    blocker = self.engine.get_unit_by_id(battle.blocker_id) or battle.blocker_snapshot
    human_is_attacker = battle.attacker_owner == self.engine.human_player.player_id
    human_dice = battle.attacker_dice if human_is_attacker else battle.blocker_dice
    enemy_dice = battle.blocker_dice if human_is_attacker else battle.attacker_dice

    attacker_surface = self.build_preview_creature_surface(attacker, battle.attacker_owner == self.engine.human_player.player_id, attacking=True)
    blocker_surface = self.build_preview_creature_surface(blocker, battle.blocker_owner == self.engine.human_player.player_id)
    card_y = panel.y + 84
    attacker_rect = attacker_surface.get_rect(topleft=(panel.x + 56, card_y))
    blocker_rect = blocker_surface.get_rect(topright=(panel.right - 56, card_y))
    self.combat_overlay_card_rects["attacker"] = attacker_rect
    self.combat_overlay_card_rects["blocker"] = blocker_rect

    self.screen.blit(attacker_surface, attacker_rect.topleft)
    self.screen.blit(blocker_surface, blocker_rect.topleft)
    pygame.draw.rect(self.screen, CARD_BORDER, attacker_rect, 3, border_radius=10)
    pygame.draw.rect(self.screen, CARD_BORDER, blocker_rect, 3, border_radius=10)
    self.draw_combat_damage_popups()

    middle_x = attacker_rect.right + 48
    middle_width = blocker_rect.left - middle_x - 48
    column_gap = 18
    column_width = (middle_width - column_gap) // 2
    left_column_x = middle_x
    right_column_x = middle_x + column_width + column_gap
    human_column_x = left_column_x if human_is_attacker else right_column_x
    enemy_column_x = right_column_x if human_is_attacker else left_column_x
    dice_title_y = panel.y + 84

    def row_text_for_human(die, round_number: int) -> str:
        if die.comparison_label:
            return die.comparison_label
        if battle.pending_comparison is not None:
            current_human_die = (
                battle.pending_comparison.attacker_die if human_is_attacker else battle.pending_comparison.blocker_die
            )
            if die is current_human_die:
                return f"{die.display()} | Runde {round_number}: Offen"
        return die.display()

    def row_text_for_enemy(die, round_number: int) -> str:
        if die.comparison_label:
            return die.comparison_label
        if battle.pending_comparison is not None:
            current_enemy_die = (
                battle.pending_comparison.blocker_die if human_is_attacker else battle.pending_comparison.attacker_die
            )
            if die is current_enemy_die:
                return f"{die.display()} | Runde {round_number}: Offen"
        return "Verdeckt"

    for index, die in enumerate(human_dice):
        rect = pygame.Rect(
            human_column_x,
            dice_title_y + 42 + index * 58,
            column_width,
            46,
        )
        pygame.draw.rect(self.screen, BUTTON_COLOR, rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=6)
        self.blit_text(self.font, row_text_for_human(die, index + 1), TEXT_COLOR, rect.x + 10, rect.y + 11)
        if not die.used and battle.pending_comparison is None:
            available_index = len([existing for existing in human_dice[:index] if not existing.used])
            self.click_targets["human_dice"].append((rect, available_index))

    for index, die in enumerate(enemy_dice):
        rect = pygame.Rect(
            enemy_column_x,
            dice_title_y + 42 + index * 58,
            column_width,
            46,
        )
        pygame.draw.rect(self.screen, BUTTON_COLOR, rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=6)
        self.blit_text(self.font, row_text_for_enemy(die, index + 1), TEXT_COLOR, rect.x + 10, rect.y + 11)

    if battle.pending_comparison is not None:
        attacker_die = battle.pending_comparison.attacker_die
        blocker_die = battle.pending_comparison.blocker_die
        info_y = dice_title_y + 42 + max(len(human_dice), len(enemy_dice)) * 58 + 12
        self.blit_text(self.font, f"Aufgedeckt: {attacker.name} {attacker_die.display()} | {blocker.name} {blocker_die.display()}", TEXT_COLOR, human_column_x, info_y)
        if battle.pending_comparison.human_can_adapt:
            self.blit_text(self.small_font, "Anpassung kann jetzt eingesetzt werden.", MUTED_TEXT, human_column_x, info_y + 28)


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
