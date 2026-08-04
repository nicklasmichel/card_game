from __future__ import annotations

from typing import List

from core.models import (
    BattlefieldCreature,
    CardType,
    CardCost,
    CardInstance,
    PendingRecyclePayment,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_RECYCLE_PAYMENT,
    PHASE_RESOURCE,
    PHASE_SUMMONING,
    PlayerState,
    ResourceCard,
)


def format_card_cost(self, cost: CardCost) -> str:
    if cost.resources <= 0 and cost.recycle <= 0:
        return "0"
    if cost.resources > 0 and cost.recycle > 0:
        return f"{cost.resources} + Recycle {cost.recycle}"
    if cost.resources > 0:
        return str(cost.resources)
    return f"Recycle {cost.recycle}"


def get_card_cost_to_pay(self, player: PlayerState, card: CardInstance) -> CardCost:
    if card.template.card_type != CardType.CREATURE:
        return card.template.cost
    return CardCost(
        resources=max(0, card.template.resource_cost - getattr(player, "creature_cost_reduction_this_turn", 0)),
        recycle=card.template.recycle_cost,
    )


def can_play_card(self, player: PlayerState, card: CardInstance) -> bool:
    return player.can_pay(self.get_card_cost_to_pay(player, card))


def register_hand_card_played(self, player: PlayerState) -> None:
    if player != self.active_player:
        return
    player.hand_cards_played_this_turn += 1
    if player.summoner_passive_draw_used_this_turn or player.hand_cards_played_this_turn != 4:
        return
    player.summoner_passive_draw_used_this_turn = True
    drawn = self.draw_card_for_player(player, "Beschwoerer-Passiv")
    if drawn is not None:
        self.log(f"{player.name} zieht 1 Karte durch den Beschwoerer.")
    elif self.phase != PHASE_GAME_OVER:
        self.log("Es kann keine Karte durch den Beschwoerer gezogen werden.")


def begin_recycle_payment(self, card_instance_id: int) -> bool:
    if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
        return False
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_instance_id), None)
    if card is None:
        self.log("Diese Handkarte kann nicht gespielt werden.")
        return False
    if not self.can_play_card(self.active_player, card):
        self.log("Nicht genügend Ressourcen oder Recyclekosten können nicht bezahlt werden.")
        return False
    if card.template.recycle_cost <= 0:
        return self.resolve_creature_play(card)
    self.pending_recycle_payment = PendingRecyclePayment(
        card_instance_id=card.instance_id,
        required_count=card.template.recycle_cost,
        selected_resource_ids=[],
    )
    self.phase = PHASE_RECYCLE_PAYMENT
    self.selected_hand_ids = [card.instance_id]
    self.log(
        f"Wähle {card.template.recycle_cost} Ressourcen für Recycle von {card.template.name} und bestätige dann."
    )
    return True


def toggle_recycle_resource_selection(self, resource_id: int) -> None:
    if self.pending_recycle_payment is None or self.phase != PHASE_RECYCLE_PAYMENT:
        return
    resource = next(
        (
            existing
            for existing in self.active_player.resources
            if existing.resource_id == resource_id
        ),
        None,
    )
    if resource is None:
        return
    selected = self.pending_recycle_payment.selected_resource_ids
    if resource_id in selected:
        selected.remove(resource_id)
        return
    if len(selected) >= self.pending_recycle_payment.required_count:
        self.log("Es wurden bereits genug Ressourcen für Recycle ausgewählt.")
        return
    selected.append(resource_id)


def cancel_recycle_payment(self) -> None:
    if self.pending_recycle_payment is None:
        return
    self.pending_recycle_payment = None
    self.phase = PHASE_SUMMONING
    self.selected_hand_ids.clear()
    self.log("Recycle-Auswahl abgebrochen.")


def confirm_recycle_payment(self) -> None:
    pending = self.pending_recycle_payment
    if pending is None or self.phase != PHASE_RECYCLE_PAYMENT:
        return
    card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
    if card is None:
        self.cancel_recycle_payment()
        return
    if len(pending.selected_resource_ids) != pending.required_count:
        self.log("Wähle genau die benötigte Anzahl an Ressourcen für Recycle.")
        return
    if not self.can_play_card(self.active_player, card):
        self.log("Die Kosten können nicht mehr vollständig bezahlt werden.")
        return
    self.pending_recycle_payment = None
    self.phase = PHASE_SUMMONING
    if not self.resolve_creature_play(card, recycle_resource_ids=list(pending.selected_resource_ids)):
        self.pending_recycle_payment = pending
        self.phase = PHASE_RECYCLE_PAYMENT


def resolve_creature_play(self, card: CardInstance, recycle_resource_ids: List[int] | None = None) -> bool:
    cost = self.get_card_cost_to_pay(self.active_player, card)
    if not self.can_play_card(self.active_player, card):
        self.log("Nicht genügend Ressourcen oder Recyclekosten können nicht bezahlt werden.")
        return False
    if cost.recycle > 0 and recycle_resource_ids is None:
        self.log("Recycle-Ressourcen wurden nicht ausgewählt.")
        return False
    if recycle_resource_ids is not None and len(recycle_resource_ids) != cost.recycle:
        self.log("Die Anzahl ausgewählter Recycle-Ressourcen ist ungültig.")
        return False
    if recycle_resource_ids is not None and len(set(recycle_resource_ids)) != len(recycle_resource_ids):
        self.log("Eine Ressource kann für Recycle nicht mehrfach ausgewählt werden.")
        return False

    available_resource_ids = {
        resource.resource_id
        for resource in self.active_player.resources
        if resource.resource_id is not None
    }
    if recycle_resource_ids is not None and any(resource_id not in available_resource_ids for resource_id in recycle_resource_ids):
        self.log("Mindestens eine ausgewählte Recycle-Ressource ist nicht mehr verfügbar.")
        return False

    tapped_resources = self.active_player.tap_resources_for_cost(cost.resources)
    if len(tapped_resources) != cost.resources:
        self.log("Nicht genügend bereite Ressourcen.")
        return False

    recycled_templates: List[str] = []
    if recycle_resource_ids:
        resources_to_recycle = [
            resource
            for resource in self.active_player.resources
            if resource.resource_id in recycle_resource_ids
        ]
        if len(resources_to_recycle) != len(recycle_resource_ids):
            self.log("Recycle konnte nicht vollständig bezahlt werden.")
            return False
        self.active_player.resources = [
            resource
            for resource in self.active_player.resources
            if resource.resource_id not in recycle_resource_ids
        ]
        recycled_cards = [
            CardInstance(self.make_instance_id(), resource.template, was_recycled=True)
            for resource in resources_to_recycle
        ]
        recycled_templates = [resource.template.template_id for resource in resources_to_recycle]
        self.active_player.deck.extend(recycled_cards)
        self.rng.shuffle(self.active_player.deck)
        self.queue_recycle_reveal_event(self.active_player.player_id, recycled_templates)
        if self.statistics is not None:
            self.statistics.register_recycle_payment(self.active_player.player_id, card.template.recycle_cost)

    self.active_player.hand = [
        existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
    ]
    self.active_player.battlefield.append(BattlefieldCreature.from_card(card))
    self.selected_hand_ids.clear()
    if self.statistics is not None:
        self.statistics.register_creature_played(
            self.active_player.player_id,
            card.template.recycle_cost,
        )
        self.log(
            f"{self.active_player.name} spielt {card.template.name} "
            f"({card.template.aw}/{card.template.vw}) für {self.format_card_cost(cost)}."
        )
    self.register_hand_card_played(self.active_player)
    if card.template.draw_on_play > 0:
        for _ in range(card.template.draw_on_play):
            drawn = self.draw_card_for_player(self.active_player, card.template.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return True
        self.log(
            f"{card.template.name} laesst {self.active_player.name} beim Ausspielen {card.template.draw_on_play} Karte(n) ziehen."
        )
    if card.template.self_damage_on_play > 0:
        self.active_player.life -= card.template.self_damage_on_play
        self.queue_player_damage_event(
            target_player_id=self.active_player.player_id,
            amount=card.template.self_damage_on_play,
            source_element=card.template.element,
        )
        self.log(
            f"{self.active_player.name} erleidet {card.template.self_damage_on_play} Schaden durch {card.template.name}."
        )
        self.check_for_game_over()
        if self.phase == PHASE_GAME_OVER:
            return True
    if card.template.opponent_damage_on_play > 0:
        self.defending_player.life -= card.template.opponent_damage_on_play
        self.queue_player_damage_event(
            target_player_id=self.defending_player.player_id,
            amount=card.template.opponent_damage_on_play,
            source_element=card.template.element,
            attacker_id=card.instance_id,
        )
        if self.statistics is not None:
            self.statistics.register_player_damage(
                self.active_player.player_id,
                card.template.opponent_damage_on_play,
            )
        self.log(
            f"{card.template.name} verursacht beim Ausspielen {card.template.opponent_damage_on_play} Schaden an {self.defending_player.name}."
        )
        self.check_for_game_over()
        if self.phase == PHASE_GAME_OVER:
            return True
    self.begin_forced_discard(
        self.active_player,
        card.template.discard_self_on_play,
        card.template.name,
        PHASE_SUMMONING,
    )
    if self.phase == PHASE_FORCED_DISCARD:
        return True
    self.begin_forced_discard(
        self.defending_player,
        card.template.discard_opponent_on_play,
        card.template.name,
        PHASE_SUMMONING,
    )
    if self.phase == PHASE_FORCED_DISCARD:
        return True
    if recycled_templates:
        recycled_names = ", ".join(self.templates[template_id].name for template_id in recycled_templates)
        self.log(f"Recycle aufgedeckt und zurück ins Deck gemischt: {recycled_names}.")
    self.auto_advance_human_summoning_phase_if_needed()
    return True


def resolve_end_of_turn_returns(self, player: PlayerState) -> None:
    returning = [
        creature
        for creature in player.battlefield
        if getattr(creature, "return_to_deck_end_of_turn", False)
    ]
    if not returning:
        return
    returning_ids = {creature.unit_id for creature in returning}
    player.battlefield = [
        creature for creature in player.battlefield if creature.unit_id not in returning_ids
    ]
    for creature in returning:
        player.deck.append(CardInstance(self.make_instance_id(), self.templates[creature.template_id]))
    self.rng.shuffle(player.deck)
    names = ", ".join(creature.name for creature in returning)
    self.log(f"{names} wird/werden am Ende des Zuges zurück ins Deck gemischt.")


def can_activate_summoner_draw(self, player: PlayerState) -> bool:
    return False


def activate_summoner_draw(self, player: PlayerState) -> bool:
    if player == self.active_player and player.is_human:
        self.log("Der Beschwoerer besitzt derzeit keine aktivierbare Faehigkeit.")
    return False


def play_selected_card_as_resource(self) -> None:
    if self.phase != PHASE_RESOURCE or self.active_player.resources_played_this_turn >= 2:
        return
    card = self.get_selected_hand_card()
    if card is None:
        self.log("Keine Handkarte als Ressource ausgewählt.")
        return
    self.play_hand_card_as_resource(card.instance_id)


def play_hand_card_as_resource(self, card_id: int) -> None:
    if self.phase != PHASE_RESOURCE or self.active_player.resources_played_this_turn >= 2 or not self.active_player.is_human:
        return
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
    if card is None:
        self.log("Diese Handkarte kann nicht als Ressource gespielt werden.")
        return
    self.active_player.hand = [
        existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
    ]
    self.active_player.resources.append(ResourceCard(template=card.template, resource_id=card.instance_id))
    self.active_player.resources_played_this_turn += 1
    self.selected_hand_ids.clear()
    if self.statistics is not None:
        self.statistics.register_resource_played(self.active_player.player_id)
    self.log(f"{self.active_player.name} legt {card.template.name} als Ressource.")
    self.register_hand_card_played(self.active_player)
    if self.active_player.resources_played_this_turn >= 2:
        self.enter_summoning_phase()


def play_selected_creature_card(self) -> None:
    if self.phase != PHASE_SUMMONING:
        return
    card = self.get_selected_hand_card()
    if card is None:
        self.log("Keine Kreatur-Karte ausgewählt.")
        return
    self.begin_recycle_payment(card.instance_id)


def play_hand_card_in_summoning_zone(self, card_id: int) -> None:
    if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
        return
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
    if card is None:
        self.log("Diese Handkarte kann gerade nicht gespielt werden.")
        return
    if card.template.card_type == CardType.CREATURE:
        self.begin_recycle_payment(card_id)
        return
    if card.template.card_type in {CardType.RITUAL, CardType.SPELL}:
        self.begin_spell_cast(card_id)


def play_hand_card_as_creature(self, card_id: int) -> None:
    if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
        return
    self.play_hand_card_in_summoning_zone(card_id)
