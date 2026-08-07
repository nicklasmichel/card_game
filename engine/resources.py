from __future__ import annotations

from typing import List

from core.models import (
    Ability,
    BattlefieldCreature,
    CardType,
    CardCost,
    CardInstance,
    MAIN_PHASES,
    PendingRecyclePayment,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PHASE_REACTION,
    PHASE_RECYCLE_PAYMENT,
    PlayerState,
    ResourceCard,
)


def choose_enemy_creature_to_tap_on_play(self, controller: PlayerState, source_creature: BattlefieldCreature):
    opponent = self.players[1 - controller.player_id]
    candidates = [creature for creature in opponent.battlefield if creature.current_hp > 0]
    if not candidates:
        return None
    untapped_candidates = [creature for creature in candidates if not creature.tapped]
    pool = untapped_candidates or candidates
    likely_attackers = [creature for creature in controller.battlefield if creature.current_hp > 0 and creature.is_ready()]
    if source_creature.has_ability(Ability.HASTE):
        likely_attackers = [*likely_attackers, source_creature]

    def score(creature: BattlefieldCreature) -> tuple[float, int, int, int]:
        blocks_likely_attack = sum(
            1
            for attacker in likely_attackers
            if self.can_creature_block_attacker(creature, attacker)
        )
        threat = self.get_creature_attack_value(creature) * 1.4 + self.get_creature_current_hp(creature)
        return (
            blocks_likely_attack * 3.0 + threat,
            0 if creature.tapped else 1,
            self.get_creature_attack_value(creature),
            self.get_creature_current_hp(creature),
        )

    return max(pool, key=score)


def apply_creature_enter_play_effects(self, controller: PlayerState, creature: BattlefieldCreature) -> None:
    tap_count = getattr(creature, "tap_enemy_creature_on_play", 0)
    for _ in range(tap_count):
        target = choose_enemy_creature_to_tap_on_play(self, controller, creature)
        if target is None:
            break
        if not target.tapped:
            target.tapped = True
        self.log(f"{creature.name} tappt {target.name}.")


def handle_creature_player_damage_triggers(self, controller: PlayerState, creature: BattlefieldCreature, damage: int) -> None:
    if damage <= 0:
        return
    draw_count = getattr(creature, "draw_on_player_damage", 0)
    if draw_count <= 0:
        return
    for _ in range(draw_count):
        drawn = self.draw_card_for_player(controller, creature.name)
        if drawn is None and self.phase == PHASE_GAME_OVER:
            break
    if self.phase != PHASE_GAME_OVER:
        self.log(f"{creature.name} laesst {controller.name} durch Spielerschaden {draw_count} Karte(n) ziehen.")


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
    return


def begin_recycle_payment(self, card_instance_id: int) -> bool:
    if self.phase not in MAIN_PHASES or not self.active_player.is_human:
        return False
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_instance_id), None)
    if card is None:
        self.log("Diese Handkarte kann nicht gespielt werden.")
        return False
    if not self.can_play_card(self.active_player, card):
        self.log("Nicht genuegend Ressourcen oder Recyclekosten koennen nicht bezahlt werden.")
        return False
    if card.template.recycle_cost <= 0:
        return self.resolve_creature_play(card)
    self.pending_recycle_payment = PendingRecyclePayment(
        card_instance_id=card.instance_id,
        required_count=card.template.recycle_cost,
        selected_resource_ids=[],
        return_phase=self.phase,
    )
    self.phase = PHASE_RECYCLE_PAYMENT
    self.selected_hand_ids = [card.instance_id]
    self.log(
        f"Waehle {card.template.recycle_cost} Ressourcen fuer Recycle von {card.template.name} und bestaetige dann."
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
        self.log("Es wurden bereits genug Ressourcen fuer Recycle ausgewaehlt.")
        return
    selected.append(resource_id)


def cancel_recycle_payment(self) -> None:
    pending = self.pending_recycle_payment
    if pending is None:
        return
    self.pending_recycle_payment = None
    self.phase = pending.return_phase
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
        self.log("Waehle genau die benoetigte Anzahl an Ressourcen fuer Recycle.")
        return
    if not self.can_play_card(self.active_player, card):
        self.log("Die Kosten koennen nicht mehr vollstaendig bezahlt werden.")
        return
    self.pending_recycle_payment = None
    self.phase = pending.return_phase
    if not self.resolve_creature_play(card, recycle_resource_ids=list(pending.selected_resource_ids)):
        self.pending_recycle_payment = pending
        self.phase = PHASE_RECYCLE_PAYMENT


def resolve_creature_play(self, card: CardInstance, recycle_resource_ids: List[int] | None = None) -> bool:
    cost = self.get_card_cost_to_pay(self.active_player, card)
    if not self.can_play_card(self.active_player, card):
        self.log("Nicht genuegend Ressourcen oder Recyclekosten koennen nicht bezahlt werden.")
        return False
    if cost.recycle > 0 and recycle_resource_ids is None:
        self.log("Recycle-Ressourcen wurden nicht ausgewaehlt.")
        return False
    if recycle_resource_ids is not None and len(recycle_resource_ids) != cost.recycle:
        self.log("Die Anzahl ausgewaehlter Recycle-Ressourcen ist ungueltig.")
        return False
    if recycle_resource_ids is not None and len(set(recycle_resource_ids)) != len(recycle_resource_ids):
        self.log("Eine Ressource kann fuer Recycle nicht mehrfach ausgewaehlt werden.")
        return False

    available_resource_ids = {
        resource.resource_id
        for resource in self.active_player.resources
        if resource.resource_id is not None
    }
    if recycle_resource_ids is not None and any(resource_id not in available_resource_ids for resource_id in recycle_resource_ids):
        self.log("Mindestens eine ausgewaehlte Recycle-Ressource ist nicht mehr verfuegbar.")
        return False

    tapped_resources = self.active_player.tap_resources_for_cost(cost.resources)
    if len(tapped_resources) != cost.resources:
        self.log("Nicht genuegend bereite Ressourcen.")
        return False

    recycled_templates: List[str] = []
    if recycle_resource_ids:
        resources_to_recycle = [
            resource
            for resource in self.active_player.resources
            if resource.resource_id in recycle_resource_ids
        ]
        if len(resources_to_recycle) != len(recycle_resource_ids):
            self.log("Recycle konnte nicht vollstaendig bezahlt werden.")
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
    created_creature = BattlefieldCreature.from_card(card)
    self.active_player.battlefield.append(created_creature)
    self.selected_hand_ids.clear()
    if self.statistics is not None:
        self.statistics.register_creature_played(
            self.active_player.player_id,
            card.template.recycle_cost,
        )
        self.log(
            f"{self.active_player.name} spielt {card.template.name} "
            f"(AW {card.template.aw} / VW {card.template.vw} / LW {card.template.effective_lw} / SW {card.template.effective_sw}) "
            f"fuer {self.format_card_cost(cost)}."
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
    apply_creature_enter_play_effects(self, self.active_player, created_creature)
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
        self.phase,
    )
    if self.phase == PHASE_FORCED_DISCARD:
        return True
    self.begin_forced_discard(
        self.defending_player,
        card.template.discard_opponent_on_play,
        card.template.name,
        self.phase,
    )
    if self.phase == PHASE_FORCED_DISCARD:
        return True
    if recycled_templates:
        recycled_names = ", ".join(self.templates[template_id].name for template_id in recycled_templates)
        self.log(f"Recycle aufgedeckt und zurueck ins Deck gemischt: {recycled_names}.")
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
    self.log(f"{names} wird/werden am Ende des Zuges zurueck ins Deck gemischt.")


def can_activate_summoner_draw(self, player: PlayerState) -> bool:
    return False


def activate_summoner_draw(self, player: PlayerState) -> bool:
    if player == self.active_player and player.is_human:
        self.log("Der Beschwoerer besitzt derzeit keine aktivierbare Faehigkeit.")
    return False


def play_selected_card_as_resource(self) -> None:
    if self.phase not in MAIN_PHASES or self.active_player.resources_played_this_turn >= 2:
        return
    card = self.get_selected_hand_card()
    if card is None:
        self.log("Keine Handkarte als Ressource ausgewaehlt.")
        return
    self.play_hand_card_as_resource(card.instance_id)


def play_hand_card_as_resource(self, card_id: int) -> None:
    if self.phase not in MAIN_PHASES or self.active_player.resources_played_this_turn >= 2 or not self.active_player.is_human:
        return
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
    if card is None:
        self.log("Diese Handkarte kann nicht als Ressource gespielt werden.")
        return
    self.active_player.hand = [
        existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
    ]
    comes_in_tapped = self.active_player.resources_played_this_turn >= 1
    self.active_player.resources.append(
        ResourceCard(template=card.template, resource_id=card.instance_id, tapped=comes_in_tapped)
    )
    self.active_player.resources_played_this_turn += 1
    self.selected_hand_ids.clear()
    if self.statistics is not None:
        self.statistics.register_resource_played(self.active_player.player_id)
    state_text = "getappt" if comes_in_tapped else "bereit"
    self.log(f"{self.active_player.name} legt {card.template.name} als Ressource ({state_text}).")
    self.register_hand_card_played(self.active_player)


def play_selected_creature_card(self) -> None:
    if self.phase not in MAIN_PHASES:
        return
    card = self.get_selected_hand_card()
    if card is None:
        self.log("Keine Kreatur-Karte ausgewaehlt.")
        return
    self.begin_recycle_payment(card.instance_id)


def play_hand_card_in_summoning_zone(self, card_id: int) -> None:
    if self.phase == PHASE_REACTION and self.reaction_priority_player_id == self.human_player.player_id:
        self.begin_spell_from_hand(card_id)
        return
    if self.phase not in MAIN_PHASES or not self.active_player.is_human:
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
    if self.phase not in MAIN_PHASES or not self.active_player.is_human:
        return
    self.play_hand_card_in_summoning_zone(card_id)
