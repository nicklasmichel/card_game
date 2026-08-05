from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True, frozen=True)
class StrategyWeights:
    player_damage: float = 1.0
    lethal: float = 1.0
    own_losses: float = 1.0
    enemy_losses: float = 1.0
    board_width: float = 1.0
    third_attacker: float = 1.0
    flying_damage: float = 1.0
    recycle_penalty: float = 1.0
    counterattack_risk: float = 1.0
    draw_value: float = 1.0
    graveyard_value: float = 1.0
    bounce_tempo: float = 1.0
    blocker_value: float = 1.0
    future_playability: float = 1.0


@dataclass(slots=True, frozen=True)
class StrategyMetric:
    key: str
    value: str


@dataclass(slots=True, frozen=True)
class StrategyDecision:
    mode: str
    primary_goal: str
    reason_codes: tuple[str, ...] = ()
    weights: StrategyWeights = field(default_factory=StrategyWeights)
    metrics: tuple[StrategyMetric, ...] = ()


class DeckStrategy(Protocol):
    def evaluate(
        self,
        ai,
        player,
        engine,
        *,
        hand,
        available_resources: int,
        total_resources: int,
        phase: str,
    ) -> StrategyDecision: ...
