from __future__ import annotations

from itertools import combinations

from engine.builder import BUILDER_ABILITY_OPTIONS

from .types import BuilderCreatureCandidate, BuilderStrategicSnapshot


def candidate_cost(*, aw: int, vw: int, sw: int, lw: int, abilities_count: int) -> int:
    return aw + vw + sw + max(0, lw - 1) + abilities_count


def is_legal_builder_candidate(candidate: BuilderCreatureCandidate, available_resources: int) -> bool:
    if min(candidate.aw, candidate.vw, candidate.sw) < 0 or candidate.lw < 1:
        return False
    if len(candidate.abilities) != len(set(candidate.abilities)):
        return False
    expected_cost = candidate_cost(
        aw=candidate.aw,
        vw=candidate.vw,
        sw=candidate.sw,
        lw=candidate.lw,
        abilities_count=len(candidate.abilities),
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
    candidates: dict[tuple[int, int, int, int, tuple[str, ...]], BuilderCreatureCandidate] = {}
    if available_resources <= 4:
        _generate_exhaustive_candidates(candidates, available_resources)
    else:
        _generate_structured_candidates(candidates, snapshot, available_resources)
    return sorted(
        candidates.values(),
        key=lambda candidate: (candidate.cost, candidate.signature, candidate.generation_reason),
    )


def _generate_exhaustive_candidates(
    candidates: dict[tuple[int, int, int, int, tuple[str, ...]], BuilderCreatureCandidate],
    available_resources: int,
) -> None:
    ability_subsets = _ability_subsets_for_budget(available_resources)
    for abilities in ability_subsets:
        ability_cost = len(abilities)
        remaining = available_resources - ability_cost
        for aw in range(remaining + 1):
            for vw in range(remaining - aw + 1):
                for sw in range(remaining - aw - vw + 1):
                    max_bonus_lw = remaining - aw - vw - sw
                    for bought_hp in range(max_bonus_lw + 1):
                        lw = 1 + bought_hp
                        _add_candidate(
                            candidates,
                            aw=aw,
                            vw=vw,
                            sw=sw,
                            lw=lw,
                            abilities=abilities,
                            generation_reason="exhaustive",
                        )


def _generate_structured_candidates(
    candidates: dict[tuple[int, int, int, int, tuple[str, ...]], BuilderCreatureCandidate],
    snapshot: BuilderStrategicSnapshot,
    available_resources: int,
) -> None:
    budgets = sorted({budget for budget in {available_resources, available_resources - 1, available_resources - 2, max(1, available_resources // 2)} if budget >= 0})
    ability_packages = _structured_ability_packages(snapshot, available_resources)
    family_patterns = (
        ("aw_heavy", (3, 1, 1, 1)),
        ("vw_heavy", (1, 3, 1, 1)),
        ("sw_heavy", (1, 1, 3, 1)),
        ("lw_heavy", (1, 1, 1, 3)),
        ("aw_sw", (3, 1, 3, 1)),
        ("aw_lw", (3, 1, 1, 3)),
        ("vw_lw", (1, 3, 1, 3)),
        ("sw_lw", (1, 1, 3, 3)),
        ("balanced", (2, 2, 2, 2)),
    )

    for budget in budgets:
        _add_candidate(candidates, aw=0, vw=0, sw=0, lw=1, abilities=frozenset(), generation_reason="zero_seed")
        for package_name, abilities in ability_packages:
            if len(abilities) > budget:
                continue
            stat_budget = budget - len(abilities)
            for family_name, weights in family_patterns:
                aw, vw, sw, lw = _allocate_stats_by_weights(stat_budget, weights)
                _add_candidate(
                    candidates,
                    aw=aw,
                    vw=vw,
                    sw=sw,
                    lw=lw,
                    abilities=abilities,
                    generation_reason=f"{family_name}:{package_name}",
                )


def _structured_ability_packages(
    snapshot: BuilderStrategicSnapshot,
    available_resources: int,
) -> list[tuple[str, frozenset]]:
    packages = [
        ("none", frozenset()),
        ("haste", frozenset({BUILDER_ABILITY_OPTIONS[0]})),
        ("flying", frozenset({BUILDER_ABILITY_OPTIONS[1]})),
        ("enraged", frozenset({BUILDER_ABILITY_OPTIONS[2]})),
        ("trample", frozenset({BUILDER_ABILITY_OPTIONS[3]})),
        ("vigilant", frozenset({BUILDER_ABILITY_OPTIONS[4]})),
        ("life_steal", frozenset({BUILDER_ABILITY_OPTIONS[5]})),
        ("haste_trample", frozenset({BUILDER_ABILITY_OPTIONS[0], BUILDER_ABILITY_OPTIONS[3]})),
        ("haste_flying", frozenset({BUILDER_ABILITY_OPTIONS[0], BUILDER_ABILITY_OPTIONS[1]})),
        ("flying_enraged", frozenset({BUILDER_ABILITY_OPTIONS[1], BUILDER_ABILITY_OPTIONS[2]})),
        ("trample_life_steal", frozenset({BUILDER_ABILITY_OPTIONS[3], BUILDER_ABILITY_OPTIONS[5]})),
        ("vigilant_life_steal", frozenset({BUILDER_ABILITY_OPTIONS[4], BUILDER_ABILITY_OPTIONS[5]})),
    ]
    if snapshot.enemy_flying_count == 0:
        packages.append(("flying_pressure", frozenset({BUILDER_ABILITY_OPTIONS[1], BUILDER_ABILITY_OPTIONS[0]})))
    if snapshot.enemy_has_board:
        packages.append(("board_break", frozenset({BUILDER_ABILITY_OPTIONS[2], BUILDER_ABILITY_OPTIONS[3]})))
    if available_resources >= 6:
        packages.append(("triple_aggression", frozenset({BUILDER_ABILITY_OPTIONS[0], BUILDER_ABILITY_OPTIONS[1], BUILDER_ABILITY_OPTIONS[3]})))
        packages.append(("sticky_duelist", frozenset({BUILDER_ABILITY_OPTIONS[2], BUILDER_ABILITY_OPTIONS[4], BUILDER_ABILITY_OPTIONS[5]})))
    return packages


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


def _ability_subsets_for_budget(available_resources: int) -> list[frozenset]:
    subsets = [frozenset()]
    for size in range(1, min(len(BUILDER_ABILITY_OPTIONS), available_resources) + 1):
        subsets.extend(frozenset(combo) for combo in combinations(BUILDER_ABILITY_OPTIONS, size))
    return subsets


def _add_candidate(
    candidates: dict[tuple[int, int, int, int, tuple[str, ...]], BuilderCreatureCandidate],
    *,
    aw: int,
    vw: int,
    sw: int,
    lw: int,
    abilities: frozenset,
    generation_reason: str,
) -> None:
    candidate = BuilderCreatureCandidate(
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
        abilities=frozenset(abilities),
        cost=candidate_cost(aw=aw, vw=vw, sw=sw, lw=lw, abilities_count=len(abilities)),
        generation_reason=generation_reason,
    )
    current = candidates.get(candidate.signature)
    if current is None or len(generation_reason) < len(current.generation_reason):
        candidates[candidate.signature] = candidate
