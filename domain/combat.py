from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


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
class PendingComparison:
    attacker_die: DieResult
    blocker_die: DieResult
    human_is_attacker: bool
    human_can_adapt: bool = False
    human_used_adaptation: bool = False


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
    attacker_used_adaptation: bool = False
    blocker_used_adaptation: bool = False
    pending_comparison: Optional[PendingComparison] = None


@dataclass
class PendingBlockOrder:
    attacker_id: int
    blocker_ids: List[int]
    chosen_order: List[int] = field(default_factory=list)
