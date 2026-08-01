from __future__ import annotations

from typing import Dict, List

import pygame

from models import (
    ButtonSpec,
    Element,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_SUMMONING,
    PHASE_ORDER_BLOCKERS,
    PHASE_RESOURCE,
)
from ui.style import (
    BUTTON_COLOR,
    BUTTON_DISABLED,
    CARD_BORDER,
    ENEMY_CARD_COLOR,
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
        return "Beschwörung"
    if phase == "Recycle auswählen":
        return "Beschwörung"
    if phase in {PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_ORDER_BLOCKERS, PHASE_DICE_BATTLE}:
        return "Kampf"
    return phase


def draw_enemy_area(self) -> None:
    sections = self.get_playfield_sections()
    hand_rect = sections["enemy_hand"]
    resource_rect = sections["enemy_resources"]
    creatures_rect = sections["enemy_creatures"]
    self.draw_playfield_section_box(hand_rect, "enemy_hand")
    self.draw_playfield_section_box(resource_rect, "enemy_resources")
    self.draw_playfield_section_box(creatures_rect, "enemy_creatures")
    self.draw_hand(self.engine.ai_player, hand_rect.x + 10, hand_rect.y + 10, hand_rect.width - 20, interactive=False)
    self.draw_resources(
        self.engine.ai_player.resources,
        resource_rect.x + 10,
        resource_rect.y + 10,
        resource_rect.width - 20,
        player=self.engine.ai_player,
        target_key=None,
    )
    self.draw_creatures(
        self.engine.ai_player.battlefield,
        False,
        "enemy_creatures",
        creatures_rect.x + 10,
        creatures_rect.y + 10,
        creatures_rect.width - 20,
        creatures_rect.height - 20,
    )


def draw_player_area(self) -> None:
    sections = self.get_playfield_sections()
    creatures_rect = sections["player_creatures"]
    resource_rect = sections["player_resources"]
    hand_rect = sections["player_hand"]
    self.player_creature_rect = creatures_rect.copy()
    self.player_resource_rect = resource_rect.copy()
    self.draw_playfield_section_box(resource_rect, "player_resources")
    self.draw_playfield_section_box(creatures_rect, "player_creatures")
    self.draw_playfield_section_box(hand_rect, "player_hand")
    self.draw_resources(
        self.engine.human_player.resources,
        resource_rect.x + 10,
        resource_rect.y + 10,
        resource_rect.width - 20,
        player=self.engine.human_player,
        target_key="player_resources",
    )
    self.draw_creatures(
        self.engine.human_player.battlefield,
        True,
        "player_creatures",
        creatures_rect.x + 10,
        creatures_rect.y + 10,
        creatures_rect.width - 20,
        creatures_rect.height - 20,
    )
    self.draw_hand(self.engine.human_player, hand_rect.x + 10, hand_rect.y + 10, hand_rect.width - 20)


def draw_combat_links(self) -> None:
    if not self.engine.selected_attackers and not self.engine.block_assignments:
        return

    sections = self.get_playfield_sections()
    enemy_rect = sections["enemy_creatures"]
    player_rect = sections["player_creatures"]
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
        blocker_ids = self.engine.block_assignments.get(attacker_id, [])
        attacker_rect = enemy_positions.get(attacker_id) or player_positions.get(attacker_id)
        if attacker_rect is None:
            continue

        attacker_selected = attacker_id == self.engine.selected_attack_target_id
        if not blocker_ids:
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
        for blocker_id in blocker_ids:
            blocker_rect = player_positions.get(blocker_id) or enemy_positions.get(blocker_id)
            if blocker_rect is None:
                continue
            blocker_selected = blocker_id == self.engine.selected_blocker_id or blocker_id in self.engine.blocker_to_attackers
            blocker_color = HIGHLIGHT if attacker_selected else ((102, 188, 112) if len(blocker_ids) == 1 else (212, 170, 94))
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
    section_gap = 2
    usable_height = playfield_rect.height - section_gap * 5
    section_height = usable_height // 6
    remainder = usable_height - section_height * 6

    heights = [
        section_height,
        section_height,
        section_height,
        section_height,
        section_height,
        section_height + remainder,
    ]

    enemy_hand = pygame.Rect(playfield_rect.x, playfield_rect.y, playfield_rect.width, heights[0])
    enemy_resources = pygame.Rect(playfield_rect.x, enemy_hand.bottom + section_gap, playfield_rect.width, heights[1])
    enemy_creatures = pygame.Rect(playfield_rect.x, enemy_resources.bottom + section_gap, playfield_rect.width, heights[2])
    player_creatures = pygame.Rect(playfield_rect.x, enemy_creatures.bottom + section_gap, playfield_rect.width, heights[3])
    player_resources = pygame.Rect(playfield_rect.x, player_creatures.bottom + section_gap, playfield_rect.width, heights[4])
    player_hand = pygame.Rect(playfield_rect.x, player_resources.bottom + section_gap, playfield_rect.width, heights[5])

    return {
        "enemy_hand": enemy_hand,
        "enemy_resources": enemy_resources,
        "enemy_creatures": enemy_creatures,
        "player_creatures": player_creatures,
        "player_resources": player_resources,
        "player_hand": player_hand,
    }


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
    summoner_width = 0
    center_padding = max(28, self.card_gap * 2)
    if player is not None:
        summoner_width = self.card_height if player.summoner_tapped else self.card_width
        summoner_height = self.card_width if player.summoner_tapped else self.card_height
        summoner_x = start_x + max(0, (available_width - summoner_width) // 2)
        summoner_y = start_y + max(0, (self.card_height - summoner_height) // 2)
        summoner_rect = self.draw_summoner_card(
            player.summoner_key,
            player.life,
            summoner_x,
            summoner_y,
            player.summoner_tapped,
            self.get_think_progress(player),
        )
        self.summoner_rects[player.player_id] = summoner_rect.copy()
        if self.last_preview_builder is not None:
            self.preview_targets.append((summoner_rect.copy(), self.last_preview_builder))
        if target_key == "player_resources":
            self.click_targets["player_summoner"].append((summoner_rect.copy(), player.player_id))
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
        if (
            target_key == "player_resources"
            and player is not None
            and player.player_id == self.engine.human_player.player_id
            and self.engine.pending_recycle_payment is not None
            and resource.resource_id is not None
        ):
            selected = resource.resource_id in self.engine.pending_recycle_payment.selected_resource_ids
            badge_rect = pygame.Rect(rect.x + 6, rect.y + 6, 28, 28)
            pygame.draw.circle(self.screen, HIGHLIGHT if selected else (18, 18, 20), badge_rect.center, 14)
            pygame.draw.circle(self.screen, CARD_BORDER, badge_rect.center, 12, 2)
            self.blit_centered_text(self.small_font, str(index + 1), TEXT_COLOR, badge_rect)
            if selected:
                pygame.draw.rect(self.screen, HIGHLIGHT, rect, 3, border_radius=8)
            self.click_targets[target_key].append((rect, resource.resource_id))
        if self.last_preview_builder is not None:
            self.preview_targets.append((rect, self.last_preview_builder))


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
            if target_key == "player_creatures" and creature.unit_id in self.engine.selected_attackers:
                selected = True
            if target_key == "player_creatures" and creature.unit_id in self.engine.blocker_to_attackers:
                selected = True
            if target_key == "player_creatures" and creature.unit_id == self.engine.selected_blocker_id:
                selected = True
            if target_key == "enemy_creatures" and creature.unit_id == self.engine.selected_attack_target_id:
                selected = True
            if self.engine.pending_order is not None and creature.unit_id in self.engine.pending_order.chosen_order:
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
        if self.last_preview_builder is not None:
            self.preview_targets.append((rect, self.last_preview_builder))
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
        if interactive or self.show_enemy_hand_cards:
            rect = self.draw_hand_card(card, x, start_y, interactive and card.instance_id in self.engine.selected_hand_ids)
        else:
            rect = self.draw_hidden_hand_card(card, x, start_y)
        if self.last_preview_builder is not None:
            self.preview_targets.append((rect, self.last_preview_builder))
        if interactive:
            self.click_targets["hand"].append((rect, card.instance_id))


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
    max_offset = max(0, content_height - viewport.height)
    self.log_scroll_offset = max_offset
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
        button_rect = pygame.Rect(
            start_x,
            start_y + index * (height + gap),
            width,
            height,
        )
        pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
        self.blit_centered_text(self.font, spec.label, TEXT_COLOR, button_rect)
        self.buttons.append((button_rect, spec))

    ui_total_height = len(ui_specs) * height + max(0, len(ui_specs) - 1) * gap
    ui_start_y = rect.bottom - ui_total_height - 12
    for index, spec in enumerate(ui_specs):
        button_rect = pygame.Rect(
            start_x,
            ui_start_y + index * (height + gap),
            width,
            height,
        )
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
        life_badge_rect = pygame.Rect(deck_rect.centerx - 23, deck_rect.y + int(card_height * 0.31) - 23, 46, 46)
        deck_badge_rect = pygame.Rect(deck_rect.centerx - 23, deck_rect.y + int(card_height * 0.69) - 23, 46, 46)
        self.draw_card_badge(self.screen, life_badge_rect, str(player.life), self.font)
        self.draw_card_badge(self.screen, deck_badge_rect, str(len(player.deck)), self.font)
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
