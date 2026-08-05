from __future__ import annotations

from dataclasses import dataclass

from core.ai.strategies.base import DeckStrategy, StrategyDecision, StrategyMetric, StrategyWeights
from core.models import Ability, CardType, PHASE_MAIN_1, PHASE_MAIN_2, PlayerState, SpellEffect


AIR_MODE_LETHAL = "LETHAL"
AIR_MODE_PRESSURE = "PRESSURE"
AIR_MODE_BUILD_SWARM = "BUILD_SWARM"
AIR_MODE_RELOAD = "RELOAD"
AIR_MODE_RECOVER = "RECOVER"
AIR_MODE_STABILIZE = "STABILIZE"


@dataclass(slots=True, frozen=True)
class AirStrategicSnapshot:
    own_life: int
    enemy_life: int
    hand_size: int
    available_resources: int
    total_resources: int
    resources_left_to_play: int
    own_creatures: int
    enemy_creatures: int
    possible_attackers: int
    flying_attackers: int
    haste_creatures_in_hand: int
    enemy_flying_blockers: int
    expected_player_damage: int
    expected_own_losses: int
    expected_enemy_losses: int
    expected_counterattack_damage: int
    probable_unblocked_damage: int
    passive_attackers_reachable: bool
    graveyard_creatures: int
    hand_quality: float
    has_hand_reload: bool
    has_graveyard_recovery: bool
    lethal_available: bool
    opponent_lethal_threat: bool

    def to_metrics(self) -> tuple[StrategyMetric, ...]:
        return (
            StrategyMetric("possible_attackers", str(self.possible_attackers)),
            StrategyMetric("flying_attackers", str(self.flying_attackers)),
            StrategyMetric("expected_player_damage", str(self.expected_player_damage)),
            StrategyMetric("expected_counterattack_damage", str(self.expected_counterattack_damage)),
            StrategyMetric("passive_attackers_reachable", str(self.passive_attackers_reachable).lower()),
            StrategyMetric("hand_size", str(self.hand_size)),
            StrategyMetric("graveyard_creatures", str(self.graveyard_creatures)),
            StrategyMetric("lethal_available", str(self.lethal_available).lower()),
            StrategyMetric("opponent_lethal_threat", str(self.opponent_lethal_threat).lower()),
        )


class AirStrategy(DeckStrategy):
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
        snapshot = self._build_snapshot(
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

    def _build_snapshot(self, ai, player: PlayerState, engine, *, hand, available_resources: int, total_resources: int, phase: str) -> AirStrategicSnapshot:
        enemy = engine.players[1 - player.player_id]
        ready_attackers = [creature for creature in player.battlefield if creature.is_ready() and creature.current_hp > 0]
        probable_attack = ai._estimate_best_air_attack_plan(player, enemy, hand, [])
        probable_unblocked_damage = ai._find_probable_unblocked_damage(player, enemy, hand)
        enemy_counterattack = ai._estimate_enemy_counterattack(player, enemy, attacking_ids=set())
        flying_attackers = sum(1 for creature in ready_attackers if creature.has_ability(Ability.FLYING))
        haste_in_hand = sum(
            1
            for card in hand
            if card.template.card_type == CardType.CREATURE and card.template.has_ability(Ability.HASTE)
        )
        enemy_flying_blockers = sum(
            1
            for creature in enemy.battlefield
            if creature.current_hp > 0 and creature.is_ready() and creature.has_ability(Ability.FLYING) and not creature.cannot_block
        )
        hand_quality = self._estimate_hand_quality(ai, player, engine, hand, available_resources, total_resources)
        has_hand_reload = any(
            card.template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW
            and len(player.deck) >= card.template.spell_draw_count
            for card in hand
        )
        has_graveyard_recovery = any(
            card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND
            and len([discard_card for discard_card in player.discard_pile if discard_card.template.card_type == CardType.CREATURE]) >= card.template.spell_amount
            for card in hand
        )
        lethal_available = bool(probable_attack.get("is_lethal"))
        if not lethal_available:
            for bonus in (1, 2):
                buffed = ai._estimate_best_air_attack_plan(player, enemy, hand, [], attack_bonus_amount=bonus)
                if buffed.get("is_lethal"):
                    lethal_available = True
                    break
        if not lethal_available and probable_unblocked_damage >= enemy.life:
            lethal_available = True
        resources_left_to_play = max(0, 2 - player.resources_played_this_turn)
        opponent_lethal_threat = enemy_counterattack["damage"] >= player.life
        return AirStrategicSnapshot(
            own_life=player.life,
            enemy_life=enemy.life,
            hand_size=len(hand),
            available_resources=available_resources,
            total_resources=total_resources,
            resources_left_to_play=resources_left_to_play,
            own_creatures=len(player.battlefield),
            enemy_creatures=len(enemy.battlefield),
            possible_attackers=ai._count_probable_attackers(player, hand),
            flying_attackers=flying_attackers,
            haste_creatures_in_hand=haste_in_hand,
            enemy_flying_blockers=enemy_flying_blockers,
            expected_player_damage=int(probable_attack.get("direct_damage", 0)),
            expected_own_losses=int(probable_attack.get("own_losses", 0)),
            expected_enemy_losses=int(probable_attack.get("enemy_kills", 0)),
            expected_counterattack_damage=int(enemy_counterattack["damage"]),
            probable_unblocked_damage=probable_unblocked_damage,
            passive_attackers_reachable=ai._count_probable_attackers(player, hand) >= 3,
            graveyard_creatures=len([discard_card for discard_card in player.discard_pile if discard_card.template.card_type == CardType.CREATURE]),
            hand_quality=hand_quality,
            has_hand_reload=has_hand_reload,
            has_graveyard_recovery=has_graveyard_recovery,
            lethal_available=lethal_available,
            opponent_lethal_threat=opponent_lethal_threat,
        )

    def _estimate_hand_quality(self, ai, player: PlayerState, engine, hand, available_resources: int, total_resources: int) -> float:
        if not hand:
            return 0.0
        worth = 0.0
        for card in hand:
            if ai._air_template_is_generally_draw_worthy(
                player,
                engine,
                card.template,
                hand,
                available_resources=available_resources,
                total_resources=total_resources,
            ):
                worth += 1.4
            if ai._air_template_improves_weak_hand(
                player,
                engine,
                card.template,
                hand,
                available_resources=available_resources,
                total_resources=total_resources,
            ):
                worth += 0.6
            if card.template.card_type == CardType.CREATURE:
                worth += 0.35 * (card.template.aw + card.template.vw)
        return worth / len(hand)

    def _select_mode(self, snapshot: AirStrategicSnapshot) -> tuple[str, str, tuple[str, ...]]:
        if snapshot.lethal_available:
            return AIR_MODE_LETHAL, "deal_lethal_damage", ("lethal_available",)
        if snapshot.opponent_lethal_threat:
            return AIR_MODE_STABILIZE, "prevent_opponent_lethal", ("opponent_lethal_threat",)
        if snapshot.has_hand_reload and snapshot.hand_size <= 1:
            return AIR_MODE_RELOAD, "reload_hand", ("hand_nearly_empty",)
        if snapshot.has_graveyard_recovery and snapshot.graveyard_creatures >= 2 and snapshot.hand_quality <= 2.6:
            return AIR_MODE_RECOVER, "recover_creatures", ("valuable_graveyard_targets",)
        if snapshot.possible_attackers < 3 and snapshot.hand_size >= 2:
            return AIR_MODE_BUILD_SWARM, "build_wide_board", ("insufficient_attackers",)
        return AIR_MODE_PRESSURE, "maximize_player_damage", ("default_pressure_plan",)

    def _weights_for_mode(self, mode: str) -> StrategyWeights:
        if mode == AIR_MODE_LETHAL:
            return StrategyWeights(
                player_damage=1.45,
                lethal=2.4,
                own_losses=0.45,
                enemy_losses=0.8,
                board_width=0.7,
                third_attacker=1.3,
                flying_damage=1.2,
                recycle_penalty=0.45,
                counterattack_risk=0.35,
                draw_value=0.7,
                graveyard_value=0.8,
                bounce_tempo=1.5,
                blocker_value=0.8,
                future_playability=0.4,
            )
        if mode == AIR_MODE_BUILD_SWARM:
            return StrategyWeights(
                player_damage=0.95,
                lethal=1.0,
                own_losses=1.0,
                enemy_losses=0.9,
                board_width=1.55,
                third_attacker=1.55,
                flying_damage=1.0,
                recycle_penalty=1.35,
                counterattack_risk=1.0,
                draw_value=0.9,
                graveyard_value=0.9,
                bounce_tempo=0.9,
                blocker_value=1.0,
                future_playability=1.45,
            )
        if mode == AIR_MODE_RELOAD:
            return StrategyWeights(
                player_damage=0.85,
                lethal=1.0,
                own_losses=1.0,
                enemy_losses=0.9,
                board_width=0.9,
                third_attacker=0.9,
                flying_damage=0.9,
                recycle_penalty=1.1,
                counterattack_risk=1.0,
                draw_value=1.7,
                graveyard_value=0.9,
                bounce_tempo=0.8,
                blocker_value=1.0,
                future_playability=1.35,
            )
        if mode == AIR_MODE_RECOVER:
            return StrategyWeights(
                player_damage=0.95,
                lethal=1.0,
                own_losses=1.0,
                enemy_losses=0.95,
                board_width=1.0,
                third_attacker=1.1,
                flying_damage=1.05,
                recycle_penalty=1.0,
                counterattack_risk=1.0,
                draw_value=0.95,
                graveyard_value=1.7,
                bounce_tempo=0.9,
                blocker_value=1.0,
                future_playability=1.2,
            )
        if mode == AIR_MODE_STABILIZE:
            return StrategyWeights(
                player_damage=0.65,
                lethal=1.0,
                own_losses=1.2,
                enemy_losses=1.1,
                board_width=0.8,
                third_attacker=0.75,
                flying_damage=0.8,
                recycle_penalty=1.4,
                counterattack_risk=1.8,
                draw_value=0.8,
                graveyard_value=0.9,
                bounce_tempo=1.35,
                blocker_value=1.7,
                future_playability=1.0,
            )
        return StrategyWeights(
            player_damage=1.2,
            lethal=1.15,
            own_losses=0.95,
            enemy_losses=1.0,
            board_width=1.2,
            third_attacker=1.3,
            flying_damage=1.2,
            recycle_penalty=0.95,
            counterattack_risk=1.0,
            draw_value=0.95,
            graveyard_value=1.0,
            bounce_tempo=1.15,
            blocker_value=1.0,
            future_playability=1.05,
        )
