from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic

import core.config as config
from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_CREATURE_CAP
from core.models import Ability, PHASE_BUILDER_ABILITY, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1

from .attack_policy import BuilderAttackDecision, evaluate_best_builder_attack
from .config import BUILDER_AI_WEIGHTS
from .cap_strategy import compute_builder_cap_context
from .candidates import (
    builder_candidate_budgets,
    generate_builder_creature_candidates,
    is_legal_builder_candidate,
    select_builder_creature_search_frontier,
)
from .combat_eval import can_legally_block, summarize_builder_combat_matchup
from .debug import (
    builder_debug_build_top_n,
    builder_debug_enabled,
    builder_debug_include_fingerprints,
    builder_debug_top_n,
    builder_debug_verbose,
    contribution_pairs,
    emit_builder_debug_line,
    ensure_builder_weights_logged,
    log_builder_fingerprint,
    log_builder_state,
    score_delta_keys,
    turn_score_gap,
)
from .horizon import NEXT_TURN_LETHAL_BONUS, REPEATED_LETHAL_PREVENTION_BONUS, BuilderHorizonReport, evaluate_main_action_horizon
from .scoring import estimate_creature_board_value, score_builder_creature_candidate
from .search_budget import FINAL_DECISION_SEARCH_BUDGET, TURN_LOOKAHEAD_SEARCH_BUDGET
from .search_control import builder_search_scope, builder_search_should_stop, store_bounded_cache_entry
from .snapshot import build_builder_snapshot
from .turn_projection import (
    build_current_turn_projection,
    normalize_builder_abilities,
    project_ability_action,
    project_creature_action,
    project_pass_action,
    project_resource_action,
)
from .turn_types import (
    BuilderAbilityActionCandidate,
    BuilderProjectedCandidate,
    BuilderTurnActionCandidate,
    BuilderTurnDecision,
    BuilderTurnScore,
)

CREATURE_FUTURE_VALUE_WEIGHT = 1.0
RESOURCE_GROWTH_WEIGHT = 1.0
IMMEDIATE_COMBAT_DELTA_WEIGHT = 1.0
READY_DEFENSE_WEIGHT = 0.9
SURVIVAL_URGENCY_WEIGHT = 1.0
RESOURCE_HORIZON_FACTOR = 1.15
RESOURCE_LOW_LEVEL_BONUS = 1.7
RESOURCE_CAP_DECAY = 0.28
BOARD_VALUE_WEIGHT = 0.22
RISK_PENALTY_WEIGHT = 0.26
FUTURE_OFFENSE_WEIGHT = 0.45
BOARD_SLOT_OPPORTUNITY_WEIGHT = 0.65
HASTE_IMMEDIATE_WEIGHT = 0.7
FLYING_OFFENSE_WEIGHT = 0.7
FLYING_COVERAGE_WEIGHT = 0.45
CURVE_DELAY_WEIGHT = 0.95
ROLE_NOVELTY_WEIGHT = 0.6
PASS_ACTION_PENALTY = 0.35
SUICIDE_ATTACK_PENALTY = 4.6
GLASS_CANNON_PENALTY = 2.4
RESOURCE_UNDER_PRESSURE_PENALTY = 1.45
RESOURCE_SAFE_PRESSURE_SCALE = 0.18
RESOURCE_CAUTION_PRESSURE_SCALE = 0.62
RESOURCE_FOUNDATION_TARGET = 4
RESOURCE_FOUNDATION_BONUS = 0.8
RESOURCE_CATCHUP_BONUS = 0.4
SAFE_FOUNDATION_BUILD_DELAY = 3.3
SAFE_COUNTER_DAMAGE_PREVENTION_DISCOUNT = 1.7
WIN_BONUS = 10000.0
LOSS_PENALTY = -10000.0
ZERO_OFFENSE_BUILD_RISK_PENALTY = 1.5
EMPTY_BOARD_RAMP_PENALTY = 1.35
CAP_PRESSURE_WEIGHT = 0.55
RESOURCE_AT_CAP_PENALTY = 0.6
TAPPED_NEW_BODY_PENALTY = 0.45
DRAW_REWARD_VALUE = 0.0
CARD_HOLD_WEIGHT = 0.0
ABILITY_IMPACT_WEIGHT = 0.0
_FUTURE_SLOT_VALUE_CACHE: dict[tuple, float] = {}
_BUDGET_FRONTIER_CACHE: dict[tuple, tuple[float, str]] = {}
ROOT_BUILD_SCORING_LIMIT = 128
FRONTIER_BUILD_SCORING_LIMIT = 48
ROOT_BUILD_SCORING_SECONDS = 4.0
FRONTIER_SCORING_SECONDS = 1.5
# Main-action candidates only need a representative future line. Giving every
# candidate a full second lets 20+ otherwise legal builds consume the entire
# turn deadline on repeated attack/block projections. The selected action still
# retains the normal attack search; only its comparative future preview is
# bounded more tightly.
ACTION_HORIZON_SECONDS = 0.5


@dataclass(frozen=True)
class BuilderTurnWeights:
    creature_future_value: float = CREATURE_FUTURE_VALUE_WEIGHT
    resource_growth: float = RESOURCE_GROWTH_WEIGHT
    immediate_combat_delta: float = IMMEDIATE_COMBAT_DELTA_WEIGHT
    ready_defense: float = READY_DEFENSE_WEIGHT
    survival_urgency: float = SURVIVAL_URGENCY_WEIGHT
    board_value: float = BOARD_VALUE_WEIGHT
    risk_penalty: float = RISK_PENALTY_WEIGHT
    card_hold: float = CARD_HOLD_WEIGHT
    ability_impact: float = ABILITY_IMPACT_WEIGHT


TURN_WEIGHTS = BuilderTurnWeights()


def plan_builder_turn(player, engine, *, cancel_event=None) -> BuilderTurnDecision:
    runtime_signature = build_builder_runtime_fingerprint(player, engine)
    cached = getattr(engine.ai, "_last_builder_turn_decision", None)
    if cached is not None and _decision_matches_runtime(cached, engine.phase, runtime_signature):
        return cached

    time_limit = max(1.0, float(getattr(config, "AI_THINKING_TIME_LIMIT_SECONDS", 25.0)))
    deadline = monotonic() + time_limit

    with builder_search_scope(deadline=deadline, cancel_event=cancel_event) as search_control:
        if engine.phase == PHASE_MAIN_1 and not player.main_action_used_this_turn:
            decision = _plan_builder_full_turn(player, engine, runtime_signature, deadline=deadline)
        elif engine.phase == PHASE_BUILDER_ABILITY:
            decision = _plan_builder_continuation(
                player,
                engine,
                runtime_signature,
                allow_ability=BUILDER_ABILITIES_ENABLED and not engine.builder_ability_used_this_turn,
                deadline=deadline,
            )
        elif engine.phase == PHASE_DECLARE_ATTACKERS:
            decision = _plan_builder_continuation(player, engine, runtime_signature, allow_ability=False, deadline=deadline)
        else:
            decision = _plan_builder_continuation(player, engine, runtime_signature, allow_ability=False, deadline=deadline)
        search_metrics = search_control.metrics()
        setattr(engine.ai, "_last_builder_search_metrics", search_metrics)

    setattr(engine.ai, "_last_builder_turn_decision", decision)
    if builder_debug_enabled():
        emit_builder_debug_line(
            engine,
            "AI PERF",
            player=player,
            decision="turn_search",
            pairs=tuple(search_metrics.items()),
        )
    return decision


def choose_builder_turn_plan(player, engine, *, cancel_event=None) -> BuilderTurnDecision:
    return plan_builder_turn(player, engine, cancel_event=cancel_event)


def materialize_builder_turn_decision(
    decision: BuilderTurnDecision,
    *,
    synthetic_unit_id: int,
    actual_unit_id: int,
    post_main_signature: tuple,
) -> BuilderTurnDecision:
    def remap_unit_id(unit_id: int | None) -> int | None:
        if unit_id == synthetic_unit_id:
            return actual_unit_id
        return unit_id

    predicted_attack = decision.predicted_attack_decision
    if predicted_attack is not None:
        predicted_attack = replace(
            predicted_attack,
            candidate=replace(
                predicted_attack.candidate,
                attacker_ids=tuple(remap_unit_id(attacker_id) for attacker_id in predicted_attack.candidate.attacker_ids),
                enraged_targets=tuple(
                    (remap_unit_id(attacker_id), remap_unit_id(blocker_id))
                    for attacker_id, blocker_id in predicted_attack.candidate.enraged_targets
                ),
            ),
            defensive_response=tuple(
                (remap_unit_id(attacker_id), remap_unit_id(blocker_id))
                for attacker_id, blocker_id in (predicted_attack.defensive_response or ())
            ),
        )
    return replace(
        decision,
        ability_action=replace(decision.ability_action, target_id=remap_unit_id(decision.ability_action.target_id)),
        predicted_attack_decision=predicted_attack,
        post_main_signature=post_main_signature,
    )


def choose_builder_main_action(player, engine) -> str:
    return plan_builder_turn(player, engine).action_candidate.action_kind


def choose_builder_creature_plan(player, engine) -> dict | None:
    decision = plan_builder_turn(player, engine)
    if decision.action_candidate.action_kind != "creature" or decision.action_candidate.creature_candidate is None:
        return None
    return build_builder_plan_dict(decision.action_candidate.creature_candidate)


def build_builder_plan_dict(candidate) -> dict:
    return {
        "aw": candidate.aw,
        "vw": candidate.vw,
        "sw": candidate.sw,
        "lw": candidate.lw,
        "ability": candidate.builder_ability,
        "ability_label": None if candidate.builder_ability is None else candidate.builder_ability.value,
        "ability_cost": 0,
        "haste": candidate.has_haste,
        "haste_cost": candidate.haste_cost,
        "abilities": tuple(sorted(ability.value for ability in candidate.abilities)),
        "cost": candidate.cost,
        "profile": candidate.generation_reason or "planned",
        "candidate_signature": candidate.key,
    }


def extract_candidate_future_value(candidate_score, candidate, snapshot) -> float:
    return round(
        candidate_score.raw_stats
        + candidate_score.synergy
        + candidate_score.board_fit
        + candidate_score.survivability
        + candidate_score.matchup_defense
        + candidate_score.matchup_offense * 0.42
        + candidate_score.evasion * 0.25
        + candidate_score.kill_pressure * 0.18
        - abs(candidate_score.death_risk) * 0.35
        + _stats_role_bonus(candidate, snapshot)
        - max(0.0, -candidate_score.unused_resources),
        4,
    )


def score_resource_growth_action(
    snapshot,
    current_candidate_frontier,
    next_resource_candidate_frontier,
    *,
    expected_counter_damage: float = 0.0,
    counter_lethal_risk: float = 0.0,
) -> float:
    if snapshot.own_total_resources >= 10:
        return float("-inf")
    current_best = max((projected.future_value for projected in current_candidate_frontier), default=0.0)
    next_best = max((projected.future_value for projected in next_resource_candidate_frontier), default=current_best)
    marginal_capacity = max(0.0, next_best - current_best)
    pressure = _base_survival_pressure(snapshot)
    horizon = max(0.16, RESOURCE_HORIZON_FACTOR - snapshot.own_total_resources * 0.07 - pressure * 0.07)
    level_bonus = max(0.0, RESOURCE_LOW_LEVEL_BONUS - snapshot.own_total_resources * RESOURCE_CAP_DECAY)
    life_after_counter = snapshot.own_life - max(0.0, expected_counter_damage)
    if pressure < 3.0:
        pressure_scale = 0.0
    elif counter_lethal_risk > 0.0 or life_after_counter <= 2.0:
        pressure_scale = 1.0
    elif life_after_counter <= 4.0:
        pressure_scale = RESOURCE_CAUTION_PRESSURE_SCALE
    else:
        # Board pressure matters, but taking a few non-lethal points at high life
        # is often the correct price for permanently improving every later build.
        pressure_scale = RESOURCE_SAFE_PRESSURE_SCALE
    under_pressure_penalty = pressure * RESOURCE_UNDER_PRESSURE_PENALTY * pressure_scale
    safe_to_develop = counter_lethal_risk <= 0.0 and life_after_counter >= 5.0
    foundation_bonus = 0.0
    catchup_bonus = 0.0
    if safe_to_develop:
        missing_foundation = max(0, RESOURCE_FOUNDATION_TARGET - snapshot.own_total_resources)
        foundation_bonus = missing_foundation * RESOURCE_FOUNDATION_BONUS
        catchup_bonus = min(
            0.8,
            max(0, snapshot.enemy_total_resources - snapshot.own_total_resources) * RESOURCE_CATCHUP_BONUS,
        )
    empty_board_penalty = EMPTY_BOARD_RAMP_PENALTY if not snapshot.own_has_board and snapshot.own_total_resources >= 4 else 0.0
    at_cap_penalty = RESOURCE_AT_CAP_PENALTY if snapshot.own_creature_count >= BUILDER_CREATURE_CAP else 0.0
    return round(
        level_bonus
        + marginal_capacity * horizon
        + foundation_bonus
        + catchup_bonus
        - under_pressure_penalty
        - empty_board_penalty
        - at_cap_penalty,
        4,
    )


def build_builder_runtime_fingerprint(player, engine) -> tuple:
    enemy = engine.players[1 - player.player_id]
    hand_signature = ()
    ability_used = False
    if BUILDER_ABILITIES_ENABLED:
        hand_signature = tuple(sorted((card.instance_id, getattr(engine.get_builder_card_ability(card), "value", "")) for card in player.hand))
        ability_used = engine.builder_ability_used_this_turn
    return (
        player.player_id,
        engine.phase,
        player.life,
        enemy.life,
        player.total_resources(),
        player.available_resources(),
        enemy.total_resources(),
        enemy.available_resources(),
        ability_used,
        hand_signature,
        tuple(sorted(getattr(engine, "builder_created_this_turn_ids", set()))),
        tuple(_runtime_unit_signature(creature) for creature in player.battlefield),
        tuple(_runtime_unit_signature(creature) for creature in enemy.battlefield),
        int(getattr(engine, "builder_stalled_turns", 0)),
    )


def _plan_builder_full_turn(player, engine, runtime_signature: tuple, *, deadline: float) -> BuilderTurnDecision:
    if builder_debug_enabled():
        ensure_builder_weights_logged(engine)
    snapshot = build_builder_snapshot(player, engine)
    if builder_debug_verbose():
        log_builder_state(engine, player, decision="main", snapshot=snapshot)
    base_projection = build_current_turn_projection(player, engine)
    attack_cache: dict[tuple, BuilderAttackDecision] = {}
    horizon_cache: dict[tuple, BuilderHorizonReport] = {}
    baseline_attack = _evaluate_attack_cached(base_projection, attack_cache)
    if baseline_attack.score.guaranteed_player_damage >= base_projection.enemy_life > 0:
        action_candidate = BuilderTurnActionCandidate(
            action_kind="pass",
            creature_candidate=None,
            projected_total_resources=player.total_resources(),
            projected_ready_resources=player.available_resources(),
            generation_reason="guaranteed_lethal_attack",
        )
        frontier_context = (0.0, "-", 0.0, "-", 0.0, "-")
        decision = _build_action_decision(
            action_candidate=action_candidate,
            ability_action=BuilderAbilityActionCandidate(action_kind="skip", generation_reason="lethal_short_circuit"),
            main_projection=base_projection,
            projection=base_projection,
            baseline_attack=baseline_attack,
            skip_attack=baseline_attack,
            predicted_attack=baseline_attack,
            snapshot=snapshot,
            projected_candidate=None,
            source_signature=runtime_signature,
            fallback_used=False,
            skip_hold_value=0.0,
            horizon_cache=horizon_cache,
            frontier_context=frontier_context,
            engine=engine,
            player=player,
            deadline=deadline,
            evaluate_horizon=engine.phase != PHASE_DECLARE_ATTACKERS,
        )
        decision = _finalize_selected_attack_plan(base_projection, decision)
        _debug_turn_decision(engine, player, runtime_signature, snapshot, baseline_attack, [decision], False)
        return decision
    static_candidates, fallback_used, build_debug = _build_projected_candidates(
        player,
        engine,
        snapshot,
        deadline=min(deadline, monotonic() + ROOT_BUILD_SCORING_SECONDS),
    )
    shortlisted = _shortlist_projected_candidates(static_candidates, snapshot)
    frontier_context = _build_frontier_context(
        snapshot,
        base_projection,
        deadline=min(deadline, monotonic() + FRONTIER_SCORING_SECONDS),
    )

    decisions: list[BuilderTurnDecision] = []
    for action_candidate, projection, projected_candidate in _generate_main_action_projections(player, engine, base_projection, shortlisted):
        if not BUILDER_ABILITIES_ENABLED:
            predicted_attack = _evaluate_attack_cached(projection, attack_cache)
            decisions.append(
                _build_action_decision(
                    action_candidate=action_candidate,
                    ability_action=BuilderAbilityActionCandidate(action_kind="skip", generation_reason="disabled"),
                    main_projection=projection,
                    projection=projection,
                    baseline_attack=baseline_attack,
                    skip_attack=predicted_attack,
                    predicted_attack=predicted_attack,
                    snapshot=snapshot,
                    projected_candidate=projected_candidate,
                    source_signature=runtime_signature,
                    fallback_used=fallback_used,
                    skip_hold_value=0.0,
                    horizon_cache=horizon_cache,
                    frontier_context=frontier_context,
                    engine=engine,
                    player=player,
                    deadline=deadline,
                )
            )
            current_decision = decisions[-1]
            if (
                current_decision.predicted_attack_decision is not None
                and current_decision.predicted_attack_decision.score.guaranteed_player_damage >= base_projection.enemy_life > 0
            ):
                _debug_build_candidates(engine, player, snapshot, build_debug, shortlisted, current_decision)
                _debug_turn_decision(engine, player, runtime_signature, snapshot, baseline_attack, [current_decision], fallback_used)
                return current_decision
            if decisions and builder_search_should_stop(deadline):
                break
            continue
        decisions.extend(
            _evaluate_ability_plans_for_projection(
                player=player,
                engine=engine,
                snapshot=snapshot,
                action_candidate=action_candidate,
                main_projection=projection,
                projected_candidate=projected_candidate,
                baseline_attack=baseline_attack,
                attack_cache=attack_cache,
                horizon_cache=horizon_cache,
                source_signature=runtime_signature,
                fallback_used=fallback_used,
                frontier_context=frontier_context,
                deadline=deadline,
            )
        )
        if decisions and builder_search_should_stop(deadline):
            break
    decisions.sort(key=_turn_decision_sort_key, reverse=True)
    decision = _finalize_selected_attack_plan(base_projection, decisions[0])
    decisions[0] = decision
    _debug_build_candidates(engine, player, snapshot, build_debug, shortlisted, decision)
    _debug_turn_decision(engine, player, runtime_signature, snapshot, baseline_attack, decisions, fallback_used)
    return decision


def _plan_builder_continuation(player, engine, runtime_signature: tuple, *, allow_ability: bool, deadline: float) -> BuilderTurnDecision:
    if builder_debug_enabled():
        ensure_builder_weights_logged(engine)
    snapshot = build_builder_snapshot(player, engine)
    if builder_debug_verbose():
        log_builder_state(
            engine,
            player,
            decision="attack" if engine.phase == PHASE_DECLARE_ATTACKERS else "continue",
            snapshot=snapshot,
        )
    base_projection = build_current_turn_projection(player, engine)
    if engine.phase == PHASE_DECLARE_ATTACKERS:
        # Creature-frontier values cannot change the already committed main
        # action.  Computing them here used to consume the attack phase's local
        # budget before the accurate combat search even started.
        frontier_context = (0.0, "-", 0.0, "-", 0.0, "-")
    else:
        frontier_context = _build_frontier_context(
            snapshot,
            base_projection,
            deadline=min(deadline, monotonic() + FRONTIER_SCORING_SECONDS),
        )
    attack_cache: dict[tuple, BuilderAttackDecision] = {}
    horizon_cache: dict[tuple, BuilderHorizonReport] = {}
    attack_budget = (
        FINAL_DECISION_SEARCH_BUDGET
        if engine.phase == PHASE_DECLARE_ATTACKERS
        else TURN_LOOKAHEAD_SEARCH_BUDGET
    )
    baseline_attack = _evaluate_attack_cached(
        base_projection,
        attack_cache,
        search_budget=attack_budget,
    )
    action_candidate = BuilderTurnActionCandidate(
        action_kind="continue",
        creature_candidate=None,
        projected_total_resources=player.total_resources(),
        projected_ready_resources=player.available_resources(),
        generation_reason="continuation",
    )
    if not BUILDER_ABILITIES_ENABLED:
        decision = _build_action_decision(
            action_candidate=action_candidate,
            ability_action=BuilderAbilityActionCandidate(action_kind="skip", generation_reason="disabled"),
            main_projection=base_projection,
            projection=base_projection,
            baseline_attack=baseline_attack,
            skip_attack=baseline_attack,
            predicted_attack=baseline_attack,
            snapshot=snapshot,
            projected_candidate=None,
            source_signature=runtime_signature,
            fallback_used=False,
            skip_hold_value=0.0,
            horizon_cache=horizon_cache,
            frontier_context=frontier_context,
            engine=engine,
            player=player,
            deadline=deadline,
            evaluate_horizon=engine.phase != PHASE_DECLARE_ATTACKERS,
        )
        return _finalize_selected_attack_plan(base_projection, decision)
    decisions = _evaluate_ability_plans_for_projection(
        player=player,
        engine=engine,
        snapshot=snapshot,
        action_candidate=action_candidate,
        main_projection=base_projection,
        projected_candidate=None,
        baseline_attack=baseline_attack,
        attack_cache=attack_cache,
        horizon_cache=horizon_cache,
        source_signature=runtime_signature,
        fallback_used=False,
        frontier_context=frontier_context,
        allow_ability=allow_ability,
        deadline=deadline,
        evaluate_horizon=engine.phase != PHASE_DECLARE_ATTACKERS,
    )
    decisions.sort(key=_turn_decision_sort_key, reverse=True)
    return _finalize_selected_attack_plan(base_projection, decisions[0])


def _generate_main_action_projections(player, engine, base_projection, shortlisted):
    yielded = False
    if player.total_resources() < engine.BUILDER_MAX_RESOURCES:
        resource_candidate = BuilderTurnActionCandidate(
            action_kind="resource",
            creature_candidate=None,
            projected_total_resources=player.total_resources() + 1,
            projected_ready_resources=player.available_resources() + 1,
            generation_reason="resource_growth",
        )
        yielded = True
        # Resource growth is cheap to evaluate and must not disappear merely
        # because creature projections consume the turn-wide time budget.
        yield resource_candidate, project_resource_action(base_projection), None

    if len(base_projection.own_units) < engine.BUILDER_CREATURE_CAP:
        for projected_candidate in shortlisted:
            action_candidate = BuilderTurnActionCandidate(
                action_kind="creature",
                creature_candidate=projected_candidate.candidate,
                projected_total_resources=player.total_resources(),
                projected_ready_resources=max(0, player.available_resources() - projected_candidate.candidate.cost),
                generation_reason="|".join(projected_candidate.shortlist_reasons) or projected_candidate.candidate.generation_reason,
            )
            yielded = True
            yield action_candidate, project_creature_action(base_projection, action_candidate), projected_candidate
    if not yielded:
        pass_candidate = BuilderTurnActionCandidate(
            action_kind="pass",
            creature_candidate=None,
            projected_total_resources=player.total_resources(),
            projected_ready_resources=player.available_resources(),
            generation_reason="no_legal_main_action",
        )
        yield pass_candidate, project_pass_action(base_projection), None


def _evaluate_ability_plans_for_projection(
    *,
    player,
    engine,
    snapshot,
    action_candidate: BuilderTurnActionCandidate,
    main_projection,
    projected_candidate: BuilderProjectedCandidate | None,
    baseline_attack: BuilderAttackDecision,
    attack_cache: dict[tuple, BuilderAttackDecision],
    horizon_cache: dict[tuple, BuilderHorizonReport],
    source_signature: tuple,
    fallback_used: bool,
    frontier_context: tuple[float, str, float, str, float, str],
    deadline: float,
    allow_ability: bool = True,
    evaluate_horizon: bool = True,
) -> list[BuilderTurnDecision]:
    if not BUILDER_ABILITIES_ENABLED:
        predicted_attack = _evaluate_attack_cached(main_projection, attack_cache)
        return [
            _build_action_decision(
                action_candidate=action_candidate,
                ability_action=BuilderAbilityActionCandidate(action_kind="skip", generation_reason="disabled"),
                main_projection=main_projection,
                projection=main_projection,
                baseline_attack=baseline_attack,
                skip_attack=predicted_attack,
                predicted_attack=predicted_attack,
                snapshot=snapshot,
                projected_candidate=projected_candidate,
                source_signature=source_signature,
                fallback_used=fallback_used,
                skip_hold_value=0.0,
                horizon_cache=horizon_cache,
                frontier_context=frontier_context,
                engine=engine,
                player=player,
                deadline=deadline,
                evaluate_horizon=evaluate_horizon,
            )
        ]
    ability_candidates = _generate_ability_action_candidates(player, engine, main_projection, allow_ability=allow_ability)
    skip_projection = project_ability_action(main_projection, BuilderAbilityActionCandidate(action_kind="skip"))
    skip_attack = _evaluate_attack_cached(skip_projection, attack_cache)
    skip_hold_value = _remaining_hand_value(player, engine, None, snapshot, main_projection)

    decisions: list[BuilderTurnDecision] = []
    for ability_action in ability_candidates:
        ability_projection = project_ability_action(main_projection, ability_action)
        predicted_attack = _evaluate_attack_cached(ability_projection, attack_cache)
        decision = _build_action_decision(
            action_candidate=action_candidate,
            ability_action=ability_action,
            main_projection=main_projection,
            projection=ability_projection,
            baseline_attack=baseline_attack,
            skip_attack=skip_attack,
            predicted_attack=predicted_attack,
            snapshot=snapshot,
            projected_candidate=projected_candidate,
            source_signature=source_signature,
            fallback_used=fallback_used,
            skip_hold_value=skip_hold_value,
            horizon_cache=horizon_cache,
            frontier_context=frontier_context,
            engine=engine,
            player=player,
            deadline=deadline,
            evaluate_horizon=evaluate_horizon,
        )
        decisions.append(decision)
        if decisions and builder_search_should_stop(deadline):
            break
    return decisions


def _generate_ability_action_candidates(player, engine, projection, *, allow_ability: bool) -> list[BuilderAbilityActionCandidate]:
    if not BUILDER_ABILITIES_ENABLED:
        return [BuilderAbilityActionCandidate(action_kind="skip", generation_reason="disabled")]
    if not allow_ability or engine.builder_ability_used_this_turn or not player.hand:
        return [BuilderAbilityActionCandidate(action_kind="skip", generation_reason="not_available")]

    created_this_turn_ids = set(getattr(engine, "builder_created_this_turn_ids", set()))
    if projection.hypothetical_unit_id is not None:
        created_this_turn_ids.add(projection.hypothetical_unit_id)

    candidates: dict[tuple, BuilderAbilityActionCandidate] = {
        ("skip",): BuilderAbilityActionCandidate(action_kind="skip", generation_reason="preserve_card")
    }
    own_units = list(projection.own_units)
    any_units = list(projection.own_units + projection.enemy_units)
    for card in sorted(player.hand, key=lambda current: current.instance_id):
        ability = engine.get_builder_card_ability(card)
        if ability is None:
            continue
        for unit in own_units:
            if _can_grant_projection_ability(unit, ability, created_this_turn_ids):
                key = ("grant", ability.value, unit.unit_id)
                candidates.setdefault(
                    key,
                    BuilderAbilityActionCandidate(
                        action_kind="grant_ability",
                        card_instance_id=card.instance_id,
                        card_ability=ability,
                        target_id=unit.unit_id,
                        generation_reason="grant",
                    ),
                )
            for stat_name in ("aw", "vw", "sw", "lw"):
                key = ("stat", ability.value, unit.unit_id, stat_name)
                candidates.setdefault(
                    key,
                    BuilderAbilityActionCandidate(
                        action_kind="add_stat",
                        card_instance_id=card.instance_id,
                        card_ability=ability,
                        target_id=unit.unit_id,
                        selected_stat=stat_name,
                        generation_reason="stat",
                    ),
                )
        for unit in any_units:
            key = ("damage", ability.value, unit.unit_id)
            candidates.setdefault(
                key,
                BuilderAbilityActionCandidate(
                    action_kind="deal_damage",
                    card_instance_id=card.instance_id,
                    card_ability=ability,
                    target_id=unit.unit_id,
                    generation_reason="damage",
                ),
            )
    ordered = sorted(candidates.values(), key=_ability_candidate_sort_key)
    return _shortlist_ability_actions(ordered, projection)


def _shortlist_ability_actions(candidates: list[BuilderAbilityActionCandidate], projection) -> list[BuilderAbilityActionCandidate]:
    if len(candidates) <= 28:
        return candidates
    selected: list[BuilderAbilityActionCandidate] = []
    buckets = {
        "skip": [],
        "grant_ability": [],
        "add_stat": [],
        "deal_damage": [],
    }
    for candidate in candidates:
        buckets[candidate.action_kind].append(candidate)
    selected.extend(buckets["skip"][:1])
    selected.extend(buckets["grant_ability"][:10])
    selected.extend(buckets["add_stat"][:10])
    selected.extend(buckets["deal_damage"][:7])
    selected = sorted({(candidate.action_kind, candidate.card_instance_id, candidate.target_id, candidate.selected_stat): candidate for candidate in selected}.values(), key=_ability_candidate_sort_key)
    return selected


def _build_projected_candidates(
    player,
    engine,
    snapshot,
    *,
    deadline: float | None = None,
    scoring_limit: int = ROOT_BUILD_SCORING_LIMIT,
) -> tuple[list[BuilderProjectedCandidate], bool, dict]:
    available_resources = player.available_resources()
    candidates = generate_builder_creature_candidates(snapshot, available_resources)
    considered_budgets = builder_candidate_budgets(snapshot, available_resources)
    enemy_creatures = list(engine.players[1 - player.player_id].battlefield)
    own_creatures = list(player.battlefield)
    legal = [candidate for candidate in candidates if is_legal_builder_candidate(candidate, available_resources)]
    if not legal:
        return [], False, {
            "budget": available_resources,
            "considered_budgets": considered_budgets,
            "generated_count": len(candidates),
            "legal_count": 0,
            "projected_all": tuple(),
            "frontier": tuple(),
        }
    search_frontier = select_builder_creature_search_frontier(
        legal,
        snapshot,
        limit=scoring_limit,
    )
    projected: list[BuilderProjectedCandidate] = []
    for candidate in search_frontier:
        static_score = score_builder_creature_candidate(
            candidate,
            snapshot,
            available_resources=available_resources,
            enemy_creatures=enemy_creatures,
            own_creatures=own_creatures,
        )
        projected.append(
            BuilderProjectedCandidate(
                candidate=candidate,
                static_score=static_score,
                future_value=extract_candidate_future_value(static_score, candidate, snapshot),
            )
        )
        if projected and builder_search_should_stop(deadline):
            break
    projected.sort(key=_projected_candidate_sort_key, reverse=True)
    return projected, False, {
        "budget": available_resources,
        "considered_budgets": considered_budgets,
        "generated_count": len(candidates),
        "legal_count": len(legal),
        "search_frontier_count": len(search_frontier),
        "projected_all": tuple(projected),
        "frontier": tuple(projected),
    }


def _build_action_decision(
    *,
    action_candidate: BuilderTurnActionCandidate,
    ability_action: BuilderAbilityActionCandidate,
    main_projection,
    projection,
    baseline_attack: BuilderAttackDecision,
    skip_attack: BuilderAttackDecision,
    predicted_attack: BuilderAttackDecision,
    snapshot,
    projected_candidate: BuilderProjectedCandidate | None,
    source_signature: tuple,
    fallback_used: bool,
    skip_hold_value: float,
    horizon_cache: dict[tuple, BuilderHorizonReport],
    frontier_context: tuple[float, str, float, str, float, str],
    engine,
    player,
    deadline: float,
    evaluate_horizon: bool = True,
) -> BuilderTurnDecision:
    cap_context = compute_builder_cap_context(
        projection.players[projection.player_id],
        projection,
        creature_cap=BUILDER_CREATURE_CAP,
        resource_budget=projection.own_total_resources,
    )
    current_frontier = [projected_candidate] if projected_candidate is not None else []
    next_frontier = []
    if action_candidate.action_kind == "resource":
        next_snapshot = build_builder_snapshot(projection.players[projection.player_id], projection)
        next_frontier, _, _ = _build_projected_candidates(
            projection.players[projection.player_id],
            projection,
            next_snapshot,
            deadline=min(deadline, monotonic() + FRONTIER_SCORING_SECONDS),
            scoring_limit=FRONTIER_BUILD_SCORING_LIMIT,
        )

    terminal = _score_terminal_projection(projection, predicted_attack)
    if not evaluate_horizon or predicted_attack.score.guaranteed_player_damage >= projection.enemy_life > 0:
        horizon = BuilderHorizonReport()
    else:
        horizon = _evaluate_horizon_cached(
            projection,
            predicted_attack,
            horizon_cache,
            deadline=min(deadline, monotonic() + ACTION_HORIZON_SECONDS),
        )
    creature_future_value = 0.0 if projected_candidate is None else projected_candidate.future_value * TURN_WEIGHTS.creature_future_value
    raw_resource_growth_value = (
        score_resource_growth_action(
            snapshot,
            current_frontier,
            next_frontier,
            expected_counter_damage=predicted_attack.score.projected_counter_damage,
            counter_lethal_risk=predicted_attack.score.counter_lethal_risk,
        )
        if action_candidate.action_kind == "resource"
        else 0.0
    )
    resource_growth_value = (
        raw_resource_growth_value
        * TURN_WEIGHTS.resource_growth
        * BUILDER_AI_WEIGHTS.resource_growth_vs_build
    )
    raw_immediate_combat_delta = _score_immediate_combat_delta(
        snapshot,
        projection,
        baseline_attack,
        predicted_attack,
        projected_candidate,
    )
    immediate_combat_delta = raw_immediate_combat_delta * TURN_WEIGHTS.immediate_combat_delta
    end_of_turn_readiness = _score_end_of_turn_readiness(projection, predicted_attack, snapshot) * TURN_WEIGHTS.ready_defense
    survival_urgency = _score_action_survival_urgency(snapshot, projection, predicted_attack, action_candidate.action_kind) * TURN_WEIGHTS.survival_urgency
    board_value = _score_board_projection_value(projection) * TURN_WEIGHTS.board_value
    expected_enemy_followup_damage = predicted_attack.score.projected_counter_damage
    enemy_lethal_risk = predicted_attack.score.counter_lethal_risk
    survival_buffer = projection.own_life - expected_enemy_followup_damage
    future_offense_raw = _score_future_offense_value(snapshot, projection, predicted_attack, projected_candidate, horizon)
    future_offense_value = future_offense_raw * FUTURE_OFFENSE_WEIGHT
    board_slot_raw = _score_board_slot_opportunity_cost(snapshot, projection, predicted_attack, projected_candidate, cap_context, horizon)
    board_slot_opportunity_cost = board_slot_raw * BOARD_SLOT_OPPORTUNITY_WEIGHT
    haste_immediate_value = _score_haste_immediate_value(
        snapshot,
        projection,
        predicted_attack,
        projected_candidate,
        baseline_attack,
    ) * HASTE_IMMEDIATE_WEIGHT
    flying_offense_value = _score_flying_offense_value(snapshot, projection, predicted_attack, projected_candidate) * FLYING_OFFENSE_WEIGHT
    flying_coverage_raw = _score_flying_coverage_value(snapshot, projection, predicted_attack, projected_candidate, horizon)
    flying_coverage_value = flying_coverage_raw * FLYING_COVERAGE_WEIGHT
    (
        best_build_value_now,
        best_build_stats_now,
        best_build_value_r_plus_1,
        best_build_stats_r_plus_1,
        best_build_value_r_plus_2,
        best_build_stats_r_plus_2,
    ) = frontier_context
    curve_delay_raw = _score_curve_delay(
        snapshot,
        projection,
        baseline_attack,
        predicted_attack,
        projected_candidate,
        best_build_value_now,
        best_build_value_r_plus_1,
        best_build_value_r_plus_2,
    )
    curve_delay_value = -curve_delay_raw * CURVE_DELAY_WEIGHT
    role_novelty_raw = _score_role_novelty(snapshot, projection, predicted_attack, projected_candidate)
    role_novelty_value = role_novelty_raw * ROLE_NOVELTY_WEIGHT
    projected_slot_tenure = _estimate_projected_slot_tenure(snapshot, projection, predicted_attack, projected_candidate)
    ability_value = _score_ability_action_value(
        ability_action,
        main_projection,
        projection,
        predicted_attack,
        skip_attack,
        snapshot,
        action_candidate.action_kind,
    ) * TURN_WEIGHTS.ability_impact
    resource_value = resource_growth_value
    draw_value = _score_attack_draw_value(player, engine, predicted_attack)
    card_value = _remaining_hand_value(player, engine, ability_action.card_instance_id, snapshot, projection) - skip_hold_value
    risk = _score_action_risk(snapshot, projection, predicted_attack, projected_candidate, ability_action, action_candidate.action_kind, fallback_used)
    total = (
        terminal
        + creature_future_value
        + resource_growth_value
        + immediate_combat_delta
        + end_of_turn_readiness
        + survival_urgency
        + ability_value
        + board_value
        + draw_value
        + card_value
        + future_offense_value
        + board_slot_opportunity_cost
        + haste_immediate_value
        + flying_offense_value
        + flying_coverage_value
        + curve_delay_value
        + role_novelty_value
        + risk
    )
    selection_score = total
    debug_contributions = (
        ("terminal", terminal, 1.0, terminal),
        ("board_value", _score_board_projection_value(projection), TURN_WEIGHTS.board_value, board_value),
        ("resource_value", resource_growth_value, 1.0, resource_value),
        ("card_value", card_value, 1.0, card_value),
        ("draw_value", draw_value, 1.0, draw_value),
        ("future", 0.0 if projected_candidate is None else projected_candidate.future_value, TURN_WEIGHTS.creature_future_value, creature_future_value),
        (
            "growth",
            raw_resource_growth_value,
            TURN_WEIGHTS.resource_growth * BUILDER_AI_WEIGHTS.resource_growth_vs_build if action_candidate.action_kind == "resource" else 0.0,
            resource_growth_value,
        ),
        (
            "combat_delta",
            raw_immediate_combat_delta,
            TURN_WEIGHTS.immediate_combat_delta,
            immediate_combat_delta,
        ),
        (
            "readiness",
            _score_end_of_turn_readiness(projection, predicted_attack, snapshot),
            TURN_WEIGHTS.ready_defense,
            end_of_turn_readiness,
        ),
        (
            "survival_urgency",
            _score_action_survival_urgency(snapshot, projection, predicted_attack, action_candidate.action_kind),
            TURN_WEIGHTS.survival_urgency,
            survival_urgency,
        ),
        ("lethal", predicted_attack.score.lethal_value, 1.0, predicted_attack.score.lethal_value),
        (
            "future_offense",
            future_offense_raw,
            FUTURE_OFFENSE_WEIGHT,
            future_offense_value,
        ),
        (
            "slot_opportunity",
            board_slot_raw,
            BOARD_SLOT_OPPORTUNITY_WEIGHT,
            board_slot_opportunity_cost,
        ),
        (
            "haste_immediate",
            _score_haste_immediate_value(snapshot, projection, predicted_attack, projected_candidate, baseline_attack),
            HASTE_IMMEDIATE_WEIGHT,
            haste_immediate_value,
        ),
        (
            "flying_offense",
            _score_flying_offense_value(snapshot, projection, predicted_attack, projected_candidate),
            FLYING_OFFENSE_WEIGHT,
            flying_offense_value,
        ),
        (
            "flying_coverage",
            flying_coverage_raw,
            FLYING_COVERAGE_WEIGHT,
            flying_coverage_value,
        ),
        (
            "curve_delay",
            curve_delay_raw,
            -CURVE_DELAY_WEIGHT,
            curve_delay_value,
        ),
        (
            "role_novelty",
            role_novelty_raw,
            ROLE_NOVELTY_WEIGHT,
            role_novelty_value,
        ),
        (
            "ability",
            _score_ability_action_value(
                ability_action,
                main_projection,
                projection,
                predicted_attack,
                skip_attack,
                snapshot,
                action_candidate.action_kind,
            ),
            TURN_WEIGHTS.ability_impact,
            ability_value,
        ),
        ("risk", risk / TURN_WEIGHTS.risk_penalty if TURN_WEIGHTS.risk_penalty else risk, TURN_WEIGHTS.risk_penalty, risk),
    )
    score = BuilderTurnScore(
        terminal=round(terminal, 4),
        board_value=round(board_value, 4),
        resource_value=round(resource_value, 4),
        card_value=round(card_value, 4),
        draw_value=round(draw_value, 4),
        creature_future_value=round(creature_future_value, 4),
        resource_growth_value=round(resource_growth_value, 4),
        immediate_combat_delta=round(immediate_combat_delta, 4),
        expected_player_damage=round(predicted_attack.score.player_damage, 4),
        expected_enemy_kill_value=round(predicted_attack.score.enemy_kill_value, 4),
        expected_own_death_value=round(predicted_attack.score.own_death_risk, 4),
        end_of_turn_readiness=round(end_of_turn_readiness, 4),
        survival_urgency=round(survival_urgency, 4),
        lethal_value=round(predicted_attack.score.lethal_value, 4),
        ability_value=round(ability_value, 4),
        risk_adjustment=round(risk, 4),
        expected_enemy_followup_damage=round(expected_enemy_followup_damage, 4),
        enemy_lethal_risk=round(enemy_lethal_risk, 4),
        survival_buffer=round(survival_buffer, 4),
        future_offense_value=round(future_offense_value, 4),
        board_slot_opportunity_cost=round(board_slot_opportunity_cost, 4),
        haste_immediate_value=round(haste_immediate_value, 4),
        flying_offense_value=round(flying_offense_value, 4),
        flying_coverage_value=round(flying_coverage_value, 4),
        curve_delay_value=round(curve_delay_value, 4),
        role_novelty_value=round(role_novelty_value, 4),
        projected_slot_tenure=round(projected_slot_tenure, 4),
        best_build_value_now=round(best_build_value_now, 4),
        best_build_value_r_plus_1=round(best_build_value_r_plus_1, 4),
        best_build_value_r_plus_2=round(best_build_value_r_plus_2, 4),
        best_build_stats_now=best_build_stats_now,
        best_build_stats_r_plus_1=best_build_stats_r_plus_1,
        best_build_stats_r_plus_2=best_build_stats_r_plus_2,
        selection_score=round(selection_score, 4),
        total=round(total, 4),
        baseline_attack_score=round(baseline_attack.score.total, 4),
        projected_attack_score=round(predicted_attack.score.total, 4),
        search_was_exact=predicted_attack.search_metadata.exact_search,
        evaluated_candidate_count=1,
        own_next_attack_damage=round(horizon.own_next_attack_damage, 4),
        own_next_attack_lethal=horizon.own_next_attack_lethal,
        own_next_attackers=tuple(horizon.own_next_attackers),
        enemy_future_blockers=tuple(horizon.enemy_future_blockers),
        enemy_blocker_ready_in_time=horizon.enemy_blocker_ready_in_time,
        turns_to_own_lethal=horizon.turns_to_own_lethal,
        lethal_line_exact=horizon.lethal_line_exact,
        lethal_line_fallback_used=horizon.lethal_line_fallback_used,
        known_enemy_attack_timeline=tuple(horizon.known_enemy_attack_timeline),
        damage_before_coverage_ready=round(horizon.damage_before_coverage_ready, 4),
        second_attack_damage=round(horizon.second_attack_damage, 4),
        second_attack_lethal=horizon.second_attack_lethal,
        coverage_ready_turn=horizon.coverage_ready_turn,
        coverage_prevents_repeated_lethal=horizon.coverage_prevents_repeated_lethal,
        must_hold_as_blocker=horizon.must_hold_as_blocker,
        cumulative_unavoidable_damage=round(horizon.cumulative_unavoidable_damage, 4),
        debug_contributions=tuple((name, round(raw, 4), round(weight, 4), round(contribution, 4)) for name, raw, weight, contribution in debug_contributions),
    )
    return BuilderTurnDecision(
        action_candidate=action_candidate,
        ability_action=ability_action,
        score=score,
        predicted_attack_decision=predicted_attack,
        state_signature=source_signature,
        post_main_signature=_projection_runtime_fingerprint(main_projection, phase=PHASE_BUILDER_ABILITY, ability_used=False),
        post_ability_signature=_projection_runtime_fingerprint(
            projection,
            phase=PHASE_DECLARE_ATTACKERS,
            ability_used=ability_action.action_kind != "skip",
        ),
    )


def _evaluate_attack_cached(
    projection,
    cache: dict[tuple, BuilderAttackDecision],
    *,
    search_budget=TURN_LOOKAHEAD_SEARCH_BUDGET,
) -> BuilderAttackDecision:
    cache_key = _attack_cache_key(projection)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    decision = evaluate_best_builder_attack(
        projection.players[projection.player_id],
        projection,
        search_budget=search_budget,
    )
    cache[cache_key] = decision
    return decision


def _finalize_selected_attack_plan(base_projection, decision: BuilderTurnDecision) -> BuilderTurnDecision:
    """Run the accurate attack search once for the action we will execute.

    Main-action comparison deliberately uses the cheaper lookahead budget.  In
    the past the attack phase then discarded that preview and silently chose a
    different attack.  Finalizing only the selected line keeps main search
    bounded while giving execution one authoritative attack decision to reuse.
    """
    predicted = decision.predicted_attack_decision
    if (
        predicted is not None
        and predicted.search_metadata.search_budget_name == FINAL_DECISION_SEARCH_BUDGET.mode_name
    ):
        return decision

    action_kind = decision.action_candidate.action_kind
    if action_kind == "resource":
        main_projection = project_resource_action(base_projection)
    elif action_kind == "creature":
        main_projection = project_creature_action(base_projection, decision.action_candidate)
    elif action_kind == "pass":
        main_projection = project_pass_action(base_projection)
    else:
        main_projection = base_projection

    final_projection = (
        project_ability_action(main_projection, decision.ability_action)
        if BUILDER_ABILITIES_ENABLED
        else main_projection
    )
    final_attack = evaluate_best_builder_attack(
        final_projection.players[final_projection.player_id],
        final_projection,
        search_budget=FINAL_DECISION_SEARCH_BUDGET,
        debug_output=False,
    )
    if (
        predicted is not None
        and final_attack.candidate == predicted.candidate
        and final_attack.defensive_response == predicted.defensive_response
    ):
        return decision
    return replace(decision, predicted_attack_decision=final_attack)


def _evaluate_horizon_cached(
    projection,
    predicted_attack: BuilderAttackDecision,
    cache: dict[tuple, BuilderHorizonReport],
    *,
    deadline: float,
) -> BuilderHorizonReport:
    cache_key = (
        projection.state_signature,
        tuple(predicted_attack.candidate.attacker_ids),
        tuple(predicted_attack.defensive_response or predicted_attack.score.chosen_block_assignment),
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    report = evaluate_main_action_horizon(projection, predicted_attack, deadline=deadline)
    cache[cache_key] = report
    return report


def _attack_cache_key(projection) -> tuple:
    return (
        projection.player_id,
        projection.enemy_id,
        projection.own_life,
        projection.enemy_life,
        int(getattr(projection, "builder_stalled_turns", 0)),
        projection.available_attacker_ids,
        tuple(_projection_unit_signature(unit) for unit in projection.own_units),
        tuple(_projection_unit_signature(unit) for unit in projection.enemy_units),
    )


def _shortlist_projected_candidates(projected_candidates: list[BuilderProjectedCandidate], snapshot) -> list[BuilderProjectedCandidate]:
    ready_resources = snapshot.own_ready_resources
    limit = 16 if ready_resources <= 4 else 20
    if snapshot.enemy_potential_attacker_count >= 3 or snapshot.enemy_creature_count >= 4:
        limit += 4
    if len(projected_candidates) <= limit:
        return projected_candidates
    selected: dict[tuple, BuilderProjectedCandidate] = {}

    def take(candidates: list[BuilderProjectedCandidate], count: int, reason: str) -> None:
        for projected in candidates[:count]:
            if projected.candidate.key not in selected:
                selected[projected.candidate.key] = BuilderProjectedCandidate(
                    candidate=projected.candidate,
                    static_score=projected.static_score,
                    future_value=projected.future_value,
                    shortlist_reasons=tuple(sorted(set(projected.shortlist_reasons + (reason,)))),
                )

    by_future = sorted(projected_candidates, key=_projected_candidate_sort_key, reverse=True)
    by_damage = sorted(projected_candidates, key=lambda projected: (projected.candidate.sw, projected.future_value, projected.candidate.key), reverse=True)
    by_attack = sorted(projected_candidates, key=lambda projected: (projected.candidate.aw, projected.future_value, projected.candidate.key), reverse=True)
    by_defense = sorted(
        projected_candidates,
        key=lambda projected: (
            projected.candidate.vw + projected.candidate.lw,
            projected.static_score.matchup_defense,
            projected.future_value,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_hybrid = sorted(
        projected_candidates,
        key=lambda projected: (
            min(projected.candidate.aw, projected.candidate.vw, projected.candidate.sw),
            projected.future_value,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_haste = sorted(
        [projected for projected in projected_candidates if projected.candidate.has_haste],
        key=_projected_candidate_sort_key,
        reverse=True,
    )
    by_haste_damage = sorted(
        [projected for projected in projected_candidates if projected.candidate.has_haste and projected.candidate.sw > 0],
        key=lambda projected: (
            projected.candidate.sw,
            projected.static_score.immediate_pressure,
            projected.candidate.aw,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_flying = sorted(
        [projected for projected in projected_candidates if projected.candidate.has_ability(Ability.FLYING)],
        key=_projected_candidate_sort_key,
        reverse=True,
    )
    by_flying_damage = sorted(
        [projected for projected in projected_candidates if projected.candidate.has_ability(Ability.FLYING) and projected.candidate.sw > 0],
        key=lambda projected: (
            projected.candidate.sw,
            projected.candidate.vw,
            projected.static_score.damage_delivery_probability,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_immediate_blocker = sorted(
        [
            projected
            for projected in projected_candidates
            if projected.candidate.has_haste and projected.candidate.vw > 0
        ],
        key=lambda projected: (
            max(
                projected.static_score.block_win_probability,
                projected.static_score.blocker_survival_probability,
            ),
            projected.static_score.immediate_prevented_damage,
            projected.static_score.attacker_kill_probability,
            projected.static_score.life_breakpoint,
            projected.static_score.matchup_defense,
            projected.candidate.vw,
            projected.candidate.lw,
            -projected.candidate.cost,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_block_win = sorted(
        [projected for projected in projected_candidates if projected.candidate.vw > 0],
        key=lambda projected: (
            projected.static_score.block_win_probability,
            projected.static_score.blocker_survival_probability,
            projected.static_score.life_breakpoint,
            projected.static_score.matchup_defense,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_kill_and_survive = sorted(
        [projected for projected in projected_candidates if projected.candidate.vw > 0 and projected.candidate.sw > 0],
        key=lambda projected: (
            projected.static_score.attacker_kill_probability + projected.static_score.blocker_survival_probability,
            projected.static_score.repeated_block_value,
            projected.static_score.matchup_defense,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_persistent_blocker = sorted(
        [projected for projected in projected_candidates if projected.candidate.vw > 0],
        key=lambda projected: (
            projected.static_score.repeated_block_value,
            projected.static_score.blocker_survival_probability,
            projected.static_score.attacker_kill_probability,
            projected.static_score.life_breakpoint,
            projected.static_score.matchup_defense,
            projected.candidate.vw,
            projected.candidate.lw,
            projected.future_value,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_width_control = sorted(
        [projected for projected in projected_candidates if projected.candidate.vw > 0 and projected.candidate.sw > 0],
        key=lambda projected: (
            projected.static_score.repeated_prevented_damage,
            projected.static_score.attacker_kill_probability,
            projected.static_score.blocker_survival_probability,
            projected.candidate.vw,
            projected.candidate.sw,
            -projected.candidate.cost,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_face_damage = sorted(
        projected_candidates,
        key=lambda projected: (
            projected.static_score.immediate_pressure,
            projected.static_score.expected_player_damage,
            projected.static_score.matchup_offense,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_offense_access = sorted(
        projected_candidates,
        key=lambda projected: (
            projected.static_score.attack_access_probability,
            projected.static_score.damage_delivery_probability,
            projected.static_score.attacker_kill_probability,
            -projected.static_score.stranded_damage,
            projected.candidate.aw,
            projected.candidate.sw,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_damage_breakpoint = sorted(
        [projected for projected in projected_candidates if projected.candidate.sw > 0],
        key=lambda projected: (
            projected.static_score.damage_delivery_probability,
            -projected.static_score.stranded_damage,
            -projected.static_score.overkill_damage,
            -projected.candidate.cost,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_life_breakpoint = sorted(
        [projected for projected in projected_candidates if projected.candidate.vw > 0 or projected.candidate.lw > 1],
        key=lambda projected: (
            projected.static_score.life_breakpoint,
            projected.static_score.blocker_survival_probability,
            -projected.candidate.cost,
            projected.static_score.matchup_defense,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_highest_haste_defense = sorted(
        [
            projected
            for projected in projected_candidates
            if projected.candidate.has_haste and projected.candidate.vw > 0
        ],
        key=lambda projected: (
            max(
                projected.static_score.block_win_probability,
                projected.static_score.blocker_survival_probability,
            ),
            projected.static_score.immediate_prevented_damage,
            projected.static_score.repeated_block_value,
            projected.static_score.matchup_defense,
            projected.candidate.vw,
            projected.candidate.lw,
            projected.candidate.key,
        ),
        reverse=True,
    )
    by_terminal = sorted(
        [
            projected for projected in projected_candidates
            if projected.candidate.has_haste and projected.static_score.immediate_pressure > 0.0
        ],
        key=lambda projected: (
            projected.static_score.immediate_pressure >= snapshot.enemy_life,
            projected.static_score.immediate_pressure,
            projected.static_score.expected_player_damage,
            projected.static_score.matchup_offense,
            projected.candidate.key,
        ),
        reverse=True,
    )

    # Insert tactically mandatory shapes first.  The insertion order is also the
    # evaluation order when a turn reaches its time budget.  Under immediate
    # pressure, persistent Haste blockers must be evaluated before glass-cannon
    # Haste bodies; otherwise a deadline can leave the planner with only
    # offensive candidates even though defensive candidates were generated.
    must_answer_now = (
        snapshot.enemy_potential_attacker_count > 0
        and snapshot.own_life <= max(4, snapshot.enemy_total_sw)
    )
    if must_answer_now:
        take(by_immediate_blocker, 4, "mandatory_emergency_haste_blocker")
        take(by_highest_haste_defense, 2, "mandatory_emergency_haste_defense")
    take(by_haste_damage, 2, "mandatory_haste_damage")
    take(by_flying_damage, 2 if snapshot.enemy_flying_count > 0 else 1, "mandatory_flying_damage")
    take(by_terminal, 3, "mandatory_terminal")
    take(by_immediate_blocker, 3 if snapshot.enemy_potential_attacker_count > 0 else 1, "mandatory_immediate_blocker")
    take(by_block_win, 2 if snapshot.enemy_potential_attacker_count > 0 else 1, "mandatory_highest_block_win")
    take(by_kill_and_survive, 2 if snapshot.enemy_potential_attacker_count > 0 else 1, "mandatory_kill_and_survive")
    take(by_damage_breakpoint, 2, "mandatory_damage_breakpoint")
    take(by_face_damage, 2, "mandatory_face_damage")
    take(by_offense_access, 2, "mandatory_offense_access")
    take(by_persistent_blocker, 3 if snapshot.enemy_potential_attacker_count > 0 else 1, "mandatory_persistent_blocker")
    take(by_width_control, 2 if snapshot.enemy_creature_count > 1 else 1, "mandatory_anti_width")
    take(by_life_breakpoint, 2 if snapshot.enemy_potential_attacker_count > 0 else 1, "mandatory_life_breakpoint")
    take(by_highest_haste_defense, 2 if snapshot.enemy_potential_attacker_count > 0 else 1, "mandatory_haste_defense")
    take(by_future, 8 if ready_resources <= 4 else 12, "future")
    take(by_damage, 4 if ready_resources <= 4 else 6, "damage")
    take(by_attack, 4 if ready_resources <= 4 else 5, "attack")
    take(by_defense, 4 if ready_resources <= 4 else 6, "defense")
    take(by_hybrid, 3 if ready_resources <= 4 else 4, "hybrid")
    take(by_haste, 4, "haste")
    take(by_flying, 4, "flying")
    return list(selected.values())[:limit]


def _score_end_of_turn_readiness(projection, predicted_attack: BuilderAttackDecision, snapshot) -> float:
    attacked_ids = set(predicted_attack.candidate.attacker_ids)
    enemy_pressure = max(0.6, snapshot.enemy_potential_attacker_count * 0.32 + snapshot.enemy_total_sw * 0.08 + snapshot.enemy_flying_count * 0.25)
    projected_counter_attackers = _projected_counterattack_units(projection, predicted_attack)
    total = 0.0
    for unit in projection.own_units:
        if unit.unit_id in attacked_ids:
            ready_for_defense = unit.has_ability(Ability.VIGILANT) or unit.has_ability(Ability.VIGILANCE)
        else:
            ready_for_defense = not unit.tapped
        block_quality = _projected_block_quality(unit, projected_counter_attackers)
        legally_relevant_blocker = block_quality > 0.0
        if ready_for_defense and legally_relevant_blocker:
            total += estimate_creature_board_value(unit) * 0.05 * enemy_pressure * block_quality
        if ready_for_defense and (unit.has_ability(Ability.VIGILANT) or unit.has_ability(Ability.VIGILANCE)):
            total += 0.22
        if unit.unit_id == projection.hypothetical_unit_id and not unit.tapped and legally_relevant_blocker:
            total += (0.18 + unit.vw * 0.05 + unit.current_hp * 0.03) * block_quality
        if unit.unit_id == projection.hypothetical_unit_id and unit.tapped:
            total -= TAPPED_NEW_BODY_PENALTY
    return total


def _score_future_offense_value(snapshot, projection, predicted_attack, projected_candidate, horizon: BuilderHorizonReport) -> float:
    if projected_candidate is None:
        return 0.0
    if horizon.own_next_attack_lethal:
        return NEXT_TURN_LETHAL_BONUS + horizon.own_next_attack_damage
    if horizon.own_next_attack_damage <= 0.0:
        return -2.4 if projected_candidate.candidate.sw <= 0 else -0.8
    pressure_bonus = 0.0
    if projection.hypothetical_unit_id in horizon.own_next_attackers:
        pressure_bonus += 0.55
    if not horizon.enemy_blocker_ready_in_time:
        pressure_bonus += 0.35
    return horizon.own_next_attack_damage + pressure_bonus


def _score_board_slot_opportunity_cost(snapshot, projection, predicted_attack, projected_candidate, cap_context, horizon: BuilderHorizonReport) -> float:
    if projected_candidate is None or snapshot.own_creature_count != BUILDER_CREATURE_CAP - 1:
        return 0.0
    if predicted_attack.score.guaranteed_player_damage >= projection.enemy_life > 0:
        return 0.0
    if horizon.own_next_attack_lethal or horizon.coverage_prevents_repeated_lethal:
        return 0.0
    pressure = _base_survival_pressure(snapshot)
    safe_fifth_slot_penalty = 0.0
    if (
        pressure <= 2.0
        and snapshot.enemy_total_sw <= 1
        and predicted_attack.score.counter_lethal_risk <= 0.0
    ):
        safe_fifth_slot_penalty = projected_candidate.future_value * 0.6
    superior_future_gap = _estimate_future_slot_advantage(snapshot, projection, projected_candidate)
    if superior_future_gap <= 0.0:
        return -safe_fifth_slot_penalty
    release_probability = 0.0
    if cap_context.weakest_unit_value <= 1.0:
        release_probability += 0.3
    if projected_candidate.candidate.sw > 0 and projected_candidate.candidate.lw <= 2:
        release_probability += 0.18
    if predicted_attack.score.enemy_kill_value > 0.0 or snapshot.enemy_potential_attacker_count > 0:
        release_probability += 0.12
    wait_probability = max(0.08, 0.52 - pressure * 0.05)
    if predicted_attack.score.counter_lethal_risk > 0.0:
        wait_probability *= 0.2
    discounted_gap = superior_future_gap * wait_probability * max(0.15, 1.0 - min(0.8, release_probability))
    if (
        cap_context.at_cap
        and pressure <= 3.0
        and predicted_attack.score.counter_lethal_risk <= 0.0
        and predicted_attack.score.guaranteed_player_damage < max(4.0, snapshot.enemy_life * 0.75)
    ):
        discounted_gap += cap_context.replacement_value * 0.7
        if (
            projected_candidate.candidate.aw == 0
            and projected_candidate.candidate.sw <= 2
            and projected_candidate.candidate.vw <= 2
        ):
            discounted_gap += projected_candidate.future_value * max(0.0, 0.32 - pressure * 0.06)
    if pressure <= 4.0 and horizon.own_next_attack_damage < max(4.0, snapshot.enemy_life * 0.5) and horizon.second_attack_damage <= 1.0:
        discounted_gap += projected_candidate.future_value * max(0.0, 0.65 - pressure * 0.07)
    return -(discounted_gap + safe_fifth_slot_penalty)


def _score_haste_immediate_value(snapshot, projection, predicted_attack, projected_candidate, baseline_attack) -> float:
    if projected_candidate is None or not projected_candidate.candidate.has_haste:
        return 0.0
    new_unit_id = projection.hypothetical_unit_id
    value = 0.0
    if new_unit_id is not None and new_unit_id in predicted_attack.candidate.attacker_ids:
        marginal_player_damage = max(
            0.0,
            predicted_attack.score.player_damage - baseline_attack.score.player_damage,
        )
        value += marginal_player_damage * 0.73
        if predicted_attack.score.guaranteed_player_damage >= projection.enemy_life > 0:
            value += 2.2
    return value


def _score_flying_offense_value(snapshot, projection, predicted_attack, projected_candidate) -> float:
    if projected_candidate is None or not projected_candidate.candidate.has_ability(Ability.FLYING):
        return 0.0
    enemy_flying_blockers = sum(1 for unit in projection.enemy_units if unit.has_ability(Ability.FLYING))
    value = projected_candidate.candidate.sw * (0.24 if enemy_flying_blockers == 0 else 0.08)
    if predicted_attack.candidate.attacker_ids and projection.hypothetical_unit_id in predicted_attack.candidate.attacker_ids:
        value += predicted_attack.score.player_damage * 0.2
    return value


def _score_flying_coverage_value(snapshot, projection, predicted_attack, projected_candidate, horizon: BuilderHorizonReport) -> float:
    value = 0.0
    coverage_quality = 1.0
    flying_candidate = projected_candidate is not None and projected_candidate.candidate.has_ability(Ability.FLYING)
    if flying_candidate:
        candidate = projected_candidate.candidate
        static = projected_candidate.static_score
        coverage_quality = (
            max(static.block_win_probability, static.blocker_survival_probability)
            if candidate.vw > 0
            else 0.0
        )
    if horizon.coverage_prevents_repeated_lethal:
        value += REPEATED_LETHAL_PREVENTION_BONUS * coverage_quality
        if flying_candidate and coverage_quality > 0.0:
            # Once flying coverage exists, rank the body by whether it can keep
            # providing that coverage.  Damage is only a small tie-breaker; it
            # must not turn a fragile one-shot chump into the preferred answer.
            body_value = (
                static.matchup_defense * 2.0
                + static.blocker_survival_probability * 12.0
                + static.repeated_block_value * 2.0
                + candidate.vw
                + max(0, candidate.lw - 1) * 1.5
                + candidate.sw * 0.5
            )
            value += body_value * coverage_quality
    if horizon.coverage_ready_turn == 1:
        unavoidable_second_damage = max(0.0, horizon.cumulative_unavoidable_damage - horizon.damage_before_coverage_ready)
    else:
        unavoidable_second_damage = horizon.second_attack_damage
    prevented_second_damage = max(0.0, horizon.second_attack_damage - unavoidable_second_damage)
    value += prevented_second_damage * 1.6 * coverage_quality
    if horizon.coverage_ready_turn is None and horizon.second_attack_damage > 0.0:
        value -= horizon.second_attack_damage * 0.4
    if flying_candidate:
        if horizon.second_attack_damage <= 0.0 and not horizon.coverage_prevents_repeated_lethal:
            value *= 0.35
        elif horizon.coverage_ready_turn == 1 and coverage_quality > 0.0:
            value += 0.45 * coverage_quality
    return value


def _base_survival_pressure(snapshot) -> float:
    pressure = (
        max(0.0, snapshot.enemy_total_sw - snapshot.own_total_current_hp * 0.25)
        + snapshot.enemy_potential_attacker_count * 0.9
        + snapshot.enemy_flying_count * 0.8
        + max(0.0, -snapshot.board_value_difference) * 0.35
    )
    if not snapshot.own_has_board and snapshot.enemy_has_board:
        pressure += 2.4
    pressure += max(0.0, 8 - snapshot.own_life) * 0.8
    return pressure


def _estimate_future_slot_advantage(snapshot, projection, projected_candidate) -> float:
    future_budget = snapshot.own_ready_resources + 1
    if future_budget <= snapshot.own_ready_resources:
        return 0.0
    own_units = tuple(unit for unit in projection.own_units if unit.unit_id != projection.hypothetical_unit_id)
    cache_key = (
        snapshot,
        future_budget,
        tuple(_projection_unit_signature(unit) for unit in own_units),
        tuple(_projection_unit_signature(unit) for unit in projection.enemy_units),
    )
    cached = _FUTURE_SLOT_VALUE_CACHE.get(cache_key)
    if cached is None:
        legal = [
            candidate
            for candidate in generate_builder_creature_candidates(snapshot, future_budget)
            if is_legal_builder_candidate(candidate, future_budget)
        ]
        legal = select_builder_creature_search_frontier(
            legal,
            snapshot,
            limit=FRONTIER_BUILD_SCORING_LIMIT,
        )
        best_future_value = 0.0
        for candidate in legal:
            static_score = score_builder_creature_candidate(
                candidate,
                snapshot,
                available_resources=future_budget,
                enemy_creatures=list(projection.enemy_units),
                own_creatures=list(own_units),
            )
            best_future_value = max(best_future_value, extract_candidate_future_value(static_score, candidate, snapshot))
        cached = best_future_value
        store_bounded_cache_entry(_FUTURE_SLOT_VALUE_CACHE, cache_key, cached, max_entries=2048)
    return max(0.0, cached - projected_candidate.future_value)


def _best_frontier_build_value(
    snapshot,
    projection,
    budget: int,
    required_ability: Ability | None = None,
    *,
    deadline: float | None = None,
) -> tuple[float, str]:
    if budget <= 0:
        return 0.0, "-"
    cache_key = (
        snapshot,
        budget,
        getattr(required_ability, "value", "-"),
        tuple(_projection_unit_signature(unit) for unit in projection.own_units),
        tuple(_projection_unit_signature(unit) for unit in projection.enemy_units),
    )
    cached = _BUDGET_FRONTIER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    adjusted_snapshot = replace(
        snapshot,
        own_total_resources=budget,
        own_ready_resources=budget,
        resource_difference=budget - snapshot.enemy_total_resources,
    )
    legal = [
        candidate
        for candidate in generate_builder_creature_candidates(adjusted_snapshot, budget)
        if is_legal_builder_candidate(candidate, budget)
        and (required_ability is None or candidate.has_ability(required_ability))
    ]
    legal = select_builder_creature_search_frontier(
        legal,
        adjusted_snapshot,
        limit=FRONTIER_BUILD_SCORING_LIMIT,
    )
    best_value = 0.0
    best_stats = "-"
    for candidate in legal:
        static_score = score_builder_creature_candidate(
            candidate,
            adjusted_snapshot,
            available_resources=budget,
            enemy_creatures=list(projection.enemy_units),
            own_creatures=list(projection.own_units),
        )
        future_value = extract_candidate_future_value(static_score, candidate, adjusted_snapshot)
        if future_value > best_value:
            best_value = future_value
            best_stats = f"{candidate.aw}/{candidate.vw}/{candidate.sw}/{candidate.lw}/{getattr(candidate.builder_ability, 'value', '-').lower()}"
        if builder_search_should_stop(deadline):
            break
    result = (round(best_value, 4), best_stats)
    store_bounded_cache_entry(_BUDGET_FRONTIER_CACHE, cache_key, result, max_entries=2048)
    return result


def _build_frontier_context(snapshot, projection, *, deadline: float | None = None) -> tuple[float, str, float, str, float, str]:
    best_now, best_now_stats = _best_frontier_build_value(
        snapshot,
        projection,
        projection.own_total_resources,
        deadline=deadline,
    )
    best_r1, best_r1_stats = _best_frontier_build_value(
        snapshot,
        projection,
        min(10, projection.own_total_resources + 1),
        deadline=deadline,
    )
    best_r2, best_r2_stats = _best_frontier_build_value(
        snapshot,
        projection,
        min(10, projection.own_total_resources + 2),
        deadline=deadline,
    )
    return (
        best_now,
        best_now_stats,
        best_r1,
        best_r1_stats,
        best_r2,
        best_r2_stats,
    )


def _estimate_projected_slot_tenure(snapshot, projection, predicted_attack, projected_candidate) -> float:
    if projected_candidate is None:
        return 0.0
    candidate = projected_candidate.candidate
    tenure = 1.0
    if candidate.aw == 0 and candidate.sw <= 1:
        tenure += 1.2
    if candidate.vw >= 1 or candidate.lw >= 3:
        tenure += 0.8
    if snapshot.own_creature_count >= BUILDER_CREATURE_CAP - 1:
        tenure += 0.7
    if projection.hypothetical_unit_id in predicted_attack.candidate.attacker_ids and predicted_attack.score.enemy_kill_value > 0.0:
        tenure -= 0.8
    if candidate.has_ability(Ability.FLYING):
        tenure -= 0.3
    return max(0.0, tenure)


def _score_role_novelty(snapshot, projection, predicted_attack, projected_candidate) -> float:
    if projected_candidate is None:
        return 0.0
    candidate = projected_candidate.candidate
    hypothetical_unit_id = projection.hypothetical_unit_id
    existing_units = [
        unit
        for unit in projection.own_units
        if hypothetical_unit_id is None or unit.unit_id != hypothetical_unit_id
    ]
    similar_units = 0
    own_flying = sum(1 for unit in existing_units if unit.has_ability(Ability.FLYING))
    own_zero_attack = sum(1 for unit in existing_units if unit.aw == 0 and unit.sw <= 1)
    for unit in existing_units:
        same_ability = candidate.builder_ability is not None and unit.has_ability(candidate.builder_ability)
        similar_stats = abs(unit.aw - candidate.aw) <= 1 and abs(unit.vw - candidate.vw) <= 1 and abs(unit.sw - candidate.sw) <= 1
        if same_ability and similar_stats:
            similar_units += 1
    novelty = 0.0
    if candidate.has_ability(Ability.FLYING) and own_flying == 0:
        novelty += 1.8 if snapshot.enemy_flying_count > 0 or snapshot.enemy_total_resources >= 5 else 0.8
    if candidate.sw >= 2 and predicted_attack.score.guaranteed_player_damage > 0.0:
        novelty += 0.5
    if candidate.aw == 0 and candidate.sw == 0 and snapshot.enemy_potential_attacker_count == 0:
        novelty -= 1.2
    if candidate.has_haste and predicted_attack.score.player_damage <= 0.0 and candidate.sw == 0:
        novelty -= 1.4
        if (
            snapshot.own_life >= 10
            and predicted_attack.score.counter_lethal_risk <= 0.0
            and predicted_attack.score.projected_counter_damage < max(2.0, snapshot.own_life - 4.0)
        ):
            novelty -= 4.0
    if own_zero_attack >= 2 and candidate.aw == 0 and candidate.sw <= 1:
        novelty -= 0.8
    novelty -= similar_units * 0.45
    return novelty


def _score_curve_delay(
    snapshot,
    projection,
    baseline_attack,
    predicted_attack,
    projected_candidate,
    best_build_value_now: float,
    best_build_value_r_plus_1: float,
    best_build_value_r_plus_2: float,
) -> float:
    if projected_candidate is None:
        return 0.0
    candidate = projected_candidate.candidate
    tactical_impact = (
        max(0.0, predicted_attack.score.guaranteed_player_damage)
        + max(0.0, projected_candidate.static_score.matchup_defense)
        + max(0.0, projected_candidate.static_score.immediate_pressure)
    )
    must_act_now = (
        predicted_attack.score.counter_lethal_risk > 0.0
        or predicted_attack.score.projected_counter_damage >= max(1.0, projection.own_life - 1.0)
    )
    if must_act_now and tactical_impact > 0.0:
        return 0.0
    future_gap = max(0.0, best_build_value_r_plus_1 - max(projected_candidate.future_value, best_build_value_now * 0.7))
    future_gap += max(0.0, best_build_value_r_plus_2 - best_build_value_r_plus_1) * 0.35
    if snapshot.own_creature_count >= BUILDER_CREATURE_CAP - 1:
        future_gap += _estimate_projected_slot_tenure(snapshot, projection, predicted_attack, projected_candidate) * 0.55
    if candidate.aw == 0 and candidate.sw == 0:
        future_gap += 1.2
    elif candidate.aw == 0 and candidate.sw <= 1 and predicted_attack.score.player_damage <= 0.0:
        future_gap += 0.8
    safe_state = predicted_attack.score.counter_lethal_risk <= 0.0 and predicted_attack.score.projected_counter_damage < max(2.0, projection.own_life - 3.0)
    if safe_state:
        future_gap *= 1.1
        new_unit_attacks = projection.hypothetical_unit_id in predicted_attack.candidate.attacker_ids
        if candidate.has_haste and not new_unit_attacks and candidate.aw == 0 and candidate.sw <= 1:
            # Haste may still be a useful emergency blocker, but paying for it on
            # a tiny passive body is poor curve development while life is safe.
            future_gap += 0.9
    dampener = max(0.15, 1.0 - min(0.82, tactical_impact * 0.22))
    curve_delay = future_gap * dampener
    safe_without_build = (
        baseline_attack.score.counter_lethal_risk <= 0.0
        and snapshot.own_life - baseline_attack.score.projected_counter_damage >= 5.0
    )
    immediate_lethal = predicted_attack.score.guaranteed_player_damage >= projection.enemy_life > 0
    if safe_without_build and not immediate_lethal and snapshot.own_total_resources < RESOURCE_FOUNDATION_TARGET:
        missing_foundation = RESOURCE_FOUNDATION_TARGET - snapshot.own_total_resources
        marginal_player_damage = max(
            0.0,
            predicted_attack.score.player_damage - baseline_attack.score.player_damage,
        )
        development_delay = missing_foundation * SAFE_FOUNDATION_BUILD_DELAY
        development_delay -= min(0.8, marginal_player_damage * 0.4)
        curve_delay += max(0.0, development_delay)
    return curve_delay


def _score_immediate_combat_delta(snapshot, projection, baseline_attack, predicted_attack, projected_candidate) -> float:
    value = predicted_attack.score.total - baseline_attack.score.total
    if projected_candidate is None:
        return value
    new_unit_attacks = projection.hypothetical_unit_id in predicted_attack.candidate.attacker_ids
    prevented_counter_damage = max(
        0.0,
        baseline_attack.score.projected_counter_damage - predicted_attack.score.projected_counter_damage,
    )
    safe_without_new_body = (
        baseline_attack.score.counter_lethal_risk <= 0.0
        and snapshot.own_life - baseline_attack.score.projected_counter_damage >= 5.0
    )
    if safe_without_new_body and not new_unit_attacks and prevented_counter_damage > 0.0:
        # Counter damage is already represented by survival urgency. Discounting
        # its second appearance prevents safe chump blockers from beating a
        # permanent resource upgrade solely by absorbing optional chip damage.
        value -= prevented_counter_damage * SAFE_COUNTER_DAMAGE_PREVENTION_DISCOUNT
    return value


def evaluate_builder_next_main_value(projection) -> tuple[float, str, str]:
    player = projection.players[projection.player_id]
    snapshot = build_builder_snapshot(player, projection)
    cap_context = compute_builder_cap_context(
        player,
        projection,
        creature_cap=BUILDER_CREATURE_CAP,
        resource_budget=projection.own_total_resources,
    )
    best_now, best_now_stats = _best_frontier_build_value(snapshot, projection, projection.own_total_resources)
    best_flying_now, best_flying_stats = _best_frontier_build_value(snapshot, projection, projection.own_total_resources, Ability.FLYING)
    best_r1, _ = _best_frontier_build_value(snapshot, projection, min(10, projection.own_total_resources + 1))
    best_r2, _ = _best_frontier_build_value(snapshot, projection, min(10, projection.own_total_resources + 2))

    best_value = -PASS_ACTION_PENALTY
    best_action = "pass"
    best_stats = "-"
    must_answer_now = snapshot.enemy_potential_attacker_count > 0 and snapshot.own_life <= max(4, snapshot.enemy_total_sw)

    if len(projection.own_units) < BUILDER_CREATURE_CAP:
        build_value = best_now
        build_stats = best_now_stats
        if snapshot.enemy_flying_count > 0 and not any(unit.has_ability(Ability.FLYING) for unit in projection.own_units):
            if best_flying_now > 0.0:
                build_value = best_flying_now + 5.0
                build_stats = best_flying_stats
            else:
                build_value -= 2.5
        if build_value > best_value:
            best_value = build_value
            best_action = "creature"
            best_stats = build_stats

    if projection.own_total_resources < 10:
        curve_value = max(0.0, best_r1 - best_now) + max(0.0, best_r2 - best_r1) * 0.35
        resource_value = curve_value + max(0.0, 1.4 - projection.own_total_resources * 0.18)
        if cap_context.at_cap:
            resource_value -= cap_context.replacement_value * 1.25 + cap_context.cap_pressure
        if must_answer_now:
            resource_value -= 1.8
        if resource_value > best_value:
            best_value = resource_value
            best_action = "resource"
            best_stats = "-"
    return round(best_value, 4), best_action, best_stats


def _score_action_survival_urgency(snapshot, projection, predicted_attack, action_kind: str) -> float:
    pressure = _base_survival_pressure(snapshot)
    expected_damage = predicted_attack.score.projected_counter_damage
    lethal_risk = predicted_attack.score.counter_lethal_risk
    life_after = projection.own_life - expected_damage
    projected_counter_attackers = _projected_counterattack_units(projection, predicted_attack)
    legal_blockers = sum(
        1
        for unit in projection.own_units
        if not unit.tapped and _can_affect_projected_counterattack(unit, projected_counter_attackers)
    )
    if expected_damage <= 0.0 and lethal_risk <= 0.0:
        stability = legal_blockers * 0.12 + max(0.0, life_after - 2.0) * 0.05
        if action_kind == "pass":
            stability -= 0.25
        return stability
    life_buffer = max(0.0, life_after)
    damage_penalty = expected_damage * (0.4 + max(0.0, 4.0 - life_buffer) * 0.11)
    lethal_penalty = lethal_risk * (9.0 + max(0.0, 3.0 - life_buffer) * 1.6)
    blocker_relief = legal_blockers * 0.14
    resource_tax = 0.2 if action_kind == "resource" and expected_damage > 0.0 and life_buffer > 2.0 else 0.6 if action_kind == "pass" else 0.0
    return blocker_relief - damage_penalty - lethal_penalty - resource_tax - pressure * 0.02 + min(1.2, life_buffer * 0.08)


def _score_board_projection_value(projection) -> float:
    own = sum(estimate_creature_board_value(unit) for unit in projection.own_units)
    enemy = sum(estimate_creature_board_value(unit) for unit in projection.enemy_units)
    return own - enemy


def _score_attack_draw_value(player, engine, predicted_attack: BuilderAttackDecision) -> float:
    if not BUILDER_ABILITIES_ENABLED:
        return 0.0
    if not predicted_attack.candidate.attacker_ids:
        return 0.0
    if player.player_id == engine.starting_player_id and player.turns_started <= 1:
        return 0.0
    attack_quality = predicted_attack.score.enemy_kill_value + predicted_attack.score.player_damage - predicted_attack.score.own_death_risk
    quality_factor = 1.0 if attack_quality >= 0.5 else 0.55 if attack_quality >= -0.25 else 0.15
    return (DRAW_REWARD_VALUE + max(0.0, 0.45 - len(player.hand) * 0.08)) * quality_factor


def _remaining_hand_value(player, engine, used_card_instance_id: int | None, snapshot, projection) -> float:
    if not BUILDER_ABILITIES_ENABLED:
        return 0.0
    total = 0.0
    for card in player.hand:
        if used_card_instance_id is not None and card.instance_id == used_card_instance_id:
            continue
        ability = engine.get_builder_card_ability(card)
        if ability is None:
            continue
        total += _estimate_card_hold_value(ability, snapshot, projection)
    return total * CARD_HOLD_WEIGHT


def _estimate_card_hold_value(ability: Ability, snapshot, projection) -> float:
    own_damaged = sum(1 for unit in projection.own_units if unit.current_hp < unit.lw)
    own_big_bodies = sum(1 for unit in projection.own_units if unit.sw >= 2)
    enemy_big_bodies = sum(1 for unit in projection.enemy_units if unit.current_hp >= 3)
    if ability == Ability.FLYING:
        return 1.35 if snapshot.enemy_flying_count == 0 else 0.95
    if ability == Ability.HASTE:
        return 1.05 if projection.hypothetical_unit_id is not None else 0.75
    if ability == Ability.PROVOKE:
        return 1.15 if snapshot.enemy_creature_count > 0 else 0.55
    if ability == Ability.VIGILANCE:
        return 0.95 if own_big_bodies > 0 else 1.25
    if ability == Ability.LIFELINK:
        return 1.05 if own_damaged > 0 else 0.7
    if ability == Ability.DEATHTOUCH:
        return 1.0 if enemy_big_bodies > 0 else 0.65
    if ability == Ability.TRAMPLE:
        return 1.05 if own_big_bodies > 0 else 0.65
    return 0.6


def _score_ability_action_value(ability_action, main_projection, projection, predicted_attack, skip_attack, snapshot, main_action_kind: str) -> float:
    if not BUILDER_ABILITIES_ENABLED:
        return 0.0
    if ability_action.action_kind == "skip":
        return 0.0
    target = projection.get_unit_by_id(ability_action.target_id or -1)
    attack_delta = predicted_attack.score.total - skip_attack.score.total
    if ability_action.action_kind == "grant_ability" and ability_action.card_ability is not None and target is not None:
        return _score_granted_ability_shell(ability_action.card_ability, target, predicted_attack, skip_attack, snapshot, attack_delta)
    if ability_action.action_kind == "add_stat" and target is not None and ability_action.selected_stat is not None:
        base = estimate_creature_board_value(target) * 0.08
        if ability_action.selected_stat == "aw":
            base += target.sw * 0.14
        elif ability_action.selected_stat == "vw":
            base += target.lw * 0.1 + 0.55
        elif ability_action.selected_stat == "sw":
            base += max(0.25, target.aw * 0.18) + 0.3
        elif ability_action.selected_stat == "lw":
            base += 0.6 + (0.35 if target.current_hp <= 2 else 0.0)
        if target.aw == 0 and target.vw == 0 and target.sw == 0 and target.lw <= 1:
            base -= 2.0
        if (
            predicted_attack.score.total <= skip_attack.score.total + 0.05
            and snapshot.enemy_creature_count == 0
            and target.aw + target.vw + target.sw <= 1
            and target.lw <= 2
        ):
            base -= 1.4
        if main_action_kind == "pass":
            base -= 0.15
        if attack_delta > 0.15:
            base += min(1.0, attack_delta * 0.24)
        return base
    if ability_action.action_kind == "deal_damage":
        return _score_damage_mode_action(main_projection, projection, ability_action, predicted_attack, skip_attack)
    return 0.0


def _score_granted_ability_shell(ability: Ability, target, predicted_attack, skip_attack, snapshot, attack_delta: float) -> float:
    if ability == Ability.FLYING:
        score = target.sw * 0.28 + target.aw * 0.12 + (0.4 if snapshot.enemy_flying_count == 0 else 0.1)
        if target.unit_id in predicted_attack.candidate.attacker_ids:
            score += min(1.4, max(0.0, attack_delta) * 0.35)
        if target.sw <= 1:
            score -= 0.35
        return score
    if ability == Ability.HASTE:
        attacks_now = target.unit_id in predicted_attack.candidate.attacker_ids
        return (1.4 if attacks_now else 0.0) + target.sw * 0.25
    if ability == Ability.VIGILANCE:
        attacks_now = target.unit_id in predicted_attack.candidate.attacker_ids
        defensive_body = target.vw + target.current_hp
        score = defensive_body * 0.12 + (0.55 if attacks_now else 0.0)
        return score
    if ability == Ability.LIFELINK:
        return target.sw * 0.22 + max(0, target.lw - target.current_hp) * 0.35 + target.lw * 0.05
    if ability == Ability.DEATHTOUCH:
        score = max(target.sw, 1) * 0.28 + target.aw * 0.08 + snapshot.enemy_board_value * 0.03
        if attack_delta > 0.1:
            score += min(0.8, attack_delta * 0.22)
        return score
    if ability == Ability.TRAMPLE:
        score = target.sw * 0.28 + target.aw * 0.08
        if attack_delta > 0.1:
            score += min(0.85, attack_delta * 0.24)
        return score
    if ability == Ability.PROVOKE:
        attacks_now = target.unit_id in predicted_attack.candidate.attacker_ids
        score = target.sw * 0.16 + snapshot.enemy_creature_count * 0.08
        score += min(1.8, max(0.0, attack_delta) * 0.42)
        if attacks_now and predicted_attack.score.player_damage > skip_attack.score.player_damage:
            score += 0.45
        forced_target = next(
            (blocker_id for attacker_id, blocker_id in predicted_attack.candidate.enraged_targets if attacker_id == target.unit_id),
            None,
        )
        if forced_target is not None:
            skipped_blockers = {blocker_id for _, blocker_id in skip_attack.score.chosen_block_assignment}
            if forced_target in skipped_blockers:
                score += 1.2
            freed_damage = predicted_attack.score.player_damage - skip_attack.score.player_damage
            if freed_damage > 0.5:
                score += min(1.2, freed_damage * 0.32)
            kill_delta = predicted_attack.score.enemy_kill_value - skip_attack.score.enemy_kill_value
            if kill_delta >= 0.0:
                score += min(0.55, 0.22 + kill_delta * 0.08)
        if target.aw == 0 and target.sw == 0:
            score -= 0.4
        return score
    return 0.0


def _score_damage_mode_action(main_projection, projection, ability_action, predicted_attack, skip_attack) -> float:
    target_before = main_projection.get_unit_by_id(ability_action.target_id or -1)
    target_after = projection.get_unit_by_id(ability_action.target_id or -1)
    if target_before is None:
        return 0.0

    score = 0.0
    target_is_enemy = any(unit.unit_id == target_before.unit_id for unit in main_projection.enemy_units)
    if not target_is_enemy:
        return -1.2

    if target_after is None:
        score += 0.8 + estimate_creature_board_value(target_before) * 0.2
    else:
        score += 0.12 + max(0.0, target_before.current_hp - target_after.current_hp) * 0.18

    skip_blockers = {blocker_id for _, blocker_id in skip_attack.score.chosen_block_assignment}
    predicted_blockers = {blocker_id for _, blocker_id in predicted_attack.score.chosen_block_assignment}
    if target_before.unit_id in skip_blockers:
        score += 0.95
        if target_before.unit_id not in predicted_blockers:
            score += 0.85
        if target_before.current_hp == 2:
            score += 0.95
        elif target_before.current_hp == 3:
            score += 0.4

    attack_delta = predicted_attack.score.total - skip_attack.score.total
    player_damage_delta = predicted_attack.score.player_damage - skip_attack.score.player_damage
    enemy_kill_delta = predicted_attack.score.enemy_kill_value - skip_attack.score.enemy_kill_value
    own_loss_delta = skip_attack.score.own_death_risk - predicted_attack.score.own_death_risk

    score += min(2.4, max(0.0, attack_delta) * 0.45)
    score += min(1.3, max(0.0, player_damage_delta) * 0.28)
    score += min(1.1, max(0.0, enemy_kill_delta) * 0.18)
    score += min(1.0, max(0.0, own_loss_delta) * 0.22)
    if enemy_kill_delta > 0.15 and own_loss_delta > -0.05:
        score += min(0.95, enemy_kill_delta * 0.16 + max(0.0, own_loss_delta) * 0.18)
    if attack_delta > 0.35 and target_before.unit_id in skip_blockers:
        score += min(1.2, attack_delta * 0.25)

    if target_before.vw > 0:
        score += 0.18
    if target_before.current_hp == 2:
        score += 0.22
    if target_before.current_hp >= 3 and attack_delta > 0.2:
        score += 0.18
    return score


def _score_action_risk(snapshot, projection, predicted_attack, projected_candidate, ability_action, action_kind: str, fallback_used: bool) -> float:
    pressure = _base_survival_pressure(snapshot)
    risk = 0.0
    if action_kind == "pass":
        risk -= PASS_ACTION_PENALTY
    if projected_candidate is not None:
        candidate = projected_candidate.candidate
        ability_breakthrough = BUILDER_ABILITIES_ENABLED and (
            ability_action.action_kind == "grant_ability"
            and ability_action.target_id == projection.hypothetical_unit_id
            and ability_action.card_ability in {Ability.FLYING, Ability.HASTE, Ability.PROVOKE}
        )
        if candidate.sw >= 3 and candidate.aw == 0 and candidate.vw == 0 and projection.hypothetical_unit_id not in predicted_attack.candidate.attacker_ids:
            risk -= GLASS_CANNON_PENALTY
        if BUILDER_ABILITIES_ENABLED and candidate.aw == 0 and candidate.sw >= 4 and candidate.lw <= 1 and snapshot.enemy_hand_count > 0:
            risk -= 1.8
        if candidate.aw == 0 and candidate.sw == 0 and candidate.vw >= 1 and candidate.lw >= 4 and pressure < 4.0:
            risk -= ZERO_OFFENSE_BUILD_RISK_PENALTY
        if BUILDER_ABILITIES_ENABLED and candidate.aw == 0 and candidate.sw >= 4 and not ability_breakthrough and predicted_attack.score.lethal_value < WIN_BONUS:
            risk -= 1.8
    if (
        predicted_attack.candidate.attacker_ids
        and predicted_attack.score.player_damage <= 0.75
        and predicted_attack.score.enemy_kill_value <= predicted_attack.score.own_death_risk * 0.6
        and predicted_attack.score.lethal_value < WIN_BONUS
    ):
        risk -= SUICIDE_ATTACK_PENALTY
    if snapshot.enemy_has_board and not any(not unit.tapped and not unit.cannot_block for unit in projection.own_units):
        risk -= 1.2 + pressure * 0.14
    if BUILDER_ABILITIES_ENABLED and ability_action.action_kind == "grant_ability" and ability_action.card_ability == Ability.VIGILANCE:
        target = projection.get_unit_by_id(ability_action.target_id or -1)
        if target is not None and target.aw == 0 and target.vw == 0:
            risk -= 1.4
    if fallback_used:
        risk -= 0.55
    return -abs(risk) * TURN_WEIGHTS.risk_penalty


def _score_terminal_projection(projection, predicted_attack: BuilderAttackDecision) -> float:
    if projection.enemy_life <= 0:
        return WIN_BONUS
    if projection.own_life <= 0:
        return LOSS_PENALTY
    if predicted_attack.score.guaranteed_player_damage >= projection.enemy_life > 0:
        return WIN_BONUS
    if (
        projection.own_life > 0
        and predicted_attack.score.counter_lethal_risk >= 1.0
        and predicted_attack.score.projected_counter_damage >= projection.own_life
    ):
        return LOSS_PENALTY
    return 0.0


def _projected_counterattack_units(projection, predicted_attack: BuilderAttackDecision):
    attacker_ids = tuple(predicted_attack.score.projected_counter_attackers)
    if not attacker_ids:
        return ()
    return tuple(
        attacker
        for attacker in (projection.get_unit_by_id(attacker_id) for attacker_id in attacker_ids)
        if attacker is not None and attacker.sw > 0
    )


def _can_affect_projected_counterattack(unit, projected_counter_attackers) -> bool:
    if getattr(unit, "cannot_block", False) or getattr(unit, "tapped", False):
        return False
    if not projected_counter_attackers:
        return True
    return any(can_legally_block(attacker, unit, require_ready=True) for attacker in projected_counter_attackers)


def _projected_block_quality(unit, projected_counter_attackers) -> float:
    if not _can_affect_projected_counterattack(unit, projected_counter_attackers):
        return 0.0
    if unit.vw <= 0:
        return 0.0
    if not projected_counter_attackers:
        return 1.0
    qualities = []
    for attacker in projected_counter_attackers:
        if not can_legally_block(attacker, unit, require_ready=True):
            continue
        matchup = summarize_builder_combat_matchup(attacker, unit)
        qualities.append(max(matchup.block_win_probability, matchup.blocker_survival_probability))
    return max(qualities, default=0.0)


def _stats_role_bonus(candidate, snapshot) -> float:
    score = 0.0
    if candidate.aw >= 1 and candidate.sw >= 2:
        score += 0.35
    if candidate.vw >= 2 and candidate.lw >= 3:
        score += 0.45
    if candidate.aw == 0 and candidate.vw == 0 and candidate.sw >= 3 and snapshot.enemy_has_board:
        score -= 1.65
    if candidate.aw == 0 and candidate.sw == 0 and candidate.vw >= 1 and candidate.lw >= 4 and snapshot.enemy_total_sw < 4:
        score -= 1.0
    return score


def _can_grant_projection_ability(unit, ability: Ability, created_this_turn_ids: set[int]) -> bool:
    normalized_distinct = {
        Ability.VIGILANCE if current == Ability.VIGILANT else Ability.LIFELINK if current == Ability.LIFE_STEAL else Ability.PROVOKE if current == Ability.ENRAGED else current
        for current in normalize_builder_abilities(unit.abilities)
        if current in {Ability.DEATHTOUCH, Ability.FLYING, Ability.HASTE, Ability.LIFELINK, Ability.TRAMPLE, Ability.VIGILANCE, Ability.PROVOKE}
    }
    if ability in normalized_distinct:
        return False
    if len(normalized_distinct) >= 2:
        return False
    if ability == Ability.HASTE and unit.unit_id not in created_this_turn_ids:
        return False
    return True


def _ability_candidate_sort_key(candidate: BuilderAbilityActionCandidate) -> tuple:
    return (
        1 if candidate.action_kind == "skip" else 0,
        candidate.action_kind,
        getattr(candidate.card_ability, "value", ""),
        candidate.target_id if candidate.target_id is not None else -1,
        candidate.selected_stat or "",
        candidate.card_instance_id if candidate.card_instance_id is not None else -1,
    )


def _projected_candidate_sort_key(projected: BuilderProjectedCandidate) -> tuple:
    return (
        projected.future_value,
        projected.static_score.matchup_defense,
        projected.static_score.board_fit,
        projected.static_score.survivability,
        projected.static_score.kill_pressure,
        projected.candidate.key,
    )


def _turn_decision_sort_key(decision: BuilderTurnDecision) -> tuple:
    candidate = decision.action_candidate
    return (
        decision.score.selection_score,
        decision.score.lethal_value,
        -decision.score.enemy_lethal_risk,
        -decision.score.expected_own_death_value,
        decision.score.expected_enemy_kill_value,
        1 if decision.ability_action.action_kind != "skip" else 0,
        candidate.action_kind,
        candidate.creature_candidate.key if candidate.creature_candidate is not None else ("resource",),
        _ability_candidate_sort_key(decision.ability_action),
    )


def _runtime_unit_signature(creature) -> tuple:
    return (
        creature.unit_id,
        creature.aw,
        creature.vw,
        creature.sw,
        creature.lw,
        creature.current_hp,
        creature.tapped,
        creature.summoning_sick,
        tuple(sorted(normalize_builder_abilities(creature.abilities), key=lambda ability: ability.value)),
    )


def _decision_matches_runtime(decision: BuilderTurnDecision, phase: str, runtime_signature: tuple) -> bool:
    runtime_without_phase = _runtime_signature_without_phase(runtime_signature)
    if phase == PHASE_MAIN_1:
        return decision.state_signature == runtime_signature
    if phase == PHASE_BUILDER_ABILITY:
        return (
            decision.post_main_signature == runtime_signature
            or decision.state_signature == runtime_signature
            or _runtime_signature_without_phase(decision.state_signature) == runtime_without_phase
            or _runtime_signature_without_phase(decision.post_main_signature) == runtime_without_phase
        )
    if phase == PHASE_DECLARE_ATTACKERS:
        return (
            decision.post_ability_signature == runtime_signature
            or decision.post_main_signature == runtime_signature
            or _runtime_signature_without_phase(decision.state_signature) == runtime_without_phase
            or _runtime_signature_without_phase(decision.post_main_signature) == runtime_without_phase
            or _runtime_signature_without_phase(decision.post_ability_signature) == runtime_without_phase
        )
    return decision.state_signature == runtime_signature


def _runtime_signature_without_phase(signature: tuple) -> tuple:
    if len(signature) < 2:
        return signature
    return signature[:1] + signature[2:]


def _projection_runtime_fingerprint(projection, *, phase: str, ability_used: bool) -> tuple:
    created_ids = ()
    if projection.hypothetical_unit_id is not None:
        created_ids = (projection.hypothetical_unit_id,)
    return (
        projection.player_id,
        phase,
        projection.own_life,
        projection.enemy_life,
        projection.own_total_resources,
        projection.own_ready_resources,
        projection.enemy_total_resources,
        projection.enemy_ready_resources,
        ability_used if BUILDER_ABILITIES_ENABLED else False,
        projection.hand_signature if BUILDER_ABILITIES_ENABLED else (),
        created_ids,
        tuple(_projection_unit_signature(unit) for unit in projection.own_units),
        tuple(_projection_unit_signature(unit) for unit in projection.enemy_units),
        int(getattr(projection, "builder_stalled_turns", 0)),
    )


def _projection_unit_signature(unit) -> tuple:
    return (
        unit.unit_id,
        unit.aw,
        unit.vw,
        unit.sw,
        unit.lw,
        unit.current_hp,
        unit.tapped,
        unit.summoning_sickness,
        tuple(sorted(ability.value for ability in normalize_builder_abilities(unit.abilities))),
    )


def _debug_build_candidates(engine, player, snapshot, build_debug: dict, shortlisted: list[BuilderProjectedCandidate], decision: BuilderTurnDecision) -> None:
    if not builder_debug_enabled():
        return
    top_n = builder_debug_build_top_n()
    selected_signature = (
        decision.action_candidate.creature_candidate.key
        if decision.action_candidate.action_kind == "creature" and decision.action_candidate.creature_candidate is not None
        else None
    )
    all_candidates = list(build_debug.get("projected_all", ()))
    frontier = list(build_debug.get("frontier", ()))
    if not all_candidates and not frontier:
        return
    emit_builder_debug_line(
        engine,
        "AI BUILD",
        player=player,
        decision="build",
        pairs=(
            ("budget", build_debug.get("budget", 0)),
            ("considered_budgets", build_debug.get("considered_budgets", ())),
            ("generated", build_debug.get("generated_count", 0)),
            ("legal", build_debug.get("legal_count", 0)),
            ("frontier", len(frontier)),
            ("shortlisted", len(shortlisted)),
            ("pruned", len(shortlisted) < len(all_candidates) or len(frontier) < len(all_candidates)),
        ),
    )
    ranked = shortlisted if shortlisted else frontier
    static_ranked = sorted(
        all_candidates if all_candidates else ranked,
        key=lambda current: (current.static_score.total, current.candidate.key),
        reverse=True,
    )
    displayed = list(ranked[:top_n])
    if selected_signature is not None and all(candidate.candidate.key != selected_signature for candidate in displayed):
        selected = next((candidate for candidate in ranked if candidate.candidate.key == selected_signature), None)
        if selected is not None:
            displayed.append(selected)
    seen: set[tuple] = set()
    for index, projected in enumerate(displayed, start=1):
        signature = projected.candidate.key
        if signature in seen:
            continue
        seen.add(signature)
        score = projected.static_score
        emit_builder_debug_line(
            engine,
            "AI BUILD",
            player=player,
            decision="build",
            pairs=(
                ("rank", index),
                ("stats", f"{projected.candidate.aw}/{projected.candidate.vw}/{projected.candidate.sw}/{projected.candidate.lw}"),
                ("ability", getattr(projected.candidate.builder_ability, "value", "-")),
                ("ability_cost", 0),
                ("haste", projected.candidate.has_haste),
                ("haste_cost", projected.candidate.haste_cost),
                ("enters_tapped", projected.candidate.enters_tapped),
                ("cost", projected.candidate.cost),
                ("unused", max(0, snapshot.own_ready_resources - projected.candidate.cost)),
                ("static_total", score.total),
                ("future", projected.future_value),
                ("raw", score.raw_stats),
                ("abilities", score.abilities),
                ("synergy", score.synergy),
                ("board_fit", score.board_fit),
                ("immediate_pressure", score.immediate_pressure),
                ("survivability", score.survivability),
                ("matchup_offense", score.matchup_offense),
                ("matchup_defense", score.matchup_defense),
                ("evasion", score.evasion),
                ("expected_player_damage", score.expected_player_damage),
                ("expected_heal", score.expected_heal),
                ("kill_pressure", score.kill_pressure),
                ("death_risk", score.death_risk),
                ("attack_access_probability", score.attack_access_probability),
                ("block_win_probability", score.block_win_probability),
                ("attacker_kill_probability", score.attacker_kill_probability),
                ("blocker_survival_probability", score.blocker_survival_probability),
                ("damage_delivery_probability", score.damage_delivery_probability),
                ("stranded_damage", score.stranded_damage),
                ("overkill_damage", score.overkill_damage),
                ("life_breakpoint", score.life_breakpoint),
                ("immediate_prevented_damage", score.immediate_prevented_damage),
                ("repeated_block_value", score.repeated_block_value),
                ("repeated_prevented_damage", score.repeated_prevented_damage),
                ("shortlist_reasons", projected.shortlist_reasons),
                ("selected_in_turn", selected_signature == signature),
            ),
        )
    if ranked:
        static_best = static_ranked[0]
        static_runner_up = static_ranked[1] if len(static_ranked) > 1 else None
        shortlist_best = ranked[0]
        dynamic_best = next((current for current in ranked if current.candidate.key == selected_signature), shortlist_best)
        emit_builder_debug_line(
            engine,
            "AI BUILD",
            player=player,
            decision="build",
            pairs=(
                ("static_best", f"{static_best.candidate.aw}/{static_best.candidate.vw}/{static_best.candidate.sw}/{static_best.candidate.lw}"),
                ("static_best_total", static_best.static_score.total),
                ("static_runner_up", "N/A" if static_runner_up is None else f"{static_runner_up.candidate.aw}/{static_runner_up.candidate.vw}/{static_runner_up.candidate.sw}/{static_runner_up.candidate.lw}"),
                ("static_runner_up_total", "N/A" if static_runner_up is None else static_runner_up.static_score.total),
                ("static_gap", "N/A" if static_runner_up is None else round(static_best.static_score.total - static_runner_up.static_score.total, 4)),
                ("shortlist_rank_best", f"{shortlist_best.candidate.aw}/{shortlist_best.candidate.vw}/{shortlist_best.candidate.sw}/{shortlist_best.candidate.lw}"),
                ("shortlist_rank_best_total", shortlist_best.static_score.total),
                ("selected_build", f"{dynamic_best.candidate.aw}/{dynamic_best.candidate.vw}/{dynamic_best.candidate.sw}/{dynamic_best.candidate.lw}"),
                ("selected_build_selection_score", decision.score.selection_score if selected_signature is not None else "N/A"),
                ("chosen_build", f"{dynamic_best.candidate.aw}/{dynamic_best.candidate.vw}/{dynamic_best.candidate.sw}/{dynamic_best.candidate.lw}"),
                ("ability", getattr(dynamic_best.candidate.builder_ability, "value", "-")),
                ("ability_cost", 0),
                ("haste", dynamic_best.candidate.has_haste),
                ("haste_cost", dynamic_best.candidate.haste_cost),
                ("enters_tapped", dynamic_best.candidate.enters_tapped),
                ("chosen_static_total", dynamic_best.static_score.total),
                ("chosen_vs_static_best_delta", round(dynamic_best.static_score.total - static_best.static_score.total, 4)),
                ("selection_reason", "static_best" if dynamic_best.candidate.key == static_best.candidate.key else ("shortlist_rank_best" if dynamic_best.candidate.key == shortlist_best.candidate.key else "dynamic_turn_selection")),
            ),
        )


def _debug_turn_decision(engine, player, runtime_signature: tuple, snapshot, baseline_attack, decisions, fallback_used: bool) -> None:
    if not builder_debug_enabled():
        return
    best = decisions[0]
    gap, runner_up = turn_score_gap(decisions)
    displayed: list[BuilderTurnDecision] = []
    seen_keys: set[tuple] = set()

    def add_decision(current: BuilderTurnDecision | None) -> None:
        if current is None:
            return
        key = (
            current.action_candidate.action_kind,
            None if current.action_candidate.creature_candidate is None else current.action_candidate.creature_candidate.key,
            current.ability_action.action_kind,
            current.ability_action.target_id,
            current.ability_action.selected_stat,
        )
        if key in seen_keys:
            return
        seen_keys.add(key)
        displayed.append(current)

    for action_kind in ("resource", "creature", "pass", "continue"):
        add_decision(next((current for current in decisions if current.action_candidate.action_kind == action_kind), None))
    add_decision(best)
    add_decision(runner_up)
    for current in decisions:
        if len(displayed) >= builder_debug_top_n() + 4:
            break
        add_decision(current)
    displayed.sort(key=_turn_decision_sort_key, reverse=True)
    forced_loss_all_actions = all(
        current.score.enemy_lethal_risk >= 1.0 and current.score.expected_enemy_followup_damage >= snapshot.own_life
        for current in decisions
    )
    best_survival_margin = max((current.score.survival_buffer for current in decisions), default=0.0)
    emit_builder_debug_line(
        engine,
        "AI PLAN",
        player=player,
        decision="main",
        pairs=(
            ("resources", f"{snapshot.own_ready_resources}/{snapshot.own_total_resources}"),
            ("life", f"{snapshot.own_life}/{snapshot.enemy_life}"),
            ("board", f"{snapshot.own_board_value}/{snapshot.enemy_board_value}"),
            ("urgency", _base_survival_pressure(snapshot)),
            ("baseline_attack", list(baseline_attack.candidate.attacker_ids)),
            ("baseline_attack_score", baseline_attack.score.total),
            ("baseline_attack_lethal", baseline_attack.score.lethal_probability),
            ("attack_search_exact", baseline_attack.search_metadata.exact_search),
            ("fallback", fallback_used),
            ("forced_loss_all_actions", forced_loss_all_actions),
            ("best_survival_margin", round(best_survival_margin, 4)),
        ),
    )
    for rank, current in enumerate(displayed, start=1):
        action = current.action_candidate
        attack = current.predicted_attack_decision
        pairs = [
            ("rank", rank),
            ("candidate", action.action_kind),
            ("selection_score", current.score.selection_score),
            ("turn_total", current.score.total),
            ("attack", [] if attack is None else list(attack.candidate.attacker_ids)),
            ("projected_enemy_main_action", None if attack is None else attack.score.projected_counter_main_action),
            ("projected_enemy_main_stats", None if attack is None else attack.score.projected_counter_main_stats),
            ("projected_enemy_attackers", [] if attack is None else list(attack.score.projected_counter_attackers)),
            ("board_value", current.score.board_value),
            ("resource_value", current.score.resource_value),
            ("creature_future_value", current.score.creature_future_value),
            ("resource_growth_value", current.score.resource_growth_value),
            ("immediate_combat_delta", current.score.immediate_combat_delta),
            ("expected_player_damage", current.score.expected_player_damage),
            ("expected_enemy_kill_value", current.score.expected_enemy_kill_value),
            ("expected_own_death_value", current.score.expected_own_death_value),
            ("end_of_turn_readiness", current.score.end_of_turn_readiness),
            ("survival_urgency", current.score.survival_urgency),
            ("expected_enemy_damage", current.score.expected_enemy_followup_damage),
            ("enemy_lethal_risk", current.score.enemy_lethal_risk),
            ("survival_buffer", current.score.survival_buffer),
            ("future_offense_value", current.score.future_offense_value),
            ("own_next_attack_damage", current.score.own_next_attack_damage),
            ("own_next_attack_lethal", current.score.own_next_attack_lethal),
            ("own_next_attackers", list(current.score.own_next_attackers)),
            ("enemy_future_blockers", [f"{attacker_id}:{list(blockers)}" for attacker_id, blockers in current.score.enemy_future_blockers]),
            ("enemy_blocker_ready_in_time", current.score.enemy_blocker_ready_in_time),
            ("turns_to_own_lethal", current.score.turns_to_own_lethal),
            ("lethal_line_exact", current.score.lethal_line_exact),
            ("lethal_line_fallback_used", current.score.lethal_line_fallback_used),
            ("damage_before_coverage_ready", current.score.damage_before_coverage_ready),
            ("second_attack_damage", current.score.second_attack_damage),
            ("second_attack_lethal", current.score.second_attack_lethal),
            ("coverage_ready_turn", current.score.coverage_ready_turn),
            ("coverage_prevents_repeated_lethal", current.score.coverage_prevents_repeated_lethal),
            ("must_hold_as_blocker", current.score.must_hold_as_blocker),
            ("cumulative_unavoidable_damage", current.score.cumulative_unavoidable_damage),
            ("board_slot_opportunity_cost", current.score.board_slot_opportunity_cost),
            ("haste_immediate_value", current.score.haste_immediate_value),
            ("flying_offense", current.score.flying_offense_value),
            ("flying_coverage", current.score.flying_coverage_value),
            ("curve_delay", current.score.curve_delay_value),
            ("role_novelty", current.score.role_novelty_value),
            ("projected_slot_tenure", current.score.projected_slot_tenure),
            ("best_build_value_now", current.score.best_build_value_now),
            ("best_build_stats_now", current.score.best_build_stats_now),
            ("best_build_value_r_plus_1", current.score.best_build_value_r_plus_1),
            ("best_build_stats_r_plus_1", current.score.best_build_stats_r_plus_1),
            ("best_build_value_r_plus_2", current.score.best_build_value_r_plus_2),
            ("best_build_stats_r_plus_2", current.score.best_build_stats_r_plus_2),
            ("lethal_value", current.score.lethal_value),
            ("risk_adjustment", current.score.risk_adjustment),
        ]
        if action.creature_candidate is not None:
            pairs.append(("stats", f"{action.creature_candidate.aw}/{action.creature_candidate.vw}/{action.creature_candidate.sw}/{action.creature_candidate.lw}"))
            pairs.extend(
                (
                    ("ability", getattr(action.creature_candidate.builder_ability, "value", "-")),
                    ("ability_cost", 0),
                    ("haste", action.creature_candidate.has_haste),
                    ("haste_cost", action.creature_candidate.haste_cost),
                    ("enters_tapped", action.creature_candidate.enters_tapped),
                    ("new_unit_tapped", action.creature_candidate.enters_tapped),
                    ("new_unit_sick", action.creature_candidate.enters_tapped),
                    ("new_unit_can_attack", action.creature_candidate.has_haste),
                    ("new_unit_can_block", not action.creature_candidate.enters_tapped),
                    ("new_unit_block_reason", "-" if not action.creature_candidate.enters_tapped else "tapped"),
                )
            )
        emit_builder_debug_line(engine, "AI PLAN", player=player, decision="main", pairs=tuple(pairs))
        if builder_debug_verbose():
            emit_builder_debug_line(
                engine,
                "AI PLAN",
                player=player,
                decision="main",
                pairs=(("rank", rank),) + contribution_pairs(current.score),
            )
    emit_builder_debug_line(
        engine,
        "AI PLAN",
        player=player,
        decision="main",
        pairs=(
            ("choose", best.action_candidate.action_kind),
            ("choose_stats", None if best.action_candidate.creature_candidate is None else f"{best.action_candidate.creature_candidate.aw}/{best.action_candidate.creature_candidate.vw}/{best.action_candidate.creature_candidate.sw}/{best.action_candidate.creature_candidate.lw}"),
            ("total", best.score.selection_score),
            ("selection_score", best.score.selection_score),
            ("turn_total", best.score.total),
            ("runner_up", "-" if runner_up is None else runner_up.action_candidate.action_kind),
            (
                "runner_up_stats",
                "N/A" if runner_up is None
                else None if runner_up.action_candidate.creature_candidate is None
                else f"{runner_up.action_candidate.creature_candidate.aw}/{runner_up.action_candidate.creature_candidate.vw}/{runner_up.action_candidate.creature_candidate.sw}/{runner_up.action_candidate.creature_candidate.lw}",
            ),
            ("runner_up_total", "N/A" if runner_up is None else runner_up.score.selection_score),
            ("runner_up_selection_score", "N/A" if runner_up is None else runner_up.score.selection_score),
            ("gap", "N/A" if runner_up is None else gap),
            ("delta_keys", "N/A" if runner_up is None else score_delta_keys(best.score, runner_up.score)),
            ("planned_attack", [] if best.predicted_attack_decision is None else list(best.predicted_attack_decision.candidate.attacker_ids)),
            ("selection_reason", "max_selection_score"),
            ("forced_loss_all_actions", forced_loss_all_actions),
            ("best_survival_margin", round(best_survival_margin, 4)),
        ),
    )
    if builder_debug_verbose() and builder_debug_include_fingerprints():
        after = build_builder_runtime_fingerprint(player, engine)
        log_builder_fingerprint(engine, player, decision="main", before=runtime_signature, after=after)
