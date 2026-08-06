from __future__ import annotations

from core.ai.fire.assessment import build_fire_snapshot
from core.ai.strategies.base import DeckStrategy, StrategyDecision, StrategyWeights
from core.models import PlayerState


FIRE_MODE_LETHAL = "LETHAL"
FIRE_MODE_STABILIZE = "STABILIZE"
FIRE_MODE_CONTROL = "CONTROL"
FIRE_MODE_RAMP = "RAMP"
FIRE_MODE_DEPLOY_THREAT = "DEPLOY_THREAT"
FIRE_MODE_REFUEL = "REFUEL"


class FireStrategy(DeckStrategy):
    def evaluate(
        self,
        ai,
        player: PlayerState,
        engine,
        *,
        hand,
        available_resources: int,
        total_resources: int,
        phase: str,
    ) -> StrategyDecision:
        snapshot = build_fire_snapshot(
            ai,
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
            phase=phase,
        )
        mode, primary_goal, reason_codes = self._select_mode(snapshot)
        return StrategyDecision(
            mode=mode,
            primary_goal=primary_goal,
            reason_codes=reason_codes,
            weights=self._weights_for_mode(mode),
            metrics=snapshot.to_metrics(),
        )

    def _select_mode(self, snapshot):
        if snapshot.lethal_available:
            return FIRE_MODE_LETHAL, "assemble_lethal", ("lethal_line_available",)
        if snapshot.opponent_lethal_threat:
            return FIRE_MODE_STABILIZE, "prevent_enemy_lethal", ("enemy_lethal_threat",)
        if snapshot.dangerous_board:
            return FIRE_MODE_CONTROL, "control_enemy_board", ("dangerous_enemy_board",)
        if snapshot.can_deploy_threat:
            return FIRE_MODE_DEPLOY_THREAT, "deploy_major_threat", ("playable_large_creature",)
        if snapshot.can_ramp_safely and snapshot.ramp_cards > 0:
            return FIRE_MODE_RAMP, "increase_future_resources", ("safe_ramp_window",)
        if snapshot.needs_refuel and snapshot.draw_cards > 0:
            return FIRE_MODE_REFUEL, "refill_hand", ("hand_needs_refuel",)
        return FIRE_MODE_CONTROL, "control_enemy_board", ("default_control_plan",)

    def _weights_for_mode(self, mode: str) -> StrategyWeights:
        if mode == FIRE_MODE_LETHAL:
            return StrategyWeights(player_damage=1.7, lethal=2.6, own_losses=0.5, enemy_losses=0.8, recycle_penalty=0.55, counterattack_risk=0.35, draw_value=0.4, future_playability=0.3)
        if mode == FIRE_MODE_STABILIZE:
            return StrategyWeights(player_damage=0.6, lethal=1.0, own_losses=1.25, enemy_losses=1.4, flying_damage=1.5, recycle_penalty=1.3, counterattack_risk=1.8, draw_value=0.7, blocker_value=1.6, future_playability=0.8)
        if mode == FIRE_MODE_CONTROL:
            return StrategyWeights(player_damage=0.8, lethal=1.0, own_losses=1.0, enemy_losses=1.45, flying_damage=1.4, recycle_penalty=1.0, counterattack_risk=1.2, draw_value=0.85, future_playability=1.0)
        if mode == FIRE_MODE_RAMP:
            return StrategyWeights(player_damage=0.7, lethal=1.0, own_losses=1.0, enemy_losses=0.9, recycle_penalty=1.0, counterattack_risk=1.0, draw_value=0.9, future_playability=1.6)
        if mode == FIRE_MODE_DEPLOY_THREAT:
            return StrategyWeights(player_damage=1.1, lethal=1.2, own_losses=0.95, enemy_losses=1.0, recycle_penalty=0.9, counterattack_risk=0.95, draw_value=0.8, future_playability=1.2)
        return StrategyWeights(player_damage=0.7, lethal=1.0, own_losses=1.0, enemy_losses=0.9, recycle_penalty=1.1, counterattack_risk=1.0, draw_value=1.7, future_playability=1.25)
