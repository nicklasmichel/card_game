from __future__ import annotations

from typing import Optional

from core.ai.air.registry import get_air_creature_handler
from core.models import Ability, BattlefieldCreature, CardInstance, CardType, PlayerState, SpellEffect


class AssessmentComponent:
    def template_is_generally_draw_worthy(
        self,
        ai,
        player: PlayerState,
        engine,
        template,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
    ) -> bool:
        if template.card_type == CardType.CREATURE:
            if max(0, template.resource_cost - getattr(player, "creature_cost_reduction_this_turn", 0)) <= available_resources and template.recycle_cost <= total_resources:
                return True
            return template.resource_cost <= total_resources + 1
        effect = template.spell_effect
        if effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            return sum(1 for hand_card in hand if hand_card.template.card_type == CardType.CREATURE) >= 2 and available_resources >= template.resource_cost
        if effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
            return len(engine.get_valid_discard_creature_target_refs(player)) >= template.spell_amount
        if effect == SpellEffect.DISCARD_HAND_AND_DRAW:
            return len(player.deck) >= template.spell_draw_count and len(hand) <= max(2, template.spell_draw_count - 1)
        if effect == SpellEffect.RETURN_CREATURES_TO_HAND:
            return engine.count_valid_return_to_hand_targets() >= template.spell_amount
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
            return any(creature.is_ready() for creature in player.battlefield)
        return template.resource_cost <= available_resources and template.recycle_cost <= total_resources

    def template_improves_weak_hand(
        self,
        ai,
        player: PlayerState,
        engine,
        template,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
    ) -> bool:
        if template.card_type == CardType.CREATURE:
            if not any(hand_card.template.card_type == CardType.CREATURE for hand_card in hand):
                return True
            return max(0, template.resource_cost - getattr(player, "creature_cost_reduction_this_turn", 0)) <= total_resources + 1
        return self.template_is_generally_draw_worthy(
            ai,
            player,
            engine,
            template,
            hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )

    def reaction_hold_advantage(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        with_support: dict,
        without_support: dict,
    ) -> float:
        if with_support["ending_available_resources"] <= without_support["ending_available_resources"]:
            return 0.0
        with_ids = set(with_support["sequence"])
        without_ids = set(without_support["sequence"])
        with_remaining = [card for card in hand if card.instance_id not in with_ids]
        without_remaining = [card for card in hand if card.instance_id not in without_ids]
        if self.has_plausible_combat_reaction(ai, player, engine, with_remaining, with_support["ending_available_resources"]) and not self.has_plausible_combat_reaction(
            ai,
            player,
            engine,
            without_remaining,
            without_support["ending_available_resources"],
        ):
            return 0.4
        return 0.0

    def has_plausible_combat_reaction(self, ai, player: PlayerState, engine, hand: list[CardInstance], available_resources: int) -> bool:
        for card in hand:
            if card.template.card_type != CardType.SPELL:
                continue
            if available_resources < card.template.resource_cost:
                continue
            effect = card.template.spell_effect
            if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT and any(creature.is_ready() for creature in player.battlefield):
                return True
        return False

    def estimate_best_attack_plan(self, ai, player, enemy, hand, sequence, *, engine=None, attack_bonus_amount: int = 0):
        attackers = ai._project_air_attackers(player, hand, sequence)
        if not attackers:
            return {
                "score": 0.0,
                "attacker_ids": [],
                "target_id": None,
                "direct_damage": 0,
                "enemy_kills": 0,
                "own_losses": 0,
                "is_lethal": False,
            }
        target_ids = [None]
        if attack_bonus_amount > 0:
            target_ids = [creature.unit_id for creature in attackers]
        best = {
            "score": 0.0,
            "attacker_ids": [],
            "target_id": None,
            "direct_damage": 0,
            "enemy_kills": 0,
            "own_losses": 0,
            "is_lethal": False,
        }
        for target_id in target_ids:
            for mask in range(1, 1 << len(attackers)):
                chosen_attackers = [attackers[index] for index in range(len(attackers)) if mask & (1 << index)]
                if target_id is not None and target_id not in {creature.unit_id for creature in chosen_attackers}:
                    continue
                plan = self.score_attack_subset(
                    ai,
                    player,
                    chosen_attackers,
                    enemy,
                    attack_bonus_target_id=target_id,
                    attack_bonus_amount=attack_bonus_amount,
                    hand=hand,
                    engine=engine,
                )
                if plan["score"] > best["score"] + 0.01 or (
                    abs(plan["score"] - best["score"]) <= 0.01
                    and (plan["is_lethal"], plan["direct_damage"], len(plan["attacker_ids"]))
                    > (best["is_lethal"], best["direct_damage"], len(best["attacker_ids"]))
                ):
                    best = plan
        return best

    def score_attack_subset(
        self,
        ai,
        player: PlayerState,
        attackers: list[BattlefieldCreature],
        enemy: PlayerState,
        *,
        attack_bonus_target_id: int | None,
        attack_bonus_amount: int,
        hand: list[CardInstance] | None = None,
        engine=None,
    ) -> dict:
        strategy_weights = None
        if engine is not None:
            strategy_weights = ai._air_strategy_weights(
                player,
                engine,
                hand=list(player.hand) if hand is None else hand,
            )
        cloned_attackers = [
            ai._clone_attack_creature(
                attacker,
                attack_bonus_amount if attacker.unit_id == attack_bonus_target_id else 0,
            )
            for attacker in attackers
        ]
        blockers = ai._get_probable_blockers(enemy)
        blocker_assignments = ai.choose_blockers_for_attackers(cloned_attackers, blockers)
        blockers_by_id = {blocker.unit_id: blocker for blocker in blockers}
        score = 0.0
        direct_damage = 0
        enemy_kills = 0
        own_losses = 0
        for attacker in cloned_attackers:
            blocker_id = blocker_assignments.get(attacker.unit_id)
            assigned_blockers = [blockers_by_id[blocker_id]] if blocker_id in blockers_by_id else []
            attacker_value = attacker.sw * 1.8 + attacker.current_hp * 1.1 + len(attacker.abilities) * 0.4
            if not assigned_blockers:
                direct_damage += attacker.sw
                damage_weight = 1.45 if strategy_weights is None else 1.1 + 0.35 * strategy_weights.player_damage
                score += attacker.sw * damage_weight
                if attacker.has_ability(Ability.FLYING) and not any(blocker.has_ability(Ability.FLYING) for blocker in blockers):
                    score += 0.8 if strategy_weights is None else 0.55 + 0.25 * strategy_weights.flying_damage
                if attacker.has_ability(Ability.VIGILANT):
                    score += 0.45 if strategy_weights is None else 0.25 + 0.25 * strategy_weights.blocker_value
                continue
            blocker_aw_total = sum(blocker.aw for blocker in assigned_blockers)
            kills_here = 0
            if any(attacker.sw >= blocker.current_hp for blocker in assigned_blockers):
                kills_here = sum(1 for blocker in assigned_blockers if attacker.sw >= blocker.current_hp)
                enemy_kills += kills_here
                enemy_weight = 0.7 if strategy_weights is None else 0.45 + 0.25 * strategy_weights.enemy_losses
                score += sum((blocker.aw + blocker.current_hp * 1.1) * enemy_weight for blocker in assigned_blockers if attacker.sw >= blocker.current_hp)
            if blocker_aw_total >= attacker.current_hp:
                own_losses += 1
                own_weight = 0.8 if strategy_weights is None else 0.45 + 0.35 * strategy_weights.own_losses
                score -= attacker_value * own_weight
            else:
                score += 0.7 + attacker.sw * 0.35 + kills_here * 0.3
        if len(cloned_attackers) >= 3:
            score += 2.0 if strategy_weights is None else 1.0 + strategy_weights.third_attacker
        if direct_damage >= enemy.life:
            score += 9.0 if strategy_weights is None else 5.0 + 4.0 * strategy_weights.lethal
        counterattack = self.estimate_enemy_counterattack(
            ai,
            player,
            enemy,
            attacking_ids={attacker.unit_id for attacker in cloned_attackers},
        )
        if not direct_damage >= enemy.life:
            counter_weight = 1.0 if strategy_weights is None else strategy_weights.counterattack_risk
            if counterattack["is_lethal"]:
                score -= 12.0 * counter_weight
            elif counterattack["damage"] >= max(1, player.life - 2):
                score -= 4.5 * counter_weight
            elif counterattack["damage"] >= max(1, player.life // 2):
                score -= 1.6 * counter_weight
        return {
            "score": score,
            "attacker_ids": [attacker.unit_id for attacker in cloned_attackers],
            "target_id": attack_bonus_target_id,
            "direct_damage": direct_damage,
            "enemy_kills": enemy_kills,
            "own_losses": own_losses,
            "is_lethal": direct_damage >= enemy.life,
        }

    def estimate_enemy_counterattack(self, ai, player: PlayerState, enemy: PlayerState, *, attacking_ids: set[int]) -> dict:
        enemy_attackers = [creature for creature in enemy.battlefield if creature.current_hp > 0 and creature.is_ready()]
        if not enemy_attackers:
            return {"damage": 0, "is_lethal": False}
        remaining_blockers = [
            creature
            for creature in player.battlefield
            if creature.current_hp > 0
            and creature.is_ready()
            and (creature.unit_id not in attacking_ids or creature.has_ability(Ability.VIGILANT))
            and not creature.cannot_block
            and creature.vw > 0
        ]
        blocker_assignments = ai.choose_blockers_for_attackers(enemy_attackers, remaining_blockers)
        blockers_by_id = {blocker.unit_id: blocker for blocker in remaining_blockers}
        direct_damage = 0
        for attacker in enemy_attackers:
            blocker_id = blocker_assignments.get(attacker.unit_id)
            assigned_blockers = [blockers_by_id[blocker_id]] if blocker_id in blockers_by_id else []
            if not assigned_blockers:
                direct_damage += attacker.sw
        return {"damage": direct_damage, "is_lethal": direct_damage >= player.life}

    def count_probable_attackers(self, ai, player: PlayerState, hand: list[CardInstance]) -> int:
        ready_now = len([creature for creature in player.battlefield if creature.is_ready()])
        hasty_from_hand = len([card for card in hand if card.template.card_type == CardType.CREATURE and card.template.has_ability(Ability.HASTE)])
        return ready_now + hasty_from_hand

    def find_probable_unblocked_damage(self, ai, player: PlayerState, enemy: PlayerState, hand: list[CardInstance]) -> int:
        blockers = ai._get_probable_blockers(enemy)
        flying_blockers = len([creature for creature in blockers if creature.has_ability(Ability.FLYING)])
        probable_damage = 0
        no_blockers = not blockers
        aura_bonus = sum(getattr(creature, "own_flying_attack_aura", 0) for creature in player.battlefield if creature.current_hp > 0)
        for creature in player.battlefield:
            if not creature.is_ready():
                continue
            if no_blockers or (creature.has_ability(Ability.FLYING) and flying_blockers == 0):
                probable_damage += creature.sw
        for card in hand:
            if card.template.card_type != CardType.CREATURE:
                continue
            if not card.template.has_ability(Ability.HASTE):
                continue
            if no_blockers or (card.template.has_ability(Ability.FLYING) and flying_blockers == 0):
                probable_damage += card.template.effective_sw
        return probable_damage

    def count_unblockable_haste_attackers(self, ai, player: PlayerState, enemy: PlayerState, hand: list[CardInstance]) -> int:
        blockers = ai._get_probable_blockers(enemy)
        flying_blockers = [creature for creature in blockers if creature.has_ability(Ability.FLYING)]
        count = 0
        for creature in player.battlefield:
            if not creature.is_ready():
                continue
            if creature.has_ability(Ability.HASTE) and (not blockers or (creature.has_ability(Ability.FLYING) and not flying_blockers)):
                count += 1
        for card in hand:
            if card.template.card_type != CardType.CREATURE or not card.template.has_ability(Ability.HASTE):
                continue
            if not blockers or (card.template.has_ability(Ability.FLYING) and not flying_blockers):
                count += 1
        return count

    def generic_creature_keep_adjustment(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        card: CardInstance,
        hand: list[CardInstance],
        *,
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> float:
        template = card.template
        blockers = ai._get_probable_blockers(enemy)
        flying_blockers = [creature for creature in blockers if creature.has_ability(Ability.FLYING)]
        attack_now = 0.0
        if template.has_ability(Ability.HASTE):
            if not blockers:
                attack_now += template.aw * 1.7 + 1.1
            elif template.has_ability(Ability.FLYING) and not flying_blockers:
                attack_now += template.aw * 1.8 + 1.3
            else:
                bad_trade = any(blocker.aw >= template.vw and blocker.current_hp >= template.aw for blocker in blockers)
                if bad_trade:
                    attack_now -= 0.9
                else:
                    attack_now += 0.7 + template.aw * 0.35
        flight_pressure = 0.0
        if template.has_ability(Ability.FLYING):
            if not flying_blockers:
                flight_pressure += 1.8 + template.aw * 0.35 + template.vw * 0.15
            elif len(flying_blockers) == 1:
                flight_pressure += 0.7
            else:
                flight_pressure -= 0.3

        probable_attackers = self.count_probable_attackers(ai, player, hand)
        third_attacker_bonus = 0.0
        if probable_attackers == 2:
            if template.has_ability(Ability.HASTE):
                third_attacker_bonus += 1.8
                if attack_now <= 0.0:
                    third_attacker_bonus -= 0.7
            elif template.has_ability(Ability.FLYING):
                third_attacker_bonus += 1.2 if not flying_blockers else 0.5

        lethal_bonus = 0.0
        unblocked_damage = self.find_probable_unblocked_damage(ai, player, enemy, hand)
        if enemy.life <= unblocked_damage:
            lethal_bonus += 2.8
        elif template.has_ability(Ability.HASTE) and enemy.life <= unblocked_damage + template.aw:
            lethal_bonus += 2.0

        spell_bonus = 0.0
        has_attack_spell = any(
            hand_card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT
            for hand_card in hand
            if hand_card.template.spell_effect is not None and hand_card.instance_id != card.instance_id
        )
        if has_attack_spell:
            if template.has_ability(Ability.HASTE):
                spell_bonus += 0.8
            if template.has_ability(Ability.FLYING) and not flying_blockers:
                spell_bonus += 0.9

        recycle_penalty = 0.0
        remaining_after_recycle = projected_total_resources - template.recycle_cost
        if template.recycle_cost > 0:
            recycle_penalty -= template.recycle_cost * 0.6
            if remaining_after_recycle <= 0:
                recycle_penalty -= 2.4
            elif remaining_after_recycle == 1:
                recycle_penalty -= 1.4
            elif remaining_after_recycle == 2:
                recycle_penalty -= 0.6

        base_curve = 0.15 * template.aw + 0.1 * template.vw
        return base_curve + attack_now + flight_pressure + third_attacker_bonus + lethal_bonus + spell_bonus + recycle_penalty

    def find_lethal_enabler(self, ai, player: PlayerState, enemy: PlayerState, hand: list[CardInstance]) -> Optional[CardInstance]:
        probable_unblocked_damage = self.find_probable_unblocked_damage(ai, player, enemy, hand)
        if probable_unblocked_damage <= 0:
            return None
        for card in hand:
            if (
                card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT
                and probable_unblocked_damage + card.template.combat_sw_bonus >= enemy.life
            ):
                return card
        return None

    def find_only_answer_card(self, ai, player: PlayerState, enemy: PlayerState, engine, hand: list[CardInstance]) -> Optional[CardInstance]:
        if not enemy.battlefield:
            return None
        threatening_enemy = max(enemy.battlefield, key=lambda creature: creature.aw + creature.current_hp)
        if threatening_enemy.aw + threatening_enemy.current_hp < 6:
            return None
        answers = [card for card in hand if card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND]
        if len(answers) == 1:
            return answers[0]
        defensive_creatures = [
            card for card in hand
            if card.template.card_type == CardType.CREATURE and not card.template.cannot_block
        ]
        if len(defensive_creatures) == 1 and not player.battlefield:
            return defensive_creatures[0]
        return None

    def specific_creature_keep_adjustment(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        card: CardInstance,
        hand: list[CardInstance],
        *,
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> float:
        handler = get_air_creature_handler(card.template.template_id)
        if handler is None:
            return self.generic_creature_keep_adjustment(
                ai,
                player,
                enemy,
                card,
                hand,
                projected_available_resources=projected_available_resources,
                projected_total_resources=projected_total_resources,
            )
        return handler.keep_adjustment(
            ai,
            player,
            enemy,
            card,
            hand,
            projected_available_resources=projected_available_resources,
            projected_total_resources=projected_total_resources,
        )

    def specific_spell_keep_adjustment(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        engine,
        card: CardInstance,
        hand: list[CardInstance],
        *,
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> float:
        effect = card.template.spell_effect
        handler = ai._get_air_card_handler(card)
        if handler is not None:
            specialized = handler.keep_adjustment(
                ai,
                player,
                enemy,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            if specialized is not None:
                return specialized
        if effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            comparison = ai._evaluate_air_cost_reduction_support_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return 2.8 if comparison["is_useful"] else -3.2
        if effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
            comparison = ai._evaluate_air_windruf_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return 2.3 if comparison["is_useful"] else -2.2
        if effect == SpellEffect.DISCARD_HAND_AND_DRAW:
            comparison = ai._evaluate_air_sturmruf_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            if card.template.spell_amount >= 5:
                return 2.3 if comparison["is_useful"] else -3.0
            return 3.0 if comparison["is_useful"] else -3.2
        if effect == SpellEffect.RETURN_CREATURES_TO_HAND:
            comparison = ai._evaluate_air_bounce_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
            )
            return 2.4 if comparison["is_useful"] else -3.0
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
            comparison = ai._evaluate_air_global_attack_bonus_reaction_plan(player, engine, card)
            return 2.6 if comparison["is_useful"] else -2.8
        return 0.0
