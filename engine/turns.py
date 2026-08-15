from __future__ import annotations

from typing import List, Optional

from core.models import BattlefieldCreature, PHASE_BUILDER_ABILITY, PHASE_BUILDER_CREATURE, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_MAIN_1, PlayerState


def apply_ai_mulligan(self) -> None:
    return


def apply_human_mulligan(self) -> None:
    return


def lose_game_from_empty_deck(self, player: PlayerState, source_name: str) -> None:
    winner = self.players[1 - player.player_id]
    self.phase = "Game Over"
    self.game_over_text = f"{winner.name} wins. {player.name} can no longer draw because of {source_name}."
    self.log(self.game_over_text)
    self.persist_game_results_once()


def draw_card_for_player(self, player: PlayerState, source_name: str):
    return None


def begin_first_turn(self) -> None:
    self.active_player_index = self.starting_player_id
    self.turn_number = 0
    self.start_turn()


def start_turn(self) -> None:
    self.start_builder_turn()


def available_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return [creature for creature in player.battlefield if creature.is_ready()]


def available_blockers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return [
        creature
        for creature in player.battlefield
        if not creature.tapped
        and not getattr(creature, "cannot_block", False)
    ]


def get_mandatory_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return []


def has_playable_creature_in_hand(self, player: PlayerState) -> bool:
    return False


def can_take_second_main_actions(self, player: PlayerState) -> bool:
    return False


def enter_second_main_phase(self) -> None:
    self.clear_combat_temporary_effects()
    self.finish_builder_turn_after_combat()
    self.end_turn()


def begin_main_phase_priority_window(self, phase: str, continuation) -> None:
    continuation()


def request_combat_transition(self) -> None:
    if self.phase not in {PHASE_MAIN_1, PHASE_BUILDER_ABILITY}:
        return
    if not self.active_player.battlefield:
        self.log("Combat is skipped automatically. No friendly creatures are in play.")
        self.enter_second_main_phase()
        return
    if self.available_attackers(self.active_player):
        self.begin_main_phase_priority_window(PHASE_MAIN_1, self.begin_attack_declaration)
        return
    self.log("No creatures can attack. Combat cannot begin.")


def enter_combat_or_second_main(self) -> None:
    if self.phase not in {PHASE_MAIN_1, PHASE_BUILDER_ABILITY}:
        return
    if not self.active_player.battlefield:
        self.log("Combat is skipped automatically. No friendly creatures are in play.")
        self.enter_second_main_phase()
        return
    if self.available_attackers(self.active_player):
        self.begin_attack_declaration()
        return
    self.log("No creatures can attack. Combat cannot begin.")


def auto_resolve_human_no_blockers_if_needed(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    if not self.defending_player.is_human:
        return
    if self.available_blockers(self.defending_player):
        return
    self.log("No creatures can block. Damage goes through automatically.")
    self.finish_block_assignment()


def resolve_stalled_dice_battle_if_needed(self) -> None:
    if self.phase != PHASE_DICE_BATTLE or self.pending_dice_battle is None:
        return


def handle_human_timeout(self) -> None:
    if self.phase == PHASE_BUILDER_CREATURE and self.active_player.is_human:
        self.log(f"Time expired. {self.active_player.name} cancels creature building.")
        self.cancel_builder_creature_build()
        return
    if self.phase == PHASE_BUILDER_ABILITY and self.active_player.is_human:
        self.log(f"Time expired. {self.active_player.name} skips the ability phase.")
        self.skip_builder_ability_phase()
        return
    if self.phase == PHASE_MAIN_1 and self.active_player.is_human:
        if self.available_attackers(self.active_player):
            self.log(f"Time expired. {self.active_player.name} moves to combat.")
            self.request_combat_transition()
        else:
            self.log(f"Time expired. {self.active_player.name} ends the turn.")
            self.request_end_turn()
        return
    if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
        self.log("Time expired. No attackers declared.")
        self.confirm_attackers()
        return
    if self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
        self.log("Time expired. No blockers declared.")
        self.finish_block_assignment()


def get_creature_by_id(self, creature_id: int) -> Optional[BattlefieldCreature]:
    for player in self.players:
        for creature in player.battlefield:
            if creature.unit_id == creature_id:
                return creature
    return None


def get_unit_by_id(self, unit_id: int) -> Optional[BattlefieldCreature]:
    return self.get_creature_by_id(unit_id)


def get_unit_owner(self, unit_id: int) -> Optional[PlayerState]:
    for player in self.players:
        for unit in player.battlefield:
            if unit.unit_id == unit_id:
                return player
    return None


def is_own_main_phase(self, player: PlayerState) -> bool:
    return player == self.active_player and self.phase == PHASE_MAIN_1


def has_more_dice_battles_after_current(self) -> bool:
    if self.pending_dice_battle is None:
        return False
    for attacker_id in self.combat_queue[self.current_attack_index + 1:]:
        next_attacker = self.get_unit_by_id(attacker_id)
        if next_attacker is None or self.is_creature_destroyed(next_attacker):
            continue
        blocker_id = self.block_assignments.get(attacker_id)
        if blocker_id is None:
            continue
        blocker = self.get_unit_by_id(blocker_id)
        if blocker is not None and not self.is_creature_destroyed(blocker):
            return True
    return False


def clear_end_of_turn_temporary_effects(self) -> None:
    self.active_player.creature_cost_reduction_this_turn = 0
    self.clear_combat_temporary_effects()
    for player in self.players:
        for creature in player.battlefield:
            creature.temporary_aw_bonus = 0
            creature.temporary_abilities.clear()


def clear_combat_temporary_effects(self) -> None:
    for player in self.players:
        for creature in player.battlefield:
            creature.temporary_combat_aw_bonus = 0
            creature.temporary_combat_sw_bonus = 0
