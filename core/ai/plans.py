from __future__ import annotations

from dataclasses import dataclass, field, replace

from core.ai.strategies.base import StrategyMetric, StrategyWeights


PLAN_STATUS_PLANNED = "planned"
PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_PARTIAL = "partially_executed"
PLAN_STATUS_COMPLETED = "completed"
PLAN_STATUS_INVALID = "invalid"
PLAN_STATUS_DISCARDED = "discarded"

STEP_STATUS_PLANNED = "planned"
STEP_STATUS_COMPLETED = "completed"
STEP_STATUS_SKIPPED = "skipped"

VALIDATION_STATUS_VALID = "valid"
VALIDATION_STATUS_PARTIAL = "partially_valid"
VALIDATION_STATUS_REPLAN = "replan_required"
VALIDATION_STATUS_COMPLETED = "completed"


@dataclass(slots=True, frozen=True)
class PlanStep:
    action_type: str
    card_instance_id: int | None = None
    target_ids: tuple[int, ...] = ()
    expected_phase: str | None = None
    required_available_resources: int = 0
    expected_recycle_cost: int = 0
    reason_codes: tuple[str, ...] = ()
    status: str = STEP_STATUS_PLANNED


@dataclass(slots=True, frozen=True)
class PlannedAttack:
    attacker_ids: tuple[int, ...] = ()
    expected_damage: int | None = None
    expected_blocker_ids: tuple[int, ...] = ()
    reserved_resources: int = 0
    reserved_card_instance_ids: tuple[int, ...] = ()

    @property
    def expected_attacker_count(self) -> int:
        return len(self.attacker_ids)

    @property
    def triggers_summoner_passive(self) -> bool:
        return len(self.attacker_ids) >= 3


@dataclass(slots=True, frozen=True)
class ReactionIntent:
    card_instance_id: int
    allowed_triggers: tuple[str, ...] = ()
    condition_reason_code: str = ""
    reserved_resources: int = 0
    preferred_target_ids: tuple[int, ...] = ()


@dataclass(slots=True, frozen=True)
class ResourceReservation:
    amount: int
    purpose_reason_code: str
    card_instance_id: int | None = None
    expected_timing_window: str | None = None


@dataclass(slots=True, frozen=True)
class PlanValidationResult:
    status: str
    reason_codes: tuple[str, ...] = ()
    invalid_step_index: int | None = None
    can_skip_current_step: bool = False


@dataclass(slots=True, frozen=True)
class TurnPlan:
    plan_id: int
    revision: int
    player_id: int
    turn_number: int
    created_phase: str
    status: str = PLAN_STATUS_PLANNED
    steps: tuple[PlanStep, ...] = ()
    attack: PlannedAttack = field(default_factory=PlannedAttack)
    reaction_intents: tuple[ReactionIntent, ...] = ()
    resource_reservations: tuple[ResourceReservation, ...] = ()
    strategy_mode: str = ""
    primary_goal: str = ""
    strategy_reason_codes: tuple[str, ...] = ()
    strategy_weights: StrategyWeights = field(default_factory=StrategyWeights)
    strategy_metrics: tuple[StrategyMetric, ...] = ()
    next_step_index: int = 0
    completed_step_indices: tuple[int, ...] = ()
    skipped_step_indices: tuple[int, ...] = ()
    invalid_reason_codes: tuple[str, ...] = ()

    def current_step(self) -> PlanStep | None:
        if self.next_step_index >= len(self.steps):
            return None
        return self.steps[self.next_step_index]

    def step_for_card(self, card_instance_id: int) -> PlanStep | None:
        for step in self.steps:
            if step.card_instance_id == card_instance_id:
                return step
        return None

    def with_status(self, status: str, *, invalid_reason_codes: tuple[str, ...] | None = None) -> TurnPlan:
        return replace(
            self,
            status=status,
            invalid_reason_codes=self.invalid_reason_codes if invalid_reason_codes is None else invalid_reason_codes,
        )

    def with_step_completed(self, index: int) -> TurnPlan:
        if index < 0 or index >= len(self.steps):
            return self
        updated_steps = list(self.steps)
        updated_steps[index] = replace(updated_steps[index], status=STEP_STATUS_COMPLETED)
        completed = tuple(sorted({*self.completed_step_indices, index}))
        next_index = self.next_step_index
        while next_index < len(updated_steps) and updated_steps[next_index].status != STEP_STATUS_PLANNED:
            next_index += 1
        status = PLAN_STATUS_COMPLETED if next_index >= len(updated_steps) else PLAN_STATUS_PARTIAL
        return replace(
            self,
            steps=tuple(updated_steps),
            next_step_index=next_index,
            completed_step_indices=completed,
            status=status,
        )

    def with_step_skipped(self, index: int) -> TurnPlan:
        if index < 0 or index >= len(self.steps):
            return self
        updated_steps = list(self.steps)
        updated_steps[index] = replace(updated_steps[index], status=STEP_STATUS_SKIPPED)
        skipped = tuple(sorted({*self.skipped_step_indices, index}))
        next_index = self.next_step_index
        while next_index < len(updated_steps) and updated_steps[next_index].status != STEP_STATUS_PLANNED:
            next_index += 1
        status = PLAN_STATUS_COMPLETED if next_index >= len(updated_steps) else PLAN_STATUS_PARTIAL
        return replace(
            self,
            steps=tuple(updated_steps),
            next_step_index=next_index,
            skipped_step_indices=skipped,
            status=status,
        )

    def debug_summary(self) -> str:
        current = self.current_step()
        step_text = current.action_type if current is not None else "none"
        return (
            f"TurnPlan(id={self.plan_id}, turn={self.turn_number}, status={self.status}, "
            f"mode={self.strategy_mode or 'none'}, next_step={step_text}, attack={len(self.attack.attacker_ids)}, "
            f"reservations={sum(item.amount for item in self.resource_reservations)})"
        )
