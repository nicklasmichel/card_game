from __future__ import annotations

from functools import lru_cache
from itertools import combinations
from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.models import Ability, BattlefieldCreature

from .combat_eval import (
    BuilderCombatantView,
    build_candidate_combatant_view,
    can_legally_be_forced_to_block,
    can_legally_block,
    coerce_builder_combatant,
    estimate_builder_combat,
    estimate_unblocked_attack,
    summarize_builder_combat_matchup,
)
from .types import BuilderCandidateScore, BuilderCreatureCandidate, BuilderStrategicSnapshot

RAW_STAT_WEIGHTS = {
    "aw": 0.2,
    "vw": 0.18,
    "sw": 0.22,
    "hp": 0.14,
}

ABILITY_BASE_WEIGHTS = {
    Ability.HASTE: 0.0,
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
FRAGILE_DAMAGE_SHELL_PENALTY = -2.35
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
    view = coerce_builder_combatant(creature)
    return _estimate_creature_board_value_cached(
        view.aw,
        view.vw,
        view.sw,
        view.current_hp,
        tuple(sorted(ability.value for ability in view.abilities)),
    )


@lru_cache(maxsize=4096)
def _estimate_creature_board_value_cached(aw: int, vw: int, sw: int, current_hp: int, abilities: tuple[str, ...]) -> float:
    value = (
        aw * RAW_STAT_WEIGHTS["aw"]
        + vw * RAW_STAT_WEIGHTS["vw"]
        + sw * RAW_STAT_WEIGHTS["sw"]
        + current_hp * RAW_STAT_WEIGHTS["hp"]
    )
    for ability_name in abilities:
        value += ABILITY_BASE_WEIGHTS.get(Ability(ability_name), 0.0)
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
        attack_access_probability=round(matchup["attack_access_probability"], 4),
        block_win_probability=round(matchup["block_win_probability"], 4),
        attacker_kill_probability=round(matchup["attacker_kill_probability"], 4),
        blocker_survival_probability=round(matchup["blocker_survival_probability"], 4),
        damage_delivery_probability=round(matchup["damage_delivery_probability"], 4),
        stranded_damage=round(matchup["stranded_damage"], 4),
        overkill_damage=round(matchup["overkill_damage"], 4),
        life_breakpoint=round(matchup["life_breakpoint"], 4),
        repeated_block_value=round(matchup["repeated_block_value"], 4),
        immediate_prevented_damage=round(matchup["immediate_prevented_damage"], 4),
        repeated_prevented_damage=round(matchup["repeated_prevented_damage"], 4),
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
    die_sides = snapshot.combat_die_sides
    candidate_future = build_candidate_combatant_view(candidate, ready=True)
    candidate_immediate = build_candidate_combatant_view(candidate, ready=Ability.HASTE in candidate.abilities)
    future_enemy_blockers = [coerce_builder_combatant(creature, ready=True) for creature in enemy_creatures]
    immediate_enemy_blockers = [coerce_builder_combatant(creature) for creature in enemy_creatures]
    enemy_attackers = [coerce_builder_combatant(creature, ready=True) for creature in enemy_creatures]
    own_blockers = [coerce_builder_combatant(creature) for creature in own_creatures]

    offensive = _evaluate_offensive_matchups(
        candidate_future,
        future_enemy_blockers,
        prefer_forced=Ability.ENRAGED in candidate.abilities,
        die_sides=die_sides,
    )
    future_defense = _evaluate_defensive_matchups(candidate_future, enemy_attackers, die_sides=die_sides)
    immediate_defense = _evaluate_marginal_immediate_defense(
        candidate_immediate,
        enemy_attackers,
        own_blockers,
        die_sides=die_sides,
    )
    immediate = _evaluate_immediate_pressure(candidate_immediate, snapshot, immediate_enemy_blockers, die_sides=die_sides)
    evasion = _evaluate_evasion(candidate_future, candidate_immediate, snapshot, future_enemy_blockers, immediate_enemy_blockers)

    return {
        "matchup_offense": offensive["score"],
        "matchup_defense": future_defense["score"] + immediate_defense["score"],
        "immediate_pressure": immediate["score"],
        "evasion": evasion["score"],
        "expected_player_damage": offensive["expected_player_damage"] + immediate["expected_player_damage"],
        "expected_heal": offensive["expected_heal"] + immediate["expected_heal"],
        "kill_pressure": offensive["kill_pressure"] + future_defense["kill_pressure"] + immediate_defense["kill_pressure"],
        "death_risk": offensive["death_risk"] + future_defense["death_risk"] + immediate_defense["death_risk"],
        "attack_access_probability": offensive["attack_access_probability"],
        "block_win_probability": max(future_defense["block_win_probability"], immediate_defense["block_win_probability"]),
        "attacker_kill_probability": max(offensive["attacker_kill_probability"], future_defense["attacker_kill_probability"], immediate_defense["attacker_kill_probability"]),
        "blocker_survival_probability": max(future_defense["blocker_survival_probability"], immediate_defense["blocker_survival_probability"]),
        "damage_delivery_probability": max(offensive["damage_delivery_probability"], immediate["damage_delivery_probability"]),
        "stranded_damage": offensive["stranded_damage"],
        "overkill_damage": offensive["overkill_damage"],
        "life_breakpoint": max(future_defense["life_breakpoint"], immediate_defense["life_breakpoint"]),
        "repeated_block_value": future_defense["repeated_block_value"] + immediate_defense["repeated_block_value"],
        "immediate_prevented_damage": immediate_defense["immediate_prevented_damage"],
        "repeated_prevented_damage": future_defense["repeated_prevented_damage"] + immediate_defense["repeated_prevented_damage"],
    }


def _evaluate_offensive_matchups(candidate_view, enemy_blockers: list, *, prefer_forced: bool, die_sides: int) -> dict[str, float]:
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
            "attack_access_probability": 1.0 if unblocked.player_damage > 0 else 0.0,
            "attacker_kill_probability": 0.0,
            "damage_delivery_probability": 1.0 if unblocked.player_damage > 0 else 0.0,
            "stranded_damage": 0.0,
            "overkill_damage": 0.0,
        }

    blocker_estimates = [_offensive_matchup_summary(candidate_view, blocker, die_sides=die_sides) for blocker in legal_normal_blockers]
    chosen_summary = min(blocker_estimates, key=lambda summary: summary["score"])
    offense_score = chosen_summary["score"]

    if prefer_forced and legal_forced_blockers:
        forced_summaries = [_offensive_matchup_summary(candidate_view, blocker, die_sides=die_sides) for blocker in legal_forced_blockers]
        best_forced = max(forced_summaries, key=lambda summary: summary["score"])
        best_forced_score = max(best_forced["score"], unblocked_score)
        if best_forced_score > offense_score:
            offense_score = best_forced_score
        if unblocked_score >= best_forced["score"] and unblocked_score >= chosen_summary["score"]:
            chosen_summary = {
                "score": unblocked_score,
                "expected_player_damage": unblocked.player_damage,
                "expected_heal": unblocked.attacker_heal,
                "kill_pressure": 0.0,
                "death_risk": 0.0,
                "attack_access_probability": 1.0 if unblocked.player_damage > 0 else 0.0,
                "attacker_kill_probability": 0.0,
                "damage_delivery_probability": 1.0 if unblocked.player_damage > 0 else 0.0,
                "stranded_damage": 0.0,
                "overkill_damage": 0.0,
            }
        elif best_forced["score"] >= chosen_summary["score"]:
            chosen_summary = best_forced

    return {
        "score": offense_score,
        "expected_player_damage": chosen_summary["expected_player_damage"],
        "expected_heal": chosen_summary["expected_heal"],
        "kill_pressure": chosen_summary["kill_pressure"],
        "death_risk": chosen_summary["death_risk"],
        "attack_access_probability": chosen_summary["attack_access_probability"],
        "attacker_kill_probability": chosen_summary["attacker_kill_probability"],
        "damage_delivery_probability": chosen_summary["damage_delivery_probability"],
        "stranded_damage": chosen_summary["stranded_damage"],
        "overkill_damage": chosen_summary["overkill_damage"],
    }


def _offensive_matchup_summary(candidate_view, blocker_view, *, die_sides: int) -> dict[str, float]:
    estimate = estimate_builder_combat(candidate_view, blocker_view, die_sides)
    matchup = summarize_builder_combat_matchup(candidate_view, blocker_view, die_sides)
    blocker_value = estimate_creature_board_value(blocker_view)
    attacker_value = estimate_creature_board_value(candidate_view)
    delivered_creature_damage = matchup.expected_damage_to_blocker
    score = _score_offensive_estimate(
        player_damage=estimate.expected_player_damage,
        creature_damage=delivered_creature_damage,
        kill_probability=estimate.defender_death_probability,
        death_probability=estimate.attacker_death_probability,
        heal=estimate.expected_attacker_heal,
    )
    score += matchup.attack_access_probability * 0.9
    score += matchup.damage_delivery_probability * 0.6
    score += estimate.attacker_survival_probability * 0.75
    score += estimate.defender_death_probability * blocker_value * 0.08
    score -= matchup.stranded_damage * 0.95
    score -= matchup.overkill_damage * 0.22
    score -= estimate.attacker_death_probability * attacker_value * 0.08
    if candidate_view.aw <= 1 and not candidate_view.has_ability(Ability.FLYING):
        score -= max(0.0, 0.65 - matchup.attack_access_probability) * max(1.0, float(candidate_view.sw))
    return {
        "score": score,
        "expected_player_damage": estimate.expected_player_damage,
        "expected_heal": estimate.expected_attacker_heal,
        "kill_pressure": estimate.defender_death_probability * KILL_PROBABILITY_WEIGHT,
        "death_risk": -(estimate.attacker_death_probability * DEATH_PROBABILITY_PENALTY),
        "attack_access_probability": matchup.attack_access_probability,
        "attacker_kill_probability": matchup.attacker_kill_probability,
        "damage_delivery_probability": matchup.damage_delivery_probability,
        "stranded_damage": matchup.stranded_damage,
        "overkill_damage": matchup.overkill_damage,
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


def _evaluate_defensive_matchups(candidate_view, enemy_attackers: list, *, die_sides: int) -> dict[str, float]:
    legal_attackers = [enemy for enemy in enemy_attackers if can_legally_block(enemy, candidate_view, require_ready=False)]
    if not legal_attackers:
        return {
            "score": 0.0,
            "kill_pressure": 0.0,
            "death_risk": 0.0,
            "repeated_block_value": 0.0,
            "block_win_probability": 0.0,
            "attacker_kill_probability": 0.0,
            "blocker_survival_probability": 0.0,
            "life_breakpoint": 0.0,
            "immediate_prevented_damage": 0.0,
            "repeated_prevented_damage": 0.0,
        }

    summaries = []
    for enemy in legal_attackers:
        estimate = estimate_builder_combat(enemy, candidate_view, die_sides)
        matchup = summarize_builder_combat_matchup(enemy, candidate_view, die_sides)
        prevented_damage = matchup.immediate_prevented_damage
        kill_probability = matchup.blocker_kill_probability
        survive_probability = matchup.blocker_survival_probability
        block_win_probability = matchup.block_win_probability
        delivered_kill_damage = matchup.expected_damage_to_attacker
        overkill_damage = matchup.overkill_damage
        repeat_block_value = matchup.repeated_block_value
        unresolved_threat = (1.0 - kill_probability) * (enemy.sw * 1.1 + enemy.aw * 0.35)
        brittle_chump_penalty = 0.0
        if survive_probability < 0.2 and kill_probability < 0.2:
            brittle_chump_penalty += 1.15 + max(0.0, enemy.sw - prevented_damage) * 0.25
        if candidate_view.sw <= 0:
            brittle_chump_penalty += 0.55 * max(0.0, 1.0 - kill_probability)
        life_breakpoint_bonus = matchup.blocker_life_breakpoint * max(0.45, enemy.sw * 0.18)
        score = (
            prevented_damage * DEFENSIVE_PREVENTED_DAMAGE_WEIGHT
            + kill_probability * DEFENSIVE_KILL_WEIGHT
            + delivered_kill_damage * 0.45
            + block_win_probability * DEFENSIVE_CONTEST_WEIGHT
            + survive_probability * (DEFENSIVE_SURVIVAL_WEIGHT + 0.75)
            + repeat_block_value * 0.9
            + life_breakpoint_bonus
            - estimate.defender_death_probability * DEFENSIVE_DEATH_PENALTY
            - overkill_damage * 0.18
            - unresolved_threat
            - brittle_chump_penalty
        )
        summaries.append(
            {
                "score": score,
                "kill_pressure": kill_probability * DEFENSIVE_KILL_WEIGHT,
                "death_risk": -(estimate.defender_death_probability * DEFENSIVE_DEATH_PENALTY),
                "repeated_block_value": repeat_block_value,
                "weight": max(1.0, enemy.sw + enemy.aw * 0.35),
                "block_win_probability": block_win_probability,
                "attacker_kill_probability": kill_probability,
                "blocker_survival_probability": survive_probability,
                "life_breakpoint": matchup.blocker_life_breakpoint,
                "immediate_prevented_damage": prevented_damage,
                "repeated_prevented_damage": repeat_block_value,
            }
        )
    total_weight = sum(summary["weight"] for summary in summaries)
    weighted_score = sum(summary["score"] * summary["weight"] for summary in summaries) / max(1.0, total_weight)
    return {
        "score": weighted_score,
        "kill_pressure": sum(summary["kill_pressure"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "death_risk": sum(summary["death_risk"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "repeated_block_value": sum(summary["repeated_block_value"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "block_win_probability": sum(summary["block_win_probability"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "attacker_kill_probability": sum(summary["attacker_kill_probability"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "blocker_survival_probability": sum(summary["blocker_survival_probability"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "life_breakpoint": sum(summary["life_breakpoint"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "immediate_prevented_damage": sum(summary["immediate_prevented_damage"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
        "repeated_prevented_damage": sum(summary["repeated_prevented_damage"] * summary["weight"] for summary in summaries) / max(1.0, total_weight),
    }


def _evaluate_immediate_pressure(candidate_view, snapshot: BuilderStrategicSnapshot, immediate_enemy_blockers: list, *, die_sides: int) -> dict[str, float]:
    if not candidate_view.has_ability(Ability.HASTE):
        return {"score": 0.0, "expected_player_damage": 0.0, "expected_heal": 0.0, "damage_delivery_probability": 0.0}

    legal_blockers = [blocker for blocker in immediate_enemy_blockers if can_legally_block(candidate_view, blocker, require_ready=True)]
    if not legal_blockers:
        unblocked = estimate_unblocked_attack(candidate_view)
        lethal_bonus = IMMEDIATE_LETHAL_BONUS_WEIGHT if unblocked.player_damage >= snapshot.enemy_life else 0.0
        return {
            "score": unblocked.player_damage * EXPECTED_PLAYER_DAMAGE_WEIGHT + unblocked.attacker_heal * EXPECTED_HEAL_WEIGHT + lethal_bonus,
            "expected_player_damage": unblocked.player_damage,
            "expected_heal": unblocked.attacker_heal,
            "damage_delivery_probability": 1.0 if unblocked.player_damage > 0 else 0.0,
        }

    offensive = _evaluate_offensive_matchups(
        candidate_view,
        immediate_enemy_blockers,
        prefer_forced=Ability.ENRAGED in candidate_view.abilities,
        die_sides=die_sides,
    )
    lethal_bonus = IMMEDIATE_LETHAL_BONUS_WEIGHT if offensive["expected_player_damage"] >= snapshot.enemy_life else 0.0
    return {
        "score": offensive["score"] + lethal_bonus,
        "expected_player_damage": offensive["expected_player_damage"],
        "expected_heal": offensive["expected_heal"],
        "damage_delivery_probability": offensive["damage_delivery_probability"],
    }


def _evaluate_immediate_defense(candidate_view, enemy_attackers: list, *, die_sides: int) -> dict[str, float]:
    if not candidate_view.has_ability(Ability.HASTE):
        return {
            "score": 0.0,
            "kill_pressure": 0.0,
            "death_risk": 0.0,
            "repeated_block_value": 0.0,
            "block_win_probability": 0.0,
            "attacker_kill_probability": 0.0,
            "blocker_survival_probability": 0.0,
            "life_breakpoint": 0.0,
            "immediate_prevented_damage": 0.0,
            "repeated_prevented_damage": 0.0,
        }
    defensive = _evaluate_defensive_matchups(candidate_view, enemy_attackers, die_sides=die_sides)
    return {
        "score": defensive["score"],
        "kill_pressure": defensive["kill_pressure"],
        "death_risk": defensive["death_risk"],
        "repeated_block_value": defensive["repeated_block_value"],
        "block_win_probability": defensive["block_win_probability"],
        "attacker_kill_probability": defensive["attacker_kill_probability"],
        "blocker_survival_probability": defensive["blocker_survival_probability"],
        "life_breakpoint": defensive["life_breakpoint"],
        "immediate_prevented_damage": defensive["immediate_prevented_damage"],
        "repeated_prevented_damage": defensive["repeated_prevented_damage"],
    }


def _evaluate_marginal_immediate_defense(candidate_view, enemy_attackers: list, own_blockers: list, *, die_sides: int) -> dict[str, float]:
    if not candidate_view.has_ability(Ability.HASTE):
        return {
            "score": 0.0,
            "kill_pressure": 0.0,
            "death_risk": 0.0,
            "block_win_probability": 0.0,
            "attacker_kill_probability": 0.0,
            "blocker_survival_probability": 0.0,
            "life_breakpoint": 0.0,
            "immediate_prevented_damage": 0.0,
            "repeated_block_value": 0.0,
            "repeated_prevented_damage": 0.0,
        }
    baseline_damage = _optimal_enemy_damage(enemy_attackers, own_blockers)
    with_candidate_damage = _optimal_enemy_damage(enemy_attackers, own_blockers + [candidate_view])
    marginal_prevented = max(0.0, baseline_damage - with_candidate_damage)
    defensive = _evaluate_immediate_defense(candidate_view, enemy_attackers, die_sides=die_sides)
    if marginal_prevented <= 0.0 and defensive["repeated_block_value"] <= 0.0:
        return {
            "score": 0.0,
            "kill_pressure": 0.0,
            "death_risk": 0.0,
            "block_win_probability": defensive["block_win_probability"],
            "attacker_kill_probability": defensive["attacker_kill_probability"],
            "blocker_survival_probability": defensive["blocker_survival_probability"],
            "life_breakpoint": defensive["life_breakpoint"],
            "immediate_prevented_damage": marginal_prevented,
            "repeated_block_value": defensive["repeated_block_value"],
            "repeated_prevented_damage": defensive["repeated_prevented_damage"],
        }
    score = marginal_prevented * (DEFENSIVE_PREVENTED_DAMAGE_WEIGHT + 0.35)
    score += max(0.0, defensive["kill_pressure"]) * 1.35
    score += max(0.0, defensive["death_risk"]) * 0.7
    score += defensive["repeated_block_value"] * 1.1
    score += defensive["life_breakpoint"] * 0.8
    return {
        "score": score,
        "kill_pressure": defensive["kill_pressure"],
        "death_risk": defensive["death_risk"],
        "block_win_probability": defensive["block_win_probability"],
        "attacker_kill_probability": defensive["attacker_kill_probability"],
        "blocker_survival_probability": defensive["blocker_survival_probability"],
        "life_breakpoint": defensive["life_breakpoint"],
        "immediate_prevented_damage": marginal_prevented,
        "repeated_block_value": defensive["repeated_block_value"],
        "repeated_prevented_damage": defensive["repeated_prevented_damage"],
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


def _combatant_signature(subject) -> tuple:
    view = coerce_builder_combatant(subject)
    return (
        view.aw,
        view.vw,
        view.sw,
        view.lw,
        view.current_hp,
        view.ready,
        view.cannot_block,
        tuple(sorted(ability.value for ability in view.abilities)),
    )


def _view_from_signature(signature: tuple) -> BuilderCombatantView:
    aw, vw, sw, lw, current_hp, ready, cannot_block, abilities = signature
    return BuilderCombatantView(
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
        current_hp=current_hp,
        ready=ready,
        cannot_block=cannot_block,
        abilities=frozenset(Ability(name) for name in abilities),
        name="cached",
    )


def _optimal_enemy_damage(enemy_attackers: list, own_blockers: list) -> float:
    attacker_signatures = tuple(sorted(_combatant_signature(attacker) for attacker in enemy_attackers if coerce_builder_combatant(attacker).sw > 0))
    blocker_signatures = tuple(sorted(_combatant_signature(blocker) for blocker in own_blockers))
    if not attacker_signatures:
        return 0.0
    return _optimal_enemy_damage_cached(attacker_signatures, blocker_signatures)


@lru_cache(maxsize=4096)
def _optimal_enemy_damage_cached(attacker_signatures: tuple, blocker_signatures: tuple) -> float:
    attackers = [_view_from_signature(signature) for signature in attacker_signatures]
    blockers = [_view_from_signature(signature) for signature in blocker_signatures]
    best_damage = 0.0
    for size in range(len(attackers) + 1):
        for attack_group in combinations(attackers, size):
            damage = _worst_case_player_damage_for_attack_group(list(attack_group), blockers)
            if damage > best_damage:
                best_damage = damage
    return best_damage


def _worst_case_player_damage_for_attack_group(attack_group: list[BuilderCombatantView], blockers: list[BuilderCombatantView]) -> float:
    if not attack_group:
        return 0.0
    worst_damage = float("inf")
    for assignment in _enumerate_block_assignments(attack_group, blockers, 0, {}, set()):
        damage = 0.0
        for attacker in attack_group:
            blocker = assignment.get(id(attacker))
            if blocker is None:
                damage += estimate_unblocked_attack(attacker).player_damage
            else:
                damage += estimate_builder_combat(attacker, blocker).expected_player_damage
        worst_damage = min(worst_damage, damage)
    return 0.0 if worst_damage == float("inf") else worst_damage


def _enumerate_block_assignments(
    attackers: list[BuilderCombatantView],
    blockers: list[BuilderCombatantView],
    index: int,
    current: dict[int, BuilderCombatantView],
    used_blockers: set[int],
):
    if index >= len(attackers):
        yield dict(current)
        return
    attacker = attackers[index]
    yield from _enumerate_block_assignments(attackers, blockers, index + 1, current, used_blockers)
    for blocker in blockers:
        blocker_token = id(blocker)
        if blocker_token in used_blockers:
            continue
        if not can_legally_block(attacker, blocker, require_ready=True):
            continue
        current[id(attacker)] = blocker
        yield from _enumerate_block_assignments(attackers, blockers, index + 1, current, used_blockers | {blocker_token})
        current.pop(id(attacker), None)
