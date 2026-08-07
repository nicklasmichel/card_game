from __future__ import annotations

from core.models import Ability, CardInstance, PlayerState, SpellEffect, SpellTargetRef


def score_fire_damage_target(player: PlayerState, enemy: PlayerState, amount: int, target) -> float:
    if target.current_hp <= 0:
        return -999.0
    owner_is_enemy = target in enemy.battlefield
    threat = target.aw * 2.2 + target.current_hp
    flyer_bonus = 2.4 if target.has_ability(Ability.FLYING) else 0.0
    kill_bonus = 8.0 if target.current_hp <= amount else amount * 0.6
    wounded_bonus = 1.2 if target.current_hp <= amount + 1 else 0.0
    own_penalty = 5.0 if not owner_is_enemy else 0.0
    return (threat + flyer_bonus + kill_bonus + wounded_bonus) if owner_is_enemy else -own_penalty


def choose_best_damage_target(engine, player: PlayerState, amount: int) -> SpellTargetRef | None:
    enemy = engine.players[1 - player.player_id]
    creatures = enemy.battlefield + player.battlefield
    if not creatures:
        return None
    best_creature = creatures[0]
    best_score = score_fire_damage_target(player, enemy, amount, best_creature)
    for creature in creatures[1:]:
        score = score_fire_damage_target(player, enemy, amount, creature)
        if score > best_score:
            best_score = score
            best_creature = creature
    return SpellTargetRef("creature", creature_id=best_creature.unit_id)


def evaluate_fire_board_wipe(player: PlayerState, enemy: PlayerState, amount: int) -> dict:
    enemy_kills = sum(1 for creature in enemy.battlefield if creature.current_hp <= amount)
    own_losses = sum(1 for creature in player.battlefield if creature.current_hp <= amount)
    enemy_damage_marked = sum(min(amount, creature.current_hp) for creature in enemy.battlefield)
    own_damage_marked = sum(min(amount, creature.current_hp) for creature in player.battlefield)
    score = enemy_kills * 5.5 + enemy_damage_marked * 0.6 - own_losses * 4.2 - own_damage_marked * 0.45
    return {
        "is_useful": score > 2.0,
        "score": score,
        "enemy_kills": enemy_kills,
        "own_losses": own_losses,
    }


def evaluate_fire_draw_spell(player: PlayerState, card: CardInstance) -> float:
    draw_count = card.template.spell_draw_count
    passive_discount = 0.45 if player.life < 10 else 0.0
    base = draw_count * 2.2 - passive_discount
    if len(player.hand) <= 2:
        base += 1.8
    if len(player.hand) >= 5:
        base -= 1.2
    if draw_count == 3 and len(player.hand) <= 1:
        base += 0.7
    return base


def evaluate_fire_ramp_spell(player: PlayerState, card: CardInstance, next_resource_goal: int) -> float:
    ramp = card.template.spell_amount
    gap = max(0, next_resource_goal - player.total_resources())
    if gap <= 0:
        return -2.0
    return ramp * 2.4 + min(ramp, gap) * 1.2 - max(0, player.total_resources() - 4) * 1.5
