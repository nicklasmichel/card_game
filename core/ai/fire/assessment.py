from __future__ import annotations

from dataclasses import dataclass

from core.config import FIRE_SUMMONER_DRAW_THRESHOLD
from core.ai.fire.effects import evaluate_fire_board_wipe
from core.models import Ability, CardInstance, CardType, PlayerState, SpellEffect
from core.ai.strategies.base import StrategyMetric


@dataclass(slots=True, frozen=True)
class FireStrategicSnapshot:
    own_life: int
    enemy_life: int
    passive_active_next_turn: bool
    hand_size: int
    available_resources: int
    total_resources: int
    resources_left_to_play: int
    next_resource_is_ready: bool
    ramp_cards: int
    draw_cards: int
    burn_cards: int
    total_direct_spell_damage: int
    own_creatures: int
    enemy_creatures: int
    enemy_flyers: int
    ready_attackers: int
    enraged_creatures: int
    trample_creatures: int
    playable_threats: int
    expected_enemy_damage: int
    best_board_wipe_enemy_kills: int
    best_board_wipe_own_losses: int
    lethal_available: bool
    opponent_lethal_threat: bool
    dangerous_board: bool
    can_ramp_safely: bool
    can_deploy_threat: bool
    needs_refuel: bool
    next_resource_goal: int

    def to_metrics(self) -> tuple[StrategyMetric, ...]:
        return (
            StrategyMetric("enemy_flyers", str(self.enemy_flyers)),
            StrategyMetric("direct_spell_damage", str(self.total_direct_spell_damage)),
            StrategyMetric("expected_enemy_damage", str(self.expected_enemy_damage)),
            StrategyMetric("board_wipe_enemy_kills", str(self.best_board_wipe_enemy_kills)),
            StrategyMetric("board_wipe_own_losses", str(self.best_board_wipe_own_losses)),
            StrategyMetric("passive_active_next_turn", str(self.passive_active_next_turn).lower()),
            StrategyMetric("can_ramp_safely", str(self.can_ramp_safely).lower()),
            StrategyMetric("can_deploy_threat", str(self.can_deploy_threat).lower()),
        )


def _estimate_enemy_damage(engine, player: PlayerState, enemy: PlayerState) -> int:
    counter = engine.ai.assessment.estimate_enemy_counterattack(engine.ai, player, enemy, attacking_ids=set())
    return int(counter["damage"])


def _evaluate_best_board_wipe(ai, player: PlayerState, enemy: PlayerState, amount: int) -> tuple[int, int]:
    result = evaluate_fire_board_wipe(ai, player, enemy, amount)
    return int(result["enemy_kills"]), int(result["own_losses"])


def _estimate_attack_damage(player: PlayerState, enemy: PlayerState) -> int:
    blockers = [creature for creature in enemy.battlefield if creature.current_hp > 0 and creature.is_ready() and not creature.cannot_block]
    damage = 0
    for creature in player.battlefield:
        if not creature.is_ready() or creature.current_hp <= 0:
            continue
        if not blockers:
            damage += creature.sw
            continue
        if creature.has_ability(Ability.TRAMPLE):
            best_overflow = max((max(0, creature.sw - blocker.current_hp) for blocker in blockers), default=0)
            damage += best_overflow
    return damage


def _estimate_total_direct_spell_damage(hand: list[CardInstance], available_resources: int, total_resources: int) -> int:
    best = 0
    for card in hand:
        if (
            card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES_AND_PLAYERS
            and available_resources >= card.template.resource_cost
            and total_resources >= card.template.recycle_cost
        ):
            best = max(best, card.template.spell_amount)
    return best


def build_fire_snapshot(ai, player: PlayerState, engine, *, hand: list[CardInstance], available_resources: int, total_resources: int, phase: str) -> FireStrategicSnapshot:
    enemy = engine.players[1 - player.player_id]
    has_infernobestie = any(card.template.template_id == "fire_creature_infernobestie" for card in hand)
    has_hoellenbestie = any(card.template.template_id == "fire_creature_hoellenbestie" for card in hand)
    ramp_cards = [card for card in hand if card.template.spell_effect == SpellEffect.DECK_TO_TAPPED_RESOURCES]
    draw_cards = [card for card in hand if card.template.spell_effect == SpellEffect.DRAW_CARDS]
    burn_cards = [card for card in hand if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE]
    board_wipes = [
        card for card in hand
        if card.template.spell_effect in (
            SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES,
            SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES_AND_PLAYERS,
        )
    ]
    own_ready = [creature for creature in player.battlefield if creature.is_ready() and creature.current_hp > 0]
    playable_threats = [
        card for card in hand
        if card.template.card_type == CardType.CREATURE
        and card.template.resource_cost >= 4
        and available_resources >= card.template.resource_cost
        and total_resources >= card.template.recycle_cost
    ]
    best_enemy_kills = 0
    best_own_losses = 0
    for wipe in board_wipes:
        enemy_kills, own_losses = _evaluate_best_board_wipe(ai, player, enemy, wipe.template.spell_amount)
        if enemy_kills - own_losses > best_enemy_kills - best_own_losses:
            best_enemy_kills, best_own_losses = enemy_kills, own_losses
    expected_enemy_damage = _estimate_enemy_damage(engine, player, enemy)
    attack_damage = _estimate_attack_damage(player, enemy)
    spell_damage = _estimate_total_direct_spell_damage(hand, available_resources, total_resources)
    enemy_flyers = sum(1 for creature in enemy.battlefield if creature.current_hp > 0 and creature.has_ability(Ability.FLYING))
    dangerous_board = bool(enemy.battlefield) and (
        expected_enemy_damage >= max(4, player.life // 3)
        or enemy_flyers > 0
        or max((creature.sw for creature in enemy.battlefield), default=0) >= 3
    )
    desired_resource_cap = 6 if has_hoellenbestie else 5 if has_infernobestie else 4
    can_ramp_safely = total_resources < desired_resource_cap and expected_enemy_damage < max(4, player.life - 5)
    needs_refuel = len(hand) <= 2 or (
        len(playable_threats) == 0
        and not burn_cards
        and len(draw_cards) > 0
    )
    if has_hoellenbestie:
        next_goal = 6
    elif has_infernobestie:
        next_goal = 5
    elif spell_damage >= 4 or len(draw_cards) > 0:
        next_goal = 5 if total_resources < 5 else total_resources
    else:
        next_goal = 4 if total_resources < 4 else total_resources
    return FireStrategicSnapshot(
        own_life=player.life,
        enemy_life=enemy.life,
        passive_active_next_turn=player.life < FIRE_SUMMONER_DRAW_THRESHOLD,
        hand_size=len(hand),
        available_resources=available_resources,
        total_resources=total_resources,
        resources_left_to_play=max(0, 2 - player.resources_played_this_turn),
        next_resource_is_ready=player.resources_played_this_turn == 0,
        ramp_cards=len(ramp_cards),
        draw_cards=len(draw_cards),
        burn_cards=len(burn_cards),
        total_direct_spell_damage=spell_damage,
        own_creatures=len(player.battlefield),
        enemy_creatures=len(enemy.battlefield),
        enemy_flyers=enemy_flyers,
        ready_attackers=len(own_ready),
        enraged_creatures=sum(1 for creature in player.battlefield if creature.has_ability(Ability.ENRAGED)),
        trample_creatures=sum(1 for creature in player.battlefield if creature.has_ability(Ability.TRAMPLE)),
        playable_threats=len(playable_threats),
        expected_enemy_damage=expected_enemy_damage,
        best_board_wipe_enemy_kills=best_enemy_kills,
        best_board_wipe_own_losses=best_own_losses,
        lethal_available=attack_damage >= enemy.life,
        opponent_lethal_threat=expected_enemy_damage >= player.life,
        dangerous_board=dangerous_board,
        can_ramp_safely=can_ramp_safely,
        can_deploy_threat=bool(playable_threats) and expected_enemy_damage < max(6, player.life - 4),
        needs_refuel=needs_refuel,
        next_resource_goal=next_goal,
    )
