from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations

import core.config as config
from core.models import Ability

from .config import BUILDER_AI_WEIGHTS
from .debug import (
    builder_debug_enabled,
    builder_debug_include_fingerprints,
    builder_debug_top_n,
    builder_debug_verbose,
    contribution_pairs,
    emit_builder_debug_line,
    log_builder_fingerprint,
    log_builder_state,
    score_delta_keys,
    select_scored_rows,
)
from .cap_strategy import compute_builder_cap_context
from .combat_assignments import (
    convolve_damage_distributions,
    generate_block_assignment_tuples,
    player_damage_distribution_for_combat,
)
from .combat_eval import can_legally_be_forced_to_block, can_legally_block, estimate_builder_combat, estimate_unblocked_attack
from .search_budget import BuilderSearchBudget, FINAL_DECISION_SEARCH_BUDGET, TURN_LOOKAHEAD_SEARCH_BUDGET
from .scoring import estimate_creature_board_value
from .turn_projection import BuilderTurnProjection, ProjectedPlayerView, ProjectedUnitView
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
COUNTERATTACK_SEARCH_BUDGET = BuilderSearchBudget(
    max_exact_attack_candidates=24,
    max_exact_block_assignments=96,
    max_heuristic_attack_candidates=10,
    max_heuristic_block_responses=8,
    mode_name="counter",
)
LOOKAHEAD_FOLLOWUP_SHORTLIST_LIMIT = 4


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
    lost_block_value: float = 0.0
    projected_counter_damage: float = 0.0
    projected_counter_kill_value: float = 0.0
    counter_lethal_risk: float = 0.0
    lethal_probability: float = 0.0
    guaranteed_player_damage: float = 0.0
    chosen_block_assignment: tuple[tuple[int, int], ...] = ()
    debug_contributions: tuple[tuple[str, float, float, float], ...] = ()


@dataclass(frozen=True)
class BuilderAttackDecision:
    candidate: BuilderAttackCandidate
    score: BuilderAttackScore
    defensive_response: tuple[tuple[int, int], ...] | None
    search_metadata: BuilderSearchMetadata
    scored_candidates: tuple[tuple[BuilderAttackCandidate, BuilderAttackScore], ...] = ()


def evaluate_best_builder_attack(
    player,
    combat_context,
    search_budget=FINAL_DECISION_SEARCH_BUDGET,
    *,
    include_counterattack: bool = True,
    debug_output: bool = True,
) -> BuilderAttackDecision:
    decision, _ = _evaluate_best_builder_attack_details(
        player,
        combat_context,
        search_budget=search_budget,
        include_counterattack=include_counterattack,
        debug_output=debug_output,
    )
    return decision


def _evaluate_best_builder_attack_details(player, combat_context, *, search_budget, include_counterattack: bool, debug_output: bool = True):
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
    counter_cache: dict[tuple, BuilderAttackScore] | None = {} if include_counterattack else None
    for candidate in candidates:
        score, block_metadata = _score_builder_attack_candidate_details(
            candidate,
            player,
            enemy,
            combat_context,
            search_budget=search_budget,
            cap_context=cap_context,
            include_counterattack=False if include_counterattack else include_counterattack,
        )
        scored_candidates.append((candidate, score))
        generated_block_assignments += block_metadata["generated_block_assignments"]
        evaluated_block_assignments += block_metadata["evaluated_block_assignments"]
        block_pruned += block_metadata["pruned_candidates"]
        block_exact = block_exact and block_metadata["exact_search"]
    if include_counterattack and scored_candidates:
        scored_candidates.sort(key=_attack_candidate_sort_key, reverse=True)
        followup_indexes = _select_followup_shortlist_indexes(scored_candidates, search_budget)
        rescored: list[tuple[BuilderAttackCandidate, BuilderAttackScore]] = []
        for index, (candidate, score) in enumerate(scored_candidates):
            if index in followup_indexes:
                score = _apply_enemy_followup_pressure(
                    score,
                    candidate=candidate,
                    block_assignment=score.chosen_block_assignment,
                    player=player,
                    enemy=enemy,
                    search_budget=search_budget,
                    counter_cache=counter_cache,
                )
            rescored.append((candidate, score))
        scored_candidates = rescored
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
        scored_candidates=tuple(scored_candidates),
    )
    if debug_output:
        _debug_attack_decision(combat_context, player, decision)
    return decision, scored_candidates


def _select_followup_shortlist_indexes(
    scored_candidates: list[tuple[BuilderAttackCandidate, BuilderAttackScore]],
    search_budget: BuilderSearchBudget,
) -> set[int]:
    if not scored_candidates:
        return set()
    if search_budget.mode_name == TURN_LOOKAHEAD_SEARCH_BUDGET.mode_name:
        limit = min(len(scored_candidates), LOOKAHEAD_FOLLOWUP_SHORTLIST_LIMIT)
    else:
        limit = min(len(scored_candidates), max(1, search_budget.max_heuristic_attack_candidates))
    selected = set(range(limit))
    no_attack_index = next(
        (
            index
            for index, (candidate, _score) in enumerate(scored_candidates)
            if not candidate.attacker_ids
        ),
        None,
    )
    if no_attack_index is not None:
        selected.add(no_attack_index)
    return selected


def choose_builder_attackers(player, engine) -> list:
    decision = evaluate_best_builder_attack(player, engine, search_budget=FINAL_DECISION_SEARCH_BUDGET)
    setattr(engine.ai, "_last_builder_attack_candidate", decision.candidate)
    setattr(engine.ai, "_last_builder_attack_decision", decision)
    setattr(engine.ai, "_last_builder_enraged_targets", dict(decision.candidate.enraged_targets))
    lookup = {creature.unit_id: creature for creature in player.battlefield}
    return [lookup[attacker_id] for attacker_id in decision.candidate.attacker_ids if attacker_id in lookup]


def choose_builder_attack_candidate(player, engine):
    decision, scored_candidates = _evaluate_best_builder_attack_details(
        player,
        engine,
        search_budget=FINAL_DECISION_SEARCH_BUDGET,
        include_counterattack=True,
    )
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


def score_builder_attack_candidate(
    candidate: BuilderAttackCandidate,
    player,
    engine,
    *,
    search_budget=FINAL_DECISION_SEARCH_BUDGET,
    include_counterattack: bool = True,
) -> BuilderAttackScore:
    enemy = engine.players[1 - player.player_id]
    cap_context = compute_builder_cap_context(
        player,
        engine,
        creature_cap=getattr(engine, "BUILDER_CREATURE_CAP", 5),
        resource_budget=player.total_resources(),
    )
    score, _ = _score_builder_attack_candidate_details(
        candidate,
        player,
        enemy,
        engine,
        search_budget=search_budget,
        cap_context=cap_context,
        include_counterattack=include_counterattack,
    )
    return score


def _score_builder_attack_candidate_details(
    candidate: BuilderAttackCandidate,
    player,
    enemy,
    engine,
    *,
    search_budget,
    cap_context,
    include_counterattack: bool,
) -> tuple[BuilderAttackScore, dict]:
    if not candidate.attacker_ids:
        preservation = _score_no_attack(player, enemy, engine, cap_context)
        base_score = BuilderAttackScore(
            player_damage=0.0,
            enemy_creature_damage=0.0,
            own_creature_damage=0.0,
            enemy_kill_value=0.0,
            own_death_risk=0.0,
            lifesteal_value=0.0,
            board_position_value=preservation,
            vigilance_value=0.0,
            lethal_value=0.0,
            lost_block_value=0.0,
            projected_counter_damage=0.0,
            projected_counter_kill_value=0.0,
            counter_lethal_risk=0.0,
            total=round(preservation, 4),
            chosen_block_assignment=(),
            debug_contributions=(
                ("preservation", round(preservation, 4), 1.0, round(preservation, 4)),
            ),
        )
        if include_counterattack:
            base_score = _apply_enemy_followup_pressure(
                base_score,
                candidate=candidate,
                block_assignment=(),
                player=player,
                enemy=enemy,
                search_budget=search_budget,
            )
        return (
            base_score,
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
    block_value_cache: dict[int, float] = {}
    scored_assignments = [
        evaluate_attack_assignment(
            candidate,
            assignment,
            player,
            enemy,
            engine,
            pair_cache=pair_cache,
            block_value_cache=block_value_cache,
            cap_context=cap_context,
        )
        for assignment in assignments
    ]
    scored_assignments.sort(key=lambda score: (score.total, score.player_damage, score.enemy_kill_value, tuple(score.chosen_block_assignment)))
    best_response = scored_assignments[0]
    if include_counterattack and best_response.lethal_value < GUARANTEED_LETHAL_BONUS:
        best_response = _apply_enemy_followup_pressure(
            best_response,
            candidate=candidate,
            block_assignment=best_response.chosen_block_assignment,
            player=player,
            enemy=enemy,
            search_budget=search_budget,
        )
    return best_response, block_metadata


def _apply_enemy_followup_pressure(
    base_score: BuilderAttackScore,
    *,
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
    search_budget,
    counter_cache: dict[tuple, BuilderAttackScore] | None = None,
) -> BuilderAttackScore:
    if base_score.guaranteed_player_damage >= enemy.life > 0:
        return base_score
    counter_score = _estimate_candidate_counterattack(
        candidate,
        block_assignment,
        player,
        enemy,
        search_budget=search_budget,
        counter_cache=counter_cache,
    )
    adjusted_total = base_score.total
    lost_block_penalty = base_score.lost_block_value * BUILDER_AI_WEIGHTS.lost_block_value
    counter_damage_penalty = counter_score.player_damage * BUILDER_AI_WEIGHTS.expected_counter_damage
    counter_lethal_penalty = counter_score.lethal_probability * BUILDER_AI_WEIGHTS.enemy_lethal_probability
    adjusted_total -= lost_block_penalty
    adjusted_total -= counter_damage_penalty
    adjusted_total -= counter_lethal_penalty
    lethal_penalty = 0.0
    if counter_score.guaranteed_player_damage >= player.life > 0:
        lethal_penalty = BUILDER_AI_WEIGHTS.enemy_lethal_penalty
        adjusted_total -= lethal_penalty
    debug_contributions = tuple(
        current
        for current in base_score.debug_contributions
        if current[0] not in {"lost_block", "counter_damage", "counter_lethal", "enemy_lethal_penalty"}
    ) + (
        (
            "lost_block",
            round(base_score.lost_block_value, 4),
            round(-BUILDER_AI_WEIGHTS.lost_block_value, 4),
            round(-lost_block_penalty, 4),
        ),
        (
            "counter_damage",
            round(counter_score.player_damage, 4),
            round(-BUILDER_AI_WEIGHTS.expected_counter_damage, 4),
            round(-counter_damage_penalty, 4),
        ),
        (
            "counter_lethal",
            round(counter_score.lethal_probability, 4),
            round(-BUILDER_AI_WEIGHTS.enemy_lethal_probability, 4),
            round(-counter_lethal_penalty, 4),
        ),
        (
            "enemy_lethal_penalty",
            round(1.0 if lethal_penalty else 0.0, 4),
            round(-lethal_penalty, 4),
            round(-lethal_penalty, 4),
        ),
    )
    return replace(
        base_score,
        projected_counter_damage=round(counter_score.player_damage, 4),
        projected_counter_kill_value=round(counter_score.enemy_kill_value, 4),
        counter_lethal_risk=round(counter_score.lethal_probability, 4),
        total=round(adjusted_total, 4),
        debug_contributions=debug_contributions,
    )


def evaluate_attack_assignment(
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
    engine,
    *,
    pair_cache: dict[tuple[int, int], tuple] | None = None,
    block_value_cache: dict[int, float] | None = None,
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
    lost_block_value = 0.0

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
        else:
            cached_block_value = None if block_value_cache is None else block_value_cache.get(attacker.unit_id)
            if cached_block_value is None:
                cached_block_value = _estimate_block_value(attacker, enemy, engine)
                if block_value_cache is not None:
                    block_value_cache[attacker.unit_id] = cached_block_value
            lost_block_value += cached_block_value

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
    projected_counter_damage = 0.0
    projected_counter_kill_value = 0.0
    counter_lethal_risk = 0.0
    debug_contributions = (
        ("player_damage", player_damage, PLAYER_DAMAGE_WEIGHT, player_damage * PLAYER_DAMAGE_WEIGHT),
        ("enemy_creature_damage", enemy_creature_damage, ENEMY_BOARD_DAMAGE_WEIGHT, enemy_creature_damage * ENEMY_BOARD_DAMAGE_WEIGHT),
        ("own_creature_damage", own_creature_damage, -OWN_BOARD_DAMAGE_PENALTY, -own_creature_damage * OWN_BOARD_DAMAGE_PENALTY),
        ("enemy_kill_value", enemy_kill_value, ENEMY_KILL_VALUE_WEIGHT, enemy_kill_value * ENEMY_KILL_VALUE_WEIGHT),
        ("own_death_risk", effective_own_death_penalty, -OWN_DEATH_VALUE_PENALTY, -effective_own_death_penalty * OWN_DEATH_VALUE_PENALTY),
        ("lifesteal", lifesteal_value, 1.0, lifesteal_value),
        ("board_position", board_position_value, 1.0, board_position_value),
        ("vigilance", vigilance_value, 1.0, vigilance_value),
        ("slot_release", slot_release_value, 1.0, slot_release_value),
        ("lethal", lethal_value, 1.0, lethal_value),
        ("lost_block", lost_block_value, 0.0, 0.0),
        ("counter_damage", projected_counter_damage, 0.0, 0.0),
        ("counter_lethal", counter_lethal_risk, 0.0, 0.0),
    )
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
        lost_block_value=round(lost_block_value, 4),
        projected_counter_damage=round(projected_counter_damage, 4),
        projected_counter_kill_value=round(projected_counter_kill_value, 4),
        counter_lethal_risk=round(counter_lethal_risk, 4),
        total=round(total, 4),
        lethal_probability=round(lethal_probability, 4),
        guaranteed_player_damage=round(float(guaranteed_player_damage), 4),
        chosen_block_assignment=tuple(sorted(block_assignment)),
        debug_contributions=tuple((name, round(raw, 4), round(weight, 4), round(contribution, 4)) for name, raw, weight, contribution in debug_contributions),
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


def _estimate_block_value(blocker, enemy, engine) -> float:
    if not any(can_legally_block(attacker, blocker, require_ready=False) for attacker in enemy.battlefield):
        return 0.0
    role_penalty = 0.35 if blocker.vw <= 0 else 1.0
    role_penalty *= 0.55 if blocker.aw > blocker.vw + 1 else 1.0
    total = 0.0
    legal_attackers = [attacker for attacker in enemy.battlefield if can_legally_block(attacker, blocker, require_ready=False)]
    for attacker in legal_attackers:
        estimate = estimate_builder_combat(attacker, blocker)
        prevented_damage = max(0.0, attacker.sw - estimate.expected_player_damage)
        kill_value = estimate.attacker_death_probability * blocker.sw * BUILDER_AI_WEIGHTS.defensive_removal_probability
        survival_value = (1.0 - estimate.defender_death_probability) * max(0.6, blocker.current_hp * 0.18 + blocker.vw * 0.22)
        matchup_value = prevented_damage + kill_value + survival_value
        if blocker.aw == 0 and blocker.vw >= 2:
            matchup_value *= 1.0 + BUILDER_AI_WEIGHTS.role_fit * 0.22
        total += matchup_value
    average = total / max(1, len(legal_attackers))
    damage_race_bonus = min(1.5, max(0, enemy.life - 1) * 0.04) * BUILDER_AI_WEIGHTS.damage_race
    return average * role_penalty + damage_race_bonus


def _estimate_candidate_counterattack(
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
    *,
    search_budget,
    counter_cache: dict[tuple, BuilderAttackScore] | None = None,
) -> BuilderAttackScore:
    counter_projection = _build_counterattack_projection(candidate, block_assignment, player, enemy)
    if counter_cache is not None and counter_projection.state_signature in counter_cache:
        return counter_cache[counter_projection.state_signature]
    counter_player = counter_projection.players[counter_projection.player_id]
    counter_decision, _ = _evaluate_best_builder_attack_details(
        counter_player,
        counter_projection,
        search_budget=COUNTERATTACK_SEARCH_BUDGET,
        include_counterattack=False,
        debug_output=False,
    )
    if counter_cache is not None:
        counter_cache[counter_projection.state_signature] = counter_decision.score
    return counter_decision.score


def _build_counterattack_projection(
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
) -> BuilderTurnProjection:
    own_post: list[ProjectedUnitView] = []
    enemy_post: list[ProjectedUnitView] = []
    attacker_ids = set(candidate.attacker_ids)
    assignment_map = dict(block_assignment)
    attackers = {unit.unit_id: unit for unit in player.battlefield}
    blockers = {unit.unit_id: unit for unit in enemy.battlefield}
    post_hp: dict[int, int] = {}
    removed_ids: set[int] = set()

    for attacker_id, blocker_id in block_assignment:
        attacker = attackers.get(attacker_id)
        blocker = blockers.get(blocker_id)
        if attacker is None or blocker is None:
            continue
        estimate = estimate_builder_combat(attacker, blocker)
        attacker_hp = int(attacker.current_hp)
        blocker_hp = int(blocker.current_hp)
        if estimate.attacker_death_probability >= 1.0:
            removed_ids.add(attacker_id)
        else:
            attacker_hp = max(1, attacker_hp - int(round(estimate.expected_damage_to_attacker)))
            attacker_hp = min(int(attacker.lw), attacker_hp + int(round(estimate.expected_attacker_heal)))
            post_hp[attacker_id] = attacker_hp
        if estimate.defender_death_probability >= 1.0:
            removed_ids.add(blocker_id)
        else:
            blocker_hp = max(1, blocker_hp - int(round(estimate.expected_damage_to_defender)))
            blocker_hp = min(int(blocker.lw), blocker_hp + int(round(estimate.expected_defender_heal)))
            post_hp[blocker_id] = blocker_hp

    for attacker_id in attacker_ids:
        if attacker_id in assignment_map or attacker_id in removed_ids:
            continue
        attacker = attackers.get(attacker_id)
        if attacker is None:
            continue
        unblocked = estimate_unblocked_attack(attacker)
        healed_hp = min(int(attacker.lw), int(attacker.current_hp) + int(round(unblocked.attacker_heal)))
        post_hp[attacker_id] = healed_hp

    for unit in enemy.battlefield:
        if unit.unit_id in removed_ids:
            continue
        own_post.append(
            ProjectedUnitView(
                unit_id=unit.unit_id,
                name=unit.name,
                aw=unit.aw,
                vw=unit.vw,
                sw=unit.sw,
                lw=unit.lw,
                current_hp=post_hp.get(unit.unit_id, unit.current_hp),
                abilities=frozenset(unit.abilities),
                tapped=False,
                summoning_sickness=False,
                cannot_block=getattr(unit, "cannot_block", False),
                debug_label=getattr(unit, "name", ""),
            )
        )

    for unit in player.battlefield:
        if unit.unit_id in removed_ids:
            continue
        attacked = unit.unit_id in attacker_ids
        enemy_post.append(
            ProjectedUnitView(
                unit_id=unit.unit_id,
                name=unit.name,
                aw=unit.aw,
                vw=unit.vw,
                sw=unit.sw,
                lw=unit.lw,
                current_hp=post_hp.get(unit.unit_id, unit.current_hp),
                abilities=frozenset(unit.abilities),
                tapped=bool(
                    (attacked and not (unit.has_ability(Ability.VIGILANT) or unit.has_ability(Ability.VIGILANCE)))
                    or (not attacked and getattr(unit, "tapped", False))
                ),
                summoning_sickness=getattr(unit, "summoning_sick", getattr(unit, "summoning_sickness", False)),
                cannot_block=getattr(unit, "cannot_block", False),
                debug_label=getattr(unit, "name", ""),
            )
        )

    return BuilderTurnProjection(
        player_id=enemy.player_id,
        enemy_id=player.player_id,
        action_kind="projected_counterattack",
        own_life=enemy.life,
        enemy_life=player.life,
        own_total_resources=enemy.total_resources(),
        own_ready_resources=enemy.available_resources(),
        enemy_total_resources=player.total_resources(),
        enemy_ready_resources=player.available_resources(),
        own_units=tuple(own_post),
        enemy_units=tuple(enemy_post),
        available_attacker_ids=tuple(unit.unit_id for unit in own_post if unit.is_ready()),
        hypothetical_unit_id=None,
        candidate_signature=("counterattack", candidate.attacker_ids),
        state_signature=("counterattack", candidate.attacker_ids),
    )


def _attack_candidate_sort_key(scored_candidate: tuple[BuilderAttackCandidate, BuilderAttackScore]) -> tuple:
    candidate, score = scored_candidate
    return (
        score.total,
        score.guaranteed_player_damage,
        -score.own_death_risk,
        tuple(candidate.attacker_ids),
        tuple(candidate.enraged_targets),
    )


def log_builder_attack_decision(engine, player, decision: BuilderAttackDecision) -> None:
    _debug_attack_decision(engine, player, decision)


def _debug_attack_decision(engine, player, decision: BuilderAttackDecision) -> None:
    if not builder_debug_enabled():
        return
    if not hasattr(engine, "turn_number"):
        return
    scored_candidates = list(decision.scored_candidates)
    best_candidate = decision.candidate
    metadata = decision.search_metadata
    if builder_debug_verbose():
        log_builder_state(engine, player, decision="attack")
    available = list(engine.available_attackers(player))
    cap_context = compute_builder_cap_context(
        player,
        engine,
        creature_cap=getattr(engine, "BUILDER_CREATURE_CAP", 5),
        resource_budget=player.total_resources(),
    )
    mandatory = {
        ("attack", tuple(), tuple()),
        ("attack", tuple(sorted(creature.unit_id for creature in available)), tuple()),
    }
    if scored_candidates:
        mandatory.add(_candidate_row_key(scored_candidates[0][0]))
    if len(scored_candidates) > 1:
        mandatory.add(_candidate_row_key(scored_candidates[1][0]))
    displayed = select_scored_rows(scored_candidates, top_n=builder_debug_top_n(), mandatory_keys=mandatory)
    emit_builder_debug_line(
        engine,
        "AI ATTACK",
        player=player,
        decision="attack",
        pairs=(
            ("available", [creature.unit_id for creature in available]),
            ("cap_pressure", cap_context.cap_pressure),
            ("replacement_value", cap_context.replacement_value),
            ("best_replacement_value", cap_context.best_replacement_value),
            ("weakest_unit", cap_context.weakest_unit_id),
            ("search_exact", metadata.exact_search),
            ("attack_candidates", metadata.evaluated_attack_candidates),
            ("block_assignments", metadata.evaluated_block_assignments),
            ("pruned", metadata.pruned_candidates),
            ("budget", metadata.search_budget_name),
        ),
    )
    for rank, (candidate, score) in enumerate(displayed, start=1):
        held_back = [creature.unit_id for creature in available if creature.unit_id not in candidate.attacker_ids]
        blocked_ids = {attacker_id for attacker_id, _ in score.chosen_block_assignment}
        unblocked_ids = [attacker_id for attacker_id in candidate.attacker_ids if attacker_id not in blocked_ids]
        weakest_attacking = cap_context.at_cap and cap_context.weakest_unit_id in candidate.attacker_ids
        response_fights = []
        for attacker_id, blocker_id in score.chosen_block_assignment:
            attacker = engine.get_unit_by_id(attacker_id)
            blocker = engine.get_unit_by_id(blocker_id)
            if attacker is None or blocker is None:
                continue
            estimate = estimate_builder_combat(attacker, blocker)
            response_fights.append(
                f"{attacker_id}->{blocker_id}:pdmg={estimate.expected_player_damage:.2f},kill={estimate.defender_death_probability:.2f},risk={estimate.attacker_death_probability:.2f}"
            )
        emit_builder_debug_line(
            engine,
            "AI ATTACK",
            player=player,
            decision="attack",
            pairs=(
                ("rank", rank),
                ("attackers", list(candidate.attacker_ids)),
                ("held", held_back),
                ("total", score.total),
                ("player_damage", score.player_damage),
                ("guaranteed_player_damage", score.guaranteed_player_damage),
                ("lethal_probability", score.lethal_probability),
                ("own_lethal", score.lethal_value >= GUARANTEED_LETHAL_BONUS),
                ("enemy_creature_damage", score.enemy_creature_damage),
                ("enemy_kill_value", score.enemy_kill_value),
                ("own_creature_damage", score.own_creature_damage),
                ("own_death_risk", score.own_death_risk),
                ("lost_block_value", score.lost_block_value),
                ("projected_counter_damage", score.projected_counter_damage),
                ("projected_counter_kill_value", score.projected_counter_kill_value),
                ("enemy_lethal_risk", score.counter_lethal_risk),
                ("board_position_value", score.board_position_value),
                ("response_policy", "adversarial_worst_for_attacker"),
                ("best_response", list(score.chosen_block_assignment)),
                ("response_unblocked", unblocked_ids),
                ("response_total", score.total),
                ("response_fights", response_fights),
                ("slot_release_possible", weakest_attacking and cap_context.weakest_unit_id in blocked_ids),
                ("slot_release_guaranteed", False if weakest_attacking else None),
                ("slot_status_if_no_block", "occupied" if weakest_attacking and cap_context.weakest_unit_id in unblocked_ids else None),
            ),
        )
        if builder_debug_verbose():
            emit_builder_debug_line(
                engine,
                "AI ATTACK",
                player=player,
                decision="attack",
                pairs=(("rank", rank),) + contribution_pairs(score),
            )
    runner_up = scored_candidates[1] if len(scored_candidates) > 1 else None
    best_score = scored_candidates[0][1] if scored_candidates else None
    emit_builder_debug_line(
        engine,
        "AI ATTACK",
        player=player,
        decision="attack",
        pairs=(
            ("choose", [] if best_candidate is None else list(best_candidate.attacker_ids)),
            ("total", 0.0 if best_score is None else best_score.total),
            ("runner_up", "-" if runner_up is None else list(runner_up[0].attacker_ids)),
            ("runner_up_total", 0.0 if runner_up is None else runner_up[1].total),
            ("gap", 0.0 if runner_up is None or best_score is None else round(best_score.total - runner_up[1].total, 4)),
            ("delta_keys", "-" if runner_up is None or best_score is None else score_delta_keys(best_score, runner_up[1])),
        ),
    )
    if builder_debug_verbose() and builder_debug_include_fingerprints():
        from .turn_policy import build_builder_runtime_fingerprint

        before = build_builder_runtime_fingerprint(player, engine)
        after = build_builder_runtime_fingerprint(player, engine)
        log_builder_fingerprint(engine, player, decision="attack", before=before, after=after)


def _candidate_row_key(candidate: BuilderAttackCandidate) -> tuple:
    return ("attack", tuple(candidate.attacker_ids), tuple(candidate.enraged_targets))
