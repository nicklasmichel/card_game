from __future__ import annotations

import math
from typing import List

import pygame

from models import Ability, CardTemplate, Element, PHASE_RESOURCE, PHASE_SUMMONING
from ui.style import (
    ATTACK_HIGHLIGHT,
    CARD_BADGE_DARK,
    CARD_BADGE_LIGHT,
    CARD_BORDER,
    CARD_COLOR,
    CARD_FRAME_GOLD,
    CARD_HEADER,
    CARD_RULEBOX,
    CARD_SHADOW,
    CARD_TEXT_DARK,
    CARD_TYPE_BAR,
    ENEMY_CARD_COLOR,
    HIGHLIGHT,
    PLAYER_CARD_COLOR,
    RESOURCE_COLOR,
    SECTION_COLOR,
    ZONE_HAND,
)


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


def draw_hand_card(self, card, x: int, y: int, selected: bool, note: str = "") -> pygame.Rect:
    line_one, line_two = self.get_card_ability_lines(card.template)
    surface = self.build_card_surface(
        template_id=card.template.template_id,
        title=card.template.name,
        cost=card.template.cost,
        stats=f"{card.template.aw}/{card.template.vw}",
        defense_text=f"{card.template.vw}/{card.template.vw}",
        element=card.template.element,
        type_line=self.get_creature_type_line(card.template),
        line_one=line_one,
        line_two=note or line_two,
        accent_color=(186, 177, 154),
        frame_color=CARD_FRAME_GOLD,
        tapped=False,
        selected=selected,
    )
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
    if not self.drag_active or self.dragged_hand_card_id is None or self.drag_current_pos is None:
        return
    card = next(
        (existing for existing in self.engine.human_player.hand if existing.instance_id == self.dragged_hand_card_id),
        None,
    )
    if card is None:
        return
    x = self.drag_current_pos[0] - self.card_width // 2
    y = self.drag_current_pos[1] - self.card_height // 2
    self.draw_hand_card(card, x, y, selected=True)


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
    think_progress: float | None = None,
) -> pygame.Rect:
    rect = pygame.Rect(x, y, self.card_width, self.card_height)
    image = self.summoner_images.get(summoner_key)
    if image is None:
        pygame.draw.rect(self.screen, CARD_COLOR, rect, border_radius=9)
        self.draw_summoner_life_circle(life, x, y, think_progress)
        self.last_rendered_card_surface = self.screen.subsurface(rect).copy()
        self.last_preview_builder = lambda summoner_key=summoner_key, life=life, think_progress=think_progress: self.build_preview_summoner_surface(summoner_key, life, think_progress)
        return rect
    scaled = pygame.transform.smoothscale(image, (self.card_width, self.card_height))
    clipped = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
    pygame.draw.rect(clipped, (255, 255, 255), pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
    scaled.blit(clipped, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    self.screen.blit(scaled, rect.topleft)
    self.draw_summoner_life_circle(life, x, y, think_progress)
    self.last_rendered_card_surface = self.screen.subsurface(rect).copy()
    self.last_preview_builder = lambda summoner_key=summoner_key, life=life, think_progress=think_progress: self.build_preview_summoner_surface(summoner_key, life, think_progress)
    return rect


def draw_summoner_life_circle(self, life: int, x: int, y: int, think_progress: float | None) -> None:
    scale = getattr(self, "layout_scale", 1.0)
    center = (x + self.card_width // 2, y + int(self.card_height * 0.72))
    radius = max(12, int(24 * scale))
    circle_rect = pygame.Rect(center[0] - radius, center[1] - radius, radius * 2, radius * 2)
    ring_radius = max(8, radius - max(1, int(2 * scale)))
    ring_width = max(2, int(4 * scale))
    pygame.draw.circle(self.screen, (18, 18, 20), center, radius)
    pygame.draw.circle(self.screen, (0, 0, 0), center, ring_radius, ring_width)
    if think_progress is not None and think_progress > 0:
        steps = max(8, int(96 * think_progress))
        start_angle = -0.5 * math.pi
        end_angle = start_angle + (2 * math.pi * think_progress)
        points = []
        for step in range(steps + 1):
            angle = start_angle + (end_angle - start_angle) * (step / steps)
            px = center[0] + math.cos(angle) * ring_radius
            py = center[1] + math.sin(angle) * ring_radius
            points.append((round(px), round(py)))
        if len(points) >= 2:
            pygame.draw.lines(self.screen, (212, 170, 74), False, points, ring_width)
        for point in points:
            pygame.draw.circle(self.screen, (212, 170, 74), point, ring_width // 2)
    self.blit_centered_text(self.small_font, str(life), (255, 255, 255), circle_rect)


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
        tapped=creature.tapped,
        selected=selected,
        attacking=attacking,
    )
    width = self.card_height if creature.tapped else self.card_width
    height = self.card_width if creature.tapped else self.card_height
    rect = pygame.Rect(x, y, width, height)
    self.last_rendered_card_surface = surface
    self.last_preview_builder = lambda creature=creature, is_human=is_human, extra_line=extra_line, attacking=attacking: self.build_preview_creature_surface(creature, is_human, extra_line, attacking)
    self.screen.blit(surface, rect.topleft)
    return rect


def build_card_surface(
    self,
    template_id: str | None,
    title: str,
    cost: int,
    stats: str,
    defense_text: str | None,
    element: Element,
    type_line: str,
    line_one: str,
    line_two: str,
    accent_color,
    frame_color,
    tapped: bool,
    selected: bool,
    attacking: bool = False,
) -> pygame.Surface:
    s = lambda value: max(1, int(round(value * getattr(self, "layout_scale", 1.0))))
    if template_id is not None and template_id in getattr(self, "creature_art_images", {}):
        return build_full_art_card_surface(
            self,
            template_id,
            title,
            cost,
            stats,
            defense_text,
            element,
            line_one,
            line_two,
            tapped,
            selected,
            attacking,
        )

    base = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)

    outer_rect = pygame.Rect(0, 0, self.card_width, self.card_height)
    header_y = max(s(4), int(self.card_height * 0.02))
    header_rect = pygame.Rect(s(7), header_y, self.card_width - s(14), s(24))
    art_top = header_rect.bottom + s(1)
    art_rect = pygame.Rect(s(9), art_top, self.card_width - s(18), int(self.card_height * 0.41))
    text_rect = pygame.Rect(s(9), art_rect.bottom + s(8), self.card_width - s(18), s(22))
    pygame.draw.rect(base, CARD_COLOR, outer_rect, border_radius=s(9))
    pygame.draw.rect(base, accent_color, art_rect, border_radius=s(4))

    self.draw_art_panel(base, art_rect, accent_color)

    aw_text, vw_text = stats.split("/", maxsplit=1)
    shield_text = defense_text or vw_text
    element_icon_size = max(s(22), int(self.card_width * 0.13))
    element_icon_rect = pygame.Rect(
        self.card_width - s(8) - element_icon_size,
        header_y + s(1),
        element_icon_size,
        element_icon_size,
    )
    cost_text = str(cost)
    cost_width = self.small_font.size(cost_text)[0]
    cost_x = element_icon_rect.x - cost_width - s(2)
    title_text = self.fit_text(self.small_font, title, max(s(24), cost_x - s(12)))
    self.blit_text_to_surface(base, self.small_font, title_text, CARD_TEXT_DARK, s(10), header_y + s(5))
    self.blit_text_to_surface(base, self.small_font, cost_text, CARD_TEXT_DARK, cost_x, header_y + s(5))
    self.blit_symbol_image(base, get_element_symbol_key(element), element_icon_rect)
    if line_one:
        self.blit_text_to_surface(base, self.small_font, self.fit_text(self.small_font, line_one, self.card_width - s(28)), CARD_TEXT_DARK, s(12), text_rect.y + s(3))
    if line_two:
        self.blit_text_to_surface(base, self.small_font, self.fit_text(self.small_font, line_two, self.card_width - s(28)), CARD_TEXT_DARK, s(12), self.card_height - s(42))
    footer_y = self.card_height - s(14)
    aw_x = s(12)
    shield_width = self.small_font.size(shield_text)[0]
    shield_icon_size = s(22)
    shield_x = self.card_width - s(6) - shield_width - shield_icon_size
    self.blit_text_to_surface(base, self.small_font, aw_text, CARD_TEXT_DARK, aw_x, self.card_height - s(24))
    self.blit_text_to_surface(base, self.small_font, shield_text, CARD_TEXT_DARK, shield_x, self.card_height - s(24))
    aw_width = self.small_font.size(aw_text)[0]
    self.blit_symbol_image(base, "sword_symbol", pygame.Rect(aw_x + aw_width - s(1), footer_y - s(12), s(22), s(22)))
    self.blit_symbol_image(base, "shield_symbol", pygame.Rect(self.card_width - s(6) - shield_icon_size, footer_y - s(14), shield_icon_size, shield_icon_size))

    if selected:
        pygame.draw.rect(base, HIGHLIGHT, pygame.Rect(0, 0, self.card_width, self.card_height), max(1, s(3)), border_radius=s(8))

    if tapped:
        return pygame.transform.rotate(base, -90)
    return base


def build_full_art_card_surface(
    self,
    template_id: str,
    title: str,
    cost: int,
    stats: str,
    defense_text: str | None,
    element: Element,
    line_one: str,
    line_two: str,
    tapped: bool,
    selected: bool,
    attacking: bool,
) -> pygame.Surface:
    s = lambda value: max(1, int(round(value * getattr(self, "layout_scale", 1.0))))
    base = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
    image = self.creature_art_images.get(template_id)
    if image is None:
        return build_card_surface(
            self,
            None,
            title,
            cost,
            stats,
            defense_text,
            element,
            "",
            line_one,
            line_two,
            (186, 177, 154),
            CARD_FRAME_GOLD,
            tapped,
            selected,
            attacking,
        )

    scaled = pygame.transform.smoothscale(image, (self.card_width, self.card_height))
    clipped = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
    pygame.draw.rect(clipped, (255, 255, 255), pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
    scaled.blit(clipped, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    base.blit(scaled, (0, 0))

    overlay = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
    pygame.draw.rect(overlay, (0, 0, 0, 52), pygame.Rect(0, 0, self.card_width, s(30)), border_radius=s(9))
    pygame.draw.rect(overlay, (0, 0, 0, 70), pygame.Rect(0, self.card_height - s(56), self.card_width, s(56)), border_radius=s(9))
    base.blit(overlay, (0, 0))

    aw_text, vw_text = stats.split("/", maxsplit=1)
    shield_text = defense_text or vw_text
    element_icon_size = max(s(22), int(self.card_width * 0.13))
    header_y = max(s(4), int(self.card_height * 0.02))
    element_icon_rect = pygame.Rect(self.card_width - s(8) - element_icon_size, header_y + s(1), element_icon_size, element_icon_size)
    cost_text = str(cost)
    cost_width = self.small_font.size(cost_text)[0]
    cost_x = element_icon_rect.x - cost_width - s(2)
    title_text = self.fit_text(self.small_font, title, max(s(24), cost_x - s(12)))
    blit_text_with_shadow(base, self.small_font, title_text, (255, 255, 255), s(10), header_y + s(5))
    blit_text_with_shadow(base, self.small_font, cost_text, (255, 255, 255), cost_x, header_y + s(5))
    self.blit_symbol_image(base, get_element_symbol_key(element), element_icon_rect)

    if line_one:
        blit_text_with_shadow(base, self.small_font, self.fit_text(self.small_font, line_one, self.card_width - s(20)), (255, 255, 255), s(10), self.card_height - s(54))
    if line_two:
        blit_text_with_shadow(base, self.small_font, self.fit_text(self.small_font, line_two, self.card_width - s(20)), (255, 255, 255), s(10), self.card_height - s(40))

    footer_y = self.card_height - s(14)
    aw_x = s(10)
    shield_width = self.small_font.size(shield_text)[0]
    shield_icon_size = s(22)
    shield_x = self.card_width - s(6) - shield_width - shield_icon_size
    blit_text_with_shadow(base, self.small_font, aw_text, (255, 255, 255), aw_x, self.card_height - s(24))
    blit_text_with_shadow(base, self.small_font, shield_text, (255, 255, 255), shield_x, self.card_height - s(24))
    aw_width = self.small_font.size(aw_text)[0]
    self.blit_symbol_image(base, "sword_symbol", pygame.Rect(aw_x + aw_width - s(1), footer_y - s(12), s(22), s(22)))
    self.blit_symbol_image(base, "shield_symbol", pygame.Rect(self.card_width - s(6) - shield_icon_size, footer_y - s(14), shield_icon_size, shield_icon_size))

    if selected:
        pygame.draw.rect(base, HIGHLIGHT, pygame.Rect(0, 0, self.card_width, self.card_height), max(1, s(3)), border_radius=s(8))
    if tapped:
        return pygame.transform.rotate(base, -90)
    return base


def blit_text_with_shadow(surface: pygame.Surface, font: pygame.font.Font, text: str, color, x: int, y: int) -> None:
    shadow = font.render(text, True, (0, 0, 0))
    surface.blit(shadow, (x + 1, y + 1))
    surface.blit(font.render(text, True, color), (x, y))


def blit_symbol_image(self, surface: pygame.Surface, symbol_key: str, rect: pygame.Rect) -> None:
    image = getattr(self, "ui_symbol_images", {}).get(symbol_key)
    if image is None:
        return
    scaled = pygame.transform.smoothscale(image, (rect.width, rect.height))
    surface.blit(scaled, rect.topleft)


def get_element_symbol_key(element: Element) -> str:
    return {
        Element.FIRE: "fire_symbol",
        Element.WATER: "water_symbol",
        Element.EARTH: "earth_symbol",
        Element.AIR: "air_symbol",
    }[element]


def get_creature_type_line(self, template: CardTemplate) -> str:
    return f"Kreatur - {template.element.value}"


def get_card_ability_lines(self, template: CardTemplate) -> tuple[str, str]:
    names = self.get_ability_names(template.abilities)
    if not names:
        return "", ""
    return ", ".join(names), ""


def get_card_ability_lines_from_creature(self, creature) -> tuple[str, str]:
    names = self.get_ability_names(creature.abilities)
    if not names:
        return "", ""
    return ", ".join(names), ""


def get_ability_names(self, abilities) -> List[str]:
    order = [
        Ability.IGNITE,
        Ability.TRAMPLE,
        Ability.HASTE,
        Ability.VIGILANCE,
        Ability.DEFENDER,
        Ability.STEADFAST,
        Ability.REGENERATION,
        Ability.ADAPTATION,
    ]
    return [ability.value for ability in order if ability in abilities]


def blit_text_to_surface(self, surface: pygame.Surface, font: pygame.font.Font, text: str, color, x: int, y: int) -> None:
    surface.blit(font.render(text, True, color), (x, y))


def blit_centered_text_to_surface(
    self,
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    color,
    rect: pygame.Rect,
) -> None:
    text_surface = font.render(text, True, color)
    surface.blit(text_surface, text_surface.get_rect(center=rect.center))


def fit_text(self, font: pygame.font.Font, text: str, max_width: int) -> str:
    if font.size(text)[0] <= max_width:
        return text
    shortened = text
    while shortened and font.size(shortened + "...")[0] > max_width:
        shortened = shortened[:-1]
    return shortened + "..." if shortened else text[:1]


def draw_art_panel(self, surface: pygame.Surface, rect: pygame.Rect, accent_color) -> None:
    art_top = tuple(min(255, channel + 38) for channel in accent_color)
    art_bottom = tuple(max(0, channel - 28) for channel in accent_color)
    for offset in range(rect.height):
        ratio = offset / max(1, rect.height - 1)
        color = tuple(
            int(art_top[index] * (1 - ratio) + art_bottom[index] * ratio)
            for index in range(3)
        )
        pygame.draw.line(surface, color, (rect.x, rect.y + offset), (rect.right - 1, rect.y + offset))
    pygame.draw.rect(surface, CARD_BORDER, rect, 1, border_radius=4)
    symbol_rect = pygame.Rect(rect.x + 20, rect.y + 10, rect.width - 40, rect.height - 20)
    pygame.draw.ellipse(surface, CARD_BADGE_LIGHT, symbol_rect, 2)
    pygame.draw.line(surface, CARD_BADGE_LIGHT, (symbol_rect.x + 8, symbol_rect.bottom - 8), (symbol_rect.centerx, symbol_rect.y + 8), 2)
    pygame.draw.line(surface, CARD_BADGE_LIGHT, (symbol_rect.centerx, symbol_rect.y + 8), (symbol_rect.right - 8, symbol_rect.bottom - 8), 2)


def build_resource_back_surface(self, element: Element, tapped: bool) -> pygame.Surface:
    key_map = {
        Element.FIRE: "fire",
        Element.WATER: "water",
        Element.EARTH: "earth",
        Element.AIR: "air",
    }
    image_key = key_map[element]
    source_image = self.resource_back_images.get(image_key)
    if source_image is not None:
        framed = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
        shadow_rect = pygame.Rect(4, 5, self.card_width - 6, self.card_height - 6)
        pygame.draw.rect(framed, CARD_SHADOW, shadow_rect, border_radius=9)
        image_surface = pygame.transform.smoothscale(source_image, (self.card_width, self.card_height))
        clipped = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
        pygame.draw.rect(clipped, (255, 255, 255), pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
        image_surface.blit(clipped, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        framed.blit(image_surface, (0, 0))
        pygame.draw.rect(framed, CARD_BORDER, pygame.Rect(0, 0, self.card_width, self.card_height), 2, border_radius=9)
        if tapped:
            return pygame.transform.rotate(framed, -90)
        return framed

    accent_color = self.get_element_color(element)
    base = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
    shadow_rect = pygame.Rect(4, 5, self.card_width - 6, self.card_height - 6)
    pygame.draw.rect(base, CARD_SHADOW, shadow_rect, border_radius=9)

    outer_rect = pygame.Rect(0, 0, self.card_width, self.card_height)
    inner_rect = pygame.Rect(4, 4, self.card_width - 8, self.card_height - 8)
    symbol_rect = pygame.Rect(16, 22, self.card_width - 32, self.card_height - 64)
    footer_rect = pygame.Rect(16, self.card_height - 34, self.card_width - 32, 18)

    pygame.draw.rect(base, accent_color, outer_rect, border_radius=9)
    pygame.draw.rect(base, CARD_BORDER, outer_rect, 2, border_radius=9)
    self.draw_resource_backdrop(base, inner_rect, element, accent_color)
    self.draw_element_symbol(base, symbol_rect, element)
    pygame.draw.rect(base, (255, 255, 255, 36), footer_rect, border_radius=5)
    pygame.draw.rect(base, CARD_BADGE_LIGHT, footer_rect, 1, border_radius=5)
    self.blit_centered_text_to_surface(base, self.small_font, element.value, CARD_BADGE_LIGHT, footer_rect)

    if tapped:
        return pygame.transform.rotate(base, -90)
    return base


def draw_resource_backdrop(self, surface: pygame.Surface, rect: pygame.Rect, element: Element, accent_color) -> None:
    top_color = tuple(min(255, channel + 34) for channel in accent_color)
    bottom_color = tuple(max(0, channel - 36) for channel in accent_color)
    for offset in range(rect.height):
        ratio = offset / max(1, rect.height - 1)
        color = tuple(
            int(top_color[index] * (1 - ratio) + bottom_color[index] * ratio)
            for index in range(3)
        )
        pygame.draw.line(surface, color, (rect.x, rect.y + offset), (rect.right - 1, rect.y + offset))

    overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    if element == Element.FIRE:
        ember_color = (255, 230, 180, 46)
        for x_offset, y_offset, radius in (
            (22, 22, 10),
            (rect.width - 36, 38, 8),
            (40, rect.height - 62, 12),
            (rect.width - 52, rect.height - 84, 9),
        ):
            pygame.draw.circle(overlay, ember_color, (x_offset, y_offset), radius)
    elif element == Element.WATER:
        wave_color = (255, 255, 255, 42)
        for y_offset in (28, 58, 88, 118):
            pygame.draw.arc(overlay, wave_color, pygame.Rect(16, y_offset, rect.width - 32, 24), 0.1, 3.04, 3)
    elif element == Element.EARTH:
        ridge_color = (255, 255, 255, 28)
        bands = (
            [(18, rect.height - 40), (60, rect.height - 78), (100, rect.height - 40)],
            [(70, rect.height - 34), (118, rect.height - 94), (rect.width - 18, rect.height - 34)],
        )
        for band in bands:
            pygame.draw.polygon(overlay, ridge_color, band)
    elif element == Element.AIR:
        cloud_color = (255, 255, 255, 34)
        for arc_rect in (
            pygame.Rect(22, 34, rect.width - 44, 30),
            pygame.Rect(34, 72, rect.width - 68, 26),
            pygame.Rect(18, 108, rect.width - 36, 30),
        ):
            pygame.draw.arc(overlay, cloud_color, arc_rect, 0.2, 3.0, 3)

    surface.blit(overlay, rect.topleft)
    pygame.draw.rect(surface, (255, 255, 255, 18), rect, 1, border_radius=7)


def draw_element_symbol(self, surface: pygame.Surface, rect: pygame.Rect, element: Element) -> None:
    center = rect.center
    width = rect.width
    height = rect.height
    symbol_color = CARD_BADGE_LIGHT
    line_width = 4

    if element == Element.FIRE:
        flame_points = [
            (center[0], rect.y + 18),
            (center[0] - width // 8, center[1] - height // 7),
            (center[0] - width // 5, center[1] - 2),
            (center[0] - width // 4, center[1] + height // 7),
            (center[0] - width // 10, rect.bottom - 24),
            (center[0], rect.bottom - 14),
            (center[0] + width // 8, rect.bottom - 26),
            (center[0] + width // 5, center[1] + height // 10),
            (center[0] + width // 8, center[1] - height // 9),
        ]
        inner_flame = [
            (center[0], center[1] - height // 8),
            (center[0] - width // 12, center[1] + 4),
            (center[0] - width // 16, center[1] + height // 7),
            (center[0], rect.bottom - 34),
            (center[0] + width // 14, center[1] + height // 10),
            (center[0] + width // 13, center[1] - 2),
        ]
        pygame.draw.polygon(surface, symbol_color, flame_points)
        pygame.draw.polygon(surface, CARD_BORDER, flame_points, line_width)
        pygame.draw.polygon(surface, accent_light(symbol_color), inner_flame)
        pygame.draw.polygon(surface, CARD_BORDER, inner_flame, 2)
    elif element == Element.WATER:
        drop_points = [
            (center[0], rect.y + 14),
            (center[0] - width // 5, center[1] - height // 10),
            (center[0] - width // 4, center[1] + height // 8),
            (center[0] - width // 10, rect.bottom - 22),
            (center[0], rect.bottom - 14),
            (center[0] + width // 10, rect.bottom - 22),
            (center[0] + width // 4, center[1] + height // 8),
            (center[0] + width // 5, center[1] - height // 10),
        ]
        shine = pygame.Rect(center[0] - width // 7, center[1] - height // 10, width // 8, height // 6)
        pygame.draw.polygon(surface, symbol_color, drop_points)
        pygame.draw.polygon(surface, CARD_BORDER, drop_points, line_width)
        pygame.draw.ellipse(surface, accent_light(symbol_color), shine)
    elif element == Element.EARTH:
        left_mountain = [
            (rect.x + 18, rect.bottom - 24),
            (center[0] - width // 5, center[1] - height // 7),
            (center[0] + width // 16, rect.bottom - 24),
        ]
        right_mountain = [
            (center[0] - width // 18, rect.bottom - 24),
            (center[0] + width // 6, center[1] - height // 4),
            (rect.right - 18, rect.bottom - 24),
        ]
        snow_left = [
            (center[0] - width // 5, center[1] - height // 7),
            (center[0] - width // 6, center[1] - height // 20),
            (center[0] - width // 9, center[1] - height // 10),
            (center[0] - width // 16, center[1] - height // 24),
        ]
        snow_right = [
            (center[0] + width // 6, center[1] - height // 4),
            (center[0] + width // 8, center[1] - height // 7),
            (center[0] + width // 10, center[1] - height // 6),
            (center[0] + width // 18, center[1] - height // 10),
        ]
        ground_y = rect.bottom - 24
        pygame.draw.polygon(surface, symbol_color, left_mountain)
        pygame.draw.polygon(surface, symbol_color, right_mountain)
        pygame.draw.polygon(surface, CARD_BORDER, left_mountain, line_width)
        pygame.draw.polygon(surface, CARD_BORDER, right_mountain, line_width)
        pygame.draw.polygon(surface, accent_light(symbol_color), snow_left)
        pygame.draw.polygon(surface, accent_light(symbol_color), snow_right)
        pygame.draw.line(surface, CARD_BORDER, (rect.x + 16, ground_y), (rect.right - 16, ground_y), 3)
    elif element == Element.AIR:
        cloud_parts = [
            pygame.Rect(center[0] - width // 4, center[1] - 8, width // 3, height // 4),
            pygame.Rect(center[0] - width // 10, center[1] - height // 6, width // 3, height // 3),
            pygame.Rect(center[0] + width // 10, center[1] - 2, width // 4, height // 5),
            pygame.Rect(center[0] - width // 3, center[1] + 2, width // 4, height // 5),
        ]
        base_rect = pygame.Rect(center[0] - width // 3, center[1] + height // 12, (2 * width) // 3, height // 5)
        for part in cloud_parts:
            pygame.draw.ellipse(surface, symbol_color, part)
            pygame.draw.ellipse(surface, CARD_BORDER, part, 2)
        pygame.draw.rect(surface, symbol_color, base_rect, border_radius=10)
        pygame.draw.rect(surface, CARD_BORDER, base_rect, 2, border_radius=10)


def accent_light(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(min(255, channel + 8) for channel in color)


def get_element_color(self, element: Element) -> tuple[int, int, int]:
    if element == Element.FIRE:
        return (255, 110, 64)
    if element == Element.WATER:
        return (72, 170, 255)
    if element == Element.EARTH:
        return (164, 194, 74)
    return (210, 220, 255)


def blit_centered_text(self, font: pygame.font.Font, text: str, color, rect: pygame.Rect) -> None:
    surface = font.render(text, True, color)
    self.screen.blit(surface, surface.get_rect(center=rect.center))


def wrap_text(self, font: pygame.font.Font, text: str, max_width: int) -> List[str]:
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = ""
    for word in words:
        proposal = word if not current else f"{current} {word}"
        if font.size(proposal)[0] <= max_width:
            current = proposal
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def blit_wrapped_text(self, font: pygame.font.Font, text: str, color, rect: pygame.Rect, line_height: int) -> int:
    lines = self.wrap_text(font, text, rect.width)
    y = rect.y
    for line in lines:
        self.blit_text(font, line, color, rect.x, y)
        y += line_height
    return y


def get_target_at_position(self, area: str, position: tuple[int, int]) -> tuple[pygame.Rect, int] | None:
    for rect, item_id in reversed(self.click_targets[area]):
        if rect.collidepoint(position):
            return rect, item_id
    return None


def can_drag_hand_card(self, card_id: int | None = None) -> bool:
    return self.can_drag_hand_card_to_resource() or self.can_drag_hand_card_to_creature(card_id)


def can_drag_hand_card_to_resource(self) -> bool:
    return (
        self.engine.phase == PHASE_RESOURCE
        and self.engine.active_player.is_human
        and not self.engine.active_player.resource_played_this_turn
    )


def can_drop_on_resource_area(self, position: tuple[int, int]) -> bool:
    return self.player_resource_rect.collidepoint(position)


def can_drag_hand_card_to_creature(self, card_id: int | None = None) -> bool:
    if self.engine.phase != PHASE_SUMMONING or not self.engine.active_player.is_human:
        return False
    target_card_id = self.dragged_hand_card_id if card_id is None else card_id
    if target_card_id is None:
        return False
    card = next(
        (existing for existing in self.engine.human_player.hand if existing.instance_id == target_card_id),
        None,
    )
    return card is not None and self.engine.active_player.can_pay(card.template.cost)


def can_drop_on_creature_area(self, position: tuple[int, int]) -> bool:
    return self.player_creature_rect.collidepoint(position)


def clear_drag_state(self) -> None:
    self.dragged_hand_card_id = None
    self.drag_start_pos = None
    self.drag_current_pos = None
    self.drag_active = False
