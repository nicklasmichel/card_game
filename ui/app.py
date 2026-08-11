from __future__ import annotations

import math
import os
from typing import Callable, Dict, List, Tuple

import pygame

from core.game_mode import is_builder_mode
from core.game_logic import GameEngine
from core.models import (
    ButtonSpec,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PHASE_RECYCLE_PAYMENT,
    PHASE_MULLIGAN,
)
from ui.card_rendering import (
    blit_centered_text,
    blit_centered_text_to_surface,
    blit_symbol_image,
    blit_text_to_surface,
    blit_wrapped_text,
    build_hand_card_surface,
    build_card_surface,
    build_resource_back_surface,
    can_drag_hand_card,
    can_drag_hand_card_to_creature,
    can_drag_hand_card_to_resource,
    can_drop_on_creature_area,
    can_drop_on_resource_area,
    clear_drag_state,
    draw_art_panel,
    draw_card_badge,
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
    draw_summoner_footer,
    draw_summoner_life_circle,
    fit_text,
    get_card_preview_ability_details,
    get_display_builder_creature_stats,
    get_display_creature_stats,
    get_display_template_stats,
    get_ability_names,
    get_card_ability_lines,
    get_card_ability_lines_from_creature,
    get_creature_type_line,
    get_element_color,
    get_target_at_position,
    wrap_text,
)
from ui.assets import (
    build_preview_creature_surface,
    build_preview_deck_surface,
    build_preview_hand_card_surface,
    build_preview_hidden_hand_surface,
    build_preview_resource_surface,
    build_preview_summoner_surface,
    build_recycle_reveal_surfaces,
    draw_card_preview_overlay,
    handle_preview_start,
    handle_preview_stop,
    load_card_art_images,
    load_resource_back_images,
    load_summoner_images,
    load_ui_symbol_images,
    render_scaled_card_surface,
)
from ui.layout import (
    blit_text,
    draw_arrowhead,
    draw_builder_resource_stack_card,
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
    draw_side_piles,
    draw_side_log,
    draw_side_overview,
    draw_side_panel,
    format_target_ref,
    get_creature_screen_positions,
    get_playfield_sections,
    get_side_panel_layout,
    handle_log_scroll,
)
from ui.overlays import (
    draw_discard_target_overlay,
    draw_dice_battle_overlay,
    draw_game_over_overlay,
    draw_mulligan_overlay,
    draw_pause_overlay,
    draw_reaction_focus_preview,
)
from ui.runtime import (
    draw,
    get_decision_marker,
    get_think_progress,
    handle_mouse_click,
    handle_mouse_down,
    handle_mouse_motion,
    handle_mouse_up,
    handle_ui_action,
    run,
    trigger_primary_action_button,
    update_decision_timer,
)
from ui.visuals import (
    consume_visual_events,
    draw_combat_damage_popups,
    draw_creature_overlays,
    draw_damage_popups,
    draw_recycle_reveals,
    prune_finished_visuals,
)



class TcgPrototypeApp:
    draw_playfield_section_box = draw_playfield_section_box
    build_hand_card_surface = build_hand_card_surface
    draw_hand_card = draw_hand_card
    draw_hidden_hand_card = draw_hidden_hand_card
    draw_dragged_card = draw_dragged_card
    draw_resource_card = draw_resource_card
    draw_summoner_card = draw_summoner_card
    draw_summoner_footer = draw_summoner_footer
    draw_summoner_life_circle = draw_summoner_life_circle
    draw_card_badge = draw_card_badge
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
    get_display_builder_creature_stats = get_display_builder_creature_stats
    get_display_creature_stats = get_display_creature_stats
    get_display_template_stats = get_display_template_stats
    get_card_preview_ability_details = get_card_preview_ability_details
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
    draw_enemy_area = draw_enemy_area
    draw_player_area = draw_player_area
    draw_combat_links = draw_combat_links
    get_creature_screen_positions = get_creature_screen_positions
    get_playfield_sections = get_playfield_sections
    draw_polyline = draw_polyline
    draw_arrowhead = draw_arrowhead
    draw_builder_resource_stack_card = draw_builder_resource_stack_card
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
    draw_side_piles = draw_side_piles
    format_target_ref = format_target_ref
    handle_log_scroll = handle_log_scroll
    draw_mulligan_overlay = draw_mulligan_overlay
    draw_discard_target_overlay = draw_discard_target_overlay
    draw_dice_battle_overlay = draw_dice_battle_overlay
    draw_game_over_overlay = draw_game_over_overlay
    draw_pause_overlay = draw_pause_overlay
    draw_reaction_focus_preview = draw_reaction_focus_preview
    blit_text = blit_text
    draw_section_box = draw_section_box
    load_resource_back_images = load_resource_back_images
    load_summoner_images = load_summoner_images
    load_ui_symbol_images = load_ui_symbol_images
    load_card_art_images = load_card_art_images
    render_scaled_card_surface = render_scaled_card_surface
    build_preview_hand_card_surface = build_preview_hand_card_surface
    build_preview_hidden_hand_surface = build_preview_hidden_hand_surface
    build_preview_resource_surface = build_preview_resource_surface
    build_preview_deck_surface = build_preview_deck_surface
    build_preview_creature_surface = build_preview_creature_surface
    build_preview_summoner_surface = build_preview_summoner_surface
    build_recycle_reveal_surfaces = build_recycle_reveal_surfaces
    handle_preview_start = handle_preview_start
    handle_preview_stop = handle_preview_stop
    draw_card_preview_overlay = draw_card_preview_overlay
    consume_visual_events = consume_visual_events
    prune_finished_visuals = prune_finished_visuals
    draw_damage_popups = draw_damage_popups
    draw_combat_damage_popups = draw_combat_damage_popups
    draw_creature_overlays = draw_creature_overlays
    draw_recycle_reveals = draw_recycle_reveals
    run = run
    get_decision_marker = get_decision_marker
    update_decision_timer = update_decision_timer
    get_think_progress = get_think_progress
    handle_ui_action = handle_ui_action
    trigger_primary_action_button = trigger_primary_action_button
    handle_mouse_down = handle_mouse_down
    handle_mouse_up = handle_mouse_up
    handle_mouse_motion = handle_mouse_motion
    handle_mouse_click = handle_mouse_click
    draw = draw

    def __init__(self) -> None:
        os.environ["SDL_VIDEO_CENTERED"] = "1"
        pygame.init()
        display_info = pygame.display.Info()
        self.window_width = display_info.current_w
        self.window_height = display_info.current_h
        display_flags = pygame.NOFRAME | pygame.DOUBLEBUF
        try:
            self.screen = pygame.display.set_mode(
                (self.window_width, self.window_height),
                display_flags,
                vsync=1,
            )
        except TypeError:
            self.screen = pygame.display.set_mode(
                (self.window_width, self.window_height),
                display_flags,
            )
        self.card_width = 172 if self.window_width >= 1800 else 151
        self.card_height = int(self.card_width * 1.26)
        self.card_gap = 18 if self.window_width >= 1800 else 13
        if is_builder_mode():
            self.side_panel_width = 470 if self.window_width >= 1800 else 430
        else:
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
        self.card_art_images = self.load_card_art_images()
        self.log_scroll_offset = 0
        self.log_viewport_rect = pygame.Rect(0, 0, 0, 0)
        self.buttons: List[Tuple[pygame.Rect, ButtonSpec]] = []
        self.show_enemy_hand_cards = False
        self.primary_action_space_down = False
        self.paused = False
        self.pause_started_at_ms: int | None = None
        self.player_creature_rect = pygame.Rect(0, 0, 0, 0)
        self.player_resource_rect = pygame.Rect(0, 0, 0, 0)
        self.dragged_hand_card_id: int | None = None
        self.drag_start_pos: tuple[int, int] | None = None
        self.drag_current_pos: tuple[int, int] | None = None
        self.drag_grab_offset: tuple[int, int] | None = None
        self.drag_active = False
        self.dragged_card_surface: pygame.Surface | None = None
        self.last_rendered_card_surface: pygame.Surface | None = None
        self.last_preview_builder: Callable[[], pygame.Surface] | None = None
        self.last_preview_info_builder: Callable[[], list[tuple[str, str]]] | None = None
        self.preview_targets: List[Tuple] = []
        self.preview_builder: Callable[[], pygame.Surface] | None = None
        self.preview_info_builder: Callable[[], list[tuple[str, str]]] | None = None
        self.preview_surface: pygame.Surface | None = None
        self.damage_popups: List[dict] = []
        self.recycle_reveals: List[dict] = []
        self.creature_lunges: Dict[int, dict] = {}
        self.creature_overlay_draws: List[tuple] = []
        self.combat_overlay_card_rects: Dict[str, pygame.Rect] = {}
        self.creature_rects: Dict[int, pygame.Rect] = {}
        self.summoner_rects: Dict[int, pygame.Rect] = {}
        self.click_targets: Dict[str, List[Tuple[pygame.Rect, int]]] = {
            "hand": [],
            "enemy_deck": [],
            "player_summoner": [],
            "enemy_summoner": [],
            "player_creatures": [],
            "enemy_creatures": [],
            "combat_lane": [],
            "mulligan_hand": [],
            "player_resources": [],
            "discard_cards": [],
        }

    def get_summoner_rect_for_player(self, player) -> pygame.Rect:
        sections = self.get_playfield_sections()
        if is_builder_mode():
            hand_rect = sections["player_hand"] if player.player_id == self.engine.human_player.player_id else sections["enemy_hand"]
            return pygame.Rect(hand_rect.right - self.card_width - 18, hand_rect.y + 8, self.card_width, self.card_height)
        resource_rect = sections["player_resources"] if player.player_id == self.engine.human_player.player_id else sections["enemy_resources"]
        start_x = resource_rect.x + 10
        available_width = resource_rect.width - 20
        summoner_x = start_x + max(0, (available_width - self.card_width) // 2)
        return pygame.Rect(summoner_x, resource_rect.y + 10, self.card_width, self.card_height)

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
        dx = target_rect.centerx - base_rect.centerx
        dy = target_rect.centery - base_rect.centery
        distance = max(1.0, (dx * dx + dy * dy) ** 0.5)
        stop_gap = 42.0
        charge_ratio = max(0.0, min(1.0, (distance - stop_gap) / distance))
        max_offset_x = dx * charge_ratio
        max_offset_y = dy * charge_ratio

        forward_duration = 620.0
        hold_duration = 110.0
        return_duration = 820.0
        total_duration = forward_duration + hold_duration + return_duration

        if elapsed >= total_duration:
            return (0, 0)

        if elapsed <= forward_duration:
            t = max(0.0, min(1.0, elapsed / forward_duration))
            progress = 1.0 - ((1.0 - t) ** 3)
        elif elapsed <= forward_duration + hold_duration:
            progress = 1.0
        else:
            t = max(0.0, min(1.0, (elapsed - forward_duration - hold_duration) / return_duration))
            progress = 0.5 * (1.0 + math.cos(math.pi * t))

        return (round(max_offset_x * progress), round(max_offset_y * progress))


def run() -> None:
    app = TcgPrototypeApp()
    app.run()


