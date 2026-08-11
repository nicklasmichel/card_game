from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.config import STARTING_LIFE
from .cards import CardCost, CardInstance, ResourceCard
from .enums import Ability, Element


@dataclass
class BattlefieldCreature:
    unit_id: int
    template_id: str
    name: str
    cost: CardCost
    aw: int
    vw: int
    lw: int
    sw: int
    element: Element
    abilities: frozenset[Ability]
    builder_ability: Ability | None
    rules_text: str
    return_to_deck_end_of_turn: bool
    cannot_block: bool
    must_attack_each_turn: bool
    all_attackers_die_bonus: int
    draw_on_attack: int
    draw_on_death: int
    draw_on_player_damage: int
    tap_enemy_creature_on_play: int
    return_other_own_haste_on_combat_death: bool
    own_flying_attack_aura: int
    current_hp: int
    temporary_aw_bonus: int = 0
    temporary_combat_aw_bonus: int = 0
    temporary_combat_sw_bonus: int = 0
    temporary_abilities: set[Ability] = field(default_factory=set)
    tapped: bool = True
    summoning_sick: bool = True

    @classmethod
    def from_card(cls, card: CardInstance) -> "BattlefieldCreature":
        has_haste = card.template.has_ability(Ability.HASTE)
        return cls(
            unit_id=card.instance_id,
            template_id=card.template.template_id,
            name=card.template.name,
            cost=card.template.cost,
            aw=card.template.aw,
            vw=card.template.vw,
            lw=card.template.effective_lw,
            sw=card.template.effective_sw,
            element=card.template.element,
            abilities=card.template.abilities,
            builder_ability=card.template.builder_ability,
            rules_text=card.template.rules_text,
            return_to_deck_end_of_turn=card.template.return_to_deck_end_of_turn,
            cannot_block=card.template.cannot_block,
            must_attack_each_turn=card.template.must_attack_each_turn,
            all_attackers_die_bonus=card.template.all_attackers_die_bonus,
            draw_on_attack=card.template.draw_on_attack,
            draw_on_death=card.template.draw_on_death,
            draw_on_player_damage=card.template.draw_on_player_damage,
            tap_enemy_creature_on_play=card.template.tap_enemy_creature_on_play,
            return_other_own_haste_on_combat_death=card.template.return_other_own_haste_on_combat_death,
            own_flying_attack_aura=card.template.own_flying_attack_aura,
            current_hp=card.template.effective_lw,
            temporary_aw_bonus=0,
            temporary_combat_aw_bonus=0,
            temporary_combat_sw_bonus=0,
            tapped=not has_haste,
            summoning_sick=not has_haste,
        )

    @property
    def damage_taken(self) -> int:
        return self.lw - self.current_hp

    @property
    def aw_vw(self) -> str:
        return f"{self.aw}/{self.vw}"

    def is_ready(self) -> bool:
        return not self.tapped and (not self.summoning_sick or self.has_ability(Ability.HASTE))

    def has_ability(self, ability: Ability) -> bool:
        all_abilities = set(self.abilities) | set(self.temporary_abilities)
        if ability == Ability.LIFE_STEAL:
            return Ability.LIFE_STEAL in all_abilities or Ability.LIFELINK in all_abilities
        if ability == Ability.LIFELINK:
            return Ability.LIFELINK in all_abilities or Ability.LIFE_STEAL in all_abilities
        if ability == Ability.VIGILANT:
            return Ability.VIGILANT in all_abilities or Ability.VIGILANCE in all_abilities
        if ability == Ability.VIGILANCE:
            return Ability.VIGILANCE in all_abilities or Ability.VIGILANT in all_abilities
        if ability == Ability.ENRAGED:
            return Ability.ENRAGED in all_abilities or Ability.PROVOKE in all_abilities
        return ability in all_abilities

    def block_capacity(self) -> int:
        return 1

    def short_status(self) -> str:
        if self.tapped:
            return "Getappt"
        if self.summoning_sick:
            return "Neu"
        return "Bereit"
@dataclass
class PlayerState:
    player_id: int
    name: str
    is_human: bool
    summoner_key: str = ""
    life: int = STARTING_LIFE
    deck: List[CardInstance] = field(default_factory=list)
    hand: List[CardInstance] = field(default_factory=list)
    discard_pile: List[CardInstance] = field(default_factory=list)
    battlefield: List[BattlefieldCreature] = field(default_factory=list)
    resources: List[ResourceCard] = field(default_factory=list)
    resources_played_this_turn: int = 0
    main_action_used_this_turn: bool = False
    summoner_passive_draw_used_this_turn: bool = False
    creature_cost_reduction_this_turn: int = 0
    summoner_tapped: bool = False
    turns_started: int = 0
    mulligan_used: bool = False

    def untap_for_turn(self) -> None:
        for resource in self.resources:
            resource.tapped = False
        for creature in self.battlefield:
            creature.tapped = False
            creature.summoning_sick = False
        self.resources_played_this_turn = 0
        self.main_action_used_this_turn = False
        self.summoner_passive_draw_used_this_turn = False
        self.summoner_tapped = False

    def draw_card(self) -> Optional[CardInstance]:
        if not self.deck:
            return None
        card = self.deck.pop()
        self.hand.append(card)
        return card

    def available_resources(self) -> int:
        return sum(1 for resource in self.resources if not resource.tapped)

    def total_resources(self) -> int:
        return len(self.resources)

    def can_pay(self, cost: CardCost | int) -> bool:
        if isinstance(cost, int):
            return self.available_resources() >= cost
        return self.available_resources() >= cost.resources and self.total_resources() >= cost.recycle

    def tap_resources_for_cost(self, resource_cost: int) -> list[ResourceCard]:
        if self.available_resources() < resource_cost:
            return []
        remaining = resource_cost
        tapped_resources: list[ResourceCard] = []
        for resource in self.resources:
            if remaining == 0:
                break
            if not resource.tapped:
                resource.tapped = True
                tapped_resources.append(resource)
                remaining -= 1
        return tapped_resources if remaining == 0 else []

    def pay_cost(self, cost: int) -> bool:
        tapped_resources = self.tap_resources_for_cost(cost)
        if len(tapped_resources) != cost:
            return False
        return True
