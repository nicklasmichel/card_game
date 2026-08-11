from __future__ import annotations

from core.models import BattlefieldCreature, CardCost, CardInstance, PlayerState


def handle_creature_player_damage_triggers(self, controller: PlayerState, creature: BattlefieldCreature, damage: int) -> None:
    if damage <= 0:
        return
    draw_count = getattr(creature, "draw_on_player_damage", 0)
    if draw_count <= 0:
        return
    for _ in range(draw_count):
        drawn = self.draw_card_for_player(controller, creature.name)
        if drawn is None and self.phase == "Game Over":
            break
    if self.phase != "Game Over":
        self.log(f"{creature.name} lets {controller.name} draw {draw_count} card(s) from player damage.")


def format_card_cost(self, cost: CardCost) -> str:
    if cost.resources <= 0 and cost.recycle <= 0:
        return "0"
    if cost.resources > 0 and cost.recycle > 0:
        return f"{cost.resources} + Recycle {cost.recycle}"
    if cost.resources > 0:
        return str(cost.resources)
    return f"Recycle {cost.recycle}"


def format_resource_play_log(self, player: PlayerState, card_name: str) -> str:
    return f"{player.name} adds resource {player.resources_played_this_turn}/10 ({card_name})."


def get_card_cost_to_pay(self, player: PlayerState, card: CardInstance) -> CardCost:
    return card.template.cost
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
    self.log(f"{names} is shuffled back into the deck at end of turn.")
def play_hand_card_in_summoning_zone(self, card_id: int) -> None:
    if self.phase == "Builder Ability" and self.active_player.is_human:
        if self.begin_builder_ability_use(card_id):
            self.log("Choose whether to grant the ability or deal 1 damage.")
        else:
            self.log("This ability card cannot be played right now.")
