from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from core.builder_rules import BUILDER_CREATURE_CAP
from core.models import Ability

from .attack_policy import BuilderAttackCandidate, BuilderAttackDecision, evaluate_best_builder_attack
from .candidates import generate_builder_creature_candidates, is_legal_builder_candidate, select_builder_creature_search_frontier
from .combat_eval import can_legally_block, estimate_builder_combat, estimate_unblocked_attack
from .scoring import score_builder_creature_candidate
from .search_budget import TURN_LOOKAHEAD_SEARCH_BUDGET
from .search_control import builder_search_should_stop, count_builder_search_work, store_bounded_cache_entry
from .snapshot import build_builder_snapshot
from .turn_projection import BuilderTurnProjection, project_attack_to_next_turn, project_creature_action, project_pass_action
from .turn_types import BuilderTurnActionCandidate

HORIZON_BUILD_LIMIT = 3
HORIZON_CANDIDATE_SCORING_LIMIT = 16
_HORIZON_MAIN_ACTION_CACHE: dict[tuple, tuple[tuple[int, str, object], ...]] = {}
NEXT_TURN_LETHAL_BONUS = 900.0
# Coverage is strategically mandatory, but it must stay on the same scale as
# the rest of the turn score.  The old value (520) flattened every meaningful
# distinction between possible flying blockers.
REPEATED_LETHAL_PREVENTION_BONUS = 48.0


@dataclass(frozen=True)
class BuilderEnemyAttackTimelineEntry:
    attacker_id: int
    attacker_profile: str
    first_attack_damage: float
    survives_first_attack: bool
    second_attack_damage: float
    second_attack_lethal: bool
    coverage_ready_turn: int | None
    blocker_ready_in_time: bool
    must_hold_as_blocker: bool
    coverage_prevents_repeated_lethal: bool
    cumulative_unavoidable_damage: float


@dataclass(frozen=True)
class BuilderHorizonReport:
    own_next_attack_damage: float = 0.0
    own_next_attack_lethal: bool = False
    own_next_attackers: tuple[int, ...] = ()
    enemy_future_blockers: tuple[tuple[int, tuple[int, ...]], ...] = ()
    enemy_blocker_ready_in_time: bool = False
    turns_to_own_lethal: int | None = None
    lethal_line_exact: bool = True
    lethal_line_fallback_used: bool = False
    known_enemy_attack_timeline: tuple[BuilderEnemyAttackTimelineEntry, ...] = field(default_factory=tuple)
    damage_before_coverage_ready: float = 0.0
    second_attack_damage: float = 0.0
    second_attack_lethal: bool = False
    coverage_ready_turn: int | None = None
    coverage_prevents_repeated_lethal: bool = False
    must_hold_as_blocker: bool = False
    cumulative_unavoidable_damage: float = 0.0
    offense_response_main_action: str = "pass"
    offense_response_attackers: tuple[int, ...] = ()
    defense_response_main_action: str = "pass"
    defense_response_attackers: tuple[int, ...] = ()


@dataclass(frozen=True)
class _HorizonLine:
    main_action_kind: str
    attack_decision: BuilderAttackDecision
    next_turn_projection: BuilderTurnProjection
    own_next_attack: BuilderAttackDecision
    enemy_future_blockers: tuple[tuple[int, tuple[int, ...]], ...]
    enemy_blocker_ready_in_time: bool
    timeline: tuple[BuilderEnemyAttackTimelineEntry, ...]
    damage_before_coverage_ready: float
    second_attack_damage: float
    second_attack_lethal: bool
    coverage_ready_turn: int | None
    coverage_prevents_repeated_lethal: bool
    must_hold_as_blocker: bool
    cumulative_unavoidable_damage: float


def evaluate_main_action_horizon(
    projection: BuilderTurnProjection,
    predicted_attack: BuilderAttackDecision,
    *,
    deadline: float | None = None,
) -> BuilderHorizonReport:
    enemy_turn_projection = project_attack_to_next_turn(
        projection,
        predicted_attack.candidate.attacker_ids,
        predicted_attack.defensive_response or predicted_attack.score.chosen_block_assignment,
    )
    known_enemy_attackers = tuple(
        unit.unit_id
        for unit in enemy_turn_projection.own_units
        if unit.is_ready() and unit.sw > 0
    )
    lines = _build_horizon_lines(enemy_turn_projection, known_enemy_attackers, deadline=deadline)
    if not lines:
        return BuilderHorizonReport()
    offense_line = min(lines, key=_offense_line_sort_key)
    defense_line = max(lines, key=_defense_line_sort_key)
    own_next_damage = round(offense_line.own_next_attack.score.guaranteed_player_damage, 4)
    exact = offense_line.attack_decision.search_metadata.exact_search and offense_line.own_next_attack.search_metadata.exact_search
    # A fallback result is useful as a heuristic, but it is not proof of a
    # forced lethal line and must never unlock the large lethal bonus.
    own_next_lethal = own_next_damage >= offense_line.next_turn_projection.enemy_life > 0 and exact
    return BuilderHorizonReport(
        own_next_attack_damage=own_next_damage,
        own_next_attack_lethal=own_next_lethal,
        own_next_attackers=tuple(offense_line.own_next_attack.candidate.attacker_ids),
        enemy_future_blockers=offense_line.enemy_future_blockers,
        enemy_blocker_ready_in_time=(not own_next_lethal and offense_line.enemy_blocker_ready_in_time),
        turns_to_own_lethal=1 if own_next_lethal else None,
        lethal_line_exact=exact,
        lethal_line_fallback_used=not exact,
        known_enemy_attack_timeline=defense_line.timeline,
        damage_before_coverage_ready=round(defense_line.damage_before_coverage_ready, 4),
        second_attack_damage=round(defense_line.second_attack_damage, 4),
        second_attack_lethal=defense_line.second_attack_lethal,
        coverage_ready_turn=defense_line.coverage_ready_turn,
        coverage_prevents_repeated_lethal=defense_line.coverage_prevents_repeated_lethal,
        must_hold_as_blocker=defense_line.must_hold_as_blocker,
        cumulative_unavoidable_damage=round(defense_line.cumulative_unavoidable_damage, 4),
        offense_response_main_action=offense_line.main_action_kind,
        offense_response_attackers=tuple(offense_line.attack_decision.candidate.attacker_ids),
        defense_response_main_action=defense_line.main_action_kind,
        defense_response_attackers=tuple(defense_line.attack_decision.candidate.attacker_ids),
    )


def evaluate_block_horizon(
    projection: BuilderTurnProjection,
    attack_candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
) -> BuilderHorizonReport:
    next_turn_projection = project_attack_to_next_turn(
        projection,
        attack_candidate.attacker_ids,
        block_assignment,
    )
    timeline, first_damage, second_damage, second_lethal, coverage_ready_turn, coverage_prevents, must_hold, cumulative = _analyze_known_enemy_timeline(
        projection,
        attack_candidate,
        block_assignment,
        next_turn_projection,
        known_enemy_attackers=attack_candidate.attacker_ids,
    )
    return BuilderHorizonReport(
        known_enemy_attack_timeline=timeline,
        damage_before_coverage_ready=round(first_damage if coverage_ready_turn == 1 else cumulative, 4),
        second_attack_damage=round(second_damage, 4),
        second_attack_lethal=second_lethal,
        coverage_ready_turn=coverage_ready_turn,
        coverage_prevents_repeated_lethal=coverage_prevents,
        must_hold_as_blocker=must_hold,
        cumulative_unavoidable_damage=round(cumulative, 4),
    )


def _build_horizon_lines(
    enemy_turn_projection: BuilderTurnProjection,
    known_enemy_attackers: tuple[int, ...],
    *,
    deadline: float | None,
) -> list[_HorizonLine]:
    lines: list[_HorizonLine] = []
    for main_action_kind, projected_state in _generate_enemy_main_projections(enemy_turn_projection, deadline=deadline):
        if lines and builder_search_should_stop(deadline):
            break
        count_builder_search_work("horizon_lines_started")
        best_attack = evaluate_best_builder_attack(
            projected_state.players[projected_state.player_id],
            projected_state,
            search_budget=TURN_LOOKAHEAD_SEARCH_BUDGET,
            include_counterattack=False,
            debug_output=False,
        )
        attack_options = [best_attack]
        if best_attack.candidate.attacker_ids:
            no_attack_score = next(
                (
                    score
                    for candidate, score in best_attack.scored_candidates
                    if not candidate.attacker_ids
                ),
                None,
            )
            if no_attack_score is not None:
                no_attack_decision = BuilderAttackDecision(
                    candidate=BuilderAttackCandidate(attacker_ids=()),
                    score=no_attack_score,
                    defensive_response=no_attack_score.chosen_block_assignment,
                    search_metadata=best_attack.search_metadata,
                )
                # The opponent may always decline to attack and retain every
                # blocker. Evaluate that adversarial response before the
                # deadline can truncate the horizon.
                attack_options = [no_attack_decision, best_attack]
        seen_attacks: set[tuple[int, ...]] = set()
        for attack_decision in attack_options:
            if lines and builder_search_should_stop(deadline):
                break
            attack_key = tuple(attack_decision.candidate.attacker_ids)
            if attack_key in seen_attacks:
                continue
            seen_attacks.add(attack_key)
            next_turn_projection = project_attack_to_next_turn(
                projected_state,
                attack_decision.candidate.attacker_ids,
                attack_decision.defensive_response or attack_decision.score.chosen_block_assignment,
            )
            chosen_blocks = attack_decision.defensive_response or attack_decision.score.chosen_block_assignment
            if next_turn_projection.own_life <= 0:
                own_next_attack = _empty_attack_decision(search_exact=attack_decision.search_metadata.exact_search)
            else:
                own_next_attack = evaluate_best_builder_attack(
                    next_turn_projection.players[next_turn_projection.player_id],
                    next_turn_projection,
                    search_budget=TURN_LOOKAHEAD_SEARCH_BUDGET,
                    include_counterattack=False,
                    debug_output=False,
                )
            relevant_threat_ids = _identify_relevant_future_threats(projected_state, known_enemy_attackers)
            timeline, first_damage, second_damage, second_lethal, coverage_ready_turn, coverage_prevents, must_hold, cumulative = _analyze_known_enemy_timeline(
                projected_state,
                attack_decision.candidate,
                chosen_blocks,
                next_turn_projection,
                known_enemy_attackers=relevant_threat_ids,
            )
            enemy_future_blockers = _legal_blocker_map(next_turn_projection, own_next_attack.candidate.attacker_ids)
            lines.append(
                _HorizonLine(
                    main_action_kind=main_action_kind,
                    attack_decision=attack_decision,
                    next_turn_projection=next_turn_projection,
                    own_next_attack=own_next_attack,
                    enemy_future_blockers=enemy_future_blockers,
                    enemy_blocker_ready_in_time=any(blockers for _, blockers in enemy_future_blockers),
                    timeline=timeline,
                    damage_before_coverage_ready=first_damage if coverage_ready_turn == 1 else cumulative,
                    second_attack_damage=second_damage,
                    second_attack_lethal=second_lethal,
                    coverage_ready_turn=coverage_ready_turn,
                    coverage_prevents_repeated_lethal=coverage_prevents,
                    must_hold_as_blocker=must_hold,
                    cumulative_unavoidable_damage=cumulative,
                )
            )
    return lines


def _generate_enemy_main_projections(enemy_turn_projection: BuilderTurnProjection, *, deadline: float | None = None):
    yield "pass", project_pass_action(enemy_turn_projection)
    if len(enemy_turn_projection.own_units) >= BUILDER_CREATURE_CAP:
        return
    counter_player = enemy_turn_projection.players[enemy_turn_projection.player_id]
    snapshot = build_builder_snapshot(counter_player, enemy_turn_projection)
    legal_builds = [
        candidate
        for candidate in generate_builder_creature_candidates(snapshot, enemy_turn_projection.own_ready_resources)
        if is_legal_builder_candidate(candidate, enemy_turn_projection.own_ready_resources)
    ]
    legal_builds = select_builder_creature_search_frontier(
        legal_builds,
        snapshot,
        limit=HORIZON_CANDIDATE_SCORING_LIMIT,
    )
    cache_key = (
        enemy_turn_projection.state_signature,
        enemy_turn_projection.own_ready_resources,
        enemy_turn_projection.enemy_life,
    )
    cached = _HORIZON_MAIN_ACTION_CACHE.get(cache_key)
    if cached is None:
        selected: dict[tuple, tuple[int, str, object]] = {}
        completed_scoring = True

        def consider(priority: int, label: str, candidate) -> None:
            if candidate is None:
                return
            existing = selected.get(candidate.key)
            if existing is None or priority < existing[0]:
                selected[candidate.key] = (priority, label, candidate)

        if legal_builds:
            scored = []
            for candidate in legal_builds:
                if scored and builder_search_should_stop(deadline):
                    completed_scoring = False
                    break
                scored.append((
                    score_builder_creature_candidate(
                        candidate,
                        snapshot,
                        available_resources=enemy_turn_projection.own_ready_resources,
                        enemy_creatures=list(enemy_turn_projection.enemy_units),
                        own_creatures=list(enemy_turn_projection.own_units),
                    ),
                    candidate,
                ))
                if builder_search_should_stop(deadline):
                    completed_scoring = False
                    break
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
            haste = [row for row in scored if row[1].has_haste]
            flying = [row for row in scored if row[1].has_ability(Ability.FLYING)]
            delayed = [row for row in scored if not row[1].has_haste]
            defensive = [row for row in scored if row[1].vw > 0]
            terminal = [
                row for row in scored
                if row[1].has_haste and (
                    row[0].immediate_pressure >= enemy_turn_projection.enemy_life
                    or row[0].expected_player_damage >= enemy_turn_projection.enemy_life
                )
            ]
            haste.sort(
                key=lambda row: (
                    row[0].immediate_pressure,
                    row[0].expected_player_damage,
                    row[0].attack_access_probability,
                    row[1].key,
                ),
                reverse=True,
            )
            flying.sort(
                key=lambda row: (
                    row[0].evasion,
                    row[0].matchup_offense,
                    row[1].key,
                ),
                reverse=True,
            )
            delayed.sort(
                key=lambda row: (
                    row[0].matchup_offense,
                    row[0].damage_delivery_probability,
                    -row[0].stranded_damage,
                    row[1].key,
                ),
                reverse=True,
            )
            defensive.sort(
                key=lambda row: (
                    row[0].repeated_block_value,
                    row[0].block_win_probability,
                    row[0].life_breakpoint,
                    row[1].key,
                ),
                reverse=True,
            )
            for current in terminal[:3]:
                consider(0, "build_terminal", current[1])
            consider(1, "build_haste", None if not haste else haste[0][1])
            consider(2, "build_flying", None if not flying else flying[0][1])
            consider(3, "build_delayed", None if not delayed else delayed[0][1])
            consider(4, "build_defense", None if not defensive else defensive[0][1])
            consider(5, "build_best", scored[0][1])
        cached = tuple(sorted(selected.values(), key=lambda row: (row[0], row[1], row[2].key)))
        if completed_scoring:
            store_bounded_cache_entry(_HORIZON_MAIN_ACTION_CACHE, cache_key, cached, max_entries=2048)
    ordered_candidates = list(cached)[:HORIZON_BUILD_LIMIT]
    for _, label, candidate in ordered_candidates:
        action = BuilderTurnActionCandidate(
            action_kind="creature",
            creature_candidate=candidate,
            projected_total_resources=enemy_turn_projection.own_total_resources,
            projected_ready_resources=max(0, enemy_turn_projection.own_ready_resources - candidate.cost),
            generation_reason=label,
        )
        yield label, project_creature_action(enemy_turn_projection, action)


def _identify_relevant_future_threats(projected_state: BuilderTurnProjection, known_enemy_attackers: tuple[int, ...]) -> tuple[int, ...]:
    seen = set(known_enemy_attackers)
    for unit in projected_state.own_units:
        if unit.unit_id in seen:
            continue
        if unit.has_ability(Ability.FLYING) and unit.sw > 0:
            seen.add(unit.unit_id)
            continue
        if unit.sw >= 5:
            seen.add(unit.unit_id)
    return tuple(sorted(seen))


def _empty_attack_decision(*, search_exact: bool) -> BuilderAttackDecision:
    from .attack_policy import BuilderAttackScore
    from .turn_types import BuilderSearchMetadata

    return BuilderAttackDecision(
        candidate=BuilderAttackCandidate(attacker_ids=()),
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
        defensive_response=(),
        search_metadata=BuilderSearchMetadata(
            exact_search=search_exact,
            generated_attack_candidates=0,
            evaluated_attack_candidates=0,
            generated_block_assignments=0,
            evaluated_block_assignments=0,
            pruned_candidates=0,
            search_budget_name=TURN_LOOKAHEAD_SEARCH_BUDGET.mode_name,
        ),
    )


def _analyze_known_enemy_timeline(
    attack_projection: BuilderTurnProjection,
    attack_candidate: BuilderAttackCandidate,
    block_assignment: tuple[tuple[int, int], ...],
    next_turn_projection: BuilderTurnProjection,
    *,
    known_enemy_attackers: tuple[int, ...],
) -> tuple[tuple[BuilderEnemyAttackTimelineEntry, ...], float, float, bool, int | None, bool, bool, float]:
    chosen_blocks = dict(block_assignment)
    attack_lookup = {unit.unit_id: unit for unit in attack_projection.own_units}
    relevant_attackers = tuple(
        attacker_id
        for attacker_id in known_enemy_attackers
        if attacker_id in attack_lookup and attack_lookup[attacker_id].has_ability(Ability.FLYING)
    )
    if not relevant_attackers:
        return (), 0.0, 0.0, False, None, False, False, 0.0
    defend_lookup = {unit.unit_id: unit for unit in attack_projection.enemy_units}
    next_enemy_lookup = {unit.unit_id: unit for unit in next_turn_projection.enemy_units}
    first_attack_total = max(0.0, float(attack_projection.enemy_life) - float(next_turn_projection.own_life))

    next_ready_blockers = [unit for unit in next_turn_projection.own_units if not unit.tapped and not unit.cannot_block]
    raw_second_attackers = [next_enemy_lookup[attacker_id] for attacker_id in relevant_attackers if attacker_id in next_enemy_lookup and next_enemy_lookup[attacker_id].sw > 0]
    second_raw_damage = sum(estimate_unblocked_attack(attacker).player_damage for attacker in raw_second_attackers)
    second_assignment, second_assignment_damage = _best_second_attack_assignment(raw_second_attackers, next_ready_blockers)
    second_assignment_map = dict(second_assignment)
    used_blockers = {blocker_id for _, blocker_id in second_assignment}
    coverage_ready_turn = 1 if raw_second_attackers and (second_assignment or any(_legal_blockers_for_attacker(attacker, next_ready_blockers) for attacker in raw_second_attackers)) else None
    must_hold = any(
        not _is_vigilant(next(unit for unit in next_ready_blockers if unit.unit_id == blocker_id))
        for blocker_id in used_blockers
    )
    second_attack_lethal = next_turn_projection.own_life > 0 and second_raw_damage >= next_turn_projection.own_life
    coverage_prevents_repeated_lethal = next_turn_projection.own_life > 0 and second_raw_damage >= next_turn_projection.own_life and second_assignment_damage < next_turn_projection.own_life
    cumulative = first_attack_total + (second_assignment_damage if coverage_ready_turn == 1 else second_raw_damage)

    timeline: list[BuilderEnemyAttackTimelineEntry] = []
    for attacker_id in relevant_attackers:
        attacker = attack_lookup.get(attacker_id)
        if attacker is None or attacker.sw <= 0:
            continue
        blocker_id = chosen_blocks.get(attacker_id)
        blocker = defend_lookup.get(blocker_id) if blocker_id is not None else None
        if attacker_id not in attack_candidate.attacker_ids:
            first_attack_damage = 0.0
            survives_first_attack = attacker_id in next_enemy_lookup
        elif blocker is None:
            first_attack_damage = estimate_unblocked_attack(attacker).player_damage
            survives_first_attack = attacker_id in next_enemy_lookup
        else:
            estimate = estimate_builder_combat(attacker, blocker)
            first_attack_damage = estimate.expected_player_damage
            survives_first_attack = estimate.attacker_death_probability < 1.0 and attacker_id in next_enemy_lookup
        second_attacker = next_enemy_lookup.get(attacker_id)
        legal_blockers = [] if second_attacker is None else _legal_blockers_for_attacker(second_attacker, next_ready_blockers)
        covered_second_damage = 0.0
        must_hold_blocker = False
        if second_attacker is not None:
            if attacker_id in second_assignment_map:
                assigned_blocker = next(unit for unit in next_ready_blockers if unit.unit_id == second_assignment_map[attacker_id])
                covered_second_damage = estimate_builder_combat(second_attacker, assigned_blocker).expected_player_damage
                must_hold_blocker = not _is_vigilant(assigned_blocker)
            else:
                covered_second_damage = estimate_unblocked_attack(second_attacker).player_damage
        raw_second_damage = 0.0 if second_attacker is None else estimate_unblocked_attack(second_attacker).player_damage
        entry_second_lethal = next_turn_projection.own_life > 0 and raw_second_damage >= next_turn_projection.own_life
        timeline.append(
            BuilderEnemyAttackTimelineEntry(
                attacker_id=attacker_id,
                attacker_profile=_attacker_profile(attacker),
                first_attack_damage=round(first_attack_damage, 4),
                survives_first_attack=survives_first_attack,
                second_attack_damage=round(raw_second_damage, 4),
                second_attack_lethal=entry_second_lethal,
                coverage_ready_turn=1 if legal_blockers else None,
                blocker_ready_in_time=bool(legal_blockers),
                must_hold_as_blocker=must_hold_blocker,
                coverage_prevents_repeated_lethal=entry_second_lethal and covered_second_damage < next_turn_projection.own_life,
                cumulative_unavoidable_damage=round(first_attack_damage + (covered_second_damage if legal_blockers else raw_second_damage), 4),
            )
        )
    return (
        tuple(timeline),
        round(first_attack_total, 4),
        round(second_raw_damage, 4),
        second_attack_lethal,
        coverage_ready_turn,
        coverage_prevents_repeated_lethal,
        must_hold,
        round(cumulative, 4),
    )


def _best_second_attack_assignment(attackers, blockers) -> tuple[tuple[tuple[int, int], ...], float]:
    if not attackers:
        return (), 0.0
    unblocked_damage = [estimate_unblocked_attack(attacker).player_damage for attacker in attackers]
    blocked_damage = []
    for attacker in attackers:
        row = []
        for blocker in blockers:
            if can_legally_block(attacker, blocker, require_ready=True):
                row.append(estimate_builder_combat(attacker, blocker).expected_player_damage)
            else:
                row.append(None)
        blocked_damage.append(row)

    @lru_cache(maxsize=None)
    def solve(attacker_index: int, used_mask: int) -> tuple[float, tuple[tuple[int, int], ...]]:
        if attacker_index >= len(attackers):
            return 0.0, ()
        best_total, best_assignment = solve(attacker_index + 1, used_mask)
        best_total += unblocked_damage[attacker_index]

        attacker = attackers[attacker_index]
        for blocker_index, blocker in enumerate(blockers):
            if used_mask & (1 << blocker_index):
                continue
            damage = blocked_damage[attacker_index][blocker_index]
            if damage is None:
                continue
            next_total, next_assignment = solve(attacker_index + 1, used_mask | (1 << blocker_index))
            total = damage + next_total
            assignment = ((attacker.unit_id, blocker.unit_id),) + next_assignment
            if total < best_total:
                best_total = total
                best_assignment = assignment
        return best_total, best_assignment

    best_damage, best_assignment = solve(0, 0)
    return tuple(sorted(best_assignment)), round(best_damage, 4)


def _legal_blocker_map(projection: BuilderTurnProjection, attacker_ids: tuple[int, ...]) -> tuple[tuple[int, tuple[int, ...]], ...]:
    blockers = [unit for unit in projection.enemy_units if not unit.tapped and not unit.cannot_block]
    rows = []
    for attacker_id in attacker_ids:
        attacker = projection.get_unit_by_id(attacker_id)
        if attacker is None:
            continue
        rows.append((attacker_id, tuple(blocker.unit_id for blocker in blockers if can_legally_block(attacker, blocker, require_ready=True))))
    return tuple(rows)


def _legal_blockers_for_attacker(attacker, blockers) -> list:
    return [blocker for blocker in blockers if can_legally_block(attacker, blocker, require_ready=True)]


def _attacker_profile(attacker) -> str:
    ability = next(iter(sorted((current.value for current in attacker.abilities))), "-")
    return f"{attacker.aw}/{attacker.vw}/{attacker.sw}/{attacker.current_hp}/{ability}"


def _is_vigilant(unit) -> bool:
    return unit.has_ability(Ability.VIGILANCE) or unit.has_ability(Ability.VIGILANT)


def _offense_line_sort_key(line: _HorizonLine) -> tuple:
    own_next_damage = line.own_next_attack.score.guaranteed_player_damage
    own_next_lethal = own_next_damage >= line.next_turn_projection.enemy_life > 0
    return (
        0 if line.next_turn_projection.own_life <= 0 else 1,
        0 if not own_next_lethal else 1,
        own_next_damage,
        0 if line.enemy_blocker_ready_in_time else 1,
        -line.attack_decision.score.player_damage,
        -line.cumulative_unavoidable_damage,
    )


def _defense_line_sort_key(line: _HorizonLine) -> tuple:
    return (
        1 if line.second_attack_lethal else 0,
        line.cumulative_unavoidable_damage,
        line.second_attack_damage,
        line.cumulative_unavoidable_damage,
        line.attack_decision.score.player_damage,
        1 if not line.coverage_prevents_repeated_lethal else 0,
    )
