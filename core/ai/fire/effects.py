from __future__ import annotations

from dataclasses import dataclass, replace

from core.config import FIRE_SUMMONER_DRAW_THRESHOLD
from core.models import Ability, BattlefieldCreature, CardInstance, PlayerState, SpellEffect, SpellTargetRef


@dataclass(slots=True, frozen=True)
class ProjectedGlobalDamageState:
    own_life: int
    enemy_life: int
    own_survivors: tuple[BattlefieldCreature, ...]
    enemy_survivors: tuple[BattlefieldCreature, ...]
    own_losses: int
    enemy_kills: int
    own_damage_marked: int
    enemy_damage_marked: int
    immediate_win: bool
    immediate_loss: bool
    is_draw: bool
    projected_attack_damage: int
    projected_enemy_counterattack_damage: int


def _clone_survivors(creatures: list[BattlefieldCreature], amount: int) -> tuple[BattlefieldCreature, ...]:
    survivors: list[BattlefieldCreature] = []
    for creature in creatures:
        projected_hp = creature.current_hp - amount
        if projected_hp <= 0:
            continue
        survivors.append(replace(creature, current_hp=projected_hp))
    return tuple(survivors)


def _legal_blockers_for_attacker(attackers_owner_blockers: list[BattlefieldCreature], attacker: BattlefieldCreature) -> list[BattlefieldCreature]:
    legal: list[BattlefieldCreature] = []
    for blocker in attackers_owner_blockers:
        if blocker.current_hp <= 0 or not blocker.is_ready() or blocker.cannot_block or blocker.vw <= 0:
            continue
        if attacker.has_ability(Ability.FLYING) and not blocker.has_ability(Ability.FLYING):
            continue
        legal.append(blocker)
    return legal


def _estimate_projected_attack_damage(attackers: tuple[BattlefieldCreature, ...], blockers: tuple[BattlefieldCreature, ...]) -> int:
    ready_attackers = [creature for creature in attackers if creature.current_hp > 0 and creature.is_ready()]
    if not ready_attackers:
        return 0
    remaining_blockers = [creature for creature in blockers if creature.current_hp > 0 and creature.is_ready() and not creature.cannot_block and creature.vw > 0]
    damage = 0
    for attacker in ready_attackers:
        legal_blockers = _legal_blockers_for_attacker(remaining_blockers, attacker)
        if not legal_blockers:
            damage += attacker.sw
            continue
        if attacker.has_ability(Ability.TRAMPLE):
            damage += max(0, attacker.sw - min(blocker.current_hp for blocker in legal_blockers))
        chosen = max(legal_blockers, key=lambda blocker: blocker.current_hp)
        remaining_blockers = [blocker for blocker in remaining_blockers if blocker.unit_id != chosen.unit_id]
    return damage


def project_fire_global_damage_state(ai, player: PlayerState, enemy: PlayerState, amount: int) -> ProjectedGlobalDamageState:
    own_survivors = _clone_survivors(player.battlefield, amount)
    enemy_survivors = _clone_survivors(enemy.battlefield, amount)
    own_life = player.life - amount
    enemy_life = enemy.life - amount
    projected_attack_damage = _estimate_projected_attack_damage(own_survivors, enemy_survivors)
    projected_player = PlayerState(player.player_id, player.name, player.is_human, summoner_key=player.summoner_key, life=own_life, battlefield=list(own_survivors))
    projected_enemy = PlayerState(enemy.player_id, enemy.name, enemy.is_human, summoner_key=enemy.summoner_key, life=enemy_life, battlefield=list(enemy_survivors))
    projected_enemy_counterattack_damage = ai.assessment.estimate_enemy_counterattack(ai, projected_player, projected_enemy, attacking_ids=set())["damage"]
    return ProjectedGlobalDamageState(
        own_life=own_life,
        enemy_life=enemy_life,
        own_survivors=own_survivors,
        enemy_survivors=enemy_survivors,
        own_losses=sum(1 for creature in player.battlefield if creature.current_hp <= amount),
        enemy_kills=sum(1 for creature in enemy.battlefield if creature.current_hp <= amount),
        own_damage_marked=sum(min(amount, creature.current_hp) for creature in player.battlefield),
        enemy_damage_marked=sum(min(amount, creature.current_hp) for creature in enemy.battlefield),
        immediate_win=enemy_life <= 0 < own_life,
        immediate_loss=own_life <= 0 < enemy_life,
        is_draw=own_life <= 0 and enemy_life <= 0,
        projected_attack_damage=projected_attack_damage,
        projected_enemy_counterattack_damage=int(projected_enemy_counterattack_damage),
    )


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
    creatures = [
        creature
        for creature in enemy.battlefield + player.battlefield
        if engine.can_target_creature_with_explicit_spell(creature)
    ]
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


def evaluate_fire_board_wipe(ai, player: PlayerState, enemy: PlayerState, amount: int) -> dict:
    projected = project_fire_global_damage_state(ai, player, enemy, amount)
    if projected.immediate_win:
        return {
            "is_useful": True,
            "score": 1000.0 + projected.enemy_kills * 2.0,
            "enemy_kills": projected.enemy_kills,
            "own_losses": projected.own_losses,
            "is_lethal": True,
            "is_draw": False,
        }
    if projected.immediate_loss:
        return {
            "is_useful": False,
            "score": -1000.0,
            "enemy_kills": projected.enemy_kills,
            "own_losses": projected.own_losses,
            "is_lethal": False,
            "is_draw": False,
        }
    draw_score = 0.0
    if projected.is_draw:
        draw_score = 18.0 if ai.assessment.estimate_enemy_counterattack(ai, player, enemy, attacking_ids=set())["is_lethal"] else -8.0
    score = (
        projected.enemy_kills * 5.5
        + projected.enemy_damage_marked * 0.6
        - projected.own_losses * 4.2
        - projected.own_damage_marked * 0.45
        + amount * 1.8
        + projected.projected_attack_damage * 8.0
        - projected.projected_enemy_counterattack_damage * 5.5
        + draw_score
    )
    post_ritual_lethal = projected.enemy_life > 0 and projected.own_life > 0 and projected.projected_attack_damage >= projected.enemy_life
    if post_ritual_lethal:
        score += 60.0
    if projected.projected_enemy_counterattack_damage >= max(1, projected.own_life):
        score -= 80.0
    return {
        "is_useful": post_ritual_lethal or projected.is_draw or score > 2.0,
        "score": score,
        "enemy_kills": projected.enemy_kills,
        "own_losses": projected.own_losses,
        "is_lethal": projected.immediate_win or post_ritual_lethal,
        "is_draw": projected.is_draw,
        "projected_attack_damage": projected.projected_attack_damage,
        "projected_enemy_counterattack_damage": projected.projected_enemy_counterattack_damage,
        "projected_enemy_life": projected.enemy_life,
        "projected_own_life": projected.own_life,
    }


def evaluate_fire_draw_spell(player: PlayerState, card: CardInstance) -> float:
    draw_count = card.template.spell_draw_count
    passive_discount = 0.45 if player.life < FIRE_SUMMONER_DRAW_THRESHOLD else 0.0
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
    return ramp * 2.4 + min(ramp, gap) * 1.2 - max(0, player.total_resources() - 5) * 1.5
