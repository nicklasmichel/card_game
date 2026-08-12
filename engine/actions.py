from __future__ import annotations

from typing import Optional

from core.models import Ability, CardInstance, PHASE_BUILDER_ABILITY, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_GAME_OVER


def get_selected_hand_card(self) -> Optional[CardInstance]:
    if len(self.selected_hand_ids) != 1:
        return None
    selected_id = self.selected_hand_ids[0]
    for card in self.active_player.hand:
        if card.instance_id == selected_id:
            return card
    return None


def toggle_hand_card(self, card_id: int) -> None:
    if self.phase == PHASE_BUILDER_ABILITY and self.active_player.is_human:
        if card_id in self.selected_hand_ids:
            self.cancel_builder_ability_use()
        else:
            self.begin_builder_ability_use(card_id)
        return
    if not self.active_player.is_human:
        return
    if card_id in self.selected_hand_ids:
        self.selected_hand_ids.clear()
    else:
        self.selected_hand_ids = [card_id]


def handle_action(self, action: str) -> None:
    if action == "confirm_ai_action":
        self.execute_prepared_ai_action()
        return
    if action == "exit_game":
        self.exit_requested = True
        return
    if action == "new_game":
        self.start_new_game()
        return
    if self.phase == PHASE_GAME_OVER:
        return
    human_defense_response = self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human
    if not self.active_player.is_human and self.phase not in {PHASE_DICE_BATTLE} and not human_defense_response:
        return

    if action == "builder_add_resource":
        self.builder_add_resource(self.active_player)
    elif action == "builder_pass_main_action":
        self.builder_pass_main_action(self.active_player)
    elif action == "builder_open_creature":
        self.begin_builder_creature_build()
    elif action == "builder_aw_down":
        self.adjust_builder_creature_stat("aw", -1)
    elif action == "builder_aw_up":
        self.adjust_builder_creature_stat("aw", 1)
    elif action == "builder_vw_down":
        self.adjust_builder_creature_stat("vw", -1)
    elif action == "builder_vw_up":
        self.adjust_builder_creature_stat("vw", 1)
    elif action == "builder_sw_down":
        self.adjust_builder_creature_stat("sw", -1)
    elif action == "builder_sw_up":
        self.adjust_builder_creature_stat("sw", 1)
    elif action == "builder_lw_down":
        self.adjust_builder_creature_stat("lw", -1)
    elif action == "builder_lw_up":
        self.adjust_builder_creature_stat("lw", 1)
    elif action == "builder_select_ability_haste":
        self.toggle_builder_creature_ability(Ability.HASTE)
    elif action == "builder_select_ability_flying":
        self.toggle_builder_creature_ability(Ability.FLYING)
    elif action == "builder_select_ability_vigilance":
        self.toggle_builder_creature_ability(Ability.VIGILANCE)
    elif action == "builder_select_ability_trample":
        self.toggle_builder_creature_ability(Ability.TRAMPLE)
    elif action == "builder_confirm_creature":
        self.confirm_builder_creature_build()
    elif action == "builder_cancel_creature":
        self.cancel_builder_creature_build()
    elif action.startswith("builder_use_card_"):
        self.begin_builder_ability_use(int(action.removeprefix("builder_use_card_")))
    elif action == "builder_mode_grant_ability":
        self.choose_builder_ability_mode("grant_ability")
    elif action == "builder_mode_damage":
        self.choose_builder_ability_mode("deal_damage")
    elif action == "builder_stat_aw":
        self.choose_builder_ability_mode("add_stat", "aw")
    elif action == "builder_stat_vw":
        self.choose_builder_ability_mode("add_stat", "vw")
    elif action == "builder_stat_sw":
        self.choose_builder_ability_mode("add_stat", "sw")
    elif action == "builder_stat_lw":
        self.choose_builder_ability_mode("add_stat", "lw")
    elif action == "builder_confirm_ability":
        self.resolve_builder_ability_use()
    elif action == "builder_cancel_ability":
        self.cancel_builder_ability_use()
    elif action == "builder_skip_ability":
        self.skip_builder_ability_phase()
    elif action == "to_combat":
        self.request_combat_transition()
    elif action == "confirm_attackers":
        self.confirm_attackers()
    elif action == "clear_blocks":
        self.clear_block_assignments()
    elif action == "confirm_blocks":
        self.finish_block_assignment()
    elif action == "end_dice_battle":
        self.end_dice_battle()
    elif action == "end_turn":
        self.request_end_turn()
