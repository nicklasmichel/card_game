from __future__ import annotations


def reset_builder_game_caches() -> None:
    from .attack_policy import _COUNTER_MAIN_ACTION_CACHE
    from .combat_eval import _coerce_projected_unit_cached
    from .horizon import _HORIZON_MAIN_ACTION_CACHE
    from .turn_policy import _BUDGET_FRONTIER_CACHE, _FUTURE_SLOT_VALUE_CACHE

    _COUNTER_MAIN_ACTION_CACHE.clear()
    _HORIZON_MAIN_ACTION_CACHE.clear()
    _BUDGET_FRONTIER_CACHE.clear()
    _FUTURE_SLOT_VALUE_CACHE.clear()
    _coerce_projected_unit_cached.cache_clear()
