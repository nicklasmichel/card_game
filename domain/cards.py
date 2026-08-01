from __future__ import annotations

from dataclasses import dataclass

from .enums import Ability, Element


@dataclass(frozen=True)
class CardCost:
    resources: int = 0
    recycle: int = 0

    def __post_init__(self) -> None:
        if self.resources < 0:
            raise ValueError("Ressourcenkosten dürfen nicht negativ sein.")
        if self.recycle < 0:
            raise ValueError("Recyclekosten dürfen nicht negativ sein.")

    @property
    def total_value(self) -> int:
        return self.resources + self.recycle


@dataclass(frozen=True)
class CardTemplate:
    template_id: str
    name: str
    cost: CardCost
    aw: int
    vw: int
    element: Element
    abilities: frozenset[Ability] = frozenset()
    rules_text: str = ""
    self_damage_on_play: int = 0
    opponent_damage_on_play: int = 0
    discard_self_on_play: int = 0
    discard_opponent_on_play: int = 0
    reveal_opponent_hand: bool = False
    return_to_deck_end_of_turn: bool = False
    cannot_block: bool = False

    def has_ability(self, ability: Ability) -> bool:
        return ability in self.abilities

    @property
    def resource_cost(self) -> int:
        return self.cost.resources

    @property
    def recycle_cost(self) -> int:
        return self.cost.recycle


@dataclass
class CardInstance:
    instance_id: int
    template: CardTemplate
    was_recycled: bool = False


@dataclass
class ResourceCard:
    template: CardTemplate
    resource_id: int | None = None
    tapped: bool = False


@dataclass
class PendingRecyclePayment:
    card_instance_id: int
    required_count: int
    selected_resource_ids: list[int]


@dataclass
class PendingForcedDiscard:
    target_player_id: int
    required_count: int
    selected_card_ids: list[int]
    source_card_name: str
    return_phase: str
