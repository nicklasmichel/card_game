from __future__ import annotations

from typing import List

import pygame

from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_ABILITY_COST, BUILDER_CREATURE_ABILITIES
from core.models import ButtonSpec, PHASE_BUILDER_ABILITY, PHASE_BUILDER_CREATURE, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_MAIN_1
from engine.builder import BUILDER_ABILITY_LABELS, BUILDER_CREATURE_ABILITY_RULES_TEXT
from ui.style import BUTTON_COLOR, BUTTON_DISABLED, CARD_BORDER, HIGHLIGHT, MUTED_TEXT, PANEL_COLOR, PLAYER_CARD_COLOR, SECTION_COLOR, TEXT_COLOR

BUILDER_STAT_ACTIONS = {
    "builder_aw_up",
    "builder_aw_down",
    "builder_vw_up",
    "builder_vw_down",
    "builder_sw_up",
    "builder_sw_down",
    "builder_lw_up",
    "builder_lw_down",
}


def _soft_disabled_button_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(int(color[index] * 0.45 + BUTTON_DISABLED[index] * 0.55) for index in range(3))


def get_overview_phase_label(phase: str) -> str:
    if phase == PHASE_BUILDER_CREATURE:
        return "Build creature"
    if phase == PHASE_BUILDER_ABILITY:
        return "Combat" if not BUILDER_ABILITIES_ENABLED else "Ability"
    if phase == PHASE_MAIN_1:
        return "Main Phase"
    if phase in {PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE}:
        return "Combat"
    return phase


def get_action_panel_title(self) -> str:
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        return "Build creature"
    return get_overview_phase_label(self.engine.phase)


def get_action_panel_prompt(self) -> str:
    if self.engine.is_ai_thinking():
        return self.engine.current_prompt()
    if self.engine.pending_ai_action is not None:
        return self.engine.current_prompt()
    if self.engine.phase == PHASE_MAIN_1:
        if not self.engine.active_player.main_action_used_this_turn:
            return ""
        return "Continue to combat."
    if self.engine.phase == PHASE_BUILDER_ABILITY:
        return "Attack or end the turn."
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        return ""
    return self.engine.current_prompt()


def get_panel_header_font(self) -> pygame.font.Font:
    return pygame.font.SysFont("arial", max(self.font.get_height() + 6, 28), bold=True)


def _rebuild_log_cache(self, width: int, line_height: int, line_gap: int) -> None:
    wrapped_entries = [self.wrap_text(self.font, message, width) or [""] for message in self.engine.log_messages]
    self._log_wrapped_entries = wrapped_entries
    self._log_wrapped_width = width
    self._log_cached_message_count = len(self.engine.log_messages)
    self._log_entry_heights = [
        len(entry) * line_height + max(0, len(entry) - 1) * line_gap
        for entry in wrapped_entries
    ]


def _ensure_log_cache(self, width: int, line_height: int, line_gap: int) -> None:
    cached_width = getattr(self, "_log_wrapped_width", None)
    cached_count = getattr(self, "_log_cached_message_count", 0)
    if cached_width != width or cached_count > len(self.engine.log_messages):
        _rebuild_log_cache(self, width, line_height, line_gap)
        return
    if cached_count == len(self.engine.log_messages):
        return
    wrapped_entries = getattr(self, "_log_wrapped_entries", [])
    entry_heights = getattr(self, "_log_entry_heights", [])
    for message in self.engine.log_messages[cached_count:]:
        wrapped = self.wrap_text(self.font, message, width) or [""]
        wrapped_entries.append(wrapped)
        entry_heights.append(len(wrapped) * line_height + max(0, len(wrapped) - 1) * line_gap)
    self._log_wrapped_entries = wrapped_entries
    self._log_entry_heights = entry_heights
    self._log_wrapped_width = width
    self._log_cached_message_count = len(self.engine.log_messages)


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
    header_font = get_panel_header_font(self)
    header_y = rect.y + 12
    self.blit_text(header_font, "Logging", TEXT_COLOR, rect.x + 12, header_y)
    header_gap = 18
    viewport = pygame.Rect(
        rect.x + 12,
        header_y + header_font.get_height() + header_gap,
        rect.width - 36,
        rect.height - (header_font.get_height() + header_gap + 12),
    )
    self.log_viewport_rect = viewport
    line_height = 22
    line_gap = 2
    entry_gap = 6
    _ensure_log_cache(self, viewport.width, line_height, line_gap)
    wrapped_entries = getattr(self, "_log_wrapped_entries", [])
    entry_heights = getattr(self, "_log_entry_heights", [])
    content_height = sum(entry_heights) + max(0, len(entry_heights) - 1) * entry_gap
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
    for entry_index, entry in enumerate(wrapped_entries):
        entry_height = entry_heights[entry_index]
        entry_bottom = y + entry_height
        if entry_bottom < viewport.y:
            y = entry_bottom + (entry_gap if entry_index < len(wrapped_entries) - 1 else 0)
            continue
        if y > viewport.bottom:
            break
        for line_index, line in enumerate(entry):
            if y + line_height >= viewport.y and y <= viewport.bottom:
                self.blit_text(self.font, line, MUTED_TEXT, viewport.x, y)
            y += line_height
            if line_index < len(entry) - 1:
                y += line_gap
        if entry_index < len(wrapped_entries) - 1:
            y += entry_gap
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
    button_font = get_panel_header_font(self)
    compact_button_font = pygame.font.SysFont("arial", max(self.font.get_height() + 2, 22), bold=True)
    header_font = button_font
    header_y = rect.y + 12
    self.blit_text(
        header_font,
        f"{self.engine.active_player.name} - {phase_label}",
        TEXT_COLOR,
        rect.x + 12,
        header_y,
    )
    prompt_text = get_action_panel_prompt(self)
    prompt_bottom = header_y + header_font.get_height()
    if prompt_text:
        prompt_rect = pygame.Rect(rect.x + 12, prompt_bottom + 12, rect.width - 24, 64)
        self.blit_wrapped_text(self.font, prompt_text, MUTED_TEXT, prompt_rect, 22)
        prompt_bottom = prompt_rect.bottom
    button_margin = 12
    width = rect.width - button_margin * 2
    height = 36
    gap = 10
    builder_resource_line_height = 22
    start_x = rect.x + button_margin
    large_primary_button = len(action_specs) == 1 and (
        action_specs[0].label == "Next"
        or action_specs[0].action in {"confirm_attackers", "confirm_blocks", "end_dice_battle", "new_game"}
    )
    builder_main_action_row = (
        self.engine.phase == PHASE_MAIN_1
        and self.engine.active_player.is_human
        and len(action_specs) == 2
        and {spec.action for spec in action_specs} == {"builder_add_resource", "builder_open_creature"}
    )
    combat_block_action_row = False
    if builder_main_action_row or combat_block_action_row or large_primary_button:
        height = 72
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        stat_specs = [spec for spec in action_specs if spec.action in BUILDER_STAT_ACTIONS]
        ability_specs = [spec for spec in action_specs if spec.action.startswith("builder_select_ability_")]
        footer_specs = [spec for spec in action_specs if spec not in stat_specs and spec not in ability_specs]
        stat_rows = (len(stat_specs) + 3) // 4
        stat_button_size = max(44, (width - gap * 3) // 4)
        button_total_height = builder_resource_line_height + gap
        if ability_specs:
            button_total_height += len(ability_specs) * 44 + max(0, len(ability_specs) - 1) * gap
        if stat_specs:
            if button_total_height:
                button_total_height += gap
            button_total_height += stat_rows * stat_button_size + max(0, stat_rows - 1) * gap
        if footer_specs:
            if button_total_height:
                button_total_height += gap
            button_total_height += len(footer_specs) * 44 + max(0, len(footer_specs) - 1) * gap
    elif builder_main_action_row or combat_block_action_row:
        button_total_height = len(action_specs) * height + gap
    else:
        button_total_height = len(action_specs) * height + max(0, len(action_specs) - 1) * gap
    button_start_y = rect.bottom - 12 - button_total_height
    draw_action_detail_sections(self, rect, prompt_bottom + 8, button_start_y - 8)
    start_y = button_start_y
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        stat_gap = 8
        stat_button_size = max(44, (width - stat_gap * 3) // 4)
        current_y = start_y
        stat_specs = [spec for spec in action_specs if spec.action in BUILDER_STAT_ACTIONS]
        ability_specs = [spec for spec in action_specs if spec.action.startswith("builder_select_ability_")]
        footer_specs = [spec for spec in action_specs if spec not in stat_specs and spec not in ability_specs]
        if self.engine.pending_builder_creature is not None:
            spent_resources = self.engine.builder_creature_build_cost()
            max_resources = self.engine.pending_builder_creature.available_resources
            self.blit_text(
                self.font,
                f"Resources {spent_resources}/{max_resources}",
                MUTED_TEXT,
                start_x,
                current_y,
            )
            current_y += builder_resource_line_height + gap
        for spec in ability_specs:
            button_rect = pygame.Rect(start_x, current_y, width, 44)
            selected_ability_action = None
            if self.engine.pending_builder_creature is not None and self.engine.pending_builder_creature.selected_ability is not None:
                selected_ability_action = (
                    f"builder_select_ability_{self.engine.pending_builder_creature.selected_ability.name.lower()}"
                )
            is_selected_ability = spec.action == selected_ability_action
            button_color = HIGHLIGHT if is_selected_ability and spec.enabled else BUTTON_COLOR if spec.enabled else BUTTON_DISABLED
            pygame.draw.rect(self.screen, button_color, button_rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
            self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
            current_y += 44 + gap
        if ability_specs and stat_specs:
            current_y += gap
        stat_rows = (len(stat_specs) + 3) // 4
        for row_index in range(stat_rows):
            row_specs = stat_specs[row_index * 4 : row_index * 4 + 4]
            for column_index, spec in enumerate(row_specs):
                button_rect = pygame.Rect(
                    start_x + column_index * (stat_button_size + stat_gap),
                    current_y,
                    stat_button_size,
                    stat_button_size,
                )
                color = BUTTON_COLOR if spec.enabled else _soft_disabled_button_color(BUTTON_COLOR)
                pygame.draw.rect(self.screen, color, button_rect, border_radius=6)
                pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
                self.blit_centered_text(compact_button_font, spec.label, TEXT_COLOR, button_rect)
                self.buttons.append((button_rect, spec))
            current_y += stat_button_size + gap
        if stat_specs and footer_specs:
            current_y += gap
        for spec in footer_specs:
            button_rect = pygame.Rect(start_x, current_y, width, 44)
            is_create_button = spec.action == "builder_confirm_creature"
            if is_create_button and spec.enabled:
                button_color = PLAYER_CARD_COLOR
            elif spec.enabled:
                button_color = BUTTON_COLOR
            else:
                button_color = BUTTON_DISABLED
            pygame.draw.rect(self.screen, button_color, button_rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
            self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
            current_y += 44 + gap
        return
    if builder_main_action_row or combat_block_action_row:
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
