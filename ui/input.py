from __future__ import annotations


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
            self.engine.handle_action(spec.action)
            return
    for area in self.click_targets:
        target = self.get_target_at_position(area, position)
        if target is not None:
            area_name = "hand" if area == "mulligan_hand" else area
            self.engine.handle_click(area_name, target[1])
            return
