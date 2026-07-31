from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .cards import CardInstance, ResourceCard
from .enums import Ability, Element


@dataclass
class BattlefieldCreature:
    unit_id: int
    template_id: str
    name: str
    cost: int
    aw: int
    vw: int
    element: Element
    abilities: frozenset[Ability]
    current_hp: int
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
            element=card.template.element,
            abilities=card.template.abilities,
            current_hp=card.template.vw,
            tapped=not has_haste,
            summoning_sick=not has_haste,
        )

    @property
    def damage_taken(self) -> int:
        return self.vw - self.current_hp

    @property
    def aw_vw(self) -> str:
        return f"{self.aw}/{self.vw}"

    def is_ready(self) -> bool:
        return not self.tapped and not self.summoning_sick

    def has_ability(self, ability: Ability) -> bool:
        return ability in self.abilities

    def block_capacity(self) -> int:
        return 2 if self.has_ability(Ability.DEFENDER) else 1

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
    life: int = 20
    deck: List[CardInstance] = field(default_factory=list)
    hand: List[CardInstance] = field(default_factory=list)
    battlefield: List[BattlefieldCreature] = field(default_factory=list)
    resources: List[ResourceCard] = field(default_factory=list)
    resource_played_this_turn: bool = False
    turns_started: int = 0
    mulligan_used: bool = False

    def untap_for_turn(self) -> None:
        for resource in self.resources:
            resource.tapped = False
        for creature in self.battlefield:
            if creature.has_ability(Ability.REGENERATION) and creature.current_hp < creature.vw:
                creature.current_hp = min(creature.vw, creature.current_hp + 1)
            creature.tapped = False
            creature.summoning_sick = False
        self.resource_played_this_turn = False

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

    def can_pay(self, cost: int) -> bool:
        return self.available_resources() >= cost

    def pay_cost(self, cost: int) -> bool:
        if not self.can_pay(cost):
            return False
        remaining = cost
        for resource in self.resources:
            if remaining == 0:
                break
            if not resource.tapped:
                resource.tapped = True
                remaining -= 1
        return True
