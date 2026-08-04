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
        self._committed_air_plan: dict | None = None
        self._planned_rueckenwind_target_id: int | None = None
        self._planned_attacker_ids: list[int] = []

    def has_valid_spell_targets(self, player: PlayerState, engine, card: CardInstance) -> bool:
        effect = card.template.spell_effect
        enemy = engine.players[1 - player.player_id]
        if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
            return bool(enemy.battlefield or player.battlefield)
        if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
            return True
        if effect == SpellEffect.SACRIFICE_FOR_DAMAGE:
            return bool(player.battlefield) and (bool(enemy.battlefield) or enemy.life > 0)
        if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            return bool(player.battlefield or enemy.battlefield)
        if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
            return bool(player.battlefield or enemy.battlefield)
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            return len(player.battlefield) + len(enemy.battlefield) >= 2
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
                SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE,
                SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE,
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
        }
        for card in hand:
            if (
                card.template.card_type not in {CardType.RITUAL, CardType.SPELL}
                or card.template.spell_effect != SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN
                or not engine.can_play_card(player, card)
            ):
                continue
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
            value += 0.2
        if template.cannot_block:
            value -= 0.5
        if template.recycle_cost > 0:
            value += 0.6
        if template.all_attackers_die_bonus > 0:
            value += 2.2
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
            return len(player.hand) >= 2 and len(player.deck) >= 3
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            return own_creature_count + len(enemy.battlefield) >= 2
        if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            return engine.creatures_died_this_turn > 0
        if effect in {
            SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND,
            SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE,
            SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE,
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
            weak_hand = sum(
                1
                for hand_card in remaining_hand
                if not self._air_card_has_live_use(
                    player,
                    engine,
                    hand_card,
                    remaining_hand,
                    available_resources,
                    total_resources,
                )
            )
            return 0.6 + weak_hand * 0.9
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            creature_values = sorted(
                (creature.aw + creature.current_hp, owner_id)
                for owner_id, creatures in (
                    (player.player_id, player.battlefield),
                    (enemy.player_id, enemy.battlefield),
                )
                for creature in creatures
            )
            if len(creature_values) < 2:
                return -2.0
            best_two = creature_values[-2:]
            enemy_gain = sum(value for value, owner_id in best_two if owner_id == enemy.player_id)
            own_loss = sum(value for value, owner_id in best_two if owner_id == player.player_id)
            return 1.0 + max(0.0, enemy_gain - own_loss) * 0.35
        if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            return engine.creatures_died_this_turn * 1.8
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
            return len(hand) >= 2 and len(player.deck) >= 3
        if template.spell_effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            return len(player.battlefield) + len(enemy.battlefield) >= 2
        if template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            return engine.has_valid_ausweichen_target(player)
        if template.spell_effect in {SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE, SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE}:
            return engine.has_valid_combat_die_target(player)
        if template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
            return self._find_probable_unblocked_damage(player, enemy, hand) > 0
        if template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            return engine.creatures_died_this_turn > 0 and projected_total_resources >= template.recycle_cost
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
        if with_attack["target_id"] is None or not with_attack["attacker_ids"]:
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
        passive_follow_up_hits = 0
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
            if self._air_template_can_be_played_as_fourth_card(
                player,
                template,
                available_resources=next_available,
                total_resources=next_total,
                creature_discount=creature_discount,
            ):
                passive_follow_up_hits += 1
        p_playable_now = cheap_playable_hits / total_remaining if total_remaining else 0.0
        p_useful = broadly_useful_hits / total_remaining if total_remaining else 0.0
        p_weak_replace = weak_replace_hits / total_remaining if total_remaining else 0.0
        p_creature_hit = creature_hits / total_remaining if total_remaining else 0.0
        p_passive_follow_up = passive_follow_up_hits / total_remaining if total_remaining else 0.0
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
        if player.hand_cards_played_this_turn == 2 and next_available > 0:
            expected_upgrade += p_passive_follow_up * 1.2
        if player.hand_cards_played_this_turn == 3:
            expected_upgrade += 0.6
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

    def _air_template_is_generally_draw_worthy(
        self,
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
        if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
            return any(creature.is_ready() for creature in player.battlefield)
        if effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
            return len(player.deck) >= 2
        if effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
            return False
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            return len(player.battlefield) + len(engine.players[1 - player.player_id].battlefield) >= 2 and total_resources >= template.recycle_cost
        if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            return engine.creatures_died_this_turn > 0 and total_resources >= template.recycle_cost
        return template.resource_cost <= available_resources and template.recycle_cost <= total_resources

    def _air_template_improves_weak_hand(
        self,
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
        return self._air_template_is_generally_draw_worthy(
            player,
            engine,
            template,
            hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )

    def _air_template_can_be_played_as_fourth_card(
        self,
        player: PlayerState,
        template,
        *,
        available_resources: int,
        total_resources: int,
        creature_discount: int,
    ) -> bool:
        if player.hand_cards_played_this_turn != 2:
            return False
        if template.card_type == CardType.CREATURE:
            return max(0, template.resource_cost - creature_discount) <= available_resources and template.recycle_cost <= total_resources
        return template.resource_cost <= available_resources and template.recycle_cost <= total_resources and template.card_type in {CardType.RITUAL, CardType.SPELL}

    def _air_reaction_hold_advantage(
        self,
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
        if self._has_plausible_air_combat_reaction(player, engine, with_remaining, with_support["ending_available_resources"]) and not self._has_plausible_air_combat_reaction(
            player,
            engine,
            without_remaining,
            without_support["ending_available_resources"],
        ):
            return 0.4
        return 0.0

    def _has_plausible_air_combat_reaction(self, player: PlayerState, engine, hand: list[CardInstance], available_resources: int) -> bool:
        enemy = engine.players[1 - player.player_id]
        for card in hand:
            if card.template.card_type != CardType.SPELL:
                continue
            if available_resources < card.template.resource_cost:
                continue
            effect = card.template.spell_effect
            if effect in {SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE, SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE} and bool(player.battlefield):
                return True
            if effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE and self._find_probable_unblocked_damage(player, enemy, hand) > 0:
                return True
        return False

    def _estimate_best_air_attack_plan(
        self,
        player: PlayerState,
        enemy: PlayerState,
        hand: list[CardInstance],
        sequence: list[int],
        *,
        attack_bonus_amount: int = 0,
    ) -> dict:
        attackers = self._project_air_attackers(player, hand, sequence)
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
                plan = self._score_air_attack_subset(
                    chosen_attackers,
                    enemy,
                    attack_bonus_target_id=target_id,
                    attack_bonus_amount=attack_bonus_amount,
                )
                if plan["score"] > best["score"] + 0.01 or (
                    abs(plan["score"] - best["score"]) <= 0.01
                    and (plan["is_lethal"], plan["direct_damage"], len(plan["attacker_ids"])) > (best["is_lethal"], best["direct_damage"], len(best["attacker_ids"]))
                ):
                    best = plan
        return best

    def _project_air_attackers(self, player: PlayerState, hand: list[CardInstance], sequence: list[int]) -> list[BattlefieldCreature]:
        hand_by_id = {card.instance_id: card for card in hand}
        attackers = [creature for creature in player.battlefield if creature.is_ready() and creature.current_hp > 0]
        for card_id in sequence:
            card = hand_by_id.get(card_id)
            if card is None or card.template.card_type != CardType.CREATURE or not card.template.has_ability(Ability.HASTE):
                continue
            created = BattlefieldCreature.from_card(card)
            created.tapped = False
            created.summoning_sick = False
            attackers.append(created)
        return attackers

    def _clone_attack_creature(self, creature: BattlefieldCreature, attack_bonus: int = 0) -> BattlefieldCreature:
        return BattlefieldCreature(
            unit_id=creature.unit_id,
            template_id=creature.template_id,
            name=creature.name,
            cost=creature.cost,
            aw=creature.aw + attack_bonus,
            vw=creature.vw,
            element=creature.element,
            abilities=creature.abilities,
            rules_text=creature.rules_text,
            reveal_opponent_hand=creature.reveal_opponent_hand,
            return_to_deck_end_of_turn=creature.return_to_deck_end_of_turn,
            cannot_block=creature.cannot_block,
            must_attack_each_turn=creature.must_attack_each_turn,
            all_attackers_die_bonus=creature.all_attackers_die_bonus,
            current_hp=creature.current_hp,
            temporary_aw_bonus=creature.temporary_aw_bonus,
            tapped=creature.tapped,
            summoning_sick=creature.summoning_sick,
            temporary_abilities=set(creature.temporary_abilities),
        )

    def _score_air_attack_subset(
        self,
        attackers: list[BattlefieldCreature],
        enemy: PlayerState,
        *,
        attack_bonus_target_id: int | None,
        attack_bonus_amount: int,
    ) -> dict:
        cloned_attackers = [
            self._clone_attack_creature(
                attacker,
                attack_bonus_amount if attacker.unit_id == attack_bonus_target_id else 0,
            )
            for attacker in attackers
        ]
        blockers = [creature for creature in enemy.battlefield if creature.current_hp > 0]
        blocker_assignments = self.choose_blockers_for_attackers(cloned_attackers, blockers)
        blockers_by_id = {blocker.unit_id: blocker for blocker in blockers}
        score = 0.0
        direct_damage = 0
        enemy_kills = 0
        own_losses = 0
        for attacker in cloned_attackers:
            assigned_blockers = [blockers_by_id[blocker_id] for blocker_id in blocker_assignments.get(attacker.unit_id, []) if blocker_id in blockers_by_id]
            attacker_value = attacker.aw * 1.6 + attacker.current_hp * 1.1 + len(attacker.abilities) * 0.4
            if not assigned_blockers:
                direct_damage += attacker.aw
                score += attacker.aw * 1.45
                if attacker.has_ability(Ability.FLYING) and not any(blocker.has_ability(Ability.FLYING) for blocker in blockers):
                    score += 0.8
                continue
            blocker_aw_total = sum(blocker.aw for blocker in assigned_blockers)
            kills_here = 0
            if any(attacker.aw >= blocker.current_hp for blocker in assigned_blockers):
                kills_here = sum(1 for blocker in assigned_blockers if attacker.aw >= blocker.current_hp)
                enemy_kills += kills_here
                score += sum((blocker.aw + blocker.current_hp * 1.1) * 0.7 for blocker in assigned_blockers if attacker.aw >= blocker.current_hp)
            if blocker_aw_total >= attacker.current_hp:
                own_losses += 1
                score -= attacker_value * 0.8
            else:
                score += 0.7 + attacker.aw * 0.25 + kills_here * 0.3
        if direct_damage >= enemy.life:
            score += 9.0
        return {
            "score": score,
            "attacker_ids": [attacker.unit_id for attacker in cloned_attackers],
            "target_id": attack_bonus_target_id,
            "direct_damage": direct_damage,
            "enemy_kills": enemy_kills,
            "own_losses": own_losses,
            "is_lethal": direct_damage >= enemy.life,
        }

    def _count_probable_attackers(self, player: PlayerState, hand: list[CardInstance]) -> int:
        ready_now = len([creature for creature in player.battlefield if creature.is_ready()])
        hasty_from_hand = len([
            card for card in hand
            if card.template.card_type == CardType.CREATURE and card.template.has_ability(Ability.HASTE)
        ])
        return ready_now + hasty_from_hand

    def _find_probable_unblocked_damage(self, player: PlayerState, enemy: PlayerState, hand: list[CardInstance]) -> int:
        flying_blockers = len([creature for creature in enemy.battlefield if creature.has_ability(Ability.FLYING)])
        best_damage = 0
        for creature in player.battlefield:
            if not creature.is_ready():
                continue
            if creature.has_ability(Ability.FLYING) and flying_blockers == 0:
                best_damage = max(best_damage, creature.aw)
        for card in hand:
            if card.template.card_type != CardType.CREATURE:
                continue
            if not card.template.has_ability(Ability.HASTE):
                continue
            if card.template.has_ability(Ability.FLYING) and flying_blockers == 0:
                best_damage = max(best_damage, card.template.aw)
        return best_damage

    def _find_air_lethal_enabler(self, player: PlayerState, enemy: PlayerState, hand: list[CardInstance]) -> Optional[CardInstance]:
        probable_unblocked_damage = self._find_probable_unblocked_damage(player, enemy, hand)
        if probable_unblocked_damage <= 0:
            return None
        for card in hand:
            if card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE and probable_unblocked_damage * 2 >= enemy.life:
                return card
        return None

    def _find_air_only_answer_card(self, player: PlayerState, enemy: PlayerState, engine, hand: list[CardInstance]) -> Optional[CardInstance]:
        if not enemy.battlefield:
            return None
        threatening_enemy = max(enemy.battlefield, key=lambda creature: creature.aw + creature.current_hp)
        if threatening_enemy.aw + threatening_enemy.current_hp < 6:
            return None
        answers = [
            card for card in hand
            if card.template.spell_effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND
        ]
        if len(answers) == 1:
            return answers[0]
        defensive_creatures = [
            card for card in hand
            if card.template.card_type == CardType.CREATURE and not card.template.cannot_block
        ]
        if len(defensive_creatures) == 1 and not player.battlefield:
            return defensive_creatures[0]
        return None

    def _air_specific_creature_keep_adjustment(
        self,
        player: PlayerState,
        enemy: PlayerState,
        card: CardInstance,
        hand: list[CardInstance],
        *,
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> float:
        template = card.template
        if template.template_id == "air_creature_windgeist":
            if not player.battlefield:
                return 1.6
            better_creatures = [
                other for other in hand
                if other.instance_id != card.instance_id
                and other.template.card_type == CardType.CREATURE
                and other.template.aw + other.template.vw > template.aw + template.vw
            ]
            return -0.8 if better_creatures else 0.2
        if template.template_id == "air_creature_boeengeist":
            remaining_after_recycle = projected_total_resources - template.recycle_cost
            if remaining_after_recycle <= 1:
                return -1.4
            return 1.4 if not player.battlefield else 0.5
        if template.template_id == "air_creature_windhuscher":
            return 2.0 if self._find_probable_unblocked_damage(player, enemy, hand) > 0 else -1.2
        if template.template_id in {"air_creature_boeenreiter", "air_creature_windklinge"}:
            immediate_attack = template.has_ability(Ability.HASTE)
            adjustment = 1.8 if immediate_attack else 0.4
            if template.recycle_cost > 0 and projected_total_resources - template.recycle_cost <= 1:
                adjustment -= 1.6
            return adjustment
        if template.template_id in {"air_creature_sturmfalke", "air_creature_himmelsgreif"}:
            adjustment = 1.6 if not any(creature.has_ability(Ability.FLYING) for creature in enemy.battlefield) else 0.5
            if any(card.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE for card in hand):
                adjustment += 1.2
            if template.recycle_cost > 0 and projected_total_resources - template.recycle_cost <= 1:
                adjustment -= 1.2
            return adjustment
        if template.template_id == "air_creature_himmelsspaeher":
            return -0.8 if enemy.battlefield and max(creature.aw for creature in enemy.battlefield) >= template.vw else 1.0
        if template.template_id == "air_creature_wolkenwaechter":
            return -1.4 if enemy.battlefield and not player.battlefield else 0.8
        if template.template_id == "air_creature_sturmfuerst":
            attackers = self._count_probable_attackers(player, hand)
            if projected_total_resources >= 4 and attackers >= 2:
                return 4.2
            if projected_total_resources <= 2:
                return -1.2
            return 1.2
        return 0.0

    def _air_specific_spell_keep_adjustment(
        self,
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
        if effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
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
            return 2.8 if comparison["is_useful"] else -3.2
        if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
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
            return 2.4 if comparison["is_useful"] else -2.4
        if effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
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
            return 2.3 if comparison["is_useful"] else -2.2
        if effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
            weak_hand = sum(
                1
                for hand_card in hand
                if hand_card.instance_id != card.instance_id
                and not self._air_card_has_live_use(
                    player,
                    engine,
                    hand_card,
                    hand,
                    projected_available_resources,
                    projected_total_resources,
                )
            )
            return 2.2 if weak_hand >= 2 else -2.8
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            if len(player.battlefield) + len(enemy.battlefield) < 2:
                return -3.2
            all_creatures = sorted(
                (creature.aw + creature.current_hp, owner_id)
                for owner_id, creatures in (
                    (player.player_id, player.battlefield),
                    (enemy.player_id, enemy.battlefield),
                )
                for creature in creatures
            )
            best_two = all_creatures[-2:]
            enemy_gain = sum(value for value, owner_id in best_two if owner_id == enemy.player_id)
            own_loss = sum(value for value, owner_id in best_two if owner_id == player.player_id)
            return 2.8 if enemy_gain - own_loss >= 2 else -1.8
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            return 2.0 if engine.has_valid_ausweichen_target(player) else -2.2
        if effect == SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE:
            return 1.6 if engine.has_valid_combat_die_target(player) else -1.8
        if effect == SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE:
            return 2.2 if engine.has_valid_combat_die_target(player) else -2.1
        if effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
            damage = self._find_probable_unblocked_damage(player, enemy, hand)
            if damage * 2 >= enemy.life and damage > 0:
                return 5.5
            return 2.0 if damage > 0 else -2.6
        if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            if projected_total_resources < card.template.recycle_cost:
                return -3.0
            if engine.creatures_died_this_turn <= 0:
                return -3.2
            remaining_after_recycle = projected_total_resources - card.template.recycle_cost
            return engine.creatures_died_this_turn * 2.2 + (1.0 if remaining_after_recycle >= 2 else -1.6)
        return 0.0

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
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
                useful_targets = [creature for creature in player.battlefield if creature.current_hp > 0]
                score = (1 if useful_targets else -5, len(useful_targets), 0)
            elif card.template.spell_effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
                score = (2 if len(player.deck) >= 2 else -10, len(player.hand), 0)
            elif card.template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
                weak_cards = sum(
                    1
                    for hand_card in player.hand
                    if hand_card.instance_id != card.instance_id
                    and not self._air_card_has_live_use(
                        player,
                        engine,
                        hand_card,
                        player.hand,
                        player.available_resources(),
                        player.total_resources(),
                    )
                )
                score = (2 if weak_cards >= 2 else 0, weak_cards, -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
                all_creatures = sorted(
                    (creature.aw + creature.current_hp, owner_id)
                    for owner_id, creatures in (
                        (player.player_id, player.battlefield),
                        (engine.human_player.player_id, engine.human_player.battlefield),
                    )
                    for creature in creatures
                )
                if len(all_creatures) >= 2:
                    best_two = all_creatures[-2:]
                    enemy_gain = sum(value for value, owner_id in best_two if owner_id == engine.human_player.player_id)
                    own_loss = sum(value for value, owner_id in best_two if owner_id == player.player_id)
                    score = (2 if enemy_gain > own_loss else 0, enemy_gain - own_loss, 0)
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
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
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
        if self._planned_attacker_ids:
            planned = [creature for creature in creatures if creature.unit_id in self._planned_attacker_ids and creature.is_ready()]
            if planned:
                return planned
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
