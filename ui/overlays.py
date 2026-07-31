from __future__ import annotations

import pygame

from ui.style import BUTTON_COLOR, CARD_BORDER, ENEMY_CARD_COLOR, HIGHLIGHT, MUTED_TEXT, OVERLAY_COLOR, PANEL_COLOR, TEXT_COLOR


def draw_mulligan_overlay(self) -> None:
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    _, _, _, action_rect = self.get_side_panel_layout()
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
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(max(40, (self.window_width - 1180) // 2), max(40, (self.window_height - 680) // 2), 1180, 680)
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    attacker = self.engine.get_unit_by_id(battle.attacker_id)
    blocker = self.engine.get_unit_by_id(battle.blocker_id)
    if attacker is None or blocker is None:
        return
    human_is_attacker = battle.attacker_owner == self.engine.human_player.player_id
    human_unit = attacker if human_is_attacker else blocker
    enemy_unit = blocker if human_is_attacker else attacker
    human_dice = battle.attacker_dice if human_is_attacker else battle.blocker_dice
    enemy_dice = battle.blocker_dice if human_is_attacker else battle.attacker_dice
    self.blit_text(self.title_font, f"Würfelkampf: {attacker.name} gegen {blocker.name}", TEXT_COLOR, panel.x + 30, panel.y + 32)
    self.blit_text(self.font, f"Eigene Kreatur: {human_unit.name} ({human_unit.aw_vw}) HP {human_unit.current_hp}/{human_unit.vw}", TEXT_COLOR, panel.x + 30, panel.y + 64)
    self.blit_text(self.font, f"Gegnerische Kreatur: {enemy_unit.name} ({enemy_unit.aw_vw}) HP {enemy_unit.current_hp}/{enemy_unit.vw}", TEXT_COLOR, panel.x + 30, panel.y + 92)
    self.blit_text(self.font, f"Verdeckte Gegnerwürfel: {sum(1 for die in enemy_dice if not die.used)}", MUTED_TEXT, panel.x + 30, panel.y + 120)
    available_human_dice = [die for die in human_dice if not die.used]
    self.blit_text(self.title_font, "Eigene verfügbare Würfel", TEXT_COLOR, panel.x + 30, panel.y + 158)
    if battle.pending_comparison is None:
        for index, die in enumerate(available_human_dice):
            rect = pygame.Rect(panel.x + 30 + (index % 4) * 270, panel.y + 194 + (index // 4) * 56, 248, 44)
            pygame.draw.rect(self.screen, BUTTON_COLOR, rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=6)
            self.blit_text(self.font, f"{index + 1}. {die.display()}", TEXT_COLOR, rect.x + 10, rect.y + 10)
            self.click_targets["human_dice"].append((rect, index))
    else:
        attacker_die = battle.pending_comparison.attacker_die
        blocker_die = battle.pending_comparison.blocker_die
        self.blit_text(self.font, f"Aufgedeckt: {attacker.name} {attacker_die.display()} | {blocker.name} {blocker_die.display()}", TEXT_COLOR, panel.x + 30, panel.y + 202)
        if battle.pending_comparison.human_can_adapt:
            self.blit_text(self.small_font, "Anpassung kann jetzt eingesetzt werden.", MUTED_TEXT, panel.x + 30, panel.y + 228)
    self.blit_text(self.title_font, "Bisherige Vergleiche", TEXT_COLOR, panel.x + 30, panel.y + 320)
    y = panel.y + 356
    for record in battle.history[-5:]:
        self.blit_text(self.small_font, f"Runde {record.round_number}: {record.human_unit_name} {record.human_result} | {record.enemy_unit_name} {record.enemy_result}", TEXT_COLOR, panel.x + 30, y)
        self.blit_text(self.small_font, record.outcome_text, MUTED_TEXT, panel.x + 30, y + 18)
        y += 44


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
