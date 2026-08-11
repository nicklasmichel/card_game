from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import core.config as config
from core.models import Ability

from .cap_strategy import compute_builder_cap_context
from .combat_assignments import (
    convolve_damage_distributions,
    generate_block_assignment_tuples,
    player_damage_distribution_for_combat,
)
from .combat_eval import can_legally_be_forced_to_block, can_legally_block, estimate_builder_combat, estimate_unblocked_attack
from .search_budget import FINAL_DECISION_SEARCH_BUDGET
from .scoring import estimate_creature_board_value
from .turn_types import BuilderSearchMetadata

PLAYER_DAMAGE_WEIGHT = 2.2
ENEMY_BOARD_DAMAGE_WEIGHT = 0.5
OWN_BOARD_DAMAGE_PENALTY = 0.45
ENEMY_KILL_VALUE_WEIGHT = 1.1
OWN_DEATH_VALUE_PENALTY = 1.2
LIFESTEAL_WEIGHT = 0.8
VIGILANCE_PRESERVATION_WEIGHT = 0.18
GUARANTEED_LETHAL_BONUS = 1000.0
LETHAL_PROBABILITY_WEIGHT = 12.0
NO_ATTACK_PRESERVATION_WEIGHT = 0.16
NO_ATTACK_PRESSURE_WEIGHT = 0.24
SUICIDE_ATTACK_SCORE_PENALTY = 5.0
LOW_IMPACT_ATTACK_PENALTY = 1.35
CAP_SLOT_RELEASE_WEIGHT = 0.7
CAP_WEAK_UNIT_DEATH_RELIEF_WEIGHT = 0.9
CAP_UNBLOCKED_PRESSURE_BONUS = 0.22
FULL_ATTACK_ENUMERATION_THRESHOLD = 8
ENRAGED_TARGET_LIMIT = 2


@dataclass(frozen=True)
class BuilderAttackCandidate:
    attacker_ids: tuple[int, ...]
    enraged_targets: tuple[tuple[int, int], ...] = ()
    generation_reason: str = "generated"


@dataclass(frozen=True)
class BuilderAttackScore:
    player_damage: float
    enemy_creature_damage: float
    own_creature_damage: float
    enemy_kill_value: float
    own_death_risk: float
    lifesteal_value: float
    board_position_value: float
    vigilance_value: float
    lethal_value: float
    total: float
    lethal_probability: float = 0.0
    guaranteed_player_damage: float = 0.0
    chosen_block_assignment: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class BuilderAttackDecision:
    candidate: BuilderAttackCandidate
    score: BuilderAttackScore
    defensive_response: tuple[tuple[int, int], ...] | None
    search_metadata: BuilderSearchMetadata


def evaluate_best_builder_attack(player, combat_context, search_budget=FINAL_DECISION_SEARCH_BUDGET) -> BuilderAttackDecision:
    decision, _ = _evaluate_best_builder_attack_details(player, combat_context, search_budget=search_budget)
    return decision


def _evaluate_best_builder_attack_details(player, combat_context, *, search_budget):
    enemy = combat_context.players[1 - player.player_id]
    cap_context = compute_builder_cap_context(
        player,
        combat_context,
        creature_cap=getattr(combat_context, "BUILDER_CREATURE_CAP", 5),
        resource_budget=player.total_resources(),
    )
    candidates, attack_exact, attack_pruned = _generate_builder_attack_candidates_with_metadata(player, combat_context, search_budget=search_budget)
    scored_candidates: list[tuple[BuilderAttackCandidate, BuilderAttackScore]] = []
    generated_block_assignments = 0
    evaluated_block_assignments = 0
    block_pruned = 0
    block_exact = True
    for candidate in candidates:
        score, block_metadata = _score_builder_attack_candidate_details(
            candidate,
            player,
            enemy,
            combat_context,
            search_budget=search_budget,
            cap_context=cap_context,
        )
        scored_candidates.append((candidate, score))
        generated_block_assignments += block_metadata["generated_block_assignments"]
        evaluated_block_assignments += block_metadata["evaluated_block_assignments"]
        block_pruned += block_metadata["pruned_candidates"]
        block_exact = block_exact and block_metadata["exact_search"]
    scored_candidates.sort(key=_attack_candidate_sort_key, reverse=True)
    best_candidate, best_score = scored_candidates[0]
    metadata = BuilderSearchMetadata(
        exact_search=bool(attack_exact and block_exact),
        generated_attack_candidates=len(candidates),
        evaluated_attack_candidates=len(candidates),
        generated_block_assignments=generated_block_assignments,
        evaluated_block_assignments=evaluated_block_assignments,
        pruned_candidates=attack_pruned + block_pruned,
        search_budget_name=search_budget.mode_name,
    )
    decision = BuilderAttackDecision(
        candidate=best_candidate,
        score=best_score,
        defensive_response=best_score.chosen_block_assignment,
        search_metadata=metadata,
    )
    _debug_attack_decision(combat_context, player, scored_candidates, best_candidate, metadata)
    return decision, scored_candidates


def choose_builder_attackers(player, engine) -> list:
    decision = evaluate_best_builder_attack(player, engine, search_budget=FINAL_DECISION_SEARCH_BUDGET)
    setattr(engine.ai, "_last_builder_attack_candidate", decision.candidate)
    setattr(engine.ai, "_last_builder_attack_decision", decision)
    setattr(engine.ai, "_last_builder_enraged_targets", dict(decision.candidate.enraged_targets))
    lookup = {creature.unit_id: creature for creature in player.battlefield}
    return [lookup[attacker_id] for attacker_id in decision.candidate.attacker_ids if attacker_id in lookup]


def choose_builder_attack_candidate(player, engine):
    decision, scored_candidates = _evaluate_best_builder_attack_details(player, engine, search_budget=FINAL_DECISION_SEARCH_BUDGET)
    setattr(engine.ai, "_last_builder_attack_candidate", decision.candidate)
    setattr(engine.ai, "_last_builder_attack_decision", decision)
    setattr(engine.ai, "_last_builder_enraged_targets", dict(decision.candidate.enraged_targets))
    return decision.candidate, decision.score, scored_candidates


def generate_builder_attack_candidates(player, engine, *, search_budget=FINAL_DECISION_SEARCH_BUDGET) -> list[BuilderAttackCandidate]:
    candidates, _, _ = _generate_builder_attack_candidates_with_metadata(player, engine, search_budget=search_budget)
    return candidates


def _generate_builder_attack_candidates_with_metadata(player, engine, *, search_budget=FINAL_DECISION_SEARCH_BUDGET) -> tuple[list[BuilderAttackCandidate], bool, int]:
    available_attackers = list(engine.available_attackers(player))
    enemy_battlefield = list(engine.players[1 - player.player_id].battlefield)
    exact_upper_bound = estimate_attack_candidate_upper_bound(available_attackers, enemy_battlefield)
    if (
        len(available_attackers) <= FULL_ATTACK_ENUMERATION_THRESHOLD
        and exact_upper_bound <= search_budget.max_exact_attack_candidates
    ):
        candidates = _generate_exhaustive_attack_candidates(available_attackers, enemy_battlefield)
        return candidates, True, 0
    candidates = _generate_structured_attack_candidates(available_attackers, enemy_battlefield)
    pruned = max(0, exact_upper_bound - len(candidates))
    return candidates[: search_budget.max_heuristic_attack_candidates], False, pruned


def generate_builder_block_assignments(
    candidate: BuilderAttackCandidate,
    player,
    enemy,
    engine,
    *,
    search_budget=FINAL_DECISION_SEARCH_BUDGET,
    metadata: dict | None = None,
) -> list[tuple[tuple[int, int], ...]]:
    attackers = [engine.get_unit_by_id(attacker_id) for attacker_id in candidate.attacker_ids]
    attackers = [attacker for attacker in attackers if attacker is not None]
    blockers = list(engine.available_blockers(enemy))
    forced_map = dict(candidate.enraged_targets)
    return generate_block_assignment_tuples(
        attackers,
        blockers,
        forced_map,
        search_budget=search_budget,
        metadata=metadata,
    )


def score_builder_attack_candidate(candidate: BuilderAttackCandidate, player, engine, *, search_budget=FINAL_DECISION_SEARCH_BUDGET) -> BuilderAttackScore:
    enemy = engine.players[1 - player.player_id]
    cap_context = compute_builder_cap_context(
        player,
        engine,
        creature_cap=getattr(engine, "BUILDER_CREATURE_CAP", 5),
        resource_budget=player.total_resources(),
    )
    score, _ = _score_builder_attack_candidate_details(candidate, player, enemy, engine, search_budget=search_budget, cap_context=cap_context)
    return score


def _score_builder_attack_candidate_details(candidate: BuilderAttackCandidate, player, enemy, engine, *, search_budget, cap_context) -> tuple[BuilderAttackScore, dict]:
    if not candidate.attacker_ids:
        preservation = _score_no_attack(player, enemy, engine, cap_context)
        return (
            BuilderAttackScore(
                player_damage=0.0,
                enemy_creature_damage=0.0,
                own_creature_damage=0.0,
                enemy_kill_value=0.0,
                own_death_risk=0.0,
                lifesteal_value=0.0,
                board_position_value=preservation,
                vigilance_value=0.0,
                lethal_value=0.0,
                total=round(preservation, 4),
                chosen_block_assignment=(),
            ),
            {
                "exact_search": True,
                "generated_block_assignments": 1,
                "evaluated_block_assignments": 1,
                "pruned_candidates": 0,
            },
        )

    block_metadata: dict = {}
    assignments = generate_builder_block_assignments(
        candidate,
        player,
        enemy,
        engine,
        search_budget=search_budget,
        metadata=block_metadata,
    )
    pair_cache: dict[tuple[int, int], tuple] = {}
    scored_assignments = [
        evaluate_attack_assignment(candidate, assignment, player, enemy, engine, pair_cache=pair_cache, cap_context=cap_context)
        for assignment in assignments
    ]
    scored_assignments.sort(key=lambda score: (score.total, score.player_damage, score.enemy_kill_value, tuple(score.chosen_block_assignment)))
    return scored_assignments[0], block_metadata


def evaluate_attack_assignment(
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
    engine,
    *,
    pair_cache: dict[tuple[int, int], tuple] | None = None,
    cap_context=None,
) -> BuilderAttackScore:
    assignment_map = dict(block_assignment)
    attackers = [engine.get_unit_by_id(attacker_id) for attacker_id in candidate.attacker_ids]
    attackers = [attacker for attacker in attackers if attacker is not None]

    player_damage = 0.0
    enemy_creature_damage = 0.0
    own_creature_damage = 0.0
    enemy_kill_value = 0.0
    own_death_risk = 0.0
    effective_own_death_penalty = 0.0
    lifesteal_value = 0.0
    board_position_value = 0.0
    vigilance_value = 0.0
    slot_release_value = 0.0
    damage_distributions: list[dict[int, float]] = []

    enemy_potential_attackers = len(engine.available_attackers(enemy))
    for attacker in attackers:
        blocker_id = assignment_map.get(attacker.unit_id)
        if blocker_id is None:
            unblocked = estimate_unblocked_attack(attacker)
            player_damage += unblocked.player_damage
            lifesteal_value += unblocked.attacker_heal * LIFESTEAL_WEIGHT
            damage_distributions.append({int(unblocked.player_damage): 1.0})
            if cap_context is not None and cap_context.at_cap and attacker.unit_id == cap_context.weakest_unit_id:
                slot_release_value += min(cap_context.cap_pressure, unblocked.player_damage * CAP_UNBLOCKED_PRESSURE_BONUS)
        else:
            blocker = engine.get_unit_by_id(blocker_id)
            if blocker is None:
                continue
            pair_key = (attacker.unit_id, blocker.unit_id)
            cached = None if pair_cache is None else pair_cache.get(pair_key)
            if cached is None:
                estimate = estimate_builder_combat(attacker, blocker)
                blocker_value = estimate_creature_board_value(blocker)
                attacker_value = estimate_creature_board_value(attacker)
                damage_distribution = player_damage_distribution_for_combat(attacker, estimate)
                cached = (estimate, blocker_value, attacker_value, damage_distribution)
                if pair_cache is not None:
                    pair_cache[pair_key] = cached
            estimate, blocker_value, attacker_value, damage_distribution = cached
            enemy_creature_damage += estimate.expected_damage_to_defender
            own_creature_damage += estimate.expected_damage_to_attacker
            player_damage += estimate.expected_player_damage
            enemy_kill_value += estimate.defender_death_probability * blocker_value
            own_death_risk += estimate.attacker_death_probability * attacker_value
            effective_own_death_penalty += estimate.attacker_death_probability * attacker_value
            lifesteal_value += (estimate.expected_attacker_heal - estimate.expected_defender_heal) * LIFESTEAL_WEIGHT
            board_position_value += (
                estimate.defender_death_probability * blocker_value
                - estimate.attacker_death_probability * attacker_value
            ) * 0.12
            damage_distributions.append(damage_distribution)
            if cap_context is not None and cap_context.at_cap and attacker.unit_id == cap_context.weakest_unit_id:
                replacement_relief = estimate.attacker_death_probability * cap_context.cap_pressure
                slot_release_value += replacement_relief * CAP_SLOT_RELEASE_WEIGHT
                effective_own_death_penalty -= replacement_relief * CAP_WEAK_UNIT_DEATH_RELIEF_WEIGHT
        if attacker.has_ability(Ability.VIGILANT):
            vigilance_value += VIGILANCE_PRESERVATION_WEIGHT * enemy_potential_attackers

    effective_own_death_penalty = max(0.0, effective_own_death_penalty or own_death_risk)

    guaranteed_player_damage = sum(min(distribution.keys()) for distribution in damage_distributions) if damage_distributions else 0.0
    total_damage_distribution = convolve_damage_distributions(damage_distributions)
    lethal_probability = sum(probability for damage, probability in total_damage_distribution.items() if damage >= enemy.life)
    lethal_value = (
        GUARANTEED_LETHAL_BONUS
        if enemy.life > 0 and guaranteed_player_damage >= enemy.life
        else lethal_probability * LETHAL_PROBABILITY_WEIGHT
    )

    total = (
        player_damage * PLAYER_DAMAGE_WEIGHT
        + enemy_creature_damage * ENEMY_BOARD_DAMAGE_WEIGHT
        - own_creature_damage * OWN_BOARD_DAMAGE_PENALTY
        + enemy_kill_value * ENEMY_KILL_VALUE_WEIGHT
        - effective_own_death_penalty * OWN_DEATH_VALUE_PENALTY
        + lifesteal_value
        + board_position_value
        + vigilance_value
        + slot_release_value
        + lethal_value
    )
    if lethal_value < GUARANTEED_LETHAL_BONUS:
        if player_damage <= 0.75 and enemy_kill_value <= own_death_risk * 0.55 and own_death_risk >= 1.0:
            total -= SUICIDE_ATTACK_SCORE_PENALTY
        elif player_damage <= 0.25 and enemy_kill_value <= own_death_risk * 0.85 and own_death_risk > enemy_kill_value:
            total -= LOW_IMPACT_ATTACK_PENALTY
    return BuilderAttackScore(
        player_damage=round(player_damage, 4),
        enemy_creature_damage=round(enemy_creature_damage, 4),
        own_creature_damage=round(own_creature_damage, 4),
        enemy_kill_value=round(enemy_kill_value, 4),
        own_death_risk=round(own_death_risk, 4),
        lifesteal_value=round(lifesteal_value, 4),
        board_position_value=round(board_position_value, 4),
        vigilance_value=round(vigilance_value, 4),
        lethal_value=round(lethal_value, 4),
        total=round(total, 4),
        lethal_probability=round(lethal_probability, 4),
        guaranteed_player_damage=round(float(guaranteed_player_damage), 4),
        chosen_block_assignment=tuple(sorted(block_assignment)),
    )


def estimate_attack_candidate_upper_bound(available_attackers: list, enemy_battlefield: list) -> int:
    subset_count = 2 ** len(available_attackers)
    multiplier = 1
    for attacker in available_attackers:
        if not attacker.has_ability(Ability.ENRAGED):
            continue
        legal_targets = sum(
            1 for blocker in enemy_battlefield if can_legally_be_forced_to_block(attacker, blocker, require_ready=True)
        )
        multiplier *= max(1, legal_targets + 1)
    return subset_count * multiplier


def _generate_exhaustive_attack_candidates(available_attackers: list, enemy_battlefield: list) -> list[BuilderAttackCandidate]:
    candidates: dict[tuple, BuilderAttackCandidate] = {}
    for size in range(len(available_attackers) + 1):
        for combo in combinations(available_attackers, size):
            for candidate in _expand_enraged_targets(combo, enemy_battlefield, heuristic=False):
                candidates[(candidate.attacker_ids, candidate.enraged_targets)] = candidate
    return sorted(candidates.values(), key=lambda candidate: (len(candidate.attacker_ids), candidate.attacker_ids, candidate.enraged_targets))


def _generate_structured_attack_candidates(available_attackers: list, enemy_battlefield: list) -> list[BuilderAttackCandidate]:
    candidates: dict[tuple, BuilderAttackCandidate] = {}

    def add(group: list, reason: str) -> None:
        for candidate in _expand_enraged_targets(group, enemy_battlefield, heuristic=True):
            candidates[(candidate.attacker_ids, candidate.enraged_targets)] = BuilderAttackCandidate(
                attacker_ids=candidate.attacker_ids,
                enraged_targets=candidate.enraged_targets,
                generation_reason=reason,
            )

    add([], "none")
    add(available_attackers, "all")
    add([unit for unit in available_attackers if unit.has_ability(Ability.VIGILANT)], "vigilant")
    add([unit for unit in available_attackers if unit.has_ability(Ability.FLYING)], "flying")
    add([unit for unit in available_attackers if unit.has_ability(Ability.HASTE)], "haste")
    sorted_by_sw = sorted(available_attackers, key=lambda unit: (-unit.sw, -unit.aw, unit.unit_id))
    sorted_by_value = sorted(available_attackers, key=lambda unit: (-estimate_creature_board_value(unit), unit.unit_id))
    add(sorted_by_sw[: max(1, min(4, len(sorted_by_sw)))], "high_sw")
    add(sorted_by_value[: max(1, min(4, len(sorted_by_value)))], "high_value")
    for attacker in available_attackers:
        add([attacker], "single")
    for count in range(2, min(4, len(sorted_by_value)) + 1):
        add(sorted_by_value[:count], "top_combo")
    return sorted(candidates.values(), key=lambda candidate: (len(candidate.attacker_ids), candidate.attacker_ids, candidate.enraged_targets))


def _expand_enraged_targets(attacker_group, enemy_battlefield: list, *, heuristic: bool) -> list[BuilderAttackCandidate]:
    attackers = list(attacker_group)
    attacker_ids = tuple(attacker.unit_id for attacker in attackers)
    if not attackers:
        return [BuilderAttackCandidate(attacker_ids=(), enraged_targets=(), generation_reason="none")]
    enraged_attackers = [attacker for attacker in attackers if attacker.has_ability(Ability.ENRAGED)]
    if not enraged_attackers:
        return [BuilderAttackCandidate(attacker_ids=attacker_ids, enraged_targets=(), generation_reason="subset")]

    option_sets: list[tuple[int, list[int | None]]] = []
    for attacker in enraged_attackers:
        legal_targets = [blocker for blocker in enemy_battlefield if can_legally_be_forced_to_block(attacker, blocker, require_ready=True)]
        if heuristic and len(legal_targets) > ENRAGED_TARGET_LIMIT:
            legal_targets = _select_top_enraged_targets(attacker, attackers, legal_targets)[:ENRAGED_TARGET_LIMIT]
        option_sets.append((attacker.unit_id, [None] + [blocker.unit_id for blocker in legal_targets]))

    candidates: list[BuilderAttackCandidate] = []

    def recurse(index: int, chosen: list[tuple[int, int]], used_blockers: set[int]) -> None:
        if index >= len(option_sets):
            candidates.append(
                BuilderAttackCandidate(
                    attacker_ids=attacker_ids,
                    enraged_targets=tuple(sorted(chosen)),
                    generation_reason="subset",
                )
            )
            return
        attacker_id, options = option_sets[index]
        for blocker_id in options:
            if blocker_id is None:
                recurse(index + 1, chosen, used_blockers)
                continue
            if blocker_id in used_blockers:
                continue
            recurse(index + 1, chosen + [(attacker_id, blocker_id)], used_blockers | {blocker_id})

    recurse(0, [], set())
    return candidates


def _select_top_enraged_targets(attacker, all_attackers: list, legal_targets: list) -> list:
    scored = []
    for blocker in legal_targets:
        estimate = estimate_builder_combat(attacker, blocker)
        release_value = sum(
            other.sw for other in all_attackers if other.unit_id != attacker.unit_id and can_legally_block(other, blocker, require_ready=True)
        )
        score = (
            estimate.expected_player_damage * PLAYER_DAMAGE_WEIGHT
            + estimate.defender_death_probability * estimate_creature_board_value(blocker)
            - estimate.attacker_death_probability * estimate_creature_board_value(attacker)
            + release_value * 0.25
        )
        scored.append((score, blocker))
    scored.sort(key=lambda item: (item[0], -item[1].unit_id), reverse=True)
    return [blocker for _, blocker in scored]


def _score_no_attack(player, enemy, engine, cap_context) -> float:
    ready_creatures = list(engine.available_attackers(player))
    preservation = sum(estimate_creature_board_value(creature) for creature in ready_creatures) * NO_ATTACK_PRESERVATION_WEIGHT
    pressure_guard = len(engine.available_attackers(enemy)) * NO_ATTACK_PRESSURE_WEIGHT
    cap_drag = 0.0
    if cap_context is not None and cap_context.at_cap and cap_context.cap_pressure > 0:
        cap_drag = min(3.4, cap_context.cap_pressure * 0.36)
    return preservation + pressure_guard - cap_drag


def _attack_candidate_sort_key(scored_candidate: tuple[BuilderAttackCandidate, BuilderAttackScore]) -> tuple:
    candidate, score = scored_candidate
    return (
        score.total,
        score.guaranteed_player_damage,
        -score.own_death_risk,
        tuple(candidate.attacker_ids),
        tuple(candidate.enraged_targets),
    )


def _debug_attack_decision(engine, player, scored_candidates, best_candidate, metadata: BuilderSearchMetadata) -> None:
    if not getattr(config, "BUILDER_AI_DEBUG", 0):
        return
    available = list(engine.available_attackers(player))
    engine.log("Builder AI Attack:")
    engine.log("Available attackers: " + (", ".join(f"{creature.name}#{creature.unit_id}" for creature in available) or "-"))
    for index, (candidate, score) in enumerate(scored_candidates[:5], start=1):
        attackers = ", ".join(str(attacker_id) for attacker_id in candidate.attacker_ids) or "No attack"
        forced = ", ".join(f"{attacker_id}->{blocker_id}" for attacker_id, blocker_id in candidate.enraged_targets) or "-"
        response = ", ".join(f"{attacker_id}->{blocker_id}" for attacker_id, blocker_id in score.chosen_block_assignment) or "-"
        engine.log(
            f"{index}. Attack [{attackers}] | forced {forced} | player_damage={score.player_damage:.2f} | "
            f"enemy_kill_value={score.enemy_kill_value:.2f} | own_death_risk={score.own_death_risk:.2f} | "
            f"response {response} | total={score.total:.2f}"
        )
    engine.log(
        f"Search: exact={metadata.exact_search} attack_candidates={metadata.evaluated_attack_candidates} "
        f"block_assignments={metadata.evaluated_block_assignments} budget={metadata.search_budget_name}"
    )
    if best_candidate is None:
        engine.log("Decision: No attack")
    else:
        engine.log(f"Decision: Attack {list(best_candidate.attacker_ids)}")
