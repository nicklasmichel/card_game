from __future__ import annotations

import pygame

from core.models import (
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MULLIGAN,
    PHASE_RECYCLE_PAYMENT,
    PHASE_RESOURCE,
    PHASE_SUMMONING,
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
        self.clock.tick_busy_loop(FPS)

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
    if self.engine.phase == PHASE_RECYCLE_PAYMENT:
        return (self.engine.active_player.player_id, self.engine.phase, "recycle")
    if self.engine.phase == PHASE_FORCED_DISCARD:
        return (self.engine.human_player.player_id, self.engine.phase, "forced_discard")
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
    if self.engine.pending_order is not None:
        self.draw_block_order_overlay()
    if self.engine.pending_dice_battle is not None:
        self.draw_dice_battle_overlay()
    if self.engine.phase == PHASE_GAME_OVER:
        self.draw_game_over_overlay()
    self.draw_card_preview_overlay()
    self.show_enemy_hand_cards = previous_show_enemy_hand_cards

    pygame.display.flip()
