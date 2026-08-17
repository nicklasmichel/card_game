from __future__ import annotations

from dataclasses import dataclass

from .scoring import estimate_creature_board_value, score_builder_creature_candidate
from .snapshot import build_builder_snapshot
from .candidates import generate_builder_creature_candidates, is_legal_builder_candidate, select_builder_creature_search_frontier
from .search_control import builder_search_cache, builder_search_should_stop, count_builder_search_work


@dataclass(frozen=True)
class BuilderCapContext:
    creature_count: int
    creature_cap: int
    at_cap: bool
    weakest_unit_id: int | None
    weakest_unit_value: float
    best_replacement_value: float
    replacement_value: float
    cap_pressure: float


REPLACEMENT_TAPPED_DELAY_PENALTY = 0.7
REPLACEMENT_PRESSURE_DELAY_WEIGHT = 0.18
WEAKEST_GLASS_CANNON_PENALTY = 1.15
WEAKEST_SOFT_WALL_PENALTY = 1.2
CAP_PRESSURE_REPLACEMENT_WEIGHT = 0.92
CAP_PRESSURE_WEAK_SLOT_BONUS = 0.55
# Cap pressure is consulted in many hypothetical attack/counterattack states.
# Scoring 48 replacement bodies in every one of those states multiplied a
# five-on-five turn into thousands of full creature evaluations.  The shared
# frontier is already role-diverse; sixteen candidates retain its offensive,
# defensive and balanced leaders while keeping the tactical search usable.
CAP_REPLACEMENT_SCORING_LIMIT = 16


def estimate_builder_slot_unit_value(unit) -> float:
    value = estimate_creature_board_value(unit)
    if getattr(unit, "tapped", False):
        value -= 0.55
    if getattr(unit, "summoning_sickness", False):
        value -= 0.45
    if getattr(unit, "vw", 0) <= 0:
        value -= 0.4
    if getattr(unit, "aw", 0) == 0 and getattr(unit, "sw", 0) == 0:
        value -= 0.9
    elif getattr(unit, "aw", 0) == 0 and getattr(unit, "sw", 0) >= 3 and getattr(unit, "current_hp", 0) <= 1:
        value -= 1.2
    return round(value, 4)


def compute_builder_cap_context(player, engine, *, creature_cap: int, resource_budget: int | None = None) -> BuilderCapContext:
    battlefield = list(player.battlefield)
    creature_count = len(battlefield)
    if not battlefield:
        return BuilderCapContext(creature_count, creature_cap, False, None, 0.0, 0.0, 0.0, 0.0)

    weakest = min(battlefield, key=lambda unit: (estimate_builder_slot_unit_value(unit), unit.unit_id))
    weakest_value = estimate_builder_slot_unit_value(weakest)
    if creature_count < creature_cap:
        return BuilderCapContext(creature_count, creature_cap, False, weakest.unit_id, weakest_value, 0.0, 0.0, 0.0)

    snapshot = build_builder_snapshot(player, engine)
    if resource_budget is None:
        resource_budget = player.total_resources()
    cache = builder_search_cache("cap_context")
    cache_key = _cap_context_cache_key(player, engine, creature_cap, resource_budget)
    if cache is not None and cache_key in cache:
        count_builder_search_work("cap_cache_hits")
        return cache[cache_key]
    legal_candidates = [
        candidate
        for candidate in generate_builder_creature_candidates(snapshot, max(0, resource_budget))
        if is_legal_builder_candidate(candidate, max(0, resource_budget))
    ]
    if not legal_candidates:
        return BuilderCapContext(creature_count, creature_cap, True, weakest.unit_id, weakest_value, weakest_value, 0.0, 0.0)
    legal_candidates = select_builder_creature_search_frontier(
        legal_candidates,
        snapshot,
        limit=CAP_REPLACEMENT_SCORING_LIMIT,
    )

    enemy_battlefield = list(engine.players[1 - player.player_id].battlefield)
    best_replacement_value = float("-inf")
    for candidate in legal_candidates:
        if best_replacement_value != float("-inf") and builder_search_should_stop():
            break
        count_builder_search_work("cap_candidates_scored")
        candidate_score = score_builder_creature_candidate(
            candidate,
            snapshot,
            available_resources=max(0, resource_budget),
            enemy_creatures=enemy_battlefield,
            own_creatures=battlefield,
        ).total
        delay_penalty = REPLACEMENT_TAPPED_DELAY_PENALTY + snapshot.enemy_potential_attacker_count * REPLACEMENT_PRESSURE_DELAY_WEIGHT
        adjusted = candidate_score - delay_penalty
        if adjusted > best_replacement_value:
            best_replacement_value = adjusted
    best_replacement_value = max(0.0, best_replacement_value)
    replacement_value = max(0.0, best_replacement_value - weakest_value)
    pressure_factor = 1.0
    if snapshot.enemy_potential_attacker_count > snapshot.own_ready_attacker_count + 1:
        pressure_factor -= 0.35
    if snapshot.enemy_total_sw >= snapshot.own_total_current_hp * 0.6:
        pressure_factor -= 0.25
    if getattr(weakest, "tapped", False):
        pressure_factor += 0.25
    if getattr(weakest, "aw", 0) == 0 and getattr(weakest, "sw", 0) == 0:
        pressure_factor += 0.2
    weak_slot_bonus = 0.0
    if getattr(weakest, "aw", 0) == 0 and getattr(weakest, "sw", 0) >= 3 and getattr(weakest, "current_hp", 0) <= 1:
        weak_slot_bonus += WEAKEST_GLASS_CANNON_PENALTY
    if getattr(weakest, "aw", 0) == 0 and getattr(weakest, "sw", 0) == 0 and getattr(weakest, "vw", 0) <= 1:
        weak_slot_bonus += WEAKEST_SOFT_WALL_PENALTY
    cap_pressure = max(
        0.0,
        replacement_value * CAP_PRESSURE_REPLACEMENT_WEIGHT * max(0.25, pressure_factor)
        + weak_slot_bonus * CAP_PRESSURE_WEAK_SLOT_BONUS,
    )
    result = BuilderCapContext(
        creature_count=creature_count,
        creature_cap=creature_cap,
        at_cap=True,
        weakest_unit_id=weakest.unit_id,
        weakest_unit_value=round(weakest_value, 4),
        best_replacement_value=round(best_replacement_value, 4),
        replacement_value=round(replacement_value, 4),
        cap_pressure=round(cap_pressure, 4),
    )
    if cache is not None and not builder_search_should_stop():
        cache[cache_key] = result
    return result


def _cap_context_cache_key(player, engine, creature_cap: int, resource_budget: int) -> tuple:
    state_signature = getattr(engine, "state_signature", None)
    if state_signature is None:
        enemy = engine.players[1 - player.player_id]
        state_signature = (
            player.life,
            enemy.life,
            player.total_resources(),
            player.available_resources(),
            enemy.total_resources(),
            tuple(_cap_unit_signature(unit) for unit in player.battlefield),
            tuple(_cap_unit_signature(unit) for unit in enemy.battlefield),
        )
    return player.player_id, creature_cap, resource_budget, state_signature


def _cap_unit_signature(unit) -> tuple:
    return (
        unit.unit_id,
        unit.aw,
        unit.vw,
        unit.sw,
        unit.lw,
        unit.current_hp,
        bool(getattr(unit, "tapped", False)),
        bool(getattr(unit, "summoning_sickness", False)),
        tuple(sorted(getattr(ability, "value", str(ability)) for ability in unit.abilities)),
    )
