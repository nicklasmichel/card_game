from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuilderSearchBudget:
    max_exact_attack_candidates: int
    max_exact_block_assignments: int
    max_heuristic_attack_candidates: int
    max_heuristic_block_responses: int
    mode_name: str


FINAL_DECISION_SEARCH_BUDGET = BuilderSearchBudget(
    max_exact_attack_candidates=256,
    max_exact_block_assignments=256,
    max_heuristic_attack_candidates=48,
    max_heuristic_block_responses=24,
    mode_name="final",
)


TURN_LOOKAHEAD_SEARCH_BUDGET = BuilderSearchBudget(
    # Main-action comparison runs this search many times.  A smaller tactical
    # sample is sufficient here because the chosen action is re-evaluated once
    # with FINAL_DECISION_SEARCH_BUDGET before execution.
    max_exact_attack_candidates=12,
    max_exact_block_assignments=48,
    max_heuristic_attack_candidates=6,
    max_heuristic_block_responses=4,
    mode_name="lookahead",
)
