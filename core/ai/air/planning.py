from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardType, DieResult, PHASE_REACTION, PHASE_SPELL_TARGETING, PlayerState, ReactionTrigger, SpellEffect, SpellTargetRef

class AirPlanningMixin:
    def choose_resource_cards_to_play(self, player: PlayerState, engine) -> List[CardInstance]:
        if player.resources_played_this_turn >= 2 or not player.hand:
            return []
        if getattr(player, "summoner_key", "") == "air":
            return self._choose_air_resource_cards_to_play(player, engine)
        remaining_slots = max(0, 2 - player.resources_played_this_turn)
        chosen: list[CardInstance] = []
        hand_snapshot = list(player.hand)
        shadow_player = PlayerState(player.player_id, player.name, player.is_human)
        shadow_player.resources_played_this_turn = player.resources_played_this_turn
        shadow_player.hand = hand_snapshot
        shadow_player.resources = list(player.resources)
        for _ in range(min(remaining_slots, len(hand_snapshot))):
            next_card = self.choose_resource_card(shadow_player)
            if next_card is None:
                break
            chosen.append(next_card)
            shadow_player.hand = [card for card in shadow_player.hand if card.instance_id != next_card.instance_id]
            shadow_player.resources_played_this_turn += 1
        return chosen

    def _choose_air_resource_cards_to_play(self, player: PlayerState, engine) -> List[CardInstance]:
        max_new_resources = min(2 - player.resources_played_this_turn, len(player.hand))
        if max_new_resources <= 0:
            return []
        current_total_resources = player.total_resources()
        if len(player.hand) <= 1:
            return []
        if len(player.hand) == 2:
            max_new_resources = min(max_new_resources, 1)

        best_option: tuple[float, int, int, list[CardInstance]] | None = None
        for resource_count in range(max_new_resources + 1):
            if len(player.hand) - resource_count <= 0:
                continue
            resource_cards = self._select_air_resource_cards(player, engine, resource_count)
            score = self._score_air_resource_count_option(player, engine, resource_cards)
            option = (score, -resource_count, len(player.hand) - resource_count, resource_cards)
            if best_option is None or option > best_option:
                best_option = option
        return best_option[3] if best_option is not None else []

    def _select_air_resource_cards(self, player: PlayerState, engine, resource_count: int) -> list[CardInstance]:
        if resource_count <= 0:
            return []
        projected_available_resources = player.available_resources() + resource_count
        projected_total_resources = player.total_resources() + resource_count
        chosen: list[CardInstance] = []
        remaining_hand = list(player.hand)
        for _ in range(min(resource_count, len(remaining_hand))):
            protected_ids = self._air_current_plan_protected_ids(
                player,
                engine,
                remaining_hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
            )
            scored_cards: list[tuple[tuple[float, int, int, int, int], CardInstance]] = []
            duplicate_counts = self._template_counts(remaining_hand)
            creatures_in_hand = [card for card in remaining_hand if card.template.card_type == CardType.CREATURE]
            interactive_templates = {
                SpellEffect.RETURN_TWO_CREATURES_TO_HAND,
                SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND,
                SpellEffect.REROLL_OPEN_DIE,
                SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT,
                SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE,
                SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN,
            }
            interactions_in_hand = [
                card for card in remaining_hand
                if card.template.spell_effect in interactive_templates
            ]
            for card in remaining_hand:
                keep_value = self._air_resource_keep_value(
                    player,
                    engine,
                    card,
                    hand=remaining_hand,
                    projected_available_resources=projected_available_resources,
                    projected_total_resources=projected_total_resources,
                    duplicate_count=duplicate_counts.get(card.template.template_id, 1),
                    protected_ids=protected_ids,
                )
                tie_break = (
                    keep_value,
                    0 if duplicate_counts.get(card.template.template_id, 1) > 1 else 1,
                    0 if not self._air_card_has_live_use(player, engine, card, remaining_hand, projected_available_resources, projected_total_resources) else 1,
                    0 if card.template.card_type != CardType.CREATURE and self._air_card_role_is_redundant(card, remaining_hand) else 1,
                    0 if self._distance_to_reasonable_play(card, projected_total_resources) > 1 else 1,
                    0 if card.template.card_type != CardType.CREATURE else 1,
                )
                if len(creatures_in_hand) == 1 and card.template.card_type == CardType.CREATURE:
                    tie_break = (tie_break[0] + 8.0, *tie_break[1:])
                if len(interactions_in_hand) == 1 and card in interactions_in_hand and engine.players[1 - player.player_id].battlefield:
                    tie_break = (tie_break[0] + 3.0, *tie_break[1:])
                scored_cards.append((tie_break, card))
            scored_cards.sort(key=lambda item: item[0])
            selected = scored_cards[0][1]
            chosen.append(selected)
            remaining_hand = [card for card in remaining_hand if card.instance_id != selected.instance_id]
        return chosen

    def _score_air_resource_count_option(self, player: PlayerState, engine, resource_cards: list[CardInstance]) -> float:
        resource_count = len(resource_cards)
        remaining_hand = [card for card in player.hand if card.instance_id not in {resource.instance_id for resource in resource_cards}]
        current_available_resources = player.available_resources()
        available_resources = current_available_resources + resource_count
        total_resources = player.total_resources() + resource_count
        sequence_value, ending_total_resources, cards_played = self._best_air_main_phase_sequence(
            player,
            engine,
            remaining_hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        sacrificed_value = sum(
            self._air_resource_keep_value(
                player,
                engine,
                card,
                hand=player.hand,
                projected_available_resources=available_resources,
                projected_total_resources=total_resources,
                duplicate_count=sum(1 for hand_card in player.hand if hand_card.template.template_id == card.template.template_id),
                protected_ids=self._air_current_plan_protected_ids(
                    player,
                    engine,
                    remaining_hand,
                    available_resources=available_resources,
                    total_resources=total_resources,
                ),
            )
            for card in resource_cards
        )
        remaining_hand_size = len(remaining_hand)
        draw_aggression = 0.2 * min(2, len(player.deck))
        target_four_bonus = 0.0
        target_five_bonus = 0.0
        if total_resources >= 4 and any(card.template.resource_cost == 4 for card in remaining_hand):
            target_four_bonus = 1.2
        if total_resources >= 5 and any(card.template.resource_cost >= 5 for card in remaining_hand):
            target_five_bonus = 1.8
        overgrowth_penalty = 0.0
        if total_resources > 5:
            overgrowth_penalty = (total_resources - 5) * 2.0
        elif total_resources == 5 and not any(card.template.resource_cost >= 5 for card in remaining_hand):
            overgrowth_penalty = 0.9
        elif total_resources == 4 and not any(card.template.resource_cost >= 4 for card in remaining_hand):
            overgrowth_penalty = 0.35

        hand_floor_penalty = 0.0
        if total_resources <= 1 and remaining_hand_size <= 0:
            hand_floor_penalty += 6.0
        elif 2 <= total_resources <= 3 and remaining_hand_size < 2:
            hand_floor_penalty += (2 - remaining_hand_size) * 3.0
        elif total_resources >= 4 and remaining_hand_size < 3:
            hand_floor_penalty += (3 - remaining_hand_size) * 2.0
        if remaining_hand_size <= 1:
            hand_floor_penalty += 1.8

        remaining_resource_bonus_map = {
            0: -3.5,
            1: -1.8,
            2: 0.8,
            3: 2.3,
            4: 1.8,
            5: 1.2,
        }
        remaining_resource_bonus = remaining_resource_bonus_map.get(
            ending_total_resources,
            1.2 - max(0, ending_total_resources - 5) * 1.8,
        )
        current_resource_pressure = 0.0
        if current_available_resources <= 1:
            current_resource_pressure += resource_count * 2.0
            if resource_count == 2 and len(player.hand) >= 4 and len(remaining_hand) >= 2:
                current_resource_pressure += 1.8
            if current_available_resources == 0 and resource_count == 2 and len(player.hand) >= 5:
                current_resource_pressure += 1.6
        elif current_available_resources == 2:
            current_resource_pressure += resource_count * 1.2
        elif current_available_resources == 3:
            current_resource_pressure += 0.5 if resource_count == 1 else -1.0 if resource_count == 2 else 0.0
            if cards_played > 0 and resource_count > 0 and target_four_bonus == 0.0 and target_five_bonus == 0.0:
                current_resource_pressure -= 1.1
        elif current_available_resources == 4:
            current_resource_pressure += 0.4 if resource_count == 1 and target_five_bonus > 0 else -1.0 * resource_count
        elif current_available_resources >= 5:
            current_resource_pressure -= 1.8 * resource_count

        if resource_count == 2 and current_available_resources >= 3:
            current_resource_pressure -= 1.0
        if resource_count == 0 and cards_played > 0:
            current_resource_pressure += 0.8
        if resource_count == 0 and cards_played == 0 and current_available_resources <= 1:
            current_resource_pressure -= 2.0

        return (
            sequence_value
            + remaining_resource_bonus
            + current_resource_pressure
            + target_four_bonus
            + target_five_bonus
            + draw_aggression
            - sacrificed_value * 0.34
            - hand_floor_penalty
            - overgrowth_penalty
            - resource_count * 0.12
        )

    def _best_air_main_phase_sequence(
        self,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
    ) -> tuple[float, int, int]:
        plan = self._best_air_main_phase_plan(
            player,
            engine,
            hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        return plan["score"], plan["ending_total_resources"], len(plan["sequence"])

    def choose_main_phase_card(self, player: PlayerState, engine) -> Optional[CardInstance]:
        if getattr(player, "summoner_key", "") == "air":
            committed = self._get_committed_air_sequence(player, engine)
            if committed:
                return next((card for card in player.hand if card.instance_id == committed[0]), None)
            plan = self._build_best_air_turn_plan(player, engine)
            if not plan["sequence"]:
                return None
            self._commit_air_turn_plan(player, engine, plan)
            next_id = plan["sequence"][0]
            return next((card for card in player.hand if card.instance_id == next_id), None)
        self._clear_air_plan_state()
        spell = self.choose_ritual(player, engine)
        if spell is not None:
            return spell
        return self.choose_playable_creature(player)

    def _clear_air_plan_state(self) -> None:
        self._committed_air_plan = None
        self._planned_rueckenwind_target_id = None
        self._planned_turbulenz_target_ids = []
        self._planned_attacker_ids = []

    def _get_air_turn_key(self, player: PlayerState, engine) -> tuple[int, int, int]:
        return player.player_id, player.turns_started, engine.turn_number

    def _get_committed_air_sequence(self, player: PlayerState, engine) -> list[int]:
        if self._committed_air_plan is None or self._committed_air_plan.get("turn_key") != self._get_air_turn_key(player, engine):
            self._clear_air_plan_state()
            return []
        hand_ids = {card.instance_id for card in player.hand}
        remaining_sequence = [card_id for card_id in self._committed_air_plan.get("sequence", []) if card_id in hand_ids]
        self._committed_air_plan["sequence"] = remaining_sequence
        if not remaining_sequence:
            self._clear_air_plan_state()
            return []
        return remaining_sequence

    def _commit_air_turn_plan(self, player: PlayerState, engine, plan: dict) -> None:
        self._committed_air_plan = {
            "turn_key": self._get_air_turn_key(player, engine),
            "sequence": list(plan.get("sequence", [])),
        }
        self._planned_rueckenwind_target_id = plan.get("rueckenwind_target_id")
        self._planned_turbulenz_target_ids = list(plan.get("turbulenz_target_ids", []))
        self._planned_attacker_ids = list(plan.get("attacker_ids", []))

    def _build_best_air_turn_plan(self, player: PlayerState, engine) -> dict:
        hand = list(player.hand)
        enemy = engine.players[1 - player.player_id]
        base_plan = self._best_air_main_phase_plan(
            player,
            engine,
            hand,
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
        )
        base_attack = self._estimate_best_air_attack_plan(
            player,
            enemy,
            hand,
            base_plan["sequence"],
        )
        best_total = base_plan["score"] + base_attack["score"]
        best_plan = {
            "sequence": list(base_plan["sequence"]),
            "attacker_ids": list(base_attack["attacker_ids"]),
            "rueckenwind_target_id": None,
            "turbulenz_target_ids": [],
        }
        for card in hand:
            if (
                card.template.card_type not in {CardType.RITUAL, CardType.SPELL}
                or card.template.spell_effect not in {SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN, SpellEffect.RETURN_TWO_CREATURES_TO_HAND}
                or not engine.can_play_card(player, card)
            ):
                continue
            if card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
                comparison = self._evaluate_air_attack_bonus_support_plan(
                    player,
                    engine,
                    card,
                    hand=hand,
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                if not comparison["is_useful"]:
                    continue
                if comparison["with_total"] <= best_total + 0.65:
                    continue
                best_total = comparison["with_total"]
                best_plan = {
                    "sequence": [card.instance_id, *comparison["continuation_sequence"]],
                    "attacker_ids": list(comparison["attacker_ids"]),
                    "rueckenwind_target_id": comparison["target_id"],
                    "turbulenz_target_ids": [],
                }
                continue
            comparison = self._evaluate_air_turbulenz_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            if not comparison["is_useful"]:
                continue
            if comparison["with_total"] <= best_total + 1.0:
                continue
            best_total = comparison["with_total"]
            best_plan = {
                "sequence": [card.instance_id, *comparison["continuation_sequence"]],
                "attacker_ids": list(comparison["attacker_ids"]),
                "rueckenwind_target_id": None,
                "turbulenz_target_ids": list(comparison["target_ids"]),
            }
            for prefix_card in hand:
                if prefix_card.instance_id == card.instance_id or prefix_card.template.card_type != CardType.CREATURE:
                    continue
                reduced_cost = max(0, prefix_card.template.resource_cost - getattr(player, "creature_cost_reduction_this_turn", 0))
                if player.available_resources() < reduced_cost or player.total_resources() < prefix_card.template.recycle_cost:
                    continue
                prefix_battlefield = list(player.battlefield)
                prefix_created = BattlefieldCreature.from_card(prefix_card)
                prefix_created.tapped = not prefix_card.template.has_ability(Ability.HASTE)
                prefix_created.summoning_sick = not prefix_card.template.has_ability(Ability.HASTE)
                prefix_battlefield.append(prefix_created)
                prefix_player = self._clone_air_shadow_player(player, prefix_battlefield)
                prefix_hand = [existing for existing in hand if existing.instance_id != prefix_card.instance_id]
                prefixed = self._evaluate_air_turbulenz_plan(
                    prefix_player,
                    engine,
                    card,
                    hand=prefix_hand,
                    available_resources=player.available_resources() - reduced_cost,
                    total_resources=player.total_resources() - prefix_card.template.recycle_cost,
                    own_creature_count=len(prefix_battlefield),
                    ready_attacker_count=len([creature for creature in prefix_battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                if not prefixed["is_useful"] or prefixed["with_total"] <= best_total + 0.65:
                    continue
                best_total = prefixed["with_total"]
                best_plan = {
                    "sequence": [prefix_card.instance_id, card.instance_id, *prefixed["continuation_sequence"]],
                    "attacker_ids": list(prefixed["attacker_ids"]),
                    "rueckenwind_target_id": None,
                    "turbulenz_target_ids": list(prefixed["target_ids"]),
                }
        return best_plan

    def _best_air_main_phase_plan(
        self,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
        start_creature_discount: int | None = None,
        start_own_creature_count: int | None = None,
        start_ready_attacker_count: int | None = None,
    ) -> dict:
        enemy = engine.players[1 - player.player_id]

        def search(
            remaining_hand: list[CardInstance],
            remaining_available: int,
            remaining_total: int,
            creature_discount: int,
            own_creature_count: int,
            ready_attacker_count: int,
        ) -> tuple[float, int, int, tuple[int, ...]]:
            best = (0.0, remaining_available, remaining_total, ())
            for index, card in enumerate(remaining_hand):
                play = self._simulate_air_main_phase_play(
                    player,
                    enemy,
                    engine,
                    card,
                    remaining_hand,
                    remaining_available,
                    remaining_total,
                    creature_discount,
                    own_creature_count,
                    ready_attacker_count,
                )
                if play is None:
                    continue
                next_hand = remaining_hand[:index] + remaining_hand[index + 1 :]
                future_score, future_available, future_total, future_sequence = search(
                    next_hand,
                    play["available_resources"],
                    play["total_resources"],
                    play["creature_discount"],
                    play["own_creature_count"],
                    play["ready_attacker_count"],
                )
                total_score = play["value"] + future_score
                candidate_sequence = (card.instance_id,) + future_sequence
                candidate = (total_score, future_available, future_total, candidate_sequence)
                if candidate[0] > best[0] or (
                    candidate[0] == best[0]
                    and (len(candidate[3]), candidate[2], candidate[1]) > (len(best[3]), best[2], best[1])
                ):
                    best = candidate
            return best

        score, ending_available_resources, ending_total_resources, sequence = search(
            hand,
            available_resources,
            total_resources,
            getattr(player, "creature_cost_reduction_this_turn", 0) if start_creature_discount is None else start_creature_discount,
            len(player.battlefield) if start_own_creature_count is None else start_own_creature_count,
            len([creature for creature in player.battlefield if creature.is_ready()]) if start_ready_attacker_count is None else start_ready_attacker_count,
        )
        sequence_cards = [card for card in hand if card.instance_id in sequence]
        return {
            "score": score,
            "ending_available_resources": ending_available_resources,
            "ending_total_resources": ending_total_resources,
            "sequence": list(sequence),
            "cards_played": len(sequence),
            "creatures_played": sum(1 for card in sequence_cards if card.template.card_type == CardType.CREATURE),
            "creature_value": sum(self._air_creature_play_value(card) for card in sequence_cards if card.template.card_type == CardType.CREATURE),
        }

    def _simulate_air_main_phase_play(
        self,
        player: PlayerState,
        enemy: PlayerState,
        engine,
        card: CardInstance,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        creature_discount: int,
        own_creature_count: int,
        ready_attacker_count: int,
    ) -> Optional[dict]:
        template = card.template
        if template.card_type == CardType.CREATURE:
            cost = max(0, template.resource_cost - creature_discount)
            if available_resources < cost or total_resources < template.recycle_cost:
                return None
            value = self._air_creature_play_value(card)
            return {
                "value": value,
                "available_resources": available_resources - cost,
                "total_resources": total_resources - template.recycle_cost,
                "creature_discount": creature_discount,
                "own_creature_count": own_creature_count + 1,
                "ready_attacker_count": ready_attacker_count + (1 if template.has_ability(Ability.HASTE) else 0),
            }
        if template.card_type not in {CardType.RITUAL, CardType.SPELL}:
            return None
        if available_resources < template.resource_cost or total_resources < template.recycle_cost:
            return None
        if not self._air_card_has_live_use(
            player,
            engine,
            card,
            hand,
            available_resources,
            total_resources,
        ):
            return None
        remaining_hand = [existing for existing in hand if existing.instance_id != card.instance_id]
        next_available_resources = available_resources - template.resource_cost
        next_total_resources = total_resources - template.recycle_cost
        next_creature_discount = creature_discount
        next_own_creature_count = own_creature_count
        next_ready_attacker_count = ready_attacker_count
        value = self._air_spell_play_value(
            player,
            enemy,
            engine,
            card,
            remaining_hand=remaining_hand,
            available_resources=next_available_resources,
            total_resources=next_total_resources,
            own_creature_count=own_creature_count,
            ready_attacker_count=ready_attacker_count,
            creature_discount=creature_discount,
        )
        if template.spell_effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            next_creature_discount += template.spell_amount
        if template.spell_effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
            value += 0.8
        return {
            "value": value,
            "available_resources": next_available_resources,
            "total_resources": next_total_resources,
            "creature_discount": next_creature_discount,
            "own_creature_count": next_own_creature_count,
            "ready_attacker_count": next_ready_attacker_count,
        }

    def _air_creature_play_value(self, card: CardInstance) -> float:
        template = card.template
        value = template.aw * 1.7 + template.vw * 1.3
        if template.has_ability(Ability.HASTE):
            value += 1.4
        if template.has_ability(Ability.FLYING):
            value += 1.0
        if template.return_to_deck_end_of_turn:
            value += 0.7
        if template.must_attack_each_turn:
            value -= 0.3
        if template.cannot_block:
            value -= 0.8
        if template.recycle_cost > 0:
            value += 0.2
        if template.all_attackers_die_bonus > 0:
            value += 2.2
        if template.draw_on_play > 0:
            value += template.draw_on_play * 2.0
        if template.draw_on_attack > 0:
            value += template.draw_on_attack * 1.5
        if template.draw_on_death > 0:
            value += template.draw_on_death * 1.2
        if getattr(template, "draw_on_player_damage", 0) > 0:
            value += template.draw_on_player_damage * 1.8
        if getattr(template, "tap_enemy_creature_on_play", 0) > 0:
            value += template.tap_enemy_creature_on_play * 1.5
        if getattr(template, "return_other_own_haste_on_combat_death", False):
            value += 2.3
        if getattr(template, "own_flying_attack_aura", 0) > 0:
            value += template.own_flying_attack_aura * 2.6
        return value

    def _air_main_phase_spell_has_value(
        self,
        player: PlayerState,
        enemy: PlayerState,
        engine,
        card: CardInstance,
        *,
        own_creature_count: int,
        ready_attacker_count: int,
    ) -> bool:
        effect = card.template.spell_effect
        handler = self._get_air_card_handler(card)
        if handler is not None:
            specialized = handler.has_live_use(
                self,
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            if specialized is not None:
                return specialized
        if effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            comparison = self._evaluate_air_cost_reduction_support_plan(
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return comparison["is_useful"]
        if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            comparison = self._evaluate_air_attack_bonus_support_plan(
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return comparison["is_useful"]
        if effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
            comparison = self._evaluate_air_windwechsel_plan(
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return comparison["is_useful"]
        if effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
            comparison = self._evaluate_air_sturmformation_plan(
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return comparison["is_useful"]
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.has_live_use(
                    self,
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=own_creature_count,
                    ready_attacker_count=ready_attacker_count,
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                if specialized is not None:
                    return specialized
            return own_creature_count + len(enemy.battlefield) >= 2
        if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            comparison = self._evaluate_air_nachwehen_plan(
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
            )
            return comparison["is_useful"]
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            comparison = self._evaluate_air_ausweichen_plan(
                player,
                engine,
                card,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
            )
            return comparison["is_useful"]
        if effect in {
            SpellEffect.REROLL_OPEN_DIE,
            SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE,
        }:
            return False
        return self.has_valid_spell_targets(player, engine, card)

    def _air_spell_play_value(
        self,
        player: PlayerState,
        enemy: PlayerState,
        engine,
        card: CardInstance,
        *,
        remaining_hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> float:
        effect = card.template.spell_effect
        handler = self._get_air_card_handler(card)
        if handler is not None:
            specialized = handler.play_value(
                self,
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            if specialized is not None:
                return specialized
        if effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            comparison = self._evaluate_air_cost_reduction_support_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            comparison = self._evaluate_air_attack_bonus_support_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
            comparison = self._evaluate_air_windwechsel_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
            comparison = self._evaluate_air_sturmformation_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.play_value(
                    self,
                    player,
                    engine,
                    card,
                    hand=[card] + remaining_hand,
                    available_resources=available_resources,
                    total_resources=total_resources + card.template.recycle_cost,
                    own_creature_count=own_creature_count,
                    ready_attacker_count=ready_attacker_count,
                    creature_discount=creature_discount,
                )
                if specialized is not None:
                    return specialized
            comparison = self._evaluate_air_turbulenz_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            comparison = self._evaluate_air_ausweichen_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
            )
            return comparison["value"]
        if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            comparison = self._evaluate_air_nachwehen_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources,
                total_resources=total_resources + card.template.recycle_cost,
            )
            return comparison["value"]
        return 0.5

    def _air_resource_keep_value(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        projected_available_resources: int,
        projected_total_resources: int,
        duplicate_count: int,
        protected_ids: set[int],
    ) -> float:
        template = card.template
        enemy = engine.players[1 - player.player_id]
        value = 0.0
        next_turn_resources = projected_total_resources + 1
        if card.instance_id in protected_ids:
            value += 8.5
        if template.card_type == CardType.CREATURE:
            value += 3.2 + self._air_creature_play_value(card)
            if projected_available_resources >= template.resource_cost and projected_total_resources >= template.recycle_cost:
                value += 2.8
            elif template.resource_cost == projected_total_resources + 1:
                value += 1.8
            elif template.resource_cost <= next_turn_resources:
                value += 1.2
            else:
                value -= 0.4 * max(0, template.resource_cost - next_turn_resources)
            projected_remaining_resources = projected_total_resources - template.recycle_cost
            if template.recycle_cost > 0:
                if projected_remaining_resources >= 3:
                    value += 0.8
                elif projected_remaining_resources == 2:
                    value += 0.2
                else:
                    value -= 1.3 + (2 - projected_remaining_resources) * 0.8
            creatures_in_hand = sum(1 for hand_card in hand if hand_card.template.card_type == CardType.CREATURE)
            if creatures_in_hand == 1:
                value += 4.0
            if not player.battlefield:
                value += 1.1
            if template.resource_cost >= 5 and template.recycle_cost > 0 and projected_total_resources >= 4:
                value += 2.8
            value += self._air_specific_creature_keep_adjustment(
                player,
                enemy,
                card,
                hand,
                projected_available_resources=projected_available_resources,
                projected_total_resources=projected_total_resources,
            )
        else:
            has_live_use = self._air_card_has_live_use(
                player,
                engine,
                card,
                hand,
                projected_available_resources,
                projected_total_resources,
            )
            if has_live_use:
                value += self._air_spell_play_value(
                    player,
                    enemy,
                    engine,
                    card,
                    remaining_hand=[hand_card for hand_card in hand if hand_card.instance_id != card.instance_id],
                    available_resources=projected_available_resources,
                    total_resources=projected_total_resources,
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                ) + 1.2
            else:
                value -= 2.0
            if projected_available_resources >= template.resource_cost and projected_total_resources >= template.recycle_cost:
                value += 0.9
            elif template.resource_cost <= next_turn_resources:
                value += 0.6
            if template.resource_cost == 0 and template.recycle_cost > 0:
                value += 1.4 if engine.creatures_died_this_turn > 0 else -0.6
            value += self._air_specific_spell_keep_adjustment(
                player,
                enemy,
                engine,
                card,
                hand,
                projected_available_resources=projected_available_resources,
                projected_total_resources=projected_total_resources,
            )
        if duplicate_count > 1:
            value -= 1.2 * (duplicate_count - 1)
        if self._air_card_role_is_redundant(card, hand):
            value -= 0.7
        return value

    def _template_counts(self, cards: list[CardInstance]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for card in cards:
            counts[card.template.template_id] = counts.get(card.template.template_id, 0) + 1
        return counts

    def _air_current_plan_protected_ids(
        self,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
    ) -> set[int]:
        plan = self._best_air_main_phase_plan(
            player,
            engine,
            hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        protected_ids = set(plan["sequence"])
        enemy = engine.players[1 - player.player_id]
        if not player.battlefield:
            playable_creatures = [
                card for card in hand
                if card.template.card_type == CardType.CREATURE
                and available_resources >= card.template.resource_cost
                and total_resources >= card.template.recycle_cost
            ]
            if len(playable_creatures) == 1:
                protected_ids.add(playable_creatures[0].instance_id)
        lethal_card = self._find_air_lethal_enabler(player, enemy, hand)
        if lethal_card is not None:
            protected_ids.add(lethal_card.instance_id)
        answer_card = self._find_air_only_answer_card(player, enemy, engine, hand)
        if answer_card is not None:
            protected_ids.add(answer_card.instance_id)
        return protected_ids

    def _air_card_has_live_use(
        self,
        player: PlayerState,
        engine,
        card: CardInstance,
        hand: list[CardInstance],
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> bool:
        enemy = engine.players[1 - player.player_id]
        template = card.template
        if template.card_type == CardType.CREATURE:
            return projected_available_resources >= template.resource_cost and projected_total_resources >= template.recycle_cost
        handler = self._get_air_card_handler(card)
        if handler is not None:
            specialized = handler.has_live_use(
                self,
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
            if specialized is not None:
                return specialized
        if template.spell_effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            comparison = self._evaluate_air_cost_reduction_support_plan(
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
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            comparison = self._evaluate_air_attack_bonus_support_plan(
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
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
            comparison = self._evaluate_air_windwechsel_plan(
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
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
            comparison = self._evaluate_air_sturmformation_plan(
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
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.has_live_use(
                    self,
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
                if specialized is not None:
                    return specialized
            comparison = self._evaluate_air_turbulenz_plan(
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
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.has_live_use(
                    self,
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
                if specialized is not None:
                    return specialized
            comparison = self._evaluate_air_ausweichen_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
            )
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.REROLL_OPEN_DIE:
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.has_live_use(
                    self,
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
                if specialized is not None:
                    return specialized
            return engine.has_valid_open_die_target()
        if template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT:
            return any(creature.is_ready() for creature in player.battlefield)
        if template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
            return self._find_probable_unblocked_damage(player, enemy, hand) > 1
        if template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            if projected_total_resources < template.recycle_cost:
                return False
            comparison = self._evaluate_air_nachwehen_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
            )
            return comparison["value"] > 0.4
        return self.has_valid_spell_targets(player, engine, card)

    def _air_card_role_is_redundant(self, card: CardInstance, hand: list[CardInstance]) -> bool:
        template = card.template
        if sum(1 for hand_card in hand if hand_card.template.template_id == template.template_id) > 1:
            return True
        if template.card_type == CardType.CREATURE:
            same_cost_creatures = [
                hand_card for hand_card in hand
                if hand_card.instance_id != card.instance_id
                and hand_card.template.card_type == CardType.CREATURE
                and hand_card.template.resource_cost == template.resource_cost
                and hand_card.template.aw + hand_card.template.vw >= template.aw + template.vw
            ]
            return bool(same_cost_creatures)
        return False

    def _distance_to_reasonable_play(self, card: CardInstance, projected_total_resources: int) -> int:
        return max(0, card.template.resource_cost - projected_total_resources)

    def _count_discounted_creature_lines(self, hand: list[CardInstance], available_resources: int, total_resources: int) -> int:
        count = 0
        creatures = [card for card in hand if card.template.card_type == CardType.CREATURE]
        for creature in creatures:
            reduced_cost = max(0, creature.template.resource_cost - 1)
            if available_resources >= reduced_cost and total_resources >= creature.template.recycle_cost:
                count += 1
        if len(creatures) >= 2 and count >= 2:
            return count
        return count

