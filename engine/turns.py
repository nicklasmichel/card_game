from __future__ import annotations

from typing import List, Optional

from core.config import FIRE_SUMMONER_DRAW_THRESHOLD
from core.game_mode import is_builder_mode
from core.models import (
    BattlefieldCreature,
    CardInstance,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PHASE_MULLIGAN,
    PHASE_REACTION,
    PHASE_RECYCLE_PAYMENT,
    PHASE_SPELL_TARGETING,
    MAIN_PHASES,
    PlayerState,
    ReactionTrigger,
)


def apply_ai_mulligan(self) -> None:
    ai_indices = self.ai.mulligan_indices(self.ai_player.hand)
    if not ai_indices:
        self.ai_player.mulligan_used = True
        return
    to_replace = [self.ai_player.hand[index] for index in ai_indices]
    self.ai_player.hand = [card for idx, card in enumerate(self.ai_player.hand) if idx not in ai_indices]
    self.ai_player.deck.extend(to_replace)
    self.rng.shuffle(self.ai_player.deck)
    for _ in to_replace:
        self.draw_card_for_player(self.ai_player, "Mulligan")
        if self.phase == PHASE_GAME_OVER:
            return
    self.ai_player.mulligan_used = True
    self.log(f"Gegner fuehrt einen Mulligan mit {len(to_replace)} Karten durch.")


def apply_human_mulligan(self) -> None:
    if self.human_player.mulligan_used:
        return
    if self.selected_hand_ids:
        to_replace = [card for card in self.human_player.hand if card.instance_id in self.selected_hand_ids]
        self.human_player.hand = [card for card in self.human_player.hand if card.instance_id not in self.selected_hand_ids]
        self.human_player.deck.extend(to_replace)
        self.rng.shuffle(self.human_player.deck)
        for _ in to_replace:
            self.draw_card_for_player(self.human_player, "Mulligan")
            if self.phase == PHASE_GAME_OVER:
                return
        self.log(f"Spieler tauscht {len(to_replace)} Karten per Mulligan.")
    else:
        self.log("Spieler behaelt seine Starthand.")
    self.human_player.mulligan_used = True
    self.selected_hand_ids.clear()
    self.begin_first_turn()


def lose_game_from_empty_deck(self, player: PlayerState, source_name: str) -> None:
    if self.phase == PHASE_GAME_OVER:
        return
    winner = self.players[1 - player.player_id]
    self.phase = PHASE_GAME_OVER
    self.game_over_text = f"{winner.name} gewinnt. {player.name} kann durch {source_name} keine Karte mehr ziehen."
    self.log(self.game_over_text)
    self.persist_game_results_once()


def draw_card_for_player(self, player: PlayerState, source_name: str):
    if not player.deck:
        self.lose_game_from_empty_deck(player, source_name)
        return None
    drawn = player.draw_card()
    if drawn is not None and self.statistics is not None:
        self.statistics.register_draw(player.player_id)
        if drawn.was_recycled:
            self.statistics.register_recycled_card_drawn(player.player_id)
    return drawn


def begin_first_turn(self) -> None:
    self.active_player_index = self.starting_player_id
    self.turn_number = 0
    self.start_turn()


def start_turn(self) -> None:
    if is_builder_mode():
        self.start_builder_turn()
        return
    if hasattr(self.ai, "clear_active_turn_plan"):
        self.ai.clear_active_turn_plan()
    player = self.active_player
    self.turn_number += 1
    self.creatures_died_this_turn = 0
    player.untap_for_turn()
    self.log(f"Zug {self.turn_number}: {player.name} ist am Zug.")
    player.summoner_passive_draw_used_this_turn = False
    self.attack_declared_this_turn = False
    draw_allowed = not (player.player_id == self.starting_player_id and player.turns_started == 0)
    if draw_allowed:
        drawn = self.draw_card_for_player(player, "Ziehphase")
        if drawn is not None:
            self.log(f"{player.name} zieht eine Karte.")
        elif self.phase == PHASE_GAME_OVER:
            return
        else:
            self.log(f"{player.name} kann keine Karte ziehen.")
    else:
        self.log(f"{player.name} beginnt und zieht im ersten Zug keine Karte.")
    if (
        getattr(player, "summoner_key", "") == "fire"
        and player.life < FIRE_SUMMONER_DRAW_THRESHOLD
        and not player.summoner_passive_draw_used_this_turn
    ):
        player.summoner_passive_draw_used_this_turn = True
        drawn = self.draw_card_for_player(player, "Beschwoerer-Passiv")
        if drawn is not None:
            self.log(f"{player.name} zieht 1 zusaetzliche Karte durch den Beschwoerer.")
        elif self.phase != PHASE_GAME_OVER:
            self.log("Es kann keine zusaetzliche Karte durch den Beschwoerer gezogen werden.")
        if self.phase == PHASE_GAME_OVER:
            return
    player.turns_started += 1
    player.resources_played_this_turn = 0
    self.phase = PHASE_MAIN_1
    self.selected_hand_ids.clear()
    self.selected_attackers.clear()
    self.selected_blocker_id = None
    self.ai_turn_initialized = False
    self.pending_ai_action = None
    if self.statistics is not None:
        self.statistics.register_turn_count(self.turn_number)
    self.check_for_game_over()


def available_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return [creature for creature in player.battlefield if creature.is_ready()]


def available_blockers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return [
        creature
        for creature in player.battlefield
        if creature.is_ready()
        and not getattr(creature, "cannot_block", False)
        and self.get_creature_defense_value(creature) > 0
    ]


def get_mandatory_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return []


def has_playable_creature_in_hand(self, player: PlayerState) -> bool:
    return any(self.can_play_card(player, card) for card in player.hand)


def can_take_second_main_actions(self, player: PlayerState) -> bool:
    if is_builder_mode():
        return False
    if player != self.active_player:
        return False
    if player.resources_played_this_turn < 2 and bool(player.hand):
        return True
    current_phase = self.phase
    try:
        self.phase = PHASE_MAIN_2
        return any(self.can_play_card(player, card) for card in player.hand)
    finally:
        self.phase = current_phase


def enter_second_main_phase(self) -> None:
    self.clear_combat_temporary_effects()
    if is_builder_mode():
        self.end_turn()
        return
    if not getattr(self, "attack_declared_this_turn", False):
        self.log("Zweite Hauptphase wird uebersprungen. Es gab keinen Angriff.")
        self.end_turn()
        return
    if not self.can_take_second_main_actions(self.active_player):
        self.log("Zweite Hauptphase wird uebersprungen. Es sind keine weiteren Aktionen moeglich.")
        self.end_turn()
        return
    self.phase = PHASE_MAIN_2
    self.log("Zweite Hauptphase begonnen.")


def begin_main_phase_priority_window(self, phase: str, continuation) -> None:
    trigger = ReactionTrigger.MAIN_1_PRIORITY if phase == PHASE_MAIN_1 else ReactionTrigger.MAIN_2_PRIORITY
    self.begin_general_spell_window(
        trigger=trigger,
        first_responder_id=1 - self.active_player.player_id,
        resume_phase=phase,
        continuation=continuation,
    )


def request_combat_transition(self) -> None:
    if self.phase != PHASE_MAIN_1:
        return
    if not self.active_player.battlefield:
        self.log("Kampfphase wird automatisch uebersprungen. Keine eigenen Kreaturen im Spiel.")
        self.enter_second_main_phase()
        return
    if self.available_attackers(self.active_player):
        self.begin_main_phase_priority_window(PHASE_MAIN_1, self.begin_attack_declaration)
        return
    self.log("Keine Kreaturen koennen angreifen. Die Kampfphase kann nicht begonnen werden.")


def enter_combat_or_second_main(self) -> None:
    if self.phase != PHASE_MAIN_1:
        return
    if not self.active_player.battlefield:
        self.log("Kampfphase wird automatisch uebersprungen. Keine eigenen Kreaturen im Spiel.")
        self.enter_second_main_phase()
        return
    if self.available_attackers(self.active_player):
        self.begin_attack_declaration()
        return
    self.log("Keine Kreaturen koennen angreifen. Die Kampfphase kann nicht begonnen werden.")


def auto_resolve_human_no_blockers_if_needed(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    if not self.defending_player.is_human:
        return
    if self.available_blockers(self.defending_player):
        return
    self.log("Keine Kreaturen koennen blocken. Schaden geht automatisch durch.")
    self.finish_block_assignment()


def resolve_stalled_dice_battle_if_needed(self) -> None:
    if self.phase != PHASE_DICE_BATTLE or self.pending_dice_battle is None:
        return
    return


def handle_human_timeout(self) -> None:
    if is_builder_mode() and self.phase == PHASE_BUILDER_CREATURE and self.active_player.is_human:
        self.log("Zeit abgelaufen. Spieler bricht den Kreaturenbau ab.")
        self.cancel_builder_creature_build()
        return
    if self.phase == PHASE_MULLIGAN:
        self.log("Zeit abgelaufen. Spieler behaelt seine Starthand.")
        self.apply_human_mulligan()
        return
    if self.phase == PHASE_MAIN_1 and self.active_player.is_human:
        if self.available_attackers(self.active_player):
            self.log("Zeit abgelaufen. Spieler wechselt in die Kampfphase.")
            self.request_combat_transition()
        else:
            self.log("Zeit abgelaufen. Spieler beendet seinen Zug.")
            self.request_end_turn()
        return
    if self.phase == PHASE_MAIN_2 and self.active_player.is_human:
        self.log("Zeit abgelaufen. Spieler beendet seinen Zug.")
        self.request_end_turn()
        return
    if self.phase == PHASE_RECYCLE_PAYMENT and self.active_player.is_human:
        self.log("Zeit abgelaufen. Spieler bricht die Recycle-Auswahl ab.")
        self.cancel_recycle_payment()
        return
    if self.phase == PHASE_SPELL_TARGETING and self.active_player.is_human:
        self.log("Zeit abgelaufen. Spieler bricht die Zauberauswahl ab.")
        self.cancel_pending_spell_cast()
        return
    if self.phase == PHASE_REACTION and self.reaction_priority_player_id == self.human_player.player_id:
        self.log("Zeit abgelaufen. Spieler passt im Reaktionsfenster.")
        self.pass_reaction()
        return
    if self.phase == PHASE_FORCED_DISCARD and self.pending_forced_discard is not None:
        required = self.pending_forced_discard.required_count
        chosen = self.human_player.hand[:required]
        self.pending_forced_discard.selected_card_ids = [card.instance_id for card in chosen]
        self.selected_hand_ids = list(self.pending_forced_discard.selected_card_ids)
        self.log("Zeit abgelaufen. Spieler wirft Handkarten automatisch ab.")
        self.confirm_forced_discard()
        return
    if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
        self.log("Zeit abgelaufen. Kein Angriff deklariert.")
        self.confirm_attackers()
        return
    if self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
        self.log("Zeit abgelaufen. Keine Blocker deklariert.")
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
    return player == self.active_player and self.phase in MAIN_PHASES


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
