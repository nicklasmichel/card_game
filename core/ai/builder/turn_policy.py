from __future__ import annotations

from math import isfinite

import core.config as config
from core.models import Ability

from .attack_policy import BuilderAttackDecision, evaluate_best_builder_attack
from .candidates import generate_builder_creature_candidates, is_legal_builder_candidate
from .scoring import estimate_creature_board_value, score_builder_creature_candidate
from .search_budget import TURN_LOOKAHEAD_SEARCH_BUDGET
from .snapshot import build_builder_snapshot
from .turn_projection import build_current_turn_projection, project_creature_action, project_resource_action
from .turn_types import (
    BuilderProjectedCandidate,
    BuilderTurnActionCandidate,
    BuilderTurnDecision,
    BuilderTurnScore,
)

CREATURE_FUTURE_VALUE_WEIGHT = 1.0
RESOURCE_GROWTH_WEIGHT = 1.0
IMMEDIATE_COMBAT_DELTA_WEIGHT = 1.0
READY_DEFENSE_WEIGHT = 1.0
SURVIVAL_URGENCY_WEIGHT = 1.0
RESOURCE_HORIZON_FACTOR = 1.35
RESOURCE_LOW_LEVEL_BONUS = 3.2
RESOURCE_CAP_DECAY = 0.34
SURVIVAL_RESOURCE_PENALTY = 0.9
SURVIVAL_CREATURE_DEFENSE_WEIGHT = 0.12
NON_HASTE_SURVIVAL_DISCOUNT = 0.22
RISK_PENALTY_WEIGHT = 0.11
VIGILANT_READINESS_BONUS = 0.22
HASTE_READY_DEFENSE_BONUS = 0.16
IMMEDIATE_PRESSURE_DISCOUNT = 0.92
EXPECTED_DAMAGE_DISCOUNT = 0.72
HASTE_FUTURE_DISCOUNT = 0.22
FULL_BUDGET_FALLBACK_PENALTY = 0.55


def plan_builder_turn(player, engine) -> BuilderTurnDecision:
    state_signature = _build_turn_state_signature(player, engine)
    cached = getattr(engine.ai, "_last_builder_turn_decision", None)
    cached_signature = getattr(engine.ai, "_last_builder_turn_signature", None)
    if cached is not None and cached_signature == state_signature:
        return cached

    snapshot = build_builder_snapshot(player, engine)
    base_projection = build_current_turn_projection(player, engine)
    baseline_attack = evaluate_best_builder_attack(
        base_projection.players[player.player_id],
        base_projection,
        search_budget=TURN_LOOKAHEAD_SEARCH_BUDGET,
    )

    static_candidates, fallback_used = _build_projected_candidates(player, engine, snapshot)
    shortlisted = _shortlist_projected_candidates(static_candidates, snapshot.own_ready_resources)

    decisions: list[BuilderTurnDecision] = []
    if player.total_resources() < engine.BUILDER_MAX_RESOURCES:
        resource_candidate = BuilderTurnActionCandidate(
            action_kind="resource",
            creature_candidate=None,
            projected_total_resources=player.total_resources() + 1,
            projected_ready_resources=player.available_resources() + 1,
            generation_reason="resource_growth",
        )
        decisions.append(
            _build_action_decision(
                action_candidate=resource_candidate,
                projection=project_resource_action(base_projection),
                baseline_attack=baseline_attack,
                predicted_attack=baseline_attack,
                snapshot=snapshot,
                projected_candidate=None,
                evaluated_candidate_count=len(shortlisted),
            )
        )

    for projected_candidate in shortlisted:
        action_candidate = BuilderTurnActionCandidate(
            action_kind="creature",
            creature_candidate=projected_candidate.candidate,
            projected_total_resources=player.total_resources(),
            projected_ready_resources=max(0, player.available_resources() - projected_candidate.candidate.cost),
            generation_reason="|".join(projected_candidate.shortlist_reasons) or projected_candidate.candidate.generation_reason,
        )
        projection = project_creature_action(base_projection, action_candidate)
        if Ability.HASTE in projected_candidate.candidate.abilities:
            predicted_attack = evaluate_best_builder_attack(
                projection.players[player.player_id],
                projection,
                search_budget=TURN_LOOKAHEAD_SEARCH_BUDGET,
            )
        else:
            predicted_attack = baseline_attack
        decisions.append(
            _build_action_decision(
                action_candidate=action_candidate,
                projection=projection,
                baseline_attack=baseline_attack,
                predicted_attack=predicted_attack,
                snapshot=snapshot,
                projected_candidate=projected_candidate,
                evaluated_candidate_count=len(shortlisted),
                fallback_used=fallback_used,
            )
        )

    decisions.sort(key=_turn_decision_sort_key, reverse=True)
    decision = decisions[0]
    setattr(engine.ai, "_last_builder_turn_decision", decision)
    setattr(engine.ai, "_last_builder_turn_signature", state_signature)
    _debug_turn_decision(engine, snapshot, baseline_attack, decisions, fallback_used)
    return decision


def choose_builder_turn_plan(player, engine) -> BuilderTurnDecision:
    return plan_builder_turn(player, engine)


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
        "abilities": tuple(sorted(candidate.abilities, key=lambda ability: ability.value)),
        "cost": candidate.cost,
        "profile": candidate.generation_reason or "planned",
        "candidate_signature": candidate.signature,
    }


def extract_candidate_future_value(candidate_score, candidate, snapshot) -> float:
    future_value = (
        candidate_score.raw_stats
        + candidate_score.abilities
        + candidate_score.synergy
        + candidate_score.board_fit
        + candidate_score.survivability
        + candidate_score.matchup_defense
        + candidate_score.matchup_offense * 0.55
        + candidate_score.evasion * 0.45
        + candidate_score.kill_pressure * 0.3
        + max(0.0, candidate_score.expected_heal) * 0.2
        - abs(candidate_score.death_risk) * 0.28
        - candidate_score.immediate_pressure * IMMEDIATE_PRESSURE_DISCOUNT
        - candidate_score.expected_player_damage * EXPECTED_DAMAGE_DISCOUNT
        - max(0.0, candidate_score.unused_resources)
    )
    if Ability.HASTE in candidate.abilities:
        future_value -= HASTE_FUTURE_DISCOUNT
    if snapshot.enemy_flying_count > 0 and Ability.FLYING in candidate.abilities:
        future_value += 0.2
    return round(future_value, 4)


def score_resource_growth_action(snapshot, current_candidate_frontier, next_resource_candidate_frontier) -> float:
    if snapshot.own_total_resources >= 10:
        return float("-inf")
    current_best = max((projected.future_value for projected in current_candidate_frontier), default=0.0)
    next_best = max((projected.future_value for projected in next_resource_candidate_frontier), default=current_best)
    marginal_capacity = max(0.0, next_best - current_best)
    pressure = _base_survival_pressure(snapshot)
    horizon = max(0.18, RESOURCE_HORIZON_FACTOR - snapshot.own_total_resources * 0.08 - pressure * 0.09)
    level_bonus = max(0.0, RESOURCE_LOW_LEVEL_BONUS - snapshot.own_total_resources * RESOURCE_CAP_DECAY)
    midgame_plateau_penalty = max(0.0, snapshot.own_total_resources - 3) * 2.4
    board_safety = max(-1.5, min(1.8, snapshot.board_value_difference * 0.22 + snapshot.life_difference * 0.08))
    return round(level_bonus + marginal_capacity * horizon + board_safety - midgame_plateau_penalty, 4)


def _build_projected_candidates(player, engine, snapshot) -> tuple[list[BuilderProjectedCandidate], bool]:
    available_resources = player.available_resources()
    candidates = generate_builder_creature_candidates(snapshot, available_resources)
    enemy_creatures = list(engine.players[1 - player.player_id].battlefield)
    own_creatures = list(player.battlefield)
    legal = [candidate for candidate in candidates if is_legal_builder_candidate(candidate, available_resources)]
    full_budget = [candidate for candidate in legal if candidate.cost == available_resources]
    fallback_used = False
    chosen_frontier = full_budget
    if not chosen_frontier and legal:
        highest_cost = max(candidate.cost for candidate in legal)
        chosen_frontier = [candidate for candidate in legal if candidate.cost == highest_cost]
        fallback_used = highest_cost != available_resources
    projected: list[BuilderProjectedCandidate] = []
    for candidate in chosen_frontier:
        static_score = score_builder_creature_candidate(
            candidate,
            snapshot,
            available_resources=available_resources,
            enemy_creatures=enemy_creatures,
            own_creatures=own_creatures,
        )
        future_value = extract_candidate_future_value(static_score, candidate, snapshot)
        projected.append(
            BuilderProjectedCandidate(
                candidate=candidate,
                static_score=static_score,
                future_value=future_value,
            )
        )
    projected.sort(key=_projected_candidate_sort_key, reverse=True)
    return projected, fallback_used


def _build_action_decision(
    *,
    action_candidate: BuilderTurnActionCandidate,
    projection,
    baseline_attack: BuilderAttackDecision,
    predicted_attack: BuilderAttackDecision,
    snapshot,
    projected_candidate: BuilderProjectedCandidate | None,
    evaluated_candidate_count: int,
    fallback_used: bool = False,
) -> BuilderTurnDecision:
    current_frontier = [projected_candidate] if projected_candidate is not None else []
    next_frontier = []
    if action_candidate.action_kind == "resource":
        next_snapshot = build_builder_snapshot(projection.players[projection.player_id], projection)
        next_frontier, _ = _build_projected_candidates(projection.players[projection.player_id], projection, next_snapshot)
    creature_future_value = 0.0 if projected_candidate is None else projected_candidate.future_value * CREATURE_FUTURE_VALUE_WEIGHT
    resource_growth_value = (
        score_resource_growth_action(snapshot, current_frontier, next_frontier) * RESOURCE_GROWTH_WEIGHT
        if action_candidate.action_kind == "resource"
        else 0.0
    )
    lethal_value = predicted_attack.score.lethal_value - baseline_attack.score.lethal_value
    immediate_combat_delta = (
        predicted_attack.score.total
        - baseline_attack.score.total
        - lethal_value
    ) * IMMEDIATE_COMBAT_DELTA_WEIGHT
    readiness = _score_end_of_turn_readiness(projection, predicted_attack, snapshot) * READY_DEFENSE_WEIGHT
    survival = _score_action_survival_urgency(snapshot, projected_candidate, predicted_attack, action_candidate.action_kind) * SURVIVAL_URGENCY_WEIGHT
    risk = _score_action_risk(snapshot, projection, predicted_attack, projected_candidate, fallback_used)
    total = creature_future_value + resource_growth_value + immediate_combat_delta + readiness + survival + lethal_value + risk
    score = BuilderTurnScore(
        creature_future_value=round(creature_future_value, 4),
        resource_growth_value=round(resource_growth_value, 4),
        immediate_combat_delta=round(immediate_combat_delta, 4),
        expected_player_damage=round(predicted_attack.score.player_damage, 4),
        expected_enemy_kill_value=round(predicted_attack.score.enemy_kill_value, 4),
        expected_own_death_value=round(predicted_attack.score.own_death_risk, 4),
        end_of_turn_readiness=round(readiness, 4),
        survival_urgency=round(survival, 4),
        lethal_value=round(lethal_value, 4),
        risk_adjustment=round(risk, 4),
        total=round(total, 4),
        baseline_attack_score=round(baseline_attack.score.total, 4),
        projected_attack_score=round(predicted_attack.score.total, 4),
        search_was_exact=predicted_attack.search_metadata.exact_search,
        evaluated_candidate_count=evaluated_candidate_count,
    )
    return BuilderTurnDecision(
        action_candidate=action_candidate,
        score=score,
        predicted_attack_decision=predicted_attack,
        state_signature=projection.state_signature,
    )


def _shortlist_projected_candidates(projected_candidates: list[BuilderProjectedCandidate], ready_resources: int) -> list[BuilderProjectedCandidate]:
    if ready_resources <= 4:
        return projected_candidates
    selected: dict[tuple, BuilderProjectedCandidate] = {}

    def take(candidates: list[BuilderProjectedCandidate], count: int, reason: str) -> None:
        for projected in candidates[:count]:
            if projected.candidate.signature not in selected:
                selected[projected.candidate.signature] = BuilderProjectedCandidate(
                    candidate=projected.candidate,
                    static_score=projected.static_score,
                    future_value=projected.future_value,
                    shortlist_reasons=tuple(sorted(set(projected.shortlist_reasons + (reason,)))),
                )

    by_future = sorted(projected_candidates, key=_projected_candidate_sort_key, reverse=True)
    by_haste = sorted(
        [projected for projected in projected_candidates if Ability.HASTE in projected.candidate.abilities],
        key=lambda projected: (
            projected.static_score.immediate_pressure,
            projected.static_score.expected_player_damage,
            projected.future_value,
            projected.candidate.signature,
        ),
        reverse=True,
    )
    by_defense = sorted(
        projected_candidates,
        key=lambda projected: (
            projected.static_score.matchup_defense + projected.static_score.survivability + projected.static_score.board_fit,
            projected.future_value,
            projected.candidate.signature,
        ),
        reverse=True,
    )
    by_flying = sorted(
        [projected for projected in projected_candidates if Ability.FLYING in projected.candidate.abilities],
        key=_projected_candidate_sort_key,
        reverse=True,
    )
    by_tactical = sorted(
        [projected for projected in projected_candidates if {Ability.TRAMPLE, Ability.ENRAGED} & projected.candidate.abilities],
        key=_projected_candidate_sort_key,
        reverse=True,
    )
    by_sustain = sorted(
        [projected for projected in projected_candidates if {Ability.VIGILANT, Ability.LIFE_STEAL} & projected.candidate.abilities],
        key=_projected_candidate_sort_key,
        reverse=True,
    )

    take(by_future, 24, "future")
    take(by_haste, 8, "haste")
    take(by_defense, 6, "defense")
    take(by_flying, 4, "flying")
    take(by_tactical, 4, "tactical")
    take(by_sustain, 4, "sustain")
    shortlisted = list(selected.values())
    shortlisted.sort(key=_projected_candidate_sort_key, reverse=True)
    haste_candidates = [projected for projected in shortlisted if Ability.HASTE in projected.candidate.abilities]
    non_haste_candidates = [projected for projected in shortlisted if Ability.HASTE not in projected.candidate.abilities]
    capped_haste = haste_candidates[:8]
    capped = capped_haste + non_haste_candidates
    capped.sort(key=_projected_candidate_sort_key, reverse=True)
    return capped[:40]


def _score_end_of_turn_readiness(projection, predicted_attack: BuilderAttackDecision, snapshot) -> float:
    attacked_ids = set(predicted_attack.candidate.attacker_ids)
    enemy_pressure = max(0.6, snapshot.enemy_potential_attacker_count * 0.3 + snapshot.enemy_total_sw * 0.08 + snapshot.enemy_flying_count * 0.22)
    total = 0.0
    for unit in projection.own_units:
        if unit.unit_id in attacked_ids:
            ready = unit.has_ability(Ability.VIGILANT)
        else:
            ready = unit.is_ready()
        if unit.unit_id == projection.hypothetical_unit_id and unit.has_ability(Ability.HASTE) and ready:
            total += HASTE_READY_DEFENSE_BONUS
        if ready:
            total += estimate_creature_board_value(unit) * 0.05 * enemy_pressure
            if unit.has_ability(Ability.VIGILANT):
                total += VIGILANT_READINESS_BONUS
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


def _score_action_survival_urgency(snapshot, projected_candidate, predicted_attack, action_kind: str) -> float:
    pressure = _base_survival_pressure(snapshot)
    if action_kind == "resource":
        return -pressure * SURVIVAL_RESOURCE_PENALTY
    if projected_candidate is None:
        return 0.0
    defensive_value = projected_candidate.static_score.matchup_defense + projected_candidate.static_score.survivability + projected_candidate.static_score.board_fit
    if Ability.HASTE not in projected_candidate.candidate.abilities:
        defensive_value *= NON_HASTE_SURVIVAL_DISCOUNT
    if Ability.VIGILANT in projected_candidate.candidate.abilities:
        defensive_value += 0.6
    if Ability.HASTE in projected_candidate.candidate.abilities and not predicted_attack.candidate.attacker_ids:
        defensive_value += 0.4
    return pressure * defensive_value * SURVIVAL_CREATURE_DEFENSE_WEIGHT


def _score_action_risk(snapshot, projection, predicted_attack, projected_candidate, fallback_used: bool) -> float:
    pressure = _base_survival_pressure(snapshot)
    risk = 0.0
    if projected_candidate is not None and projection.hypothetical_unit_id is not None:
        new_unit = projection.get_unit_by_id(projection.hypothetical_unit_id)
        if new_unit is not None and not new_unit.is_ready():
            risk -= estimate_creature_board_value(new_unit) * pressure * RISK_PENALTY_WEIGHT
    if snapshot.enemy_has_board and not any(unit.is_ready() for unit in projection.own_units):
        risk -= 1.4 + pressure * 0.15
    if fallback_used:
        risk -= FULL_BUDGET_FALLBACK_PENALTY
    return risk


def _projected_candidate_sort_key(projected: BuilderProjectedCandidate) -> tuple:
    return (
        projected.future_value,
        projected.static_score.matchup_defense,
        projected.static_score.board_fit,
        projected.static_score.survivability,
        projected.static_score.kill_pressure,
        projected.candidate.signature,
    )


def _turn_decision_sort_key(decision: BuilderTurnDecision) -> tuple:
    candidate = decision.action_candidate
    return (
        decision.score.total,
        -decision.score.expected_player_damage,
        -decision.score.expected_own_death_value,
        decision.score.expected_enemy_kill_value,
        1 if candidate.action_kind == "creature" else 0,
        1 if candidate.creature_candidate is not None and Ability.HASTE in candidate.creature_candidate.abilities else 0,
        candidate.creature_candidate.signature if candidate.creature_candidate is not None else ("resource",),
    )


def _build_turn_state_signature(player, engine) -> tuple:
    return (
        engine.turn_number,
        engine.phase,
        player.player_id,
        player.life,
        engine.players[1 - player.player_id].life,
        player.total_resources(),
        player.available_resources(),
        engine.players[1 - player.player_id].total_resources(),
        engine.players[1 - player.player_id].available_resources(),
        tuple(
            (
                creature.unit_id,
                creature.aw,
                creature.vw,
                creature.sw,
                creature.lw,
                creature.current_hp,
                creature.tapped,
                creature.summoning_sick,
                tuple(sorted(ability.value for ability in creature.abilities)),
            )
            for creature in player.battlefield
        ),
        tuple(
            (
                creature.unit_id,
                creature.aw,
                creature.vw,
                creature.sw,
                creature.lw,
                creature.current_hp,
                creature.tapped,
                creature.summoning_sick,
                tuple(sorted(ability.value for ability in creature.abilities)),
            )
            for creature in engine.players[1 - player.player_id].battlefield
        ),
    )


def _debug_turn_decision(engine, snapshot, baseline_attack, decisions, fallback_used: bool) -> None:
    if not getattr(config, "BUILDER_AI_DEBUG", 0):
        return
    engine.log("Builder AI Turn:")
    engine.log(
        f"resources={snapshot.own_total_resources} ready={snapshot.own_ready_resources} "
        f"life={snapshot.own_life} enemy_life={snapshot.enemy_life} "
        f"board={snapshot.own_board_value:.1f} enemy_board={snapshot.enemy_board_value:.1f} "
        f"urgency={_base_survival_pressure(snapshot):.2f}"
    )
    engine.log(
        f"Baseline attack: {[*baseline_attack.candidate.attacker_ids]} "
        f"score={baseline_attack.score.total:.2f} lethal={baseline_attack.score.lethal_probability:.2f} "
        f"exact={baseline_attack.search_metadata.exact_search}"
    )
    if fallback_used:
        engine.log("Fallback: no full-budget build found, using highest legal cost frontier.")
    for index, decision in enumerate(decisions[:5], start=1):
        action = decision.action_candidate
        if action.action_kind == "resource":
            engine.log(
                f"{index}. Resource | growth={decision.score.resource_growth_value:.2f} "
                f"combat_delta={decision.score.immediate_combat_delta:.2f} total={decision.score.total:.2f}"
            )
            continue
        candidate = action.creature_candidate
        attack = decision.predicted_attack_decision
        abilities = ",".join(sorted(ability.value for ability in candidate.abilities)) or "-"
        engine.log(
            f"{index}. Creature {candidate.aw}/{candidate.vw}/{candidate.sw}/{candidate.lw} {abilities} "
            f"cost={candidate.cost} future={decision.score.creature_future_value:.2f} "
            f"combat_delta={decision.score.immediate_combat_delta:.2f} "
            f"ready_eot={decision.score.end_of_turn_readiness:.2f} "
            f"total={decision.score.total:.2f} shortlist={action.generation_reason} "
            f"attack={[*attack.candidate.attacker_ids]} exact={attack.search_metadata.exact_search}"
        )
    chosen = decisions[0].action_candidate
    if chosen.action_kind == "resource":
        engine.log("Decision: Resource")
    else:
        candidate = chosen.creature_candidate
        abilities = ",".join(sorted(ability.value for ability in candidate.abilities)) or "-"
        engine.log(f"Decision: Creature {candidate.aw}/{candidate.vw}/{candidate.sw}/{candidate.lw} {abilities}")


def _is_finite_score(score: BuilderTurnScore) -> bool:
    return all(isfinite(value) for value in score.__dict__.values() if isinstance(value, float))
