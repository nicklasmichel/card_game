from __future__ import annotations

from typing import List

import pygame

from core.game_mode import is_builder_mode
from core.models import Ability, CardTemplate, CardType, Element, SpellTiming
from ui.style import CARD_BADGE_LIGHT, CARD_BORDER


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
    if template.card_type == CardType.CREATURE:
        return f"Kreatur - {template.element.value}"
    if template.card_type == CardType.SPELL and template.spell_timing is not None:
        return f"{template.spell_timing.value} - {template.element.value}"
    return f"{template.card_type.value} - {template.element.value}"


def get_card_ability_lines(self, template: CardTemplate) -> tuple[str, str]:
    if is_builder_mode() and getattr(template, "template_id", "").startswith("builder_ability_"):
        return template.name, ""
    names = self.get_ability_names(template.abilities)
    line_one = ", ".join(names)
    if not line_one and template.card_type in {CardType.RITUAL, CardType.SPELL}:
        if template.card_type == CardType.SPELL and template.spell_timing is not None:
            line_one = template.spell_timing.value
        else:
            line_one = template.card_type.value
    line_two = "" if template.card_type == CardType.CREATURE and names else normalize_rules_text(getattr(template, "rules_text", ""), names)
    return line_one, line_two


def get_card_ability_lines_from_creature(self, creature) -> tuple[str, str]:
    names = self.get_ability_names(creature.abilities)
    line_one = ", ".join(names)
    line_two = ""
    return line_one, line_two


def get_display_creature_stats(self, creature) -> tuple[str, str, str, str]:
    display_aw = self.engine.get_creature_attack_value(creature)
    display_vw = self.engine.get_creature_defense_value(creature)
    current_lw = self.engine.get_creature_current_lw(creature)
    display_sw = self.engine.get_creature_damage_value(creature)
    return str(display_aw), str(display_vw), str(current_lw), str(display_sw)


def get_display_builder_creature_stats(self, creature) -> tuple[str, str, str, str]:
    display_aw = self.engine.get_creature_attack_value(creature)
    display_vw = self.engine.get_creature_defense_value(creature)
    current_lw = self.engine.get_creature_current_lw(creature)
    max_lw = getattr(creature, "lw", current_lw)
    display_sw = self.engine.get_creature_damage_value(creature)
    return str(display_aw), str(display_vw), str(display_sw), f"{current_lw}/{max_lw}"


def get_display_template_stats(self, template) -> tuple[str, str, str, str]:
    if hasattr(self, "engine"):
        max_lw = self.engine.get_template_max_lw(template)
        display_sw = self.engine.get_template_damage_value(template)
    else:
        max_lw = template.effective_lw
        display_sw = template.effective_sw
    return str(template.aw), str(template.vw), str(max_lw), str(display_sw)


def get_ability_names(self, abilities) -> List[str]:
    order = [
        Ability.DEATHTOUCH,
        Ability.ENRAGED,
        Ability.PROVOKE,
        Ability.TRAMPLE,
        Ability.HASTE,
        Ability.FLYING,
        Ability.VIGILANT,
        Ability.VIGILANCE,
        Ability.LIFE_STEAL,
        Ability.LIFELINK,
        Ability.MAGIC_RESISTANT,
    ]
    display_names = {
        Ability.DEATHTOUCH: "Deathtouch",
        Ability.ENRAGED: "Wuetend",
        Ability.PROVOKE: "Provoke",
        Ability.TRAMPLE: "Trampelnd",
        Ability.HASTE: "Haste" if is_builder_mode() else "Schnell",
        Ability.FLYING: "Flying" if is_builder_mode() else "Fliegend",
        Ability.VIGILANT: "Vigilance" if is_builder_mode() else "Wachsam",
        Ability.VIGILANCE: "Vigilance",
        Ability.LIFE_STEAL: "Lifelink" if is_builder_mode() else "Lebensraub",
        Ability.LIFELINK: "Lifelink",
        Ability.MAGIC_RESISTANT: "Magieresistent",
    }
    return [display_names.get(ability, ability.value) for ability in order if ability in abilities]


def get_ability_description(ability: Ability) -> str:
    descriptions = {
        Ability.DEATHTOUCH: "Whenever this creature deals at least 1 damage to another creature, destroy that creature.",
        Ability.HASTE: "This creature can attack during the turn it is created." if is_builder_mode() else "Schnelle Kreaturen kommen ungetappt ins Spiel und koennen direkt angreifen oder blocken.",
        Ability.FLYING: "This creature can only be blocked by creatures with Flying." if is_builder_mode() else "Fliegende Kreaturen koennen nur von Kreaturen mit Fliegend geblockt werden.",
        Ability.TRAMPLE: "Excess damage dealt to a blocking creature is dealt to the defending player.",
        Ability.ENRAGED: "When this creature attacks, you may choose a creature the defending player controls. That creature blocks this creature.",
        Ability.PROVOKE: "When this creature attacks, you may choose a creature the defending player controls. That creature blocks this creature.",
        Ability.VIGILANT: "Attacking does not cause this creature to tap." if is_builder_mode() else "Diese Kreatur wird beim Angreifen nicht getappt.",
        Ability.VIGILANCE: "Attacking does not cause this creature to tap.",
        Ability.LIFE_STEAL: "Whenever this creature deals damage, it heals itself by that amount, up to its maximum Life." if is_builder_mode() else "Wenn diese Kreatur Schaden verursacht, heilt sie sich selbst um den tatsaechlich verursachten Schaden bis maximal zu ihrem Leben.",
        Ability.LIFELINK: "Whenever this creature deals damage, it heals itself by that amount, up to its maximum Life.",
        Ability.MAGIC_RESISTANT: "Diese Kreatur kann nicht das Ziel von Ritualen, Spontanzaubern oder Kampfzaubern sein.",
    }
    return descriptions.get(ability, ability.value)


def get_card_preview_ability_details(self, source) -> List[tuple[str, str]]:
    template = source.template if hasattr(source, "template") else source
    template_id = getattr(template, "template_id", "")
    if is_builder_mode() and template_id.startswith("builder_ability_"):
        card_name = getattr(template, "name", "Ability")
        return [
            (card_name, get_ability_description(getattr(Ability, template_id.removeprefix("builder_ability_").upper(), Ability.PROVOKE))),
            (
                "Builder card modes",
                "During the ability phase, you may grant this keyword to one of your creatures, give +1 Attack, Defense, Damage, or Life to one of your creatures, or deal 1 damage to any creature.",
            ),
        ]
    abilities = getattr(source, "abilities", frozenset())
    ordered_names = self.get_ability_names(abilities)
    if not ordered_names:
        return []
    name_by_ability = {
        Ability.DEATHTOUCH: "Deathtouch",
        Ability.ENRAGED: "Wuetend",
        Ability.PROVOKE: "Provoke",
        Ability.TRAMPLE: "Trampelnd",
        Ability.HASTE: "Haste" if is_builder_mode() else "Schnell",
        Ability.FLYING: "Flying" if is_builder_mode() else "Fliegend",
        Ability.VIGILANT: "Vigilance" if is_builder_mode() else "Wachsam",
        Ability.VIGILANCE: "Vigilance",
        Ability.LIFE_STEAL: "Lifelink" if is_builder_mode() else "Lebensraub",
        Ability.LIFELINK: "Lifelink",
        Ability.MAGIC_RESISTANT: "Magieresistent",
    }
    details: List[tuple[str, str]] = []
    for ability in (Ability.DEATHTOUCH, Ability.PROVOKE, Ability.ENRAGED, Ability.TRAMPLE, Ability.HASTE, Ability.FLYING, Ability.VIGILANCE, Ability.VIGILANT, Ability.LIFELINK, Ability.LIFE_STEAL, Ability.MAGIC_RESISTANT):
        if ability in abilities:
            details.append((name_by_ability[ability], get_ability_description(ability)))
    return details

def normalize_rules_text(rules_text: str, ability_names: List[str]) -> str:
    normalized = rules_text.strip()
    if not normalized or not ability_names:
        return normalized
    changed = True
    while changed and normalized:
        changed = False
        for ability_name in ability_names:
            prefix = f"{ability_name}."
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].lstrip()
                changed = True
                break
    return normalized


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
