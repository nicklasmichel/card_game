from __future__ import annotations

from functools import lru_cache

from core.builder_rules import (
    BUILDER_BASE_STATS,
    BUILDER_CREATURE_STAT_CAP,
    builder_creature_stat_cost,
    builder_creature_stats_are_valid,
    validate_builder_creature_abilities,
)
from core.models import Ability

from .types import BuilderCreatureCandidate, BuilderStrategicSnapshot


_SEARCH_FRONTIER_PROFILES = (
    (4, 0, 4, 1),  # immediate pressure
    (4, 2, 2, 1),  # attack through medium defense
    (2, 1, 4, 1),  # damage delivery
    (1, 4, 1, 4),  # durable blocker
    (2, 4, 2, 2),  # active defense
    (2, 2, 2, 2),  # balanced body
    (1, 2, 1, 5),  # high-life wall
    (3, 1, 3, 3),  # resilient pressure
)


def candidate_cost(*, aw: int, vw: int, sw: int, lw: int, ability: Ability | None = None, has_haste: bool = False) -> int:
    if ability is not None:
        raise ValueError("Haste is the only ability available during creature building")
    return builder_creature_stat_cost(
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
    )


def is_legal_builder_candidate(candidate: BuilderCreatureCandidate, available_resources: int) -> bool:
    if not builder_creature_stats_are_valid(
        aw=candidate.aw,
        vw=candidate.vw,
        sw=candidate.sw,
        lw=candidate.lw,
    ):
        return False
    try:
        validate_builder_creature_abilities(candidate.abilities)
    except ValueError:
        return False
    expected_cost = candidate_cost(
        aw=candidate.aw,
        vw=candidate.vw,
        sw=candidate.sw,
        lw=candidate.lw,
        ability=candidate.builder_ability,
        has_haste=candidate.has_haste,
    )
    if candidate.cost != expected_cost:
        return False
    return candidate.cost <= available_resources and (not candidate.has_haste or available_resources >= 1)


def generate_builder_creature_candidates(
    snapshot: BuilderStrategicSnapshot,
    available_resources: int,
) -> list[BuilderCreatureCandidate]:
    if available_resources < 0:
        return []
    budgets = _candidate_budgets(snapshot, available_resources)
    candidates: dict[tuple[int, int, int, int, str], BuilderCreatureCandidate] = {}
    for budget in budgets:
        for candidate in _generate_cached_budget_candidates(budget):
            candidates[candidate.key] = candidate
    return sorted(candidates.values(), key=lambda candidate: (candidate.cost, candidate.key, candidate.generation_reason))


@lru_cache(maxsize=32)
def _generate_cached_budget_candidates(budget: int) -> tuple[BuilderCreatureCandidate, ...]:
    candidates: dict[tuple[int, int, int, int, str], BuilderCreatureCandidate] = {}
    _generate_budget_candidates(candidates, budget)
    return tuple(sorted(candidates.values(), key=lambda candidate: (candidate.cost, candidate.key, candidate.generation_reason)))


def builder_candidate_budgets(snapshot: BuilderStrategicSnapshot, available_resources: int) -> tuple[int, ...]:
    return _candidate_budgets(snapshot, available_resources)


def select_builder_creature_search_frontier(
    candidates: list[BuilderCreatureCandidate],
    snapshot: BuilderStrategicSnapshot,
    *,
    limit: int,
) -> list[BuilderCreatureCandidate]:
    """Keep a small, diverse set for expensive tactical evaluation.

    Candidate generation stays exhaustive so callers and tests can inspect every
    legal build.  The game tree, however, only needs representative stat shapes
    for each ability.  Round-robin selection prevents a single raw-score ranking
    from dropping a tactically important wall, haste body, flyer, or damage
    breakpoint.
    """
    if limit <= 0:
        return []
    if len(candidates) <= limit:
        return list(candidates)

    buckets: list[list[BuilderCreatureCandidate]] = []
    ability_groups: list[list[BuilderCreatureCandidate]] = []
    ability_profiles = sorted(
        {(candidate.builder_ability, candidate.has_haste) for candidate in candidates},
        key=lambda profile: (getattr(profile[0], "value", ""), profile[1]),
    )
    for ability, has_haste in ability_profiles:
        group = [
            candidate
            for candidate in candidates
            if candidate.builder_ability == ability and candidate.has_haste == has_haste
        ]
        if not group:
            continue
        ability_groups.append(group)
        buckets.append(sorted(group, key=_cheap_candidate_search_key, reverse=True))
        buckets.append(sorted(group, key=lambda candidate: (candidate.sw, candidate.aw, candidate.vw, candidate.lw, candidate.key), reverse=True))
        buckets.append(sorted(group, key=lambda candidate: (candidate.aw, candidate.sw, candidate.lw, candidate.vw, candidate.key), reverse=True))
        buckets.append(sorted(group, key=lambda candidate: (candidate.vw, candidate.lw, candidate.sw, candidate.aw, candidate.key), reverse=True))
        buckets.append(sorted(group, key=lambda candidate: (candidate.lw, candidate.vw, candidate.sw, candidate.aw, candidate.key), reverse=True))
        buckets.append(
            sorted(
                group,
                key=lambda candidate: (
                    min(candidate.aw, candidate.vw, candidate.sw),
                    min(candidate.vw, candidate.lw - 1),
                    candidate.sw,
                    candidate.key,
                ),
                reverse=True,
            )
        )
        named_profiles = [candidate for candidate in group if candidate.generation_reason != "exhaustive"]
        if named_profiles:
            buckets.append(sorted(named_profiles, key=_cheap_candidate_search_key, reverse=True))
        for profile in _SEARCH_FRONTIER_PROFILES:
            buckets.append(sorted(group, key=lambda candidate, current=profile: _profile_fit_key(candidate, current), reverse=True))

    selected: dict[tuple, BuilderCreatureCandidate] = {}
    # Guarantee representation before the round-robin walks the larger profile
    # bucket list.  Small counter-search limits must still contain every ability.
    for group in ability_groups:
        candidate = max(group, key=_cheap_candidate_search_key)
        selected.setdefault(candidate.key, candidate)
        if len(selected) >= limit:
            return list(selected.values())
    for group in ability_groups:
        candidate = max(group, key=lambda current: (current.vw, current.lw, current.sw, current.key))
        selected.setdefault(candidate.key, candidate)
        if len(selected) >= limit:
            return list(selected.values())
    offsets = [0] * len(buckets)
    while len(selected) < limit:
        made_progress = False
        for bucket_index, bucket in enumerate(buckets):
            while offsets[bucket_index] < len(bucket):
                candidate = bucket[offsets[bucket_index]]
                offsets[bucket_index] += 1
                if candidate.key in selected:
                    continue
                selected[candidate.key] = candidate
                made_progress = True
                break
            if len(selected) >= limit:
                break
        if not made_progress:
            break

    if len(selected) < limit:
        for candidate in sorted(candidates, key=_cheap_candidate_search_key, reverse=True):
            selected.setdefault(candidate.key, candidate)
            if len(selected) >= limit:
                break
    return list(selected.values())


def _cheap_candidate_search_key(candidate: BuilderCreatureCandidate) -> tuple:
    return (
        candidate.sw * 1.20 + candidate.aw + candidate.vw * 0.92 + (candidate.lw - 1) * 0.78,
        min(candidate.aw, candidate.vw, candidate.sw),
        candidate.key,
    )


def _profile_fit_key(candidate: BuilderCreatureCandidate, profile: tuple[int, int, int, int]) -> tuple:
    candidate_stats = tuple(
        max(0, value - base)
        for value, base in zip(candidate.signature, BUILDER_BASE_STATS)
    )
    candidate_total = max(1, sum(candidate_stats))
    profile_total = max(1, sum(profile))
    distance = sum(
        abs(current / candidate_total - target / profile_total)
        for current, target in zip(candidate_stats, profile)
    )
    return (-distance, _cheap_candidate_search_key(candidate))


def _candidate_budgets(snapshot: BuilderStrategicSnapshot, available_resources: int) -> tuple[int, ...]:
    if available_resources < 0:
        return ()
    return (available_resources,)


def _generate_budget_candidates(
    candidates: dict[tuple[int, int, int, int, str], BuilderCreatureCandidate],
    budget: int,
) -> None:
    if budget == 0:
        _add_candidate(candidates, aw=0, vw=0, sw=0, lw=1, generation_reason="zero_budget")
        return

    maximum_stat = BUILDER_CREATURE_STAT_CAP
    maximum_life_bonus = BUILDER_CREATURE_STAT_CAP - 1
    for aw_bonus in range(min(budget, maximum_stat) + 1):
        for vw_bonus in range(min(budget - aw_bonus, maximum_stat) + 1):
            for sw_bonus in range(min(budget - aw_bonus - vw_bonus, maximum_stat) + 1):
                hp_budget = budget - aw_bonus - vw_bonus - sw_bonus
                if hp_budget > maximum_life_bonus:
                    continue
                lw = 1 + hp_budget
                _add_candidate(
                    candidates,
                    aw=aw_bonus,
                    vw=vw_bonus,
                    sw=sw_bonus,
                    lw=lw,
                    generation_reason="exhaustive",
                )

    for profile_name, weights in (
        ("aggressive", (3, 0, 3, 1)),
        ("defensive", (1, 3, 1, 3)),
        ("hybrid", (2, 2, 2, 2)),
        ("damage", (1, 0, 4, 1)),
        ("attack", (4, 1, 2, 1)),
        ("wall", (0, 4, 1, 4)),
        ("sturdy", (1, 2, 1, 4)),
    ):
        aw, vw, sw, lw = _allocate_stats_by_weights(budget, weights)
        _add_candidate(candidates, aw=aw, vw=vw, sw=sw, lw=lw, generation_reason=profile_name)


def _allocate_stats_by_weights(stat_budget: int, weights: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    aw = 0
    vw = 0
    sw = 0
    lw = 1
    if stat_budget <= 0:
        return aw, vw, sw, lw
    weighted_order = []
    labels = ("aw", "vw", "sw", "lw")
    for label, weight in zip(labels, weights):
        weighted_order.extend([label] * max(1, weight))
    allocated = 0
    index = 0
    while allocated < stat_budget:
        stat = weighted_order[index % len(weighted_order)]
        index += 1
        if stat == "aw":
            if aw >= BUILDER_CREATURE_STAT_CAP:
                continue
            aw += 1
        elif stat == "vw":
            if vw >= BUILDER_CREATURE_STAT_CAP:
                continue
            vw += 1
        elif stat == "sw":
            if sw >= BUILDER_CREATURE_STAT_CAP:
                continue
            sw += 1
        else:
            if lw >= BUILDER_CREATURE_STAT_CAP:
                continue
            lw += 1
        allocated += 1
    return aw, vw, sw, lw


def _add_candidate(
    candidates: dict[tuple[int, int, int, int, str], BuilderCreatureCandidate],
    *,
    aw: int,
    vw: int,
    sw: int,
    lw: int,
    generation_reason: str,
) -> None:
    if not builder_creature_stats_are_valid(aw=aw, vw=vw, sw=sw, lw=lw):
        return
    stat_cost = candidate_cost(aw=aw, vw=vw, sw=sw, lw=lw)
    ability_sets = (frozenset(), frozenset({Ability.HASTE})) if stat_cost > 0 else (frozenset(),)
    for abilities in ability_sets:
        candidate = BuilderCreatureCandidate(
            aw=aw,
            vw=vw,
            sw=sw,
            lw=lw,
            cost=stat_cost,
            abilities=abilities,
            generation_reason=generation_reason,
        )
        current = candidates.get(candidate.key)
        if current is None or len(generation_reason) < len(current.generation_reason):
            candidates[candidate.key] = candidate
