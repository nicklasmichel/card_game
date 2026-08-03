from __future__ import annotations

from typing import List, Optional

from core.models import (
    BattlefieldCreature,
    CardInstance,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MULLIGAN,
    PHASE_REACTION,
    PHASE_RECYCLE_PAYMENT,
    PHASE_RESOURCE,
    PHASE_SPELL_TARGETING,
    PHASE_SUMMONING,
    PlayerState,
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
    player = self.active_player
    self.turn_number += 1
    self.creatures_died_this_turn = 0
    player.untap_for_turn()
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
        self.log(f"{player.name} ist Startspieler und zieht im ersten Zug keine Karte.")
    player.turns_started += 1
    player.resources_played_this_turn = 0
    self.phase = PHASE_RESOURCE
    self.selected_hand_ids.clear()
    self.selected_attackers.clear()
    self.selected_blocker_id = None
    self.ai_turn_initialized = False
    if self.statistics is not None:
        self.statistics.register_turn_count(self.turn_number)
    self.log(f"Zug {self.turn_number}: {player.name} ist am Zug.")
    self.check_for_game_over()


def available_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return [creature for creature in player.battlefield if creature.is_ready()]


def available_blockers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return [creature for creature in player.battlefield if creature.is_ready() and not getattr(creature, "cannot_block", False)]


def get_mandatory_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
    return [creature for creature in available_attackers(self, player) if getattr(creature, "must_attack_each_turn", False)]


def has_playable_creature_in_hand(self, player: PlayerState) -> bool:
    return any(self.can_play_card(player, card) for card in player.hand)


def enter_summoning_phase(self) -> None:
    self.phase = PHASE_SUMMONING
    self.log("Beschwoerungsphase begonnen.")
    self.auto_advance_human_summoning_phase_if_needed()


def auto_advance_human_summoning_phase_if_needed(self) -> None:
    if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
        return
    if self.has_playable_creature_in_hand(self.active_player):
        return
    self.log("Keine Karte kann ausgespielt werden. Kampfphase beginnt automatisch.")
    self.begin_attack_declaration()


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
    battle = self.pending_dice_battle
    if battle.resolution_complete:
        return
    if battle.pending_comparison is not None:
        if not battle.pending_comparison.human_can_adapt:
            self.resolve_pending_comparison(use_human_adaptation=False)
        return
    human_is_attacker = battle.attacker_owner == self.human_player.player_id
    human_dice = battle.attacker_dice if human_is_attacker else battle.blocker_dice
    enemy_dice = battle.blocker_dice if human_is_attacker else battle.attacker_dice
    if any(not die.used for die in human_dice) and any(not die.used for die in enemy_dice):
        return
    attacker = self.get_unit_by_id(battle.attacker_id)
    blocker = self.get_unit_by_id(battle.blocker_id)
    if attacker is None or blocker is None:
        battle.resolution_complete = True
        return
    self.finalize_or_continue_dice_battle(battle, attacker, blocker)


def handle_human_timeout(self) -> None:
    if self.phase == PHASE_MULLIGAN:
        self.log("Zeit abgelaufen. Spieler behaelt seine Starthand.")
        self.apply_human_mulligan()
        return
    if self.phase == PHASE_RESOURCE and self.active_player.is_human:
        self.log("Zeit abgelaufen. Keine Ressource gespielt.")
        self.enter_summoning_phase()
        return
    if self.phase == PHASE_SUMMONING and self.active_player.is_human:
        self.log("Zeit abgelaufen. Keine Kreatur gespielt.")
        self.begin_attack_declaration()
        return
    if self.phase == PHASE_RECYCLE_PAYMENT and self.active_player.is_human:
        self.log("Zeit abgelaufen. Recycle-Auswahl wurde abgebrochen.")
        self.cancel_recycle_payment()
        return
    if self.phase == PHASE_SPELL_TARGETING and self.active_player.is_human:
        self.log("Zeit abgelaufen. Zauberauswahl wurde abgebrochen.")
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
        self.log("Zeit abgelaufen. Handkarten wurden automatisch abgeworfen.")
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


def has_more_dice_battles_after_current(self) -> bool:
    battle = self.pending_dice_battle
    if battle is None:
        return False

    attacker = self.get_unit_by_id(battle.attacker_id)
    if attacker is not None and attacker.current_hp > 0:
        for blocker_id in self.current_blocker_order[self.current_blocker_index:]:
            blocker = self.get_unit_by_id(blocker_id)
            if blocker is not None and blocker.current_hp > 0:
                return True

    for attacker_id in self.combat_queue[self.current_attack_index + 1:]:
        next_attacker = self.get_unit_by_id(attacker_id)
        if next_attacker is None or next_attacker.current_hp <= 0:
            continue
        for blocker_id in self.block_assignments.get(attacker_id, []):
            blocker = self.get_unit_by_id(blocker_id)
            if blocker is not None and blocker.current_hp > 0:
                return True
    return False


def clear_end_of_turn_temporary_effects(self) -> None:
    self.active_player.creature_cost_reduction_this_turn = 0
    self.active_player.attackers_die_bonus_this_turn = 0
    self.active_player.direct_attack_damage_multiplier_this_turn.clear()
    for player in self.players:
        for creature in player.battlefield:
            creature.temporary_abilities.clear()
