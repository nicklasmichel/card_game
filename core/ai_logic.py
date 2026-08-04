from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardType, DieResult, PHASE_REACTION, PHASE_SPELL_TARGETING, ReactionTrigger, SpellEffect, PlayerState, SpellTargetRef


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
        self._planned_turbulenz_target_ids: list[int] = []
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
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT:
            return engine.has_valid_boeenschub_target(player)
        if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
            return bool(player.battlefield or enemy.battlefield)
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            return len(player.battlefield) + len(enemy.battlefield) >= 2
        if effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
            return bool(player.battlefield or enemy.battlefield)
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            return engine.has_valid_ausweichen_target(player)
        if effect == SpellEffect.REROLL_OPEN_DIE:
            return engine.has_valid_open_die_target()
        if effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
            enemy = engine.players[1 - player.player_id]
            return bool(self._current_windrausch_attackers(player, engine)) or self._find_probable_unblocked_damage(player, enemy, list(player.hand)) > 0
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
            value += 0.2
        if template.cannot_block:
            value -= 0.5
        if template.recycle_cost > 0:
            value += 0.6
        if template.all_attackers_die_bonus > 0:
            value += 2.2
        if template.draw_on_play > 0:
            value += template.draw_on_play * 2.0
        if template.draw_on_attack > 0:
            value += template.draw_on_attack * 1.5
        if template.draw_on_death > 0:
            value += template.draw_on_death * 1.2
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
        if player.hand_cards_played_this_turn == 2 and next_available > 0:
            expected_upgrade += p_passive_follow_up * 1.4
        if next_available == 0:
            expected_upgrade -= 1.0
            if weak_current >= 2 or len(remaining_hand) <= 1:
                expected_upgrade += 0.5
        discard_penalty = discarded_value * 0.43 + max(0, len(remaining_hand) - 1) * 0.95
        if len(remaining_hand) >= 4:
            discard_penalty += 1.1
        passive_draw_loss = 0.0
        if player.hand_cards_played_this_turn == 3:
            passive_draw_loss = p_useful * 1.4 + p_playable_now * 0.9 + 0.8
        expected_total = after_cast_known["score"] + expected_upgrade - discard_penalty - passive_draw_loss - 1.2
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
        shadow.hand_cards_played_this_turn = player.hand_cards_played_this_turn
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
                if player.hand_cards_played_this_turn == 2 and replay_value > 0.8:
                    value += 0.45
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
            return engine.creatures_died_this_turn >= 2 and total_resources >= template.recycle_cost
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
            if effect == SpellEffect.REROLL_OPEN_DIE and bool(player.battlefield):
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
            draw_on_attack=creature.draw_on_attack,
            draw_on_death=creature.draw_on_death,
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
        probable_damage = 0
        no_blockers = not enemy.battlefield
        for creature in player.battlefield:
            if not creature.is_ready():
                continue
            if no_blockers or (creature.has_ability(Ability.FLYING) and flying_blockers == 0):
                probable_damage += creature.aw
        for card in hand:
            if card.template.card_type != CardType.CREATURE:
                continue
            if not card.template.has_ability(Ability.HASTE):
                continue
            if no_blockers or (card.template.has_ability(Ability.FLYING) and flying_blockers == 0):
                probable_damage += card.template.aw
        return probable_damage

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
            return 2.8 if comparison["is_useful"] else -3.0
        if effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
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
            return 3.0 if comparison["is_useful"] else -3.2
        if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
            comparison = self._evaluate_air_ausweichen_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
            )
            return 2.4 if comparison["is_useful"] else -3.0
        if effect == SpellEffect.REROLL_OPEN_DIE:
            return 1.6 if engine.has_valid_open_die_target() else -1.8
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT:
            comparison = self._evaluate_air_boeenschub_reaction_plan(player, engine, card)
            return 2.6 if comparison["is_useful"] else -2.8
        if effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
            damage = self._find_probable_unblocked_damage(player, enemy, hand)
            if damage * 2 >= enemy.life and damage > 0:
                return 5.5
            return 2.4 if damage >= 4 else 0.9 if damage >= 2 else -2.8
        if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
            comparison = self._evaluate_air_nachwehen_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
            )
            return comparison["value"]
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
        candidates = engine.get_open_die_target_refs()
        if not candidates:
            return None, -999.0
        scored = [(self._score_windstoss_target(player, engine, target), target) for target in candidates]
        best_score, best_target = max(scored, key=lambda item: item[0])
        return best_target, best_score

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
        if chosen.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE and best_score[0] <= 0:
            return None
        if chosen.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN and best_score[0] <= 0:
            return None
        return chosen if best_score[0] > 0 or self.rng.random() < 0.4 else None

    def choose_resources_to_recycle(self, player: PlayerState, count: int) -> List[int]:
        if count <= 0:
            return []

        def score(resource) -> tuple[int, int, int, int, int]:
            template = resource.template
            return (
                1 if getattr(resource, "tapped", False) else 0,
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
