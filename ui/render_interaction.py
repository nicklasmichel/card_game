from __future__ import annotations

import pygame

from core.models import PHASE_BUILDER_ABILITY
from ui.style import ATTACK_HIGHLIGHT, LIFE_BAR_HEIGHT_RATIO, ZONE_HAND


RESOURCE_BACKGROUND_SEGMENTS = 10
RESOURCE_SEGMENT_TINTS = {
    0: (62, 158, 255),
    1: (255, 76, 104),
}
RESOURCE_LIT_FILL_ALPHA_RANGE = (48, 168)
RESOURCE_LIT_BORDER_ALPHA_RANGE = (92, 224)


def get_resource_background_segment_rects(
    width: int,
    height: int,
    *,
    segment_count: int = RESOURCE_BACKGROUND_SEGMENTS,
    top_reserved_height: int = 0,
    bottom_reserved_height: int = 0,
) -> list[pygame.Rect]:
    if width <= 0 or height <= 0 or segment_count <= 0:
        return []
    horizontal_margin = min(12, max(4, width // 80))
    top_reserved_height = min(height, max(0, int(top_reserved_height)))
    bottom_reserved_height = min(
        max(0, height - top_reserved_height),
        max(0, int(bottom_reserved_height)),
    )
    available_height = max(0, height - top_reserved_height - bottom_reserved_height)
    vertical_margin = min(10, max(4, available_height // 40))
    inner_width = max(0, width - horizontal_margin * 2)
    inner_height = max(0, available_height - vertical_margin * 2)
    gap = min(8, max(3, width // 260))
    rects: list[pygame.Rect] = []
    for index in range(segment_count):
        column_left = horizontal_margin + round(inner_width * index / segment_count)
        column_right = horizontal_margin + round(inner_width * (index + 1) / segment_count)
        rects.append(
            pygame.Rect(
                column_left + gap // 2,
                top_reserved_height + vertical_margin,
                max(1, column_right - column_left - gap),
                inner_height,
            )
        )
    return rects


def get_lit_resource_segment_alphas(
    resource_number: int,
    *,
    segment_count: int = RESOURCE_BACKGROUND_SEGMENTS,
) -> tuple[int, int]:
    if segment_count <= 1:
        progress = 1.0
    else:
        clamped_number = min(segment_count, max(1, int(resource_number)))
        progress = (clamped_number - 1) / (segment_count - 1)

    fill_min, fill_max = RESOURCE_LIT_FILL_ALPHA_RANGE
    border_min, border_max = RESOURCE_LIT_BORDER_ALPHA_RANGE
    return (
        round(fill_min + (fill_max - fill_min) * progress),
        round(border_min + (border_max - border_min) * progress),
    )


def _draw_resource_progress_background(self, zone_surface: pygame.Surface, zone_key: str) -> None:
    if not zone_key.endswith("creatures"):
        return
    player = self.engine.player_two if zone_key.startswith("player_2_") else self.engine.player_one
    resource_count = min(RESOURCE_BACKGROUND_SEGMENTS, max(0, player.total_resources()))
    segment_color = RESOURCE_SEGMENT_TINTS.get(player.player_id, RESOURCE_SEGMENT_TINTS[0])
    life_bar_height = max(1, round(zone_surface.get_height() * LIFE_BAR_HEIGHT_RATIO))
    player_two_zone = zone_key.startswith("player_2_")

    overlay = pygame.Surface(zone_surface.get_size(), pygame.SRCALPHA)
    for index, segment_rect in enumerate(
        get_resource_background_segment_rects(
            zone_surface.get_width(),
            zone_surface.get_height(),
            top_reserved_height=life_bar_height if player_two_zone else 0,
            bottom_reserved_height=0 if player_two_zone else life_bar_height,
        )
    ):
        is_lit = index < resource_count
        if is_lit:
            lit_fill_alpha, lit_border_alpha = get_lit_resource_segment_alphas(index + 1)
            pygame.draw.rect(overlay, (*segment_color, lit_fill_alpha), segment_rect, border_radius=5)
            pygame.draw.rect(overlay, (*segment_color, lit_border_alpha), segment_rect, 1, border_radius=5)
        else:
            pygame.draw.rect(overlay, (*segment_color, 20), segment_rect, border_radius=5)
            pygame.draw.rect(overlay, (*segment_color, 48), segment_rect, 1, border_radius=5)
    zone_surface.blit(overlay, (0, 0))


def draw_playfield_section_box(self, rect: pygame.Rect, zone_key: str) -> None:
    fill_color = self.get_zone_fill_color(zone_key)
    zone_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(zone_surface, fill_color, pygame.Rect(0, 0, rect.width, rect.height), border_radius=5)
    _draw_resource_progress_background(self, zone_surface, zone_key)
    mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), pygame.Rect(0, 0, rect.width, rect.height), border_radius=5)
    zone_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    self.screen.blit(zone_surface, rect.topleft)
    if zone_key == "player_1_creatures" and self.dragged_hand_card_id is not None and self.can_drag_hand_card_to_creature():
        if self.drag_current_pos is not None and self.can_drop_on_creature_area(self.drag_current_pos):
            pygame.draw.rect(self.screen, ATTACK_HIGHLIGHT, rect, 3, border_radius=5)


def get_zone_fill_color(self, zone_key: str) -> tuple[int, int, int, int]:
    if zone_key in {"player_2_hand", "player_1_hand"}:
        return ZONE_HAND

    player = self.engine.player_two if zone_key.startswith("player_2_") else self.engine.player_one
    deck_key = player.summoner_key or "air"
    base_map = {
        "fire": (214, 74, 66),
        "water": (66, 144, 232),
        "earth": (148, 96, 62),
        "air": (228, 236, 248),
    }
    base = base_map.get(deck_key, base_map["air"])
    if zone_key.endswith("creatures"):
        return (base[0], base[1], base[2], 54)

    neutral = ZONE_HAND[:3]
    blended = tuple((neutral[index] + base[index]) // 2 for index in range(3))
    return (blended[0], blended[1], blended[2], 42)


def get_target_at_position(self, area: str, position: tuple[int, int]) -> tuple[pygame.Rect, int] | None:
    for rect, item_id in reversed(self.click_targets[area]):
        if rect.collidepoint(position):
            return rect, item_id
    return None


def can_drag_hand_card(self, card_id: int | None = None) -> bool:
    return self.can_drag_hand_card_to_creature(card_id)


def can_drag_hand_card_to_creature(self, card_id: int | None = None) -> bool:
    target_card_id = self.dragged_hand_card_id if card_id is None else card_id
    if target_card_id is None:
        return False
    if (
        self.engine.phase != PHASE_BUILDER_ABILITY
        or self.engine.active_player.player_id != self.session.local_player_id
    ):
        return False
    card = next(
        (existing for existing in self.engine.human_player.hand if existing.instance_id == target_card_id),
        None,
    )
    return card is not None and self.engine.get_builder_card_ability(card) is not None


def can_drop_on_creature_area(self, position: tuple[int, int]) -> bool:
    return self.player_creature_rect.collidepoint(position)


def clear_drag_state(self) -> None:
    self.dragged_hand_card_id = None
    self.drag_start_pos = None
    self.drag_current_pos = None
    self.drag_grab_offset = None
    self.drag_active = False
    self.dragged_card_surface = None
