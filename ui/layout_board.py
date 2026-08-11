from __future__ import annotations

from typing import Dict

import pygame

from core.builder_rules import BUILDER_CREATURE_CAP, BUILDER_MAX_RESOURCES
from core.config import STARTING_LIFE
from core.models import PHASE_BUILDER_CREATURE
from ui.style import CARD_BORDER, HIGHLIGHT, TEXT_COLOR


def draw_enemy_area(self) -> None:
    sections = self.get_playfield_sections()
    creatures_rect = sections["player_2_creatures"]
    self.draw_playfield_section_box(creatures_rect, "player_2_creatures")
    status_metrics = get_area_status_metrics(self, self.engine.ai_player)
    status_rect = self.draw_area_status_block(self.engine.ai_player, creatures_rect)
    self.summoner_rects[self.engine.ai_player.player_id] = status_rect
    top_reserved_height = status_metrics["block_height"] + 20
    self.draw_creatures(
        self.engine.ai_player.battlefield,
        False,
        "player_2_creatures",
        creatures_rect.x + 10,
        creatures_rect.y + top_reserved_height,
        creatures_rect.width - 20,
        max(0, creatures_rect.height - top_reserved_height - 10),
    )


def draw_player_area(self) -> None:
    sections = self.get_playfield_sections()
    creatures_rect = sections["player_1_creatures"]
    self.player_creature_rect = creatures_rect.copy()
    self.player_resource_rect = pygame.Rect(0, 0, 0, 0)
    self.draw_playfield_section_box(creatures_rect, "player_1_creatures")
    status_metrics = get_area_status_metrics(self, self.engine.human_player)
    status_rect = self.draw_area_status_block(self.engine.human_player, creatures_rect)
    self.summoner_rects[self.engine.human_player.player_id] = status_rect
    display_creatures = list(self.engine.human_player.battlefield)
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        preview_creature = self.engine.get_builder_preview_creature(self.engine.human_player)
        if preview_creature is not None:
            display_creatures.append(preview_creature)
    bottom_reserved_height = status_metrics["block_height"] + 20
    self.draw_creatures(
        display_creatures,
        True,
        "player_1_creatures",
        creatures_rect.x + 10,
        creatures_rect.y + 10,
        creatures_rect.width - 20,
        max(0, creatures_rect.height - bottom_reserved_height - 10),
    )


def draw_combat_links(self) -> None:
    if not self.engine.selected_attackers and not self.engine.block_assignments:
        return

    sections = self.get_playfield_sections()
    enemy_rect = sections["player_2_creatures"]
    player_rect = sections["player_1_creatures"]
    enemy_positions = self.get_creature_screen_positions(
        self.engine.ai_player.battlefield,
        False,
        enemy_rect.x + 10,
        enemy_rect.y + 10,
        enemy_rect.width - 20,
        enemy_rect.height - 20,
    )
    player_positions = self.get_creature_screen_positions(
        self.engine.human_player.battlefield,
        True,
        player_rect.x + 10,
        player_rect.y + 10,
        player_rect.width - 20,
        player_rect.height - 20,
    )
    defender_summoner_rect = self.summoner_rects.get(self.engine.defending_player.player_id)
    if defender_summoner_rect is None:
        defender_summoner_rect = self.get_summoner_rect_for_player(self.engine.defending_player)

    attacker_ids = self.engine.selected_attackers or list(self.engine.block_assignments.keys())
    for attacker_id in attacker_ids:
        blocker_id = self.engine.block_assignments.get(attacker_id)
        attacker_rect = enemy_positions.get(attacker_id) or player_positions.get(attacker_id)
        if attacker_rect is None:
            continue

        attacker_selected = attacker_id == self.engine.selected_attack_target_id
        if blocker_id is None:
            summoner_color = HIGHLIGHT if attacker_selected else (206, 186, 96)
            self.draw_polyline(
                start=(
                    attacker_rect.centerx,
                    attacker_rect.bottom if attacker_rect.centery < defender_summoner_rect.centery else attacker_rect.top,
                ),
                end=(
                    defender_summoner_rect.centerx,
                    defender_summoner_rect.top if defender_summoner_rect.centery > attacker_rect.centery else defender_summoner_rect.bottom,
                ),
                color=summoner_color,
                via_y=(
                    (attacker_rect.bottom + defender_summoner_rect.top) // 2
                    if attacker_rect.centery < defender_summoner_rect.centery
                    else (attacker_rect.top + defender_summoner_rect.bottom) // 2
                ),
                width=3,
            )
            continue
        blocker_rect = player_positions.get(blocker_id) or enemy_positions.get(blocker_id)
        if blocker_rect is None:
            continue
        blocker_selected = blocker_id == self.engine.selected_blocker_id
        blocker_color = HIGHLIGHT if attacker_selected else (102, 188, 112)
        self.draw_polyline(
            start=(attacker_rect.centerx, attacker_rect.bottom if attacker_rect.centery < blocker_rect.centery else attacker_rect.top),
            end=(blocker_rect.centerx, blocker_rect.top if blocker_rect.centery > attacker_rect.centery else blocker_rect.bottom),
            color=blocker_color,
            via_y=(attacker_rect.bottom + blocker_rect.top) // 2 if attacker_rect.centery < blocker_rect.centery else (attacker_rect.top + blocker_rect.bottom) // 2,
            width=3 if blocker_selected else 2,
        )


def get_creature_screen_positions(
    self,
    creatures,
    is_human: bool,
    start_x: int,
    start_y: int,
    lane_width: int,
    lane_height: int,
) -> Dict[int, pygame.Rect]:
    positions: Dict[int, pygame.Rect] = {}
    base_column_gap = self.card_gap + 70
    column_step = self.card_height + base_column_gap
    columns = max(1, lane_width // column_step)
    row_spacing = 22
    total_rows = max(1, (len(creatures) + columns - 1) // columns)
    total_height = total_rows * self.card_height + max(0, total_rows - 1) * row_spacing
    row_top = start_y + max(0, (lane_height - total_height) // 2)
    for row in range((len(creatures) + columns - 1) // columns):
        row_creatures = creatures[row * columns : (row + 1) * columns]
        widths = [self.card_height if self.is_creature_visually_tapped(creature) else self.card_width for creature in row_creatures]
        heights = [self.card_width if self.is_creature_visually_tapped(creature) else self.card_height for creature in row_creatures]
        row_height = self.card_height
        column_gap = self.card_gap + (90 if all(self.is_creature_visually_tapped(creature) for creature in row_creatures) else 24)
        row_width = sum(widths) + max(0, len(row_creatures) - 1) * column_gap
        row_start_x = start_x + max(0, (lane_width - row_width) // 2)
        x = row_start_x
        for creature, width, height in zip(row_creatures, widths, heights):
            y = row_top + max(0, (row_height - height) // 2)
            positions[creature.unit_id] = pygame.Rect(x, y, width, height)
            x += width + column_gap
        row_top += row_height + row_spacing
    return positions


def get_playfield_sections(self) -> Dict[str, pygame.Rect]:
    side_panel_x = self.window_width - self.side_panel_width - 10
    playfield_rect = pygame.Rect(10, 10, side_panel_x - 20, self.window_height - 20)
    _panel, _enemy_piles_rect, log_rect, action_rect, _player_piles_rect = self.get_side_panel_layout()
    section_gap = action_rect.y - log_rect.bottom
    usable_height = playfield_rect.height - section_gap
    enemy_height = usable_height // 2
    player_height = usable_height - enemy_height
    player_2_creatures = pygame.Rect(playfield_rect.x, playfield_rect.y, playfield_rect.width, enemy_height)
    player_1_creatures = pygame.Rect(playfield_rect.x, player_2_creatures.bottom + section_gap, playfield_rect.width, player_height)
    zero_rect = pygame.Rect(playfield_rect.x, playfield_rect.y, 0, 0)
    return {
        "player_2_hand": zero_rect,
        "player_2_resources": zero_rect,
        "player_2_creatures": player_2_creatures,
        "player_1_creatures": player_1_creatures,
        "player_1_resources": zero_rect,
        "player_1_hand": zero_rect,
    }


def draw_builder_resource_stack_card(self, player, x: int, y: int) -> pygame.Rect:
    surface = self.build_resource_back_surface(self.engine.builder_resource_template().element, False)
    badge_rect = pygame.Rect(self.card_width // 2 - 28, self.card_height // 2 - 22, 56, 44)
    self.draw_card_badge(surface, badge_rect, f"{player.total_resources()}/{BUILDER_MAX_RESOURCES}", self.small_font, self.get_think_progress(player))
    rect = pygame.Rect(x, y, self.card_width, self.card_height)
    self.screen.blit(surface, rect.topleft)
    return rect


def draw_builder_resource_counter_text(self, player, x: int, y: int) -> pygame.Rect:
    resource_text = f"{player.total_resources()}/{BUILDER_MAX_RESOURCES}"
    resource_surface = self.title_font.render(resource_text, True, TEXT_COLOR)
    rect = pygame.Rect(x, y, resource_surface.get_width(), resource_surface.get_height())
    self.screen.blit(resource_surface, rect.topleft)
    return rect


def get_area_status_metrics(self, player) -> dict[str, int]:
    life_text = f"Life {player.life}/{STARTING_LIFE}"
    creatures_text = f"Creatures {len(player.battlefield)}/{BUILDER_CREATURE_CAP}"
    resources_text = f"Resources {player.total_resources()}/{BUILDER_MAX_RESOURCES}"
    line_height = self.title_font.get_height()
    gap = 4
    return {
        "life_width": self.title_font.size(life_text)[0],
        "creatures_width": self.title_font.size(creatures_text)[0],
        "resources_width": self.title_font.size(resources_text)[0],
        "line_height": line_height,
        "block_width": max(
            self.title_font.size(life_text)[0],
            self.title_font.size(creatures_text)[0],
            self.title_font.size(resources_text)[0],
        ),
        "block_height": line_height * 3 + gap * 2,
        "gap": gap,
        "life_text": life_text,
        "creatures_text": creatures_text,
        "resources_text": resources_text,
    }


def draw_area_status_block(self, player, rect: pygame.Rect) -> pygame.Rect:
    metrics = get_area_status_metrics(self, player)
    line_height = metrics["line_height"]
    gap = metrics["gap"]
    edge_margin = 10
    is_human = bool(getattr(player, "is_human", False))
    block_rect = pygame.Rect(
        rect.centerx - metrics["block_width"] // 2,
        rect.bottom - edge_margin - metrics["block_height"] if is_human else rect.y + edge_margin,
        metrics["block_width"],
        metrics["block_height"],
    )
    line_specs = [
        ("life_text", metrics["life_width"]),
        ("creatures_text", metrics["creatures_width"]),
        ("resources_text", metrics["resources_width"]),
    ]
    if not is_human:
        line_specs = list(reversed(line_specs))

    line_rects: list[tuple[str, pygame.Rect]] = []
    current_y = block_rect.y
    for text_key, text_width in line_specs:
        line_rects.append(
            (
                text_key,
                pygame.Rect(
                    rect.centerx - text_width // 2,
                    current_y,
                    text_width,
                    line_height,
                ),
            )
        )
        current_y += line_height + gap

    for text_key, line_rect in line_rects:
        self.screen.blit(self.title_font.render(metrics[text_key], True, TEXT_COLOR), line_rect.topleft)
    return block_rect


def draw_polyline(self, start: tuple[int, int], end: tuple[int, int], color, via_y: int, width: int) -> None:
    points = [start, (start[0], via_y), (end[0], via_y), end]
    pygame.draw.lines(self.screen, color, False, points, width)
    pygame.draw.circle(self.screen, color, end, max(3, width + 1))
    self.draw_arrowhead(points[-2], end, color, width)
    self.draw_link_marker(points[1], color, width)


def draw_arrowhead(self, from_point: tuple[int, int], to_point: tuple[int, int], color, width: int) -> None:
    dx = to_point[0] - from_point[0]
    dy = to_point[1] - from_point[1]
    if dx == 0 and dy == 0:
        return
    arrow_size = 10 + width
    if abs(dx) > abs(dy):
        if dx > 0:
            points = [to_point, (to_point[0] - arrow_size, to_point[1] - arrow_size // 2), (to_point[0] - arrow_size, to_point[1] + arrow_size // 2)]
        else:
            points = [to_point, (to_point[0] + arrow_size, to_point[1] - arrow_size // 2), (to_point[0] + arrow_size, to_point[1] + arrow_size // 2)]
    else:
        if dy > 0:
            points = [to_point, (to_point[0] - arrow_size // 2, to_point[1] - arrow_size), (to_point[0] + arrow_size // 2, to_point[1] - arrow_size)]
        else:
            points = [to_point, (to_point[0] - arrow_size // 2, to_point[1] + arrow_size), (to_point[0] + arrow_size // 2, to_point[1] + arrow_size)]
    pygame.draw.polygon(self.screen, color, points)


def draw_link_marker(self, center: tuple[int, int], color, width: int) -> None:
    radius = 4 + width
    pygame.draw.circle(self.screen, color, center, radius, 2)
    pygame.draw.circle(self.screen, color, center, max(2, radius - 4))


def draw_resources(self, resources, start_x: int, start_y: int, available_width: int, player=None, target_key: str | None = None) -> None:
    summoner_rect = None
    center_padding = max(28, self.card_gap * 2)
    if not resources:
        return
    left_resources = resources[: (len(resources) + 1) // 2]
    right_resources = resources[(len(resources) + 1) // 2 :]
    left_widths = [self.card_height if resource.tapped else self.card_width for resource in left_resources]
    right_widths = [self.card_height if resource.tapped else self.card_width for resource in right_resources]
    left_start = start_x
    left_available = max(0, ((summoner_rect.x if summoner_rect is not None else start_x + available_width // 2) - left_start - center_padding))
    right_start = (summoner_rect.right + center_padding) if summoner_rect is not None else start_x + available_width // 2
    right_available = max(0, start_x + available_width - right_start)

    def _positions(widths, zone_start: int, zone_available: int, from_right: bool) -> list[int]:
        if not widths:
            return []
        base_gap = self.card_gap + 8
        total_width = sum(widths) + max(0, len(widths) - 1) * base_gap
        if total_width <= zone_available:
            x = zone_start + max(0, (zone_available - total_width) // 2)
            positions = []
            for width in widths:
                positions.append(x)
                x += width + base_gap
            return positions
        step = max(40, (zone_available - widths[-1]) // max(1, len(widths) - 1))
        if from_right:
            positions = []
            x = zone_start + zone_available - widths[0]
            for width in widths:
                positions.append(x)
                x -= step
            return list(reversed(positions))
        return [zone_start + index * step for index in range(len(widths))]

    left_positions = _positions(left_widths, left_start, left_available, from_right=True)
    right_positions = _positions(right_widths, right_start, right_available, from_right=False)
    laid_out_resources = list(zip(left_resources, left_positions)) + list(zip(right_resources, right_positions))
    for index, (resource, x) in enumerate(laid_out_resources):
        height = self.card_width if resource.tapped else self.card_height
        y = start_y + max(0, (self.card_height - height) // 2)
        rect = self.draw_resource_card(resource, x, y)
        if self.last_preview_builder is not None:
            self.preview_targets.append((rect, self.last_preview_builder, self.last_preview_info_builder))


def draw_creatures(self, creatures, is_human: bool, target_key: str, start_x: int, start_y: int, lane_width: int, lane_height: int) -> None:
    base_column_gap = self.card_gap + 70
    column_step = self.card_height + base_column_gap
    columns = max(1, lane_width // column_step)
    row_spacing = 22
    total_rows = max(1, (len(creatures) + columns - 1) // columns)
    total_height = total_rows * self.card_height + max(0, total_rows - 1) * row_spacing
    row_top = start_y + max(0, (lane_height - total_height) // 2)
    render_queue = []
    overlay_queue = []
    for row in range((len(creatures) + columns - 1) // columns):
        row_creatures = creatures[row * columns : (row + 1) * columns]
        widths = [self.card_height if self.is_creature_visually_tapped(creature) else self.card_width for creature in row_creatures]
        heights = [self.card_width if self.is_creature_visually_tapped(creature) else self.card_height for creature in row_creatures]
        row_height = self.card_height
        column_gap = self.card_gap + (90 if all(self.is_creature_visually_tapped(creature) for creature in row_creatures) else 24)
        row_width = sum(widths) + max(0, len(row_creatures) - 1) * column_gap
        row_start_x = start_x + max(0, (lane_width - row_width) // 2)
        x = row_start_x
        for creature, width, height in zip(row_creatures, widths, heights):
            y = row_top + max(0, (row_height - height) // 2)
            offset_x, offset_y = self.get_creature_animation_offset(creature.unit_id, pygame.Rect(x, y, width, height))
            draw_x = x + offset_x
            draw_y = y + offset_y
            selected = False
            if target_key == "player_1_creatures" and creature.unit_id in self.engine.selected_attackers:
                selected = True
            if target_key == "player_1_creatures" and creature.unit_id == self.engine.selected_blocker_id:
                selected = True
            if target_key == "player_2_creatures" and creature.unit_id == self.engine.selected_attack_target_id:
                selected = True
            attacking = creature.unit_id in self.engine.selected_attackers
            extra_line = ""
            render_entry = (creature, is_human, draw_x, draw_y, selected, extra_line, attacking, target_key)
            if creature.unit_id in self.creature_lunges:
                overlay_queue.append(render_entry)
            else:
                render_queue.append(render_entry)
            x += width + column_gap
        row_top += row_height + row_spacing

    for creature, is_human, draw_x, draw_y, selected, extra_line, attacking, target_key in render_queue:
        rect = self.draw_creature_card(creature, is_human, draw_x, draw_y, selected, extra_line, attacking)
        is_preview = bool(getattr(creature, "is_builder_preview", False))
        if not is_preview:
            self.creature_rects[creature.unit_id] = rect.copy()
        if self.last_preview_builder is not None:
            self.preview_targets.append((rect, self.last_preview_builder, self.last_preview_info_builder))
        if not is_preview:
            self.click_targets[target_key].append((rect, creature.unit_id))
    self.creature_overlay_draws.extend(overlay_queue)


def draw_hand(self, player, start_x: int, start_y: int, available_width: int, interactive: bool = True) -> None:
    hand = player.hand
    if not hand:
        return
    card_step = self.card_width + self.card_gap
    total_width = len(hand) * self.card_width + (len(hand) - 1) * self.card_gap
    if total_width > available_width:
        card_step = max(26, (available_width - self.card_width) // max(1, len(hand) - 1))
    total_render_width = self.card_width + max(0, len(hand) - 1) * card_step
    card_start_x = start_x + max(0, (available_width - total_render_width) // 2)

    for index, card in enumerate(hand):
        if interactive and self.drag_active and self.dragged_card_surface is not None and card.instance_id == self.dragged_hand_card_id:
            continue
        x = card_start_x + index * card_step
        if interactive:
            rect = self.draw_hand_card(card, x, start_y, interactive and card.instance_id in self.engine.selected_hand_ids)
        else:
            rect = self.draw_hidden_hand_card(card, x, start_y)
        if self.last_preview_builder is not None:
            self.preview_targets.append((rect, self.last_preview_builder, self.last_preview_info_builder))
        if interactive:
            self.click_targets["hand"].append((rect, card.instance_id))
