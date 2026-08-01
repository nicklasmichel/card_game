from __future__ import annotations

from typing import List

import pygame

from core.models import (
    ButtonSpec,
    Element,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_ORDER_BLOCKERS,
    PHASE_RESOURCE,
    PHASE_SUMMONING,
)
from ui.style import (
    BUTTON_COLOR,
    BUTTON_DISABLED,
    CARD_BORDER,
    HIGHLIGHT,
    MUTED_TEXT,
    PANEL_COLOR,
    SECTION_COLOR,
    TEXT_COLOR,
)


def get_overview_phase_label(phase: str) -> str:
    if phase == PHASE_RESOURCE:
        return "Ressource"
    if phase == PHASE_SUMMONING:
        return "Beschwoerung"
    if phase == "Recycle auswaehlen":
        return "Beschwoerung"
    if phase in {PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_ORDER_BLOCKERS, PHASE_DICE_BATTLE}:
        return "Kampf"
    return phase


def draw_side_panel(self) -> None:
    panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect = self.get_side_panel_layout()
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=6)
    self.draw_side_piles(enemy_piles_rect, self.engine.ai_player, self.get_playfield_sections()["enemy_hand"].y + 10)
    self.draw_section_box(log_rect)
    self.draw_side_log(log_rect)
    self.draw_section_box(action_rect)
    self.draw_side_actions(action_rect)
    self.draw_side_piles(player_piles_rect, self.engine.human_player, self.get_playfield_sections()["player_hand"].y + 10)


def get_side_panel_layout(self) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect]:
    panel = pygame.Rect(self.window_width - self.side_panel_width - 10, 10, self.side_panel_width, self.window_height - 20)
    inner_x = panel.x + 14
    inner_width = panel.width - 28
    section_gap = 10
    inner_height = panel.height - 28
    hand_height = self.get_playfield_sections()["player_hand"].height
    piles_height = min(hand_height, max(self.card_height + 44, inner_height // 5))
    remaining_height = inner_height - piles_height * 2 - section_gap * 4
    log_height = max(140, remaining_height // 2)
    action_height = max(180, remaining_height - log_height)
    used_height = piles_height * 2 + log_height + action_height + section_gap * 4
    slack = max(0, inner_height - used_height)
    log_height += slack // 2
    action_height += slack - (slack // 2)

    enemy_piles_rect = pygame.Rect(inner_x, panel.y + 14, inner_width, piles_height)
    log_rect = pygame.Rect(inner_x, enemy_piles_rect.bottom + section_gap, inner_width, log_height)
    action_rect = pygame.Rect(inner_x, log_rect.bottom + section_gap, inner_width, action_height)
    player_piles_rect = pygame.Rect(inner_x, action_rect.bottom + section_gap, inner_width, piles_height)
    return panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect


def draw_buttons(self) -> None:
    return


def draw_side_overview(self, rect: pygame.Rect) -> None:
    phase_label = get_overview_phase_label(self.engine.phase)
    lines = [
        f"Zug: {self.engine.turn_number}",
        f"Am Zug: {self.engine.active_player.name} - {phase_label}",
        f"Spieler LP: {self.engine.human_player.life}",
        f"Gegner LP: {self.engine.ai_player.life}",
        f"Spieler Hand/Deck: {len(self.engine.human_player.hand)}/{len(self.engine.human_player.deck)}",
        f"Gegner Hand/Deck: {len(self.engine.ai_player.hand)}/{len(self.engine.ai_player.deck)}",
    ]
    y = rect.y + 28
    for line in lines:
        self.blit_text(self.small_font, line, TEXT_COLOR, rect.x + 12, y)
        y += 16
    if self.engine.phase == PHASE_DECLARE_BLOCKERS:
        target = self.engine.get_unit_by_id(self.engine.selected_attack_target_id) if self.engine.selected_attack_target_id is not None else None
        target_name = target.name if target is not None else "-"
        self.blit_text(self.small_font, f"Blockziel: {target_name}", MUTED_TEXT, rect.x + 12, y + 4)


def draw_side_log(self, rect: pygame.Rect) -> None:
    viewport = pygame.Rect(rect.x + 12, rect.y + 28, rect.width - 36, rect.height - 40)
    self.log_viewport_rect = viewport
    line_height = 22
    line_gap = 4
    wrapped_lines: List[str] = []
    for message in self.engine.log_messages:
        wrapped = self.wrap_text(self.font, message, viewport.width)
        wrapped_lines.extend(wrapped or [""])
        wrapped_lines.append("")
    if wrapped_lines:
        wrapped_lines.pop()
    content_height = len(wrapped_lines) * (line_height + line_gap)
    previous_max_offset = max(0, getattr(self, "log_content_height", 0) - viewport.height)
    was_at_bottom = self.log_scroll_offset >= previous_max_offset
    max_offset = max(0, content_height - viewport.height)
    if was_at_bottom:
        self.log_scroll_offset = max_offset
    else:
        self.log_scroll_offset = max(0, min(self.log_scroll_offset, max_offset))
    self.log_content_height = content_height
    clip_before = self.screen.get_clip()
    self.screen.set_clip(viewport)
    y = viewport.y - self.log_scroll_offset
    for line in wrapped_lines:
        if y + line_height >= viewport.y and y <= viewport.bottom:
            self.blit_text(self.font, line, MUTED_TEXT, viewport.x, y)
        y += line_height + line_gap
    self.screen.set_clip(clip_before)
    track_rect = pygame.Rect(rect.right - 18, viewport.y, 6, viewport.height)
    pygame.draw.rect(self.screen, SECTION_COLOR, track_rect, border_radius=3)
    if content_height > viewport.height and max_offset > 0:
        thumb_height = max(28, int(viewport.height * (viewport.height / content_height)))
        thumb_y = viewport.y + int((viewport.height - thumb_height) * (self.log_scroll_offset / max_offset))
        thumb_rect = pygame.Rect(track_rect.x, thumb_y, track_rect.width, thumb_height)
        pygame.draw.rect(self.screen, HIGHLIGHT, thumb_rect, border_radius=3)
    else:
        pygame.draw.rect(self.screen, MUTED_TEXT, track_rect, border_radius=3)


def draw_side_actions(self, rect: pygame.Rect) -> None:
    action_specs = self.engine.get_button_specs()
    ui_specs = [
        ButtonSpec("Gegner Handkarten", True, "ui_toggle_enemy_hand"),
        ButtonSpec("Spiel fortsetzen" if self.paused else "Spiel Pausieren", True, "ui_toggle_pause"),
    ]
    phase_label = get_overview_phase_label(self.engine.phase)
    self.blit_text(
        self.title_font,
        f"{self.engine.turn_number} | {self.engine.active_player.name} - {phase_label}",
        TEXT_COLOR,
        rect.x + 12,
        rect.y + 12,
    )
    prompt_rect = pygame.Rect(rect.x + 12, rect.y + 52, rect.width - 24, 72)
    self.blit_wrapped_text(self.font, self.engine.current_prompt(), MUTED_TEXT, prompt_rect, 22)
    button_margin = 12
    width = rect.width - button_margin * 2
    height = 36
    gap = 10
    start_x = rect.x + button_margin
    start_y = rect.y + 132
    for index, spec in enumerate(action_specs):
        button_rect = pygame.Rect(start_x, start_y + index * (height + gap), width, height)
        pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
        self.blit_centered_text(self.font, spec.label, TEXT_COLOR, button_rect)
        self.buttons.append((button_rect, spec))

    ui_total_height = len(ui_specs) * height + max(0, len(ui_specs) - 1) * gap
    ui_start_y = rect.bottom - ui_total_height - 12
    for index, spec in enumerate(ui_specs):
        button_rect = pygame.Rect(start_x, ui_start_y + index * (height + gap), width, height)
        pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
        self.blit_centered_text(self.font, spec.label, TEXT_COLOR, button_rect)
        self.buttons.append((button_rect, spec))


def draw_side_piles(self, rect: pygame.Rect, player, card_y: int) -> None:
    card_width = self.card_width
    card_height = self.card_height
    available_width = max(0, rect.width - card_width * 2)
    side_gap = max(0, available_width // 3)
    middle_gap = max(0, rect.width - card_width * 2 - side_gap * 2)
    deck_x = rect.x + side_gap
    discard_x = deck_x + card_width + middle_gap

    top_deck_card = player.deck[-1] if player.deck else None
    if top_deck_card is not None or player.summoner_key:
        if top_deck_card is not None:
            deck_surface = self.build_resource_back_surface(top_deck_card.template.element, False)
        else:
            fallback_elements = {
                "fire": Element.FIRE,
                "water": Element.WATER,
                "earth": Element.EARTH,
                "air": Element.AIR,
            }
            deck_surface = self.build_resource_back_surface(fallback_elements.get(player.summoner_key, Element.AIR), False)
        deck_rect = pygame.Rect(deck_x, card_y, card_width, card_height)
        self.screen.blit(deck_surface, deck_rect.topleft)
        pygame.draw.rect(self.screen, CARD_BORDER, deck_rect, 2, border_radius=9)
        deck_badge_rect = pygame.Rect(deck_rect.centerx - 23, deck_rect.y + int(card_height * 0.69) - 23, 46, 46)
        self.draw_card_badge(self.screen, deck_badge_rect, str(len(player.deck)), self.font, self.get_think_progress(player))
        self.preview_targets.append((deck_rect, lambda player=player: self.build_preview_deck_surface(player)))

    top_discard = player.discard_pile[-1] if player.discard_pile else None
    discard_rect = pygame.Rect(discard_x, card_y, card_width, card_height)
    if top_discard is not None:
        preview_surface = self.build_card_surface(
            template_id=top_discard.template.template_id,
            title=top_discard.template.name,
            cost=top_discard.template.cost,
            stats=f"{top_discard.template.aw}/{top_discard.template.vw}",
            defense_text=f"{top_discard.template.vw}/{top_discard.template.vw}",
            element=top_discard.template.element,
            type_line=self.get_creature_type_line(top_discard.template),
            line_one=self.get_card_ability_lines(top_discard.template)[0],
            line_two=self.get_card_ability_lines(top_discard.template)[1],
            accent_color=(186, 177, 154),
            frame_color=(191, 161, 92),
            tapped=False,
            selected=False,
        )
        self.screen.blit(preview_surface, discard_rect.topleft)
        pygame.draw.rect(self.screen, CARD_BORDER, discard_rect, 2, border_radius=9)
        self.preview_targets.append((discard_rect, lambda card=top_discard: self.build_preview_hand_card_surface(card)))
    else:
        pygame.draw.rect(self.screen, PANEL_COLOR, discard_rect, border_radius=9)
        pygame.draw.rect(self.screen, CARD_BORDER, discard_rect, 2, border_radius=9)


def handle_log_scroll(self, delta: int) -> None:
    if self.log_viewport_rect.width <= 0 or self.log_viewport_rect.height <= 0:
        return
    mouse_pos = pygame.mouse.get_pos()
    if not self.log_viewport_rect.collidepoint(mouse_pos):
        return
    self.log_scroll_offset = max(0, self.log_scroll_offset + delta)


def blit_text(self, font: pygame.font.Font, text: str, color, x: int, y: int) -> None:
    self.screen.blit(font.render(text, True, color), (x, y))


def draw_section_box(self, rect: pygame.Rect, title: str = "") -> None:
    pygame.draw.rect(self.screen, SECTION_COLOR, rect, border_radius=6)
    pygame.draw.rect(self.screen, CARD_BORDER, rect, 1, border_radius=6)
    if title:
        self.blit_text(self.small_font, title, MUTED_TEXT, rect.x + 10, rect.y + 6)
