from __future__ import annotations

import core.config as config

from .build_policy import choose_builder_creature_candidate
from .turn_policy import choose_builder_main_action as choose_builder_main_action_v3


def choose_builder_main_action(player, engine) -> str:
    return choose_builder_main_action_v3(player, engine)


def score_builder_resource_action(snapshot, resource_limit: int) -> float:
    if snapshot.own_total_resources >= resource_limit:
        return float("-inf")

    current_total = snapshot.own_total_resources
    early_ramp_bonus = {
        0: 6.6,
        1: 7.2,
        2: 6.8,
        3: 5.7,
        4: 4.2,
        5: 3.4,
        6: 2.6,
        7: 1.8,
        8: 1.0,
        9: 0.3,
    }.get(current_total, 0.0)

    board_safety = max(-3.0, min(3.0, snapshot.board_value_difference * 0.55))
    life_safety = max(-2.0, min(2.0, snapshot.life_difference * 0.2))
    pressure_penalty = 0.0
    if not snapshot.own_has_board and snapshot.enemy_has_board:
        pressure_penalty -= 4.5
    if snapshot.enemy_potential_attacker_count > snapshot.own_creature_count:
        pressure_penalty -= min(2.5, (snapshot.enemy_potential_attacker_count - snapshot.own_creature_count) * 0.7)
    if snapshot.board_value_difference <= -3:
        pressure_penalty -= 2.0
    if snapshot.board_value_difference >= 3:
        pressure_penalty += 1.1
    if snapshot.own_total_resources >= resource_limit - 2:
        pressure_penalty -= 0.6

    return round(early_ramp_bonus + board_safety + life_safety + pressure_penalty, 4)


def _debug_builder_decision(engine, snapshot, scored_candidates, resource_score: float, decision: str) -> None:
    if not getattr(config, "BUILDER_AI_DEBUG", 0):
        return
    engine.log(
        "Builder AI: "
        f"resources={snapshot.own_total_resources} ready={snapshot.own_ready_resources} "
        f"board={snapshot.own_board_value:.1f} enemy_board={snapshot.enemy_board_value:.1f}"
    )
    engine.log("Candidates:")
    for index, (candidate, score) in enumerate(scored_candidates[:5], start=1):
        abilities = ", ".join(ability.value for ability in sorted(candidate.abilities, key=lambda ability: ability.value)) or "-"
        engine.log(
            f"{index}. {candidate.aw}/{candidate.vw}/{candidate.sw}/{candidate.lw} {abilities} | "
            f"cost {candidate.cost} | score {score.total:.2f} "
            f"(stats {score.raw_stats:.2f}, abil {score.abilities:.2f}, fit {score.board_fit:.2f}, syn {score.synergy:.2f}, "
            f"off {score.matchup_offense:.2f}, def {score.matchup_defense:.2f}, eva {score.evasion:.2f}, "
            f"pdmg {score.expected_player_damage:.2f}, heal {score.expected_heal:.2f}, "
            f"kill {score.kill_pressure:.2f}, risk {score.death_risk:.2f})"
        )
    engine.log(f"Resource score: {resource_score:.2f}")
    engine.log(f"Decision: {decision}")
