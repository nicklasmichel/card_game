from __future__ import annotations

import pygame

from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_CREATURE_ABILITIES, BUILDER_HASTE_COST
from core.models import Ability, PHASE_BUILDER_ABILITY, PHASE_BUILDER_CREATURE, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_MAIN_1
from engine.builder import BUILDER_ABILITY_LABELS, BUILDER_CREATURE_ABILITY_RULES_TEXT, get_builder_creature_abilities_label
from ui.player_labels import format_player_names_for_ui, get_player_display_name, get_ui_match_mode
from ui.style import BUTTON_COLOR, BUTTON_DISABLED, CARD_BORDER, HIGHLIGHT, MUTED_TEXT, PANEL_COLOR, PLAYER_CARD_COLOR, SECTION_COLOR, TEXT_COLOR
from ui.timers import format_elapsed_ms

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
    if self.engine.phase == PHASE_MAIN_1:
        return "Main"
    return get_overview_phase_label(self.engine.phase)


def get_action_panel_prompt(self) -> str:
    local_decision_check = getattr(self, "local_player_has_primary_decision", None)
    if callable(local_decision_check) and not local_decision_check():
        return f"Waiting for {get_player_display_name(self, self.engine.active_player)}."
    if self.engine.is_ai_thinking():
        return format_player_names_for_ui(self, self.engine.current_prompt())
    if self.engine.pending_ai_action is not None:
        return format_player_names_for_ui(self, self.engine.current_prompt())
    if self.engine.phase == PHASE_MAIN_1:
        if not self.engine.active_player.main_action_used_this_turn:
            return ""
        return "Continue to combat."
    if self.engine.phase == PHASE_BUILDER_ABILITY:
        return "Attack or end the turn."
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        return ""
    return format_player_names_for_ui(self, self.engine.current_prompt())


def get_panel_header_font(self) -> pygame.font.Font:
    return pygame.font.SysFont(
        "arial",
        max(self.font.get_height() + self.scale_font(6), self.scale_font(28)),
        bold=True,
    )


def _visible_log_messages(self) -> list[str]:
    if getattr(self.engine, "use_public_log_for_display", False):
        messages = getattr(self.engine, "public_log_messages", self.engine.log_messages)
    else:
        messages = self.engine.log_messages
    return [format_player_names_for_ui(self, message) for message in messages]


def _rebuild_log_cache(self, width: int, line_height: int, line_gap: int) -> None:
    messages = _visible_log_messages(self)
    wrapped_entries = [self.wrap_text(self.font, message, width) or [""] for message in messages]
    self._log_wrapped_entries = wrapped_entries
    self._log_wrapped_width = width
    self._log_cached_message_count = len(messages)
    self._log_cached_match_mode = get_ui_match_mode(self)
    self._log_entry_heights = [
        len(entry) * line_height + max(0, len(entry) - 1) * line_gap
        for entry in wrapped_entries
    ]


def _ensure_log_cache(self, width: int, line_height: int, line_gap: int) -> None:
    messages = _visible_log_messages(self)
    cached_width = getattr(self, "_log_wrapped_width", None)
    cached_count = getattr(self, "_log_cached_message_count", 0)
    cached_match_mode = getattr(self, "_log_cached_match_mode", None)
    if cached_width != width or cached_count > len(messages) or cached_match_mode != get_ui_match_mode(self):
        _rebuild_log_cache(self, width, line_height, line_gap)
        return
    if cached_count == len(messages):
        return
    wrapped_entries = getattr(self, "_log_wrapped_entries", [])
    entry_heights = getattr(self, "_log_entry_heights", [])
    for message in messages[cached_count:]:
        wrapped = self.wrap_text(self.font, message, width) or [""]
        wrapped_entries.append(wrapped)
        entry_heights.append(len(wrapped) * line_height + max(0, len(wrapped) - 1) * line_gap)
    self._log_wrapped_entries = wrapped_entries
    self._log_entry_heights = entry_heights
    self._log_wrapped_width = width
    self._log_cached_message_count = len(messages)
    self._log_cached_match_mode = get_ui_match_mode(self)


def draw_side_panel(self) -> None:
    panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect = self.get_side_panel_layout()
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=6)
    self.draw_section_box(log_rect)
    self.draw_side_log(log_rect)
    self.draw_section_box(action_rect)
    self.draw_side_actions(action_rect)


def get_side_panel_layout(self) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect]:
    outer_margin = self.scale_ui(10)
    inner_margin = self.scale_ui(14)
    panel = pygame.Rect(
        self.window_width - self.side_panel_width - outer_margin,
        outer_margin,
        self.side_panel_width,
        self.window_height - outer_margin * 2,
    )
    inner_x = panel.x + inner_margin
    inner_width = panel.width - inner_margin * 2
    section_gap = self.scale_ui(10)
    inner_height = panel.height - inner_margin * 2
    usable_height = inner_height - section_gap
    log_height = usable_height // 2
    action_height = usable_height - log_height
    enemy_piles_rect = pygame.Rect(inner_x, panel.y + inner_margin, inner_width, 0)
    log_rect = pygame.Rect(inner_x, panel.y + inner_margin, inner_width, log_height)
    action_rect = pygame.Rect(inner_x, log_rect.bottom + section_gap, inner_width, action_height)
    player_piles_rect = pygame.Rect(inner_x, action_rect.bottom, inner_width, 0)
    return panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect


def draw_buttons(self) -> None:
    return


def draw_side_overview(self, rect: pygame.Rect) -> None:
    phase_label = get_overview_phase_label(self.engine.phase)
    active_name = get_player_display_name(self, self.engine.active_player)
    human_name = get_player_display_name(self, self.engine.human_player)
    opponent_name = get_player_display_name(self, self.engine.ai_player)
    lines = [
        f"Turn: {self.engine.turn_number}",
        f"Active: {active_name} - {phase_label}",
        f"{human_name} Life: {self.engine.human_player.life}",
        f"{opponent_name} Life: {self.engine.ai_player.life}",
        f"{human_name} Resources: {self.engine.human_player.available_resources()}/{self.engine.human_player.total_resources()}",
        f"{opponent_name} Resources: {self.engine.ai_player.available_resources()}/{self.engine.ai_player.total_resources()}",
    ]
    if self.paused:
        lines.append("Status: Paused")
    y = rect.y + 28
    for line in lines:
        self.blit_text(self.small_font, line, TEXT_COLOR, rect.x + 12, y)
        y += 16


def draw_side_log(self, rect: pygame.Rect) -> None:
    header_font = get_panel_header_font(self)
    margin = self.scale_ui(12)
    header_y = rect.y + margin
    self.blit_text(header_font, "Logging", TEXT_COLOR, rect.x + margin, header_y)
    game_timer_text = format_elapsed_ms(getattr(self, "game_elapsed_ms", 0))
    game_timer_width = header_font.size(game_timer_text)[0]
    self.blit_text(
        header_font,
        game_timer_text,
        MUTED_TEXT,
        rect.right - margin - game_timer_width,
        header_y,
    )
    header_gap = self.scale_ui(18)
    viewport = pygame.Rect(
        rect.x + margin,
        header_y + header_font.get_height() + header_gap,
        rect.width - self.scale_ui(36),
        rect.height - (header_font.get_height() + header_gap + margin),
    )
    self.log_viewport_rect = viewport
    line_height = max(self.font.get_height() + self.scale_ui(2), self.scale_ui(22))
    line_gap = self.scale_ui(2)
    entry_gap = self.scale_ui(6)
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
    track_rect = pygame.Rect(rect.right - self.scale_ui(18), viewport.y, self.scale_ui(6), viewport.height)
    border_radius = self.scale_ui(3)
    pygame.draw.rect(self.screen, SECTION_COLOR, track_rect, border_radius=border_radius)
    if content_height > viewport.height and max_offset > 0:
        thumb_height = max(self.scale_ui(28), int(viewport.height * (viewport.height / content_height)))
        thumb_y = viewport.y + int((viewport.height - thumb_height) * (self.log_scroll_offset / max_offset))
        thumb_rect = pygame.Rect(track_rect.x, thumb_y, track_rect.width, thumb_height)
        pygame.draw.rect(self.screen, HIGHLIGHT, thumb_rect, border_radius=border_radius)
    else:
        pygame.draw.rect(self.screen, MUTED_TEXT, track_rect, border_radius=border_radius)


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
                    f"Abilities: {get_builder_creature_abilities_label(build.selected_abilities)}",
                ],
            )
        )
        sections.append(
            (
                "Ability choice",
                [
                    f"{'[x]' if ability in build.selected_abilities else '[ ]'} {BUILDER_ABILITY_LABELS[ability]} ({BUILDER_HASTE_COST if ability == Ability.HASTE else 0}) - {BUILDER_CREATURE_ABILITY_RULES_TEXT[ability]}"
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
            wrapped = self.wrap_text(self.small_font, line, rect.width - self.scale_ui(24))
            content.extend(wrapped or [""])
        line_height = max(self.small_font.get_height() + self.scale_ui(3), self.scale_ui(16))
        height = self.scale_ui(24) + len(content) * line_height
        box_rect = pygame.Rect(
            rect.x + self.scale_ui(12),
            y,
            rect.width - self.scale_ui(24),
            height,
        )
        if max_bottom is not None and box_rect.bottom > max_bottom:
            break
        pygame.draw.rect(self.screen, SECTION_COLOR, box_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, box_rect, 1, border_radius=6)
        line_y = box_rect.y + self.scale_ui(8)
        self.blit_text(self.small_font, title, HIGHLIGHT, box_rect.x + self.scale_ui(8), line_y)
        line_y += max(self.small_font.get_height() + self.scale_ui(5), self.scale_ui(18))
        first = True
        for line in content[1:]:
            color = TEXT_COLOR if first else MUTED_TEXT
            self.blit_text(self.small_font, line, color, box_rect.x + self.scale_ui(8), line_y)
            line_y += line_height
            first = False
        y = box_rect.bottom + self.scale_ui(8)
    return y


def draw_side_actions(self, rect: pygame.Rect) -> None:
    s = self.scale_ui
    local_decision_check = getattr(self, "local_player_has_primary_decision", None)
    local_player_can_act = (
        local_decision_check()
        if callable(local_decision_check)
        else True
    )
    action_specs = (
        self.engine.get_button_specs()
        if local_player_can_act
        else []
    )
    phase_label = get_action_panel_title(self)
    button_font = get_panel_header_font(self)
    compact_button_font = pygame.font.SysFont(
        "arial",
        max(self.font.get_height() + self.scale_font(2), self.scale_font(22)),
        bold=True,
    )
    header_font = button_font
    header_y = rect.y + s(12)
    phase_timer_text = format_elapsed_ms(getattr(self, "phase_elapsed_ms", 0))
    phase_timer_width = header_font.size(phase_timer_text)[0]
    phase_timer_x = rect.right - s(12) - phase_timer_width
    header_text = self.fit_text(
        header_font,
        f"{get_player_display_name(self, self.engine.active_player)} - {phase_label}",
        max(1, phase_timer_x - (rect.x + s(24))),
    )
    self.blit_text(
        header_font,
        header_text,
        TEXT_COLOR,
        rect.x + s(12),
        header_y,
    )
    self.blit_text(
        header_font,
        phase_timer_text,
        MUTED_TEXT,
        phase_timer_x,
        header_y,
    )
    prompt_text = get_action_panel_prompt(self)
    prompt_bottom = header_y + header_font.get_height()
    if prompt_text:
        prompt_rect = pygame.Rect(rect.x + s(12), prompt_bottom + s(12), rect.width - s(24), s(64))
        self.blit_wrapped_text(self.font, prompt_text, MUTED_TEXT, prompt_rect, s(22))
        prompt_bottom = prompt_rect.bottom
    button_margin = s(12)
    width = rect.width - button_margin * 2
    height = s(36)
    gap = s(10)
    builder_resource_line_height = s(22)
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
        height = s(72)
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        stat_specs = [spec for spec in action_specs if spec.action in BUILDER_STAT_ACTIONS]
        ability_specs = [spec for spec in action_specs if spec.action.startswith("builder_select_ability_")]
        footer_specs = [spec for spec in action_specs if spec not in stat_specs and spec not in ability_specs]
        stat_rows = (len(stat_specs) + 3) // 4
        stat_button_height = s(44)
        group_heights: list[int] = []
        if self.engine.pending_builder_creature is not None:
            group_heights.append(builder_resource_line_height)
        if ability_specs:
            group_heights.append(len(ability_specs) * s(44) + max(0, len(ability_specs) - 1) * gap)
        if stat_specs:
            group_heights.append(stat_rows * stat_button_height + max(0, stat_rows - 1) * gap)
        if footer_specs:
            group_heights.append(len(footer_specs) * s(44) + max(0, len(footer_specs) - 1) * gap)
        button_total_height = sum(group_heights) + max(0, len(group_heights) - 1) * gap
    elif builder_main_action_row or combat_block_action_row:
        button_total_height = len(action_specs) * height + gap
    else:
        button_total_height = len(action_specs) * height + max(0, len(action_specs) - 1) * gap
    button_start_y = rect.bottom - s(12) - button_total_height
    draw_action_detail_sections(self, rect, prompt_bottom + s(8), button_start_y - s(8))
    start_y = button_start_y
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        stat_gap = s(8)
        stat_button_width = max(s(44), (width - stat_gap * 3) // 4)
        stat_button_height = s(44)
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
        for ability_index, spec in enumerate(ability_specs):
            button_rect = pygame.Rect(start_x, current_y, width, s(44))
            selected_ability_actions = set()
            if self.engine.pending_builder_creature is not None:
                pending = self.engine.pending_builder_creature
                if pending.selected_primary_ability is not None:
                    selected_ability_actions.add(f"builder_select_ability_{pending.selected_primary_ability.name.lower()}")
                if pending.has_haste:
                    selected_ability_actions.add("builder_select_ability_haste")
            is_selected_ability = spec.action in selected_ability_actions
            button_color = HIGHLIGHT if is_selected_ability and spec.enabled else BUTTON_COLOR if spec.enabled else BUTTON_DISABLED
            pygame.draw.rect(self.screen, button_color, button_rect, border_radius=s(6))
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, s(2), border_radius=s(6))
            self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
            current_y += s(44)
            if ability_index < len(ability_specs) - 1:
                current_y += gap
        if ability_specs and (stat_specs or footer_specs):
            current_y += gap
        stat_rows = (len(stat_specs) + 3) // 4
        for row_index in range(stat_rows):
            row_specs = stat_specs[row_index * 4 : row_index * 4 + 4]
            for column_index, spec in enumerate(row_specs):
                button_rect = pygame.Rect(
                    start_x + column_index * (stat_button_width + stat_gap),
                    current_y,
                    stat_button_width,
                    stat_button_height,
                )
                color = BUTTON_COLOR if spec.enabled else _soft_disabled_button_color(BUTTON_COLOR)
                pygame.draw.rect(self.screen, color, button_rect, border_radius=s(6))
                pygame.draw.rect(self.screen, CARD_BORDER, button_rect, s(2), border_radius=s(6))
                self.blit_centered_text(compact_button_font, spec.label, TEXT_COLOR, button_rect)
                self.buttons.append((button_rect, spec))
            current_y += stat_button_height
            if row_index < stat_rows - 1:
                current_y += gap
        if stat_specs and footer_specs:
            current_y += gap
        for footer_index, spec in enumerate(footer_specs):
            button_rect = pygame.Rect(start_x, current_y, width, s(44))
            is_create_button = spec.action == "builder_confirm_creature"
            if is_create_button and spec.enabled:
                button_color = PLAYER_CARD_COLOR
            elif spec.enabled:
                button_color = BUTTON_COLOR
            else:
                button_color = BUTTON_DISABLED
            pygame.draw.rect(self.screen, button_color, button_rect, border_radius=s(6))
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, s(2), border_radius=s(6))
            self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
            current_y += s(44)
            if footer_index < len(footer_specs) - 1:
                current_y += gap
        return
    if builder_main_action_row or combat_block_action_row:
        for index, spec in enumerate(action_specs):
            button_rect = pygame.Rect(start_x, start_y + index * (height + gap), width, height)
            pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=s(6))
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, s(2), border_radius=s(6))
            self.blit_centered_text(button_font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
        return
    for index, spec in enumerate(action_specs):
        button_rect = pygame.Rect(start_x, start_y + index * (height + gap), width, height)
        pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=s(6))
        pygame.draw.rect(self.screen, CARD_BORDER, button_rect, s(2), border_radius=s(6))
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
