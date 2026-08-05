from __future__ import annotations

import pygame

from core.models import CardType, MAIN_PHASES, PHASE_REACTION
from ui.style import ATTACK_HIGHLIGHT, ZONE_HAND


def draw_playfield_section_box(self, rect: pygame.Rect, zone_key: str) -> None:
    fill_color = self.get_zone_fill_color(zone_key)
    zone_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(zone_surface, fill_color, pygame.Rect(0, 0, rect.width, rect.height), border_radius=5)
    mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), pygame.Rect(0, 0, rect.width, rect.height), border_radius=5)
    zone_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    self.screen.blit(zone_surface, rect.topleft)
    if zone_key == "player_resources" and self.dragged_hand_card_id is not None and self.can_drag_hand_card_to_resource():
        if self.drag_current_pos is not None and self.can_drop_on_resource_area(self.drag_current_pos):
            pygame.draw.rect(self.screen, ATTACK_HIGHLIGHT, rect, 3, border_radius=5)
    if zone_key == "player_creatures" and self.dragged_hand_card_id is not None and self.can_drag_hand_card_to_creature():
        if self.drag_current_pos is not None and self.can_drop_on_creature_area(self.drag_current_pos):
            pygame.draw.rect(self.screen, ATTACK_HIGHLIGHT, rect, 3, border_radius=5)


def get_zone_fill_color(self, zone_key: str) -> tuple[int, int, int, int]:
    if zone_key in {"enemy_hand", "player_hand"}:
        return ZONE_HAND

    player = self.engine.ai_player if zone_key.startswith("enemy_") else self.engine.human_player
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
    return self.can_drag_hand_card_to_resource() or self.can_drag_hand_card_to_creature(card_id)


def can_drag_hand_card_to_resource(self) -> bool:
    if (
        self.engine.phase in MAIN_PHASES
        and self.engine.active_player.is_human
        and self.engine.active_player.resources_played_this_turn < 2
        and self.engine.pending_recycle_payment is None
    ):
        return True
    if (
        self.engine.phase not in MAIN_PHASES
        or not self.engine.active_player.is_human
        or self.engine.pending_recycle_payment is not None
        or self.dragged_hand_card_id is None
    ):
        return False
    card = next(
        (existing for existing in self.engine.human_player.hand if existing.instance_id == self.dragged_hand_card_id),
        None,
    )
    return (
        card is not None
        and card.template.card_type in {CardType.RITUAL, CardType.SPELL}
        and self.engine.can_play_card(self.engine.active_player, card)
    )


def can_drop_on_resource_area(self, position: tuple[int, int]) -> bool:
    return self.player_resource_rect.collidepoint(position)


def can_drag_hand_card_to_creature(self, card_id: int | None = None) -> bool:
    if self.engine.pending_recycle_payment is not None:
        return False
    target_card_id = self.dragged_hand_card_id if card_id is None else card_id
    if target_card_id is None:
        return False
    if self.engine.phase in MAIN_PHASES and self.engine.active_player.is_human:
        card = next(
            (existing for existing in self.engine.human_player.hand if existing.instance_id == target_card_id),
            None,
        )
        return (
            card is not None
            and card.template.card_type in {CardType.CREATURE, CardType.RITUAL, CardType.SPELL}
            and self.engine.can_play_card(self.engine.active_player, card)
        )
    if (
        self.engine.phase == PHASE_REACTION
        and self.engine.reaction_priority_player_id == self.engine.human_player.player_id
    ):
        card = next(
            (existing for existing in self.engine.human_player.hand if existing.instance_id == target_card_id),
            None,
        )
        return (
            card is not None
            and card.template.card_type in {CardType.RITUAL, CardType.SPELL}
            and self.engine.can_react_with_card(self.engine.human_player, card)
        )
    return False


def can_drop_on_creature_area(self, position: tuple[int, int]) -> bool:
    return self.player_creature_rect.collidepoint(position)


def clear_drag_state(self) -> None:
    self.dragged_hand_card_id = None
    self.drag_start_pos = None
    self.drag_current_pos = None
    self.drag_grab_offset = None
    self.drag_active = False
    self.dragged_card_surface = None
