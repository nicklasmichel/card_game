from __future__ import annotations

from core.ai.strategies.air import AirStrategy
from core.ai.strategies.base import DeckStrategy
from core.ai.strategies.generic import DefaultDeckStrategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, DeckStrategy] = {
            "air": AirStrategy(),
        }
        self._default_strategy: DeckStrategy = DefaultDeckStrategy()

    def register(self, summoner_key: str, strategy: DeckStrategy) -> None:
        self._strategies[summoner_key] = strategy

    def resolve(self, summoner_key: str) -> DeckStrategy:
        return self._strategies.get(summoner_key, self._default_strategy)
