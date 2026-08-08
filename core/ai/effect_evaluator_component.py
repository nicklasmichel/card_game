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
        all_targets = [
            creature
            for creature in [*player.battlefield, *enemy.battlefield]
            if engine.can_target_creature_with_explicit_spell(creature)
        ]
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

    def evaluate_global_attack_bonus_reaction_plan(self, ai, player: PlayerState, engine, card: CardInstance, *, selected_mode: str | None = None) -> dict:
        strategy = ai._evaluate_air_strategy(player, engine)
        if engine.phase not in {PHASE_REACTION, PHASE_SPELL_TARGETING} or engine.reaction_context is None:
            return {"is_useful": False, "value": -4.0, "damage_gain": 0, "is_lethal": False}
        if engine.reaction_context.trigger != ReactionTrigger.COMBAT_START:
            return {"is_useful": False, "value": -4.0, "damage_gain": 0, "is_lethal": False}
        if player != engine.active_player:
            return {"is_useful": False, "value": -4.0, "damage_gain": 0, "is_lethal": False}
        attackers = engine.get_current_attacker_creatures(player, engine.reaction_context)
        if not attackers or player.available_resources() < card.template.resource_cost:
            return {"is_useful": False, "value": -4.0, "damage_gain": 0, "is_lethal": False}
        if getattr(card.template, "template_id", None) in {"air_spell_jagdwind", "air_spell_sturmjagd"}:
            if selected_mode is None:
                variants = [
                    self.evaluate_global_attack_bonus_reaction_plan(ai, player, engine, card, selected_mode="attack"),
                    self.evaluate_global_attack_bonus_reaction_plan(ai, player, engine, card, selected_mode="damage"),
                ]
                return max(
                    variants,
                    key=lambda result: (
                        1 if result["is_useful"] else 0,
                        1 if result["is_lethal"] else 0,
                        result["value"],
                        result["damage_gain"],
                    ),
                )
            combat_aw_bonus = card.template.combat_aw_bonus if selected_mode == "attack" else 0
            combat_sw_bonus = card.template.combat_sw_bonus if selected_mode == "damage" else 0
        else:
            combat_aw_bonus = card.template.combat_aw_bonus
            combat_sw_bonus = card.template.combat_sw_bonus
        enemy = engine.players[1 - player.player_id]
        direct_gain = 0
        kill_gain = 0.0
        for attacker in attackers:
            blocker_id = engine.block_assignments.get(attacker.unit_id)
            blockers = [engine.get_unit_by_id(blocker_id)] if blocker_id is not None and engine.get_unit_by_id(blocker_id) is not None else []
            current_aw = engine.get_creature_attack_value(attacker)
            boosted_aw = current_aw + combat_aw_bonus
            current_sw = engine.get_creature_damage_value(attacker)
            boosted_sw = current_sw + combat_sw_bonus
            if not blockers and attacker.unit_id not in engine.blocked_attackers:
                direct_gain += combat_sw_bonus
            for blocker in blockers:
                current_attack_sum = current_aw * 3.5
                boosted_attack_sum = boosted_aw * 3.5
                defense_sum = engine.get_creature_defense_value(blocker) * 3.5
                if current_attack_sum <= defense_sum < boosted_attack_sum:
                    kill_gain += ai._air_creature_board_value(blocker) * 0.45 + 1.2
                if current_sw < blocker.current_hp <= boosted_sw:
                    kill_gain += ai._air_creature_board_value(blocker) * 0.75 + 1.5
                if attacker.has_ability(Ability.TRAMPLE):
                    current_overflow = max(0, current_sw - blocker.current_hp)
                    boosted_overflow = max(0, boosted_sw - blocker.current_hp)
                    direct_gain += max(0, boosted_overflow - current_overflow) * 0.6
        base_damage = sum(engine.get_creature_damage_value(attacker) for attacker in attackers if not engine.block_assignments.get(attacker.unit_id))
        boosted_damage = base_damage + direct_gain
        is_lethal = boosted_damage >= enemy.life and base_damage < enemy.life
        score = direct_gain * (1.0 + 0.3 * strategy.weights.player_damage) + kill_gain - card.template.resource_cost * 0.7
        if len(attackers) >= 3:
            score += 1.2 * strategy.weights.third_attacker
        if is_lethal:
            score += 8.0 * strategy.weights.lethal
        if combat_sw_bonus >= 2:
            plus_one = self.evaluate_global_attack_bonus_reaction_plan(
                ai,
                player,
                engine,
                CardInstance(-999, type("TempTemplate", (), {"combat_aw_bonus": 0, "combat_sw_bonus": 1, "resource_cost": 1})()),
            )
            if plus_one["is_useful"] and plus_one["is_lethal"] == is_lethal and kill_gain <= 0:
                score -= 2.4
            elif plus_one["is_lethal"] == is_lethal and plus_one["damage_gain"] >= direct_gain and plus_one["value"] >= score - 1.0:
                score -= 2.1
        threshold = max(1.8, card.template.resource_cost * 0.9 + getattr(card.template, "recycle_cost", 0) * 0.75)
        if combat_aw_bonus > 0 and combat_sw_bonus == 0:
            threshold += 0.2
        return {
            "is_useful": is_lethal or score >= threshold,
            "value": score,
            "damage_gain": direct_gain,
            "is_lethal": is_lethal,
            "selected_mode": selected_mode,
            "combat_aw_bonus": combat_aw_bonus,
            "combat_sw_bonus": combat_sw_bonus,
        }

    def evaluate_jagdwind_reaction_plan(self, ai, player: PlayerState, engine, card: CardInstance) -> dict:
        comparison = self.evaluate_global_attack_bonus_reaction_plan(ai, player, engine, card)
        return {
            "is_useful": comparison["is_useful"],
            "value": comparison["value"],
            "target_id": None,
            "selected_mode": comparison.get("selected_mode"),
        }

    def evaluate_sturmjagd_reaction_plan(self, ai, player: PlayerState, engine, card: CardInstance) -> dict:
        comparison = self.evaluate_global_attack_bonus_reaction_plan(ai, player, engine, card)
        attackers = engine.get_current_attacker_creatures(player, engine.reaction_context)
        boosted_damage = sum(
            engine.get_creature_damage_value(creature) + comparison.get("combat_sw_bonus", card.template.combat_sw_bonus)
            for creature in attackers
            if not engine.block_assignments.get(creature.unit_id)
        )
        return {
            "is_useful": comparison["is_useful"],
            "value": comparison["value"],
            "damage": boosted_damage,
            "is_lethal": comparison["is_lethal"],
            "selected_mode": comparison.get("selected_mode"),
        }
