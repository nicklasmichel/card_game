from __future__ import annotations

from typing import List, Optional

from core.models import (
    Ability,
    CardInstance,
    CardType,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
    PHASE_REACTION,
    PHASE_RECYCLE_PAYMENT,
    PHASE_RESOURCE,
    PHASE_SPELL_TARGETING,
    PHASE_SUMMONING,
    PlayerState,
)


def choose_cards_to_discard_for_ai(self, player: PlayerState, count: int) -> List[CardInstance]:
    if count <= 0 or not player.hand:
        return []
    return self.ai.choose_cards_to_discard(player, self, count)


def discard_cards(self, player: PlayerState, cards: List[CardInstance], source_card_name: str) -> None:
    if not cards:
        return
    card_ids = {card.instance_id for card in cards}
    player.hand = [card for card in player.hand if card.instance_id not in card_ids]
    player.discard_pile.extend(cards)
    discarded_names = ", ".join(card.template.name for card in cards)
    self.log(f"{player.name} wirft durch {source_card_name} ab: {discarded_names}.")


def begin_forced_discard(self, target_player: PlayerState, count: int, source_card_name: str, return_phase: str) -> bool:
    required_count = min(count, len(target_player.hand))
    if required_count <= 0:
        return False
    if not target_player.is_human:
        cards = self.choose_cards_to_discard_for_ai(target_player, required_count)
        self.discard_cards(target_player, cards, source_card_name)
        return False
    from core.models import PendingForcedDiscard

    self.pending_forced_discard = PendingForcedDiscard(
        target_player_id=target_player.player_id,
        required_count=required_count,
        selected_card_ids=[],
        source_card_name=source_card_name,
        return_phase=return_phase,
    )
    self.phase = PHASE_FORCED_DISCARD
    self.selected_hand_ids.clear()
    self.log(f"WÃ¤hle {required_count} Handkarte(n), die du durch {source_card_name} abwerfen musst.")
    return True


def toggle_forced_discard_selection(self, card_id: int) -> None:
    pending = self.pending_forced_discard
    if pending is None or self.phase != PHASE_FORCED_DISCARD:
        return
    if pending.target_player_id != self.human_player.player_id:
        return
    if not any(card.instance_id == card_id for card in self.human_player.hand):
        return
    if card_id in pending.selected_card_ids:
        pending.selected_card_ids.remove(card_id)
    elif len(pending.selected_card_ids) < pending.required_count:
        pending.selected_card_ids.append(card_id)
    else:
        self.log("Es wurden bereits genug Handkarten zum Abwerfen ausgewÃ¤hlt.")
        return
    self.selected_hand_ids = list(pending.selected_card_ids)


def confirm_forced_discard(self) -> None:
    pending = self.pending_forced_discard
    if pending is None or self.phase != PHASE_FORCED_DISCARD:
        return
    if pending.target_player_id != self.human_player.player_id:
        return
    if len(pending.selected_card_ids) != pending.required_count:
        self.log("WÃ¤hle genau die benÃ¶tigte Anzahl an Handkarten zum Abwerfen.")
        return
    cards = [card for card in self.human_player.hand if card.instance_id in pending.selected_card_ids]
    if len(cards) != pending.required_count:
        self.log("Mindestens eine ausgewÃ¤hlte Handkarte ist nicht mehr verfÃ¼gbar.")
        return
    self.discard_cards(self.human_player, cards, pending.source_card_name)
    self.pending_forced_discard = None
    self.selected_hand_ids.clear()
    self.phase = pending.return_phase
    if self.resolving_stack:
        self.resume_stack_resolution()
        return
    if self.active_player.is_human:
        self.auto_advance_human_summoning_phase_if_needed()


def get_selected_hand_card(self) -> Optional[CardInstance]:
    if len(self.selected_hand_ids) != 1:
        return None
    selected_id = self.selected_hand_ids[0]
    candidate_hands = [self.active_player.hand]
    if self.phase in {PHASE_REACTION, PHASE_SPELL_TARGETING}:
        candidate_hands = [self.human_player.hand, self.ai_player.hand, self.active_player.hand]
    for hand in candidate_hands:
        for card in hand:
            if card.instance_id == selected_id:
                return card
    return None


def toggle_hand_card(self, card_id: int) -> None:
    if self.pending_recycle_payment is not None:
        return
    if self.phase == PHASE_FORCED_DISCARD:
        self.toggle_forced_discard_selection(card_id)
        return
    if self.phase == PHASE_MULLIGAN:
        if card_id in self.selected_hand_ids:
            self.selected_hand_ids.remove(card_id)
        else:
            self.selected_hand_ids.append(card_id)
        return
    if self.active_player.is_human and self.phase in {PHASE_RESOURCE, PHASE_SUMMONING, PHASE_REACTION}:
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

    if self.phase == PHASE_MULLIGAN:
        if action in {"confirm_mulligan", "keep_mulligan"}:
            self.apply_human_mulligan()
        return

    human_response_phases = {
        PHASE_DECLARE_BLOCKERS,
        PHASE_ORDER_BLOCKERS,
        PHASE_DICE_BATTLE,
        PHASE_FORCED_DISCARD,
        PHASE_REACTION,
        PHASE_SPELL_TARGETING,
    }
    if self.phase == PHASE_GAME_OVER or (not self.active_player.is_human and self.phase not in human_response_phases):
        return

    if action == "play_resource":
        self.play_selected_card_as_resource()
    elif action == "to_summoning":
        self.enter_summoning_phase()
    elif action == "play_creature":
        self.play_selected_creature_card()
    elif action == "play_spell":
        card = self.get_selected_hand_card()
        if card is not None and card.template.card_type in {CardType.RITUAL, CardType.SPELL}:
            self.begin_spell_cast(card.instance_id)
    elif action == "play_reaction_spell":
        card = self.get_selected_hand_card()
        if card is not None:
            self.begin_spell_from_hand(card.instance_id)
    elif action == "confirm_recycle":
        self.confirm_recycle_payment()
    elif action == "cancel_recycle":
        self.cancel_recycle_payment()
    elif action == "confirm_spell_target":
        self.confirm_pending_spell_cast()
    elif action == "choose_tailwind_haste":
        self.select_pending_spell_keyword(Ability.HASTE)
    elif action == "choose_tailwind_flying":
        self.select_pending_spell_keyword(Ability.FLYING)
    elif action == "cancel_spell_target":
        self.cancel_pending_spell_cast()
    elif action == "confirm_forced_discard":
        self.confirm_forced_discard()
    elif action == "to_combat":
        self.begin_attack_declaration()
    elif action == "confirm_attackers":
        self.confirm_attackers()
    elif action == "clear_blocks":
        self.clear_block_assignments()
    elif action == "confirm_blocks":
        self.finish_block_assignment()
    elif action == "skip_blocks":
        self.log("Keine Blocker zugewiesen. Schaden wird durchgelassen.")
        self.finish_block_assignment()
    elif action == "reset_order" and self.pending_order is not None:
        self.pending_order.chosen_order.clear()
        self.log("Blockreihenfolge zurÃ¼ckgesetzt.")
    elif action == "confirm_order":
        self.confirm_block_order()
    elif action == "use_adaptation":
        self.resolve_pending_comparison(use_human_adaptation=True)
    elif action == "resolve_comparison":
        self.resolve_pending_comparison(use_human_adaptation=False)
    elif action == "pass_reaction":
        self.pass_reaction()
    elif action == "end_dice_battle":
        self.end_dice_battle()
    elif action == "end_turn":
        self.end_turn()
