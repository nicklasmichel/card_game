from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import (
    Ability,
    BattlefieldCreature,
    CardInstance,
    CardType,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PlayerState,
    SpellEffect,
)


def expected_w6_sum(dice_count: int) -> float:
    return max(0, dice_count) * 3.5


class RandomDieStrategy:
    name = "Zufaellig"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        return rng.choice(dice)


class HighestFirstDieStrategy:
    name = "Hoechster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        return max(dice, key=lambda die: getattr(die, "total", 0))


class LowestFirstDieStrategy:
    name = "Niedrigster Wuerfel zuerst"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        return min(dice, key=lambda die: getattr(die, "total", 0))


class SacrificeLowThenHighDieStrategy:
    name = "Niedrigen Wuerfel opfern, dann hoch spielen"

    @staticmethod
    def choose(dice: List[object], rng: Random):
        if len(dice) >= 3:
            return min(dice, key=lambda die: getattr(die, "total", 0))
        return max(dice, key=lambda die: getattr(die, "total", 0))


class CommonAIMixin:
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
            return engine.has_valid_turn_attack_bonus_targets(player)
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
            return engine.has_valid_attacker_combat_bonus_targets(player)
        if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
            return bool(player.battlefield or enemy.battlefield)
        if effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
            return len(engine.get_valid_discard_creature_target_refs(player)) >= max(1, card.template.spell_amount)
        if effect == SpellEffect.RETURN_CREATURES_TO_HAND:
            return len(player.battlefield) + len(enemy.battlefield) >= max(1, card.template.spell_amount)
        if effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
            return bool(player.battlefield or enemy.battlefield)
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

    def choose_resource_card_for_main_phase(self, player: PlayerState, engine, phase: str) -> Optional[CardInstance]:
        if player.resources_played_this_turn >= 2 or not player.hand:
            return None
        if len(player.hand) <= 1:
            return None
        if phase == PHASE_MAIN_1:
            if player.resources_played_this_turn >= 1:
                return None
            playable_now = any(engine.can_play_card(player, card) for card in player.hand)
            if playable_now and player.available_resources() > 0:
                return None
            return self.choose_resource_card(player)
        if phase == PHASE_MAIN_2:
            if player.resources_played_this_turn == 0:
                if any(card.template.card_type == CardType.CREATURE and card.template.resource_cost > player.available_resources() for card in player.hand):
                    return self.choose_resource_card(player)
                if any(engine.can_play_card(player, card) for card in player.hand):
                    return self.choose_resource_card(player)
            if player.resources_played_this_turn == 1 and len(player.hand) >= 3:
                return self.choose_resource_card(player)
        return None

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
        planned_ids = tuple(getattr(self, "_get_planned_attacker_ids", lambda: ())())
        if planned_ids:
            planned = [creature for creature in creatures if creature.unit_id in planned_ids and creature.is_ready()]
            if planned:
                return planned
        return [creature for creature in creatures if creature.is_ready()]

    def choose_attackers_for_player(
        self,
        player: PlayerState,
        engine,
        creatures: List[BattlefieldCreature],
    ) -> List[BattlefieldCreature]:
        return self.choose_attackers(creatures)

    def choose_blocker(self, attacker: BattlefieldCreature, blockers: List[BattlefieldCreature]) -> Optional[BattlefieldCreature]:
        if not blockers:
            return None

        def score(blocker: BattlefieldCreature) -> tuple[float, int, int, int]:
            expected_margin = expected_w6_sum(blocker.vw) - expected_w6_sum(attacker.aw)
            survival_margin = blocker.current_hp - attacker.sw
            trade_margin = blocker.sw - attacker.current_hp
            return expected_margin, survival_margin, trade_margin, blocker.current_hp

        return max(blockers, key=score)

    def choose_blockers_for_attackers(
        self,
        attackers: List[BattlefieldCreature],
        blockers: List[BattlefieldCreature],
        existing_assignments: Optional[dict[int, int | None]] = None,
    ) -> dict[int, int | None]:
        assignments: dict[int, int | None] = {
            attacker.unit_id: (existing_assignments or {}).get(attacker.unit_id)
            for attacker in attackers
        }
        used_blockers = {blocker_id for blocker_id in assignments.values() if blocker_id is not None}

        for attacker in sorted(attackers, key=lambda unit: (-unit.sw, -unit.aw, unit.current_hp)):
            if assignments[attacker.unit_id] is not None:
                continue
            available = [
                blocker
                for blocker in blockers
                if blocker.unit_id not in used_blockers
                and (not attacker.has_ability(Ability.FLYING) or blocker.has_ability(Ability.FLYING))
            ]
            blocker = self.choose_blocker(attacker, available)
            if blocker is None:
                continue
            assignments[attacker.unit_id] = blocker.unit_id
            used_blockers.add(blocker.unit_id)
        return assignments

    def choose_die_strategy(self) -> type:
        return self.rng.choice(
            [
                RandomDieStrategy,
                HighestFirstDieStrategy,
                LowestFirstDieStrategy,
                SacrificeLowThenHighDieStrategy,
            ]
        )
