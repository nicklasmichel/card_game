from __future__ import annotations

from dataclasses import dataclass, field

from core.ai.strategies.base import StrategyMetric, StrategyWeights


@dataclass(slots=True, frozen=True)
class PlanningState:
    phase: str
    hand_ids: tuple[int, ...]
    available_resources: int
    total_resources: int
    resources_played_this_turn: int
    creature_discount: int = 0
    reserved_resources: int = 0
    expected_attacker_ids: tuple[int, ...] = ()
    expected_own_losses: int = 0
    expected_enemy_losses: int = 0


@dataclass(slots=True, frozen=True)
class MainPhaseSequenceCandidate:
    phase: str
    resource_card_ids: tuple[int, ...] = ()
    card_sequence_ids: tuple[int, ...] = ()
    first_resource_ready: bool = False
    second_resource_tapped: bool = False
    ending_available_resources: int = 0
    ending_total_resources: int = 0
    projected_hand_ids: tuple[int, ...] = ()
    score: float = 0.0


@dataclass(slots=True, frozen=True)
class AttackCandidate:
    attacker_ids: tuple[int, ...] = ()
    expected_damage: int = 0
    expected_own_losses: int = 0
    expected_enemy_losses: int = 0
    expected_counterattack_damage: int = 0
    combat_started: bool = False
    expected_unblocked_attacker_ids: tuple[int, ...] = ()
    reserved_resources: int = 0
    reaction_intent_card_ids: tuple[int, ...] = ()
    score: float = 0.0


@dataclass(slots=True, frozen=True)
class EvaluationBreakdown:
    total_score: float
    player_damage_value: float = 0.0
    board_value: float = 0.0
    hand_value: float = 0.0
    counterattack_penalty: float = 0.0
    recycle_penalty: float = 0.0
    reason_codes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class TurnPlanCandidate:
    strategy_mode: str
    primary_goal: str
    strategy_reason_codes: tuple[str, ...]
    strategy_weights: StrategyWeights
    strategy_metrics: tuple[StrategyMetric, ...]
    planning_state: PlanningState
    main_1: MainPhaseSequenceCandidate
    attack: AttackCandidate
    main_2: MainPhaseSequenceCandidate | None
    breakdown: EvaluationBreakdown
    reaction_intents: tuple[dict, ...] = ()
    reserved_resources: int = 0
    expected_end_hand_ids: tuple[int, ...] = ()
    expected_end_total_resources: int = 0
    expected_end_available_resources: int = 0
    expected_end_own_creatures: int = 0
    expected_end_enemy_creatures: int = 0
    expected_enemy_life: int = 0
    expected_own_life: int = 0
    recycle_loss: int = 0
    reason_codes: tuple[str, ...] = ()
    candidate_rank_hint: int = 0

    def debug_summary(self) -> str:
        return (
            f"TurnPlanCandidate(mode={self.strategy_mode}, score={self.breakdown.total_score:.2f}, "
            f"m1_resources={list(self.main_1.resource_card_ids)}, "
            f"m1_sequence={list(self.main_1.card_sequence_ids)}, "
            f"attackers={list(self.attack.attacker_ids)}, "
            f"m2_sequence={list(self.main_2.card_sequence_ids) if self.main_2 is not None else []}, "
            f"counter={self.attack.expected_counterattack_damage}, recycle={self.recycle_loss})"
        )
