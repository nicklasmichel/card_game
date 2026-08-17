from __future__ import annotations

from typing import Dict

import pygame

from core.builder_rules import BUILDER_CREATURE_CAP
from core.config import STARTING_LIFE
from core.models import PHASE_BUILDER_CREATURE, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE
from ui.player_labels import get_player_display_name
from ui.render_interaction import get_resource_background_segment_rects
from ui.style import HIGHLIGHT, LIFE_BAR_HEIGHT_RATIO, TEXT_COLOR


def get_life_bar_rect(creatures_rect: pygame.Rect, *, at_top: bool = False) -> pygame.Rect:
    bar_height = max(1, round(creatures_rect.height * LIFE_BAR_HEIGHT_RATIO))
    segment_rects = get_resource_background_segment_rects(creatures_rect.width, creatures_rect.height)
    left_inset = segment_rects[0].left if segment_rects else 0
    right_inset = creatures_rect.width - segment_rects[-1].right if segment_rects else 0
    return pygame.Rect(
        creatures_rect.x + left_inset,
        creatures_rect.y if at_top else creatures_rect.bottom - bar_height,
        max(1, creatures_rect.width - left_inset - right_inset),
        bar_height,
    )


def _life_bar_fill_color(life_ratio: float) -> tuple[int, int, int]:
    clamped = max(0.0, min(1.0, life_ratio))
    if clamped < 0.5:
        progress = clamped / 0.5
        start = (154, 82, 90)
        end = (157, 137, 88)
    else:
        progress = (clamped - 0.5) / 0.5
        start = (157, 137, 88)
        end = (82, 139, 108)
    return tuple(round(start[index] + (end[index] - start[index]) * progress) for index in range(3))


def get_life_bar_labels(player, *, player_name: str | None = None) -> tuple[str, str, str]:
    return (
        player.name if player_name is None else player_name,
        f"Health {player.life} / {STARTING_LIFE}",
        f"Creatures {len(player.battlefield)}/{BUILDER_CREATURE_CAP}",
    )


def draw_life_bar(self, player, creatures_rect: pygame.Rect, *, at_top: bool = False) -> pygame.Rect:
    bar_rect = get_life_bar_rect(creatures_rect, at_top=at_top)
    surface = pygame.Surface(bar_rect.size, pygame.SRCALPHA)

    vertical_padding = max(2, self.scale_ui(4))
    track_rect = pygame.Rect(
        0,
        vertical_padding,
        surface.get_width(),
        max(1, surface.get_height() - vertical_padding * 2),
    )
    pygame.draw.rect(
        surface,
        (132, 142, 156, 38),
        track_rect,
        border_radius=max(1, self.scale_ui(3)),
    )
    max_life = max(1, STARTING_LIFE)
    life_ratio = max(0.0, min(1.0, player.life / max_life))
    fill_width = round(track_rect.width * life_ratio)
    if fill_width > 0:
        fill_rect = pygame.Rect(track_rect.x, track_rect.y, fill_width, track_rect.height)
        pygame.draw.rect(
            surface,
            (*_life_bar_fill_color(life_ratio), 172),
            fill_rect,
            border_radius=max(1, self.scale_ui(3)),
        )

    player_text, health_text, creatures_text = get_life_bar_labels(
        player,
        player_name=get_player_display_name(self, player),
    )
    text_padding = self.scale_ui(10)
    label_specs = (
        (player_text, "left"),
        (health_text, "center"),
        (creatures_text, "right"),
    )
    for label, alignment in label_specs:
        text_surface = self.title_font.render(label, True, TEXT_COLOR)
        if alignment == "left":
            text_rect = text_surface.get_rect(midleft=(text_padding, surface.get_height() // 2))
        elif alignment == "right":
            text_rect = text_surface.get_rect(midright=(surface.get_width() - text_padding, surface.get_height() // 2))
        else:
            text_rect = text_surface.get_rect(center=surface.get_rect().center)
        shadow_surface = self.title_font.render(label, True, (10, 12, 16))
        surface.blit(shadow_surface, (text_rect.x + self.scale_ui(1), text_rect.y + self.scale_ui(1)))
        surface.blit(text_surface, text_rect)
    self.screen.blit(surface, bar_rect.topleft)
    return bar_rect


def draw_enemy_area(self) -> None:
    margin = self.scale_ui(10)
    sections = self.get_playfield_sections()
    creatures_rect = sections["player_2_creatures"]
    life_bar_rect = get_life_bar_rect(creatures_rect, at_top=True)
    content_rect = creatures_rect.copy()
    content_rect.y += life_bar_rect.height
    content_rect.height -= life_bar_rect.height
    self.draw_playfield_section_box(creatures_rect, "player_2_creatures")
    creature_top = content_rect.y + margin
    creature_bottom = content_rect.bottom - margin
    self.draw_creatures(
        self.engine.ai_player.battlefield,
        False,
        "player_2_creatures",
        creatures_rect.x + margin,
        creature_top,
        creatures_rect.width - margin * 2,
        max(0, creature_bottom - creature_top),
    )
    self.summoner_rects[self.engine.ai_player.player_id] = self.draw_life_bar(
        self.engine.ai_player,
        creatures_rect,
        at_top=True,
    )


def draw_player_area(self) -> None:
    margin = self.scale_ui(10)
    sections = self.get_playfield_sections()
    creatures_rect = sections["player_1_creatures"]
    life_bar_rect = get_life_bar_rect(creatures_rect)
    content_rect = creatures_rect.copy()
    content_rect.height -= life_bar_rect.height
    self.player_creature_rect = content_rect.copy()
    self.player_resource_rect = pygame.Rect(0, 0, 0, 0)
    self.draw_playfield_section_box(creatures_rect, "player_1_creatures")
    display_creatures = list(self.engine.human_player.battlefield)
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        preview_creature = self.engine.get_builder_preview_creature(self.engine.human_player)
        if preview_creature is not None:
            display_creatures.append(preview_creature)
    creature_top = content_rect.y + margin
    creature_bottom = content_rect.bottom - margin
    self.draw_creatures(
        display_creatures,
        True,
        "player_1_creatures",
        creatures_rect.x + margin,
        creature_top,
        creatures_rect.width - margin * 2,
        max(0, creature_bottom - creature_top),
    )
    self.summoner_rects[self.engine.human_player.player_id] = self.draw_life_bar(self.engine.human_player, creatures_rect)


def combat_formation_active(self) -> bool:
    return self.engine.phase in {PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE} and bool(
        self.engine.selected_attackers or self.engine.block_assignments
    )


def get_visible_combat_creature_ids(self, creatures, target_key: str) -> set[int]:
    all_ids = {creature.unit_id for creature in creatures}
    if not self.combat_formation_active():
        return all_ids

    player = self.engine.human_player if target_key == "player_1_creatures" else self.engine.ai_player
    if player.player_id == self.engine.active_player.player_id:
        return all_ids.intersection(self.engine.selected_attackers or self.engine.block_assignments.keys())

    # Defenders must remain visible and clickable until block selection is confirmed.
    if self.engine.phase == PHASE_DECLARE_BLOCKERS:
        return all_ids
    blocker_ids = {blocker_id for blocker_id in self.engine.block_assignments.values() if blocker_id is not None}
    return all_ids.intersection(blocker_ids)


def get_combat_formation_positions(
    self, creatures, target_key: str, start_x: int, start_y: int, lane_width: int, lane_height: int
) -> Dict[int, pygame.Rect]:
    """Keep attackers in place and align assigned blockers with them."""
    if not self.combat_formation_active():
        return {}

    attacker_ids = list(self.engine.selected_attackers or self.engine.block_assignments.keys())
    positions = self.get_creature_screen_positions(
        creatures,
        target_key == "player_1_creatures",
        start_x,
        start_y,
        lane_width,
        lane_height,
    )
    player = self.engine.human_player if target_key == "player_1_creatures" else self.engine.ai_player
    if player.player_id == self.engine.active_player.player_id:
        return positions

    attacker_positions = self.get_creature_screen_positions(
        self.engine.active_player.battlefield,
        self.engine.active_player.player_id == self.engine.human_player.player_id,
        start_x,
        start_y,
        lane_width,
        lane_height,
    )
    creature_by_id = {creature.unit_id: creature for creature in creatures}
    for attacker_id in attacker_ids:
        blocker_id = self.engine.block_assignments.get(attacker_id)
        blocker_rect = positions.get(blocker_id)
        attacker_rect = attacker_positions.get(attacker_id)
        blocker = creature_by_id.get(blocker_id)
        if blocker_rect is None or attacker_rect is None or blocker is None:
            continue
        positions[blocker_id] = pygame.Rect(
            attacker_rect.centerx - blocker_rect.width // 2,
            blocker_rect.y,
            blocker_rect.width,
            blocker_rect.height,
        )
    return positions


def draw_combat_links(self) -> None:
    if not self.engine.selected_attackers and not self.engine.block_assignments:
        return

    sections = self.get_playfield_sections()
    enemy_rect = sections["player_2_creatures"]
    player_rect = sections["player_1_creatures"]
    margin = self.scale_ui(10)
    enemy_positions = self.get_creature_screen_positions(
        self.engine.ai_player.battlefield,
        False,
        enemy_rect.x + margin,
        enemy_rect.y + margin,
        enemy_rect.width - margin * 2,
        enemy_rect.height - margin * 2,
    )
    player_positions = self.get_creature_screen_positions(
        self.engine.human_player.battlefield,
        True,
        player_rect.x + margin,
        player_rect.y + margin,
        player_rect.width - margin * 2,
        player_rect.height - margin * 2,
    )
    defender_summoner_rect = self.summoner_rects.get(self.engine.defending_player.player_id)
    if defender_summoner_rect is None:
        defender_summoner_rect = self.get_summoner_rect_for_player(self.engine.defending_player)

    attacker_ids = self.engine.selected_attackers or list(self.engine.block_assignments.keys())
    for attacker_id in attacker_ids:
        blocker_id = self.engine.block_assignments.get(attacker_id)
        attacker_rect = self.creature_rects.get(attacker_id) or enemy_positions.get(attacker_id) or player_positions.get(attacker_id)
        if attacker_rect is None:
            continue

        attacker_selected = attacker_id == self.engine.selected_attack_target_id
        if blocker_id is None:
            summoner_color = HIGHLIGHT if attacker_selected else (206, 186, 96)
            start = (
                attacker_rect.centerx,
                attacker_rect.bottom if attacker_rect.centery < defender_summoner_rect.centery else attacker_rect.top,
            )
            attacks_downward = attacker_rect.centery < defender_summoner_rect.centery
            end = (
                max(defender_summoner_rect.left, min(start[0], defender_summoner_rect.right - 1)),
                defender_summoner_rect.top if attacks_downward else defender_summoner_rect.bottom,
            )
            self.draw_direct_attack_marker(start, end, summoner_color, attacker_selected)
            continue
        blocker_rect = self.creature_rects.get(blocker_id) or player_positions.get(blocker_id) or enemy_positions.get(blocker_id)
        if blocker_rect is None:
            continue
        blocker_selected = blocker_id == self.engine.selected_blocker_id
        blocker_color = HIGHLIGHT if attacker_selected or blocker_selected else (102, 188, 112)
        self.draw_combat_pair_marker(
            start=(attacker_rect.centerx, attacker_rect.bottom if attacker_rect.centery < blocker_rect.centery else attacker_rect.top),
            end=(blocker_rect.centerx, blocker_rect.top if blocker_rect.centery > attacker_rect.centery else blocker_rect.bottom),
            color=blocker_color,
            selected=attacker_selected or blocker_selected,
        )


def draw_combat_pair_marker(self, start: tuple[int, int], end: tuple[int, int], color, selected: bool = False) -> None:
    width = self.scale_ui(5 if selected else 3)
    pygame.draw.line(self.screen, color, start, end, width)
    center = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
    radius = self.scale_ui(14 if selected else 12)
    pygame.draw.circle(self.screen, (36, 41, 48), center, radius)
    pygame.draw.circle(self.screen, color, center, radius, self.scale_ui(3))
    blade = max(self.scale_ui(5), radius // 2)
    pygame.draw.line(self.screen, color, (center[0] - blade, center[1] - blade), (center[0] + blade, center[1] + blade), self.scale_ui(2))
    pygame.draw.line(self.screen, color, (center[0] + blade, center[1] - blade), (center[0] - blade, center[1] + blade), self.scale_ui(2))


def draw_direct_attack_marker(self, start: tuple[int, int], end: tuple[int, int], color, selected: bool = False) -> None:
    width = self.scale_ui(5 if selected else 4)
    pygame.draw.line(self.screen, color, start, end, width)
    self.draw_arrowhead(start, end, color, width)


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
    base_column_gap = self.card_gap + self.scale_ui(70)
    column_step = self.card_height + base_column_gap
    columns = max(1, lane_width // column_step)
    row_spacing = self.scale_ui(22)
    total_rows = max(1, (len(creatures) + columns - 1) // columns)
    total_height = total_rows * self.card_height + max(0, total_rows - 1) * row_spacing
    row_top = start_y + max(0, (lane_height - total_height) // 2)
    for row in range((len(creatures) + columns - 1) // columns):
        row_creatures = creatures[row * columns : (row + 1) * columns]
        widths = [self.card_height if self.is_creature_visually_tapped(creature) else self.card_width for creature in row_creatures]
        heights = [self.card_width if self.is_creature_visually_tapped(creature) else self.card_height for creature in row_creatures]
        row_height = self.card_height
        column_gap = self.card_gap + self.scale_ui(
            90 if all(self.is_creature_visually_tapped(creature) for creature in row_creatures) else 24
        )
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
    outer_margin = self.scale_ui(10)
    side_panel_x = self.window_width - self.side_panel_width - outer_margin
    playfield_rect = pygame.Rect(
        outer_margin,
        outer_margin,
        side_panel_x - outer_margin * 2,
        self.window_height - outer_margin * 2,
    )
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


def get_area_status_metrics(self, player) -> dict[str, int]:
    name_text = get_player_display_name(self, player)
    creatures_text = f"Creatures {len(player.battlefield)}/{BUILDER_CREATURE_CAP}"
    line_height = self.title_font.get_height()
    name_font = getattr(self, "player_name_font", self.title_font)
    name_height = name_font.get_height()
    gap = self.scale_ui(4)
    return {
        "name_width": name_font.size(name_text)[0],
        "name_height": name_height,
        "creatures_width": self.title_font.size(creatures_text)[0],
        "line_height": line_height,
        "block_width": max(
            name_font.size(name_text)[0],
            self.title_font.size(creatures_text)[0],
        ),
        "block_height": line_height + name_height + gap,
        "gap": gap,
        "name_text": name_text,
        "creatures_text": creatures_text,
    }


def draw_area_status_block(self, player, rect: pygame.Rect) -> pygame.Rect:
    metrics = get_area_status_metrics(self, player)
    line_height = metrics["line_height"]
    gap = metrics["gap"]
    edge_margin = self.scale_ui(10)
    is_human = player.player_id == self.session.local_player_id
    block_rect = pygame.Rect(
        rect.centerx - metrics["block_width"] // 2,
        rect.bottom - edge_margin - metrics["block_height"] if is_human else rect.y + edge_margin,
        metrics["block_width"],
        metrics["block_height"],
    )
    line_specs = [
        ("creatures_text", metrics["creatures_width"], self.title_font, line_height),
        (
            "name_text",
            metrics["name_width"],
            getattr(self, "player_name_font", self.title_font),
            metrics["name_height"],
        ),
    ]
    if not is_human:
        line_specs = list(reversed(line_specs))

    line_rects: list[tuple[str, pygame.Rect]] = []
    current_y = block_rect.y
    for text_key, text_width, font, text_height in line_specs:
        line_rects.append(
            (
                text_key,
                font,
                pygame.Rect(
                    rect.centerx - text_width // 2,
                    current_y,
                    text_width,
                    text_height,
                ),
            )
        )
        current_y += text_height + gap

    for text_key, font, line_rect in line_rects:
        self.screen.blit(font.render(metrics[text_key], True, TEXT_COLOR), line_rect.topleft)
    return block_rect


def draw_polyline(self, start: tuple[int, int], end: tuple[int, int], color, via_y: int, width: int) -> None:
    points = [start, (start[0], via_y), (end[0], via_y), end]
    pygame.draw.lines(self.screen, color, False, points, width)
    pygame.draw.circle(self.screen, color, end, max(3, width + 1))
    self.draw_arrowhead(points[-2], end, color, width)
    self.draw_link_marker(points[1], color, width)


def draw_arrowhead(self, from_point: tuple[int, int], to_point: tuple[int, int], color, width: int) -> None:
    direction = pygame.Vector2(to_point) - pygame.Vector2(from_point)
    if direction.length_squared() == 0:
        return
    direction = direction.normalize()
    perpendicular = pygame.Vector2(-direction.y, direction.x)
    tip = pygame.Vector2(to_point)
    base = tip - direction * self.scale_ui(11)
    half_width = self.scale_ui(6)
    points = [
        (round(tip.x), round(tip.y)),
        (round(base.x + perpendicular.x * half_width), round(base.y + perpendicular.y * half_width)),
        (round(base.x - perpendicular.x * half_width), round(base.y - perpendicular.y * half_width)),
    ]
    pygame.draw.polygon(self.screen, color, points)


def draw_link_marker(self, center: tuple[int, int], color, width: int) -> None:
    radius = self.scale_ui(4) + width
    pygame.draw.circle(self.screen, color, center, radius, 2)
    pygame.draw.circle(self.screen, color, center, max(self.scale_ui(2), radius - self.scale_ui(4)))


def draw_resources(self, resources, start_x: int, start_y: int, available_width: int, player=None, target_key: str | None = None) -> None:
    summoner_rect = None
    center_padding = max(self.scale_ui(28), self.card_gap * 2)
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
        base_gap = self.card_gap + self.scale_ui(8)
        total_width = sum(widths) + max(0, len(widths) - 1) * base_gap
        if total_width <= zone_available:
            x = zone_start + max(0, (zone_available - total_width) // 2)
            positions = []
            for width in widths:
                positions.append(x)
                x += width + base_gap
            return positions
        step = max(self.scale_ui(40), (zone_available - widths[-1]) // max(1, len(widths) - 1))
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
    formation_positions = self.get_combat_formation_positions(
        creatures, target_key, start_x, start_y, lane_width, lane_height
    )
    if formation_positions:
        visible_ids = self.get_visible_combat_creature_ids(creatures, target_key)
        for creature in creatures:
            if creature.unit_id not in visible_ids:
                continue
            base_rect = formation_positions[creature.unit_id]
            offset_x, offset_y = self.get_creature_animation_offset(creature.unit_id, base_rect)
            selected = creature.unit_id in {
                self.engine.selected_attack_target_id,
                self.engine.selected_blocker_id,
            } or creature.unit_id in self.engine.selected_attackers
            rect = self.draw_creature_card(
                creature,
                is_human,
                base_rect.x + offset_x,
                base_rect.y + offset_y,
                selected,
                "",
                creature.unit_id in self.engine.selected_attackers,
            )
            self.creature_rects[creature.unit_id] = rect.copy()
            if self.last_preview_builder is not None:
                self.preview_targets.append((rect, self.last_preview_builder, self.last_preview_info_builder))
            self.click_targets[target_key].append((rect, creature.unit_id))
        return

    base_column_gap = self.card_gap + self.scale_ui(70)
    column_step = self.card_height + base_column_gap
    columns = max(1, lane_width // column_step)
    row_spacing = self.scale_ui(22)
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
        column_gap = self.card_gap + self.scale_ui(
            90 if all(self.is_creature_visually_tapped(creature) for creature in row_creatures) else 24
        )
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
        card_step = max(self.scale_ui(26), (available_width - self.card_width) // max(1, len(hand) - 1))
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
