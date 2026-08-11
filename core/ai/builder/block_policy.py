from __future__ import annotations

from dataclasses import dataclass, field

import core.config as config
from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.models import Ability

from .cap_strategy import compute_builder_cap_context
from .combat_assignments import (
    convolve_damage_distributions,
    generate_block_assignment_tuples,
    get_available_blockers_for_defender,
    get_declared_attackers_for_defender,
    get_forced_block_map_from_engine,
    player_damage_distribution_for_combat,
)
from .combat_eval import estimate_builder_combat, estimate_unblocked_attack
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
from .scoring import estimate_creature_board_value

PLAYER_DAMAGE_TAKEN_PENALTY = 2.6
OWN_DEATH_VALUE_PENALTY = 1.35
ENEMY_KILL_VALUE_WEIGHT = 1.15
OWN_LIFESTEAL_WEIGHT = 0.85
ENEMY_LIFESTEAL_PENALTY = 0.95
TRAMPLE_DAMAGE_PENALTY = 0.55
LETHAL_PREVENTION_BONUS = 1000.0
LETHAL_PROBABILITY_PENALTY = 120.0
PREVENTED_PLAYER_DAMAGE_WEIGHT = 0.4
ENEMY_CREATURE_DAMAGE_WEIGHT = 0.18
OWN_CREATURE_DAMAGE_PENALTY = 0.14
BOARD_PRESERVATION_WEIGHT = 0.16
FLYING_BLOCKER_PRESERVATION_WEIGHT = 0.22
CAP_SLOT_RELEASE_WEIGHT = 0.6


@dataclass(frozen=True)
class BuilderBlockCandidate:
    assignments: tuple[tuple[int, int], ...]
    unblocked_attacker_ids: tuple[int, ...] = field(default=(), compare=False)
    forced_assignments: tuple[tuple[int, int], ...] = field(default=(), compare=False)
    generation_reason: str = field(default="generated", compare=False)


@dataclass(frozen=True)
class BuilderBlockScore:
    prevented_player_damage: float
    expected_player_damage_taken: float
    enemy_creature_damage: float
    own_creature_damage: float
    enemy_kill_value: float
    own_death_value: float
    own_lifesteal_value: float
    enemy_lifesteal_value: float
    trample_damage_taken: float
    board_preservation: float
    lethal_prevention: float
    total: float
    guaranteed_lethal: bool = False
    lethal_probability: float = 0.0
    debug_contributions: tuple[tuple[str, float, float, float], ...] = field(default_factory=tuple)


def generate_builder_block_candidates(defending_player, engine) -> list[BuilderBlockCandidate]:
    attackers = get_declared_attackers_for_defender(defending_player, engine)
    blockers = get_available_blockers_for_defender(defending_player, engine)
    forced_map = get_forced_block_map_from_engine(engine)
    assignment_tuples = generate_block_assignment_tuples(attackers, blockers, forced_map)
    attacker_ids = {attacker.unit_id for attacker in attackers}
    forced_assignments = tuple(sorted(forced_map.items()))
    candidates: list[BuilderBlockCandidate] = []
    for assignment in assignment_tuples:
        blocked = {attacker_id for attacker_id, _ in assignment}
        unblocked = tuple(sorted(attacker_ids - blocked))
        candidates.append(
            BuilderBlockCandidate(
                assignments=tuple(sorted(assignment)),
                unblocked_attacker_ids=unblocked,
                forced_assignments=forced_assignments,
            )
        )
    return sorted(candidates, key=lambda candidate: candidate.assignments)


def score_builder_block_candidate(candidate: BuilderBlockCandidate, defending_player, engine, *, cap_context=None) -> BuilderBlockScore:
    attackers = get_declared_attackers_for_defender(defending_player, engine)
    blockers = get_available_blockers_for_defender(defending_player, engine)
    assignments = dict(candidate.assignments)
    blocker_lookup = {blocker.unit_id: blocker for blocker in blockers}
    if cap_context is None:
        cap_context = compute_builder_cap_context(
            defending_player,
            engine,
            creature_cap=getattr(engine, "BUILDER_CREATURE_CAP", 5),
            resource_budget=defending_player.total_resources(),
        )

    damage_without_blocks = 0.0
    baseline_distributions: list[dict[int, float]] = []
    current_distributions: list[dict[int, float]] = []

    expected_player_damage_taken = 0.0
    enemy_creature_damage = 0.0
    own_creature_damage = 0.0
    enemy_kill_value = 0.0
    own_death_value = 0.0
    own_lifesteal_value = 0.0
    enemy_lifesteal_value = 0.0
    trample_damage_taken = 0.0
    flying_scarcity_bonus = 0.0
    slot_release_value = 0.0

    own_flying_blockers = [blocker for blocker in blockers if blocker.has_ability(Ability.FLYING)]
    enemy_flying_threats = [
        creature
        for creature in engine.players[1 - defending_player.player_id].battlefield
        if creature.has_ability(Ability.FLYING)
    ]

    for attacker in attackers:
        unblocked = estimate_unblocked_attack(attacker)
        damage_without_blocks += unblocked.player_damage
        baseline_distributions.append({int(unblocked.player_damage): 1.0})

        blocker_id = assignments.get(attacker.unit_id)
        if blocker_id is None:
            expected_player_damage_taken += unblocked.player_damage
            enemy_lifesteal_value += unblocked.attacker_heal
            current_distributions.append({int(unblocked.player_damage): 1.0})
            continue

        blocker = blocker_lookup.get(blocker_id)
        if blocker is None:
            expected_player_damage_taken += unblocked.player_damage
            enemy_lifesteal_value += unblocked.attacker_heal
            current_distributions.append({int(unblocked.player_damage): 1.0})
            continue

        estimate = estimate_builder_combat(attacker, blocker)
        expected_player_damage_taken += estimate.expected_player_damage
        trample_damage_taken += estimate.expected_player_damage
        enemy_creature_damage += estimate.expected_damage_to_attacker
        own_creature_damage += estimate.expected_damage_to_defender
        enemy_kill_value += estimate.attacker_death_probability * estimate_creature_board_value(attacker)
        own_death_value += estimate.defender_death_probability * estimate_creature_board_value(blocker)
        own_lifesteal_value += estimate.expected_defender_heal
        enemy_lifesteal_value += estimate.expected_attacker_heal
        current_distributions.append(player_damage_distribution_for_combat(attacker, estimate))
        if cap_context.at_cap and blocker.unit_id == cap_context.weakest_unit_id:
            slot_release_value += estimate.defender_death_probability * cap_context.cap_pressure * CAP_SLOT_RELEASE_WEIGHT

        if (
            blocker.has_ability(Ability.FLYING)
            and not attacker.has_ability(Ability.FLYING)
            and len(own_flying_blockers) <= 1
            and len(enemy_flying_threats) >= 2
        ):
            flying_scarcity_bonus += (1.0 - estimate.defender_death_probability) * FLYING_BLOCKER_PRESERVATION_WEIGHT

    total_damage_distribution = convolve_damage_distributions(current_distributions)
    baseline_distribution = convolve_damage_distributions(baseline_distributions)
    life_total = defending_player.life
    guaranteed_damage = min(total_damage_distribution.keys()) if total_damage_distribution else 0
    guaranteed_lethal = life_total > 0 and guaranteed_damage >= life_total
    lethal_probability = sum(probability for damage, probability in total_damage_distribution.items() if damage >= life_total)
    baseline_guaranteed_lethal = life_total > 0 and min(baseline_distribution.keys()) >= life_total if baseline_distribution else False
    baseline_lethal_probability = sum(probability for damage, probability in baseline_distribution.items() if damage >= life_total)

    prevented_player_damage = max(0.0, damage_without_blocks - expected_player_damage_taken)
    board_preservation = (
        (enemy_kill_value - own_death_value) * BOARD_PRESERVATION_WEIGHT
        + flying_scarcity_bonus
        + slot_release_value
    )
    lethal_prevention = 0.0
    if guaranteed_lethal:
        lethal_prevention -= LETHAL_PREVENTION_BONUS * 2
    elif baseline_guaranteed_lethal:
        lethal_prevention += LETHAL_PREVENTION_BONUS
    lethal_prevention += max(0.0, baseline_lethal_probability - lethal_probability) * LETHAL_PROBABILITY_PENALTY
    lethal_prevention -= lethal_probability * LETHAL_PROBABILITY_PENALTY

    total = (
        prevented_player_damage * PREVENTED_PLAYER_DAMAGE_WEIGHT
        - expected_player_damage_taken * PLAYER_DAMAGE_TAKEN_PENALTY
        + enemy_creature_damage * ENEMY_CREATURE_DAMAGE_WEIGHT
        - own_creature_damage * OWN_CREATURE_DAMAGE_PENALTY
        + enemy_kill_value * ENEMY_KILL_VALUE_WEIGHT
        - own_death_value * OWN_DEATH_VALUE_PENALTY
        + own_lifesteal_value * OWN_LIFESTEAL_WEIGHT
        - enemy_lifesteal_value * ENEMY_LIFESTEAL_PENALTY
        - trample_damage_taken * TRAMPLE_DAMAGE_PENALTY
        + board_preservation
        + lethal_prevention
    )
    debug_contributions = (
        ("prevented_player_damage", prevented_player_damage, PREVENTED_PLAYER_DAMAGE_WEIGHT, prevented_player_damage * PREVENTED_PLAYER_DAMAGE_WEIGHT),
        ("player_damage_taken", expected_player_damage_taken, -PLAYER_DAMAGE_TAKEN_PENALTY, -expected_player_damage_taken * PLAYER_DAMAGE_TAKEN_PENALTY),
        ("enemy_creature_damage", enemy_creature_damage, ENEMY_CREATURE_DAMAGE_WEIGHT, enemy_creature_damage * ENEMY_CREATURE_DAMAGE_WEIGHT),
        ("own_creature_damage", own_creature_damage, -OWN_CREATURE_DAMAGE_PENALTY, -own_creature_damage * OWN_CREATURE_DAMAGE_PENALTY),
        ("enemy_kill_value", enemy_kill_value, ENEMY_KILL_VALUE_WEIGHT, enemy_kill_value * ENEMY_KILL_VALUE_WEIGHT),
        ("own_death_value", own_death_value, -OWN_DEATH_VALUE_PENALTY, -own_death_value * OWN_DEATH_VALUE_PENALTY),
        ("own_lifesteal", own_lifesteal_value, OWN_LIFESTEAL_WEIGHT, own_lifesteal_value * OWN_LIFESTEAL_WEIGHT),
        ("enemy_lifesteal", enemy_lifesteal_value, -ENEMY_LIFESTEAL_PENALTY, -enemy_lifesteal_value * ENEMY_LIFESTEAL_PENALTY),
        ("trample_damage", trample_damage_taken, -TRAMPLE_DAMAGE_PENALTY, -trample_damage_taken * TRAMPLE_DAMAGE_PENALTY),
        ("board_preservation", board_preservation, 1.0, board_preservation),
        ("lethal_prevention", lethal_prevention, 1.0, lethal_prevention),
    )
    return BuilderBlockScore(
        prevented_player_damage=round(prevented_player_damage, 4),
        expected_player_damage_taken=round(expected_player_damage_taken, 4),
        enemy_creature_damage=round(enemy_creature_damage, 4),
        own_creature_damage=round(own_creature_damage, 4),
        enemy_kill_value=round(enemy_kill_value, 4),
        own_death_value=round(own_death_value, 4),
        own_lifesteal_value=round(own_lifesteal_value, 4),
        enemy_lifesteal_value=round(enemy_lifesteal_value, 4),
        trample_damage_taken=round(trample_damage_taken, 4),
        board_preservation=round(board_preservation, 4),
        lethal_prevention=round(lethal_prevention, 4),
        total=round(total, 4),
        guaranteed_lethal=guaranteed_lethal,
        lethal_probability=round(lethal_probability, 4),
        debug_contributions=tuple((name, round(raw, 4), round(weight, 4), round(contribution, 4)) for name, raw, weight, contribution in debug_contributions),
    )


def choose_builder_blocks(defending_player, engine) -> dict[int, int | None]:
    candidates = generate_builder_block_candidates(defending_player, engine)
    cap_context = compute_builder_cap_context(
        defending_player,
        engine,
        creature_cap=getattr(engine, "BUILDER_CREATURE_CAP", 5),
        resource_budget=defending_player.total_resources(),
    )
    scored = [
        (candidate, score_builder_block_candidate(candidate, defending_player, engine, cap_context=cap_context))
        for candidate in candidates
    ]
    scored.sort(key=_block_candidate_sort_key, reverse=True)
    if scored:
        best_candidate, best_score = scored[0]
    else:
        best_candidate = BuilderBlockCandidate(assignments=tuple())
        best_score = BuilderBlockScore(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    _debug_block_decision(engine, defending_player, scored, best_candidate)
    result = {attacker_id: None for attacker_id in engine.block_assignments}
    for attacker_id, blocker_id in best_candidate.assignments:
        result[attacker_id] = blocker_id
    setattr(engine.ai, "_last_builder_block_candidate", best_candidate)
    setattr(engine.ai, "_last_builder_block_score", best_score)
    return result


def _block_candidate_sort_key(scored_candidate: tuple[BuilderBlockCandidate, BuilderBlockScore]) -> tuple:
    candidate, score = scored_candidate
    return (
        score.total,
        -score.expected_player_damage_taken,
        -score.own_death_value,
        score.enemy_kill_value,
        tuple(candidate.assignments),
    )


def _debug_block_decision(engine, defending_player, scored_candidates, best_candidate) -> None:
    if not builder_debug_enabled():
        return
    if not hasattr(engine, "turn_number"):
        return
    if builder_debug_verbose():
        log_builder_state(engine, defending_player, decision="block")
    attackers = get_declared_attackers_for_defender(defending_player, engine)
    forced = get_forced_block_map_from_engine(engine)
    cap_context = compute_builder_cap_context(
        defending_player,
        engine,
        creature_cap=getattr(engine, "BUILDER_CREATURE_CAP", 5),
        resource_budget=defending_player.total_resources(),
    )
    available_blockers = get_available_blockers_for_defender(defending_player, engine)
    available_ids = {blocker.unit_id for blocker in available_blockers}
    unavailable_rows = []
    for blocker in sorted(defending_player.battlefield, key=lambda current: current.unit_id):
        if blocker.unit_id in available_ids:
            continue
        if getattr(blocker, "cannot_block", False):
            reason = "cannot_block"
        elif getattr(blocker, "tapped", False):
            reason = "tapped"
        elif int(getattr(blocker, "vw", 0)) <= 0:
            reason = "defense_zero"
        else:
            reason = "no_legal_targets"
        unavailable_rows.append(f"{blocker.unit_id}:{reason}")

    mandatory = {("block", tuple())}
    if scored_candidates:
        mandatory.add(_block_candidate_row_key(scored_candidates[0][0]))
    if len(scored_candidates) > 1:
        mandatory.add(_block_candidate_row_key(scored_candidates[1][0]))
    displayed = select_scored_rows(scored_candidates, top_n=builder_debug_top_n(), mandatory_keys=mandatory)

    header_pairs = [
        ("incoming", [attacker.unit_id for attacker in attackers]),
        ("available", [blocker.unit_id for blocker in available_blockers]),
        ("unavailable", unavailable_rows),
        ("assignments", len(scored_candidates)),
        ("cap_pressure", cap_context.cap_pressure),
        ("replacement_value", cap_context.replacement_value),
        ("best_replacement_value", cap_context.best_replacement_value),
        ("weakest_unit", cap_context.weakest_unit_id),
    ]
    if BUILDER_ABILITIES_ENABLED and forced:
        header_pairs.append(("forced", list(sorted(forced.items()))))
    emit_builder_debug_line(
        engine,
        "AI BLOCK",
        player=defending_player,
        decision="block",
        pairs=tuple(header_pairs),
    )
    for rank, (candidate, score) in enumerate(displayed, start=1):
        emit_builder_debug_line(
            engine,
            "AI BLOCK",
            player=defending_player,
            decision="block",
            pairs=(
                ("rank", rank),
                ("blocks", list(candidate.assignments)),
                ("unblocked", list(candidate.unblocked_attacker_ids)),
                ("total", score.total),
                ("taken", score.expected_player_damage_taken),
                ("prevented", score.prevented_player_damage),
                ("enemy_creature_damage", score.enemy_creature_damage),
                ("own_creature_damage", score.own_creature_damage),
                ("enemy_kill", score.enemy_kill_value),
                ("own_death", score.own_death_value),
                ("own_heal", score.own_lifesteal_value),
                ("enemy_heal", score.enemy_lifesteal_value),
                ("trample", score.trample_damage_taken),
                ("board_preservation", score.board_preservation),
                ("lethal_prevention", score.lethal_prevention),
                ("guaranteed_lethal", score.guaranteed_lethal),
                ("lethal_probability", score.lethal_probability),
            ),
        )
        if builder_debug_verbose():
            emit_builder_debug_line(
                engine,
                "AI BLOCK",
                player=defending_player,
                decision="block",
                pairs=(("rank", rank),) + contribution_pairs(score),
            )
    runner_up = scored_candidates[1] if len(scored_candidates) > 1 else None
    best_score = scored_candidates[0][1] if scored_candidates else None
    emit_builder_debug_line(
        engine,
        "AI BLOCK",
        player=defending_player,
        decision="block",
        pairs=(
            ("choose", [] if best_candidate is None else list(best_candidate.assignments)),
            ("total", 0.0 if best_score is None else best_score.total),
            ("runner_up", "-" if runner_up is None else list(runner_up[0].assignments)),
            ("runner_up_total", 0.0 if runner_up is None else runner_up[1].total),
            ("gap", 0.0 if runner_up is None or best_score is None else round(best_score.total - runner_up[1].total, 4)),
            ("delta_keys", "-" if runner_up is None or best_score is None else score_delta_keys(best_score, runner_up[1])),
        ),
    )
    if builder_debug_verbose() and builder_debug_include_fingerprints():
        from .turn_policy import build_builder_runtime_fingerprint

        before = build_builder_runtime_fingerprint(defending_player, engine)
        after = build_builder_runtime_fingerprint(defending_player, engine)
        log_builder_fingerprint(engine, defending_player, decision="block", before=before, after=after)


def _block_candidate_row_key(candidate: BuilderBlockCandidate) -> tuple:
    return ("block", tuple(candidate.assignments))
