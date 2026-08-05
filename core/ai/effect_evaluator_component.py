from __future__ import annotations

from core.models import Ability, BattlefieldCreature, CardInstance, CardType, PHASE_MAIN_1, PHASE_MAIN_2, PHASE_REACTION, PHASE_SPELL_TARGETING, PlayerState, ReactionTrigger, SpellEffect


class EffectEvaluatorComponent:
    def card_has_live_use(self, ai, player, engine, card, hand, projected_available_resources: int, projected_total_resources: int) -> bool:
        return ai.turn_planner.air_card_has_live_use(
            ai,
            player,
            engine,
            card,
            hand,
            projected_available_resources,
            projected_total_resources,
        )

    def evaluate_cost_reduction_support_plan(
        self,
        ai,
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
        strategy = ai._evaluate_air_strategy(
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        weights = strategy.weights
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": []}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        without_support = ai.turn_planner.best_air_main_phase_plan(
            ai,
            player,
            engine,
            remaining_hand,
            available_resources=next_available,
            total_resources=next_total,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        with_support = ai.turn_planner.best_air_main_phase_plan(
            ai,
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
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": []}
        reaction_bonus = ai._air_reaction_hold_advantage(player, engine, remaining_hand, with_support, without_support)
        improved = (
            with_support["creatures_played"] > without_support["creatures_played"]
            or with_support["cards_played"] > without_support["cards_played"]
            or with_support["creature_value"] > without_support["creature_value"] + 0.4
            or reaction_bonus > 0.0
        )
        if not improved:
            return {"is_useful": False, "value": -3.2, "with_total": without_support["score"], "continuation_sequence": [], "attacker_ids": []}
        enemy = engine.players[1 - player.player_id]
        with_attack = ai._estimate_best_air_attack_plan(player, enemy, remaining_hand, with_support["sequence"], engine=engine)
        without_attack = ai._estimate_best_air_attack_plan(player, enemy, remaining_hand, without_support["sequence"], engine=engine)
        with_total = with_support["score"] + with_attack["score"] - 0.4
        without_total = without_support["score"] + without_attack["score"]
        if strategy.mode in {"LETHAL", "PRESSURE", "BUILD_SWARM"}:
            with_total += max(0, len(with_attack["attacker_ids"]) - len(without_attack["attacker_ids"])) * 0.45 * weights.board_width
        if len(with_attack["attacker_ids"]) >= 3 and len(without_attack["attacker_ids"]) < 3:
            with_total += 0.8 * weights.third_attacker
        value = 0.6 + max(0.0, with_total - without_total) * 0.3 + reaction_bonus
        return {
            "is_useful": True,
            "value": value,
            "with_total": with_total,
            "continuation_sequence": list(with_support["sequence"]),
            "attacker_ids": list(with_attack["attacker_ids"]),
        }

    def evaluate_attack_bonus_support_plan(
        self,
        ai,
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
        strategy = ai._evaluate_air_strategy(
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        legal_target_ids = {creature.unit_id for creature in player.battlefield if creature.current_hp > 0}
        if not legal_target_ids:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        without_support = ai.turn_planner.best_air_main_phase_plan(
            ai,
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        with_support = ai.turn_planner.best_air_main_phase_plan(
            ai,
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
        without_attack = ai._estimate_best_air_attack_plan(player, enemy, remaining_hand, without_support["sequence"], engine=engine)
        with_attack = ai._estimate_best_air_attack_plan(
            player,
            enemy,
            remaining_hand,
            with_support["sequence"],
            attack_bonus_amount=card.template.spell_amount,
            engine=engine,
        )
        if with_attack["target_id"] is None or with_attack["target_id"] not in legal_target_ids or not with_attack["attacker_ids"]:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        without_total = without_support["score"] + without_attack["score"]
        with_total = with_support["score"] + with_attack["score"] - 1.4
        direct_damage_gain = with_attack["direct_damage"] - without_attack["direct_damage"]
        enemy_kill_gain = with_attack["enemy_kills"] - without_attack["enemy_kills"]
        own_loss_improvement = without_attack["own_losses"] - with_attack["own_losses"]
        lethal_gain = with_attack["is_lethal"] and not without_attack["is_lethal"]
        if without_attack["is_lethal"] and not lethal_gain and enemy_kill_gain <= 0 and own_loss_improvement <= 0:
            return {"is_useful": False, "value": -3.4, "with_total": with_total, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        improved_attack = lethal_gain or direct_damage_gain > 0 or enemy_kill_gain > 0 or own_loss_improvement > 0
        if not improved_attack or with_total <= without_total + 0.65:
            return {"is_useful": False, "value": -3.4, "with_total": with_total, "continuation_sequence": [], "attacker_ids": [], "target_id": None}
        value = 0.7 + max(0.0, with_total - without_total) * 0.4
        if lethal_gain:
            value += 2.5 * strategy.weights.lethal
        elif strategy.mode == "PRESSURE":
            value += 0.35 * strategy.weights.player_damage
        return {
            "is_useful": True,
            "value": value,
            "with_total": with_total,
            "continuation_sequence": list(with_support["sequence"]),
            "attacker_ids": list(with_attack["attacker_ids"]),
            "target_id": with_attack["target_id"],
        }

    def evaluate_windruf_plan(
        self,
        ai,
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
        strategy = ai._evaluate_air_strategy(
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_ids": []}
        valid_targets = [discard_card for discard_card in player.discard_pile if discard_card.template.card_type == CardType.CREATURE]
        if len(valid_targets) < card.template.spell_amount:
            return {"is_useful": False, "value": -4.0, "with_total": -999.0, "continuation_sequence": [], "attacker_ids": [], "target_ids": []}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        next_available = available_resources - card.template.resource_cost
        next_total = total_resources - card.template.recycle_cost
        without_support = ai.turn_planner.best_air_main_phase_plan(
            ai,
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        enemy = engine.players[1 - player.player_id]
        without_attack = ai._estimate_best_air_attack_plan(player, enemy, remaining_hand, without_support["sequence"], engine=engine)
        without_total = without_support["score"] + without_attack["score"]
        scored_targets = sorted(
            valid_targets,
            key=lambda discard_card: ai._score_air_graveyard_creature_target(
                player,
                engine,
                discard_card,
                available_resources=next_available,
                total_resources=next_total,
                creature_discount=creature_discount,
            ),
            reverse=True,
        )
        selected = scored_targets[: card.template.spell_amount]
        selected_score = sum(
            ai._score_air_graveyard_creature_target(
                player,
                engine,
                discard_card,
                available_resources=next_available,
                total_resources=next_total,
                creature_discount=creature_discount,
            )
            for discard_card in selected
        )
        augmented_hand = remaining_hand + selected
        with_support = ai.turn_planner.best_air_main_phase_plan(
            ai,
            player,
            engine,
            augmented_hand,
            available_resources=next_available,
            total_resources=next_total,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        with_attack = ai._estimate_best_air_attack_plan(player, enemy, augmented_hand, with_support["sequence"], engine=engine)
        with_total = with_support["score"] + with_attack["score"] + selected_score * (0.08 + 0.04 * strategy.weights.graveyard_value) - 0.8
        threshold = (0.5 if card.template.spell_amount == 1 else 0.9) / max(0.75, strategy.weights.graveyard_value)
        if with_total <= without_total + threshold:
            return {"is_useful": False, "value": with_total - without_total, "with_total": with_total, "continuation_sequence": [], "attacker_ids": [], "target_ids": []}
        return {
            "is_useful": True,
            "value": 0.9 + max(0.0, with_total - without_total) * 0.35,
            "with_total": with_total,
            "continuation_sequence": list(with_support["sequence"]),
            "attacker_ids": list(with_attack["attacker_ids"]),
            "target_ids": [discard_card.instance_id for discard_card in selected],
        }

    def evaluate_sturmruf_plan(self, ai, player, engine, card, **kwargs) -> dict:
        return self.evaluate_windruf_plan(ai, player, engine, card, **kwargs)

    def evaluate_himmelswende_plan(self, ai, player, engine, card, **kwargs) -> dict:
        return self.evaluate_hand_reset_plan(ai, player, engine, card, **kwargs)

    def evaluate_orkanwende_plan(self, ai, player, engine, card, **kwargs) -> dict:
        return self.evaluate_hand_reset_plan(ai, player, engine, card, **kwargs)

    def evaluate_bounce_plan(
        self,
        ai,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
    ) -> dict:
        strategy = ai._evaluate_air_strategy(player, engine, hand=hand, available_resources=available_resources, total_resources=total_resources)
        if available_resources < card.template.resource_cost or total_resources < card.template.recycle_cost:
            return {"is_useful": False, "value": -4.0, "target_ids": [], "recast_target": False}
        enemy = engine.players[1 - player.player_id]
        all_targets = list(player.battlefield) + list(enemy.battlefield)
        if len(all_targets) < card.template.spell_amount:
            return {"is_useful": False, "value": -4.0, "target_ids": [], "recast_target": False}
        scored = sorted(
            ((ai._score_air_bounce_target(player, engine, creature), creature) for creature in all_targets),
            key=lambda item: item[0],
            reverse=True,
        )
        selected = [creature for score, creature in scored[: card.template.spell_amount]]
        selected_scores = [score for score, _creature in scored[: card.template.spell_amount]]
        if len(selected) < card.template.spell_amount:
            return {"is_useful": False, "value": -4.0, "target_ids": [], "recast_target": False}
        total_value = sum(selected_scores) * strategy.weights.bounce_tempo - (0.9 if card.template.spell_amount == 1 else 1.8)
        if strategy.mode == "STABILIZE":
            enemy_targets = sum(1 for creature in selected if engine.get_unit_owner(creature.unit_id) == enemy)
            total_value += enemy_targets * 1.2 * strategy.weights.blocker_value
        if strategy.mode == "LETHAL":
            enemy_targets = sum(1 for creature in selected if engine.get_unit_owner(creature.unit_id) == enemy)
            total_value += enemy_targets * 0.8 * strategy.weights.player_damage
        if card.template.spell_amount == 2 and any(engine.get_unit_owner(creature.unit_id) == player for creature in selected) and total_value < 3.5:
            return {"is_useful": False, "value": total_value, "target_ids": [], "recast_target": False}
        if total_value <= (1.2 if card.template.spell_amount == 1 else 2.4):
            return {"is_useful": False, "value": total_value, "target_ids": [], "recast_target": False}
        own_target = next((creature for creature in selected if engine.get_unit_owner(creature.unit_id) == player), None)
        return {
            "is_useful": True,
            "value": total_value,
            "target_ids": [creature.unit_id for creature in selected],
            "recast_target": own_target is not None and own_target.cost.resources <= max(0, available_resources - card.template.resource_cost),
        }

    def evaluate_verwehung_plan(self, ai, player, engine, card, *, hand, available_resources: int, total_resources: int) -> dict:
        comparison = self.evaluate_bounce_plan(
            ai,
            player,
            engine,
            card,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        target_id = comparison["target_ids"][0] if comparison["target_ids"] else None
        return {"is_useful": comparison["is_useful"], "value": comparison["value"], "target_id": target_id, "recast_target": comparison.get("recast_target", False)}

    def evaluate_hand_reset_plan(
        self,
        ai,
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
        strategy = ai._evaluate_air_strategy(player, engine, hand=hand, available_resources=available_resources, total_resources=total_resources)
        if total_resources < card.template.recycle_cost or len(player.deck) < card.template.spell_draw_count:
            return {"is_useful": False, "value": -5.0, "draw_count": 0, "wait_for_more": False, "with_total": -999.0}
        remaining_hand = [hand_card for hand_card in hand if hand_card.instance_id != card.instance_id]
        without_plan = ai.turn_planner.best_air_main_phase_plan(
            ai,
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
            start_creature_discount=creature_discount,
            start_own_creature_count=own_creature_count,
            start_ready_attacker_count=ready_attacker_count,
        )
        next_total = total_resources - card.template.recycle_cost
        next_available = min(available_resources, next_total)
        keep_values = [
            max(
                0.0,
                ai.turn_planner.air_resource_keep_value(
                    ai,
                    player,
                    engine,
                    hand_card,
                    hand=remaining_hand,
                    projected_available_resources=available_resources,
                    projected_total_resources=total_resources,
                    duplicate_count=sum(1 for existing in remaining_hand if existing.template.template_id == hand_card.template.template_id),
                    protected_ids=set(),
                ),
            )
            for hand_card in remaining_hand
        ]
        discarded_value = sum(keep_values)
        average_draw_value = 1.45
        if len(remaining_hand) <= 1:
            average_draw_value += 0.55
        if engine.phase == PHASE_MAIN_2:
            average_draw_value += 0.35
        expected_draw_value = card.template.spell_draw_count * average_draw_value
        resource_penalty = {0: 4.8, 1: 2.7, 2: 1.3}.get(next_total, 0.2)
        immediate_use_bonus = 0.0
        if engine.phase == PHASE_MAIN_2 and next_available > 0:
            immediate_use_bonus += 0.8
        elif engine.phase == PHASE_MAIN_1:
            immediate_use_bonus -= 0.4
        weak_hand_bonus = 0.0
        if len(remaining_hand) == 0:
            weak_hand_bonus += 2.6
        elif len(remaining_hand) == 1:
            weak_hand_bonus += 1.4
        elif len(remaining_hand) >= 4:
            weak_hand_bonus -= 1.5
        if discarded_value >= 10.0:
            weak_hand_bonus -= 2.4
        with_total = without_plan["score"] + expected_draw_value * strategy.weights.draw_value + immediate_use_bonus + weak_hand_bonus - discarded_value * 0.42 - resource_penalty * strategy.weights.recycle_penalty
        threshold = 0.6 if card.template.spell_draw_count == 3 else 1.2
        if strategy.mode == "RELOAD":
            threshold *= 0.7
        return {"is_useful": with_total > without_plan["score"] + threshold, "value": with_total - without_plan["score"], "draw_count": card.template.spell_draw_count, "wait_for_more": engine.phase == PHASE_MAIN_1 and len(remaining_hand) > 1, "with_total": with_total}

    def evaluate_global_attack_bonus_reaction_plan(self, ai, player: PlayerState, engine, card: CardInstance) -> dict:
        strategy = ai._evaluate_air_strategy(player, engine)
        if engine.phase not in {PHASE_REACTION, PHASE_SPELL_TARGETING} or engine.reaction_context is None:
            return {"is_useful": False, "value": -4.0, "damage_gain": 0, "is_lethal": False}
        if engine.reaction_context.trigger not in {ReactionTrigger.AFTER_ATTACKERS_DECLARED, ReactionTrigger.AFTER_BLOCKERS_DECLARED, ReactionTrigger.BEFORE_FIRST_COMBAT}:
            return {"is_useful": False, "value": -4.0, "damage_gain": 0, "is_lethal": False}
        attackers = engine.get_current_attacker_creatures(player, engine.reaction_context)
        if not attackers or player.available_resources() < card.template.resource_cost:
            return {"is_useful": False, "value": -4.0, "damage_gain": 0, "is_lethal": False}
        enemy = engine.players[1 - player.player_id]
        if engine.reaction_context.trigger == ReactionTrigger.AFTER_ATTACKERS_DECLARED and engine.available_blockers(enemy):
            return {"is_useful": False, "value": -1.1, "damage_gain": 0, "is_lethal": False}
        direct_gain = 0
        kill_gain = 0.0
        for attacker in attackers:
            blockers = [engine.get_unit_by_id(blocker_id) for blocker_id in engine.block_assignments.get(attacker.unit_id, []) if engine.get_unit_by_id(blocker_id) is not None]
            current_aw = engine.get_creature_attack_value(attacker)
            boosted_aw = current_aw + card.template.spell_amount
            if not blockers and attacker.unit_id not in engine.blocked_attackers:
                direct_gain += card.template.spell_amount
            for blocker in blockers:
                if current_aw < blocker.current_hp <= boosted_aw:
                    kill_gain += ai._air_creature_board_value(blocker) * 0.45 + 1.2
        base_damage = sum(engine.get_creature_attack_value(attacker) for attacker in attackers if not engine.block_assignments.get(attacker.unit_id))
        boosted_damage = base_damage + direct_gain
        is_lethal = boosted_damage >= enemy.life and base_damage < enemy.life
        score = direct_gain * (1.0 + 0.3 * strategy.weights.player_damage) + kill_gain - card.template.resource_cost * 0.7
        if len(attackers) >= 3:
            score += 1.2 * strategy.weights.third_attacker
        if is_lethal:
            score += 8.0 * strategy.weights.lethal
        if card.template.spell_amount >= 2:
            plus_one = self.evaluate_global_attack_bonus_reaction_plan(
                ai,
                player,
                engine,
                CardInstance(-999, type("TempTemplate", (), {"spell_amount": 1, "resource_cost": 1})()),
            )
            if plus_one["is_lethal"] == is_lethal and plus_one["damage_gain"] >= direct_gain and plus_one["value"] >= score - 1.0:
                score -= 2.1
        return {"is_useful": is_lethal or score >= (1.8 if card.template.spell_amount == 1 else 2.8), "value": score, "damage_gain": direct_gain, "is_lethal": is_lethal}

    def evaluate_jagdwind_reaction_plan(self, ai, player: PlayerState, engine, card: CardInstance) -> dict:
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
        candidates = [creature for creature in player.battlefield if engine.has_valid_jagdwind_target(player) and creature.unit_id in engine.block_assignments]
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
                    sturmjagd = next(
                        (
                            hand_card
                            for hand_card in player.hand
                            if hand_card.instance_id != card.instance_id
                            and hand_card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE
                            and player.available_resources() >= card.template.resource_cost + hand_card.template.resource_cost
                        ),
                        None,
                    )
                    if sturmjagd is not None:
                        score += 3.2
                if creature.has_ability(Ability.FLYING) and not any(blocker.has_ability(Ability.FLYING) for blocker in enemy.battlefield):
                    score += 0.8
            else:
                kill_gain = sum(1 for blocker in blockers if aw < blocker.current_hp <= aw + card.template.spell_amount)
                score += kill_gain * 3.5
                score += max(0, len(blockers) - 1) * 1.4
                if blockers:
                    most_valuable = max(blockers, key=ai._air_creature_board_value)
                    if aw < most_valuable.current_hp <= aw + card.template.spell_amount:
                        score += 2.5 + ai._air_creature_board_value(most_valuable) * 0.25
                    if aw >= most_valuable.current_hp:
                        score -= 1.8
                    elif aw + card.template.spell_amount < max(blocker.current_hp for blocker in blockers):
                        score -= 1.2
                if creature.current_hp <= 1 and kill_gain > 0:
                    score += 1.2
            if direct_damage_gain <= 0 and not lethal_gain and score < 1.1:
                continue
            result = {"is_useful": True, "value": score, "target_id": creature.unit_id}
            if result["value"] > best_result["value"]:
                best_result = result
        if not best_result["is_useful"] or best_result["value"] <= 1.1:
            return {"is_useful": False, "value": best_result["value"], "target_id": None}
        return best_result

    def evaluate_sturmjagd_reaction_plan(self, ai, player: PlayerState, engine, card: CardInstance) -> dict:
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
        attackers = ai._current_sturmjagd_attackers(player, engine)
        if not attackers:
            return {"is_useful": False, "value": -4.5, "damage": 0, "is_lethal": False}
        enemy = engine.players[1 - player.player_id]
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
