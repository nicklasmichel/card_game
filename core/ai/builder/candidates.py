from __future__ import annotations

from functools import lru_cache

from core.builder_rules import (
    BUILDER_HASTE_COST,
    BUILDER_PRIMARY_ABILITIES,
    builder_creature_ability_set,
    calculate_builder_creature_cost,
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
    return calculate_builder_creature_cost(
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
        has_haste=has_haste or ability == Ability.HASTE,
    )


def is_legal_builder_candidate(candidate: BuilderCreatureCandidate, available_resources: int) -> bool:
    if min(candidate.aw, candidate.vw, candidate.sw) < 0 or candidate.lw < 1:
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
    return candidate.cost <= available_resources


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
    for ability in BUILDER_PRIMARY_ABILITIES:
        _generate_budget_candidates(candidates, budget, ability=ability, has_haste=False)
        if budget >= BUILDER_HASTE_COST:
            _generate_budget_candidates(
                candidates,
                budget - BUILDER_HASTE_COST,
                ability=ability,
                has_haste=True,
            )
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

    if snapshot.enemy_flying_count > 0:
        flying = [candidate for candidate in candidates if candidate.has_ability(Ability.FLYING)]
        buckets.insert(0, sorted(flying, key=lambda candidate: (candidate.vw, candidate.lw, candidate.sw, candidate.key), reverse=True))
    if snapshot.enemy_potential_attacker_count > 0:
        haste_blockers = [candidate for candidate in candidates if candidate.has_haste]
        buckets.insert(0, sorted(haste_blockers, key=lambda candidate: (candidate.vw, candidate.lw, candidate.sw, candidate.key), reverse=True))

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
    ability_bonus = 0.0
    if candidate.has_haste:
        ability_bonus = candidate.sw * 0.35 + candidate.vw * 0.15
    elif candidate.has_ability(Ability.FLYING):
        ability_bonus = candidate.sw * 0.30
    elif candidate.has_ability(Ability.VIGILANCE):
        ability_bonus = candidate.sw * 0.16 + candidate.vw * 0.12
    elif candidate.has_ability(Ability.TRAMPLE):
        ability_bonus = candidate.sw * 0.22 + candidate.aw * 0.08
    return (
        candidate.sw * 1.20 + candidate.aw + candidate.vw * 0.92 + (candidate.lw - 1) * 0.78 + ability_bonus,
        min(candidate.aw, candidate.vw, candidate.sw),
        candidate.key,
    )


def _profile_fit_key(candidate: BuilderCreatureCandidate, profile: tuple[int, int, int, int]) -> tuple:
    candidate_stats = (candidate.aw, candidate.vw, candidate.sw, max(0, candidate.lw - 1))
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
    *,
    ability: Ability,
    has_haste: bool,
) -> None:
    if budget == 0:
        _add_candidate(candidates, aw=0, vw=0, sw=0, lw=1, ability=ability, has_haste=has_haste, generation_reason="zero_budget")
        return

    for aw in range(budget + 1):
        for vw in range(budget - aw + 1):
            for sw in range(budget - aw - vw + 1):
                hp_budget = budget - aw - vw - sw
                lw = 1 + hp_budget
                _add_candidate(candidates, aw=aw, vw=vw, sw=sw, lw=lw, ability=ability, has_haste=has_haste, generation_reason="exhaustive")

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
        _add_candidate(candidates, aw=aw, vw=vw, sw=sw, lw=lw, ability=ability, has_haste=has_haste, generation_reason=profile_name)


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
    for index in range(stat_budget):
        stat = weighted_order[index % len(weighted_order)]
        if stat == "aw":
            aw += 1
        elif stat == "vw":
            vw += 1
        elif stat == "sw":
            sw += 1
        else:
            lw += 1
    return aw, vw, sw, lw


def _add_candidate(
    candidates: dict[tuple[int, int, int, int, str], BuilderCreatureCandidate],
    *,
    aw: int,
    vw: int,
    sw: int,
    lw: int,
    ability: Ability,
    has_haste: bool,
    generation_reason: str,
) -> None:
    abilities = builder_creature_ability_set(ability, has_haste=has_haste)
    candidate = BuilderCreatureCandidate(
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
        cost=candidate_cost(aw=aw, vw=vw, sw=sw, lw=lw, ability=ability, has_haste=has_haste),
        abilities=abilities,
        generation_reason=generation_reason,
    )
    current = candidates.get(candidate.key)
    if current is None or len(generation_reason) < len(current.generation_reason):
        candidates[candidate.key] = candidate
