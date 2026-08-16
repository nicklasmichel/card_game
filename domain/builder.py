from __future__ import annotations

from dataclasses import dataclass

from core.builder_rules import (
    BUILDER_HASTE_COST,
    builder_creature_ability_set,
    builder_creature_stat_cost,
    validate_builder_primary_ability,
)
from .enums import Ability


@dataclass
class PendingBuilderCreatureBuild:
    base_aw: int = 0
    base_vw: int = 0
    base_sw: int = 0
    base_lw: int = 1
    aw: int = 0
    vw: int = 0
    sw: int = 0
    lw: int = 1
    available_resources: int = 0
    selected_primary_ability: Ability | None = None
    has_haste: bool = False

    @property
    def stat_cost(self) -> int:
        return builder_creature_stat_cost(
            aw=max(0, self.aw - self.base_aw),
            vw=max(0, self.vw - self.base_vw),
            sw=max(0, self.sw - self.base_sw),
            lw=1 + max(0, self.lw - self.base_lw),
        )

    @property
    def ability_cost(self) -> int:
        return BUILDER_HASTE_COST if self.has_haste else 0

    @property
    def spent_resources(self) -> int:
        return self.stat_cost + self.ability_cost

    @property
    def selected_abilities(self) -> frozenset[Ability]:
        return builder_creature_ability_set(self.selected_primary_ability, has_haste=self.has_haste)

    def choose_primary_ability(self, ability: Ability) -> None:
        self.selected_primary_ability = validate_builder_primary_ability(ability)

    def toggle_haste(self) -> None:
        self.has_haste = not self.has_haste


@dataclass
class PendingBuilderAbilityUse:
    card_instance_id: int
    mode: str | None = None
    selected_target_id: int | None = None
    selected_stat: str | None = None
