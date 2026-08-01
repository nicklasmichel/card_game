from __future__ import annotations


def handle_mouse_down(self, position: tuple[int, int]) -> None:
    hand_target = self.get_target_at_position("hand", position)
    if hand_target is not None and self.can_drag_hand_card(hand_target[1]):
        rect, card_id = hand_target
        self.dragged_hand_card_id = card_id
        card = next(
            (existing for existing in self.engine.human_player.hand if existing.instance_id == self.dragged_hand_card_id),
            None,
        )
        self.dragged_card_surface = self.build_hand_card_surface(card, selected=True) if card is not None else None
        self.drag_start_pos = position
        self.drag_current_pos = position
        self.drag_grab_offset = (position[0] - rect.x, position[1] - rect.y)
        self.drag_active = True
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
