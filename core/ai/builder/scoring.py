from __future__ import annotations

from statistics import mean

from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.models import Ability, BattlefieldCreature

from .combat_eval import (
    build_candidate_combatant_view,
    can_legally_be_forced_to_block,
    can_legally_block,
    coerce_builder_combatant,
    estimate_builder_combat,
    estimate_unblocked_attack,
)
from .types import BuilderCandidateScore, BuilderCreatureCandidate, BuilderStrategicSnapshot

RAW_STAT_WEIGHTS = {
    "aw": 1.0,
    "vw": 0.8,
    "sw": 1.3,
    "hp": 1.1,
}

ABILITY_BASE_WEIGHTS = {
    Ability.HASTE: 0.35,
    Ability.FLYING: 0.45,
    Ability.ENRAGED: 0.35,
    Ability.TRAMPLE: 0.25,
    Ability.VIGILANT: 0.4,
    Ability.LIFE_STEAL: 0.25,
}

SYNERGY_WEIGHTS = {
    "haste_trample": 0.45,
    "haste_flying": 0.4,
    "flying_high_sw": 0.4,
    "flying_enraged": 0.45,
    "trample_high_sw": 0.45,
    "trample_life_steal": 0.45,
    "life_steal_high_sw": 0.4,
    "vigilant_vw_lw": 0.5,
    "vigilant_life_steal": 0.3,
    "enraged_high_sw": 0.4,
}

ANTI_SYNERGY_WEIGHTS = {
    "life_steal_no_sw": -0.8,
    "trample_no_sw": -0.8,
    "haste_passive": -0.7,
    "vigilant_low_impact": -0.45,
    "enraged_no_targets": -0.55,
}

MATCHUP_WORST_CASE_WEIGHT = 0.7
MATCHUP_AVERAGE_WEIGHT = 0.3
EXPECTED_PLAYER_DAMAGE_WEIGHT = 1.3
EXPECTED_CREATURE_DAMAGE_WEIGHT = 0.55
KILL_PROBABILITY_WEIGHT = 1.4
DEATH_PROBABILITY_PENALTY = 1.45
EXPECTED_HEAL_WEIGHT = 0.8
DEFENSIVE_PREVENTED_DAMAGE_WEIGHT = 1.1
DEFENSIVE_KILL_WEIGHT = 0.8
DEFENSIVE_SURVIVAL_WEIGHT = 0.7
DEFENSIVE_DEATH_PENALTY = 0.95
DEFENSIVE_BREAKPOINT_KILL_WEIGHT = 1.1
DEFENSIVE_CONTEST_WEIGHT = 0.65
DEFENSIVE_UNRESOLVED_THREAT_PENALTY = 0.95
DEFENSIVE_STALL_ONLY_PENALTY = 1.3
DEFENSIVE_LOW_DEFENSE_PENALTY = 0.8
IMMEDIATE_LETHAL_BONUS_WEIGHT = 0.7
EVASION_IMMEDIATE_WEIGHT = 1.0
EVASION_FUTURE_WEIGHT = 0.55
FUTURE_LIFE_STEAL_BASELINE = 0.18
UNUSED_RESOURCE_WEIGHT = 0.18
FRAGILE_DAMAGE_SHELL_PENALTY = -2.2
ZERO_CONTACT_SHELL_PENALTY = -1.4
ZERO_IMPACT_SHELL_PENALTY = -2.6
BALANCED_BODY_BONUS = 0.55
TRADE_BODY_BONUS = 0.4
OPEN_HAND_GLASS_CANNON_PENALTY = -1.5
ZERO_OFFENSE_WALL_PENALTY = -1.35
LOW_CONTACT_BODY_PENALTY = -0.9
SOFT_WALL_UNRESOLVED_THREAT_PENALTY = -1.1
LOW_DAMAGE_BREAKPOINT_PENALTY = -0.85
DEFENSIVE_CONTACT_BONUS = 0.65


def estimate_creature_board_value(creature: BattlefieldCreature) -> float:
    value = (
        creature.aw * RAW_STAT_WEIGHTS["aw"]
        + creature.vw * RAW_STAT_WEIGHTS["vw"]
        + creature.sw * RAW_STAT_WEIGHTS["sw"]
        + creature.current_hp * RAW_STAT_WEIGHTS["hp"]
    )
    for ability in creature.abilities:
        value += ABILITY_BASE_WEIGHTS.get(ability, 0.0)
    return round(value, 3)


def score_builder_creature_candidate(
    candidate: BuilderCreatureCandidate,
    snapshot: BuilderStrategicSnapshot,
    *,
    available_resources: int | None = None,
    enemy_creatures: list | None = None,
    own_creatures: list | None = None,
) -> BuilderCandidateScore:
    enemy_creatures = [] if enemy_creatures is None else list(enemy_creatures)
    own_creatures = [] if own_creatures is None else list(own_creatures)
    raw_stats = _score_raw_stats(candidate)
    abilities = _score_abilities(candidate, snapshot)
    synergy = _score_synergy(candidate, snapshot)
    board_fit = _score_board_fit(candidate, snapshot)
    survivability = _score_survivability(candidate, snapshot)
    matchup = _score_candidate_matchups(candidate, snapshot, enemy_creatures, own_creatures)
    unused_resources = _score_unused_resources(candidate, available_resources)
    total = (
        raw_stats
        + abilities
        + synergy
        + board_fit
        + survivability
        + _score_shell_quality(candidate, snapshot)
        + matchup["immediate_pressure"]
        + matchup["matchup_offense"]
        + matchup["matchup_defense"]
        + matchup["evasion"]
        + matchup["kill_pressure"]
        + matchup["death_risk"]
        + unused_resources
    )
    return BuilderCandidateScore(
        raw_stats=round(raw_stats, 4),
        abilities=round(abilities, 4),
        synergy=round(synergy, 4),
        board_fit=round(board_fit, 4),
        immediate_pressure=round(matchup["immediate_pressure"], 4),
        survivability=round(survivability, 4),
        matchup_offense=round(matchup["matchup_offense"], 4),
        matchup_defense=round(matchup["matchup_defense"], 4),
        evasion=round(matchup["evasion"], 4),
        expected_player_damage=round(matchup["expected_player_damage"], 4),
        expected_heal=round(matchup["expected_heal"], 4),
        kill_pressure=round(matchup["kill_pressure"], 4),
        death_risk=round(matchup["death_risk"], 4),
        unused_resources=round(unused_resources, 4),
        total=round(total, 4),
    )


def _score_raw_stats(candidate: BuilderCreatureCandidate) -> float:
    bought_hp = max(0, candidate.lw - 1)
    return (
        candidate.aw * RAW_STAT_WEIGHTS["aw"]
        + candidate.vw * RAW_STAT_WEIGHTS["vw"]
        + candidate.sw * RAW_STAT_WEIGHTS["sw"]
        + bought_hp * RAW_STAT_WEIGHTS["hp"]
    )


def _score_abilities(candidate: BuilderCreatureCandidate, snapshot: BuilderStrategicSnapshot) -> float:
    score = sum(ABILITY_BASE_WEIGHTS.get(ability, 0.0) for ability in candidate.abilities)
    offense = candidate.aw + candidate.sw
    defense = candidate.vw + candidate.lw

    if Ability.HASTE in candidate.abilities:
        score += min(0.55, offense * 0.08)
        if snapshot.enemy_life <= 5:
            score += 0.25

    if Ability.FLYING in candidate.abilities:
        if snapshot.enemy_flying_count == 0:
            score += 0.25
        else:
            score -= min(1.4, snapshot.enemy_flying_count * 0.45 + candidate.sw * 0.08)

    if Ability.ENRAGED in candidate.abilities and snapshot.enemy_creature_count > 0:
        score += min(0.45, snapshot.enemy_creature_count * 0.08 + candidate.sw * 0.05)

    if Ability.TRAMPLE in candidate.abilities:
        score += min(0.35, candidate.sw * 0.08)

    if Ability.VIGILANT in candidate.abilities:
        score += min(0.45, candidate.aw * 0.05 + defense * 0.05)

    if Ability.LIFE_STEAL in candidate.abilities:
        score += FUTURE_LIFE_STEAL_BASELINE + min(0.25, candidate.sw * 0.05)
        if candidate.sw == 0:
            score -= 0.2

    return score


def _score_synergy(candidate: BuilderCreatureCandidate, snapshot: BuilderStrategicSnapshot) -> float:
    score = 0.0
    abilities = candidate.abilities
    high_sw = candidate.sw >= 3
    meaningful_defense = candidate.vw >= 2 or candidate.lw >= 3

    if {Ability.HASTE, Ability.TRAMPLE}.issubset(abilities):
        score += SYNERGY_WEIGHTS["haste_trample"]
    if {Ability.HASTE, Ability.FLYING}.issubset(abilities):
        score += SYNERGY_WEIGHTS["haste_flying"]
    if Ability.FLYING in abilities and high_sw:
        score += SYNERGY_WEIGHTS["flying_high_sw"]
    if {Ability.FLYING, Ability.ENRAGED}.issubset(abilities):
        score += SYNERGY_WEIGHTS["flying_enraged"]
    if Ability.TRAMPLE in abilities and high_sw:
        score += SYNERGY_WEIGHTS["trample_high_sw"]
    if {Ability.TRAMPLE, Ability.LIFE_STEAL}.issubset(abilities):
        score += SYNERGY_WEIGHTS["trample_life_steal"]
    if Ability.LIFE_STEAL in abilities and high_sw:
        score += SYNERGY_WEIGHTS["life_steal_high_sw"]
    if Ability.VIGILANT in abilities and meaningful_defense:
        score += SYNERGY_WEIGHTS["vigilant_vw_lw"]
    if {Ability.VIGILANT, Ability.LIFE_STEAL}.issubset(abilities):
        score += SYNERGY_WEIGHTS["vigilant_life_steal"]
    if Ability.ENRAGED in abilities and high_sw:
        score += SYNERGY_WEIGHTS["enraged_high_sw"]

    if Ability.LIFE_STEAL in abilities and candidate.sw == 0:
        score += ANTI_SYNERGY_WEIGHTS["life_steal_no_sw"]
    if Ability.TRAMPLE in abilities and candidate.sw == 0:
        score += ANTI_SYNERGY_WEIGHTS["trample_no_sw"]
    if Ability.HASTE in abilities and candidate.aw == 0 and candidate.sw == 0:
        score += ANTI_SYNERGY_WEIGHTS["haste_passive"]
    if Ability.VIGILANT in abilities and candidate.aw == 0 and candidate.vw == 0 and candidate.lw <= 1:
        score += ANTI_SYNERGY_WEIGHTS["vigilant_low_impact"]
    if Ability.ENRAGED in abilities and snapshot.enemy_creature_count == 0:
        score += ANTI_SYNERGY_WEIGHTS["enraged_no_targets"]

    return score


def _score_board_fit(candidate: BuilderCreatureCandidate, snapshot: BuilderStrategicSnapshot) -> float:
    score = 0.0
    offense = candidate.aw + candidate.sw
    defense = candidate.vw + candidate.lw

    if not snapshot.own_has_board:
        score += 0.25 + min(0.7, (candidate.aw + candidate.vw + candidate.sw + candidate.lw - 1) * 0.08)
    if snapshot.enemy_has_board and not snapshot.own_has_board:
        score += candidate.vw * 0.18 + max(0, candidate.lw - 1) * 0.18
        if Ability.VIGILANT in candidate.abilities:
            score += 0.3
    if snapshot.enemy_creature_count > 0 and snapshot.enemy_total_current_hp <= snapshot.enemy_creature_count * 2:
        score += candidate.sw * 0.1
    if snapshot.enemy_has_board and candidate.sw >= 1:
        one_life_targets = max(0, snapshot.enemy_creature_count * 2 - snapshot.enemy_total_current_hp)
        score += min(0.9, one_life_targets * 0.18 + candidate.sw * 0.04)
    if snapshot.enemy_has_board and candidate.vw >= 1 and candidate.sw >= 1:
        score += min(0.75, candidate.vw * 0.1 + candidate.sw * 0.12)
    if snapshot.board_value_difference >= 2.5:
        score += min(0.6, defense * 0.06)
    elif snapshot.board_value_difference <= -2.5:
        score += offense * 0.12
    return score


def _score_survivability(candidate: BuilderCreatureCandidate, snapshot: BuilderStrategicSnapshot) -> float:
    score = candidate.vw * 0.4 + max(0, candidate.lw - 1) * 0.55
    if Ability.VIGILANT in candidate.abilities:
        score += 0.22 + candidate.vw * 0.08
    if Ability.LIFE_STEAL in candidate.abilities and candidate.sw > 0:
        score += FUTURE_LIFE_STEAL_BASELINE + max(0, candidate.lw - 1) * 0.08
    if snapshot.enemy_has_board:
        score += min(0.6, snapshot.enemy_total_aw * 0.03)
        if candidate.vw <= 1 and snapshot.enemy_total_aw >= max(4, snapshot.enemy_creature_count * 3):
            score -= 0.45 + max(0, candidate.lw - 2) * 0.04
        if candidate.sw == 0 and snapshot.enemy_total_current_hp <= snapshot.enemy_creature_count * 2:
            score -= 0.35
    return score


def _score_shell_quality(candidate: BuilderCreatureCandidate, snapshot: BuilderStrategicSnapshot) -> float:
    offense = candidate.aw + candidate.sw
    defense = candidate.vw + candidate.lw
    score = 0.0
    if candidate.sw >= 3 and candidate.aw == 0 and candidate.vw == 0 and candidate.lw <= 2:
        score += FRAGILE_DAMAGE_SHELL_PENALTY
        if BUILDER_ABILITIES_ENABLED and snapshot.enemy_hand_count > 0:
            score += OPEN_HAND_GLASS_CANNON_PENALTY
    elif candidate.sw >= 3 and candidate.aw == 0 and candidate.lw <= 2:
        score += ZERO_CONTACT_SHELL_PENALTY
    if candidate.aw == 0 and candidate.vw == 0 and candidate.sw == 0:
        score += ZERO_IMPACT_SHELL_PENALTY
    if candidate.aw == 0 and candidate.sw == 0 and candidate.vw >= 1 and candidate.lw >= 4:
        pressure = snapshot.enemy_total_sw + snapshot.enemy_potential_attacker_count * 0.75
        if pressure < 4.0:
            score += ZERO_OFFENSE_WALL_PENALTY
        if snapshot.enemy_has_board:
            score += SOFT_WALL_UNRESOLVED_THREAT_PENALTY
    if candidate.aw == 0 and candidate.sw >= 4 and candidate.lw <= 2:
        score += LOW_CONTACT_BODY_PENALTY
    if snapshot.enemy_has_board and candidate.sw == 0 and candidate.vw <= 1 and candidate.lw >= 5:
        score -= 1.35
    if snapshot.enemy_has_board and candidate.sw >= 1 and candidate.vw >= 1:
        score += DEFENSIVE_CONTACT_BONUS
    if snapshot.enemy_has_board and candidate.sw == 0 and snapshot.enemy_total_current_hp <= snapshot.enemy_creature_count * 2:
        score += LOW_DAMAGE_BREAKPOINT_PENALTY
    if candidate.aw >= 1 and candidate.vw >= 1 and candidate.sw >= 1 and candidate.lw >= 2:
        score += BALANCED_BODY_BONUS
    if candidate.aw >= 1 and candidate.vw >= 2 and candidate.lw >= 3:
        score += TRADE_BODY_BONUS
    if snapshot.enemy_has_board and candidate.vw == 0 and candidate.lw <= 1:
        score -= 0.9
    if not snapshot.enemy_has_board and candidate.sw >= 3 and candidate.aw >= 1:
        score += 0.35
    if offense == 0 and defense <= 2:
        score -= 1.1
    if candidate.aw == 0 and candidate.sw > 0 and candidate.vw == 0 and candidate.lw <= 2 and snapshot.enemy_creature_count > 0:
        score -= 0.85
    return score


def _score_candidate_matchups(
    candidate: BuilderCreatureCandidate,
    snapshot: BuilderStrategicSnapshot,
    enemy_creatures: list,
    own_creatures: list,
) -> dict[str, float]:
    candidate_future = build_candidate_combatant_view(candidate, ready=True)
    candidate_immediate = build_candidate_combatant_view(candidate, ready=Ability.HASTE in candidate.abilities)
    future_enemy_blockers = [coerce_builder_combatant(creature, ready=True) for creature in enemy_creatures]
    immediate_enemy_blockers = [coerce_builder_combatant(creature) for creature in enemy_creatures]
    enemy_attackers = [coerce_builder_combatant(creature, ready=True) for creature in enemy_creatures]

    offensive = _evaluate_offensive_matchups(candidate_future, future_enemy_blockers, prefer_forced=Ability.ENRAGED in candidate.abilities)
    defensive = _evaluate_defensive_matchups(candidate_future, enemy_attackers)
    immediate_defense = _evaluate_immediate_defense(candidate_immediate, enemy_attackers)
    immediate = _evaluate_immediate_pressure(candidate_immediate, snapshot, immediate_enemy_blockers)
    evasion = _evaluate_evasion(candidate_future, candidate_immediate, snapshot, future_enemy_blockers, immediate_enemy_blockers)

    return {
        "matchup_offense": offensive["score"],
        "matchup_defense": defensive["score"] + immediate_defense["score"],
        "immediate_pressure": immediate["score"],
        "evasion": evasion["score"],
        "expected_player_damage": offensive["expected_player_damage"] + immediate["expected_player_damage"],
        "expected_heal": offensive["expected_heal"] + immediate["expected_heal"],
        "kill_pressure": offensive["kill_pressure"] + defensive["kill_pressure"] + immediate_defense["kill_pressure"],
        "death_risk": offensive["death_risk"] + defensive["death_risk"] + immediate_defense["death_risk"],
    }


def _evaluate_offensive_matchups(candidate_view, enemy_blockers: list, *, prefer_forced: bool) -> dict[str, float]:
    legal_normal_blockers = [blocker for blocker in enemy_blockers if can_legally_block(candidate_view, blocker, require_ready=True)]
    legal_forced_blockers = [blocker for blocker in enemy_blockers if can_legally_be_forced_to_block(candidate_view, blocker, require_ready=True)]
    unblocked = estimate_unblocked_attack(candidate_view)
    unblocked_score = _score_offensive_estimate(
        player_damage=unblocked.player_damage,
        creature_damage=0.0,
        kill_probability=0.0,
        death_probability=0.0,
        heal=unblocked.attacker_heal,
    )
    if not legal_normal_blockers:
        return {
            "score": unblocked_score,
            "expected_player_damage": unblocked.player_damage,
            "expected_heal": unblocked.attacker_heal,
            "kill_pressure": 0.0,
            "death_risk": 0.0,
        }

    blocker_estimates = [_offensive_matchup_summary(candidate_view, blocker) for blocker in legal_normal_blockers]
    worst_score = min(summary["score"] for summary in blocker_estimates)
    average_score = mean(summary["score"] for summary in blocker_estimates)
    offense_score = worst_score * MATCHUP_WORST_CASE_WEIGHT + average_score * MATCHUP_AVERAGE_WEIGHT
    chosen_summary = min(blocker_estimates, key=lambda summary: summary["score"])

    if prefer_forced and legal_forced_blockers:
        forced_summaries = [_offensive_matchup_summary(candidate_view, blocker) for blocker in legal_forced_blockers]
        best_forced = max(forced_summaries, key=lambda summary: summary["score"])
        offense_score = max(offense_score, best_forced["score"], unblocked_score)
        chosen_summary = best_forced if best_forced["score"] >= max(offense_score, unblocked_score) else chosen_summary
        if unblocked_score >= best_forced["score"] and unblocked_score >= offense_score:
            chosen_summary = {
                "score": unblocked_score,
                "expected_player_damage": unblocked.player_damage,
                "expected_heal": unblocked.attacker_heal,
                "kill_pressure": 0.0,
                "death_risk": 0.0,
            }
            offense_score = unblocked_score

    return {
        "score": offense_score,
        "expected_player_damage": chosen_summary["expected_player_damage"],
        "expected_heal": chosen_summary["expected_heal"],
        "kill_pressure": chosen_summary["kill_pressure"],
        "death_risk": chosen_summary["death_risk"],
    }


def _offensive_matchup_summary(candidate_view, blocker_view) -> dict[str, float]:
    estimate = estimate_builder_combat(candidate_view, blocker_view)
    score = _score_offensive_estimate(
        player_damage=estimate.expected_player_damage,
        creature_damage=estimate.expected_damage_to_defender,
        kill_probability=estimate.defender_death_probability,
        death_probability=estimate.attacker_death_probability,
        heal=estimate.expected_attacker_heal,
    )
    return {
        "score": score,
        "expected_player_damage": estimate.expected_player_damage,
        "expected_heal": estimate.expected_attacker_heal,
        "kill_pressure": estimate.defender_death_probability * KILL_PROBABILITY_WEIGHT,
        "death_risk": -(estimate.attacker_death_probability * DEATH_PROBABILITY_PENALTY),
    }


def _score_offensive_estimate(
    *,
    player_damage: float,
    creature_damage: float,
    kill_probability: float,
    death_probability: float,
    heal: float,
) -> float:
    return (
        player_damage * EXPECTED_PLAYER_DAMAGE_WEIGHT
        + creature_damage * EXPECTED_CREATURE_DAMAGE_WEIGHT
        + kill_probability * KILL_PROBABILITY_WEIGHT
        - death_probability * DEATH_PROBABILITY_PENALTY
        + heal * EXPECTED_HEAL_WEIGHT
    )


def _evaluate_defensive_matchups(candidate_view, enemy_attackers: list) -> dict[str, float]:
    legal_attackers = [enemy for enemy in enemy_attackers if can_legally_block(enemy, candidate_view, require_ready=False)]
    if not legal_attackers:
        return {"score": 0.0, "kill_pressure": 0.0, "death_risk": 0.0}

    summaries = []
    for enemy in legal_attackers:
        estimate = estimate_builder_combat(enemy, candidate_view)
        prevented_damage = max(0.0, enemy.sw - estimate.expected_player_damage)
        kill_breakpoint = 0.0
        if getattr(enemy, "current_hp", 0) > 0:
            kill_breakpoint = min(1.0, candidate_view.sw / max(1, enemy.current_hp))
        contest_ratio = min(1.3, candidate_view.vw / max(1, enemy.aw))
        unresolved_threat = (1.0 - estimate.attacker_death_probability) * (
            enemy.sw * DEFENSIVE_UNRESOLVED_THREAT_PENALTY + enemy.aw * 0.18
        )
        stall_only_penalty = 0.0
        if candidate_view.sw == 0:
            stall_only_penalty += DEFENSIVE_STALL_ONLY_PENALTY * max(0.35, 1.0 - estimate.attacker_death_probability)
        if candidate_view.vw <= 1 and enemy.aw >= 4:
            stall_only_penalty += DEFENSIVE_LOW_DEFENSE_PENALTY
        score = (
            prevented_damage * DEFENSIVE_PREVENTED_DAMAGE_WEIGHT
            + estimate.attacker_death_probability * DEFENSIVE_KILL_WEIGHT
            + kill_breakpoint * estimate.attacker_death_probability * DEFENSIVE_BREAKPOINT_KILL_WEIGHT
            + contest_ratio * DEFENSIVE_CONTEST_WEIGHT
            + (1.0 - estimate.defender_death_probability) * DEFENSIVE_SURVIVAL_WEIGHT
            - estimate.defender_death_probability * DEFENSIVE_DEATH_PENALTY
            - unresolved_threat
            - stall_only_penalty
        )
        summaries.append(
            {
                "score": score,
                "kill_pressure": estimate.attacker_death_probability * DEFENSIVE_KILL_WEIGHT,
                "death_risk": -(estimate.defender_death_probability * DEFENSIVE_DEATH_PENALTY),
            }
        )
    average_score = mean(summary["score"] for summary in summaries)
    return {
        "score": average_score,
        "kill_pressure": mean(summary["kill_pressure"] for summary in summaries),
        "death_risk": mean(summary["death_risk"] for summary in summaries),
    }


def _evaluate_immediate_pressure(candidate_view, snapshot: BuilderStrategicSnapshot, immediate_enemy_blockers: list) -> dict[str, float]:
    if not candidate_view.has_ability(Ability.HASTE):
        return {"score": 0.0, "expected_player_damage": 0.0, "expected_heal": 0.0}

    legal_blockers = [blocker for blocker in immediate_enemy_blockers if can_legally_block(candidate_view, blocker, require_ready=True)]
    if not legal_blockers:
        unblocked = estimate_unblocked_attack(candidate_view)
        lethal_bonus = IMMEDIATE_LETHAL_BONUS_WEIGHT if unblocked.player_damage >= snapshot.enemy_life else 0.0
        return {
            "score": unblocked.player_damage * EXPECTED_PLAYER_DAMAGE_WEIGHT + unblocked.attacker_heal * EXPECTED_HEAL_WEIGHT + lethal_bonus,
            "expected_player_damage": unblocked.player_damage,
            "expected_heal": unblocked.attacker_heal,
        }

    offensive = _evaluate_offensive_matchups(candidate_view, immediate_enemy_blockers, prefer_forced=Ability.ENRAGED in candidate_view.abilities)
    lethal_bonus = IMMEDIATE_LETHAL_BONUS_WEIGHT if offensive["expected_player_damage"] >= snapshot.enemy_life else 0.0
    return {
        "score": offensive["score"] + lethal_bonus,
        "expected_player_damage": offensive["expected_player_damage"],
        "expected_heal": offensive["expected_heal"],
    }


def _evaluate_immediate_defense(candidate_view, enemy_attackers: list) -> dict[str, float]:
    if not candidate_view.has_ability(Ability.HASTE):
        return {"score": 0.0, "kill_pressure": 0.0, "death_risk": 0.0}
    defensive = _evaluate_defensive_matchups(candidate_view, enemy_attackers)
    return {
        "score": defensive["score"],
        "kill_pressure": defensive["kill_pressure"],
        "death_risk": defensive["death_risk"],
    }


def _evaluate_evasion(
    candidate_future,
    candidate_immediate,
    snapshot: BuilderStrategicSnapshot,
    future_enemy_blockers: list,
    immediate_enemy_blockers: list,
) -> dict[str, float]:
    future_legal_blockers = [blocker for blocker in future_enemy_blockers if can_legally_block(candidate_future, blocker, require_ready=True)]
    immediate_legal_blockers = [blocker for blocker in immediate_enemy_blockers if can_legally_block(candidate_immediate, blocker, require_ready=True)]
    if future_legal_blockers:
        if candidate_future.has_ability(Ability.FLYING):
            contested_penalty = -(2.0 + min(1.3, len(future_legal_blockers) * 0.45 + candidate_future.sw * 0.12))
            return {"score": contested_penalty}
        return {"score": 0.0}

    future_value = candidate_future.sw * EVASION_FUTURE_WEIGHT
    if snapshot.enemy_life <= 6:
        future_value += candidate_future.sw * 0.12
    immediate_value = 0.0
    if candidate_immediate.has_ability(Ability.HASTE) and not immediate_legal_blockers:
        immediate_value = candidate_immediate.sw * EVASION_IMMEDIATE_WEIGHT
    return {"score": future_value + immediate_value}


def _score_unused_resources(candidate: BuilderCreatureCandidate, available_resources: int | None) -> float:
    if available_resources is None:
        return 0.0
    unused = max(0, available_resources - candidate.cost)
    return -(unused * UNUSED_RESOURCE_WEIGHT)
