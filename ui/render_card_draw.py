from __future__ import annotations

import pygame

from core.models import MAIN_PHASES, PHASE_REACTION
from ui.render_helpers import blit_text_with_shadow
from ui.style import CARD_BORDER, CARD_COLOR, ENEMY_CARD_COLOR, PLAYER_CARD_COLOR


def draw_hand_card(self, card, x: int, y: int, selected: bool, note: str = "") -> pygame.Rect:
    surface = self.build_hand_card_surface(card, selected, note)
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
    self.draw_summoner_footer(surface, summoner_key, life)
    rendered_surface = pygame.transform.rotate(surface, -90) if tapped else surface
    self.screen.blit(rendered_surface, rect.topleft)
    self.last_rendered_card_surface = rendered_surface.copy()
    self.last_preview_builder = lambda summoner_key=summoner_key, life=life, think_progress=think_progress: self.build_preview_summoner_surface(summoner_key, life, think_progress)
    return rect


def draw_summoner_life_circle(self, life: int, x: int, y: int, think_progress: float | None) -> None:
    return


def draw_summoner_footer(self, surface: pygame.Surface, summoner_key: str, life: int) -> None:
    scale = getattr(self, "layout_scale", 1.0)
    s = lambda value: max(1, int(round(value * scale)))
    body_size = max(self.small_font.get_height(), 12)
    title_size = max(self.small_font.get_height() + 3, 15)
    number_size = max(body_size + 8, title_size + 5, 22)
    card_number_font = pygame.font.SysFont("arial", number_size, bold=True)
    life_font = pygame.font.SysFont("arial", number_size * 2, bold=True)
    rules_font = pygame.font.SysFont("arial", max(s(9), self.small_font.get_height() - s(1)))
    rules_texts = {
        "air": "Wenn in deinem Zug mindestens 3 Kreaturen angreifen, ziehe 1 Karte.",
        "fire": "Wenn du deinen Zug mit weniger als 10 Leben beginnst, ziehe 1 zusaetzliche Karte.",
    }
    rules_text = rules_texts.get(summoner_key, "")
    rules_start_y = int(self.card_height * 0.5)
    rules_rect = pygame.Rect(s(10), rules_start_y, self.card_width - s(20), self.card_height - rules_start_y - s(12))
    rule_lines = self.wrap_text(rules_font, rules_text, rules_rect.width)
    rule_line_height = rules_font.get_height() + s(1)
    rule_y = rules_rect.y
    for line in rule_lines:
        blit_text_with_shadow(surface, rules_font, line, (255, 255, 255), rules_rect.x, rule_y)
        rule_y += rule_line_height
    life_text = str(life)
    life_text_color = (255, 142, 142) if life <= 0 else (255, 255, 255)
    life_width, life_height = life_font.size(life_text)
    life_x = (self.card_width - life_width) // 2
    life_y = int(self.card_height * 0.32) - life_height // 2
    blit_text_with_shadow(surface, life_font, life_text, life_text_color, life_x, life_y)


def draw_card_badge(
    self,
    surface: pygame.Surface,
    badge_rect: pygame.Rect,
    text: str,
    font: pygame.font.Font | None = None,
    think_progress: float | None = None,
) -> None:
    base_font = font or self.font
    badge_font_size = max(
        base_font.get_height() + 12,
        int(badge_rect.height * 0.9),
    )
    badge_font = pygame.font.Font(None, badge_font_size)
    self.blit_centered_text_to_surface(surface, badge_font, text, (0, 0, 0), badge_rect)


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
    stats = self.get_display_creature_stats(creature)
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
        stats=stats,
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
