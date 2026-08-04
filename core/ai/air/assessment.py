from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardType, DieResult, PHASE_REACTION, PHASE_SPELL_TARGETING, PlayerState, ReactionTrigger, SpellEffect, SpellTargetRef

class AirAssessmentMixin:
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
        if len(cloned_attackers) >= 3:
            score += 1.15
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
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.keep_adjustment(
                    self,
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
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.keep_adjustment(
                    self,
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
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized = handler.keep_adjustment(
                    self,
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

