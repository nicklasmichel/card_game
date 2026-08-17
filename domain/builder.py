from __future__ import annotations

from dataclasses import dataclass

from core.builder_rules import BUILDER_HASTE_COST, builder_creature_stat_cost
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
    has_haste: bool = False

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
        return BUILDER_HASTE_COST if self.has_haste else 0

    @property
    def spent_resources(self) -> int:
        # Every ready resource remains available for stats. Haste is paid
        # separately by permanently removing one resource after that payment.
        return self.stat_cost

    @property
    def total_cost(self) -> int:
        return self.stat_cost + self.ability_cost

    @property
    def selected_abilities(self) -> frozenset[Ability]:
        return frozenset({Ability.HASTE}) if self.has_haste else frozenset()


@dataclass
class PendingBuilderAbilityUse:
    card_instance_id: int
    mode: str | None = None
    selected_target_id: int | None = None
    selected_stat: str | None = None
