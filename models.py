from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


PHASE_MULLIGAN = "Mulligan"
PHASE_RESOURCE = "Ressourcenphase"
PHASE_MAIN = "Hauptphase"
PHASE_DECLARE_ATTACKERS = "Angreifer waehlen"
PHASE_DECLARE_BLOCKERS = "Blocker waehlen"
PHASE_ORDER_BLOCKERS = "Blockreihenfolge"
PHASE_DICE_BATTLE = "Wuerfelkampf"
PHASE_GAME_OVER = "Spielende"


@dataclass(frozen=True)
class CardTemplate:
    template_id: str
    name: str
    cost: int
    aw: int
    vw: int


@dataclass
class CardInstance:
    instance_id: int
    template: CardTemplate


@dataclass
class ResourceCard:
    source_name: str
    tapped: bool = False


@dataclass
class BattlefieldUnit:
    unit_id: int
    name: str
    cost: int
    aw: int
    vw: int
    current_hp: int
    tapped: bool = True
    summoning_sick: bool = True

    @classmethod
    def from_card(cls, card: CardInstance) -> "BattlefieldUnit":
        return cls(
            unit_id=card.instance_id,
            name=card.template.name,
            cost=card.template.cost,
            aw=card.template.aw,
            vw=card.template.vw,
            current_hp=card.template.vw,
        )

    @property
    def damage_taken(self) -> int:
        return self.vw - self.current_hp

    @property
    def aw_vw(self) -> str:
        return f"{self.aw}/{self.vw}"

    def is_ready(self) -> bool:
        return not self.tapped and not self.summoning_sick

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
    life: int = 20
    deck: List[CardInstance] = field(default_factory=list)
    hand: List[CardInstance] = field(default_factory=list)
    battlefield: List[BattlefieldUnit] = field(default_factory=list)
    resources: List[ResourceCard] = field(default_factory=list)
    resource_played_this_turn: bool = False
    turns_started: int = 0
    mulligan_used: bool = False

    def untap_for_turn(self) -> None:
        for resource in self.resources:
            resource.tapped = False
        for unit in self.battlefield:
            unit.tapped = False
            unit.summoning_sick = False
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


@dataclass
class DieResult:
    base_roll: int
    aw_bonus: int
    used: bool = False

    @property
    def total(self) -> int:
        return self.base_roll + self.aw_bonus

    def display(self) -> str:
        return f"{self.base_roll} + {self.aw_bonus} = {self.total}"


@dataclass
class DiceRoundRecord:
    round_number: int
    human_unit_name: str
    human_result: str
    enemy_unit_name: str
    enemy_result: str
    outcome_text: str


@dataclass
class PendingDiceBattle:
    attacker_id: int
    blocker_id: int
    attacker_owner: int
    blocker_owner: int
    attacker_dice: List[DieResult]
    blocker_dice: List[DieResult]
    ai_strategy_name: str
    ai_choose_die: Callable[[List[DieResult]], DieResult]
    history: List[DiceRoundRecord] = field(default_factory=list)


@dataclass
class PendingBlockOrder:
    attacker_id: int
    blocker_ids: List[int]
    chosen_order: List[int] = field(default_factory=list)


@dataclass
class ButtonSpec:
    label: str
    enabled: bool
    action: str
