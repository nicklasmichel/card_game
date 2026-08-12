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
    max_exact_block_assignments=2200,
    max_heuristic_attack_candidates=48,
    max_heuristic_block_responses=40,
    mode_name="final",
)


TURN_LOOKAHEAD_SEARCH_BUDGET = BuilderSearchBudget(
    max_exact_attack_candidates=16,
    max_exact_block_assignments=180,
    max_heuristic_attack_candidates=8,
    max_heuristic_block_responses=8,
    mode_name="lookahead",
)
