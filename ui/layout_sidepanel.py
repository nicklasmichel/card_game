from __future__ import annotations

from typing import List

import pygame

from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_ABILITY_COST, BUILDER_CREATURE_ABILITIES
from core.models import ButtonSpec, PHASE_BUILDER_ABILITY, PHASE_BUILDER_CREATURE, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_MAIN_1
from engine.builder import BUILDER_ABILITY_LABELS, BUILDER_CREATURE_ABILITY_RULES_TEXT
from ui.style import BUTTON_COLOR, BUTTON_DISABLED, CARD_BORDER, HIGHLIGHT, MUTED_TEXT, PANEL_COLOR, SECTION_COLOR, TEXT_COLOR

BUILDER_STAT_BUTTON_COLORS = {
    "builder_aw_up": (164, 97, 97),
    "builder_aw_down": (164, 97, 97),
    "builder_vw_up": (96, 122, 172),
    "builder_vw_down": (96, 122, 172),
    "builder_sw_up": (168, 128, 74),
    "builder_sw_down": (168, 128, 74),
    "builder_lw_up": (95, 150, 109),
    "builder_lw_down": (95, 150, 109),
}


def _dim_button_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(max(36, int(channel * 0.55)) for channel in color)


def get_overview_phase_label(phase: str) -> str:
    if phase == PHASE_BUILDER_CREATURE:
        return "Build creature"
    if phase == PHASE_BUILDER_ABILITY:
        return "Combat" if not BUILDER_ABILITIES_ENABLED else "Ability"
    if phase == PHASE_MAIN_1:
        return "Main"
    if phase in {PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE}:
        return "Combat"
    return phase


def get_action_panel_title(self) -> str:
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        return "Build creature"
    return get_overview_phase_label(self.engine.phase)


def get_action_panel_prompt(self) -> str:
    if self.engine.pending_ai_action is not None:
        return self.engine.current_prompt()
    if self.engine.phase == PHASE_MAIN_1:
        if not self.engine.active_player.main_action_used_this_turn:
            return ""
        return "Continue to combat."
    if self.engine.phase == PHASE_BUILDER_ABILITY:
        return "Attack or end the turn."
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        return "Distribute ready resources across the new creature's stats and choose exactly one free ability."
    return self.engine.current_prompt()


def draw_side_panel(self) -> None:
    panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect = self.get_side_panel_layout()
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=6)
    self.draw_section_box(log_rect)
    self.draw_side_log(log_rect)
    self.draw_section_box(action_rect)
    self.draw_side_actions(action_rect)


def get_side_panel_layout(self) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect]:
    panel = pygame.Rect(self.window_width - self.side_panel_width - 10, 10, self.side_panel_width, self.window_height - 20)
    inner_x = panel.x + 14
    inner_width = panel.width - 28
    section_gap = 10
    inner_height = panel.height - 28
    usable_height = inner_height - section_gap
    log_height = usable_height // 2
    action_height = usable_height - log_height
    enemy_piles_rect = pygame.Rect(inner_x, panel.y + 14, inner_width, 0)
    log_rect = pygame.Rect(inner_x, panel.y + 14, inner_width, log_height)
    action_rect = pygame.Rect(inner_x, log_rect.bottom + section_gap, inner_width, action_height)
    player_piles_rect = pygame.Rect(inner_x, action_rect.bottom, inner_width, 0)
    return panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect


def draw_buttons(self) -> None:
    return


def draw_side_overview(self, rect: pygame.Rect) -> None:
    phase_label = get_overview_phase_label(self.engine.phase)
    lines = [
        f"Turn: {self.engine.turn_number}",
        f"Active: {self.engine.active_player.name} - {phase_label}",
        f"Player 1 Life: {self.engine.human_player.life}",
        f"Player 2 Life: {self.engine.ai_player.life}",
        f"Player 1 Resources: {self.engine.human_player.available_resources()}/{self.engine.human_player.total_resources()}",
        f"Player 2 Resources: {self.engine.ai_player.available_resources()}/{self.engine.ai_player.total_resources()}",
    ]
    if self.paused:
        lines.append("Status: Paused")
    y = rect.y + 28
    for line in lines:
        self.blit_text(self.small_font, line, TEXT_COLOR, rect.x + 12, y)
        y += 16


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


def format_target_ref(self, target) -> str:
    return "-"


def get_action_detail_sections(self) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    if self.engine.phase == PHASE_BUILDER_CREATURE and self.engine.pending_builder_creature is not None:
        build = self.engine.pending_builder_creature
        sections.append(
            (
                "New creature",
                [
                    f"Attack: {build.aw}",
                    f"Defense: {build.vw}",
                    f"Damage: {build.sw}",
                    f"Life: {build.lw}",
                    f"Cost: {self.engine.builder_creature_build_cost()} / {build.available_resources} available",
                    f"Ready after build: {self.engine.builder_remaining_ready_resources()}",
                    f"Enters tapped: {'No' if build.has_haste else 'Yes'}",
                    f"Chosen ability: {BUILDER_ABILITY_LABELS.get(build.selected_ability, '-')}",
                ],
            )
        )
        sections.append(
            (
                "Ability choice",
                [
                    f"{'[x]' if build.selected_ability == ability else '[ ]'} {BUILDER_ABILITY_LABELS[ability]} ({BUILDER_ABILITY_COST}) - {BUILDER_CREATURE_ABILITY_RULES_TEXT[ability]}"
                    for ability in BUILDER_CREATURE_ABILITIES
                ],
            )
        )
        return sections
    if BUILDER_ABILITIES_ENABLED and self.engine.phase == PHASE_BUILDER_ABILITY and self.engine.pending_builder_ability is not None:
        pending = self.engine.pending_builder_ability
        card = next((existing for existing in self.engine.active_player.hand if existing.instance_id == pending.card_instance_id), None)
        sections.append(
            (
                "Ability card",
                [
                    f"Card: {card.template.name if card is not None else '-'}",
                    f"Mode: {pending.mode or '-'}",
                    f"Stat: {pending.selected_stat or '-'}",
                    f"Target: {self.engine.get_unit_by_id(pending.selected_target_id).name if pending.selected_target_id is not None and self.engine.get_unit_by_id(pending.selected_target_id) is not None else '-'}",
                ],
            )
        )
    return sections


def draw_action_detail_sections(self, rect: pygame.Rect, start_y: int, max_bottom: int | None = None) -> int:
    sections = get_action_detail_sections(self)
    if not sections:
        return start_y
    y = start_y
    for title, lines in sections:
        content = [title]
        for line in lines:
            wrapped = self.wrap_text(self.small_font, line, rect.width - 24)
            content.extend(wrapped or [""])
        height = 16 + len(content) * 16 + 8
        box_rect = pygame.Rect(rect.x + 12, y, rect.width - 24, height)
        if max_bottom is not None and box_rect.bottom > max_bottom:
            break
        pygame.draw.rect(self.screen, SECTION_COLOR, box_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, box_rect, 1, border_radius=6)
        line_y = box_rect.y + 8
        self.blit_text(self.small_font, title, HIGHLIGHT, box_rect.x + 8, line_y)
        line_y += 18
        first = True
        for line in content[1:]:
            color = TEXT_COLOR if first else MUTED_TEXT
            self.blit_text(self.small_font, line, color, box_rect.x + 8, line_y)
            line_y += 16
            first = False
        y = box_rect.bottom + 8
    return y


def draw_side_actions(self, rect: pygame.Rect) -> None:
    action_specs = self.engine.get_button_specs()
    phase_label = get_action_panel_title(self)
    button_font = pygame.font.SysFont("arial", max(self.font.get_height() + 6, 28), bold=True)
    compact_button_font = pygame.font.SysFont("arial", max(self.font.get_height() + 2, 22), bold=True)
    header_font = button_font
    header_y = rect.y + 12
    self.blit_text(
        header_font,
        f"{self.engine.turn_number} | {self.engine.active_player.name} - {phase_label}",
        TEXT_COLOR,
        rect.x + 12,
        header_y,
    )
    prompt_rect = pygame.Rect(rect.x + 12, header_y + header_font.get_height() + 12, rect.width - 24, 64)
    self.blit_wrapped_text(self.font, get_action_panel_prompt(self), MUTED_TEXT, prompt_rect, 22)
    button_margin = 12
    width = rect.width - button_margin * 2
    height = 36
    gap = 10
    start_x = rect.x + button_margin
    large_next_button = len(action_specs) == 1 and action_specs[0].label == "Next"
    builder_main_action_row = (
        self.engine.phase == PHASE_MAIN_1
        and self.engine.active_player.is_human
        and len(action_specs) == 2
        and {spec.action for spec in action_specs} == {"builder_add_resource", "builder_open_creature"}
    )
    if builder_main_action_row or large_next_button:
        height = 72
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        stat_rows = min(2, len(action_specs) // 4)
        trailing_buttons = max(0, len(action_specs) - stat_rows * 4)
        stat_button_size = max(44, (width - gap * 3) // 4)
        button_total_height = stat_rows * stat_button_size + max(0, stat_rows - 1) * gap
        if trailing_buttons:
            button_total_height += gap + trailing_buttons * 44 + max(0, trailing_buttons - 1) * gap
    elif builder_main_action_row:
        button_total_height = len(action_specs) * height + gap
    else:
        button_total_height = len(action_specs) * height + max(0, len(action_specs) - 1) * gap
    button_start_y = rect.bottom - 12 - button_total_height
    draw_action_detail_sections(self, rect, prompt_rect.bottom + 8, button_start_y - 8)
    start_y = button_start_y
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        stat_gap = 8
        stat_button_size = max(44, (width - stat_gap * 3) // 4)
        current_y = start_y
        stat_rows = min(2, len(action_specs) // 4)
        for row_index in range(stat_rows):
            row_specs = action_specs[row_index * 4 : row_index * 4 + 4]
            for column_index, spec in enumerate(row_specs):
                button_rect = pygame.Rect(
                    start_x + column_index * (stat_button_size + stat_gap),
                    current_y,
                    stat_button_size,
                    stat_button_size,
                )
                base_color = BUILDER_STAT_BUTTON_COLORS.get(spec.action, BUTTON_COLOR)
                color = base_color if spec.enabled else _dim_button_color(base_color)
                pygame.draw.rect(self.screen, color, button_rect, border_radius=6)
                pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
                self.blit_centered_text(compact_button_font, spec.label, TEXT_COLOR, button_rect)
                self.buttons.append((button_rect, spec))
            current_y += stat_button_size + gap
        for spec in action_specs[stat_rows * 4:]:
            button_rect = pygame.Rect(start_x, current_y, width, 44)
            selected_ability_action = None
            if self.engine.pending_builder_creature is not None and self.engine.pending_builder_creature.selected_ability is not None:
                selected_ability_action = (
                    f"builder_select_ability_{self.engine.pending_builder_creature.selected_ability.name.lower()}"
                )
            is_selected_ability = spec.action.startswith("builder_select_ability_") and spec.action == selected_ability_action
            button_color = HIGHLIGHT if is_selected_ability and spec.enabled else BUTTON_COLOR if spec.enabled else BUTTON_DISABLED
            pygame.draw.rect(self.screen, button_color, button_rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
            self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
            current_y += 44 + gap
        return
    if builder_main_action_row:
        for index, spec in enumerate(action_specs):
            button_rect = pygame.Rect(start_x, start_y + index * (height + gap), width, height)
            pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
            self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
        return
    for index, spec in enumerate(action_specs):
        button_rect = pygame.Rect(start_x, start_y + index * (height + gap), width, height)
        pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
        self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
        self.buttons.append((button_rect, spec))


def draw_side_piles(self, rect: pygame.Rect, player, card_y: int) -> None:
    return


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
