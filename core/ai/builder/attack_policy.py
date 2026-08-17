from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations

from core.config import COMBAT_DIE_SIDES
from core.builder_rules import BUILDER_CREATURE_CAP, BUILDER_MAX_RESOURCES
from core.models import Ability

from .config import BUILDER_AI_WEIGHTS
from .debug import (
    builder_debug_enabled,
    builder_debug_include_fingerprints,
    builder_debug_precision,
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
from .candidates import generate_builder_creature_candidates, is_legal_builder_candidate, select_builder_creature_search_frontier
from .combat_assignments import (
    convolve_damage_distributions,
    estimate_block_assignment_upper_bound,
    generate_block_assignment_tuples,
    player_damage_distribution_for_combat,
)
from .combat_eval import (
    can_legally_be_forced_to_block,
    can_legally_block,
    estimate_builder_combat,
    estimate_unblocked_attack,
    project_builder_combat_outcome,
)
from .snapshot import build_builder_snapshot
from .search_budget import BuilderSearchBudget, FINAL_DECISION_SEARCH_BUDGET, TURN_LOOKAHEAD_SEARCH_BUDGET
from .search_control import builder_search_should_stop, count_builder_search_work, store_bounded_cache_entry
from .scoring import estimate_creature_board_value, score_builder_creature_candidate
from .turn_projection import (
    BuilderTurnProjection,
    ProjectedUnitView,
    normalize_builder_abilities,
    project_attack_to_next_turn,
    project_creature_action,
    project_pass_action,
    project_resource_action,
)
from .turn_types import BuilderSearchMetadata, BuilderTurnActionCandidate

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
# One turn of discount from the immediate player-damage weight (2.2).
NEXT_OWN_ATTACK_DAMAGE_WEIGHT = 1.1
NEXT_OWN_ATTACK_LETHAL_BONUS = 24.0
STALL_GRACE_TURNS = 6
STALL_RAMP_TURNS = 10
STALL_EXTENDED_RAMP_TURNS = 20
STALL_MAX_PRESSURE = 7.0
STALL_MIN_BOARD_SIZE = 4
STALL_NO_ATTACK_MAX_PENALTY = 3.6
STALL_ATTACK_MAX_BONUS = 20.0
STALL_COUNTER_EXPOSURE_PENALTY = 0.55
STALL_EXTENDED_SAFE_PROGRESS_BONUS = 0.35
FULL_ATTACK_ENUMERATION_THRESHOLD = 8
ENRAGED_TARGET_LIMIT = 2
COUNTERATTACK_SEARCH_BUDGET = BuilderSearchBudget(
    max_exact_attack_candidates=24,
    max_exact_block_assignments=96,
    # This is a nested opponent reply, often evaluated dozens of times per
    # root choice.  The structured ordering guarantees no-attack, all-out and
    # the strongest pressure groups before narrower variants.
    max_heuristic_attack_candidates=6,
    max_heuristic_block_responses=4,
    mode_name="counter",
)
LOOKAHEAD_FOLLOWUP_SHORTLIST_LIMIT = 1
FINAL_FOLLOWUP_SHORTLIST_LIMIT = 1
COUNTER_MAIN_ACTION_BUILD_LIMIT = 4
COUNTER_CANDIDATE_SCORING_LIMIT = 8
LOOKAHEAD_COUNTER_BEAM_WIDTH = 3
ADVERSARIAL_NO_BLOCK_BEAM_WIDTH = 3
ADVERSARIAL_BLOCK_RESPONSE_BEAM_WIDTH = 3
PRUNED_LOOKAHEAD_SCORE = -1_000_000.0
HEURISTIC_LOST_BLOCK_CONFIDENCE = 0.5
RESIDUAL_BLOCK_COVERAGE_CONFIDENCE = 0.15
_COUNTER_MAIN_ACTION_CACHE: dict[tuple, tuple[tuple[int, str, object], ...]] = {}


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
    counter_search_exact: bool = True
    counter_fallback_used: bool = False
    counter_fallback_reason: str = ""
    projected_counter_main_action: str = "pass"
    projected_counter_main_stats: str = "-"
    projected_counter_attackers: tuple[int, ...] = ()
    projected_counter_legal_blockers: tuple[tuple[int, tuple[int, ...]], ...] = ()
    projected_next_attack_damage: float = 0.0
    projected_next_attack_lethal: bool = False
    projected_next_attackers: tuple[int, ...] = ()
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


@dataclass(frozen=True)
class BuilderCounterResult:
    score: BuilderAttackScore
    search_exact: bool
    fallback_used: bool
    fallback_reason: str
    main_action_kind: str
    main_action_stats: str = "-"
    attackers: tuple[int, ...] = ()
    legal_blockers: tuple[tuple[int, tuple[int, ...]], ...] = ()
    next_main_value: float = 0.0
    next_main_action: str = "pass"
    next_main_stats: str = "-"
    opponent_followup_damage: float = 0.0
    opponent_followup_lethal: bool = False
    opponent_followup_attackers: tuple[int, ...] = ()


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
    response_beams: dict[BuilderAttackCandidate, tuple[BuilderAttackScore, ...]] = {}
    counter_cache: dict[tuple, BuilderCounterResult] | None = {} if include_counterattack else None
    attack_evaluation_truncated = False
    for candidate in candidates:
        if scored_candidates and builder_search_should_stop():
            attack_evaluation_truncated = True
            break
        count_builder_search_work("attack_candidates_scored")
        score, block_metadata = _score_builder_attack_candidate_details(
            candidate,
            player,
            enemy,
            combat_context,
            search_budget=search_budget,
            cap_context=cap_context,
            include_counterattack=False if include_counterattack else include_counterattack,
        )
        if block_metadata.get("deadline_truncated") and candidate.attacker_ids:
            attack_evaluation_truncated = True
            break
        scored_candidates.append((candidate, score))
        response_beams[candidate] = tuple(block_metadata.get("response_beam", (score,)))
        generated_block_assignments += block_metadata["generated_block_assignments"]
        evaluated_block_assignments += block_metadata["evaluated_block_assignments"]
        block_pruned += block_metadata["pruned_candidates"]
        block_exact = block_exact and block_metadata["exact_search"]
    scored_candidates.sort(key=_attack_candidate_sort_key, reverse=True)
    if scored_candidates and scored_candidates[0][1].guaranteed_player_damage >= enemy.life > 0:
        best_candidate, best_score = scored_candidates[0]
        metadata = BuilderSearchMetadata(
            exact_search=bool(attack_exact and block_exact and not attack_evaluation_truncated),
            generated_attack_candidates=len(candidates),
            evaluated_attack_candidates=len(scored_candidates),
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
    if include_counterattack and scored_candidates:
        followup_indexes = _select_followup_shortlist_indexes(scored_candidates, search_budget)
        no_attack_index = next(
            (
                index
                for index, (candidate, _score) in enumerate(scored_candidates)
                if not candidate.attacker_ids
            ),
            None,
        )
        baseline_counter: BuilderCounterResult | None = None
        if no_attack_index is not None:
            no_attack_candidate, no_attack_score = scored_candidates[no_attack_index]
            no_attack_score = _apply_enemy_followup_pressure(
                no_attack_score,
                candidate=no_attack_candidate,
                block_assignment=no_attack_score.chosen_block_assignment,
                player=player,
                enemy=enemy,
                combat_die_sides=int(getattr(combat_context, "combat_die_sides", COMBAT_DIE_SIDES)),
                search_budget=search_budget,
                counter_cache=counter_cache,
                full_search=True,
                baseline_counter=None,
                cap_context=cap_context,
            )
            scored_candidates[no_attack_index] = (no_attack_candidate, no_attack_score)
            baseline_counter = BuilderCounterResult(
                score=no_attack_score,
                search_exact=no_attack_score.counter_search_exact,
                fallback_used=no_attack_score.counter_fallback_used,
                fallback_reason=no_attack_score.counter_fallback_reason,
                main_action_kind=no_attack_score.projected_counter_main_action,
                main_action_stats=no_attack_score.projected_counter_main_stats,
            )
        rescored: list[tuple[BuilderAttackCandidate, BuilderAttackScore]] = []
        detailed_followup_indexes = set(range(len(scored_candidates)))
        if search_budget.mode_name == TURN_LOOKAHEAD_SEARCH_BUDGET.mode_name:
            detailed_followup_indexes = set(range(min(LOOKAHEAD_COUNTER_BEAM_WIDTH, len(scored_candidates))))
            all_attack_index = max(
                range(len(scored_candidates)),
                key=lambda current: len(scored_candidates[current][0].attacker_ids),
                default=0,
            )
            detailed_followup_indexes.add(all_attack_index)
            if no_attack_index is not None:
                detailed_followup_indexes.add(no_attack_index)
        for index, (candidate, score) in enumerate(scored_candidates):
            if no_attack_index is not None and index == no_attack_index:
                rescored.append((candidate, score))
                continue
            if index not in detailed_followup_indexes:
                rescored.append(
                    (
                        candidate,
                        replace(
                            score,
                            total=PRUNED_LOOKAHEAD_SCORE,
                            counter_fallback_used=True,
                            counter_fallback_reason="lookahead_beam_pruned",
                        ),
                    )
                )
                continue
            full_followup_search = index in followup_indexes
            response_options = (score,)
            if index < ADVERSARIAL_NO_BLOCK_BEAM_WIDTH:
                response_options = response_beams.get(candidate, response_options)
                if not candidate.enraged_targets and not any(
                    not response.chosen_block_assignment for response in response_options
                ):
                    # Declining a trade can preserve the defender's next attack,
                    # so no-block must remain a candidate even when its immediate
                    # combat score was outside the static response beam.
                    response_options += (
                        evaluate_attack_assignment(
                            candidate,
                            (),
                            player,
                            enemy,
                            combat_context,
                            cap_context=cap_context,
                        ),
                    )

            adversarial_scores: list[BuilderAttackScore] = []
            for response in response_options:
                if adversarial_scores and builder_search_should_stop():
                    break
                count_builder_search_work("adversarial_responses_scored")
                adversarial_scores.append(
                    _apply_enemy_followup_pressure(
                        response,
                        candidate=candidate,
                        block_assignment=response.chosen_block_assignment,
                        player=player,
                        enemy=enemy,
                        combat_die_sides=int(getattr(combat_context, "combat_die_sides", COMBAT_DIE_SIDES)),
                        search_budget=search_budget,
                        counter_cache=counter_cache,
                        full_search=full_followup_search,
                        baseline_counter=baseline_counter,
                        cap_context=cap_context,
                    )
                )
            score = min(adversarial_scores, key=_adversarial_block_response_sort_key)
            rescored.append((candidate, score))
        scored_candidates = rescored
    scored_candidates = _apply_builder_stall_pressure(
        scored_candidates,
        player=player,
        enemy=enemy,
        engine=combat_context,
        cap_context=cap_context,
    )
    scored_candidates.sort(key=_attack_candidate_sort_key, reverse=True)
    best_candidate, best_score = scored_candidates[0]
    metadata = BuilderSearchMetadata(
        exact_search=bool(attack_exact and block_exact and not attack_evaluation_truncated),
        generated_attack_candidates=len(candidates),
        evaluated_attack_candidates=len(scored_candidates),
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
        limit = min(len(scored_candidates), FINAL_FOLLOWUP_SHORTLIST_LIMIT)
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


def _adversarial_block_response_sort_key(score: BuilderAttackScore) -> tuple:
    return (
        score.total,
        score.player_damage,
        score.enemy_kill_value,
        tuple(score.chosen_block_assignment),
    )


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
    ready_blockers = list(engine.available_blockers(engine.players[1 - player.player_id]))
    exact_upper_bound = estimate_attack_candidate_upper_bound(available_attackers, enemy_battlefield)
    exact_cap_threshold = max(search_budget.max_exact_attack_candidates, 2 ** BUILDER_CREATURE_CAP)
    # A five-creature board has only 32 attack subsets, but each subset can
    # fan out into hundreds of blocking assignments.  Enumerating all subsets
    # in that state repeatedly consumed the complete turn deadline and, worse,
    # stopped before strategically important candidates such as "attack all"
    # were evaluated.  Switch to the structured set whenever the widest combat
    # already requires heuristic block search.  That set deliberately contains
    # no attack, all attackers, singles, pressure groups and value groups.
    widest_block_upper_bound = estimate_block_assignment_upper_bound(
        len(available_attackers),
        len(ready_blockers),
    )
    if (
        len(available_attackers) <= FULL_ATTACK_ENUMERATION_THRESHOLD
        and exact_upper_bound <= exact_cap_threshold
        and widest_block_upper_bound <= search_budget.max_exact_block_assignments
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
    if include_counterattack and candidate.attacker_ids:
        baseline_counter = _estimate_candidate_counterattack(
            BuilderAttackCandidate(attacker_ids=()),
            (),
            player,
            enemy,
            combat_die_sides=int(getattr(engine, "combat_die_sides", COMBAT_DIE_SIDES)),
            search_budget=search_budget,
            counter_cache=None,
            full_search=True,
            evaluate_next_main=False,
        )
        concrete_lost_block_value = max(0.0, score.projected_counter_damage - baseline_counter.score.player_damage)
        effective_lost_block_value = max(
            concrete_lost_block_value,
            score.lost_block_value * RESIDUAL_BLOCK_COVERAGE_CONFIDENCE,
            _estimate_mandatory_coverage_loss(candidate, player, enemy),
        )
        lost_block_delta = effective_lost_block_value - score.lost_block_value
        if abs(lost_block_delta) > 0.0001:
            score = replace(
                score,
                lost_block_value=round(effective_lost_block_value, 4),
                total=round(score.total - lost_block_delta * BUILDER_AI_WEIGHTS.lost_block_value, 4),
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
                combat_die_sides=int(getattr(engine, "combat_die_sides", COMBAT_DIE_SIDES)),
                search_budget=search_budget,
                full_search=True,
                baseline_counter=None,
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
    scored_assignments = []
    for assignment in assignments:
        if scored_assignments and builder_search_should_stop():
            block_metadata["deadline_truncated"] = True
            block_metadata["exact_search"] = False
            block_metadata["pruned_candidates"] = block_metadata.get("pruned_candidates", 0) + max(
                0,
                len(assignments) - len(scored_assignments),
            )
            break
        count_builder_search_work("block_responses_scored")
        scored_assignments.append(evaluate_attack_assignment(
            candidate,
            assignment,
            player,
            enemy,
            engine,
            pair_cache=pair_cache,
            block_value_cache=block_value_cache,
            cap_context=cap_context,
        ))
    if include_counterattack:
        counter_cache: dict[tuple, BuilderCounterResult] = {}
        rescored_assignments = []
        for current in scored_assignments:
            if rescored_assignments and builder_search_should_stop():
                break
            if current.lethal_value < GUARANTEED_LETHAL_BONUS:
                current = _apply_enemy_followup_pressure(
                    current,
                    candidate=candidate,
                    block_assignment=current.chosen_block_assignment,
                    player=player,
                    enemy=enemy,
                    combat_die_sides=int(getattr(engine, "combat_die_sides", COMBAT_DIE_SIDES)),
                    search_budget=search_budget,
                    counter_cache=counter_cache,
                    full_search=True,
                    baseline_counter=None,
                    cap_context=cap_context,
                )
            rescored_assignments.append(current)
        scored_assignments = rescored_assignments
    scored_assignments.sort(key=lambda score: (score.total, score.player_damage, score.enemy_kill_value, tuple(score.chosen_block_assignment)))
    block_metadata["response_beam"] = tuple(scored_assignments[:ADVERSARIAL_BLOCK_RESPONSE_BEAM_WIDTH])
    best_response = scored_assignments[0]
    return best_response, block_metadata


def _apply_enemy_followup_pressure(
    base_score: BuilderAttackScore,
    *,
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
    combat_die_sides: int,
    search_budget,
    counter_cache: dict[tuple, BuilderCounterResult] | None = None,
    full_search: bool,
    baseline_counter: BuilderCounterResult | None,
    cap_context=None,
) -> BuilderAttackScore:
    if base_score.guaranteed_player_damage >= enemy.life > 0:
        return base_score
    # Cap pressure and replacement relief are already priced into the combat
    # assignment. Projecting another main-action reward here double-counts a
    # freed slot and can make a zero-impact suicide look overwhelmingly good.
    counter_result = _estimate_candidate_counterattack(
        candidate,
        block_assignment,
        player,
        enemy,
        combat_die_sides=combat_die_sides,
        search_budget=search_budget,
        counter_cache=counter_cache,
        full_search=full_search,
        evaluate_next_main=False,
    )
    counter_score = counter_result.score
    adjusted_total = base_score.total
    concrete_lost_block_value = 0.0
    if baseline_counter is not None and candidate.attacker_ids:
        baseline_damage = baseline_counter.score.projected_counter_damage
        concrete_lost_block_value = max(0.0, counter_score.player_damage - baseline_damage)
        if counter_score.guaranteed_player_damage >= player.life > 0 and baseline_counter.score.guaranteed_player_damage < player.life:
            concrete_lost_block_value += max(0.0, player.life - baseline_damage)
    # The assignment evaluator already estimates the defensive value lost when
    # a non-vigilant creature attacks.  Counter search can refine that value,
    # but a tied/fallback projection must not erase it (as happened when a
    # required flying blocker attacked in turn 18 of the reference game).
    heuristic_confidence = (
        RESIDUAL_BLOCK_COVERAGE_CONFIDENCE
        if baseline_counter is not None
        else HEURISTIC_LOST_BLOCK_CONFIDENCE
    )
    heuristic_lost_block_value = base_score.lost_block_value * heuristic_confidence
    heuristic_lost_block_value = max(
        heuristic_lost_block_value,
        _estimate_mandatory_coverage_loss(candidate, player, enemy),
    )
    effective_lost_block_value = max(heuristic_lost_block_value, concrete_lost_block_value)
    lost_block_penalty = effective_lost_block_value * BUILDER_AI_WEIGHTS.lost_block_value
    counter_damage_penalty = counter_score.player_damage * BUILDER_AI_WEIGHTS.expected_counter_damage
    counter_lethal_penalty = counter_score.lethal_probability * BUILDER_AI_WEIGHTS.enemy_lethal_probability
    next_attack_damage_bonus = counter_result.opponent_followup_damage * NEXT_OWN_ATTACK_DAMAGE_WEIGHT
    next_attack_lethal_bonus = NEXT_OWN_ATTACK_LETHAL_BONUS if counter_result.opponent_followup_lethal else 0.0
    next_attack_bonus = next_attack_damage_bonus + next_attack_lethal_bonus
    adjusted_total -= lost_block_penalty
    adjusted_total -= counter_damage_penalty
    adjusted_total -= counter_lethal_penalty
    adjusted_total += next_attack_bonus
    lethal_penalty = 0.0
    if counter_score.guaranteed_player_damage >= player.life > 0:
        lethal_penalty = BUILDER_AI_WEIGHTS.enemy_lethal_penalty
        adjusted_total -= lethal_penalty
    debug_contributions = tuple(
        current
        for current in base_score.debug_contributions
        if current[0] not in {
            "lost_block",
            "counter_damage",
            "counter_lethal",
            "enemy_lethal_penalty",
            "next_attack",
            "next_attack_lethal",
        }
    ) + (
        (
            "lost_block",
            round(effective_lost_block_value, 4),
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
        (
            "next_attack",
            round(counter_result.opponent_followup_damage, 4),
            round(NEXT_OWN_ATTACK_DAMAGE_WEIGHT, 4),
            round(next_attack_damage_bonus, 4),
        ),
        (
            "next_attack_lethal",
            round(1.0 if counter_result.opponent_followup_lethal else 0.0, 4),
            round(NEXT_OWN_ATTACK_LETHAL_BONUS, 4),
            round(next_attack_lethal_bonus, 4),
        ),
    )
    return replace(
        base_score,
        lost_block_value=round(effective_lost_block_value, 4),
        projected_counter_damage=round(counter_score.player_damage, 4),
        projected_counter_kill_value=round(counter_score.enemy_kill_value, 4),
        counter_lethal_risk=round(counter_score.lethal_probability, 4),
        counter_search_exact=counter_result.search_exact,
        counter_fallback_used=counter_result.fallback_used,
        counter_fallback_reason=counter_result.fallback_reason,
        projected_counter_main_action=counter_result.main_action_kind,
        projected_counter_main_stats=counter_result.main_action_stats,
        projected_counter_attackers=counter_result.attackers,
        projected_counter_legal_blockers=counter_result.legal_blockers,
        projected_next_attack_damage=round(counter_result.opponent_followup_damage, 4),
        projected_next_attack_lethal=counter_result.opponent_followup_lethal,
        projected_next_attackers=counter_result.opponent_followup_attackers,
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
    no_attacker_death_probability = 1.0
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
            no_attacker_death_probability *= 1.0 - estimate.attacker_death_probability
            lifesteal_value += (estimate.expected_attacker_heal - estimate.expected_defender_heal) * LIFESTEAL_WEIGHT
            board_position_value += (
                estimate.defender_death_probability * blocker_value
                - estimate.attacker_death_probability * attacker_value
            ) * 0.12
            damage_distributions.append(damage_distribution)
        if attacker.has_ability(Ability.VIGILANT):
            vigilance_value += VIGILANCE_PRESERVATION_WEIGHT * enemy_potential_attackers
        else:
            cached_block_value = None if block_value_cache is None else block_value_cache.get(attacker.unit_id)
            if cached_block_value is None:
                cached_block_value = _estimate_block_value(attacker, enemy, engine)
                if block_value_cache is not None:
                    block_value_cache[attacker.unit_id] = cached_block_value
            lost_block_value += cached_block_value

    if cap_context is not None and cap_context.at_cap:
        probability_any_attacker_dies = 1.0 - no_attacker_death_probability
        slot_release_value = probability_any_attacker_dies * cap_context.cap_pressure * CAP_SLOT_RELEASE_WEIGHT

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
    all_attacker_ids = tuple(unit.unit_id for unit in available_attackers)
    damage_by_id = {unit.unit_id: unit.sw for unit in available_attackers}

    def priority(candidate: BuilderAttackCandidate) -> tuple:
        if not candidate.attacker_ids:
            return (0, 0, tuple(), candidate.enraged_targets)
        if candidate.attacker_ids == all_attacker_ids:
            return (1, 0, candidate.attacker_ids, candidate.enraged_targets)
        pressure = sum(damage_by_id.get(attacker_id, 0) for attacker_id in candidate.attacker_ids)
        return (2, -pressure, -len(candidate.attacker_ids), candidate.attacker_ids, candidate.enraged_targets)

    return sorted(candidates.values(), key=priority)


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


def _apply_builder_stall_pressure(
    scored_candidates: list[tuple[BuilderAttackCandidate, BuilderAttackScore]],
    *,
    player,
    enemy,
    engine,
    cap_context,
) -> list[tuple[BuilderAttackCandidate, BuilderAttackScore]]:
    stalled_turns = max(0, int(getattr(engine, "builder_stalled_turns", 0)))
    congested_size = min(len(player.battlefield), len(enemy.battlefield))
    full_economy_lock = (
        congested_size >= BUILDER_CREATURE_CAP
        and player.total_resources() >= BUILDER_MAX_RESOURCES
        and enemy.total_resources() >= BUILDER_MAX_RESOURCES
    )
    if full_economy_lock:
        # Creature deaths are only temporary progress once both players can
        # rebuild a full-cost body every turn.  Preserve the longer no-player-
        # damage clock so kill/rebuild loops do not reset urgency forever.
        stalled_turns = max(
            stalled_turns,
            int(getattr(engine, "builder_player_damage_stalled_turns", stalled_turns)),
        )
    if stalled_turns <= STALL_GRACE_TURNS or congested_size < STALL_MIN_BOARD_SIZE:
        return scored_candidates

    board_factor = 1.0 if congested_size >= BUILDER_CREATURE_CAP else 0.65
    initial_pressure = min(
        1.0,
        (stalled_turns - STALL_GRACE_TURNS) / max(1, STALL_RAMP_TURNS),
    )
    extended_pressure = 0.0
    if full_economy_lock:
        extended_stall_turns = max(
            0,
            stalled_turns - STALL_GRACE_TURNS - STALL_RAMP_TURNS,
        )
        extended_pressure = min(
            STALL_MAX_PRESSURE - 1.0,
            extended_stall_turns / max(1, STALL_EXTENDED_RAMP_TURNS),
        )
    pressure = (initial_pressure + extended_pressure) * board_factor
    no_attack_score = next(
        (score for candidate, score in scored_candidates if not candidate.attacker_ids),
        None,
    )
    if no_attack_score is None:
        return scored_candidates
    baseline_counter_damage = no_attack_score.projected_counter_damage
    baseline_best_candidate = max(scored_candidates, key=_attack_candidate_sort_key)[0]
    preserve_existing_attack = bool(baseline_best_candidate.attacker_ids) and not full_economy_lock

    attack_adjustments: dict[BuilderAttackCandidate, float] = {}
    for candidate, score in scored_candidates:
        if not candidate.attacker_ids:
            continue
        if preserve_existing_attack and candidate != baseline_best_candidate:
            continue
        trade_progress = min(score.enemy_kill_value, score.own_death_risk)
        progress_value = (
            score.player_damage * 0.55
            + score.enemy_creature_damage * 0.2
            + score.enemy_kill_value * 0.6
            + trade_progress * 0.35
        )
        if (
            cap_context is not None
            and cap_context.at_cap
            and cap_context.weakest_unit_id is not None
            and cap_context.weakest_unit_id in dict(score.chosen_block_assignment)
        ):
            progress_value += min(cap_context.cap_pressure, score.own_death_risk) * 0.3
        extra_counter_damage = max(
            0.0,
            score.projected_counter_damage - baseline_counter_damage,
        )
        safe_progress = (
            progress_value > 0.2
            and score.counter_lethal_risk < 0.5
            and score.projected_counter_damage < max(1.0, float(player.life))
        )
        if not safe_progress:
            continue
        extended_pressure = max(0.0, pressure - 1.0)
        extended_safe_progress_bonus = extended_pressure * STALL_EXTENDED_SAFE_PROGRESS_BONUS
        progress_time_value = progress_value * (1.0 + extended_pressure)
        attack_bonus_cap = STALL_ATTACK_MAX_BONUS if full_economy_lock else 5.0
        adjustment = pressure * (
            min(attack_bonus_cap, progress_time_value)
            - extra_counter_damage * STALL_COUNTER_EXPOSURE_PENALTY
            + extended_safe_progress_bonus
        )
        if adjustment > 0.0:
            attack_adjustments[candidate] = adjustment

    if not attack_adjustments:
        return scored_candidates

    adjusted: list[tuple[BuilderAttackCandidate, BuilderAttackScore]] = []
    for candidate, score in scored_candidates:
        if not candidate.attacker_ids:
            adjustment = -pressure * STALL_NO_ATTACK_MAX_PENALTY
        else:
            adjustment = attack_adjustments.get(candidate, 0.0)
        if adjustment == 0.0:
            adjusted.append((candidate, score))
            continue
        debug_contributions = tuple(
            contribution
            for contribution in score.debug_contributions
            if contribution[0] != "stall_pressure"
        ) + (
            (
                "stall_pressure",
                round(pressure, 4),
                round(adjustment / pressure, 4),
                round(adjustment, 4),
            ),
        )
        adjusted.append(
            (
                candidate,
                replace(
                    score,
                    total=round(score.total + adjustment, 4),
                    debug_contributions=debug_contributions,
                ),
            )
        )
    return adjusted


def _score_no_attack(player, enemy, engine, cap_context) -> float:
    ready_creatures = list(engine.available_attackers(player))
    preservation = sum(estimate_creature_board_value(creature) for creature in ready_creatures) * NO_ATTACK_PRESERVATION_WEIGHT
    pressure_guard = len(engine.available_attackers(enemy)) * NO_ATTACK_PRESSURE_WEIGHT
    cap_drag = 0.0
    if cap_context is not None and cap_context.at_cap and cap_context.cap_pressure > 0:
        cap_drag = min(3.4, cap_context.cap_pressure * 0.36)
    return preservation + pressure_guard - cap_drag


def _estimate_block_value(blocker, enemy, engine) -> float:
    enemy_signatures = tuple(sorted(_attack_unit_signature(attacker) for attacker in enemy.battlefield))
    return _estimate_block_value_cached(
        _attack_unit_signature(blocker),
        enemy_signatures,
        float(getattr(enemy, "life", 0)),
    )


def _attack_unit_signature(unit) -> tuple:
    return (
        int(getattr(unit, "aw", 0)),
        int(getattr(unit, "vw", 0)),
        int(getattr(unit, "sw", 0)),
        int(getattr(unit, "lw", 0)),
        int(getattr(unit, "current_hp", 0)),
        bool(getattr(unit, "tapped", False)),
        bool(getattr(unit, "cannot_block", False)),
        tuple(sorted(ability.value for ability in getattr(unit, "abilities", ()))),
    )


@lru_cache(maxsize=4096)
def _estimate_block_value_cached(blocker_signature: tuple, enemy_signatures: tuple, enemy_life: float) -> float:
    from .combat_eval import BuilderCombatantView

    blocker = BuilderCombatantView(
        aw=blocker_signature[0],
        vw=blocker_signature[1],
        sw=blocker_signature[2],
        lw=blocker_signature[3],
        current_hp=blocker_signature[4],
        ready=not blocker_signature[5],
        cannot_block=blocker_signature[6],
        abilities=frozenset(Ability(name) for name in blocker_signature[7]),
        name="cached_blocker",
    )
    enemy_units = [
        BuilderCombatantView(
            aw=signature[0],
            vw=signature[1],
            sw=signature[2],
            lw=signature[3],
            current_hp=signature[4],
            ready=not signature[5],
            cannot_block=signature[6],
            abilities=frozenset(Ability(name) for name in signature[7]),
            name="cached_enemy",
        )
        for signature in enemy_signatures
    ]
    # A zero-Defense body may still make a legal one-shot chump block, but it
    # cannot win a defensive dice contest.  Exact counterattack projection still
    # notices a genuinely life-saving chump; this heuristic must not make the AI
    # hold such bodies back as if they were persistent blockers.
    if blocker.vw <= 0:
        return 0.0
    if not any(can_legally_block(attacker, blocker, require_ready=False) for attacker in enemy_units):
        return 0.0
    role_penalty = 1.0
    role_penalty *= 0.55 if blocker.aw > blocker.vw + 1 else 1.0
    total = 0.0
    legal_attackers = [attacker for attacker in enemy_units if can_legally_block(attacker, blocker, require_ready=False)]
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
    damage_race_bonus = min(1.5, max(0.0, enemy_life - 1.0) * 0.04) * BUILDER_AI_WEIGHTS.damage_race
    return average * role_penalty + damage_race_bonus


def _estimate_candidate_counterattack(
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
    *,
    combat_die_sides: int,
    search_budget,
    counter_cache: dict[tuple, BuilderCounterResult] | None = None,
    full_search: bool,
    evaluate_next_main: bool,
) -> BuilderCounterResult:
    counter_projection = _build_counterattack_projection(
        candidate,
        block_assignment,
        player,
        enemy,
        combat_die_sides=combat_die_sides,
    )
    cache_key = (counter_projection.state_signature, full_search, evaluate_next_main)
    if counter_cache is not None and cache_key in counter_cache:
        cached_result = counter_cache[cache_key]
        cached_fast_lethal = (
            not full_search
            and cached_result.score.guaranteed_player_damage >= counter_projection.enemy_life > 0
            and cached_result.main_action_kind in {"pass", "resource"}
        )
        if not cached_fast_lethal:
            return cached_result
    best_result: BuilderCounterResult | None = None
    if full_search:
        build_limit = 2 if search_budget.mode_name == TURN_LOOKAHEAD_SEARCH_BUDGET.mode_name else COUNTER_MAIN_ACTION_BUILD_LIMIT
    else:
        build_limit = 1
    for main_action_kind, main_action_stats, projected_state in _generate_counter_main_action_projections(counter_projection, build_limit=build_limit):
        if best_result is not None and builder_search_should_stop():
            break
        if main_action_kind == "resource" and not evaluate_next_main:
            continue
        current = _evaluate_counter_projection_attack(
            projected_state,
            main_action_kind=main_action_kind,
            main_action_stats=main_action_stats,
            full_search=full_search,
            evaluate_next_main=evaluate_next_main,
        )
        if best_result is None or _counter_result_sort_key(current, projected_state.enemy_life) > _counter_result_sort_key(best_result, counter_projection.enemy_life):
            best_result = current
    if (
        not full_search
        and best_result is not None
        and best_result.score.guaranteed_player_damage >= counter_projection.enemy_life > 0
    ):
        # A fast line may prove that lethal exists while understating its width
        # or missing the haste build that creates it. Refine only this critical
        # case; ordinary lookahead remains on the cheap search path.
        for main_action_kind, main_action_stats, projected_state in _generate_counter_main_action_projections(
            counter_projection,
            build_limit=2,
        ):
            if builder_search_should_stop():
                break
            if not main_action_kind.startswith("build_"):
                continue
            current = _evaluate_counter_projection_attack(
                projected_state,
                main_action_kind=main_action_kind,
                main_action_stats=main_action_stats,
                full_search=True,
                evaluate_next_main=evaluate_next_main,
            )
            if _counter_result_sort_key(current, projected_state.enemy_life) > _counter_result_sort_key(
                best_result,
                counter_projection.enemy_life,
            ):
                best_result = current
    if best_result is None:
        best_result = BuilderCounterResult(
            score=BuilderAttackScore(
                player_damage=0.0,
                enemy_creature_damage=0.0,
                own_creature_damage=0.0,
                enemy_kill_value=0.0,
                own_death_risk=0.0,
                lifesteal_value=0.0,
                board_position_value=0.0,
                vigilance_value=0.0,
                lethal_value=0.0,
                total=0.0,
            ),
            search_exact=True,
            fallback_used=False,
            fallback_reason="",
            main_action_kind="pass",
        )
    if (
        best_result.main_action_kind in {"build_haste_blocker", "build_terminal", "build_best"}
        and best_result.main_action_stats.endswith("/haste")
        and any(attacker_id < 0 for attacker_id in best_result.attackers)
    ):
        best_result = replace(best_result, main_action_kind="build_haste")
    if (
        best_result.main_action_kind == "pass"
        and not evaluate_next_main
        and counter_projection.own_total_resources < BUILDER_MAX_RESOURCES
    ):
        # Growing a resource has the same immediate combat state as passing, so
        # avoid evaluating that duplicate branch while retaining the better
        # strategic action label.
        best_result = replace(best_result, main_action_kind="resource")
    if counter_cache is not None:
        counter_cache[cache_key] = best_result
    return best_result


def _build_counterattack_projection(
    candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    player,
    enemy,
    *,
    combat_die_sides: int,
) -> BuilderTurnProjection:
    own_post: list[ProjectedUnitView] = []
    enemy_post: list[ProjectedUnitView] = []
    attacker_ids = set(candidate.attacker_ids)
    assignment_map = dict(block_assignment)
    attackers = {unit.unit_id: unit for unit in player.battlefield}
    blockers = {unit.unit_id: unit for unit in enemy.battlefield}
    post_hp: dict[int, int] = {}
    removed_ids: set[int] = set()
    initial_player_damage = 0.0

    for attacker_id, blocker_id in block_assignment:
        attacker = attackers.get(attacker_id)
        blocker = blockers.get(blocker_id)
        if attacker is None or blocker is None:
            continue
        outcome = project_builder_combat_outcome(attacker, blocker, combat_die_sides)
        initial_player_damage += outcome.player_damage
        if not outcome.attacker_survives:
            removed_ids.add(attacker_id)
        else:
            post_hp[attacker_id] = outcome.attacker_remaining_hp
        if not outcome.defender_survives:
            removed_ids.add(blocker_id)
        else:
            post_hp[blocker_id] = outcome.defender_remaining_hp

    for attacker_id in attacker_ids:
        if attacker_id in assignment_map or attacker_id in removed_ids:
            continue
        attacker = attackers.get(attacker_id)
        if attacker is None:
            continue
        unblocked = estimate_unblocked_attack(attacker)
        initial_player_damage += unblocked.player_damage
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
                abilities=normalize_builder_abilities(frozenset(unit.abilities)),
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
                abilities=normalize_builder_abilities(frozenset(unit.abilities)),
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
        combat_die_sides=int(combat_die_sides),
        own_life=max(0.0, float(enemy.life) - initial_player_damage),
        enemy_life=player.life,
        own_total_resources=enemy.total_resources(),
        own_ready_resources=enemy.total_resources(),
        enemy_total_resources=player.total_resources(),
        enemy_ready_resources=player.total_resources(),
        own_units=tuple(own_post),
        enemy_units=tuple(enemy_post),
        available_attacker_ids=tuple(unit.unit_id for unit in own_post if unit.is_ready()),
        hypothetical_unit_id=None,
        candidate_signature=("counterattack", candidate.attacker_ids),
        state_signature=_counter_projection_signature(
            enemy.player_id,
            player.player_id,
            max(0.0, float(enemy.life) - initial_player_damage),
            player.life,
            enemy.total_resources(),
            enemy.total_resources(),
            player.total_resources(),
            player.total_resources(),
            tuple(own_post),
            tuple(enemy_post),
        ),
    )


def _generate_counter_main_action_projections(counter_projection: BuilderTurnProjection, *, build_limit: int):
    yield "pass", "-", project_pass_action(counter_projection)
    if counter_projection.own_total_resources < BUILDER_MAX_RESOURCES:
        yield "resource", "-", project_resource_action(counter_projection)
    if len(counter_projection.own_units) >= BUILDER_CREATURE_CAP:
        return
    counter_player = counter_projection.players[counter_projection.player_id]
    counter_snapshot = build_builder_snapshot(counter_player, counter_projection)
    legal_builds = [
        current
        for current in generate_builder_creature_candidates(counter_snapshot, counter_projection.own_ready_resources)
        if is_legal_builder_candidate(current, counter_projection.own_ready_resources)
    ]
    legal_builds = select_builder_creature_search_frontier(
        legal_builds,
        counter_snapshot,
        limit=min(COUNTER_CANDIDATE_SCORING_LIMIT, max(2, build_limit * 2)),
    )
    cache_key = (
        counter_projection.state_signature,
        counter_projection.own_ready_resources,
        counter_projection.enemy_life,
        build_limit,
    )
    cached = _COUNTER_MAIN_ACTION_CACHE.get(cache_key)
    if cached is None:
        selected: dict[tuple, tuple[int, str, object]] = {}

        def consider(priority: int, label: str, candidate) -> None:
            if candidate is None:
                return
            existing = selected.get(candidate.key)
            if existing is None or priority < existing[0]:
                selected[candidate.key] = (priority, label, candidate)

        def consider_many(priority: int, label: str, rows) -> None:
            for current in rows:
                consider(priority, label, current)

        if legal_builds:
            scored = [
                (
                    score_builder_creature_candidate(
                        candidate,
                        counter_snapshot,
                        available_resources=counter_projection.own_ready_resources,
                        enemy_creatures=list(counter_projection.enemy_units),
                        own_creatures=list(counter_projection.own_units),
                    ),
                    candidate,
                )
                for candidate in legal_builds
            ]
            scored.sort(
                key=lambda row: (
                    row[0].total,
                    row[0].immediate_pressure,
                    row[0].matchup_defense,
                    row[0].matchup_offense,
                    row[1].key,
                ),
                reverse=True,
            )
            consider(6, "build_best", scored[0][1])
            haste_attackers = [row for row in scored if row[1].has_haste]
            haste_blockers = [row for row in scored if row[1].has_haste]
            delayed = [row for row in scored if not row[1].has_haste]
            flying = [row for row in scored if row[1].has_ability(Ability.FLYING)]
            defensive = [row for row in scored if row[1].vw > 0]
            terminal = [
                row for row in scored
                if row[1].has_haste and (
                    row[0].immediate_pressure >= counter_projection.enemy_life
                    or row[0].expected_player_damage >= counter_projection.enemy_life
                )
            ]
            raw_haste_damage = max(
                (candidate for candidate in legal_builds if candidate.has_haste and candidate.sw > 0),
                key=lambda candidate: (candidate.sw, candidate.aw, candidate.vw, candidate.lw, candidate.key),
                default=None,
            )
            defensive.sort(
                key=lambda row: (
                    row[0].repeated_block_value,
                    row[0].block_win_probability,
                    row[0].life_breakpoint,
                    row[0].matchup_defense,
                    row[1].key,
                ),
                reverse=True,
            )
            haste_attackers.sort(
                key=lambda row: (
                    row[0].immediate_pressure,
                    row[0].expected_player_damage,
                    row[0].attack_access_probability,
                    row[0].matchup_offense,
                    row[1].key,
                ),
                reverse=True,
            )
            haste_blockers.sort(
                key=lambda row: (
                    row[0].immediate_prevented_damage,
                    row[0].block_win_probability,
                    row[0].repeated_block_value,
                    row[0].life_breakpoint,
                    row[1].key,
                ),
                reverse=True,
            )
            delayed.sort(
                key=lambda row: (
                    row[0].evasion,
                    row[0].matchup_offense,
                    row[0].damage_delivery_probability,
                    -row[0].stranded_damage,
                    row[1].key,
                ),
                reverse=True,
            )
            flying.sort(
                key=lambda row: (
                    row[0].evasion,
                    row[0].expected_player_damage,
                    row[0].matchup_offense,
                    row[1].key,
                ),
                reverse=True,
            )
            consider_many(0, "build_terminal", [candidate for _, candidate in terminal[:3]])
            consider(1, "build_haste", raw_haste_damage)
            consider(1, "build_haste", None if not haste_attackers else haste_attackers[0][1])
            consider(2, "build_haste_blocker", None if not haste_blockers else haste_blockers[0][1])
            consider(3, "build_flying", None if not flying else flying[0][1])
            consider(4, "build_delayed", None if not delayed else delayed[0][1])
            consider(5, "build_defense", None if not defensive else defensive[0][1])
        cached = tuple(sorted(selected.values(), key=lambda row: (row[0], row[1], row[2].key)))
        store_bounded_cache_entry(_COUNTER_MAIN_ACTION_CACHE, cache_key, cached, max_entries=2048)
    ordered = list(cached)
    for _, label, current in ordered[: max(1, build_limit)]:
        action = BuilderTurnActionCandidate(
            action_kind="creature",
            creature_candidate=current,
            projected_total_resources=counter_projection.own_total_resources,
            projected_ready_resources=max(0, counter_projection.own_ready_resources - current.cost),
            generation_reason="counter_haste",
        )
        yield (
            label,
            f"{current.aw}/{current.vw}/{current.sw}/{current.lw}/{getattr(current.builder_ability, 'value', '-')}",
            project_creature_action(counter_projection, action),
        )


def _evaluate_counter_projection_attack(
    projection: BuilderTurnProjection,
    *,
    main_action_kind: str,
    main_action_stats: str,
    full_search: bool,
    evaluate_next_main: bool,
) -> BuilderCounterResult:
    return _fallback_counterattack(
        projection,
        main_action_kind=main_action_kind,
        main_action_stats=main_action_stats,
        fast_mode=not full_search,
        evaluate_next_main=evaluate_next_main,
    )


def _fallback_counterattack(
    projection: BuilderTurnProjection,
    *,
    main_action_kind: str,
    main_action_stats: str,
    fast_mode: bool,
    evaluate_next_main: bool,
) -> BuilderCounterResult:
    from .turn_policy import evaluate_builder_next_main_value

    counter_player = projection.players[projection.player_id]
    defender = projection.players[projection.enemy_id]
    available_attackers = list(projection.available_attackers(counter_player))
    enemy_battlefield = list(defender.battlefield)
    widest_block_upper_bound = estimate_block_assignment_upper_bound(
        len(available_attackers),
        len(list(projection.available_blockers(defender))),
    )
    exact_attack = (
        not fast_mode
        and len(available_attackers) <= FULL_ATTACK_ENUMERATION_THRESHOLD
        and estimate_attack_candidate_upper_bound(available_attackers, enemy_battlefield) <= COUNTERATTACK_SEARCH_BUDGET.max_exact_attack_candidates
        and widest_block_upper_bound <= COUNTERATTACK_SEARCH_BUDGET.max_exact_block_assignments
    )
    if fast_mode:
        candidates = _generate_fast_counter_candidates(available_attackers, enemy_battlefield)
    else:
        candidates = (
            _generate_exhaustive_attack_candidates(available_attackers, enemy_battlefield)
            if exact_attack
            else _generate_structured_attack_candidates(available_attackers, enemy_battlefield)[
                : COUNTERATTACK_SEARCH_BUDGET.max_heuristic_attack_candidates
            ]
        )
    best_candidate = BuilderAttackCandidate(attacker_ids=())
    best_score = BuilderAttackScore(
        player_damage=0.0,
        enemy_creature_damage=0.0,
        own_creature_damage=0.0,
        enemy_kill_value=0.0,
        own_death_risk=0.0,
        lifesteal_value=0.0,
        board_position_value=0.0,
        vigilance_value=0.0,
        lethal_value=0.0,
        total=0.0,
    )
    best_next_main_value = 0.0
    best_next_main_action = "pass"
    best_next_main_stats = "-"
    best_opponent_followup_damage = 0.0
    best_opponent_followup_lethal = False
    best_opponent_followup_attackers: tuple[int, ...] = ()
    exact_blocks = True
    search_complete = True
    evaluated_any = False
    pair_cache: dict[tuple[int, int], tuple] = {}
    for current in candidates:
        if evaluated_any and builder_search_should_stop():
            search_complete = False
            break
        evaluated_any = True
        count_builder_search_work("counter_attack_candidates_scored")
        block_metadata: dict = {}
        assignments = generate_builder_block_assignments(
            current,
            counter_player,
            defender,
            projection,
            search_budget=COUNTERATTACK_SEARCH_BUDGET,
            metadata=block_metadata,
        )
        exact_blocks = exact_blocks and block_metadata.get("exact_search", False)
        scored = [
            evaluate_attack_assignment(
                current,
                assignment,
                counter_player,
                defender,
                projection,
                pair_cache=pair_cache,
                block_value_cache=None,
                cap_context=None,
            )
            for assignment in assignments
        ]
        if not scored:
            continue
        defended = min(scored, key=lambda score: _counter_response_sort_key(score, defender.life))
        if evaluate_next_main:
            next_projection = project_attack_to_next_turn(
                projection,
                current.attacker_ids,
                defended.chosen_block_assignment,
            )
            next_main_value, next_main_action, next_main_stats = evaluate_builder_next_main_value(next_projection)
        else:
            next_main_value, next_main_action, next_main_stats = 0.0, "pass", "-"
        current_result = BuilderCounterResult(
            score=defended,
            search_exact=bool(exact_attack and exact_blocks),
            fallback_used=not (exact_attack and exact_blocks),
            fallback_reason="" if exact_attack and exact_blocks else "fallback_search",
            main_action_kind=main_action_kind,
            main_action_stats=main_action_stats,
            attackers=tuple(current.attacker_ids),
            legal_blockers=_counter_legal_blocker_map(projection, current.attacker_ids),
            next_main_value=next_main_value,
            next_main_action=next_main_action,
            next_main_stats=next_main_stats,
        )
        if _counter_result_sort_key(current_result, defender.life) > _counter_result_sort_key(
            BuilderCounterResult(
                score=best_score,
                search_exact=bool(exact_attack and exact_blocks),
                fallback_used=not (exact_attack and exact_blocks),
                fallback_reason="" if exact_attack and exact_blocks else "fallback_search",
                main_action_kind=main_action_kind,
                main_action_stats=main_action_stats,
                attackers=tuple(best_candidate.attacker_ids),
                legal_blockers=_counter_legal_blocker_map(projection, best_candidate.attacker_ids),
                next_main_value=best_next_main_value,
                next_main_action=best_next_main_action,
                next_main_stats=best_next_main_stats,
            ),
            defender.life,
        ):
            best_candidate = current
            best_score = defended
            best_next_main_value = next_main_value
            best_next_main_action = next_main_action
            best_next_main_stats = next_main_stats
    next_projection = project_attack_to_next_turn(
        projection,
        best_candidate.attacker_ids,
        best_score.chosen_block_assignment,
    )
    search_exact = bool(exact_attack and exact_blocks and search_complete)
    if next_projection.own_life > 0:
        if not fast_mode and search_exact:
            followup = evaluate_best_builder_attack(
                next_projection.players[next_projection.player_id],
                next_projection,
                search_budget=COUNTERATTACK_SEARCH_BUDGET,
                include_counterattack=False,
                debug_output=False,
            )
            best_opponent_followup_damage = followup.score.guaranteed_player_damage
            best_opponent_followup_lethal = (
                next_projection.enemy_life > 0
                and best_opponent_followup_damage >= next_projection.enemy_life
            )
            best_opponent_followup_attackers = tuple(followup.candidate.attacker_ids)
        else:
            (
                best_opponent_followup_damage,
                best_opponent_followup_lethal,
                best_opponent_followup_attackers,
            ) = _estimate_fast_followup_attack(next_projection)
    return BuilderCounterResult(
        score=best_score,
        search_exact=search_exact,
        fallback_used=not search_exact,
        fallback_reason="" if search_exact else "fallback_search",
        main_action_kind=main_action_kind,
        main_action_stats=main_action_stats,
        attackers=tuple(best_candidate.attacker_ids),
        legal_blockers=_counter_legal_blocker_map(projection, best_candidate.attacker_ids),
        next_main_value=best_next_main_value,
        next_main_action=best_next_main_action,
        next_main_stats=best_next_main_stats,
        opponent_followup_damage=best_opponent_followup_damage,
        opponent_followup_lethal=best_opponent_followup_lethal,
        opponent_followup_attackers=best_opponent_followup_attackers,
    )


def _estimate_fast_followup_attack(projection: BuilderTurnProjection) -> tuple[float, bool, tuple[int, ...]]:
    """Cheaply keep pruned attack lines on the same two-turn score horizon."""
    player = projection.players[projection.player_id]
    enemy = projection.players[projection.enemy_id]
    candidates = _generate_fast_counter_candidates(
        list(projection.available_attackers(player)),
        list(enemy.battlefield),
    )
    scored: list[tuple[BuilderAttackCandidate, BuilderAttackScore]] = []
    pair_cache: dict[tuple[int, int], tuple] = {}
    for candidate in candidates:
        assignments = generate_builder_block_assignments(
            candidate,
            player,
            enemy,
            projection,
            search_budget=COUNTERATTACK_SEARCH_BUDGET,
        )
        response_scores = [
            evaluate_attack_assignment(
                candidate,
                assignment,
                player,
                enemy,
                projection,
                pair_cache=pair_cache,
                block_value_cache=None,
                cap_context=None,
            )
            for assignment in assignments
        ]
        if response_scores:
            scored.append((candidate, min(response_scores, key=_adversarial_block_response_sort_key)))
    if not scored:
        return 0.0, False, ()
    candidate, score = max(scored, key=_attack_candidate_sort_key)
    damage = score.guaranteed_player_damage
    lethal = projection.enemy_life > 0 and damage >= projection.enemy_life
    return damage, lethal, tuple(candidate.attacker_ids)


def _estimate_mandatory_coverage_loss(candidate: BuilderAttackCandidate, player, enemy) -> float:
    """Value only the attackers that are uniquely required as legal blockers."""
    attacking_ids = set(candidate.attacker_ids)
    held_blockers = [
        blocker
        for blocker in player.battlefield
        if blocker.unit_id not in attacking_ids and blocker.is_ready()
    ]
    coverage_loss = 0.0
    for attacker in player.battlefield:
        if attacker.unit_id not in attacking_ids:
            continue
        if attacker.has_ability(Ability.VIGILANT) or attacker.has_ability(Ability.VIGILANCE):
            continue
        uniquely_covered = any(
            can_legally_block(threat, attacker, require_ready=False)
            and not any(can_legally_block(threat, held, require_ready=True) for held in held_blockers)
            for threat in enemy.battlefield
            if threat.sw > 0
        )
        if uniquely_covered:
            coverage_loss += _estimate_block_value(attacker, enemy, None) * HEURISTIC_LOST_BLOCK_CONFIDENCE
    return coverage_loss


def _generate_fast_counter_candidates(available_attackers: list, enemy_battlefield: list) -> list[BuilderAttackCandidate]:
    candidates: dict[tuple, BuilderAttackCandidate] = { (tuple(), tuple()): BuilderAttackCandidate(attacker_ids=(), enraged_targets=(), generation_reason="none") }

    def add(group: list, reason: str) -> None:
        for current in _expand_enraged_targets(group, enemy_battlefield, heuristic=True):
            candidates[(current.attacker_ids, current.enraged_targets)] = BuilderAttackCandidate(
                attacker_ids=current.attacker_ids,
                enraged_targets=current.enraged_targets,
                generation_reason=reason,
            )

    add(available_attackers, "all")
    add([unit for unit in available_attackers if unit.has_ability(Ability.FLYING)], "flying")
    by_sw = sorted(available_attackers, key=lambda unit: (unit.sw, unit.aw, unit.unit_id), reverse=True)
    by_value = sorted(available_attackers, key=lambda unit: (estimate_creature_board_value(unit), unit.sw, unit.unit_id), reverse=True)
    if by_sw:
        add(by_sw[: min(2, len(by_sw))], "top_sw")
    if by_value:
        add(by_value[:1], "top_value")
    for unit in by_sw[: min(2, len(by_sw))]:
        add([unit], "single")
    return sorted(candidates.values(), key=lambda current: (len(current.attacker_ids), current.attacker_ids, current.enraged_targets))


def _counter_score_sort_key(score: BuilderAttackScore, defender_life: int) -> tuple:
    return (
        score.guaranteed_player_damage >= defender_life > 0,
        score.lethal_probability,
        score.guaranteed_player_damage,
        score.player_damage,
        score.enemy_kill_value,
        -score.own_death_risk,
    )


def _counter_response_sort_key(score: BuilderAttackScore, defender_life: int) -> tuple:
    return (
        score.guaranteed_player_damage >= defender_life > 0,
        score.lethal_probability,
        score.guaranteed_player_damage,
        score.player_damage,
        score.enemy_kill_value,
        tuple(score.chosen_block_assignment),
    )


def _counter_result_sort_key(result: BuilderCounterResult, defender_life: int) -> tuple:
    score_key = _counter_score_sort_key(result.score, defender_life)
    return score_key[:4] + (
        len(result.attackers),
    ) + score_key[4:] + (
        -result.next_main_value,
        result.main_action_kind,
        result.attackers,
    )


def _counter_legal_blocker_map(projection: BuilderTurnProjection, attacker_ids: tuple[int, ...]) -> tuple[tuple[int, tuple[int, ...]], ...]:
    defender = projection.players[projection.enemy_id]
    available_blockers = list(projection.available_blockers(defender))
    rows: list[tuple[int, tuple[int, ...]]] = []
    for attacker_id in attacker_ids:
        attacker = projection.get_unit_by_id(attacker_id)
        if attacker is None:
            continue
        legal = tuple(
            blocker.unit_id
            for blocker in available_blockers
            if can_legally_block(attacker, blocker, require_ready=True)
        )
        rows.append((attacker_id, legal))
    return tuple(rows)


def _counter_projection_signature(
    player_id: int,
    enemy_id: int,
    own_life: int,
    enemy_life: int,
    own_total_resources: int,
    own_ready_resources: int,
    enemy_total_resources: int,
    enemy_ready_resources: int,
    own_units: tuple[ProjectedUnitView, ...],
    enemy_units: tuple[ProjectedUnitView, ...],
) -> tuple:
    return (
        player_id,
        enemy_id,
        own_life,
        enemy_life,
        own_total_resources,
        own_ready_resources,
        enemy_total_resources,
        enemy_ready_resources,
        tuple(_counter_unit_signature(unit) for unit in own_units),
        tuple(_counter_unit_signature(unit) for unit in enemy_units),
    )


def _counter_unit_signature(unit: ProjectedUnitView) -> tuple:
    return (
        unit.unit_id,
        unit.aw,
        unit.vw,
        unit.sw,
        unit.lw,
        unit.current_hp,
        unit.tapped,
        unit.summoning_sickness,
        tuple(sorted(ability.value for ability in unit.abilities)),
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
                ("counter_search_exact", score.counter_search_exact),
                ("counter_fallback_used", score.counter_fallback_used),
                ("counter_fallback_reason", score.counter_fallback_reason or "none"),
                ("projected_enemy_main_action", score.projected_counter_main_action),
                ("projected_enemy_main_stats", score.projected_counter_main_stats),
                ("projected_enemy_attackers", list(score.projected_counter_attackers)),
                ("projected_legal_blockers", [f"{attacker_id}:{list(blockers)}" for attacker_id, blockers in score.projected_counter_legal_blockers]),
                ("projected_next_attack_damage", score.projected_next_attack_damage),
                ("projected_next_attack_lethal", score.projected_next_attack_lethal),
                ("projected_next_attackers", list(score.projected_next_attackers)),
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
    precision = builder_debug_precision()
    emit_builder_debug_line(
        engine,
        "AI ATTACK",
        player=player,
        decision="attack",
        pairs=(
            ("choose", [] if best_candidate is None else list(best_candidate.attacker_ids)),
            ("total", 0.0 if best_score is None else best_score.total),
            ("runner_up", "N/A" if runner_up is None else list(runner_up[0].attacker_ids)),
            ("runner_up_total", "N/A" if runner_up is None else runner_up[1].total),
            (
                "gap",
                "N/A"
                if runner_up is None or best_score is None
                else round(round(best_score.total, precision) - round(runner_up[1].total, precision), precision),
            ),
            ("delta_keys", "N/A" if runner_up is None or best_score is None else score_delta_keys(best_score, runner_up[1])),
        ),
    )
    if builder_debug_verbose() and builder_debug_include_fingerprints():
        from .turn_policy import build_builder_runtime_fingerprint

        before = build_builder_runtime_fingerprint(player, engine)
        after = build_builder_runtime_fingerprint(player, engine)
        log_builder_fingerprint(engine, player, decision="attack", before=before, after=after)


def _candidate_row_key(candidate: BuilderAttackCandidate) -> tuple:
    return ("attack", tuple(candidate.attacker_ids), tuple(candidate.enraged_targets))
