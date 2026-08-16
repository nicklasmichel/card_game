"""Diagnostics for long-running simulations and state validation."""

from .invariants import (
    GameInvariantError,
    collect_game_invariant_violations,
    collect_prepared_action_violations,
    validate_game_invariants,
    validate_prepared_action,
)
from .soak import (
    DecisionTiming,
    SoakConfig,
    SoakGameResult,
    SoakSummary,
    run_single_game,
    run_soak,
)

__all__ = [
    "DecisionTiming",
    "GameInvariantError",
    "SoakConfig",
    "SoakGameResult",
    "SoakSummary",
    "collect_game_invariant_violations",
    "collect_prepared_action_violations",
    "run_single_game",
    "run_soak",
    "validate_game_invariants",
    "validate_prepared_action",
]
