from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardType, DieResult, PHASE_REACTION, PHASE_SPELL_TARGETING, PlayerState, ReactionTrigger, SpellEffect, SpellTargetRef

class AirReactionMixin:
    def choose_cards_to_discard(self, player: PlayerState, engine, count: int, source_card_name: str = "") -> List[CardInstance]:
        if count <= 0 or not player.hand:
            return []
        if getattr(player, "summoner_key", "") == "air":
            return self._choose_air_cards_to_discard(player, engine, count)
        return sorted(
            player.hand,
            key=lambda card: (
                card.template.cost.total_value,
                card.template.aw + card.template.vw,
                len(card.template.abilities),
            ),
        )[:count]

    def _choose_air_cards_to_discard(self, player: PlayerState, engine, count: int) -> List[CardInstance]:
        chosen: list[CardInstance] = []
        remaining_hand = list(player.hand)
        for _ in range(min(count, len(remaining_hand))):
            protected_ids = self._air_current_plan_protected_ids(
                player,
                engine,
                remaining_hand,
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
            )
            duplicate_counts = self._template_counts(remaining_hand)
            scored_cards: list[tuple[tuple[float, int, int, int, int], CardInstance]] = []
            for card in remaining_hand:
                keep_value = self._air_resource_keep_value(
                    player,
                    engine,
                    card,
                    hand=remaining_hand,
                    projected_available_resources=player.available_resources(),
                    projected_total_resources=player.total_resources(),
                    duplicate_count=duplicate_counts.get(card.template.template_id, 1),
                    protected_ids=protected_ids,
                )
                tie_break = (
                    keep_value,
                    0 if duplicate_counts.get(card.template.template_id, 1) > 1 else 1,
                    0 if not self._air_card_has_live_use(player, engine, card, remaining_hand, player.available_resources(), player.total_resources()) else 1,
                    0 if self._air_card_role_is_redundant(card, remaining_hand) else 1,
                    0 if card.template.card_type != CardType.CREATURE else 1,
                )
                scored_cards.append((tie_break, card))
            scored_cards.sort(key=lambda item: item[0])
            selected = scored_cards[0][1]
            chosen.append(selected)
            remaining_hand = [card for card in remaining_hand if card.instance_id != selected.instance_id]
        return chosen

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
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized_score = handler.score_ritual(self, player, engine, card)
                if specialized_score is not None:
                    scored.append((specialized_score, card))
                    continue
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
                comparison = self._evaluate_air_cost_reduction_support_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                score = (
                    2 if comparison["is_useful"] else -2,
                    int(comparison["value"] * 10),
                    -card.template.resource_cost,
                )
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
                valid_targets = engine.get_valid_discard_creature_target_refs(player)
                score = (
                    2 if len(valid_targets) >= card.template.spell_amount else -10,
                    len(valid_targets),
                    -card.template.resource_cost,
                )
            elif card.template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW:
                score = (
                    2 if len(player.deck) >= card.template.spell_draw_count and len(player.hand) <= 2 else -2,
                    card.template.spell_draw_count - len(player.hand),
                    -card.template.recycle_cost,
                )
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
                total_targets = len(player.battlefield) + len(engine.human_player.battlefield)
                score = (
                    1 if total_targets >= card.template.spell_amount else -10,
                    len(engine.human_player.battlefield),
                    -card.template.resource_cost,
                )
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
                attacker_count = len(engine.get_current_attacker_creatures(player))
                score = (
                    2 if attacker_count > 0 else -10,
                    attacker_count * card.template.spell_amount,
                    -card.template.resource_cost,
                )
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
                useful_targets = [creature for creature in player.battlefield if creature.current_hp > 0]
                score = (1 if useful_targets else -5, len(useful_targets), 0)
            elif card.template.spell_effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
                score = (2 if len(player.deck) >= card.template.spell_draw_count else -10, len(player.hand), 0)
            elif card.template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
                comparison = self._evaluate_air_sturmformation_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                score = (
                    2 if comparison["is_useful"] else -2,
                    int(comparison["value"] * 10),
                    -card.template.resource_cost,
                )
            elif card.template.spell_effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
                comparison = self._evaluate_air_turbulenz_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                score = (
                    2 if comparison["is_useful"] else -2,
                    int(comparison["value"] * 10),
                    1 if any(
                        engine.get_unit_owner(target_id) == engine.human_player
                        for target_id in comparison.get("target_ids", [])
                        if engine.get_unit_by_id(target_id) is not None
                    ) else 0,
                )
            elif card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
                battle = engine.pending_dice_battle
                threatened = 0
                if battle is not None:
                    own_unit = engine.get_unit_by_id(battle.attacker_id if battle.attacker_owner == player.player_id else battle.blocker_id)
                    threatened = 2 if own_unit is not None and own_unit.current_hp <= 1 else 1
                score = (threatened, 0, 0)
            elif card.template.spell_effect == SpellEffect.REROLL_OPEN_DIE:
                _target, target_score = self._best_windstoss_target(player, engine)
                score = (2 if target_score >= 2.0 else 1 if target_score >= 0.9 else 0, int(target_score * 10), 0)
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT:
                comparison = self._evaluate_air_boeenschub_reaction_plan(player, engine, card)
                score = (2 if comparison["is_useful"] else 0, int(comparison["value"] * 10), 0)
            elif card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
                comparison = self._evaluate_air_windrausch_reaction_plan(player, engine, card)
                score = (2 if comparison["is_useful"] else 0, int(comparison["value"] * 10), 0)
            elif card.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
                comparison = self._evaluate_air_nachwehen_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                )
                score = (2 if comparison["is_useful"] else 0, int(comparison["value"] * 10), 0)
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

    def _get_open_die_owner(self, engine, target: SpellTargetRef):
        open_target = engine.open_die_targets.get(target.open_die_id)
        if open_target is None:
            return None
        player_id = open_target.get("player_id")
        if player_id is None:
            return None
        return engine.players[player_id]

    def _score_windstoss_target(self, player: PlayerState, engine, target: SpellTargetRef) -> float:
        die = engine.resolve_target_open_die(target)
        if die is None:
            return -999.0
        owner = self._get_open_die_owner(engine, target)
        if owner is None:
            return -999.0
        expected_shift = 10.5 - die.base_roll
        if owner.player_id != player.player_id:
            expected_shift = die.base_roll - 10.5

        battle = engine.pending_dice_battle
        comparison = getattr(battle, "pending_comparison", None) if battle is not None else None
        if comparison is not None and (die is comparison.attacker_die or die is comparison.blocker_die):
            attacker = engine.get_unit_by_id(battle.attacker_id)
            blocker = engine.get_unit_by_id(battle.blocker_id)
            if attacker is None or blocker is None:
                return expected_shift * 0.4
            own_is_attacker = battle.attacker_owner == player.player_id
            own_die = comparison.attacker_die if own_is_attacker else comparison.blocker_die
            enemy_die = comparison.blocker_die if own_is_attacker else comparison.attacker_die
            own_unit = attacker if own_is_attacker else blocker
            enemy_unit = blocker if own_is_attacker else attacker
            margin = own_die.total - enemy_die.total
            future_margin = margin + expected_shift if owner.player_id == player.player_id else margin - expected_shift
            current_loss = margin <= 0
            future_loss = future_margin <= 0
            score = expected_shift * 0.55
            if current_loss and not future_loss:
                score += 6.0 + self._air_creature_board_value(own_unit) * 0.55
            if not current_loss and future_loss:
                score -= 5.0 + self._air_creature_board_value(own_unit) * 0.45
            if current_loss:
                score += min(5.5, self._air_creature_board_value(own_unit) * 0.35)
            if margin > 0 and die is enemy_die:
                score += min(3.0, expected_shift * 0.4)
            if margin <= 0 and die is own_die:
                score += min(3.5, (10.5 - die.base_roll) * 0.5)
            if own_unit.current_hp <= 1 and current_loss:
                score += 3.2
            if enemy_unit.current_hp <= 1 and margin > 0 and die is enemy_die:
                score += 1.2
            return score

        score = expected_shift * 0.35
        if owner.player_id == player.player_id and die.base_roll <= 4:
            score += 1.4
        if owner.player_id != player.player_id and die.base_roll >= 17:
            score += 1.4
        if owner.player_id == player.player_id and die.base_roll >= 14:
            score -= 2.4
        if owner.player_id != player.player_id and die.base_roll <= 7:
            score -= 2.1
        return score

    def _best_windstoss_target(self, player: PlayerState, engine) -> tuple[Optional[SpellTargetRef], float]:
        handler = self._get_air_card_handler_by_template_id("air_spell_windstoss")
        if handler is None or not hasattr(handler, "best_target"):
            return None, -999.0
        return handler.best_target(self, player, engine)

    def choose_spell_target_ref(self, player: PlayerState, engine, card: CardInstance, pending) -> Optional[SpellTargetRef]:
        effect = card.template.spell_effect
        enemy = engine.players[1 - player.player_id]
        handler = self._get_air_card_handler(card)
        if handler is not None:
            specialized_target = handler.choose_target_ref(self, player, engine, card, pending)
            if specialized_target is not None:
                return specialized_target
        if effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
            selected_ids = {target.card_instance_id for target in pending.selected_targets if target.card_instance_id is not None}
            valid_targets = [
                target for target in engine.get_valid_discard_creature_target_refs(player)
                if target.card_instance_id not in selected_ids
            ]
            if not valid_targets:
                return None
            return max(
                valid_targets,
                key=lambda target: (
                    (engine.resolve_target_discard_card(target).template.aw + engine.resolve_target_discard_card(target).template.vw)
                    if engine.resolve_target_discard_card(target) is not None else -999,
                    -(engine.resolve_target_discard_card(target).template.resource_cost)
                    if engine.resolve_target_discard_card(target) is not None else 0,
                ),
            )
        if effect == SpellEffect.RETURN_CREATURES_TO_HAND:
            selected_ids = {target.creature_id for target in pending.selected_targets if target.creature_id is not None}
            candidates = [
                creature for creature in player.battlefield + enemy.battlefield
                if creature.unit_id not in selected_ids
            ]
            if not candidates:
                return None
            chosen = max(
                candidates,
                key=lambda creature: (
                    1 if engine.get_unit_owner(creature.unit_id) == enemy else 0,
                    creature.aw + creature.current_hp,
                    creature.aw,
                ),
            )
            return SpellTargetRef("creature", creature_id=chosen.unit_id)
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
            return None
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
        if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            if self._planned_rueckenwind_target_id is not None:
                chosen = next((creature for creature in player.battlefield if creature.unit_id == self._planned_rueckenwind_target_id), None)
                if chosen is not None:
                    return SpellTargetRef("creature", creature_id=chosen.unit_id)
            best_plan = self._estimate_best_air_attack_plan(
                player,
                enemy,
                list(player.hand),
                [],
                attack_bonus_amount=card.template.spell_amount,
            )
            if best_plan["target_id"] is None:
                return None
            return SpellTargetRef("creature", creature_id=best_plan["target_id"])
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT:
            comparison = self._evaluate_air_boeenschub_reaction_plan(player, engine, card)
            if comparison["target_id"] is None or not comparison["is_useful"]:
                return None
            return SpellTargetRef("creature", creature_id=comparison["target_id"])
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            comparison = self._evaluate_air_ausweichen_plan(
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
            )
            if comparison["target_id"] is None or not comparison["is_useful"]:
                return None
            own_creature = engine.get_unit_by_id(comparison["target_id"])
            if own_creature is None:
                return None
            return SpellTargetRef("creature", creature_id=own_creature.unit_id)
        if effect == SpellEffect.REROLL_OPEN_DIE:
            chosen, score = self._best_windstoss_target(player, engine)
            if chosen is None or score <= 0.65:
                return None
            return chosen
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            if self._planned_turbulenz_target_ids:
                selected_ids = {target.creature_id for target in pending.selected_targets if target.creature_id is not None}
                for target_id in self._planned_turbulenz_target_ids:
                    if target_id in selected_ids:
                        continue
                    creature = engine.get_unit_by_id(target_id)
                    if creature is not None:
                        return SpellTargetRef("creature", creature_id=creature.unit_id)
            selected_ids = {target.creature_id for target in pending.selected_targets if target.creature_id is not None}
            candidates = [
                creature
                for creature in player.battlefield + enemy.battlefield
                if creature.unit_id not in selected_ids
            ]
            if candidates:
                chosen = max(
                    candidates,
                    key=lambda creature: (
                        1 if engine.get_unit_owner(creature.unit_id) == enemy else 0,
                        creature.aw + creature.current_hp,
                        creature.aw,
                    ),
                )
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
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized_score = handler.score_reaction(self, engine.ai_player, engine, card)
                if specialized_score is not None:
                    scored.append((specialized_score, card))
                    continue
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
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
                total_targets = len(engine.ai_player.battlefield) + len(engine.human_player.battlefield)
                score = (2 if total_targets >= card.template.spell_amount else -10, len(engine.human_player.battlefield))
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
                attackers = len(engine.get_current_attacker_creatures(engine.ai_player, engine.reaction_context))
                score = (2 if attackers > 0 else -10, attackers * card.template.spell_amount)
            elif card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
                comparison = self._evaluate_air_ausweichen_plan(
                    engine.ai_player,
                    engine,
                    card,
                    hand=list(engine.ai_player.hand),
                    available_resources=engine.ai_player.available_resources(),
                    total_resources=engine.ai_player.total_resources(),
                )
                score = (max(-3, int(comparison["value"] * 2)), 1 if comparison["recast_target"] else 0)
            elif card.template.spell_effect == SpellEffect.REROLL_OPEN_DIE:
                _target, target_score = self._best_windstoss_target(engine.ai_player, engine)
                score = (max(-4, int(target_score * 2)), 0)
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT:
                comparison = self._evaluate_air_boeenschub_reaction_plan(engine.ai_player, engine, card)
                score = (max(-4, int(comparison["value"] * 2)), 1 if comparison["target_id"] is not None else 0)
            elif card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
                comparison = self._evaluate_air_windrausch_reaction_plan(engine.ai_player, engine, card)
                score = (max(-4, int(comparison["value"] * 2)), 1 if comparison["is_lethal"] else 0)
            elif card.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
                comparison = self._evaluate_air_nachwehen_plan(
                    engine.ai_player,
                    engine,
                    card,
                    hand=list(engine.ai_player.hand),
                    available_resources=engine.ai_player.available_resources(),
                    total_resources=engine.ai_player.total_resources(),
                )
                score = (max(-4, int(comparison["value"] * 2)), 1 if comparison["draw_count"] >= 6 else 0)
            scored.append((score, card))
        best_score, chosen = max(scored, key=lambda item: item[0])
        if chosen.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.REROLL_OPEN_DIE and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN and best_score[0] <= 0:
            return None
        return chosen if best_score[0] > 0 or self.rng.random() < 0.4 else None

