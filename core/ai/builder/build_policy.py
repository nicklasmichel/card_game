from __future__ import annotations

from .candidates import generate_builder_creature_candidates, is_legal_builder_candidate
from .scoring import score_builder_creature_candidate
from .snapshot import build_builder_snapshot
from .turn_policy import build_builder_plan_dict
from .types import BuilderCandidateScore, BuilderCreatureCandidate


def choose_builder_creature_candidate(player, engine):
    snapshot = build_builder_snapshot(player, engine)
    available_resources = player.available_resources()
    candidates = generate_builder_creature_candidates(snapshot, available_resources)
    enemy_creatures = list(engine.players[1 - player.player_id].battlefield)
    own_creatures = list(player.battlefield)
    scored_candidates: list[tuple[BuilderCreatureCandidate, BuilderCandidateScore]] = []
    for candidate in candidates:
        if not is_legal_builder_candidate(candidate, available_resources):
            continue
        scored_candidates.append(
            (
                candidate,
                score_builder_creature_candidate(
                    candidate,
                    snapshot,
                    available_resources=available_resources,
                    enemy_creatures=enemy_creatures,
                    own_creatures=own_creatures,
                ),
            )
        )
    if not scored_candidates:
        return None, None, snapshot, []
    scored_candidates.sort(key=_sort_key, reverse=True)
    best_candidate, best_score = scored_candidates[0]
    return best_candidate, best_score, snapshot, scored_candidates


def choose_builder_creature_plan(player, engine) -> dict | None:
    best_candidate, _, _, _ = choose_builder_creature_candidate(player, engine)
    return None if best_candidate is None else build_builder_plan_dict(best_candidate)


def _sort_key(scored_candidate: tuple[BuilderCreatureCandidate, BuilderCandidateScore]) -> tuple:
    candidate, score = scored_candidate
    return (
        score.total,
        score.matchup_offense,
        score.evasion,
        score.matchup_defense,
        score.board_fit,
        score.synergy,
        score.immediate_pressure,
        score.survivability,
        -candidate.cost,
        tuple(reversed(candidate.key)),
    )
