from __future__ import annotations

import pygame

from core.models import CardCost, Element
from ui.render_helpers import accent_light, blit_text_with_shadow, get_element_symbol_key
from ui.style import (
    CARD_BADGE_LIGHT,
    CARD_BORDER,
    CARD_FRAME_GOLD,
    CARD_SHADOW,
    HIGHLIGHT,
)


def build_rule_text_lines(self, font: pygame.font.Font, max_width: int, text: str) -> list[str]:
    lines: list[str] = []
    if text:
        lines.extend(self.wrap_text(font, text, max_width))
    return [line for line in lines if line]


def get_card_text_fonts(self) -> tuple[pygame.font.Font, pygame.font.Font, pygame.font.Font, pygame.font.Font]:
    title_size = max(self.small_font.get_height() + 3, 15)
    body_size = max(self.small_font.get_height(), 12)
    number_size = max(body_size + 8, title_size + 5, 22)
    title_font = pygame.font.SysFont("arial", title_size, bold=True)
    body_font = pygame.font.SysFont("arial", body_size)
    body_italic_font = pygame.font.SysFont("arial", body_size, italic=True)
    number_font = pygame.font.SysFont("arial", number_size, bold=True)
    return title_font, body_font, body_italic_font, number_font


def build_hand_card_surface(self, card, selected: bool, note: str = "") -> pygame.Surface:
    line_one, line_two = self.get_card_ability_lines(card.template)
    is_creature = getattr(card.template, "card_type", None) is None or card.template.card_type.value == "Kreatur"
    display_cost = card.template.cost
    if is_creature and hasattr(self, "engine"):
        display_cost = self.engine.get_card_cost_to_pay(self.engine.active_player, card)
    return self.build_card_surface(
        template_id=card.template.template_id,
        title=card.template.name,
        cost=display_cost,
        stats=f"{card.template.aw}/{card.template.vw}" if is_creature else "",
        defense_text=f"{card.template.vw}/{card.template.vw}" if is_creature else None,
        element=card.template.element,
        type_line=self.get_creature_type_line(card.template),
        line_one=line_one,
        line_two=note or line_two,
        accent_color=(186, 177, 154),
        frame_color=CARD_FRAME_GOLD,
        tapped=False,
        selected=selected,
    )


def build_card_surface(
    self,
    template_id: str | None,
    title: str,
    cost: CardCost | int,
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
    if template_id is None:
        raise ValueError(f"Full-art rendering requires a template_id for card '{title}'.")
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
    title_font, body_font, body_italic_font, number_font = get_card_text_fonts(self)
    image = self.card_art_images.get(template_id)
    if image is None:
        raise KeyError(f"Missing full-art image for template_id '{template_id}'.")

    scaled = pygame.transform.smoothscale(image, (self.card_width, self.card_height))
    clipped = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
    pygame.draw.rect(clipped, (255, 255, 255), pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
    scaled.blit(clipped, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    base.blit(scaled, (0, 0))

    aw_text = ""
    vw_text = ""
    shield_text = ""
    shield_text_color = (255, 255, 255)
    if stats:
        aw_text, vw_text = stats.split("/", maxsplit=1)
        shield_text = defense_text or vw_text
        shield_text_color = (255, 142, 142) if shield_text.startswith("0/") else (255, 255, 255)
    header_y = max(s(4), int(self.card_height * 0.02))
    cost_value = cost if isinstance(cost, CardCost) else CardCost(resources=cost)
    cost_text = str(cost_value.resources) if cost_value.resources > 0 else ""
    cost_width = number_font.size(cost_text)[0] if cost_text else 0
    cost_x = self.card_width - s(8) - cost_width
    title_text = self.fit_text(title_font, title, max(s(24), cost_x - s(12)))
    blit_text_with_shadow(base, title_font, title_text, (255, 255, 255), s(10), header_y + s(3))
    if cost_text:
        blit_text_with_shadow(base, number_font, cost_text, (255, 255, 255), cost_x, header_y + s(3))
    keyword_lines = self.wrap_text(body_italic_font, line_one, self.card_width - s(20)) if line_one else []
    keyword_line_height = body_font.get_height() + s(1)
    keyword_y = header_y + s(22)
    for keyword_line in keyword_lines:
        blit_text_with_shadow(base, body_italic_font, keyword_line, (255, 255, 255), s(10), keyword_y)
        keyword_y += keyword_line_height
    rules_start_y = int(self.card_height * 0.5)
    rules_rect = pygame.Rect(s(10), rules_start_y, self.card_width - s(20), self.card_height - rules_start_y - s(32))
    rule_lines = build_rule_text_lines(self, body_font, rules_rect.width, line_two)
    rule_line_height = body_font.get_height() + s(1)
    rule_y = rules_rect.y
    for line in rule_lines:
        blit_text_with_shadow(base, body_font, line, (255, 255, 255), rules_rect.x, rule_y)
        rule_y += rule_line_height

    footer_y = self.card_height - s(14)
    aw_x = s(10)
    shield_icon_size = s(22)
    if stats:
        shield_width = number_font.size(shield_text)[0]
        shield_x = self.card_width - s(6) - shield_width - shield_icon_size
        blit_text_with_shadow(base, number_font, aw_text, (255, 255, 255), aw_x, self.card_height - s(25))
        blit_text_with_shadow(base, number_font, shield_text, shield_text_color, shield_x, self.card_height - s(25))
    recycle_icon_gap = 0
    recycle_icon_size = s(22)
    recycle_width = cost_value.recycle * recycle_icon_size + max(0, cost_value.recycle - 1) * recycle_icon_gap
    recycle_x = (self.card_width - recycle_width) // 2
    recycle_y = self.card_height - s(25)
    for recycle_index in range(cost_value.recycle):
        icon_rect = pygame.Rect(
            recycle_x + recycle_index * (recycle_icon_size + recycle_icon_gap),
            recycle_y,
            recycle_icon_size,
            recycle_icon_size,
        )
        self.blit_symbol_image(base, get_element_symbol_key(element), icon_rect)
    if stats:
        aw_width = number_font.size(aw_text)[0]
        self.blit_symbol_image(base, "sword_symbol", pygame.Rect(aw_x + aw_width - s(3), footer_y - s(12), s(22), s(22)))
        self.blit_symbol_image(base, "shield_symbol", pygame.Rect(self.card_width - s(6) - shield_icon_size, footer_y - s(12), shield_icon_size, shield_icon_size))

    if selected:
        pygame.draw.rect(base, HIGHLIGHT, pygame.Rect(0, 0, self.card_width, self.card_height), max(1, s(3)), border_radius=s(8))
    if tapped:
        return pygame.transform.rotate(base, -90)
    return base


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
        color = tuple(int(top_color[index] * (1 - ratio) + bottom_color[index] * ratio) for index in range(3))
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
