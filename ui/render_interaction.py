from __future__ import annotations

import pygame

from core.models import PHASE_BUILDER_ABILITY
from ui.style import ATTACK_HIGHLIGHT, RESOURCE_COLOR, ZONE_HAND


RESOURCE_BACKGROUND_SEGMENTS = 10


def get_resource_background_segment_rects(
    width: int,
    height: int,
    *,
    segment_count: int = RESOURCE_BACKGROUND_SEGMENTS,
) -> list[pygame.Rect]:
    if width <= 0 or height <= 0 or segment_count <= 0:
        return []
    horizontal_margin = min(12, max(4, width // 80))
    vertical_margin = min(10, max(4, height // 40))
    inner_width = max(0, width - horizontal_margin * 2)
    inner_height = max(0, height - vertical_margin * 2)
    gap = min(8, max(3, width // 260))
    rects: list[pygame.Rect] = []
    for index in range(segment_count):
        column_left = horizontal_margin + round(inner_width * index / segment_count)
        column_right = horizontal_margin + round(inner_width * (index + 1) / segment_count)
        rects.append(
            pygame.Rect(
                column_left + gap // 2,
                vertical_margin,
                max(1, column_right - column_left - gap),
                inner_height,
            )
        )
    return rects


def _get_scaled_resource_segment_image(
    self,
    index: int,
    width: int,
    height: int,
) -> pygame.Surface | None:
    images = getattr(self, "resource_segment_images", ())
    if index >= len(images) or images[index] is None or width <= 0 or height <= 0:
        return None
    cache = getattr(self, "resource_background_scaled_images", None)
    if cache is None:
        cache = {}
        self.resource_background_scaled_images = cache
    cache_key = (index, width, height)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    source = images[index]
    source_width, source_height = source.get_size()
    scale = max(width / max(1, source_width), height / max(1, source_height))
    scaled_size = (
        max(width, round(source_width * scale)),
        max(height, round(source_height * scale)),
    )
    scaled = pygame.transform.smoothscale(source, scaled_size)
    result = pygame.Surface((width, height), pygame.SRCALPHA)
    source_rect = pygame.Rect(
        max(0, (scaled.get_width() - width) // 2),
        max(0, (scaled.get_height() - height) // 2),
        width,
        height,
    )
    result.blit(scaled, (0, 0), source_rect)
    cache[cache_key] = result
    return result


def _draw_resource_progress_background(self, zone_surface: pygame.Surface, zone_key: str) -> None:
    if not zone_key.endswith("creatures"):
        return
    player = self.engine.player_two if zone_key.startswith("player_2_") else self.engine.player_one
    resource_count = min(RESOURCE_BACKGROUND_SEGMENTS, max(0, player.total_resources()))

    overlay = pygame.Surface(zone_surface.get_size(), pygame.SRCALPHA)
    lit_color = tuple(min(255, channel + 54) for channel in RESOURCE_COLOR)
    for index, segment_rect in enumerate(
        get_resource_background_segment_rects(zone_surface.get_width(), zone_surface.get_height())
    ):
        is_lit = index < resource_count
        if is_lit:
            image = _get_scaled_resource_segment_image(
                self,
                index,
                segment_rect.width,
                segment_rect.height,
            )
            if image is not None:
                overlay.blit(image, segment_rect.topleft)
            else:
                pygame.draw.rect(overlay, (*lit_color, 22), segment_rect, border_radius=5)
                pygame.draw.rect(overlay, (*lit_color, 35), segment_rect, 1, border_radius=5)
        else:
            pygame.draw.rect(
                overlay,
                (230, 236, 244, 3),
                segment_rect,
                border_radius=5,
            )
            pygame.draw.rect(overlay, (230, 236, 244, 11), segment_rect, 1, border_radius=5)
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
