from __future__ import annotations

from dataclasses import dataclass

from core.builder_rules import builder_creature_stat_cost
from .enums import Ability


@dataclass
class PendingBuilderCreatureBuild:
    base_aw: int = 1
    base_vw: int = 1
    base_sw: int = 1
    base_lw: int = 1
    aw: int = 1
    vw: int = 1
    sw: int = 1
    lw: int = 1
    available_resources: int = 0

    @property
    def stat_cost(self) -> int:
        return builder_creature_stat_cost(
            aw=self.aw,
            vw=self.vw,
            sw=self.sw,
            lw=self.lw,
        )

    @property
    def ability_cost(self) -> int:
        return 0

    @property
    def spent_resources(self) -> int:
        return self.stat_cost + self.ability_cost

    @property
    def selected_abilities(self) -> frozenset[Ability]:
        return frozenset()


@dataclass
class PendingBuilderAbilityUse:
    card_instance_id: int
    mode: str | None = None
    selected_target_id: int | None = None
    selected_stat: str | None = None
