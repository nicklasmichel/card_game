from __future__ import annotations

from dataclasses import dataclass

from .enums import Ability, Element


@dataclass(frozen=True)
class CardTemplate:
    template_id: str
    name: str
    cost: int
    aw: int
    vw: int
    element: Element
    abilities: frozenset[Ability] = frozenset()

    def has_ability(self, ability: Ability) -> bool:
        return ability in self.abilities


@dataclass
class CardInstance:
    instance_id: int
    template: CardTemplate


@dataclass
class ResourceCard:
    template: CardTemplate
    tapped: bool = False
