from __future__ import annotations

from itertools import combinations
from math import factorial

from core.models import Ability

from .combat_eval import can_legally_be_forced_to_block, can_legally_block, estimate_builder_combat
from .search_budget import FINAL_DECISION_SEARCH_BUDGET
from .scoring import estimate_creature_board_value

FULL_BLOCK_ENUMERATION_ATTACKER_THRESHOLD = 6
FULL_BLOCK_ENUMERATION_BLOCKER_THRESHOLD = 6


def canonicalize_assignment(assignments: dict[int, int] | tuple[tuple[int, int], ...] | list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    if isinstance(assignments, dict):
        items = assignments.items()
    else:
        items = assignments
    return tuple(sorted((int(attacker_id), int(blocker_id)) for attacker_id, blocker_id in items))


def get_forced_block_map_from_engine(engine) -> dict[int, int]:
    return {
        attacker_id: blocker_id
        for attacker_id, blocker_id in getattr(engine, "block_assignments", {}).items()
        if attacker_id in getattr(engine, "enraged_forced_attackers", set()) and blocker_id is not None
    }


def get_declared_attackers_for_defender(defending_player, engine) -> list:
    attacker_ids = set(getattr(engine, "block_assignments", {}).keys())
    enemy = engine.players[1 - defending_player.player_id]
    return [creature for creature in enemy.battlefield if creature.unit_id in attacker_ids]


def get_available_blockers_for_defender(defending_player, engine) -> list:
    return list(engine.available_blockers(defending_player))


def generate_block_assignment_tuples(
    attackers: list,
    blockers: list,
    forced_map: dict[int, int],
    *,
    search_budget=None,
    metadata: dict | None = None,
) -> list[tuple[tuple[int, int], ...]]:
    budget = FINAL_DECISION_SEARCH_BUDGET if search_budget is None else search_budget
    upper_bound = estimate_block_assignment_upper_bound(len(attackers), len(blockers))
    exact_search = (
        len(attackers) <= FULL_BLOCK_ENUMERATION_ATTACKER_THRESHOLD
        and len(blockers) <= FULL_BLOCK_ENUMERATION_BLOCKER_THRESHOLD
        and upper_bound <= budget.max_exact_block_assignments
    )
    if exact_search:
        assignments = _generate_exhaustive_block_assignments(attackers, blockers, forced_map)
    else:
        assignments = _generate_heuristic_block_assignments(
            attackers,
            blockers,
            forced_map,
            limit=budget.max_heuristic_block_responses,
        )
    if metadata is not None:
        metadata.update(
            {
                "exact_search": exact_search,
                "generated_block_assignments": len(assignments),
                "evaluated_block_assignments": len(assignments),
                "pruned_candidates": max(0, upper_bound - len(assignments)),
                "block_assignment_upper_bound": upper_bound,
            }
        )
    return assignments


def estimate_block_assignment_upper_bound(attacker_count: int, blocker_count: int) -> int:
    total = 1
    maximum = min(attacker_count, blocker_count)
    for used in range(1, maximum + 1):
        total += _combination(attacker_count, used) * _permutations(blocker_count, used)
    return total


def _generate_exhaustive_block_assignments(
    attackers: list,
    blockers: list,
    forced_map: dict[int, int],
) -> list[tuple[tuple[int, int], ...]]:
    raw_assignments: list[dict[int, int]] = []
    _enumerate_block_assignments(raw_assignments, attackers, blockers, forced_map, 0, {}, set())
    unique = {canonicalize_assignment(assignment) for assignment in raw_assignments}
    if not unique:
        unique = {tuple()}
    return sorted(unique)


def _enumerate_block_assignments(
    assignments: list[dict[int, int]],
    attackers: list,
    blockers: list,
    forced_map: dict[int, int],
    index: int,
    current: dict[int, int],
    used_blockers: set[int],
) -> None:
    if index >= len(attackers):
        assignments.append(dict(current))
        return
    attacker = attackers[index]
    if attacker.unit_id in forced_map:
        blocker_id = forced_map[attacker.unit_id]
        blocker = next((unit for unit in blockers if unit.unit_id == blocker_id), None)
        if blocker is not None and blocker.unit_id not in used_blockers and can_legally_be_forced_to_block(attacker, blocker, require_ready=True):
            current[attacker.unit_id] = blocker.unit_id
            _enumerate_block_assignments(assignments, attackers, blockers, forced_map, index + 1, current, used_blockers | {blocker.unit_id})
            current.pop(attacker.unit_id, None)
        return
    _enumerate_block_assignments(assignments, attackers, blockers, forced_map, index + 1, current, used_blockers)
    for blocker in blockers:
        if blocker.unit_id in used_blockers:
            continue
        if not can_legally_block(attacker, blocker, require_ready=True):
            continue
        current[attacker.unit_id] = blocker.unit_id
        _enumerate_block_assignments(assignments, attackers, blockers, forced_map, index + 1, current, used_blockers | {blocker.unit_id})
        current.pop(attacker.unit_id, None)


def _generate_heuristic_block_assignments(
    attackers: list,
    blockers: list,
    forced_map: dict[int, int],
    *,
    limit: int,
) -> list[tuple[tuple[int, int], ...]]:
    assignments: set[tuple[tuple[int, int], ...]] = {canonicalize_assignment(forced_map)}

    def add_assignment(assignment: dict[int, int] | tuple[tuple[int, int], ...]) -> None:
        assignments.add(canonicalize_assignment(assignment))

    def greedy(attacker_order: list, blocker_mode: str) -> None:
        current = dict(forced_map)
        used = set(forced_map.values())
        for attacker in attacker_order:
            if attacker.unit_id in current:
                continue
            available = [
                blocker
                for blocker in blockers
                if blocker.unit_id not in used and can_legally_block(attacker, blocker, require_ready=True)
            ]
            if not available:
                continue
            blocker = _select_blocker_for_mode(attacker, available, blocker_mode)
            if blocker is None:
                continue
            current[attacker.unit_id] = blocker.unit_id
            used.add(blocker.unit_id)
        add_assignment(current)

    add_assignment(_maximal_matching(attackers, blockers, forced_map))
    attacker_orders = [
        sorted(attackers, key=lambda unit: (_attacker_priority(unit, mode="trample"), unit.unit_id), reverse=True),
        sorted(attackers, key=lambda unit: (_attacker_priority(unit, mode="lethal"), unit.unit_id), reverse=True),
        sorted(attackers, key=lambda unit: (_attacker_priority(unit, mode="value"), unit.unit_id), reverse=True),
        sorted(attackers, key=lambda unit: (_attacker_priority(unit, mode="flying"), unit.unit_id), reverse=True),
        sorted(attackers, key=lambda unit: (_attacker_priority(unit, mode="lifesteal"), unit.unit_id), reverse=True),
    ]
    blocker_modes = ["trade", "survival", "cheap", "anti_trample", "anti_lifesteal", "flying_preserve"]
    for attacker_order in attacker_orders:
        for blocker_mode in blocker_modes:
            greedy(attacker_order, blocker_mode)

    current_assignments = sorted(assignments)
    for assignment in current_assignments[:8]:
        add_assignment(_single_swap_variant(assignment, attackers, blockers, forced_map))
        add_assignment(_single_drop_variant(assignment, forced_map))

    return sorted(assignments)[: max(1, limit)]


def _attacker_priority(attacker, *, mode: str) -> tuple[float, ...]:
    value = estimate_creature_board_value(attacker)
    if mode == "trample":
        return (1.0 if attacker.has_ability(Ability.TRAMPLE) else 0.0, attacker.sw, value)
    if mode == "flying":
        return (1.0 if attacker.has_ability(Ability.FLYING) else 0.0, attacker.sw, value)
    if mode == "lifesteal":
        return (1.0 if attacker.has_ability(Ability.LIFE_STEAL) else 0.0, attacker.sw, value)
    if mode == "lethal":
        return (attacker.sw, 1.0 if attacker.has_ability(Ability.TRAMPLE) else 0.0, value)
    return (value, attacker.sw, attacker.aw)


def _select_blocker_for_mode(attacker, available: list, blocker_mode: str):
    scored: list[tuple[tuple[float, ...], object]] = []
    for blocker in available:
        estimate = estimate_builder_combat(attacker, blocker)
        attacker_value = estimate_creature_board_value(attacker)
        blocker_value = estimate_creature_board_value(blocker)
        prevented_damage = max(0.0, attacker.sw - estimate.expected_player_damage)
        trade_swing = estimate.attacker_death_probability * attacker_value - estimate.defender_death_probability * blocker_value
        flying_preserve_penalty = (
            estimate.defender_death_probability
            if blocker.has_ability(Ability.FLYING) and not attacker.has_ability(Ability.FLYING)
            else 0.0
        )
        if blocker_mode == "cheap":
            score = (prevented_damage, -blocker_value, trade_swing, -blocker.unit_id)
        elif blocker_mode == "anti_trample":
            score = (
                1.0 if attacker.has_ability(Ability.TRAMPLE) else 0.0,
                prevented_damage,
                -estimate.expected_player_damage,
                -blocker_value,
                -blocker.unit_id,
            )
        elif blocker_mode == "anti_lifesteal":
            score = (
                1.0 if attacker.has_ability(Ability.LIFE_STEAL) else 0.0,
                prevented_damage,
                -estimate.expected_attacker_heal,
                trade_swing,
                -blocker.unit_id,
            )
        elif blocker_mode == "flying_preserve":
            score = (
                1.0 if attacker.has_ability(Ability.FLYING) else 0.0,
                prevented_damage,
                -flying_preserve_penalty,
                trade_swing,
                -blocker.unit_id,
            )
        elif blocker_mode == "survival":
            score = (prevented_damage, -estimate.defender_death_probability, trade_swing, blocker.current_hp, -blocker.unit_id)
        else:
            score = (trade_swing, prevented_damage, estimate.attacker_death_probability, -estimate.defender_death_probability, -blocker.unit_id)
        scored.append((score, blocker))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored else None


def _maximal_matching(attackers: list, blockers: list, forced_map: dict[int, int]) -> dict[int, int]:
    current = dict(forced_map)
    used = set(forced_map.values())
    for size in range(min(len(attackers), len(blockers)), 0, -1):
        for attacker_group in combinations([attacker for attacker in attackers if attacker.unit_id not in current], size):
            temp = dict(current)
            temp_used = set(used)
            complete = True
            for attacker in attacker_group:
                blocker = _select_blocker_for_mode(
                    attacker,
                    [unit for unit in blockers if unit.unit_id not in temp_used and can_legally_block(attacker, unit, require_ready=True)],
                    "cheap",
                )
                if blocker is None:
                    complete = False
                    break
                temp[attacker.unit_id] = blocker.unit_id
                temp_used.add(blocker.unit_id)
            if complete:
                return temp
    return current


def _single_swap_variant(
    assignment: tuple[tuple[int, int], ...],
    attackers: list,
    blockers: list,
    forced_map: dict[int, int],
) -> tuple[tuple[int, int], ...]:
    if not assignment:
        return assignment
    current = dict(assignment)
    used = set(current.values())
    for attacker in attackers:
        if attacker.unit_id in forced_map:
            continue
        original = current.get(attacker.unit_id)
        available = [
            blocker
            for blocker in blockers
            if blocker.unit_id != original
            and (blocker.unit_id not in used or blocker.unit_id == original)
            and can_legally_block(attacker, blocker, require_ready=True)
        ]
        replacement = _select_blocker_for_mode(attacker, available, "trade")
        if replacement is None:
            continue
        current[attacker.unit_id] = replacement.unit_id
        return canonicalize_assignment(current)
    return assignment


def _single_drop_variant(
    assignment: tuple[tuple[int, int], ...],
    forced_map: dict[int, int],
) -> tuple[tuple[int, int], ...]:
    for attacker_id, blocker_id in assignment:
        if forced_map.get(attacker_id) == blocker_id:
            continue
        reduced = dict(assignment)
        reduced.pop(attacker_id, None)
        return canonicalize_assignment(reduced)
    return assignment


def player_damage_distribution_for_combat(attacker, estimate) -> dict[int, float]:
    if estimate.expected_player_damage <= 0 or estimate.attacker_win_probability <= 0:
        return {0: 1.0}
    overflow = int(round(estimate.expected_player_damage / estimate.attacker_win_probability))
    return {0: 1.0 - estimate.attacker_win_probability, overflow: estimate.attacker_win_probability}


def convolve_damage_distributions(distributions: list[dict[int, float]]) -> dict[int, float]:
    totals = {0: 1.0}
    for distribution in distributions:
        next_totals: dict[int, float] = {}
        for total_damage, total_probability in totals.items():
            for damage, probability in distribution.items():
                next_totals[total_damage + damage] = next_totals.get(total_damage + damage, 0.0) + total_probability * probability
        totals = next_totals
    return totals


def _combination(total: int, chosen: int) -> int:
    if chosen < 0 or chosen > total:
        return 0
    return factorial(total) // (factorial(chosen) * factorial(total - chosen))


def _permutations(total: int, chosen: int) -> int:
    if chosen < 0 or chosen > total:
        return 0
    return factorial(total) // factorial(total - chosen)
