from __future__ import annotations

import pygame

from core.models import PHASE_REACTION, PHASE_SPELL_TARGETING, SpellEffect
from ui.style import BUTTON_COLOR, CARD_BORDER, ENEMY_CARD_COLOR, HIGHLIGHT, MUTED_TEXT, OVERLAY_COLOR, PANEL_COLOR, SECTION_COLOR, TEXT_COLOR


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
    attacker_owner = self.engine.get_player_by_id(battle.attacker_owner)
    human_is_attacker = battle.attacker_owner == self.engine.human_player.player_id
    human_dice = battle.attacker_dice if human_is_attacker else battle.blocker_dice
    enemy_dice = battle.blocker_dice if human_is_attacker else battle.attacker_dice
    pending_spell = self.engine.pending_spell_cast
    pending_card = self.engine.get_card_from_pending_spell(pending_spell) if pending_spell is not None else None
    selecting_combat_die = (
        self.engine.phase == PHASE_SPELL_TARGETING
        and pending_card is not None
        and pending_card.template.spell_effect in {
            SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE,
            SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE,
        }
    )

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

    if getattr(attacker_owner, "attackers_die_bonus_this_turn", 0) > 0:
        self.blit_text(
            self.font,
            f"Sturmformation aktiv: Angreifende Kreaturen erhalten +{attacker_owner.attackers_die_bonus_this_turn} auf ihre Würfelergebnisse.",
            HIGHLIGHT,
            panel.x + 56,
            panel.y + 52,
        )

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
        if not die.used and (battle.pending_comparison is None or selecting_combat_die):
            available_index = len([existing for existing in human_dice[:index] if not existing.used])
            self.click_targets["human_dice"].append((rect, available_index))
            if selecting_combat_die:
                pygame.draw.rect(self.screen, HIGHLIGHT, rect, 3, border_radius=6)

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


def draw_pause_overlay(self) -> None:
    if not self.paused:
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 90))
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(max(40, (self.window_width - 420) // 2), max(40, (self.window_height - 140) // 2), 420, 140)
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    self.blit_centered_text(self.title_font, "Pausiert", TEXT_COLOR, pygame.Rect(panel.x, panel.y + 22, panel.width, 30))
    self.blit_centered_text(self.font, "Enter setzt das Spiel fort.", MUTED_TEXT, pygame.Rect(panel.x + 20, panel.y + 68, panel.width - 40, 24))


def draw_reaction_context_boxes(self, preview_panel_rect: pygame.Rect) -> None:
    if self.engine.phase != PHASE_REACTION or self.engine.reaction_context is None:
        return
    trigger = self.engine.reaction_context.trigger.value
    next_player = self.engine.get_player_by_id(self.engine.reaction_priority_player_id) if self.engine.reaction_priority_player_id is not None else None
    profile = self.engine.get_reaction_window_profile()
    sections: list[tuple[str, list[str]]] = [
        (
            self.engine.get_reaction_window_title(),
            [
                f"Ausloeser: {trigger}",
                self.engine.get_reaction_window_description(),
                f"Naechster Spieler: {next_player.name if next_player is not None else '-'}",
                f"Fenstertyp: {'Allgemein' if profile.get('is_general_window') else 'Ereignis'}",
                f"Kampffenster: {'Ja' if profile.get('is_combat_window') else 'Nein'}",
            ],
        )
    ]
    if profile.get("shows_stack_preview", True):
        stack_lines = ["Leer"]
        if self.engine.spell_stack:
            stack_lines = []
            for depth, item in enumerate(reversed(self.engine.spell_stack), start=1):
                if item.targets:
                    target_parts: list[str] = []
                    for target in item.targets:
                        if target.target_type == "player":
                            player = self.engine.get_player_by_id(target.player_id or 0)
                            target_parts.append(player.name)
                        elif target.target_type == "creature":
                            creature = self.engine.get_unit_by_id(target.creature_id or -1)
                            target_parts.append(creature.name if creature is not None else "Kreatur nicht mehr im Spiel")
                        elif target.target_type == "die":
                            role = "Angreifer" if target.die_role == "attacker" else "Blocker"
                            target_parts.append(f"{role}-Wuerfel {0 if target.die_index is None else target.die_index + 1}")
                        else:
                            target_parts.append(target.target_type)
                    target_text = ", ".join(target_parts)
                else:
                    target_text = "ohne Ziel"
                stack_lines.append(f"{depth}. {item.controller.name}: {item.source_card.template.name} -> {target_text}")
        sections.append(("Reaktionskette", stack_lines))
    legal_lines = ["Gegner entscheidet."]
    if self.engine.reaction_priority_player_id == self.engine.human_player.player_id:
        legal = [
            card.template.name
            for card in self.engine.human_player.hand
            if self.engine.can_react_with_card(self.engine.human_player, card)
        ]
        legal_lines = legal if legal else ["Nur Passen ist legal."]
    sections.append(("Legale Reaktionen", legal_lines))

    max_width = min(360, max(260, preview_panel_rect.x - 28))
    box_right = preview_panel_rect.x - 18
    current_bottom = preview_panel_rect.bottom
    for title, lines in reversed(sections):
        wrapped_lines: list[str] = []
        for line in lines:
            wrapped_lines.extend(self.wrap_text(self.small_font, line, max_width - 18) or [""])
        box_height = 30 + len(wrapped_lines) * 16 + 10
        box_rect = pygame.Rect(box_right - max_width, current_bottom - box_height, max_width, box_height)
        box_rect.x = max(12, box_rect.x)
        pygame.draw.rect(self.screen, SECTION_COLOR, box_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, box_rect, 1, border_radius=6)
        line_y = box_rect.y + 8
        self.blit_text(self.small_font, title, HIGHLIGHT, box_rect.x + 8, line_y)
        line_y += 18
        for line in wrapped_lines:
            self.blit_text(self.small_font, line, MUTED_TEXT, box_rect.x + 8, line_y)
            line_y += 16
        current_bottom = box_rect.y - 8


def draw_reaction_focus_preview(self) -> None:
    if self.engine.phase != PHASE_REACTION or self.preview_builder is not None:
        return
    if not self.engine.reaction_window_shows_stack_preview():
        return

    focus_card = None
    if self.engine.spell_stack:
        focus_card = self.engine.spell_stack[-1].source_card
    elif self.engine.reaction_context is not None:
        focus_card = self.engine.reaction_context.source_card

    if focus_card is None:
        return

    preview_surface = self.build_preview_hand_card_surface(focus_card)
    width = preview_surface.get_width() * 2
    height = preview_surface.get_height() * 2
    playfield_width = self.window_width - self.side_panel_width - 30
    max_width = playfield_width - 80
    max_height = self.window_height - 180
    scale = min(max_width / width, max_height / height, 1.0)
    preview_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    scaled = pygame.transform.smoothscale(preview_surface, preview_size)
    playfield_center_x = 10 + playfield_width // 2
    rect = scaled.get_rect(center=(playfield_center_x, (self.window_height // 2) + 24))
    self.screen.blit(scaled, rect.topleft)
