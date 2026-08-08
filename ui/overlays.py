from __future__ import annotations

import pygame

from core.models import PHASE_REACTION, PHASE_SPELL_TARGETING, SpellEffect
from ui.style import CARD_BORDER, HIGHLIGHT, MUTED_TEXT, OVERLAY_COLOR, PANEL_COLOR, SECTION_COLOR, TEXT_COLOR


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
    max_columns = 3
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
            die_rect = pygame.Rect(start_x + die_index * (die_size + gap), start_y + row_index * (die_size + gap), die_size, die_size)
            _draw_rendered_die(self, die_rect, roll)
    if winner:
        inner_rect = pygame.Rect(card_rect.x + 4, card_rect.y + 4, card_rect.width - 8, card_rect.height - 8)
        pygame.draw.rect(self.screen, HIGHLIGHT, inner_rect, 2, border_radius=8)


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
    self.blit_text(self.font, "Klicke beliebige Karten an, um sie einmalig ins Deck zurueckzumischen und neu zu ziehen.", MUTED_TEXT, panel.x + 30, panel.y + 58)
    for index, card in enumerate(self.engine.human_player.hand):
        mulligan_step = self.card_width + 32
        rect = self.draw_hand_card(card, panel.x + 30 + index * mulligan_step, panel.y + 140, card.instance_id in self.engine.selected_hand_ids)
        self.click_targets["mulligan_hand"].append((rect, card.instance_id))


def draw_dice_battle_overlay(self) -> None:
    battles = list(getattr(self.engine, "pending_dice_battles", []) or ([] if self.engine.pending_dice_battle is None else [self.engine.pending_dice_battle]))
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
    overlay.fill((0, 0, 0, 90))
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(max(40, (self.window_width - 420) // 2), max(40, (self.window_height - 140) // 2), 420, 140)
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    self.blit_centered_text(self.title_font, "Pausiert", TEXT_COLOR, pygame.Rect(panel.x, panel.y + 22, panel.width, 30))
    self.blit_centered_text(self.font, "Enter setzt das Spiel fort.", MUTED_TEXT, pygame.Rect(panel.x + 20, panel.y + 68, panel.width - 40, 24))


def draw_discard_target_overlay(self) -> None:
    if self.engine.phase != PHASE_SPELL_TARGETING or self.engine.pending_spell_cast is None:
        return
    card = self.engine.get_card_from_pending_spell()
    if card is None or card.template.spell_effect != SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
        return
    pending = self.engine.pending_spell_cast
    controller = self.engine.get_player_by_id(pending.controller_id)
    valid_targets = self.engine.get_valid_discard_creature_target_refs(controller)
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    _, _, _, action_rect, _ = self.get_side_panel_layout()
    pygame.draw.rect(overlay, (0, 0, 0, 0), action_rect)
    self.screen.blit(overlay, (0, 0))

    panel_width = min(self.window_width - 120, 1100)
    panel_height = min(self.window_height - 160, 720)
    panel = pygame.Rect(
        max(40, (self.window_width - panel_width) // 2),
        max(40, (self.window_height - panel_height) // 2),
        panel_width,
        panel_height,
    )
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
    self.blit_text(self.title_font, f"{card.template.name} - Ablagestapel", TEXT_COLOR, panel.x + 24, panel.y + 20)
    self.blit_text(
        self.font,
        f"Waehle {card.template.spell_amount} Kreaturenkarte(n) aus deinem Ablagestapel. Ausgewaehlt: {len(pending.selected_targets)}/{card.template.spell_amount}.",
        MUTED_TEXT,
        panel.x + 24,
        panel.y + 54,
    )

    row_height = 64
    top = panel.y + 98
    selected_ids = {target.card_instance_id for target in pending.selected_targets if target.card_instance_id is not None}
    for index, target in enumerate(valid_targets):
        discard_card = self.engine.resolve_target_discard_card_for_controller(controller, target)
        if discard_card is None:
            continue
        row_rect = pygame.Rect(panel.x + 24, top + index * (row_height + 10), panel.width - 48, row_height)
        if row_rect.bottom > panel.bottom - 20:
            break
        is_selected = discard_card.instance_id in selected_ids
        pygame.draw.rect(self.screen, SECTION_COLOR if not is_selected else BUTTON_COLOR, row_rect, border_radius=6)
        pygame.draw.rect(self.screen, HIGHLIGHT if is_selected else CARD_BORDER, row_rect, 2, border_radius=6)
        abilities = ", ".join(ability.value for ability in discard_card.template.abilities) or "-"
        self.blit_text(self.font, discard_card.template.name, TEXT_COLOR, row_rect.x + 14, row_rect.y + 9)
        self.blit_text(
            self.small_font,
            (
                f"Kosten {discard_card.template.cost.resources}/R{discard_card.template.cost.recycle} | "
                f"AW {discard_card.template.aw} | VW {discard_card.template.vw} | "
                f"LW {self.engine.get_template_max_lw(discard_card.template)} | "
                f"SW {self.engine.get_template_damage_value(discard_card.template)} | "
                f"{abilities} | Besitzer: {controller.name}"
            ),
            MUTED_TEXT,
            row_rect.x + 14,
            row_rect.y + 34,
        )
        self.click_targets["discard_cards"].append((row_rect, discard_card.instance_id))


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
