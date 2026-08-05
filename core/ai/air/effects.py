from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardType, DieResult, PHASE_REACTION, PHASE_SPELL_TARGETING, PlayerState, ReactionTrigger, SpellEffect, SpellTargetRef

class AirEffectEvaluationMixin:
    def _evaluate_air_cost_reduction_support_plan(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> dict:
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost:
            return {"is_useful": False, "value": -4.0}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        without_support = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=next_available,
            total_resources=next_total,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        with_support = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=next_available,
            total_resources=next_total,
            start_creature_discount=creature_discount + card.template.spell_amount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        if with_support["creatures_played"] <= 0:
            return {"is_useful": False, "value": -4.0}
        reaction_bonus = self._air_reaction_hold_advantage(
            player,
            engine,
            remaining_hand,
            with_support,
            without_support,
        )
        improved = (
            with_support["creatures_played"] > without_support["creatures_played"]
            or with_support["cards_played"] > without_support["cards_played"]
            or with_support["creature_value"] > without_support["creature_value"] + 0.4
            or reaction_bonus > 0.0
        )
        if not improved:
            return {"is_useful": False, "value": -3.2}
        score_delta = with_support["score"] - without_support["score"]
        value = 0.6 + max(0.0, score_delta) * 0.3 + reaction_bonus
        return {"is_useful": True, "value": value}

    def _evaluate_air_attack_bonus_support_plan(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> dict:
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        legal_target_ids = {
            creature.unit_id
            for creature in player.battlefield
            if creature.current_hp > 0
        }
        if not legal_target_ids:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        without_support = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        with_support = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=next_available,
            total_resources=next_total,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        enemy = engine.players[1 - player.player_id]
        without_attack = self._estimate_best_air_attack_plan(player, enemy, remaining_hand, without_support["sequence"])
        with_attack = self._estimate_best_air_attack_plan(
            player,
            enemy,
            remaining_hand,
            with_support["sequence"],
            attack_bonus_amount=card.template.spell_amount,
        )
        if (
            with_attack["target_id"] is None
            or with_attack["target_id"] not in legal_target_ids
            or not with_attack["attacker_ids"]
        ):
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        without_total = without_support["score"] + without_attack["score"]
        with_total = with_support["score"] + with_attack["score"] - 1.4
        direct_damage_gain = with_attack["direct_damage"] - without_attack["direct_damage"]
        enemy_kill_gain = with_attack["enemy_kills"] - without_attack["enemy_kills"]
        own_loss_improvement = without_attack["own_losses"] - with_attack["own_losses"]
        lethal_gain = with_attack["is_lethal"] and not without_attack["is_lethal"]
        if without_attack["is_lethal"] and not lethal_gain and enemy_kill_gain <= 0 and own_loss_improvement <= 0:
            return {
                "is_useful": False,
                "value": -3.4,
                "with_total": with_total,
                "continuation_sequence": [],
                "attacker_ids": [],
                "target_id": None,
            }
        improved_attack = lethal_gain or direct_damage_gain > 0 or enemy_kill_gain > 0 or own_loss_improvement > 0
        if not improved_attack or with_total <= without_total + 0.65:
            return {
                "is_useful": False,
                "value": -3.4,
                "with_total": with_total,
                "continuation_sequence": [],
                "attacker_ids": [],
                "target_id": None,
            }
        value = 0.7 + max(0.0, with_total - without_total) * 0.4
        if lethal_gain:
            value += 2.5
        return {
            "is_useful": True,
            "value": value,
            "with_total": with_total,
            "continuation_sequence": list(with_support["sequence"]),
            "attacker_ids": list(with_attack["attacker_ids"]),
            "target_id": with_attack["target_id"],
        }

    def _evaluate_air_boeenschub_reaction_plan(self, player: PlayerState, engine, card: CardInstance) -> dict:
        if engine.phase not in {PHASE_REACTION, PHASE_SPELL_TARGETING} or engine.reaction_context is None:
            return {"is_useful": False, "value": -4.0, "target_id": None}
        if engine.reaction_context.trigger not in {
            ReactionTrigger.AFTER_ATTACKERS_DECLARED,
            ReactionTrigger.AFTER_BLOCKERS_DECLARED,
            ReactionTrigger.BEFORE_FIRST_COMBAT,
        }:
            return {"is_useful": False, "value": -4.0, "target_id": None}
        if player.available_resources() < card.template.resource_cost:
            return {"is_useful": False, "value": -4.0, "target_id": None}

        enemy = engine.players[1 - player.player_id]
        blockers_available = bool(engine.available_blockers(enemy))
        if engine.reaction_context.trigger == ReactionTrigger.AFTER_ATTACKERS_DECLARED and blockers_available:
            return {"is_useful": False, "value": -1.2, "target_id": None}

        candidates = [creature for creature in player.battlefield if engine.has_valid_boeenschub_target(player) and creature.unit_id in engine.block_assignments]
        best_result = {"is_useful": False, "value": -4.0, "target_id": None}
        for creature in candidates:
            aw = engine.get_creature_attack_value(creature)
            blockers = [
                engine.get_unit_by_id(blocker_id)
                for blocker_id in engine.block_assignments.get(creature.unit_id, [])
                if engine.get_unit_by_id(blocker_id) is not None
            ]
            direct_damage_gain = 0
            lethal_gain = False
            score = -1.8
            if not blockers and creature.unit_id not in engine.blocked_attackers:
                if enemy.life <= aw:
                    continue
                direct_damage_gain = card.template.spell_amount
                score += direct_damage_gain * 1.5
                if enemy.life <= aw + card.template.spell_amount and enemy.life > aw:
                    lethal_gain = True
                    score += 8.0
                elif enemy.life <= (aw + card.template.spell_amount) * 2 and enemy.life > aw * 2:
                    windrausch = next(
                        (
                            hand_card
                            for hand_card in player.hand
                            if hand_card.instance_id != card.instance_id
                            and hand_card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE
                            and player.available_resources() >= card.template.resource_cost + hand_card.template.resource_cost
                        ),
                        None,
                    )
                    if windrausch is not None:
                        score += 3.2
                if creature.has_ability(Ability.FLYING) and not any(blocker.has_ability(Ability.FLYING) for blocker in enemy.battlefield):
                    score += 0.8
            else:
                kill_gain = sum(1 for blocker in blockers if aw < blocker.current_hp <= aw + card.template.spell_amount)
                score += kill_gain * 3.5
                score += max(0, len(blockers) - 1) * 1.4
                if blockers:
                    most_valuable = max(blockers, key=self._air_creature_board_value)
                    if aw < most_valuable.current_hp <= aw + card.template.spell_amount:
                        score += 2.5 + self._air_creature_board_value(most_valuable) * 0.25
                    if aw >= most_valuable.current_hp:
                        score -= 1.8
                    elif aw + card.template.spell_amount < max(blocker.current_hp for blocker in blockers):
                        score -= 1.2
                if creature.current_hp <= 1 and kill_gain > 0:
                    score += 1.2

            if direct_damage_gain <= 0 and not lethal_gain and score < 1.1:
                continue
            result = {
                "is_useful": True,
                "value": score,
                "target_id": creature.unit_id,
            }
            if result["value"] > best_result["value"]:
                best_result = result
        if not best_result["is_useful"] or best_result["value"] <= 1.1:
            return {"is_useful": False, "value": best_result["value"], "target_id": None}
        return best_result

    def _current_windrausch_attackers(self, player: PlayerState, engine) -> list[BattlefieldCreature]:
        context = getattr(engine, "reaction_context", None)
        if context is None or context.trigger not in {
            ReactionTrigger.AFTER_BLOCKERS_DECLARED,
            ReactionTrigger.BEFORE_FIRST_COMBAT,
        }:
            return []
        return [
            creature
            for creature in player.battlefield
            if creature.unit_id in engine.block_assignments and not engine.block_assignments.get(creature.unit_id)
        ]

    def _evaluate_air_windrausch_reaction_plan(self, player: PlayerState, engine, card: CardInstance) -> dict:
        if engine.phase not in {PHASE_REACTION, PHASE_SPELL_TARGETING} or engine.reaction_context is None:
            return {"is_useful": False, "value": -5.0, "damage": 0, "is_lethal": False}
        if engine.reaction_context.trigger not in {
            ReactionTrigger.AFTER_BLOCKERS_DECLARED,
            ReactionTrigger.BEFORE_FIRST_COMBAT,
        }:
            return {"is_useful": False, "value": -5.0, "damage": 0, "is_lethal": False}
        if player != engine.active_player:
            return {"is_useful": False, "value": -5.0, "damage": 0, "is_lethal": False}
        if player.available_resources() < card.template.resource_cost or player.total_resources() < card.template.recycle_cost:
            return {"is_useful": False, "value": -5.0, "damage": 0, "is_lethal": False}

        enemy = engine.players[1 - player.player_id]
        attackers = self._current_windrausch_attackers(player, engine)
        if not attackers:
            return {"is_useful": False, "value": -4.5, "damage": 0, "is_lethal": False}

        normal_damage = sum(engine.get_creature_attack_value(creature) for creature in attackers)
        if normal_damage <= 0:
            return {"is_useful": False, "value": -4.0, "damage": 0, "is_lethal": False}
        if normal_damage >= enemy.life:
            return {"is_useful": False, "value": -2.2, "damage": normal_damage, "is_lethal": True}

        total_damage = normal_damage * 2
        is_lethal = total_damage >= enemy.life
        remaining_total_resources = player.total_resources() - card.template.recycle_cost
        remaining_available_resources = max(0, player.available_resources() - card.template.resource_cost)

        score = normal_damage * 1.55 - 4.2
        score += max(0, len(attackers) - 1) * 1.1
        if is_lethal:
            score += 11.0
        if normal_damage <= 1:
            score -= 3.5
        if len(attackers) == 1 and normal_damage <= 2:
            score -= 1.5
        resource_penalties = {0: 5.8, 1: 3.4, 2: 1.5, 3: 0.3}
        score -= resource_penalties.get(remaining_total_resources, 0.0)
        if remaining_available_resources <= 0 and not is_lethal:
            score -= 0.8
        if enemy.life - total_damage <= 2 and not is_lethal:
            score += 1.2
        if player.life <= 5 and normal_damage >= 4:
            score += 1.4

        is_useful = is_lethal or score >= 2.4
        return {"is_useful": is_useful, "value": score, "damage": total_damage, "is_lethal": is_lethal}

    def _nachwehen_future_deaths_likely(self, engine) -> bool:
        if getattr(engine, "pending_dice_battle", None) is not None:
            return True
        combat_queue = list(getattr(engine, "combat_queue", []))
        current_attack_index = getattr(engine, "current_attack_index", 0)
        block_assignments = getattr(engine, "block_assignments", {})
        for attacker_id in combat_queue[current_attack_index:]:
            living_blockers = [
                blocker_id
                for blocker_id in block_assignments.get(attacker_id, [])
                if engine.get_unit_by_id(blocker_id) is not None
            ]
            if living_blockers:
                return True
        return False

    def _evaluate_air_nachwehen_plan(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
    ) -> dict:
        if total_resources < card.template.recycle_cost:
            return {"is_useful": False, "value": -5.0, "draw_count": 0, "wait_for_more": False}

        deaths = engine.creatures_died_this_turn
        if deaths <= 0:
            return {"is_useful": False, "value": -5.0, "draw_count": 0, "wait_for_more": False}

        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        live_cards = 0
        for hand_card in remaining_hand:
            if hand_card.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
                if deaths >= 2 and total_resources >= hand_card.template.recycle_cost:
                    live_cards += 1
                continue
            if self._air_card_has_live_use(
                player,
                engine,
                hand_card,
                remaining_hand,
                available_resources,
                total_resources,
            ):
                live_cards += 1
        draw_count = deaths * card.template.spell_amount
        remaining_total_resources = total_resources - card.template.recycle_cost
        score = draw_count * 1.65 - 3.8

        if deaths == 1:
            score -= 2.2
        elif deaths == 2:
            score += 0.6
        else:
            score += 2.2 + max(0, deaths - 3) * 0.8

        if len(remaining_hand) <= 0:
            score += 2.8
        elif len(remaining_hand) == 1:
            score += 1.8
        elif len(remaining_hand) == 2:
            score += 0.8
        elif len(remaining_hand) >= 5:
            score -= 1.2
        elif len(remaining_hand) >= 3:
            score -= 0.4

        if live_cards == 0:
            score += 1.5
        elif live_cards >= 3:
            score -= 1.4
        elif live_cards >= 5:
            score -= 2.1

        resource_penalties = {0: 5.4, 1: 3.2, 2: 1.4, 3: 0.2}
        score -= resource_penalties.get(remaining_total_resources, 0.0)

        future_deaths_likely = self._nachwehen_future_deaths_likely(engine)
        urgent_need = len(remaining_hand) <= 0 or (len(remaining_hand) <= 1 and live_cards == 0)
        if future_deaths_likely and deaths < 3 and not urgent_need:
            score -= 2.6

        if remaining_total_resources <= 0 and draw_count < 6:
            score -= 2.2
        if remaining_total_resources == 1 and draw_count <= 2:
            score -= 1.3

        is_useful = draw_count >= 6 or score >= 2.3
        wait_for_more = future_deaths_likely and not urgent_need and draw_count < 6
        if wait_for_more and not draw_count >= 6:
            is_useful = False
        return {
            "is_useful": is_useful,
            "value": score,
            "draw_count": draw_count,
            "wait_for_more": wait_for_more,
        }

    def _evaluate_air_windwechsel_plan(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> dict:
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost or not player.deck:
            return {"is_useful": False, "value": -4.0}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        without_cast = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        after_cast_known = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=next_available,
            total_resources=next_total,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        weak_current = sum(
            1
            for hand_card in remaining_hand
            if not self._air_card_has_live_use(
                player,
                engine,
                hand_card,
                remaining_hand,
                next_available,
                next_total,
            )
        )
        redundant_current = sum(1 for hand_card in remaining_hand if self._air_card_role_is_redundant(hand_card, remaining_hand))
        playable_now_current = sum(
            1
            for hand_card in remaining_hand
            if hand_card.template.card_type == CardType.CREATURE
            and max(0, hand_card.template.resource_cost - creature_discount) <= next_available
            and hand_card.template.recycle_cost <= next_total
        )
        remaining_templates = [deck_card.template for deck_card in player.deck]
        total_remaining = len(remaining_templates)
        cheap_playable_hits = 0
        broadly_useful_hits = 0
        creature_hits = 0
        weak_replace_hits = 0
        for template in remaining_templates:
            if template.card_type == CardType.CREATURE:
                creature_hits += 1
                reduced_cost = max(0, template.resource_cost - creature_discount)
                if reduced_cost <= next_available and template.recycle_cost <= next_total:
                    cheap_playable_hits += 1
            if self._air_template_is_generally_draw_worthy(
                player,
                engine,
                template,
                remaining_hand,
                available_resources=next_available,
                total_resources=next_total,
            ):
                broadly_useful_hits += 1
            if self._air_template_improves_weak_hand(
                player,
                engine,
                template,
                remaining_hand,
                available_resources=next_available,
                total_resources=next_total,
            ):
                weak_replace_hits += 1
        p_playable_now = cheap_playable_hits / total_remaining if total_remaining else 0.0
        p_useful = broadly_useful_hits / total_remaining if total_remaining else 0.0
        p_weak_replace = weak_replace_hits / total_remaining if total_remaining else 0.0
        p_creature_hit = creature_hits / total_remaining if total_remaining else 0.0
        expected_upgrade = 0.0
        expected_upgrade += weak_current * 0.95
        expected_upgrade += redundant_current * 0.5
        expected_upgrade += p_useful * 2.0
        expected_upgrade += p_weak_replace * max(1, weak_current) * 1.1
        if playable_now_current == 0:
            expected_upgrade += p_playable_now * 2.2
        else:
            expected_upgrade += p_playable_now * 0.8
        if not any(hand_card.template.card_type == CardType.CREATURE for hand_card in remaining_hand):
            expected_upgrade += p_creature_hit * 1.6
        if next_available == 0:
            expected_upgrade -= 1.2
            if weak_current >= 2:
                expected_upgrade += 0.8
        expected_total = after_cast_known["score"] + expected_upgrade - 1.35
        if without_cast["score"] >= after_cast_known["score"] + 2.0 and weak_current <= 1:
            return {"is_useful": False, "value": -3.0}
        if expected_total <= without_cast["score"] + 0.45:
            return {"is_useful": False, "value": -2.8 if weak_current <= 1 else -0.8}
        return {
            "is_useful": True,
            "value": 0.7 + max(0.0, expected_total - without_cast["score"]) * 0.35,
        }

    def _evaluate_air_sturmformation_plan(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> dict:
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost or len(player.deck) < 3:
            return {"is_useful": False, "value": -4.5}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        without_cast = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        after_cast_known = self._best_air_main_phase_plan(
            player,
            engine,
            [],
            available_resources=next_available,
            total_resources=next_total,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        duplicate_counts = self._template_counts(remaining_hand)
        protected_ids = self._air_current_plan_protected_ids(
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        discarded_keep_values = [
            max(
                0.0,
                self._air_resource_keep_value(
                    player,
                    engine,
                    hand_card,
                    hand=remaining_hand,
                    projected_available_resources=available_resources,
                    projected_total_resources=total_resources,
                    duplicate_count=duplicate_counts.get(hand_card.template.template_id, 1),
                    protected_ids=protected_ids,
                ),
            )
            for hand_card in remaining_hand
        ]
        discarded_value = sum(discarded_keep_values)
        weak_current = sum(
            1
            for hand_card in remaining_hand
            if not self._air_card_has_live_use(
                player,
                engine,
                hand_card,
                remaining_hand,
                next_available,
                next_total,
            )
        )
        redundant_current = sum(1 for hand_card in remaining_hand if self._air_card_role_is_redundant(hand_card, remaining_hand))
        remaining_templates = [deck_card.template for deck_card in player.deck]
        total_remaining = len(remaining_templates)
        cheap_playable_hits = 0
        broadly_useful_hits = 0
        creature_hits = 0
        weak_replace_hits = 0
        for template in remaining_templates:
            if template.card_type == CardType.CREATURE:
                creature_hits += 1
                reduced_cost = max(0, template.resource_cost - creature_discount)
                if reduced_cost <= next_available and template.recycle_cost <= next_total:
                    cheap_playable_hits += 1
            if self._air_template_is_generally_draw_worthy(
                player,
                engine,
                template,
                [],
                available_resources=next_available,
                total_resources=next_total,
            ):
                broadly_useful_hits += 1
            if self._air_template_improves_weak_hand(
                player,
                engine,
                template,
                remaining_hand,
                available_resources=next_available,
                total_resources=next_total,
            ):
                weak_replace_hits += 1
        p_playable_now = cheap_playable_hits / total_remaining if total_remaining else 0.0
        p_useful = broadly_useful_hits / total_remaining if total_remaining else 0.0
        p_weak_replace = weak_replace_hits / total_remaining if total_remaining else 0.0
        p_creature_hit = creature_hits / total_remaining if total_remaining else 0.0
        expected_upgrade = 0.0
        expected_upgrade += p_useful * 4.4
        expected_upgrade += p_playable_now * (2.8 if next_available > 0 else 0.9)
        expected_upgrade += p_weak_replace * max(1, weak_current) * 1.9
        expected_upgrade += redundant_current * 0.8
        if not any(hand_card.template.card_type == CardType.CREATURE for hand_card in remaining_hand):
            expected_upgrade += p_creature_hit * 1.8
        if len(remaining_hand) == 0:
            expected_upgrade += 2.1
        elif len(remaining_hand) == 1:
            expected_upgrade += 0.8
        if weak_current >= max(1, len(remaining_hand)):
            expected_upgrade += 0.9
        if next_available == 0:
            expected_upgrade -= 1.0
            if weak_current >= 2 or len(remaining_hand) <= 1:
                expected_upgrade += 0.5
        discard_penalty = discarded_value * 0.43 + max(0, len(remaining_hand) - 1) * 0.95
        if len(remaining_hand) >= 4:
            discard_penalty += 1.1
        expected_total = after_cast_known["score"] + expected_upgrade - discard_penalty - 1.2
        if not remaining_hand:
            expected_total += 0.75
        if without_cast["score"] >= expected_total - 0.35:
            return {"is_useful": False, "value": -3.1 if weak_current <= 1 else -0.9}
        if discarded_value >= 10.0 and weak_current <= 1:
            return {"is_useful": False, "value": -3.6}
        return {
            "is_useful": True,
            "value": 0.9 + max(0.0, expected_total - without_cast["score"]) * 0.38,
        }

    def _clone_air_shadow_player(self, player: PlayerState, battlefield: list[BattlefieldCreature]) -> PlayerState:
        shadow = PlayerState(player.player_id, player.name, player.is_human)
        shadow.summoner_key = player.summoner_key
        shadow.life = player.life
        shadow.battlefield = list(battlefield)
        shadow.creature_cost_reduction_this_turn = getattr(player, "creature_cost_reduction_this_turn", 0)
        return shadow

    def _evaluate_air_turbulenz_plan(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> dict:
        enemy = engine.players[1 - player.player_id]
        if total_resources < card.template.recycle_cost or len(player.battlefield) + len(enemy.battlefield) < 2:
            return {"is_useful": False, "value": -4.5, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_ids": []}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_total = total_resources - card.template.recycle_cost
        next_available = min(available_resources, next_total)
        without_support = self._best_air_main_phase_plan(
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        without_attack = self._estimate_best_air_attack_plan(player, enemy, remaining_hand, without_support["sequence"])
        without_total = without_support["score"] + without_attack["score"]
        all_targets = [(creature, player.player_id) for creature in player.battlefield] + [(creature, enemy.player_id) for creature in enemy.battlefield]
        best_result = {"with_total": -999.0, "target_ids": [], "attacker_ids": [], "continuation_sequence": [], "value": -4.5}
        for first_index in range(len(all_targets)):
            for second_index in range(first_index + 1, len(all_targets)):
                first, first_owner = all_targets[first_index]
                second, second_owner = all_targets[second_index]
                target_ids = [first.unit_id, second.unit_id]
                own_removed = [creature for creature, owner_id in ((first, first_owner), (second, second_owner)) if owner_id == player.player_id]
                enemy_removed = [creature for creature, owner_id in ((first, first_owner), (second, second_owner)) if owner_id == enemy.player_id]
                shadow_player_battlefield = [creature for creature in player.battlefield if creature.unit_id not in target_ids]
                shadow_enemy_battlefield = [creature for creature in enemy.battlefield if creature.unit_id not in target_ids]
                replay_hand = list(remaining_hand)
                for creature in own_removed:
                    replay_hand.append(CardInstance(-(100000 + creature.unit_id), engine.templates[creature.template_id]))
                shadow_player = self._clone_air_shadow_player(player, shadow_player_battlefield)
                shadow_enemy = self._clone_air_shadow_player(enemy, shadow_enemy_battlefield)
                with_support = self._best_air_main_phase_plan(
                    shadow_player,
                    engine,
                    replay_hand,
                    available_resources=next_available,
                    total_resources=next_total,
                    start_creature_discount=creature_discount,
                    start_own_creature_count=len(shadow_player_battlefield),
                    start_ready_attacker_count=len([creature for creature in shadow_player_battlefield if creature.is_ready()]),
                )
                with_attack = self._estimate_best_air_attack_plan(
                    shadow_player,
                    shadow_enemy,
                    replay_hand,
                    with_support["sequence"],
                )
                target_value = 0.0
                for creature in enemy_removed:
                    target_value += creature.aw * 1.2 + creature.current_hp * 1.0
                    target_value += creature.cost.total_value * 0.75
                    if creature.cost.recycle > 0:
                        target_value += 1.2 + creature.cost.recycle * 0.8
                    if creature.damage_taken > 0:
                        target_value += creature.damage_taken * 0.6
                    if creature.has_ability(Ability.FLYING):
                        target_value += 0.5
                for creature in own_removed:
                    own_penalty = creature.aw * 0.9 + creature.current_hp * 0.8 + creature.cost.total_value * 0.5
                    if creature.is_ready():
                        own_penalty += 1.8
                    if creature.current_hp <= 1:
                        own_penalty -= 3.6
                    if creature.template_id and engine.templates[creature.template_id].has_ability(Ability.HASTE):
                        own_penalty += 0.9
                    if engine.templates[creature.template_id].resource_cost <= available_resources and next_total >= engine.templates[creature.template_id].recycle_cost:
                        own_penalty -= 0.7
                    target_value -= own_penalty
                attack_gain = with_attack["score"] - without_attack["score"]
                direct_damage_gain = with_attack["direct_damage"] - without_attack["direct_damage"]
                lethal_gain = with_attack["is_lethal"] and not without_attack["is_lethal"]
                resource_penalty = 0.0
                if next_total <= 0:
                    resource_penalty = 8.0
                elif next_total == 1:
                    resource_penalty = 4.6
                elif next_total == 2:
                    resource_penalty = 3.0
                else:
                    resource_penalty = 0.8
                with_total = with_support["score"] + with_attack["score"] + target_value - resource_penalty - 1.1
                if lethal_gain:
                    with_total += 6.5
                elif direct_damage_gain > 0:
                    with_total += direct_damage_gain * 1.4
                if len(enemy_removed) == 2:
                    with_total += 0.9
                if len(enemy_removed) == 0:
                    with_total -= 4.0
                if next_total <= 1 and not lethal_gain and direct_damage_gain <= 0:
                    with_total -= 2.0
                result = {
                    "with_total": with_total,
                    "target_ids": target_ids,
                    "attacker_ids": list(with_attack["attacker_ids"]),
                    "continuation_sequence": list(with_support["sequence"]),
                    "value": 0.7 + max(0.0, with_total - without_total) * 0.34,
                }
                if result["with_total"] > best_result["with_total"]:
                    best_result = result
        if not best_result["target_ids"]:
            return {"is_useful": False, "value": -4.5, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_ids": []}
        if best_result["with_total"] <= without_total + 1.0:
            return {"is_useful": False, "value": -3.3, "with_total": best_result["with_total"], "continuation_sequence": [], "attacker_ids": [], "target_ids": []}
        return {
            "is_useful": True,
            "value": best_result["value"],
            "with_total": best_result["with_total"],
            "continuation_sequence": best_result["continuation_sequence"],
            "attacker_ids": best_result["attacker_ids"],
            "target_ids": best_result["target_ids"],
        }

    def _air_creature_board_value(self, creature: BattlefieldCreature) -> float:
        value = creature.aw * 1.7 + creature.current_hp * 1.5 + creature.cost.total_value * 0.75
        if creature.has_ability(Ability.HASTE):
            value += 1.2
        if creature.has_ability(Ability.FLYING):
            value += 1.0
        if creature.cost.recycle > 0:
            value += 0.8 + creature.cost.recycle * 0.55
        if creature.all_attackers_die_bonus > 0:
            value += 2.2
        if getattr(creature, "draw_on_attack", 0) > 0:
            value += creature.draw_on_attack * 1.3
        if getattr(creature, "draw_on_death", 0) > 0:
            value += creature.draw_on_death * 1.0
        if getattr(creature, "draw_on_player_damage", 0) > 0:
            value += creature.draw_on_player_damage * 1.4
        if getattr(creature, "return_other_own_haste_on_combat_death", False):
            value += 2.1
        if getattr(creature, "own_flying_attack_aura", 0) > 0:
            value += creature.own_flying_attack_aura * 2.4
        if creature.return_to_deck_end_of_turn:
            value -= 0.9
        return value

    def _evaluate_air_ausweichen_plan(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
    ) -> dict:
        if available_resources < card.template.resource_cost or not player.battlefield:
            return {"is_useful": False, "value": -4.0, "target_id": None, "recast_target": False}
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        battle = engine.pending_dice_battle
        best_value = -999.0
        best_target_id: int | None = None
        best_recast = False
        for creature in player.battlefield:
            value = -1.6
            threatened = False
            board_value = self._air_creature_board_value(creature)
            damage_taken = creature.damage_taken
            if battle is not None and creature.unit_id in {battle.attacker_id, battle.blocker_id}:
                is_attacker = creature.unit_id == battle.attacker_id
                opposing = engine.get_unit_by_id(battle.blocker_id if is_attacker else battle.attacker_id)
                own_dice = battle.attacker_dice if is_attacker else battle.blocker_dice
                enemy_dice = battle.blocker_dice if is_attacker else battle.attacker_dice
                own_unused = sum(1 for die in own_dice if not die.used)
                enemy_unused = sum(1 for die in enemy_dice if not die.used)
                opposing_aw = getattr(opposing, "aw", 0)
                threatened = creature.current_hp <= max(1, opposing_aw) or (damage_taken > 0 and enemy_unused >= own_unused)
                save_bonus = board_value * (1.0 if threatened else 0.24 if damage_taken > 0 else 0.1)
                abandon_penalty = creature.aw * 0.6 + own_unused * 0.55
                if not threatened and own_unused > enemy_unused and creature.current_hp > opposing_aw:
                    abandon_penalty += 1.8
                if is_attacker:
                    abandon_penalty += 0.5
                value += save_bonus - abandon_penalty
            else:
                if damage_taken <= 0:
                    value -= 1.7
                else:
                    value += min(4.0, damage_taken * 1.55)
                    value += board_value * (0.16 if damage_taken == 1 else 0.24)
                    threatened = damage_taken >= max(1, creature.vw - 1)
                if creature.return_to_deck_end_of_turn:
                    value -= 2.1

            can_recast = next_available >= creature.cost.resources and next_total >= creature.cost.recycle
            if can_recast:
                replay_value = 0.35 * self._air_creature_play_value(CardInstance(-1, engine.templates[creature.template_id]))
                if creature.has_ability(Ability.HASTE):
                    replay_value += 1.1
                else:
                    replay_value -= 0.45
                replay_value -= creature.cost.recycle * 0.35
                value += replay_value
            else:
                value -= creature.cost.recycle * 0.25
                if not threatened and damage_taken <= 0:
                    value -= 0.9

            if creature.return_to_deck_end_of_turn and not can_recast and damage_taken <= 0:
                value -= 1.6
            if damage_taken <= 0 and not threatened and not can_recast:
                value -= 0.8
            if value > best_value:
                best_value = value
                best_target_id = creature.unit_id
                best_recast = can_recast
        threshold = 1.25 if battle is not None else 1.8
        return {
            "is_useful": best_target_id is not None and best_value > threshold,
            "value": best_value,
            "target_id": best_target_id,
            "recast_target": best_recast,
        }

