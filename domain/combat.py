from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .cards import CardCost
from .enums import Ability, Element


@dataclass
class CombatUnitSnapshot:
    unit_id: int
    template_id: str | None
    name: str
    cost: CardCost
    aw: int
    vw: int
    lw: int
    sw: int
    current_hp: int
    element: Element
    abilities: frozenset[Ability]
    rules_text: str = ""
    tapped: bool = False

    @property
    def aw_vw(self) -> str:
        return f"{self.aw}/{self.vw}"


@dataclass
class DiceRoundRecord:
    round_number: int
    attacker_rolls: List[int]
    blocker_rolls: List[int]
    attack_sum: int
    defense_sum: int
    outcome_text: str


@dataclass
class PendingDiceBattle:
    attacker_id: int
    blocker_id: int
    attacker_owner: int
    blocker_owner: int
    attacker_snapshot: CombatUnitSnapshot
    blocker_snapshot: CombatUnitSnapshot
    attacker_rolls: List[int] = field(default_factory=list)
    blocker_rolls: List[int] = field(default_factory=list)
    attack_sum: int = 0
    defense_sum: int = 0
    reroll_count: int = 0
    winner: Optional[str] = None
    creature_damage: int = 0
    trample_damage: int = 0
    history: List[DiceRoundRecord] = field(default_factory=list)
    resolution_complete: bool = False


@dataclass
class PendingDirectAttack:
    attacker_id: int
    attacker_owner: int
    defending_player_id: int
    base_damage: int
