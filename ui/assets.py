from __future__ import annotations

from pathlib import Path
from typing import Callable

import pygame

from core.models import CardInstance, Element
from ui.style import CARD_BORDER


def normalize_asset_stem(stem: str) -> str:
    return (
        stem.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
        .replace("ß", "ss")
    )


def normalize_card_art_name(name: str) -> str:
    return normalize_asset_stem(name).replace(" ", "_").lower()


def load_resource_back_images(self) -> dict[str, pygame.Surface]:
    resources_dir = Path(__file__).resolve().parent.parent / "ressources"
    image_map: dict[str, pygame.Surface] = {}
    for name in ("fire", "water", "earth", "air"):
        image_path = resources_dir / f"{name}.png"
        if image_path.exists():
            image_map[name] = pygame.image.load(str(image_path)).convert_alpha()
    return image_map


def load_summoner_images(self) -> dict[str, pygame.Surface]:
    resources_dir = Path(__file__).resolve().parent.parent / "ressources"
    image_map: dict[str, pygame.Surface] = {}
    for name in ("fire", "water", "earth", "air"):
        image_path = resources_dir / f"{name}_summoner.png"
        if image_path.exists():
            image_map[name] = pygame.image.load(str(image_path)).convert_alpha()
    return image_map


def load_ui_symbol_images(self) -> dict[str, pygame.Surface]:
    resources_dir = Path(__file__).resolve().parent.parent / "ressources"
    image_map: dict[str, pygame.Surface] = {}
    for name in (
        "creature_symbol",
        "sword_symbol",
        "shield_symbol",
        "fire_symbol",
        "water_symbol",
        "earth_symbol",
        "air_symbol",
    ):
        image_path = resources_dir / f"{name}.png"
        if image_path.exists():
            image_map[name] = pygame.image.load(str(image_path)).convert_alpha()
    return image_map


def load_card_art_images(self) -> dict[str, pygame.Surface]:
    image_map: dict[str, pygame.Surface] = {}
    base_dir = Path(__file__).resolve().parent.parent / "ressources"
    folder_prefixes = {
        "fire_creatures": "fire_creature_",
        "fire_rituals": "fire_ritual_",
        "fire_spells": "fire_spell_",
        "water_creatures": "water_creature_",
        "earth_creatures": "earth_creature_",
        "air_creatures": "air_creature_",
        "air_rituals": None,
        "air_spells": None,
    }
    for folder_name, template_prefix in folder_prefixes.items():
        resources_dir = base_dir / folder_name
        if not resources_dir.exists():
            continue
        for image_path in resources_dir.glob("*.png"):
            surface = pygame.image.load(str(image_path)).convert_alpha()
            image_map[image_path.stem] = surface
            normalized_stem = normalize_asset_stem(image_path.stem)
            image_map[normalized_stem] = surface
            stem_parts = normalized_stem.split("_", maxsplit=1)
            if template_prefix is not None and len(stem_parts) == 2:
                image_map[f"{template_prefix}{stem_parts[1]}"] = surface
    for template_id, template in getattr(self.engine, "templates", {}).items():
        normalized_name = normalize_card_art_name(template.name)
        if normalized_name in image_map:
            image_map[template_id] = image_map[normalized_name]
    return image_map


def render_scaled_card_surface(self, scale: float, render_fn: Callable[[], pygame.Surface]) -> pygame.Surface:
    old_card_width = self.card_width
    old_card_height = self.card_height
    old_small_font = self.small_font
    old_layout_scale = self.layout_scale
    self.card_width = max(1, int(old_card_width * scale))
    self.card_height = max(1, int(old_card_height * scale))
    self.small_font = pygame.font.SysFont("arial", max(12, int(12 * scale)))
    self.layout_scale = scale
    try:
        return render_fn()
    finally:
        self.card_width = old_card_width
        self.card_height = old_card_height
        self.small_font = old_small_font
        self.layout_scale = old_layout_scale


def build_preview_hand_card_surface(self, card, note: str = "") -> pygame.Surface:
    line_one, line_two = self.get_card_ability_lines(card.template)
    display_cost = card.template.cost
    is_creature = card.template.card_type.value == "Kreatur"
    if is_creature and any(existing.instance_id == card.instance_id for existing in self.engine.active_player.hand):
        display_cost = self.engine.get_card_cost_to_pay(self.engine.active_player, card)
    return self.render_scaled_card_surface(
        2.0,
        lambda: self.build_card_surface(
            template_id=card.template.template_id,
            title=card.template.name,
            cost=display_cost,
            stats=self.get_display_template_stats(card.template) if is_creature else None,
            element=card.template.element,
            type_line=self.get_creature_type_line(card.template),
            line_one=line_one,
            line_two=note or line_two,
            accent_color=(186, 177, 154),
            frame_color=(191, 161, 92),
            tapped=False,
            selected=False,
        ),
    )


def build_preview_hidden_hand_surface(self, card) -> pygame.Surface:
    return self.render_scaled_card_surface(2.0, lambda: self.build_resource_back_surface(card.template.element, False))


def build_preview_resource_surface(self, resource) -> pygame.Surface:
    return self.render_scaled_card_surface(
        2.0,
        lambda: self.build_resource_back_surface(resource.template.element, resource.tapped),
    )


def build_preview_deck_surface(self, player) -> pygame.Surface:
    top_card = player.deck[-1] if player.deck else None
    fallback_elements = {
        "fire": Element.FIRE,
        "water": Element.WATER,
        "earth": Element.EARTH,
        "air": Element.AIR,
    }
    element = top_card.template.element if top_card is not None else fallback_elements.get(player.summoner_key, Element.AIR)

    def _render() -> pygame.Surface:
        surface = self.build_resource_back_surface(element, False)
        deck_badge_rect = pygame.Rect(self.card_width // 2 - 34, self.card_height // 2 - 26, 68, 52)
        self.draw_card_badge(surface, deck_badge_rect, str(len(player.deck)), self.font, self.get_think_progress(player))
        return surface

    return self.render_scaled_card_surface(2.0, _render)


def build_preview_creature_surface(self, creature, is_human: bool, extra_line: str = "", attacking: bool = False) -> pygame.Surface:
    accent = (98, 151, 109) if is_human else (177, 98, 98)
    stats = self.get_display_creature_stats(creature)
    line_one = ""
    line_two = extra_line
    ability_line_one, ability_line_two = self.get_card_ability_lines_from_creature(creature)
    if ability_line_one:
        line_one = ability_line_one
    if not extra_line and ability_line_two:
        line_two = ability_line_two
    return self.render_scaled_card_surface(
        2.0,
        lambda: self.build_card_surface(
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
            tapped=False,
            selected=False,
            attacking=attacking,
        ),
    )


def build_preview_summoner_surface(self, summoner_key: str, life: int, think_progress: float | None = None) -> pygame.Surface:
    def _render() -> pygame.Surface:
        surface = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
        image = self.summoner_images.get(summoner_key)
        if image is None:
            pygame.draw.rect(surface, (238, 232, 218), pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
            pygame.draw.rect(surface, CARD_BORDER, pygame.Rect(0, 0, self.card_width, self.card_height), 2, border_radius=9)
        else:
            scaled = pygame.transform.smoothscale(image, (self.card_width, self.card_height))
            clipped = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
            pygame.draw.rect(clipped, (255, 255, 255), pygame.Rect(0, 0, self.card_width, self.card_height), border_radius=9)
            scaled.blit(clipped, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(scaled, (0, 0))
            pygame.draw.rect(surface, CARD_BORDER, pygame.Rect(0, 0, self.card_width, self.card_height), 2, border_radius=9)
        self.draw_summoner_footer(surface, summoner_key, life)
        return surface

    return self.render_scaled_card_surface(2.0, _render)


def handle_preview_start(self, position: tuple[int, int]) -> None:
    for rect, builder in reversed(self.preview_targets):
        if rect.collidepoint(position):
            self.preview_builder = builder
            self.preview_surface = None
            return
    self.preview_builder = None
    self.preview_surface = None


def handle_preview_stop(self) -> None:
    self.preview_builder = None
    self.preview_surface = None


def draw_card_preview_overlay(self) -> None:
    if self.preview_surface is None and self.preview_builder is not None:
        self.preview_surface = self.preview_builder()
    if self.preview_surface is None:
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill((10, 12, 16, 170))
    self.screen.blit(overlay, (0, 0))
    width = self.preview_surface.get_width() * 2
    height = self.preview_surface.get_height() * 2
    playfield_width = self.window_width - self.side_panel_width - 30
    max_width = playfield_width - 80
    max_height = self.window_height - 80
    scale = min(max_width / width, max_height / height, 1.0)
    preview_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    scaled = pygame.transform.smoothscale(self.preview_surface, preview_size)
    playfield_center_x = 10 + playfield_width // 2
    rect = scaled.get_rect(center=(playfield_center_x, self.window_height // 2))
    self.screen.blit(scaled, rect.topleft)
    pygame.draw.rect(self.screen, CARD_BORDER, rect, 3, border_radius=10)


def build_recycle_reveal_surfaces(self, template_ids: list[str]) -> list[pygame.Surface]:
    templates = [self.engine.templates[template_id] for template_id in template_ids if template_id in self.engine.templates]
    if not templates:
        return []
    return [self.build_preview_hand_card_surface(CardInstance(-1, template)) for template in templates]
