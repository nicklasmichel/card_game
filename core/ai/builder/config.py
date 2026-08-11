from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuilderAIWeights:
    lost_block_value: float = 1.35
    expected_counter_damage: float = 2.1
    own_lethal_bonus: float = 1.0
    enemy_lethal_penalty: float = 18.0
    enemy_lethal_probability: float = 14.0
    role_fit: float = 0.95
    damage_race: float = 0.7
    defensive_removal_probability: float = 0.85
    resource_growth_vs_build: float = 1.0


BUILDER_AI_WEIGHTS = BuilderAIWeights()
