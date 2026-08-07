from __future__ import annotations

import pygame

from core.models import (
    PHASE_GAME_OVER,
    MAIN_PHASES,
    PHASE_MULLIGAN,
)
from ui.style import BG_COLOR, FPS


def run(self) -> None:
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                self.handle_ui_action("ui_toggle_pause")
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                self.trigger_primary_action_button()
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
        if not self.paused and not self.engine.has_pending_ai_action():
            self.engine.prepare_ai_turn_action()
        self.engine.auto_resolve_human_no_blockers_if_needed()
        self.engine.resolve_stalled_dice_battle_if_needed()
        if self.engine.exit_requested:
            running = False
        self.draw()
        self.clock.tick_busy_loop(FPS)

    pygame.quit()


def get_decision_marker(self) -> tuple[int, str, str] | None:
    return None


def update_decision_timer(self, force_reset: bool = False) -> None:
    return


def get_decision_duration_ms(self, marker: tuple[int, str, str] | None) -> int:
    return 0


def is_timed_decision_ready(self) -> bool:
    return False


def process_timed_decision(self) -> None:
    return


def get_think_progress(self, player) -> float | None:
    return None


def handle_ui_action(self, action: str) -> bool:
    if action == "ui_toggle_enemy_hand":
        self.show_enemy_hand_cards = not self.show_enemy_hand_cards
        return True
    if action == "ui_toggle_pause":
        now = pygame.time.get_ticks()
        if self.paused:
            if self.pause_started_at_ms is not None:
                paused_duration = now - self.pause_started_at_ms
                for popup in self.damage_popups:
                    popup["started_at_ms"] += paused_duration
                for reveal in self.recycle_reveals:
                    reveal["started_at_ms"] += paused_duration
                for animation in self.creature_lunges.values():
                    animation["started_at_ms"] += paused_duration
            self.paused = False
            self.pause_started_at_ms = None
        else:
            self.paused = True
            self.pause_started_at_ms = now
        return True
    return False


def trigger_primary_action_button(self) -> None:
    for _rect, spec in self.buttons:
        if not spec.enabled:
            continue
        if not self.handle_ui_action(spec.action):
            self.engine.handle_action(spec.action)
            self.update_decision_timer(force_reset=True)
        return


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
        self.engine.play_hand_card_in_summoning_zone(self.dragged_hand_card_id)
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
    enemy_deck_target = self.get_target_at_position("enemy_deck", position)
    if enemy_deck_target is not None:
        self.handle_ui_action("ui_toggle_enemy_hand")
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
    self.combat_overlay_card_rects.clear()
    self.summoner_rects.clear()

    previous_show_enemy_hand_cards = self.show_enemy_hand_cards
    reveal_enemy_hand_from_effect = any(
        getattr(creature, "reveal_opponent_hand", False)
        for creature in self.engine.human_player.battlefield
    )
    self.show_enemy_hand_cards = self.show_enemy_hand_cards or reveal_enemy_hand_from_effect
    self.draw_enemy_area()
    self.draw_player_area()
    self.draw_combat_links()
    self.draw_creature_overlays()
    self.draw_damage_popups()
    self.draw_side_panel()
    self.draw_recycle_reveals()
    self.draw_buttons()
    self.draw_dragged_card()

    if self.engine.phase == PHASE_MULLIGAN:
        self.draw_mulligan_overlay()
    if self.engine.pending_dice_battle is not None:
        self.draw_dice_battle_overlay()
    self.draw_discard_target_overlay()
    self.draw_reaction_focus_preview()
    self.draw_pause_overlay()
    if self.engine.phase == PHASE_GAME_OVER:
        self.draw_game_over_overlay()
    self.draw_card_preview_overlay()
    self.show_enemy_hand_cards = previous_show_enemy_hand_cards

    pygame.display.flip()
