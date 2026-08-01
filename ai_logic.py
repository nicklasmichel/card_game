from __future__ import annotations

from random import Random
from typing import List, Optional

from models import Ability, BattlefieldCreature, CardCost, CardInstance, DieResult, PlayerState


class RandomDieStrategy:
    name = "Zufaellig"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        return rng.choice(dice)


class HighestFirstDieStrategy:
    name = "Hoechster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        return max(dice, key=lambda die: (die.total, die.base_roll))


class LowestFirstDieStrategy:
    name = "Niedrigster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        return min(dice, key=lambda die: (die.total, die.base_roll))


class SacrificeLowThenHighDieStrategy:
    name = "Niedrigen Wuerfel opfern, dann hoch spielen"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        if len(dice) >= 3:
            return min(dice, key=lambda die: (die.total, die.base_roll))
        return max(dice, key=lambda die: (die.total, die.base_roll))


class SimpleAI:
    def __init__(self, rng: Random) -> None:
        self.rng = rng

    def mulligan_indices(self, hand: List[CardInstance]) -> List[int]:
        low_cost_count = sum(1 for card in hand if card.template.cost.total_value <= 2)
        if low_cost_count >= 2:
            return []
        return [index for index, card in enumerate(hand) if card.template.cost.total_value >= 5]

    def choose_resource_card(self, player: PlayerState) -> Optional[CardInstance]:
        if player.resources_played_this_turn >= 2 or not player.hand:
            return None
        affordable = player.available_resources()
        return max(
            player.hand,
            key=lambda card: (
                1 if card.template.resource_cost > affordable else 0,
                card.template.cost.total_value,
                card.template.aw + card.template.vw,
            ),
        )

    def choose_playable_creature(self, player: PlayerState) -> Optional[CardInstance]:
        playable = [card for card in player.hand if player.can_pay(card.template.cost)]
        if not playable:
            return None
        return max(
            playable,
            key=lambda card: (
                card.template.aw + card.template.vw + len(card.template.abilities) * 2 - card.template.recycle_cost,
                -card.template.recycle_cost,
                card.template.resource_cost,
            ),
        )

    def choose_resources_to_recycle(self, player: PlayerState, count: int) -> List[int]:
        if count <= 0:
            return []

        def score(resource) -> tuple[int, int, int, int]:
            template = resource.template
            return (
                len(template.abilities),
                template.aw + template.vw,
                template.cost.total_value,
                template.resource_cost,
            )

        chosen = sorted(player.resources, key=score, reverse=True)[:count]
        return [resource.resource_id for resource in chosen if resource.resource_id is not None]

    def choose_attackers(self, creatures: List[BattlefieldCreature]) -> List[BattlefieldCreature]:
        return [creature for creature in creatures if creature.is_ready()]

    def choose_blocker(self, attacker: BattlefieldCreature, blockers: List[BattlefieldCreature]) -> Optional[BattlefieldCreature]:
        if not blockers:
            return None

        def score(blocker: BattlefieldCreature) -> tuple[int, int, int]:
            survival_margin = blocker.current_hp - attacker.aw
            survives = 1 if survival_margin > 0 else 0
            return survives, -abs(survival_margin), blocker.aw

        return max(blockers, key=score)

    def choose_blockers_for_attackers(
        self,
        attackers: List[BattlefieldCreature],
        blockers: List[BattlefieldCreature],
    ) -> dict[int, list[int]]:
        assignments: dict[int, list[int]] = {attacker.unit_id: [] for attacker in attackers}
        remaining_capacity = {blocker.unit_id: blocker.block_capacity() for blocker in blockers}
        blockers_by_id = {blocker.unit_id: blocker for blocker in blockers}

        for attacker in sorted(attackers, key=lambda unit: (-unit.aw, unit.current_hp)):
            while True:
                available = [
                    blocker
                    for blocker in blockers
                    if remaining_capacity.get(blocker.unit_id, 0) > 0
                    and blocker.unit_id not in assignments[attacker.unit_id]
                ]
                blocker = self.choose_blocker(attacker, available)
                if blocker is None:
                    break
                assignments[attacker.unit_id].append(blocker.unit_id)
                remaining_capacity[blocker.unit_id] -= 1
                if not blockers_by_id[blocker.unit_id].has_ability(Ability.DEFENDER):
                    break
                if attacker.aw <= blocker.current_hp:
                    break
                if self.rng.random() < 0.45:
                    break
        return assignments

    def choose_block_order(self, blockers: List[BattlefieldCreature]) -> List[BattlefieldCreature]:
        return sorted(
            blockers,
            key=lambda blocker: (
                -(blocker.vw - blocker.current_hp),
                blocker.current_hp,
                -blocker.aw,
            ),
        )

    def choose_die_strategy(self) -> type:
        return self.rng.choice(
            [
                RandomDieStrategy,
                HighestFirstDieStrategy,
                LowestFirstDieStrategy,
                SacrificeLowThenHighDieStrategy,
            ]
        )

    def should_use_adaptation(
        self,
        creature: BattlefieldCreature,
        own_die: DieResult,
        enemy_die: DieResult,
        would_take_damage: bool,
        would_be_destroyed: bool,
        tie: bool,
    ) -> bool:
        if not creature.has_ability(Ability.ADAPTATION):
            return False
        if would_take_damage and own_die.total < enemy_die.total:
            return True
        if tie and would_be_destroyed:
            return True
        expected_new_total = 10.5 + own_die.aw_bonus
        return expected_new_total > own_die.total and expected_new_total > enemy_die.total
