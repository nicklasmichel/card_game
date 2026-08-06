from __future__ import annotations

from core.models import Ability
from core.ai.fire.effects import choose_best_damage_target
from core.models import ReactionTrigger, SpellEffect, SpellTargetRef


def _score_attack_bonus(engine, creature, amount: int) -> float:
    blockers = [
        engine.get_unit_by_id(blocker_id)
        for blocker_id in engine.block_assignments.get(creature.unit_id, [])
        if engine.get_unit_by_id(blocker_id) is not None
    ]
    current_aw = engine.get_creature_attack_value(creature)
    score = 0.0
    if not blockers and creature.unit_id not in engine.blocked_attackers:
        score += amount * 1.4
    for blocker in blockers:
        if current_aw < blocker.current_hp <= current_aw + amount:
            score += 4.0 + blocker.aw
    if creature.has_ability(Ability.TRAMPLE):
        score += amount * 0.7
    return score


def choose_fire_reaction_spell(ai, hand, engine):
    legal = [
        card for card in hand
        if engine.can_react_with_card(engine.ai_player, card)
        and ai.has_valid_spell_targets(engine.ai_player, engine, card)
    ]
    if not legal:
        return None
    enemy = engine.players[1 - engine.ai_player.player_id]
    best = None
    best_score = 0.0
    for card in legal:
        score = 0.0
        if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
            target = choose_best_damage_target(engine, engine.ai_player, card.template.spell_amount)
            if target.target_type == "creature":
                creature = engine.get_unit_by_id(target.creature_id or -1)
                if creature is not None:
                    score = 6.0 if creature.current_hp <= card.template.spell_amount else 1.0
                    if creature.has_ability(Ability.FLYING):
                        score += 1.5
            else:
                if enemy.life <= card.template.spell_amount:
                    score = 20.0
        elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            targets = engine.get_valid_turn_attack_bonus_targets(engine.ai_player, engine.reaction_context)
            if targets:
                score = max(_score_attack_bonus(engine, target, card.template.spell_amount) for target in targets)
                score -= card.template.recycle_cost * 1.4
        if score > best_score:
            best_score = score
            best = card
    return best if best_score > 1.0 else None


def choose_fire_spell_target_ref(ai, player, engine, card, pending):
    effect = card.template.spell_effect
    if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
        return choose_best_damage_target(engine, player, card.template.spell_amount)
    if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
        targets = engine.get_valid_turn_attack_bonus_targets(player, engine.reaction_context)
        if not targets:
            return None
        chosen = max(
            targets,
            key=lambda creature: (
                engine.get_creature_attack_value(creature) + (3 if creature.has_ability(Ability.TRAMPLE) else 0),
                creature.current_hp,
            ),
        )
        return SpellTargetRef("creature", creature_id=chosen.unit_id)
    return None
