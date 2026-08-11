from __future__ import annotations

from dataclasses import dataclass

from core.builder_rules import coerce_builder_creature_ability
from core.models import Ability


@dataclass(frozen=True)
class BuilderStrategicSnapshot:
    own_life: int
    enemy_life: int
    own_total_resources: int
    own_ready_resources: int
    enemy_total_resources: int
    enemy_ready_resources: int
    own_hand_count: int
    enemy_hand_count: int
    own_creature_count: int
    enemy_creature_count: int
    own_board_value: float
    enemy_board_value: float
    own_total_aw: int
    own_total_vw: int
    own_total_sw: int
    own_total_current_hp: int
    enemy_total_aw: int
    enemy_total_vw: int
    enemy_total_sw: int
    enemy_total_current_hp: int
    own_flying_count: int
    enemy_flying_count: int
    own_ready_attacker_count: int
    enemy_potential_attacker_count: int
    own_has_board: bool
    enemy_has_board: bool
    life_difference: int
    resource_difference: int
    board_value_difference: float


@dataclass(frozen=True)
class BuilderCreatureCandidate:
    aw: int
    vw: int
    sw: int
    lw: int
    cost: int
    abilities: frozenset[Ability] = frozenset()
    generation_reason: str = "generated"

    @property
    def signature(self) -> tuple[int, int, int, int]:
        return (
            self.aw,
            self.vw,
            self.sw,
            self.lw,
        )

    @property
    def has_haste(self) -> bool:
        return self.builder_ability == Ability.HASTE

    @property
    def builder_ability(self) -> Ability | None:
        try:
            return coerce_builder_creature_ability(self.abilities)
        except ValueError:
            return None

    def has_ability(self, ability: Ability) -> bool:
        return ability in self.abilities

    @property
    def haste_cost(self) -> int:
        return 0

    @property
    def enters_tapped(self) -> bool:
        return not self.has_haste

    @property
    def key(self) -> tuple[int, int, int, int, str]:
        return self.signature + (getattr(self.builder_ability, "name", "-"),)


@dataclass(frozen=True)
class BuilderCandidateScore:
    raw_stats: float
    abilities: float
    synergy: float
    board_fit: float
    immediate_pressure: float
    survivability: float
    matchup_offense: float
    matchup_defense: float
    evasion: float
    expected_player_damage: float
    expected_heal: float
    kill_pressure: float
    death_risk: float
    unused_resources: float
    total: float
