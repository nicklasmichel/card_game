from __future__ import annotations

from .types import BuilderCreatureCandidate, BuilderStrategicSnapshot


def candidate_cost(*, aw: int, vw: int, sw: int, lw: int, abilities_count: int = 0) -> int:
    return aw + vw + sw + max(0, lw - 1)


def is_legal_builder_candidate(candidate: BuilderCreatureCandidate, available_resources: int) -> bool:
    if min(candidate.aw, candidate.vw, candidate.sw) < 0 or candidate.lw < 1:
        return False
    if candidate.abilities:
        return False
    expected_cost = candidate_cost(aw=candidate.aw, vw=candidate.vw, sw=candidate.sw, lw=candidate.lw)
    if candidate.cost != expected_cost:
        return False
    return candidate.cost <= available_resources


def generate_builder_creature_candidates(
    snapshot: BuilderStrategicSnapshot,
    available_resources: int,
) -> list[BuilderCreatureCandidate]:
    if available_resources < 0:
        return []
    candidates: dict[tuple[int, int, int, int], BuilderCreatureCandidate] = {}
    budgets = _candidate_budgets(snapshot, available_resources)
    for budget in budgets:
        _generate_budget_candidates(candidates, budget)
    return sorted(candidates.values(), key=lambda candidate: (candidate.cost, candidate.signature, candidate.generation_reason))


def builder_candidate_budgets(snapshot: BuilderStrategicSnapshot, available_resources: int) -> tuple[int, ...]:
    return _candidate_budgets(snapshot, available_resources)


def _candidate_budgets(snapshot: BuilderStrategicSnapshot, available_resources: int) -> tuple[int, ...]:
    if available_resources <= 4:
        return tuple(range(0, available_resources + 1))
    budgets = {
        available_resources,
        max(0, available_resources - 1),
        max(0, available_resources - 2),
        max(0, available_resources - 3),
    }
    if snapshot.enemy_has_board and available_resources >= 2:
        budgets.add(max(0, available_resources - 4))
    return tuple(sorted(budgets))


def _generate_budget_candidates(
    candidates: dict[tuple[int, int, int, int], BuilderCreatureCandidate],
    budget: int,
) -> None:
    if budget == 0:
        _add_candidate(candidates, aw=0, vw=0, sw=0, lw=1, generation_reason="zero_budget")
        return

    for aw in range(budget + 1):
        for vw in range(budget - aw + 1):
            for sw in range(budget - aw - vw + 1):
                hp_budget = budget - aw - vw - sw
                lw = 1 + hp_budget
                _add_candidate(candidates, aw=aw, vw=vw, sw=sw, lw=lw, generation_reason="exhaustive")

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
    candidates: dict[tuple[int, int, int, int], BuilderCreatureCandidate],
    *,
    aw: int,
    vw: int,
    sw: int,
    lw: int,
    generation_reason: str,
) -> None:
    candidate = BuilderCreatureCandidate(
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
        cost=candidate_cost(aw=aw, vw=vw, sw=sw, lw=lw),
        abilities=frozenset(),
        generation_reason=generation_reason,
    )
    current = candidates.get(candidate.signature)
    if current is None or len(generation_reason) < len(current.generation_reason):
        candidates[candidate.signature] = candidate
