from __future__ import annotations

from typing import Optional

from core.models import (
    Ability,
    BattlefieldCreature,
    CardInstance,
    CombatUnitSnapshot,
    DiceRoundRecord,
    DieResult,
    PendingComparison,
    PendingDiceBattle,
)


def make_combat_unit_snapshot(creature: BattlefieldCreature) -> CombatUnitSnapshot:
    return CombatUnitSnapshot(
        unit_id=creature.unit_id,
        template_id=getattr(creature, "template_id", None),
        name=creature.name,
        cost=creature.cost,
        aw=creature.aw,
        vw=creature.vw,
        current_hp=creature.current_hp,
        element=creature.element,
        abilities=creature.abilities,
        rules_text=getattr(creature, "rules_text", ""),
        tapped=creature.tapped,
    )


def start_dice_battle(self, attacker_id: int, blocker_id: int) -> None:
    attacker = self.get_unit_by_id(attacker_id)
    blocker = self.get_unit_by_id(blocker_id)
    attacker_owner = self.get_unit_owner(attacker_id)
    blocker_owner = self.get_unit_owner(blocker_id)
    if attacker is None or blocker is None or attacker_owner is None or blocker_owner is None:
        return
    strategy = self.ai.choose_die_strategy()
    self.combat_id_counter += 1
    if self.statistics is not None:
        self.statistics.start_creature_combat(
            combat_id=self.combat_id_counter,
            attacker_owner=attacker_owner.player_id,
            blocker_owner=blocker_owner.player_id,
            attacker_creature_name=attacker.name,
            blocker_creature_name=blocker.name,
            attacker_aw=attacker.aw,
            attacker_vw=attacker.vw,
            blocker_aw=blocker.aw,
            blocker_vw=blocker.vw,
            attacker_hp_before=attacker.current_hp,
            blocker_hp_before=blocker.current_hp,
        )
    self.pending_dice_battle = PendingDiceBattle(
        attacker_id=attacker_id,
        blocker_id=blocker_id,
        attacker_owner=attacker_owner.player_id,
        blocker_owner=blocker_owner.player_id,
        attacker_dice=[DieResult(self.rng.randint(1, 20), attacker.aw) for _ in range(attacker.aw)],
        blocker_dice=[DieResult(self.rng.randint(1, 20), blocker.aw) for _ in range(blocker.vw)],
        attacker_snapshot=make_combat_unit_snapshot(attacker),
        blocker_snapshot=make_combat_unit_snapshot(blocker),
        ai_strategy_name=strategy.name,
        ai_choose_die=lambda dice, strategy=strategy: strategy.choose(dice, self.rng),
    )
    self.log(f"WÃ¼rfelkampf startet: {attacker.name} gegen {blocker.name}.")


def choose_human_die(self, visible_index: int) -> None:
    battle = self.pending_dice_battle
    if battle is None or battle.resolution_complete:
        return
    human_is_attacker = battle.attacker_owner == self.human_player.player_id
    human_dice = battle.attacker_dice if human_is_attacker else battle.blocker_dice
    enemy_dice = battle.blocker_dice if human_is_attacker else battle.attacker_dice
    available_human_dice = [die for die in human_dice if not die.used]
    available_enemy_dice = [die for die in enemy_dice if not die.used]
    if not available_human_dice or not available_enemy_dice:
        return
    if visible_index < 0 or visible_index >= len(available_human_dice):
        return

    chosen_human_die = available_human_dice[visible_index]
    chosen_enemy_die = battle.ai_choose_die(available_enemy_dice)
    chosen_human_die.used = True
    chosen_enemy_die.used = True

    if human_is_attacker:
        comparison = PendingComparison(
            attacker_die=chosen_human_die,
            blocker_die=chosen_enemy_die,
            human_is_attacker=True,
        )
    else:
        comparison = PendingComparison(
            attacker_die=chosen_enemy_die,
            blocker_die=chosen_human_die,
            human_is_attacker=False,
        )
    battle.pending_comparison = comparison
    self.apply_ai_adaptation_if_needed(battle, comparison)
    if self.human_can_use_adaptation(battle, comparison):
        comparison.human_can_adapt = True
        self.log("Anpassung verfÃ¼gbar. Entscheide Ã¼ber Neu WÃ¼rfeln oder AuflÃ¶sen.")
        return
    self.resolve_pending_comparison(use_human_adaptation=False)


def human_can_use_adaptation(self, battle: PendingDiceBattle, comparison: PendingComparison) -> bool:
    human_unit = self.get_human_combat_creature(battle)
    if human_unit is None or not human_unit.has_ability(Ability.ADAPTATION):
        return False
    if comparison.human_is_attacker and battle.attacker_used_adaptation:
        return False
    if not comparison.human_is_attacker and battle.blocker_used_adaptation:
        return False
    return (
        comparison.attacker_die.total <= comparison.blocker_die.total
        if comparison.human_is_attacker
        else comparison.blocker_die.total <= comparison.attacker_die.total
    )


def get_human_combat_creature(self, battle: PendingDiceBattle) -> Optional[BattlefieldCreature]:
    if battle.attacker_owner == self.human_player.player_id:
        return self.get_unit_by_id(battle.attacker_id)
    return self.get_unit_by_id(battle.blocker_id)


def apply_ai_adaptation_if_needed(self, battle: PendingDiceBattle, comparison: PendingComparison) -> None:
    ai_is_attacker = battle.attacker_owner != self.human_player.player_id
    ai_unit = self.get_unit_by_id(battle.attacker_id if ai_is_attacker else battle.blocker_id)
    if ai_unit is None or not ai_unit.has_ability(Ability.ADAPTATION):
        return
    if ai_is_attacker and battle.attacker_used_adaptation:
        return
    if not ai_is_attacker and battle.blocker_used_adaptation:
        return

    own_die = comparison.attacker_die if ai_is_attacker else comparison.blocker_die
    enemy_die = comparison.blocker_die if ai_is_attacker else comparison.attacker_die
    own_loses = own_die.total < enemy_die.total
    tie = own_die.total == enemy_die.total
    would_take_damage = own_loses or tie
    would_be_destroyed = ai_unit.current_hp <= (0 if ai_unit.has_ability(Ability.STEADFAST) and tie else 1)
    if not self.ai.should_use_adaptation(ai_unit, own_die, enemy_die, would_take_damage, would_be_destroyed, tie):
        return

    own_die.base_roll = self.rng.randint(1, 20)
    if ai_is_attacker:
        battle.attacker_used_adaptation = True
        self.log(f"{ai_unit.name} nutzt Anpassung.")
    else:
        battle.blocker_used_adaptation = True
        self.log(f"{ai_unit.name} nutzt Anpassung.")


def resolve_pending_comparison(self, use_human_adaptation: bool) -> None:
    battle = self.pending_dice_battle
    if battle is None or battle.pending_comparison is None:
        return
    comparison = battle.pending_comparison
    if use_human_adaptation and comparison.human_can_adapt:
        if comparison.human_is_attacker:
            comparison.attacker_die.base_roll = self.rng.randint(1, 20)
            battle.attacker_used_adaptation = True
            human_unit = self.get_unit_by_id(battle.attacker_id)
        else:
            comparison.blocker_die.base_roll = self.rng.randint(1, 20)
            battle.blocker_used_adaptation = True
            human_unit = self.get_unit_by_id(battle.blocker_id)
        comparison.human_used_adaptation = True
        if human_unit is not None:
            self.log(f"{human_unit.name} nutzt Anpassung.")

    battle.pending_comparison = None
    self.apply_comparison_result(battle, comparison)


def apply_comparison_result(self, battle: PendingDiceBattle, comparison: PendingComparison) -> None:
    attacker = self.get_unit_by_id(battle.attacker_id)
    blocker = self.get_unit_by_id(battle.blocker_id)
    if attacker is None or blocker is None:
        return

    round_number = len(battle.history) + 1
    attacker_damage = 0
    blocker_damage = 0
    attacker_label = ""
    blocker_label = ""

    if comparison.attacker_die.total > comparison.blocker_die.total:
        attacker_damage = 1 + (1 if round_number == 1 and attacker.has_ability(Ability.IGNITE) else 0)
        blocker.current_hp -= attacker_damage
        self.queue_creature_damage_event("blocker", attacker_damage, attacker.element)
        outcome = f"{attacker.name} gewinnt den WÃ¼rfelvergleich und verursacht {attacker_damage} Schaden."
        attacker_label = f"{comparison.attacker_die.display()} | Runde {round_number}: Gewonnen"
        blocker_label = f"{comparison.blocker_die.display()} | Runde {round_number}: Verloren"
    elif comparison.attacker_die.total < comparison.blocker_die.total:
        blocker_damage = 1 + (1 if round_number == 1 and blocker.has_ability(Ability.IGNITE) else 0)
        attacker.current_hp -= blocker_damage
        self.queue_creature_damage_event("attacker", blocker_damage, blocker.element)
        outcome = f"{blocker.name} gewinnt den WÃ¼rfelvergleich und verursacht {blocker_damage} Schaden."
        attacker_label = f"{comparison.attacker_die.display()} | Runde {round_number}: Verloren"
        blocker_label = f"{comparison.blocker_die.display()} | Runde {round_number}: Gewonnen"
    else:
        attacker_tie_damage = 0 if attacker.has_ability(Ability.STEADFAST) else 1
        blocker_tie_damage = 0 if blocker.has_ability(Ability.STEADFAST) else 1
        attacker.current_hp -= blocker_tie_damage
        blocker.current_hp -= attacker_tie_damage
        attacker_damage = attacker_tie_damage
        blocker_damage = blocker_tie_damage
        if blocker_tie_damage > 0:
            self.queue_creature_damage_event("attacker", blocker_tie_damage, blocker.element)
        if attacker_tie_damage > 0:
            self.queue_creature_damage_event("blocker", attacker_tie_damage, attacker.element)
        attacker_label = f"{comparison.attacker_die.display()} | Runde {round_number}: Gleichstand"
        blocker_label = f"{comparison.blocker_die.display()} | Runde {round_number}: Gleichstand"
        if attacker_tie_damage == 0 and blocker_tie_damage == 0:
            outcome = "Gleichstand. Keine Kreatur erleidet Schaden."
        elif attacker_tie_damage == 0:
            outcome = f"Gleichstand. {attacker.name} bleibt unerschÃ¼tterlich, {blocker.name} erleidet 1 Schaden."
        elif blocker_tie_damage == 0:
            outcome = f"Gleichstand. {blocker.name} bleibt unerschÃ¼tterlich, {attacker.name} erleidet 1 Schaden."
        else:
            outcome = "Gleichstand. Beide Kreaturen erhalten 1 Schaden."

    if self.statistics is not None:
        self.statistics.register_dice_comparison(attacker_damage=attacker_damage, blocker_damage=blocker_damage)
    comparison.attacker_die.comparison_label = attacker_label
    comparison.blocker_die.comparison_label = blocker_label
    battle.attacker_snapshot.current_hp = attacker.current_hp
    battle.blocker_snapshot.current_hp = blocker.current_hp
    human_unit = attacker if comparison.human_is_attacker else blocker
    enemy_unit = blocker if comparison.human_is_attacker else attacker
    human_result = comparison.attacker_die.display() if comparison.human_is_attacker else comparison.blocker_die.display()
    enemy_result = comparison.blocker_die.display() if comparison.human_is_attacker else comparison.attacker_die.display()
    battle.history.append(
        DiceRoundRecord(
            round_number=round_number,
            human_unit_name=human_unit.name,
            human_result=human_result,
            enemy_unit_name=enemy_unit.name,
            enemy_result=enemy_result,
            outcome_text=outcome,
        )
    )
    self.log(f"{human_unit.name}: {human_result} | {enemy_unit.name}: {enemy_result} -> {outcome}")
    self.finalize_or_continue_dice_battle(battle, attacker, blocker)


def finalize_or_continue_dice_battle(
    self,
    battle: PendingDiceBattle,
    attacker: BattlefieldCreature,
    blocker: BattlefieldCreature,
) -> None:
    attacker_hp_after = attacker.current_hp
    blocker_hp_after = blocker.current_hp
    attacker_alive = attacker.current_hp > 0
    blocker_alive = blocker.current_hp > 0
    attacker_dice_left = any(not die.used for die in battle.attacker_dice)
    blocker_dice_left = any(not die.used for die in battle.blocker_dice)

    self.cleanup_destroyed_units()
    if attacker_alive and blocker_alive and attacker_dice_left and blocker_dice_left:
        return

    self.apply_trample_if_needed(battle, attacker_alive)
    if self.statistics is not None:
        self.statistics.finish_creature_combat(
            attacker_owner=battle.attacker_owner,
            blocker_owner=battle.blocker_owner,
            attacker_creature_name=attacker.name,
            blocker_creature_name=blocker.name,
            attacker_aw=attacker.aw,
            attacker_vw=attacker.vw,
            blocker_aw=blocker.aw,
            blocker_vw=blocker.vw,
            attacker_hp_after=attacker_hp_after,
            blocker_hp_after=blocker_hp_after,
        )
    self.log(f"Gegnerische WÃ¼rfelstrategie: {battle.ai_strategy_name}.")
    battle.resolution_complete = True


def end_dice_battle(self) -> None:
    battle = self.pending_dice_battle
    if battle is None or battle.pending_comparison is not None or not battle.resolution_complete:
        return
    self.pending_dice_battle = None
    self.advance_combat_resolution()


def apply_trample_if_needed(self, battle: PendingDiceBattle, attacker_alive: bool) -> None:
    attacker = self.get_unit_by_id(battle.attacker_id)
    if attacker is None or not attacker_alive or not attacker.has_ability(Ability.TRAMPLE):
        return
    remaining_blockers_alive = any(
        self.get_unit_by_id(blocker_id) is not None
        for blocker_id in self.block_assignments.get(battle.attacker_id, [])
    )
    if remaining_blockers_alive:
        return
    remaining_attack_dice = sum(1 for die in battle.attacker_dice if not die.used)
    if remaining_attack_dice <= 0:
        return
    self.defending_player.life -= remaining_attack_dice
    self.queue_player_damage_event(
        target_player_id=self.defending_player.player_id,
        amount=remaining_attack_dice,
        source_element=attacker.element,
        attacker_id=attacker.unit_id,
    )
    if self.statistics is not None:
        self.statistics.player_stats[self.active_player.player_id].player_damage_dealt += remaining_attack_dice
    self.log(
        f"{attacker.name} verursacht {remaining_attack_dice} Trampelschaden an {self.defending_player.name}."
    )
    self.check_for_game_over()


def cleanup_destroyed_units(self) -> None:
    for player in self.players:
        destroyed = [creature for creature in player.battlefield if creature.current_hp <= 0]
        for creature in destroyed:
            template = self.templates.get(creature.template_id)
            if template is not None:
                player.discard_pile.append(CardInstance(self.make_instance_id(), template))
            self.log(f"{creature.name} wird zerstÃ¶rt und auf den Ablagestapel gelegt.")
        player.battlefield = [creature for creature in player.battlefield if creature.current_hp > 0]
