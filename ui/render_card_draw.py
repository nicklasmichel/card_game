from __future__ import annotations

import math

import pygame

from core.models import PHASE_REACTION, PHASE_SUMMONING
from ui.render_helpers import blit_text_with_shadow
from ui.style import CARD_BORDER, CARD_COLOR, ENEMY_CARD_COLOR, PLAYER_CARD_COLOR


def draw_hand_card(self, card, x: int, y: int, selected: bool, note: str = "") -> pygame.Rect:
    surface = self.build_hand_card_surface(card, selected, note)
    if any(existing.instance_id == card.instance_id for existing in self.engine.human_player.hand):
        in_priority_window = self.engine.phase in {PHASE_SUMMONING, PHASE_REACTION}
        legal = self.engine.can_play_card(self.engine.active_player if self.engine.phase == PHASE_SUMMONING else self.engine.human_player, card)
        if in_priority_window and not legal:
            dim = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
            pygame.draw.rect(
                dim,
                (18, 18, 22, 120),
                pygame.Rect(0, 0, surface.get_width(), surface.get_height()),
                border_radius=9,
            )
            surface = surface.copy()
            surface.blit(dim, (0, 0))
    rect = pygame.Rect(x, y, self.card_width, self.card_height)
    self.last_rendered_card_surface = surface
    self.last_preview_builder = lambda card=card, note=note: self.build_preview_hand_card_surface(card, note)
    self.screen.blit(surface, rect.topleft)
    return rect


def draw_hidden_hand_card(self, card, x: int, y: int) -> pygame.Rect:
    surface = self.build_resource_back_surface(card.template.element, False)
    rect = pygame.Rect(x, y, self.card_width, self.card_height)
    self.last_rendered_card_surface = surface
    self.last_preview_builder = lambda card=card: self.build_preview_hidden_hand_surface(card)
    self.screen.blit(surface, rect.topleft)
    return rect


def draw_dragged_card(self) -> None:
    if not self.drag_active or self.dragged_hand_card_id is None:
        return
    if self.dragged_card_surface is None:
        card = next((existing for existing in self.engine.human_player.hand if existing.instance_id == self.dragged_hand_card_id), None)
        if card is None:
            return
        self.dragged_card_surface = self.build_hand_card_surface(card, selected=True)
    mouse_x, mouse_y = pygame.mouse.get_pos()
    grab_offset_x, grab_offset_y = self.drag_grab_offset or (self.card_width // 2, self.card_height // 2)
    x = mouse_x - grab_offset_x
    y = mouse_y - grab_offset_y
    self.screen.blit(self.dragged_card_surface, (x, y))


def draw_resource_card(self, resource, x: int, y: int) -> pygame.Rect:
    surface = self.build_resource_back_surface(resource.template.element, resource.tapped)
    width = self.card_height if resource.tapped else self.card_width
    height = self.card_width if resource.tapped else self.card_height
    rect = pygame.Rect(x, y, width, height)
    self.last_rendered_card_surface = surface
    self.last_preview_builder = lambda resource=resource: self.build_preview_resource_surface(resource)
    self.screen.blit(surface, rect.topleft)
    return rect


def draw_summoner_card(
    self,
    summoner_key: str,
    life: int,
    x: int,
    y: int,
    tapped: bool = False,
    think_progress: float | None = None,
) -> pygame.Rect:
    width = self.card_height if tapped else self.card_width
    height = self.card_width if tapped else self.card_height
    rect = pygame.Rect(x, y, width, height)
    surface = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
    image = self.summoner_images.get(summoner_key)
    if image is None:
        pygame.draw.rect(surface, CARD_COLOR, pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
        pygame.draw.rect(surface, CARD_BORDER, pygame.Rect(0, 0, self.card_width, self.card_height), 2, border_radius=9)
    else:
        scaled = pygame.transform.smoothscale(image, (self.card_width, self.card_height))
        clipped = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
        pygame.draw.rect(clipped, (255, 255, 255), pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
        scaled.blit(clipped, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surface.blit(scaled, (0, 0))
        pygame.draw.rect(surface, CARD_BORDER, pygame.Rect(0, 0, self.card_width, self.card_height), 2, border_radius=9)
    self.draw_summoner_footer(surface, life)
    rendered_surface = pygame.transform.rotate(surface, -90) if tapped else surface
    self.screen.blit(rendered_surface, rect.topleft)
    self.last_rendered_card_surface = rendered_surface.copy()
    self.last_preview_builder = lambda summoner_key=summoner_key, life=life, think_progress=think_progress: self.build_preview_summoner_surface(summoner_key, life, think_progress)
    return rect


def draw_summoner_life_circle(self, life: int, x: int, y: int, think_progress: float | None) -> None:
    return


def draw_summoner_footer(self, surface: pygame.Surface, life: int) -> None:
    scale = getattr(self, "layout_scale", 1.0)
    s = lambda value: max(1, int(round(value * scale)))
    card_number_font = pygame.font.SysFont("arial", max(self.small_font.get_height() + s(2), self.small_font.get_height() + 2))
    shield_text = f"{life}/20"
    shield_text_color = (255, 142, 142) if life <= 0 else (255, 255, 255)
    shield_icon_size = s(22)
    shield_width = card_number_font.size(shield_text)[0]
    shield_x = self.card_width - s(6) - shield_width - shield_icon_size
    shield_y = self.card_height - s(25)
    blit_text_with_shadow(surface, card_number_font, shield_text, shield_text_color, shield_x, shield_y)
    self.blit_symbol_image(surface, "shield_symbol", pygame.Rect(self.card_width - s(6) - shield_icon_size, self.card_height - s(26), shield_icon_size, shield_icon_size))


def draw_card_badge(
    self,
    surface: pygame.Surface,
    badge_rect: pygame.Rect,
    text: str,
    font: pygame.font.Font | None = None,
    think_progress: float | None = None,
) -> None:
    pygame.draw.circle(surface, (18, 18, 20), badge_rect.center, badge_rect.width // 2)
    ring_radius = max(4, badge_rect.width // 2 - 4)
    ring_width = max(2, badge_rect.width // 12)
    pygame.draw.circle(surface, (0, 0, 0), badge_rect.center, ring_radius, ring_width)
    if think_progress is not None and think_progress > 0:
        steps = max(8, int(96 * think_progress))
        start_angle = -0.5 * math.pi
        end_angle = start_angle + (2 * math.pi * think_progress)
        points = []
        for step in range(steps + 1):
            angle = start_angle + (end_angle - start_angle) * (step / steps)
            px = badge_rect.centerx + math.cos(angle) * ring_radius
            py = badge_rect.centery + math.sin(angle) * ring_radius
            points.append((round(px), round(py)))
        if len(points) >= 2:
            pygame.draw.lines(surface, (212, 170, 74), False, points, ring_width)
        for point in points:
            pygame.draw.circle(surface, (212, 170, 74), point, max(1, ring_width // 2))
    self.blit_centered_text_to_surface(surface, font or self.font, text, (255, 255, 255), badge_rect)


def draw_creature_card(
    self,
    creature,
    is_human: bool,
    x: int,
    y: int,
    selected: bool,
    extra_line: str = "",
    attacking: bool = False,
) -> pygame.Rect:
    visually_tapped = self.is_creature_visually_tapped(creature)
    accent = PLAYER_CARD_COLOR if is_human else ENEMY_CARD_COLOR
    line_one = ""
    line_two = ""
    if extra_line:
        line_two = extra_line
    ability_line_one, ability_line_two = self.get_card_ability_lines_from_creature(creature)
    if ability_line_one:
        line_one = ability_line_one
    if not extra_line and ability_line_two:
        line_two = ability_line_two
    surface = self.build_card_surface(
        template_id=getattr(creature, "template_id", None),
        title=creature.name,
        cost=creature.cost,
        stats=creature.aw_vw,
        defense_text=f"{creature.current_hp}/{creature.vw}",
        element=creature.element,
        type_line=f"Kreatur - {creature.element.value}",
        line_one=line_one,
        line_two=line_two,
        accent_color=accent,
        frame_color=accent,
        tapped=visually_tapped,
        selected=selected,
        attacking=attacking,
    )
    width = self.card_height if visually_tapped else self.card_width
    height = self.card_width if visually_tapped else self.card_height
    rect = pygame.Rect(x, y, width, height)
    self.last_rendered_card_surface = surface
    self.last_preview_builder = lambda creature=creature, is_human=is_human, extra_line=extra_line, attacking=attacking: self.build_preview_creature_surface(creature, is_human, extra_line, attacking)
    self.screen.blit(surface, rect.topleft)
    return rect
