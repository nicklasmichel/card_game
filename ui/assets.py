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


def load_resource_segment_images(self) -> tuple[pygame.Surface | None, ...]:
    resources_dir = Path(__file__).resolve().parent.parent / "ressources" / "resources"
    images: list[pygame.Surface | None] = []
    for resource_number in range(1, 11):
        candidates = [resources_dir / f"res{resource_number}.png"]
        if resource_number == 10:
            # Keep compatibility with the supplied filename.
            candidates.append(resources_dir / "res110.png")
        image_path = next((candidate for candidate in candidates if candidate.exists()), None)
        images.append(
            pygame.image.load(str(image_path)).convert_alpha()
            if image_path is not None
            else None
        )
    return tuple(images)


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

    builder_ability_aliases = {
        "deathtouch": ("builder_ability_deathtouch",),
        "flying": ("builder_ability_flying",),
        "haste": ("builder_ability_haste",),
        "lifesteal": ("builder_ability_lifelink", "builder_ability_life_steal"),
        "trample": ("builder_ability_trample",),
        "vigilance": ("builder_ability_vigilance", "builder_ability_vigilant"),
        "provoke": ("builder_ability_provoke", "builder_ability_enraged"),
    }

    def _register_art_file(image_path: Path) -> None:
        surface = pygame.image.load(str(image_path)).convert_alpha()
        normalized_stem = normalize_asset_stem(image_path.stem).lower()
        image_map[image_path.stem] = surface
        image_map[normalized_stem] = surface
        for template_id in builder_ability_aliases.get(normalized_stem, ()):
            image_map[template_id] = surface

    for stem in builder_ability_aliases:
        image_path = base_dir / f"{stem}.png"
        if image_path.exists():
            _register_art_file(image_path)

    builder_ability_dir = base_dir / "builder_mode" / "abilities"
    if builder_ability_dir.exists():
        for image_path in builder_ability_dir.glob("*.png"):
            _register_art_file(image_path)

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
    center_title_only = bool(
        not is_creature
        and getattr(card.template, "template_id", "").startswith("builder_ability_")
    )
    if is_creature:
        line_one = ""
        line_two = ""
    if is_creature and any(existing.instance_id == card.instance_id for existing in self.engine.active_player.hand):
        display_cost = self.engine.get_card_cost_to_pay(self.engine.active_player, card)
    return self.render_scaled_card_surface(
        2.0,
        lambda: self.build_card_surface(
            template_id=card.template.template_id,
            art_key=self.get_card_art_key(card.template),
            title=card.template.name,
            cost=display_cost,
            stats=self.get_display_template_stats(card.template) if is_creature else None,
            element=card.template.element,
            type_line=self.get_creature_type_line(card.template),
            line_one="" if center_title_only else line_one,
            line_two="" if center_title_only else note or line_two,
            accent_color=(186, 177, 154),
            frame_color=(191, 161, 92),
            tapped=False,
            selected=False,
            center_title_only=center_title_only,
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
    template_id = getattr(creature, "template_id", None)
    hide_title = bool(
        isinstance(template_id, str)
        and (template_id.startswith("builder_creature_") or template_id == "builder_creature_preview")
    )
    stats = self.get_display_builder_creature_stats(creature) if hide_title else self.get_display_creature_stats(creature)
    line_one = ""
    line_two = extra_line
    return self.render_scaled_card_surface(
        2.0,
        lambda: self.build_card_surface(
            template_id=template_id,
            art_key=self.get_card_art_key(creature),
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
            hide_title=hide_title,
            hide_cost=hide_title,
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
    for target in reversed(self.preview_targets):
        if len(target) == 3:
            rect, builder, info_builder = target
        else:
            rect, builder = target

            def info_builder() -> list:
                return []
        if rect.collidepoint(position):
            self.preview_builder = builder
            self.preview_info_builder = info_builder
            self.preview_surface = None
            return
    self.preview_builder = None
    self.preview_info_builder = None
    self.preview_surface = None


def handle_preview_stop(self) -> None:
    self.preview_builder = None
    self.preview_info_builder = None
    self.preview_surface = None


def draw_card_preview_overlay(self) -> None:
    if self.preview_surface is None and self.preview_builder is not None:
        self.preview_surface = self.preview_builder()
    if self.preview_surface is None:
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill((10, 12, 16, 170))
    self.screen.blit(overlay, (0, 0))
    ability_details = self.preview_info_builder() if self.preview_info_builder is not None else []
    width = self.preview_surface.get_width() * 2
    height = self.preview_surface.get_height() * 2
    playfield_width = self.window_width - self.side_panel_width - 30
    max_width = playfield_width - 80
    max_height = self.window_height - 80
    info_panel_width = min(420, max(300, int(playfield_width * 0.24))) if ability_details else 0
    content_gap = 24 if ability_details else 0
    total_target_width = width + info_panel_width + content_gap
    scale = min((max_width / max(1, total_target_width)), max_height / height, 1.0)
    preview_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    scaled = pygame.transform.smoothscale(self.preview_surface, preview_size)
    scaled_info_width = int(info_panel_width * scale) if ability_details else 0
    total_scaled_width = preview_size[0] + scaled_info_width + (int(content_gap * scale) if ability_details else 0)
    content_left = 10 + (playfield_width - total_scaled_width) // 2
    rect = scaled.get_rect(midleft=(content_left, self.window_height // 2))
    self.screen.blit(scaled, rect.topleft)
    pygame.draw.rect(self.screen, CARD_BORDER, rect, 3, border_radius=10)
    if ability_details:
        title_font = pygame.font.SysFont("arial", max(18, int(self.font.get_height() * scale) + 2), bold=True)
        body_font = pygame.font.SysFont("arial", max(14, int(self.small_font.get_height() * scale) + 4))
        heading_font = pygame.font.SysFont("arial", max(15, int(self.small_font.get_height() * scale) + 5), bold=True)
        gap = max(12, int(14 * scale))
        panel_rect = pygame.Rect(
            rect.right + max(12, int(content_gap * scale) - 8),
            rect.y,
            scaled_info_width,
            rect.height,
        )
        pygame.draw.rect(self.screen, (52, 58, 68), panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, CARD_BORDER, panel_rect, 2, border_radius=10)
        title_surface = title_font.render("Details", True, (240, 240, 240))
        self.screen.blit(title_surface, (panel_rect.x + gap, panel_rect.y + gap))
        current_y = panel_rect.y + gap + title_surface.get_height() + gap
        max_text_width = panel_rect.width - gap * 2
        for ability_name, description in ability_details:
            name_surface = heading_font.render(ability_name, True, (244, 239, 228))
            self.screen.blit(name_surface, (panel_rect.x + gap, current_y))
            current_y += name_surface.get_height() + max(6, int(6 * scale))
            for line in self.wrap_text(body_font, description, max_text_width):
                line_surface = body_font.render(line, True, (240, 240, 240))
                self.screen.blit(line_surface, (panel_rect.x + gap, current_y))
                current_y += line_surface.get_height() + max(2, int(2 * scale))
            current_y += gap


def build_recycle_reveal_surfaces(self, template_ids: list[str]) -> list[pygame.Surface]:
    templates = [self.engine.templates[template_id] for template_id in template_ids if template_id in self.engine.templates]
    if not templates:
        return []
    return [self.build_preview_hand_card_surface(CardInstance(-1, template)) for template in templates]
