from __future__ import annotations

from dataclasses import dataclass, field

from core.models import Ability

from .types import BuilderCandidateScore, BuilderCreatureCandidate


@dataclass(frozen=True)
class BuilderTurnActionCandidate:
    action_kind: str
    creature_candidate: BuilderCreatureCandidate | None
    projected_total_resources: int
    projected_ready_resources: int
    generation_reason: str = "generated"


@dataclass(frozen=True)
class BuilderAbilityActionCandidate:
    action_kind: str
    card_instance_id: int | None = None
    card_ability: Ability | None = None
    target_id: int | None = None
    selected_stat: str | None = None
    generation_reason: str = "generated"


@dataclass(frozen=True)
class BuilderSearchMetadata:
    exact_search: bool
    generated_attack_candidates: int
    evaluated_attack_candidates: int
    generated_block_assignments: int
    evaluated_block_assignments: int
    pruned_candidates: int
    search_budget_name: str


@dataclass(frozen=True)
class BuilderTurnScore:
    terminal: float
    board_value: float
    resource_value: float
    card_value: float
    draw_value: float
    creature_future_value: float
    resource_growth_value: float
    immediate_combat_delta: float
    expected_player_damage: float
    expected_enemy_kill_value: float
    expected_own_death_value: float
    end_of_turn_readiness: float
    survival_urgency: float
    lethal_value: float
    ability_value: float
    risk_adjustment: float
    total: float
    baseline_attack_score: float = 0.0
    projected_attack_score: float = 0.0
    search_was_exact: bool = True
    evaluated_candidate_count: int = 0


@dataclass(frozen=True)
class BuilderTurnDecision:
    action_candidate: BuilderTurnActionCandidate
    ability_action: BuilderAbilityActionCandidate
    score: BuilderTurnScore
    predicted_attack_decision: object | None
    state_signature: tuple
    post_main_signature: tuple
    post_ability_signature: tuple


@dataclass(frozen=True)
class ProjectedUnitView:
    unit_id: int
    name: str
    aw: int
    vw: int
    sw: int
    lw: int
    current_hp: int
    abilities: frozenset[Ability]
    tapped: bool
    summoning_sickness: bool
    cannot_block: bool = False
    debug_label: str = ""

    def has_ability(self, ability: Ability) -> bool:
        return ability in self.abilities

    def is_ready(self) -> bool:
        return not self.tapped and (not self.summoning_sickness or self.has_ability(Ability.HASTE))


@dataclass(frozen=True)
class ProjectedPlayerView:
    player_id: int
    name: str
    is_human: bool
    life: int
    battlefield: tuple[ProjectedUnitView, ...]
    ready_resources: int
    total_resource_count: int
    summoner_key: str = "builder"

    def available_resources(self) -> int:
        return self.ready_resources

    def total_resources(self) -> int:
        return self.total_resource_count


@dataclass(frozen=True)
class BuilderProjectedCandidate:
    candidate: BuilderCreatureCandidate
    static_score: BuilderCandidateScore
    future_value: float
    shortlist_reasons: tuple[str, ...] = field(default_factory=tuple)
