from __future__ import annotations

from random import Random
from typing import List, Optional

from core.models import Ability, BattlefieldCreature, CardCost, CardInstance, CardType, DieResult, PHASE_REACTION, PHASE_SPELL_TARGETING, PlayerState, ReactionTrigger, SpellEffect, SpellTargetRef

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
