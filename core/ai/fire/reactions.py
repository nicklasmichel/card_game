from __future__ import annotations

from core.models import Ability
from core.ai.fire.effects import choose_best_damage_target
from core.models import ReactionTrigger, SpellEffect, SpellTargetRef


def _score_attack_bonus(engine, creature, aw_bonus: int, sw_bonus: int) -> float:
    blocker_id = engine.block_assignments.get(creature.unit_id)
    blocker = engine.get_unit_by_id(blocker_id) if blocker_id is not None else None
    blockers = [blocker] if blocker is not None else []
    current_aw = engine.get_creature_attack_value(creature)
    current_sw = engine.get_creature_damage_value(creature)
    score = 0.0
    if not blockers and creature.unit_id not in engine.blocked_attackers:
        score += sw_bonus * 1.6
    for blocker in blockers:
        current_sum = current_aw * 3.5
        boosted_sum = (current_aw + aw_bonus) * 3.5
        defense_sum = engine.get_creature_defense_value(blocker) * 3.5
        if current_sum <= defense_sum < boosted_sum:
            score += 4.0 + blocker.sw
        if current_sw < blocker.current_hp <= current_sw + sw_bonus:
            score += 4.5 + blocker.sw
    if creature.has_ability(Ability.TRAMPLE):
        score += sw_bonus * 0.7
    return score


def choose_fire_reaction_spell(ai, hand, engine):
    legal = [
        card for card in hand
        if engine.can_react_with_card(engine.ai_player, card)
        and ai.has_valid_spell_targets(engine.ai_player, engine, card)
    ]
    if not legal:
        return None
    best = None
    best_score = 0.0
    for card in legal:
        score = 0.0
        if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
            target = choose_best_damage_target(engine, engine.ai_player, card.template.spell_amount)
            creature = None if target is None else engine.get_unit_by_id(target.creature_id or -1)
            if creature is not None:
                score = 6.0 if creature.current_hp <= card.template.spell_amount else 1.0
                if creature.has_ability(Ability.FLYING):
                    score += 1.5
        elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            targets = engine.get_valid_turn_attack_bonus_targets(engine.ai_player, engine.reaction_context)
            if targets:
                score = max(_score_attack_bonus(engine, target, card.template.combat_aw_bonus, card.template.combat_sw_bonus) for target in targets)
                score -= card.template.recycle_cost * 1.4
        if score > best_score:
            best_score = score
            best = card
    return best if best_score > 1.0 else None


def choose_fire_spell_target_ref(ai, player, engine, card, pending):
    effect = card.template.spell_effect
    if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
        return choose_best_damage_target(engine, player, card.template.spell_amount)
    if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
        targets = engine.get_valid_turn_attack_bonus_targets(player, engine.reaction_context)
        if not targets:
            return None
        chosen = max(
            targets,
            key=lambda creature: (
                engine.get_creature_attack_value(creature) + card.template.combat_aw_bonus,
                engine.get_creature_damage_value(creature) + card.template.combat_sw_bonus + (creature.sw if creature.has_ability(Ability.TRAMPLE) else 0),
                creature.current_hp,
            ),
        )
        return SpellTargetRef("creature", creature_id=chosen.unit_id)
    return None
