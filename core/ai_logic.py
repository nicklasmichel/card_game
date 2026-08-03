from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardType, DieResult, ReactionTrigger, SpellEffect, PlayerState, SpellTargetRef


class RandomDieStrategy:
    name = "Zufaellig"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        return rng.choice(dice)


class HighestFirstDieStrategy:
    name = "Hoechster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        return max(dice, key=lambda die: (die.total, die.base_roll))


class LowestFirstDieStrategy:
    name = "Niedrigster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        return min(dice, key=lambda die: (die.total, die.base_roll))


class SacrificeLowThenHighDieStrategy:
    name = "Niedrigen Wuerfel opfern, dann hoch spielen"

    @staticmethod
    def choose(dice: List[DieResult], rng: Random) -> DieResult:
        if len(dice) >= 3:
            return min(dice, key=lambda die: (die.total, die.base_roll))
        return max(dice, key=lambda die: (die.total, die.base_roll))


class SimpleAI:
    def __init__(self, rng: Random) -> None:
        self.rng = rng

    def has_valid_spell_targets(self, player: PlayerState, engine, card: CardInstance) -> bool:
        effect = card.template.spell_effect
        enemy = engine.players[1 - player.player_id]
        if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
            return bool(enemy.battlefield or player.battlefield)
        if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
            return True
        if effect == SpellEffect.SACRIFICE_FOR_DAMAGE:
            return bool(player.battlefield) and (bool(enemy.battlefield) or enemy.life > 0)
        if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
            return bool(player.battlefield or enemy.battlefield)
        if effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
            return bool(player.battlefield or enemy.battlefield)
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            return engine.has_valid_ausweichen_target(player)
        if effect in {SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE, SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE}:
            return engine.has_valid_combat_die_target(player)
        if effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
            pending = engine.pending_direct_attack
            return pending is not None and pending.attacker_owner == player.player_id
        return True

    def mulligan_indices(self, hand: List[CardInstance]) -> List[int]:
        low_cost_count = sum(1 for card in hand if card.template.cost.total_value <= 2)
        if low_cost_count >= 2:
            return []
        return [index for index, card in enumerate(hand) if card.template.cost.total_value >= 5]

    def choose_resource_card(self, player: PlayerState) -> Optional[CardInstance]:
        if player.resources_played_this_turn >= 2 or not player.hand:
            return None
        affordable = player.available_resources()
        return max(
            player.hand,
            key=lambda card: (
                1 if card.template.resource_cost > affordable else 0,
                card.template.cost.total_value,
                card.template.aw + card.template.vw,
            ),
        )

    def choose_playable_creature(self, player: PlayerState) -> Optional[CardInstance]:
        playable = [
            card
            for card in player.hand
            if card.template.card_type == CardType.CREATURE and player.can_pay(card.template.cost)
        ]
        if not playable:
            return None
        return max(
            playable,
            key=lambda card: (
                card.template.aw + card.template.vw + len(card.template.abilities) * 2 - card.template.recycle_cost,
                -card.template.recycle_cost,
                card.template.resource_cost,
            ),
        )

    def choose_ritual(self, player: PlayerState, engine) -> Optional[CardInstance]:
        candidates = [
            card
            for card in player.hand
            if card.template.card_type in {CardType.RITUAL, CardType.SPELL} and engine.can_play_card(player, card)
            and self.has_valid_spell_targets(player, engine, card)
        ]
        if not candidates:
            return None
        scored: list[tuple[tuple[int, int, int], CardInstance]] = []
        for card in candidates:
            score = (0, 0, -card.template.resource_cost)
            if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
                killable = [creature for creature in engine.human_player.battlefield if creature.current_hp <= card.template.spell_amount]
                score = (2 if killable else 0, len(killable), -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
                lethal = 1 if engine.human_player.life <= card.template.spell_amount else 0
                threatening = max((creature.aw for creature in engine.human_player.battlefield), default=0)
                score = (3 if lethal else 1, threatening, engine.human_player.life)
            elif card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_ALL_ENEMY_CREATURES:
                affected = len(engine.human_player.battlefield)
                score = (2 if affected >= 2 else 0, affected, 0)
            elif card.template.spell_effect == SpellEffect.SACRIFICE_FOR_DAMAGE:
                if not player.battlefield:
                    continue
                cheap = min((creature.aw + creature.current_hp for creature in player.battlefield), default=99)
                score = (1, -cheap, 0)
            elif card.template.spell_effect == SpellEffect.DRAW_AND_SELF_DAMAGE:
                score = (1 if player.life > 2 else -10, len(player.hand), 0)
            elif card.template.spell_effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
                future_creatures = [hand_card for hand_card in player.hand if hand_card.template.card_type == CardType.CREATURE]
                score = (2 if future_creatures else 0, len(future_creatures), -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
                useful_targets = [creature for creature in player.battlefield if creature.current_hp > 0]
                score = (1 if useful_targets else -5, len(useful_targets), 0)
            elif card.template.spell_effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
                score = (2 if len(player.deck) >= 2 else -10, len(player.hand), 0)
            elif card.template.spell_effect == SpellEffect.BUFF_ATTACKERS_DICE_THIS_TURN:
                ready_attackers = [creature for creature in player.battlefield if creature.is_ready()]
                score = (3 if ready_attackers else -5, len(ready_attackers), 0)
            elif card.template.spell_effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
                enemy_creatures = len(engine.human_player.battlefield)
                own_creatures = len(player.battlefield)
                score = (2 if enemy_creatures else 0, enemy_creatures - own_creatures, 0)
            elif card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
                battle = engine.pending_dice_battle
                threatened = 0
                if battle is not None:
                    own_unit = engine.get_unit_by_id(battle.attacker_id if battle.attacker_owner == player.player_id else battle.blocker_id)
                    threatened = 2 if own_unit is not None and own_unit.current_hp <= 1 else 1
                score = (threatened, 0, 0)
            elif card.template.spell_effect == SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE:
                _role, dice = engine.get_player_combat_dice(player.player_id)
                low_roll = min((die.base_roll for die in dice if not die.used), default=21)
                score = (2 if low_roll <= 6 else 0, -low_roll, 0)
            elif card.template.spell_effect == SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE:
                _role, dice = engine.get_player_combat_dice(player.player_id)
                has_target = any(not die.used for die in dice)
                score = (3 if has_target else 0, len([die for die in dice if not die.used]), 0)
            elif card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
                pending = engine.pending_direct_attack
                score = (3 if pending is not None and pending.attacker_owner == player.player_id else 0, 0, 0)
            elif card.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
                score = (2 if engine.creatures_died_this_turn > 0 else 0, engine.creatures_died_this_turn, 0)
            scored.append((score, card))
        return max(scored, key=lambda item: item[0])[1] if scored else None

    def choose_sacrifice_creature(self, player: PlayerState, engine, card: CardInstance) -> Optional[BattlefieldCreature]:
        if not player.battlefield:
            return None
        return min(
            player.battlefield,
            key=lambda creature: (
                creature.current_hp,
                creature.aw + creature.vw,
                len(creature.abilities),
            ),
        )

    def choose_spell_target_ref(self, player: PlayerState, engine, card: CardInstance, pending) -> Optional[SpellTargetRef]:
        effect = card.template.spell_effect
        enemy = engine.players[1 - player.player_id]
        if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
            candidates = enemy.battlefield or player.battlefield
            if not candidates:
                return None
            chosen = min(candidates, key=lambda creature: (creature.current_hp > card.template.spell_amount, creature.current_hp, -creature.aw))
            return SpellTargetRef("creature", creature_id=chosen.unit_id)
        if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
            if enemy.life <= card.template.spell_amount:
                return SpellTargetRef("player", player_id=enemy.player_id)
            if enemy.battlefield:
                chosen = max(enemy.battlefield, key=lambda creature: (creature.aw + creature.current_hp, creature.aw))
                return SpellTargetRef("creature", creature_id=chosen.unit_id)
            return SpellTargetRef("player", player_id=enemy.player_id)
        if effect == SpellEffect.SACRIFICE_FOR_DAMAGE:
            if pending.selected_sacrifice_creature_id is None:
                return None
            if enemy.life <= next((creature.aw for creature in player.battlefield if creature.unit_id == pending.selected_sacrifice_creature_id), 0):
                return SpellTargetRef("player", player_id=enemy.player_id)
            if enemy.battlefield:
                chosen = max(enemy.battlefield, key=lambda creature: (creature.aw + creature.current_hp, creature.aw))
                return SpellTargetRef("creature", creature_id=chosen.unit_id)
            return SpellTargetRef("player", player_id=enemy.player_id)
        if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
            candidates = player.battlefield or enemy.battlefield
            if not candidates:
                return None
            chosen = max(candidates, key=lambda creature: (creature.aw, creature.current_hp))
            return SpellTargetRef("creature", creature_id=chosen.unit_id)
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            battle = engine.pending_dice_battle
            if battle is None:
                return None
            own_creature = engine.get_unit_by_id(battle.attacker_id if battle.attacker_owner == player.player_id else battle.blocker_id)
            if own_creature is None:
                return None
            return SpellTargetRef("creature", creature_id=own_creature.unit_id)
        if effect in {SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE, SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE}:
            role, dice = engine.get_player_combat_dice(player.player_id)
            if role is None:
                return None
            available = [(index, die) for index, die in enumerate(dice) if not die.used]
            if not available:
                return None
            chosen_index, _chosen_die = min(available, key=lambda item: item[1].base_roll)
            return SpellTargetRef("die", player_id=player.player_id, die_index=chosen_index, die_role=role)
        if effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
            own_selected = any(engine.get_unit_owner(target.creature_id).player_id == player.player_id for target in pending.selected_targets if target.creature_id is not None and engine.get_unit_owner(target.creature_id) is not None)
            if player.battlefield and not own_selected:
                chosen = min(player.battlefield, key=lambda creature: (creature.current_hp, creature.aw + creature.vw))
                return SpellTargetRef("creature", creature_id=chosen.unit_id)
            if enemy.battlefield:
                chosen = max(enemy.battlefield, key=lambda creature: (creature.aw + creature.current_hp, creature.aw))
                return SpellTargetRef("creature", creature_id=chosen.unit_id)
            return None
        return None

    def choose_tailwind_ability(self, creature: BattlefieldCreature) -> Ability:
        if creature is not None and not creature.has_ability(Ability.FLYING):
            return Ability.FLYING
        return Ability.HASTE

    def choose_spell(self, hand: List[CardInstance], engine) -> Optional[CardInstance]:
        legal = [
            card
            for card in hand
            if engine.can_react_with_card(engine.ai_player, card)
            and self.has_valid_spell_targets(engine.ai_player, engine, card)
        ]
        if not legal:
            return None
        scored: list[tuple[tuple[int, int], CardInstance]] = []
        for card in legal:
            score = (0, -card.template.resource_cost)
            if card.template.spell_effect == SpellEffect.MODIFY_DIE_RESULT and engine.reaction_context is not None:
                own_die = engine.get_context_die_for_player(engine.reaction_context, engine.ai_player.player_id)
                other_die = engine.reaction_context.blocker_die if own_die is engine.reaction_context.attacker_die else engine.reaction_context.attacker_die
                if own_die is not None and other_die is not None:
                    score = (3 if own_die.total <= other_die.total < own_die.total + card.template.spell_amount else 0, 0)
            elif card.template.spell_effect == SpellEffect.DAMAGE_DECLARED_BLOCKER and engine.reaction_context is not None:
                blocker = engine.reaction_context.target_creature
                score = (2 if blocker is not None and blocker.current_hp <= card.template.spell_amount else 0, 0)
            elif card.template.spell_effect == SpellEffect.DAMAGE_OPPONENT_WHEN_TARGETED:
                score = (1, 0)
            elif card.template.spell_effect == SpellEffect.RETALIATE_DICE_DAMAGE and engine.reaction_context is not None:
                opposing = engine.reaction_context.opposing_creature
                score = (2 if opposing is not None and opposing.current_hp <= card.template.spell_amount else 0, 0)
            elif card.template.spell_effect == SpellEffect.DAMAGE_AFTER_OWN_CREATURE_DESTROYED:
                score = (1, 0)
            elif card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
                battle = engine.pending_dice_battle
                own_creature = None
                if battle is not None:
                    own_creature = engine.get_unit_by_id(battle.attacker_id if battle.attacker_owner == engine.ai_player.player_id else battle.blocker_id)
                score = (3 if own_creature is not None and own_creature.current_hp <= 1 else 0, 0)
            elif card.template.spell_effect == SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE:
                _role, dice = engine.get_player_combat_dice(engine.ai_player.player_id)
                worst = min((die.base_roll for die in dice if not die.used), default=21)
                score = (2 if worst <= 6 else 0, -worst)
            elif card.template.spell_effect == SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE:
                _role, dice = engine.get_player_combat_dice(engine.ai_player.player_id)
                score = (3 if any(not die.used for die in dice) else 0, 0)
            elif card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
                pending = engine.pending_direct_attack
                score = (4 if pending is not None and pending.attacker_owner == engine.ai_player.player_id else 0, 0)
            elif card.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
                score = (2 if engine.creatures_died_this_turn > 0 else 0, engine.creatures_died_this_turn)
            scored.append((score, card))
        chosen = max(scored, key=lambda item: item[0])[1]
        return chosen if max(scored, key=lambda item: item[0])[0][0] > 0 or self.rng.random() < 0.4 else None

    def choose_resources_to_recycle(self, player: PlayerState, count: int) -> List[int]:
        if count <= 0:
            return []

        def score(resource) -> tuple[int, int, int, int]:
            template = resource.template
            return (
                len(template.abilities),
                template.aw + template.vw,
                template.cost.total_value,
                template.resource_cost,
            )

        chosen = sorted(player.resources, key=score, reverse=True)[:count]
        return [resource.resource_id for resource in chosen if resource.resource_id is not None]

    def choose_attackers(self, creatures: List[BattlefieldCreature]) -> List[BattlefieldCreature]:
        return [creature for creature in creatures if creature.is_ready()]

    def choose_blocker(self, attacker: BattlefieldCreature, blockers: List[BattlefieldCreature]) -> Optional[BattlefieldCreature]:
        if not blockers:
            return None

        def score(blocker: BattlefieldCreature) -> tuple[int, int, int]:
            survival_margin = blocker.current_hp - attacker.aw
            survives = 1 if survival_margin > 0 else 0
            return survives, -abs(survival_margin), blocker.aw

        return max(blockers, key=score)

    def choose_provoke_target(
        self,
        attacker: BattlefieldCreature,
        blockers: List[BattlefieldCreature],
    ) -> Optional[BattlefieldCreature]:
        return self.choose_blocker(attacker, blockers)

    def choose_blockers_for_attackers(
        self,
        attackers: List[BattlefieldCreature],
        blockers: List[BattlefieldCreature],
        existing_assignments: Optional[dict[int, list[int]]] = None,
    ) -> dict[int, list[int]]:
        assignments: dict[int, list[int]] = {
            attacker.unit_id: list((existing_assignments or {}).get(attacker.unit_id, []))
            for attacker in attackers
        }
        remaining_capacity = {
            blocker.unit_id: blocker.block_capacity() - sum(
                1 for attacker_ids in assignments.values() if blocker.unit_id in attacker_ids
            )
            for blocker in blockers
        }
        blockers_by_id = {blocker.unit_id: blocker for blocker in blockers}

        for attacker in sorted(attackers, key=lambda unit: (-unit.aw, unit.current_hp)):
            while True:
                available = [
                    blocker
                    for blocker in blockers
                    if remaining_capacity.get(blocker.unit_id, 0) > 0
                    and blocker.unit_id not in assignments[attacker.unit_id]
                    and (not attacker.has_ability(Ability.FLYING) or blocker.has_ability(Ability.FLYING))
                ]
                blocker = self.choose_blocker(attacker, available)
                if blocker is None:
                    break
                assignments[attacker.unit_id].append(blocker.unit_id)
                remaining_capacity[blocker.unit_id] -= 1
                if not blockers_by_id[blocker.unit_id].has_ability(Ability.DEFENDER):
                    break
                if attacker.aw <= blocker.current_hp:
                    break
                if self.rng.random() < 0.45:
                    break
        return assignments

    def choose_block_order(self, blockers: List[BattlefieldCreature]) -> List[BattlefieldCreature]:
        return sorted(
            blockers,
            key=lambda blocker: (
                -(blocker.vw - blocker.current_hp),
                blocker.current_hp,
                -blocker.aw,
            ),
        )

    def choose_die_strategy(self) -> type:
        return self.rng.choice(
            [
                RandomDieStrategy,
                HighestFirstDieStrategy,
                LowestFirstDieStrategy,
                SacrificeLowThenHighDieStrategy,
            ]
        )

    def should_use_adaptation(
        self,
        creature: BattlefieldCreature,
        own_die: DieResult,
        enemy_die: DieResult,
        would_take_damage: bool,
        would_be_destroyed: bool,
        tie: bool,
    ) -> bool:
        if not creature.has_ability(Ability.ADAPTATION):
            return False
        if would_take_damage and own_die.total < enemy_die.total:
            return True
        if tie and would_be_destroyed:
            return True
        expected_new_total = 10.5 + own_die.aw_bonus
        return expected_new_total > own_die.total and expected_new_total > enemy_die.total
