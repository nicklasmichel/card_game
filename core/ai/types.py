from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DecisionReason:
    reason_code: str
    metrics: dict[str, float | int | bool | str] = field(default_factory=dict)


@dataclass(slots=True)
class ActionCandidate:
    action_type: str
    card_instance_id: int | None = None
    target_ids: tuple[int, ...] = ()
    reserved_resources: int = 0
    recycle_cost: int = 0
    score: float = 0.0
    reason: DecisionReason | None = None


@dataclass(slots=True)
class BoundPlan:
    sequence: tuple[int, ...] = ()
    attacker_ids: tuple[int, ...] = ()
    target_ids: tuple[int, ...] = ()
    reserved_resources: int = 0
    reason: DecisionReason | None = None
