from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import pygame

from game_logic import GameEngine
from models import (
    ButtonSpec,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_RESOURCE,
    PHASE_SUMMONING,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
)
from ui.card_rendering import (
    blit_centered_text,
    blit_centered_text_to_surface,
    blit_symbol_image,
    blit_text_to_surface,
    blit_wrapped_text,
    build_card_surface,
    build_resource_back_surface,
    can_drag_hand_card,
    can_drag_hand_card_to_creature,
    can_drag_hand_card_to_resource,
    can_drop_on_creature_area,
    can_drop_on_resource_area,
    clear_drag_state,
    draw_art_panel,
    draw_creature_card,
    draw_dragged_card,
    draw_element_symbol,
    draw_hidden_hand_card,
    get_zone_fill_color,
    draw_resource_backdrop,
    draw_hand_card,
    draw_playfield_section_box,
    draw_resource_card,
    draw_summoner_card,
    draw_summoner_life_circle,
    fit_text,
    get_ability_names,
    get_card_ability_lines,
    get_card_ability_lines_from_creature,
    get_creature_type_line,
    get_element_color,
    get_target_at_position,
    wrap_text,
)
from ui.input import handle_mouse_click, handle_mouse_down, handle_mouse_motion, handle_mouse_up
from ui.layout import (
    blit_text,
    draw_arrowhead,
    draw_buttons,
    draw_combat_links,
    draw_creatures,
    draw_enemy_area,
    draw_hand,
    draw_link_marker,
    draw_player_area,
    draw_polyline,
    draw_resources,
    draw_section_box,
    draw_side_actions,
    draw_side_log,
    draw_side_overview,
    draw_side_panel,
    get_creature_screen_positions,
    get_playfield_sections,
    get_side_panel_layout,
    handle_log_scroll,
)
from ui.overlays import (
    draw_block_order_overlay,
    draw_dice_battle_overlay,
    draw_game_over_overlay,
    draw_mulligan_overlay,
)
from ui.style import (
    AI_THINK_DURATION_MS,
    BG_COLOR,
    BUTTON_COLOR,
    BUTTON_DISABLED,
    CARD_BORDER,
    ENEMY_CARD_COLOR,
    FPS,
    HIGHLIGHT,
    HUMAN_THINK_DURATION_MS,
    MUTED_TEXT,
    OVERLAY_COLOR,
    PANEL_COLOR,
    SECTION_COLOR,
    TEXT_COLOR,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)


class TcgPrototypeApp:
    draw_playfield_section_box = draw_playfield_section_box
    draw_hand_card = draw_hand_card
    draw_hidden_hand_card = draw_hidden_hand_card
    draw_dragged_card = draw_dragged_card
    draw_resource_card = draw_resource_card
    draw_summoner_card = draw_summoner_card
    draw_summoner_life_circle = draw_summoner_life_circle
    draw_creature_card = draw_creature_card
    blit_symbol_image = blit_symbol_image
    build_card_surface = build_card_surface
    get_creature_type_line = get_creature_type_line
    get_card_ability_lines = get_card_ability_lines
    get_card_ability_lines_from_creature = get_card_ability_lines_from_creature
    get_ability_names = get_ability_names
    blit_text_to_surface = blit_text_to_surface
    blit_centered_text_to_surface = blit_centered_text_to_surface
    fit_text = fit_text
    draw_art_panel = draw_art_panel
    draw_resource_backdrop = draw_resource_backdrop
    build_resource_back_surface = build_resource_back_surface
    draw_element_symbol = draw_element_symbol
    get_zone_fill_color = get_zone_fill_color
    get_element_color = get_element_color
    blit_centered_text = blit_centered_text
    wrap_text = wrap_text
    blit_wrapped_text = blit_wrapped_text
    get_target_at_position = get_target_at_position
    can_drag_hand_card = can_drag_hand_card
    can_drag_hand_card_to_resource = can_drag_hand_card_to_resource
    can_drop_on_resource_area = can_drop_on_resource_area
    can_drag_hand_card_to_creature = can_drag_hand_card_to_creature
    can_drop_on_creature_area = can_drop_on_creature_area
    clear_drag_state = clear_drag_state
    handle_mouse_down = handle_mouse_down
    handle_mouse_up = handle_mouse_up
    handle_mouse_motion = handle_mouse_motion
    handle_mouse_click = handle_mouse_click
    draw_enemy_area = draw_enemy_area
    draw_player_area = draw_player_area
    draw_combat_links = draw_combat_links
    get_creature_screen_positions = get_creature_screen_positions
    get_playfield_sections = get_playfield_sections
    draw_polyline = draw_polyline
    draw_arrowhead = draw_arrowhead
    draw_link_marker = draw_link_marker
    draw_resources = draw_resources
    draw_creatures = draw_creatures
    draw_hand = draw_hand
    draw_side_panel = draw_side_panel
    get_side_panel_layout = get_side_panel_layout
    draw_buttons = draw_buttons
    draw_side_overview = draw_side_overview
    draw_side_log = draw_side_log
    draw_side_actions = draw_side_actions
    handle_log_scroll = handle_log_scroll
    draw_mulligan_overlay = draw_mulligan_overlay
    draw_block_order_overlay = draw_block_order_overlay
    draw_dice_battle_overlay = draw_dice_battle_overlay
    draw_game_over_overlay = draw_game_over_overlay
    blit_text = blit_text
    draw_section_box = draw_section_box

    def __init__(self) -> None:
        os.environ["SDL_VIDEO_CENTERED"] = "1"
        pygame.init()
        display_info = pygame.display.Info()
        self.window_width = display_info.current_w
        self.window_height = display_info.current_h
        self.screen = pygame.display.set_mode(
            (self.window_width, self.window_height),
            pygame.NOFRAME,
        )
        self.card_width = 172 if self.window_width >= 1800 else 151
        self.card_height = int(self.card_width * 1.26)
        self.card_gap = 18 if self.window_width >= 1800 else 13
        self.side_panel_width = 380 if self.window_width >= 1800 else 350
        self.main_area_width = self.window_width - self.side_panel_width - 30
        pygame.display.set_caption("TCG Prototype")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 20)
        self.small_font = pygame.font.SysFont("arial", 12)
        self.title_font = pygame.font.SysFont("arial", 24, bold=True)
        self.layout_scale = 1.0
        self.engine = GameEngine()
        self.resource_back_images = self.load_resource_back_images()
        self.summoner_images = self.load_summoner_images()
        self.ui_symbol_images = self.load_ui_symbol_images()
        self.creature_art_images = self.load_creature_art_images()
        self.log_scroll_offset = 0
        self.log_viewport_rect = pygame.Rect(0, 0, 0, 0)
        self.buttons: List[Tuple[pygame.Rect, ButtonSpec]] = []
        self.ai_think_duration_ms = AI_THINK_DURATION_MS
        self.human_think_duration_ms = HUMAN_THINK_DURATION_MS
        self.decision_started_at_ms = pygame.time.get_ticks()
        self.decision_marker: tuple[int, str, str] | None = None
        self.show_enemy_hand_cards = False
        self.paused = False
        self.pause_started_at_ms: int | None = None
        self.player_creature_rect = pygame.Rect(0, 0, 0, 0)
        self.player_resource_rect = pygame.Rect(0, 0, 0, 0)
        self.dragged_hand_card_id: int | None = None
        self.drag_start_pos: tuple[int, int] | None = None
        self.drag_current_pos: tuple[int, int] | None = None
        self.drag_active = False
        self.last_rendered_card_surface: pygame.Surface | None = None
        self.last_preview_builder: Callable[[], pygame.Surface] | None = None
        self.preview_targets: List[Tuple[pygame.Rect, Callable[[], pygame.Surface]]] = []
        self.preview_builder: Callable[[], pygame.Surface] | None = None
        self.preview_surface: pygame.Surface | None = None
        self.damage_popups: List[dict] = []
        self.creature_lunges: Dict[int, dict] = {}
        self.creature_overlay_draws: List[tuple] = []
        self.summoner_rects: Dict[int, pygame.Rect] = {}
        self.click_targets: Dict[str, List[Tuple[pygame.Rect, int]]] = {
            "hand": [],
            "player_creatures": [],
            "enemy_creatures": [],
            "combat_lane": [],
            "human_dice": [],
            "order_blockers": [],
            "mulligan_hand": [],
        }

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

    def load_creature_art_images(self) -> dict[str, pygame.Surface]:
        image_map: dict[str, pygame.Surface] = {}
        base_dir = Path(__file__).resolve().parent.parent / "ressources"
        for folder_name in ("fire_creatures", "water_creatures", "earth_creatures", "air_creatures"):
            resources_dir = base_dir / folder_name
            if not resources_dir.exists():
                continue
            for image_path in resources_dir.glob("*.png"):
                image_map[image_path.stem] = pygame.image.load(str(image_path)).convert_alpha()
        return image_map


    def run(self) -> None:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type == pygame.MOUSEWHEEL:
                    self.handle_log_scroll(-event.y * 36)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_down(event.pos)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    self.handle_preview_start(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.handle_mouse_up(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                    self.handle_preview_stop()
                elif event.type == pygame.MOUSEMOTION:
                    self.handle_mouse_motion(event.pos)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                    direction = -36 if event.button == 4 else 36
                    self.handle_log_scroll(direction)

            self.consume_visual_events()
            if not self.paused:
                self.update_decision_timer()
                if self.is_timed_decision_ready():
                    self.process_timed_decision()
            self.engine.auto_resolve_human_no_blockers_if_needed()
            self.engine.resolve_stalled_dice_battle_if_needed()
            if self.engine.exit_requested:
                running = False
            self.draw()
            self.clock.tick(FPS)

        pygame.quit()

    def get_decision_marker(self) -> tuple[int, str, str] | None:
        if self.engine.phase == PHASE_MULLIGAN:
            return (self.engine.human_player.player_id, self.engine.phase, "mulligan")
        if self.engine.phase == PHASE_GAME_OVER:
            return None
        if self.engine.phase == PHASE_RESOURCE:
            return (self.engine.active_player.player_id, self.engine.phase, "resource")
        if self.engine.phase == PHASE_SUMMONING:
            return (self.engine.active_player.player_id, self.engine.phase, "summoning")
        if self.engine.phase == PHASE_DECLARE_ATTACKERS:
            return (self.engine.active_player.player_id, self.engine.phase, "attackers")
        if self.engine.phase == PHASE_DECLARE_BLOCKERS and self.engine.defending_player.is_human:
            return (self.engine.human_player.player_id, self.engine.phase, "blockers")
        if self.engine.phase == PHASE_DECLARE_BLOCKERS and not self.engine.defending_player.is_human:
            return (self.engine.defending_player.player_id, self.engine.phase, "blocks_ai")
        return None

    def update_decision_timer(self, force_reset: bool = False) -> None:
        marker = self.get_decision_marker()
        if force_reset or marker != self.decision_marker:
            self.decision_marker = marker
            self.decision_started_at_ms = pygame.time.get_ticks()

    def get_decision_duration_ms(self, marker: tuple[int, str, str] | None) -> int:
        if marker is None:
            return 0
        if marker[0] == self.engine.human_player.player_id:
            return self.human_think_duration_ms
        return self.ai_think_duration_ms

    def is_timed_decision_ready(self) -> bool:
        marker = self.get_decision_marker()
        if marker is None:
            return False
        elapsed = pygame.time.get_ticks() - self.decision_started_at_ms
        return elapsed >= self.get_decision_duration_ms(marker)

    def process_timed_decision(self) -> None:
        marker = self.get_decision_marker()
        if marker is None:
            return
        if marker[0] == self.engine.human_player.player_id:
            self.engine.handle_human_timeout()
        else:
            self.engine.process_ai_turn()
        self.update_decision_timer(force_reset=True)

    def get_think_progress(self, player) -> float | None:
        marker = self.get_decision_marker()
        if marker is None or player.player_id != marker[0]:
            return None
        duration_ms = self.get_decision_duration_ms(marker)
        if duration_ms <= 0:
            return None
        now = self.pause_started_at_ms if self.paused and self.pause_started_at_ms is not None else pygame.time.get_ticks()
        elapsed = now - self.decision_started_at_ms
        return max(0.0, min(1.0, elapsed / duration_ms))

    def handle_ui_action(self, action: str) -> bool:
        if action == "ui_toggle_enemy_hand":
            self.show_enemy_hand_cards = not self.show_enemy_hand_cards
            return True
        if action == "ui_toggle_pause":
            now = pygame.time.get_ticks()
            if self.paused:
                if self.pause_started_at_ms is not None:
                    paused_duration = now - self.pause_started_at_ms
                    self.decision_started_at_ms += paused_duration
                    for popup in self.damage_popups:
                        popup["started_at_ms"] += paused_duration
                    for animation in self.creature_lunges.values():
                        animation["started_at_ms"] += paused_duration
                self.paused = False
                self.pause_started_at_ms = None
            else:
                self.paused = True
                self.pause_started_at_ms = now
            return True
        return False

    def consume_visual_events(self) -> None:
        if not self.engine.pending_visual_events:
            self.prune_finished_visuals()
            return
        now = pygame.time.get_ticks()
        popup_totals: Dict[int, dict] = {}
        for event in self.engine.pending_visual_events:
            if event.get("type") != "player_damage":
                continue
            source_element = event.get("source_element")
            color = self.get_element_color(source_element) if source_element is not None else (255, 255, 255)
            target_player_id = event["target_player_id"]
            popup_entry = popup_totals.setdefault(
                target_player_id,
                {
                    "target_player_id": target_player_id,
                    "amount": 0,
                    "color": color,
                    "started_at_ms": now,
                },
            )
            popup_entry["amount"] += event["amount"]
            attacker_id = event.get("attacker_id")
            if attacker_id is not None:
                self.creature_lunges[attacker_id] = {
                    "target_player_id": target_player_id,
                    "started_at_ms": now,
                }
        self.damage_popups.extend(popup_totals.values())
        self.engine.pending_visual_events.clear()
        self.prune_finished_visuals()

    def prune_finished_visuals(self) -> None:
        now = self.pause_started_at_ms if self.paused and self.pause_started_at_ms is not None else pygame.time.get_ticks()
        self.damage_popups = [
            popup
            for popup in self.damage_popups
            if now - popup["started_at_ms"] <= 3000
        ]
        self.creature_lunges = {
            creature_id: animation
            for creature_id, animation in self.creature_lunges.items()
            if now - animation["started_at_ms"] <= 1500
        }

    def get_summoner_rect_for_player(self, player) -> pygame.Rect:
        sections = self.get_playfield_sections()
        hand_rect = sections["player_hand"] if player.player_id == self.engine.human_player.player_id else sections["enemy_hand"]
        start_x = hand_rect.x + 10
        available_width = hand_rect.width - 20
        summoner_x = start_x + max(0, (available_width - self.card_width) // 2)
        return pygame.Rect(summoner_x, hand_rect.y + 10, self.card_width, self.card_height)

    def is_creature_visually_tapped(self, creature) -> bool:
        return (
            creature.tapped
            and creature.unit_id not in self.creature_lunges
            and creature.unit_id not in self.engine.selected_attackers
        )

    def get_creature_animation_offset(self, creature_id: int, base_rect: pygame.Rect) -> tuple[int, int]:
        animation = self.creature_lunges.get(creature_id)
        if animation is None:
            return (0, 0)
        target_player = self.engine.players[animation["target_player_id"]]
        target_rect = self.get_summoner_rect_for_player(target_player)
        now = self.pause_started_at_ms if self.paused and self.pause_started_at_ms is not None else pygame.time.get_ticks()
        elapsed = max(0.0, now - animation["started_at_ms"])
        if elapsed < 500.0:
            travel = elapsed / 500.0
        else:
            travel = max(0.0, 1.0 - ((elapsed - 500.0) / 1000.0))
        dx = target_rect.centerx - base_rect.centerx
        dy = target_rect.centery - base_rect.centery
        distance = max(1.0, (dx * dx + dy * dy) ** 0.5)
        stop_gap = 42.0
        charge_ratio = max(0.0, min(1.0, (distance - stop_gap) / distance))
        return (round(dx * charge_ratio * travel), round(dy * charge_ratio * travel))

    def draw_damage_popups(self) -> None:
        now = self.pause_started_at_ms if self.paused and self.pause_started_at_ms is not None else pygame.time.get_ticks()
        for popup in self.damage_popups:
            target_player = self.engine.players[popup["target_player_id"]]
            summoner_rect = self.get_summoner_rect_for_player(target_player)
            progress = min(1.0, max(0.0, (now - popup["started_at_ms"]) / 3000.0))
            y_offset = int(46 * progress)
            alpha = 255 if progress < 0.8 else max(0, int(255 * (1.0 - (progress - 0.8) / 0.2)))
            text = f"-{popup['amount']}"
            text_surface = self.title_font.render(text, True, popup["color"])
            shadow_surface = self.title_font.render(text, True, (0, 0, 0))
            text_surface.set_alpha(alpha)
            shadow_surface.set_alpha(alpha)
            text_rect = text_surface.get_rect(center=(summoner_rect.centerx, summoner_rect.y + int(self.card_height * 0.56) - y_offset))
            self.screen.blit(shadow_surface, text_rect.move(2, 2))
            self.screen.blit(text_surface, text_rect)

    def draw_creature_overlays(self) -> None:
        for creature, is_human, draw_x, draw_y, selected, extra_line, attacking, target_key in self.creature_overlay_draws:
            rect = self.draw_creature_card(creature, is_human, draw_x, draw_y, selected, extra_line, attacking)
            if self.last_preview_builder is not None:
                self.preview_targets.append((rect, self.last_preview_builder))
            self.click_targets[target_key].append((rect, creature.unit_id))

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
        return self.render_scaled_card_surface(
            2.0,
            lambda: self.build_card_surface(
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

    def build_preview_creature_surface(self, creature, is_human: bool, extra_line: str = "", attacking: bool = False) -> pygame.Surface:
        accent = (98, 151, 109) if is_human else (177, 98, 98)
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
                stats=creature.aw_vw,
                defense_text=f"{creature.current_hp}/{creature.vw}",
                element=creature.element,
                type_line=f"Kreatur - {creature.element.value}",
                line_one=line_one,
                line_two=line_two,
                accent_color=accent,
                frame_color=accent,
                tapped=creature.tapped,
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
            old_screen = self.screen
            self.screen = surface
            try:
                self.draw_summoner_life_circle(life, 0, 0, think_progress)
            finally:
                self.screen = old_screen
            return surface

        return self.render_scaled_card_surface(2.0, _render)

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

    def handle_mouse_down(self, position: tuple[int, int]) -> None:
        hand_target = self.get_target_at_position("hand", position)
        if hand_target is not None and self.can_drag_hand_card(hand_target[1]):
            self.dragged_hand_card_id = hand_target[1]
            self.drag_start_pos = position
            self.drag_current_pos = position
            self.drag_active = False
            return
        self.handle_mouse_click(position)

    def handle_mouse_up(self, position: tuple[int, int]) -> None:
        if self.dragged_hand_card_id is None:
            return
        if self.drag_active and self.can_drag_hand_card_to_resource() and self.can_drop_on_resource_area(position):
            self.engine.play_hand_card_as_resource(self.dragged_hand_card_id)
        elif self.drag_active and self.can_drag_hand_card_to_creature() and self.can_drop_on_creature_area(position):
            self.engine.play_hand_card_as_creature(self.dragged_hand_card_id)
        else:
            self.engine.handle_click("hand", self.dragged_hand_card_id)
        self.clear_drag_state()
        self.update_decision_timer(force_reset=True)

    def handle_mouse_motion(self, position: tuple[int, int]) -> None:
        if self.dragged_hand_card_id is None:
            return
        self.drag_current_pos = position
        if self.drag_start_pos is None:
            return
        dx = position[0] - self.drag_start_pos[0]
        dy = position[1] - self.drag_start_pos[1]
        if abs(dx) > 8 or abs(dy) > 8:
            self.drag_active = True

    def handle_mouse_click(self, position: tuple[int, int]) -> None:
        for rect, spec in self.buttons:
            if spec.enabled and rect.collidepoint(position):
                if not self.handle_ui_action(spec.action):
                    self.engine.handle_action(spec.action)
                    self.update_decision_timer(force_reset=True)
                return
        for area in self.click_targets:
            target = self.get_target_at_position(area, position)
            if target is not None:
                area_name = "hand" if area == "mulligan_hand" else area
                self.engine.handle_click(area_name, target[1])
                self.update_decision_timer(force_reset=True)
                return

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        for key in self.click_targets:
            self.click_targets[key] = []
        self.buttons.clear()
        self.preview_targets.clear()
        self.creature_overlay_draws.clear()
        self.summoner_rects.clear()

        self.draw_enemy_area()
        self.draw_player_area()
        self.draw_combat_links()
        self.draw_creature_overlays()
        self.draw_damage_popups()
        self.draw_side_panel()
        self.draw_buttons()
        self.draw_dragged_card()

        if self.engine.phase == PHASE_MULLIGAN:
            self.draw_mulligan_overlay()
        if self.engine.pending_order is not None:
            self.draw_block_order_overlay()
        if self.engine.pending_dice_battle is not None:
            self.draw_dice_battle_overlay()
        if self.engine.phase == PHASE_GAME_OVER:
            self.draw_game_over_overlay()
        self.draw_card_preview_overlay()

        pygame.display.flip()


def run() -> None:
    app = TcgPrototypeApp()
    app.run()


