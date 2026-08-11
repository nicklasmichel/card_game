from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

import core.config as config
from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_CREATURE_CAP
from core.models import Ability, PHASE_BUILDER_ABILITY, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1

from .attack_policy import BuilderAttackDecision, evaluate_best_builder_attack
from .config import BUILDER_AI_WEIGHTS
from .cap_strategy import compute_builder_cap_context
from .candidates import builder_candidate_budgets, generate_builder_creature_candidates, is_legal_builder_candidate
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
from .scoring import estimate_creature_board_value, score_builder_creature_candidate
from .search_budget import TURN_LOOKAHEAD_SEARCH_BUDGET
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
PASS_ACTION_PENALTY = 0.35
SUICIDE_ATTACK_PENALTY = 4.6
GLASS_CANNON_PENALTY = 2.4
RESOURCE_UNDER_PRESSURE_PENALTY = 1.45
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
VIGILANCE_SUICIDE_PENALTY = 0.0
HASTE_WITHOUT_ATTACK_PENALTY = 0.0
PROVOKE_RELEASE_BONUS = 0.0
STAT_BREAKPOINT_WEIGHT = 0.0
REMOVE_BLOCKER_WEIGHT = 0.0
OPEN_HAND_REMOVAL_RISK_PENALTY = 0.0
NONLETHAL_GLASS_ABILITY_PENALTY = 0.0


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


def plan_builder_turn(player, engine) -> BuilderTurnDecision:
    runtime_signature = build_builder_runtime_fingerprint(player, engine)
    cached = getattr(engine.ai, "_last_builder_turn_decision", None)
    if cached is not None and _decision_matches_runtime(cached, engine.phase, runtime_signature):
        return cached

    if engine.phase == PHASE_MAIN_1 and not player.main_action_used_this_turn:
        decision = _plan_builder_full_turn(player, engine, runtime_signature)
    elif engine.phase == PHASE_BUILDER_ABILITY:
        decision = _plan_builder_continuation(player, engine, runtime_signature, allow_ability=BUILDER_ABILITIES_ENABLED and not engine.builder_ability_used_this_turn)
    elif engine.phase == PHASE_DECLARE_ATTACKERS:
        decision = _plan_builder_continuation(player, engine, runtime_signature, allow_ability=False)
    else:
        decision = _plan_builder_continuation(player, engine, runtime_signature, allow_ability=False)

    setattr(engine.ai, "_last_builder_turn_decision", decision)
    return decision


def choose_builder_turn_plan(player, engine) -> BuilderTurnDecision:
    return plan_builder_turn(player, engine)


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


def score_resource_growth_action(snapshot, current_candidate_frontier, next_resource_candidate_frontier) -> float:
    if snapshot.own_total_resources >= 10:
        return float("-inf")
    current_best = max((projected.future_value for projected in current_candidate_frontier), default=0.0)
    next_best = max((projected.future_value for projected in next_resource_candidate_frontier), default=current_best)
    marginal_capacity = max(0.0, next_best - current_best)
    pressure = _base_survival_pressure(snapshot)
    horizon = max(0.16, RESOURCE_HORIZON_FACTOR - snapshot.own_total_resources * 0.07 - pressure * 0.07)
    level_bonus = max(0.0, RESOURCE_LOW_LEVEL_BONUS - snapshot.own_total_resources * RESOURCE_CAP_DECAY)
    under_pressure_penalty = pressure * RESOURCE_UNDER_PRESSURE_PENALTY if pressure >= 3.0 else 0.0
    empty_board_penalty = EMPTY_BOARD_RAMP_PENALTY if not snapshot.own_has_board and snapshot.own_total_resources >= 4 else 0.0
    at_cap_penalty = RESOURCE_AT_CAP_PENALTY if snapshot.own_creature_count >= BUILDER_CREATURE_CAP else 0.0
    return round(level_bonus + marginal_capacity * horizon - under_pressure_penalty - empty_board_penalty - at_cap_penalty, 4)


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
    )


def _plan_builder_full_turn(player, engine, runtime_signature: tuple) -> BuilderTurnDecision:
    if builder_debug_enabled():
        ensure_builder_weights_logged(engine)
    snapshot = build_builder_snapshot(player, engine)
    if builder_debug_verbose():
        log_builder_state(engine, player, decision="main", snapshot=snapshot)
    base_projection = build_current_turn_projection(player, engine)
    attack_cache: dict[tuple, BuilderAttackDecision] = {}
    baseline_attack = _evaluate_attack_cached(base_projection, attack_cache)
    static_candidates, fallback_used, build_debug = _build_projected_candidates(player, engine, snapshot)
    shortlisted = _shortlist_projected_candidates(static_candidates, snapshot.own_ready_resources)

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
                    engine=engine,
                    player=player,
                )
            )
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
                source_signature=runtime_signature,
                fallback_used=fallback_used,
            )
        )
    decisions.sort(key=_turn_decision_sort_key, reverse=True)
    decision = decisions[0]
    _debug_build_candidates(engine, player, snapshot, build_debug, shortlisted, decision)
    _debug_turn_decision(engine, player, runtime_signature, snapshot, baseline_attack, decisions, fallback_used)
    return decision


def _plan_builder_continuation(player, engine, runtime_signature: tuple, *, allow_ability: bool) -> BuilderTurnDecision:
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
    attack_cache: dict[tuple, BuilderAttackDecision] = {}
    baseline_attack = _evaluate_attack_cached(base_projection, attack_cache)
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
            engine=engine,
            player=player,
        )
        return decision
    decisions = _evaluate_ability_plans_for_projection(
        player=player,
        engine=engine,
        snapshot=snapshot,
        action_candidate=action_candidate,
        main_projection=base_projection,
        projected_candidate=None,
        baseline_attack=baseline_attack,
        attack_cache=attack_cache,
        source_signature=runtime_signature,
        fallback_used=False,
        allow_ability=allow_ability,
    )
    decisions.sort(key=_turn_decision_sort_key, reverse=True)
    return decisions[0]


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
    source_signature: tuple,
    fallback_used: bool,
    allow_ability: bool = True,
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
                engine=engine,
                player=player,
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
            engine=engine,
            player=player,
        )
        decisions.append(decision)
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


def _build_projected_candidates(player, engine, snapshot) -> tuple[list[BuilderProjectedCandidate], bool, dict]:
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
    projected: list[BuilderProjectedCandidate] = []
    for candidate in legal:
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
    projected.sort(key=_projected_candidate_sort_key, reverse=True)
    return projected, False, {
        "budget": available_resources,
        "considered_budgets": considered_budgets,
        "generated_count": len(candidates),
        "legal_count": len(legal),
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
    engine,
    player,
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
        next_frontier, _, _ = _build_projected_candidates(projection.players[projection.player_id], projection, next_snapshot)

    terminal = _score_terminal_projection(projection, predicted_attack)
    creature_future_value = 0.0 if projected_candidate is None else projected_candidate.future_value * TURN_WEIGHTS.creature_future_value
    resource_growth_value = (
        score_resource_growth_action(snapshot, current_frontier, next_frontier)
        * TURN_WEIGHTS.resource_growth
        * BUILDER_AI_WEIGHTS.resource_growth_vs_build
        if action_candidate.action_kind == "resource"
        else 0.0
    )
    immediate_combat_delta = (predicted_attack.score.total - baseline_attack.score.total) * TURN_WEIGHTS.immediate_combat_delta
    end_of_turn_readiness = _score_end_of_turn_readiness(projection, predicted_attack, snapshot) * TURN_WEIGHTS.ready_defense
    survival_urgency = _score_action_survival_urgency(snapshot, projection, action_candidate.action_kind) * TURN_WEIGHTS.survival_urgency
    board_value = _score_board_projection_value(projection) * TURN_WEIGHTS.board_value
    ability_value = _score_ability_action_value(
        ability_action,
        main_projection,
        projection,
        predicted_attack,
        skip_attack,
        snapshot,
        action_candidate.action_kind,
    ) * TURN_WEIGHTS.ability_impact
    raw_resource_growth_value = (
        score_resource_growth_action(snapshot, current_frontier, next_frontier)
        if action_candidate.action_kind == "resource"
        else 0.0
    )
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
        + risk
    )
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
            predicted_attack.score.total - baseline_attack.score.total,
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
            _score_action_survival_urgency(snapshot, projection, action_candidate.action_kind),
            TURN_WEIGHTS.survival_urgency,
            survival_urgency,
        ),
        ("lethal", predicted_attack.score.lethal_value, 1.0, predicted_attack.score.lethal_value),
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
        total=round(total, 4),
        baseline_attack_score=round(baseline_attack.score.total, 4),
        projected_attack_score=round(predicted_attack.score.total, 4),
        search_was_exact=predicted_attack.search_metadata.exact_search,
        evaluated_candidate_count=1,
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


def _evaluate_attack_cached(projection, cache: dict[tuple, BuilderAttackDecision]) -> BuilderAttackDecision:
    cached = cache.get(projection.state_signature)
    if cached is not None:
        return cached
    decision = evaluate_best_builder_attack(
        projection.players[projection.player_id],
        projection,
        search_budget=TURN_LOOKAHEAD_SEARCH_BUDGET,
    )
    cache[projection.state_signature] = decision
    return decision


def _shortlist_projected_candidates(projected_candidates: list[BuilderProjectedCandidate], ready_resources: int) -> list[BuilderProjectedCandidate]:
    if ready_resources <= 4:
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

    take(by_future, 20, "future")
    take(by_damage, 8, "damage")
    take(by_attack, 6, "attack")
    take(by_defense, 8, "defense")
    take(by_hybrid, 6, "hybrid")
    shortlisted = list(selected.values())
    shortlisted.sort(key=_projected_candidate_sort_key, reverse=True)
    return shortlisted[:32]


def _score_end_of_turn_readiness(projection, predicted_attack: BuilderAttackDecision, snapshot) -> float:
    attacked_ids = set(predicted_attack.candidate.attacker_ids)
    enemy_pressure = max(0.6, snapshot.enemy_potential_attacker_count * 0.32 + snapshot.enemy_total_sw * 0.08 + snapshot.enemy_flying_count * 0.25)
    total = 0.0
    for unit in projection.own_units:
        if unit.unit_id in attacked_ids:
            ready_for_defense = unit.has_ability(Ability.VIGILANT) or unit.has_ability(Ability.VIGILANCE)
        else:
            ready_for_defense = not unit.tapped
        if ready_for_defense:
            total += estimate_creature_board_value(unit) * 0.05 * enemy_pressure
        if ready_for_defense and (unit.has_ability(Ability.VIGILANT) or unit.has_ability(Ability.VIGILANCE)):
            total += 0.22
        if unit.unit_id == projection.hypothetical_unit_id and not unit.tapped and unit.vw > 0:
            total += 0.18 + unit.vw * 0.05 + unit.current_hp * 0.03
        if unit.unit_id == projection.hypothetical_unit_id and unit.tapped:
            total -= TAPPED_NEW_BODY_PENALTY
    return total


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


def _score_action_survival_urgency(snapshot, projection, action_kind: str) -> float:
    pressure = _base_survival_pressure(snapshot)
    if action_kind == "resource":
        return -pressure * 0.95
    if action_kind == "pass":
        return -pressure * 1.1
    defensive_value = sum(
        estimate_creature_board_value(unit) * (0.08 if not unit.tapped and unit.vw > 0 else 0.02)
        for unit in projection.own_units
    )
    return defensive_value * max(0.3, pressure * 0.12)


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
            base += target.sw * 0.14 + STAT_BREAKPOINT_WEIGHT
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
        if target.current_hp <= 1 and target.aw == 0 and target.vw == 0:
            score -= NONLETHAL_GLASS_ABILITY_PENALTY
        return score
    if ability == Ability.HASTE:
        attacks_now = target.unit_id in predicted_attack.candidate.attacker_ids
        return (1.4 if attacks_now else -HASTE_WITHOUT_ATTACK_PENALTY) + target.sw * 0.25
    if ability == Ability.VIGILANCE:
        attacks_now = target.unit_id in predicted_attack.candidate.attacker_ids
        defensive_body = target.vw + target.current_hp
        score = defensive_body * 0.12 + (0.55 if attacks_now else 0.0)
        if target.aw == 0 and (target.vw == 0 or target.sw >= 3 and target.current_hp <= 1):
            score -= VIGILANCE_SUICIDE_PENALTY
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
        score = (PROVOKE_RELEASE_BONUS if attacks_now else 0.0) + target.sw * 0.16 + snapshot.enemy_creature_count * 0.08
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
    if snapshot.enemy_has_board and not any(not unit.tapped and unit.vw > 0 for unit in projection.own_units):
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
    return 0.0


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
        decision.score.total,
        decision.score.lethal_value,
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
    if phase == PHASE_MAIN_1:
        return decision.state_signature == runtime_signature
    if phase == PHASE_BUILDER_ABILITY:
        return decision.post_main_signature == runtime_signature or decision.state_signature == runtime_signature
    if phase == PHASE_DECLARE_ATTACKERS:
        return decision.post_ability_signature == runtime_signature or decision.post_main_signature == runtime_signature
    return decision.state_signature == runtime_signature


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
                ("total", score.total),
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
                ("shortlist_reasons", projected.shortlist_reasons),
                ("selected_in_turn", selected_signature == signature),
            ),
        )
    if ranked:
        best = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        emit_builder_debug_line(
            engine,
            "AI BUILD",
            player=player,
            decision="build",
            pairs=(
                ("choose", f"{best.candidate.aw}/{best.candidate.vw}/{best.candidate.sw}/{best.candidate.lw}"),
                ("ability", getattr(best.candidate.builder_ability, "value", "-")),
                ("ability_cost", 0),
                ("haste", best.candidate.has_haste),
                ("haste_cost", best.candidate.haste_cost),
                ("enters_tapped", best.candidate.enters_tapped),
                ("total", best.static_score.total),
                ("runner_up", "-" if runner_up is None else f"{runner_up.candidate.aw}/{runner_up.candidate.vw}/{runner_up.candidate.sw}/{runner_up.candidate.lw}"),
                ("runner_up_total", 0.0 if runner_up is None else runner_up.static_score.total),
                ("gap", 0.0 if runner_up is None else round(best.static_score.total - runner_up.static_score.total, 4)),
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
        ),
    )
    for rank, current in enumerate(displayed, start=1):
        action = current.action_candidate
        attack = current.predicted_attack_decision
        pairs = [
            ("rank", rank),
            ("candidate", action.action_kind),
            ("total", current.score.total),
            ("attack", [] if attack is None else list(attack.candidate.attacker_ids)),
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
                    ("new_unit_can_block", action.creature_candidate.vw > 0 and not action.creature_candidate.enters_tapped),
                    ("new_unit_block_reason", "-" if action.creature_candidate.vw > 0 and not action.creature_candidate.enters_tapped else ("defense_zero" if action.creature_candidate.vw <= 0 else "tapped")),
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
            ("total", best.score.total),
            ("runner_up", "-" if runner_up is None else runner_up.action_candidate.action_kind),
            (
                "runner_up_stats",
                None if runner_up is None or runner_up.action_candidate.creature_candidate is None
                else f"{runner_up.action_candidate.creature_candidate.aw}/{runner_up.action_candidate.creature_candidate.vw}/{runner_up.action_candidate.creature_candidate.sw}/{runner_up.action_candidate.creature_candidate.lw}",
            ),
            ("runner_up_total", 0.0 if runner_up is None else runner_up.score.total),
            ("gap", gap),
            ("delta_keys", "-" if runner_up is None else score_delta_keys(best.score, runner_up.score)),
            ("planned_attack", [] if best.predicted_attack_decision is None else list(best.predicted_attack_decision.candidate.attacker_ids)),
        ),
    )
    if builder_debug_verbose() and builder_debug_include_fingerprints():
        after = build_builder_runtime_fingerprint(player, engine)
        log_builder_fingerprint(engine, player, decision="main", before=runtime_signature, after=after)


def _is_finite_score(score: BuilderTurnScore) -> bool:
    return all(isfinite(value) for value in score.__dict__.values() if isinstance(value, float))
