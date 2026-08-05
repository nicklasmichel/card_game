from __future__ import annotations

from core.ai.strategies.base import DeckStrategy, StrategyDecision, StrategyMetric, StrategyWeights


class DefaultDeckStrategy(DeckStrategy):
    def evaluate(
        self,
        ai,
        player,
        engine,
        *,
        hand,
        available_resources: int,
        total_resources: int,
        phase: str,
    ) -> StrategyDecision:
        return StrategyDecision(
            mode="DEFAULT",
            primary_goal="play_legal_actions",
            reason_codes=("default_strategy_fallback",),
            weights=StrategyWeights(),
            metrics=(
                StrategyMetric("hand_size", str(len(hand))),
                StrategyMetric("available_resources", str(available_resources)),
                StrategyMetric("total_resources", str(total_resources)),
            ),
        )
