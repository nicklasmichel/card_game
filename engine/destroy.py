from __future__ import annotations

from core.models import Ability, CardInstance, PHASE_GAME_OVER


def remove_creature_from_combat(self, creature_id: int) -> None:
    was_attacker = creature_id in self.block_assignments
    if was_attacker:
        self.blocked_attackers.discard(creature_id)
        self.combat_queue = [attacker_id for attacker_id in self.combat_queue if attacker_id != creature_id]
        self.block_assignments.pop(creature_id, None)
        self.pending_direct_attacks = [
            attack for attack in self.pending_direct_attacks if attack.attacker_id != creature_id
        ]
        if self.pending_direct_attack is not None and self.pending_direct_attack.attacker_id == creature_id:
            self.pending_direct_attack = None
    for attacker_id, blocker_id in list(self.block_assignments.items()):
        if blocker_id == creature_id:
            self.block_assignments[attacker_id] = None
    battle = self.pending_dice_battle
    if battle is not None and creature_id in {battle.attacker_id, battle.blocker_id}:
        battle.resolution_complete = True


def should_return_creature_from_combat_death(self, owner, creature) -> bool:
    if not creature.has_ability(Ability.HASTE):
        return False
    return any(
        other.current_hp > 0
        and other.unit_id != creature.unit_id
        and getattr(other, "return_other_own_haste_on_combat_death", False)
        for other in owner.battlefield
    )


def destroy_creature_immediately(
    self,
    owner,
    creature,
    source_name: str,
    *,
    died_in_combat: bool = False,
    log_destruction: bool = True,
) -> None:
    remove_creature_from_combat(self, creature.unit_id)
    return_to_hand_after_death = died_in_combat and should_return_creature_from_combat_death(self, owner, creature)
    if creature in owner.battlefield:
        owner.battlefield.remove(creature)
    self.creatures_died_this_turn += 1
    setattr(creature, "owner_id", owner.player_id)
    destroyed_card = CardInstance(self.make_instance_id(), self.templates[creature.template_id])
    owner.discard_pile.append(destroyed_card)
    if log_destruction:
        self.log(f"{source_name} destroys {creature.name}. {creature.name} goes to the discard pile.")
    draw_on_death = getattr(creature, "draw_on_death", 0)
    if draw_on_death > 0:
        for _ in range(draw_on_death):
            drawn = self.draw_card_for_player(owner, creature.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                break
        if self.phase != PHASE_GAME_OVER:
            self.log(f"{creature.name} lets {owner.name} draw {draw_on_death} card(s) when it dies.")
    if return_to_hand_after_death:
        if destroyed_card in owner.discard_pile:
            owner.discard_pile.remove(destroyed_card)
        owner.hand.append(destroyed_card)
        self.log(f"Orc Spirit returns {creature.name} to {owner.name}'s hand.")
    if self.statistics is not None:
        self.statistics.player_stats[owner.player_id].creatures_destroyed += 1
