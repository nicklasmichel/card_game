from __future__ import annotations

from random import Random
from typing import List


class RandomDieStrategy:
    name = "Zufaellig"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        return rng.choice(dice)


class HighestFirstDieStrategy:
    name = "Hoechster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        return max(dice, key=lambda die: getattr(die, "total", 0))


class LowestFirstDieStrategy:
    name = "Niedrigster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        return min(dice, key=lambda die: getattr(die, "total", 0))


class SacrificeLowThenHighDieStrategy:
    name = "Niedrigen Wuerfel opfern, dann hoch spielen"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        if len(dice) >= 3:
            return min(dice, key=lambda die: getattr(die, "total", 0))
        return max(dice, key=lambda die: getattr(die, "total", 0))
