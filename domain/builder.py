from __future__ import annotations

from dataclasses import dataclass

from core.builder_rules import builder_creature_ability_set, coerce_builder_creature_ability
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
    selected_ability: Ability | None = None

    @property
    def spent_resources(self) -> int:
        return (
            max(0, self.aw - self.base_aw)
            + max(0, self.vw - self.base_vw)
            + max(0, self.sw - self.base_sw)
            + max(0, self.lw - self.base_lw)
        )

    @property
    def has_haste(self) -> bool:
        return self.selected_ability == Ability.HASTE

    @property
    def selected_abilities(self) -> frozenset[Ability]:
        return builder_creature_ability_set(self.selected_ability)

    def choose_ability(self, ability: Ability) -> None:
        self.selected_ability = coerce_builder_creature_ability(ability)


@dataclass
class PendingBuilderAbilityUse:
    card_instance_id: int
    mode: str | None = None
    selected_target_id: int | None = None
    selected_stat: str | None = None
