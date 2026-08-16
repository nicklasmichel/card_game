from __future__ import annotations

import pygame

from core.models import PHASE_GAME_OVER
from ui.style import BG_COLOR, FPS


def run(self) -> None:
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif self.match_mode_selection_open:
                if event.type == pygame.KEYDOWN:
                    self.handle_match_mode_keydown(event)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_match_mode_click(event.pos)
            elif self.network_blocks_gameplay():
                continue
            elif (
                event.type == pygame.KEYDOWN
                and event.key == pygame.K_RETURN
                and not self.start_player_selection_open
            ):
                self.handle_ui_action("ui_toggle_pause")
            elif (
                event.type == pygame.KEYDOWN
                and event.key == pygame.K_SPACE
                and not self.start_player_selection_open
            ):
                if not self.primary_action_space_down:
                    self.primary_action_space_down = True
                    self.trigger_primary_action_button()
            elif event.type == pygame.KEYUP and event.key == pygame.K_SPACE:
                self.primary_action_space_down = False
            elif event.type == pygame.MOUSEWHEEL:
                self.handle_log_scroll(-event.y * 36)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.start_player_selection_open:
                    self.handle_start_player_selection_click(event.pos)
                else:
                    self.handle_mouse_down(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                if not self.start_player_selection_open:
                    self.handle_preview_start(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if not self.start_player_selection_open:
                    self.handle_mouse_up(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                if not self.start_player_selection_open:
                    self.handle_preview_stop()
            elif event.type == pygame.MOUSEMOTION:
                if not self.start_player_selection_open:
                    self.handle_mouse_motion(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                direction = -36 if event.button == 4 else 36
                self.handle_log_scroll(direction)

        self.update_network_state()
        self.consume_visual_events()
        gameplay_overlay_open = (
            self.match_mode_selection_open
            or self.start_player_selection_open
            or self.network_blocks_gameplay()
        )
        self.session.update(
            allow_ai=not self.paused and not gameplay_overlay_open,
            allow_automatic_rules=not gameplay_overlay_open,
            allow_commands=not self.paused and not gameplay_overlay_open,
        )
        self.update_gameplay_timers()
        if self.session.should_exit:
            running = False
        self.draw()
        self.clock.tick_busy_loop(FPS)

    self.shutdown_network()
    self.session.close()
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
    if action == "new_game":
        self.open_start_player_selection()
        return True
    if action == "ui_toggle_pause":
        now = pygame.time.get_ticks()
        if self.paused:
            if self.pause_started_at_ms is not None:
                paused_duration = now - self.pause_started_at_ms
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


def handle_start_player_selection_click(self, position: tuple[int, int]) -> None:
    for rect, selection in self.start_player_option_rects:
        if rect.collidepoint(position):
            self.start_new_game_with_selected_player(selection)
            return


def trigger_primary_action_button(self) -> None:
    for _rect, spec in self.buttons:
        if not spec.enabled:
            continue
        if not self.handle_ui_action(spec.action):
            self.session.submit_action(spec.action)
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
    if self.drag_active and self.can_drag_hand_card_to_creature() and self.can_drop_on_creature_area(position):
        self.session.submit_hand_card_play(self.dragged_hand_card_id)
    else:
        self.session.submit_click("hand", self.dragged_hand_card_id)
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
                self.session.submit_action(spec.action)
                self.update_decision_timer(force_reset=True)
            return
    for area in self.click_targets:
        target = self.get_target_at_position(area, position)
        if target is not None:
            self.session.submit_click(area, target[1])
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
    self.creature_rects.clear()
    self.summoner_rects.clear()

    self.draw_enemy_area()
    self.draw_player_area()
    self.draw_combat_links()
    self.draw_creature_overlays()
    self.draw_damage_popups()
    self.draw_side_panel()
    self.draw_buttons()
    self.draw_dragged_card()

    if getattr(self.engine, "pending_dice_battles", None) or self.engine.pending_dice_battle is not None:
        self.draw_dice_battle_overlay()
    self.draw_pause_overlay()
    if self.engine.phase == PHASE_GAME_OVER:
        self.draw_game_over_overlay()
    self.draw_start_player_overlay()
    self.draw_card_preview_overlay()
    self.draw_network_status_overlay()
    self.draw_match_mode_overlay()

    pygame.display.flip()
