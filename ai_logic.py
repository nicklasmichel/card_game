from __future__ import annotations

from random import Random
from typing import List, Optional

from models import BattlefieldUnit, CardInstance, DieResult, PlayerState


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
        low_cost_count = sum(1 for card in hand if card.template.cost <= 2)
        if low_cost_count >= 2:
            return []
        return [index for index, card in enumerate(hand) if card.template.cost >= 5]

    def choose_resource_card(self, player: PlayerState) -> Optional[CardInstance]:
        if player.resource_played_this_turn or not player.hand:
            return None
        affordable = player.available_resources()
        return max(
            player.hand,
            key=lambda card: (
                1 if card.template.cost > affordable else 0,
                card.template.cost,
                card.template.aw + card.template.vw,
            ),
        )

    def choose_playable_unit(self, player: PlayerState) -> Optional[CardInstance]:
        playable = [card for card in player.hand if player.can_pay(card.template.cost)]
        if not playable:
            return None
        return max(playable, key=lambda card: (card.template.cost, card.template.aw, card.template.vw))

    def choose_attackers(self, units: List[BattlefieldUnit]) -> List[BattlefieldUnit]:
        return [unit for unit in units if unit.is_ready()]

    def choose_blocker(self, attacker: BattlefieldUnit, blockers: List[BattlefieldUnit]) -> Optional[BattlefieldUnit]:
        if not blockers:
            return None

        def score(blocker: BattlefieldUnit) -> tuple[int, int, int]:
            survival_margin = blocker.current_hp - attacker.aw
            survives = 1 if survival_margin > 0 else 0
            return survives, -abs(survival_margin), blocker.aw

        return max(blockers, key=score)

    def choose_block_order(self, blockers: List[BattlefieldUnit]) -> List[BattlefieldUnit]:
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
