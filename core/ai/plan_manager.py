from __future__ import annotations

from dataclasses import replace

from core.ai.plans import PLAN_STATUS_ACTIVE, PLAN_STATUS_COMPLETED, TurnPlan


class PlanManager:
    def __init__(self) -> None:
        self._active_turn_plan: TurnPlan | None = None
        self._last_turn_plan: TurnPlan | None = None
        self._turn_plan_revision: int = 0
        self._next_turn_plan_id: int = 1

    @property
    def active_turn_plan(self) -> TurnPlan | None:
        return self._active_turn_plan

    @property
    def last_turn_plan(self) -> TurnPlan | None:
        return self._last_turn_plan

    def next_plan_identity(self) -> tuple[int, int]:
        plan_id = self._next_turn_plan_id
        self._next_turn_plan_id += 1
        self._turn_plan_revision += 1
        return plan_id, self._turn_plan_revision

    def activate(self, plan: TurnPlan) -> None:
        self._active_turn_plan = plan.with_status(PLAN_STATUS_ACTIVE if plan.steps else plan.status)

    def clear(self, *, reason_codes: tuple[str, ...] = (), status: str) -> None:
        if self._active_turn_plan is not None:
            self._last_turn_plan = self._active_turn_plan.with_status(status, invalid_reason_codes=reason_codes)
        self._active_turn_plan = None

    def mark_completed(self, action_type: str, *, card_instance_id: int | None = None) -> None:
        plan = self._active_turn_plan
        if plan is None:
            return
        step = plan.current_step()
        if step is None:
            self.clear(reason_codes=("plan_completed",), status=PLAN_STATUS_COMPLETED)
            return
        if step.action_type != action_type:
            return
        if card_instance_id is not None and step.card_instance_id != card_instance_id:
            return
        updated = plan.with_step_completed(plan.next_step_index)
        if updated.status == PLAN_STATUS_COMPLETED:
            self._last_turn_plan = updated
            self._active_turn_plan = None
            return
        self._active_turn_plan = updated

