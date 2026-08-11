from __future__ import annotations

from typing import Iterable

from core.models import (
    Ability,
    BattlefieldCreature,
    CombatUnitSnapshot,
    DiceRoundRecord,
    PendingDiceBattle,
    PHASE_DICE_BATTLE,
)


def make_combat_unit_snapshot(self, creature: BattlefieldCreature) -> CombatUnitSnapshot:
    return CombatUnitSnapshot(
        unit_id=creature.unit_id,
        template_id=getattr(creature, "template_id", None),
        name=creature.name,
        cost=creature.cost,
        aw=self.get_creature_attack_value(creature),
        vw=self.get_creature_defense_value(creature),
        lw=self.get_creature_max_lw(creature),
        sw=self.get_creature_damage_value(creature),
        current_hp=self.get_creature_current_hp(creature),
        element=creature.element,
        abilities=creature.abilities,
        rules_text=getattr(creature, "rules_text", ""),
        tapped=creature.tapped,
    )


def apply_life_steal_healing(self, creature: BattlefieldCreature, actual_damage: int) -> int:
    if actual_damage <= 0 or creature is None or not (
        creature.has_ability(Ability.LIFE_STEAL) or creature.has_ability(Ability.LIFELINK)
    ):
        return 0
    hp_before = creature.current_hp
    creature.current_hp = min(creature.lw, creature.current_hp + actual_damage)
    healed = creature.current_hp - hp_before
    if healed > 0:
        self.log(f"{creature.name} heilt sich durch Lebensraub um {healed} Leben.")
    return healed


def start_dice_battle(self, attacker_id: int, blocker_id: int) -> None:
    battle = create_pending_dice_battle(self, attacker_id, blocker_id)
    if battle is None:
        return
    self.pending_dice_battle = battle
    self.pending_dice_battles = [battle]
    self.log(f"Wuerfelkampf startet: {battle.attacker_snapshot.name} gegen {battle.blocker_snapshot.name}.")
    self.phase = PHASE_DICE_BATTLE


def create_pending_dice_battle(self, attacker_id: int, blocker_id: int):
    attacker = self.get_unit_by_id(attacker_id)
    blocker = self.get_unit_by_id(blocker_id)
    attacker_owner = self.get_unit_owner(attacker_id)
    blocker_owner = self.get_unit_owner(blocker_id)
    if attacker is None or blocker is None or attacker_owner is None or blocker_owner is None:
        return None
    self.combat_id_counter += 1
    if self.statistics is not None:
        self.statistics.start_creature_combat(
            combat_id=self.combat_id_counter,
            attacker_owner=attacker_owner.player_id,
            blocker_owner=blocker_owner.player_id,
            attacker_creature_name=attacker.name,
            blocker_creature_name=blocker.name,
            attacker_aw=self.get_creature_attack_value(attacker),
            attacker_vw=self.get_creature_defense_value(attacker),
            blocker_aw=self.get_creature_attack_value(blocker),
            blocker_vw=self.get_creature_defense_value(blocker),
            attacker_hp_before=self.get_creature_current_hp(attacker),
            blocker_hp_before=self.get_creature_current_hp(blocker),
        )
    battle = PendingDiceBattle(
        attacker_id=attacker_id,
        blocker_id=blocker_id,
        attacker_owner=attacker_owner.player_id,
        blocker_owner=blocker_owner.player_id,
        attacker_snapshot=make_combat_unit_snapshot(self, attacker),
        blocker_snapshot=make_combat_unit_snapshot(self, blocker),
    )
    _resolve_battle_rounds(self, battle, attacker, blocker, apply_result=False)
    return battle


def _resolve_battle_rounds(
    self,
    battle: PendingDiceBattle,
    attacker: BattlefieldCreature,
    blocker: BattlefieldCreature,
    *,
    apply_result: bool,
) -> None:
    max_rounds = 1000
    if self.get_creature_attack_value(attacker) <= 0 and self.get_creature_defense_value(blocker) <= 0:
        battle.attacker_rolls = []
        battle.blocker_rolls = []
        battle.attack_sum = 0
        battle.defense_sum = 0
        battle.winner = "blocker"
        battle.creature_damage = 0
        battle.history.append(
            DiceRoundRecord(
                round_number=1,
                attacker_rolls=[],
                blocker_rolls=[],
                attack_sum=0,
                defense_sum=0,
                outcome_text="Beide Seiten haben 0 Wuerfel. Kein Kampfschaden.",
            )
        )
        battle.resolution_complete = True
        if apply_result:
            _apply_battle_result(self, battle, attacker, blocker)
        return
    while battle.reroll_count < max_rounds:
        battle.attacker_rolls = [self.rng.randint(1, 6) for _ in range(max(0, self.get_creature_attack_value(attacker)))]
        battle.blocker_rolls = [self.rng.randint(1, 6) for _ in range(max(0, self.get_creature_defense_value(blocker)))]
        battle.attack_sum = sum(battle.attacker_rolls)
        battle.defense_sum = sum(battle.blocker_rolls)
        if battle.attack_sum == battle.defense_sum:
            battle.history.append(
                DiceRoundRecord(
                    round_number=battle.reroll_count + 1,
                    attacker_rolls=list(battle.attacker_rolls),
                    blocker_rolls=list(battle.blocker_rolls),
                    attack_sum=battle.attack_sum,
                    defense_sum=battle.defense_sum,
                    outcome_text="Gleichstand - beide Seiten wuerfeln erneut.",
                )
            )
            battle.reroll_count += 1
            continue
        _finalize_battle_rolls(self, battle, attacker, blocker)
        if apply_result:
            _apply_battle_result(self, battle, attacker, blocker)
        return
    raise RuntimeError("Combat reroll guard reached unexpectedly")


def _finalize_battle_rolls(self, battle: PendingDiceBattle, attacker: BattlefieldCreature, blocker: BattlefieldCreature) -> None:
    if battle.attack_sum > battle.defense_sum:
        winner = attacker
        loser = blocker
        battle.winner = "attacker"
    else:
        winner = blocker
        loser = attacker
        battle.winner = "blocker"
    damage = self.get_creature_damage_value(winner)
    loser_hp_before_damage = self.get_creature_current_hp(loser)
    battle.creature_damage = damage
    if battle.winner == "attacker" and attacker.has_ability(Ability.TRAMPLE):
        battle.trample_damage = max(0, damage - loser_hp_before_damage)
    outcome = (
        f"{winner.name} gewinnt ({battle.attack_sum}:{battle.defense_sum}) und verursacht {damage} Schaden."
        if battle.winner == "attacker"
        else f"{winner.name} gewinnt ({battle.defense_sum}:{battle.attack_sum}) und verursacht {damage} Schaden."
    )
    if battle.trample_damage > 0:
        outcome += f" Trampelschaden: {battle.trample_damage}."
    battle.history.append(
        DiceRoundRecord(
            round_number=battle.reroll_count + 1,
            attacker_rolls=list(battle.attacker_rolls),
            blocker_rolls=list(battle.blocker_rolls),
            attack_sum=battle.attack_sum,
            defense_sum=battle.defense_sum,
            outcome_text=outcome,
        )
    )
    battle.resolution_complete = True


def _format_rolls(rolls: Iterable[int]) -> str:
    values = list(rolls)
    return f"[{', '.join(str(value) for value in values)}]" if values else "[]"


def _record_battle_post_state(self, battle: PendingDiceBattle, attacker: BattlefieldCreature, blocker: BattlefieldCreature) -> None:
    battle.attacker_hp_after = max(0, self.get_creature_current_hp(attacker))
    battle.blocker_hp_after = max(0, self.get_creature_current_hp(blocker))
    battle.attacker_snapshot.current_hp = battle.attacker_hp_after
    battle.blocker_snapshot.current_hp = battle.blocker_hp_after


def _build_battle_resolution_log(self, battle: PendingDiceBattle, damage: int) -> str:
    attacker_name = battle.attacker_snapshot.name
    blocker_name = battle.blocker_snapshot.name
    attacker_rolls = _format_rolls(battle.attacker_rolls)
    blocker_rolls = _format_rolls(battle.blocker_rolls)
    if battle.winner == "attacker":
        loser_name = blocker_name
        loser_hp = battle.blocker_hp_after
        message = (
            f"{attacker_name} wuerfelt {attacker_rolls} = {battle.attack_sum}, "
            f"{blocker_name} wuerfelt {blocker_rolls} = {battle.defense_sum}. "
            f"{attacker_name} gewinnt und fuegt {blocker_name} {damage} Schaden zu."
        )
    else:
        loser_name = attacker_name
        loser_hp = battle.attacker_hp_after
        message = (
            f"{attacker_name} wuerfelt {attacker_rolls} = {battle.attack_sum}, "
            f"{blocker_name} wuerfelt {blocker_rolls} = {battle.defense_sum}. "
            f"{blocker_name} gewinnt und fuegt {attacker_name} {damage} Schaden zu."
        )
    if battle.trample_damage > 0:
        message += f" Trampelschaden an {self.defending_player.name}: {battle.trample_damage}."
    if loser_hp > 0:
        message += f" {loser_name} bleibt bei {loser_hp} Leben."
    else:
        message += f" {loser_name} wird zerstoert."
    return message


def apply_prepared_dice_battle(self, battle: PendingDiceBattle, *, batched: bool = False) -> None:
    attacker = self.get_unit_by_id(battle.attacker_id)
    blocker = self.get_unit_by_id(battle.blocker_id)
    if attacker is None or blocker is None:
        return
    _apply_battle_result(self, battle, attacker, blocker, batched=batched)


def _apply_battle_result(self, battle: PendingDiceBattle, attacker: BattlefieldCreature, blocker: BattlefieldCreature, *, batched: bool = False) -> None:
    if battle.result_applied:
        return
    battle.result_applied = True
    if battle.winner == "attacker":
        winner = attacker
        loser = blocker
        target_role = "blocker"
    else:
        winner = blocker
        loser = attacker
        target_role = "attacker"
    damage = battle.creature_damage or self.get_creature_damage_value(winner)
    loser_hp_before = loser.current_hp
    actual_creature_damage = min(damage, max(0, loser_hp_before))
    loser.current_hp -= damage
    if actual_creature_damage > 0 and winner.has_ability(Ability.DEATHTOUCH):
        loser.current_hp = 0
    attacker.tapped = attacker.tapped or not (
        attacker.has_ability(Ability.VIGILANT) or attacker.has_ability(Ability.VIGILANCE)
    )
    blocker.tapped = True
    self.queue_creature_damage_event(target_role, damage, winner.element)
    if battle.winner == "attacker" and battle.trample_damage > 0:
        self.defending_player.life -= battle.trample_damage
        self.queue_player_damage_event(
            target_player_id=self.defending_player.player_id,
            amount=battle.trample_damage,
            source_element=attacker.element,
            attacker_id=attacker.unit_id,
        )
        if self.statistics is not None:
            self.statistics.register_player_damage(self.active_player.player_id, battle.trample_damage)
    apply_life_steal_healing(self, winner, actual_creature_damage + (battle.trample_damage if battle.winner == "attacker" else 0))
    if self.statistics is not None:
        if battle.winner == "attacker":
            self.statistics.register_dice_comparison(attacker_damage=damage, blocker_damage=0)
        else:
            self.statistics.register_dice_comparison(attacker_damage=0, blocker_damage=damage)
    _record_battle_post_state(self, battle, attacker, blocker)
    battle.resolution_log = _build_battle_resolution_log(self, battle, damage)
    if batched:
        return
    if battle.resolution_log:
        self.log(battle.resolution_log)
    self.cleanup_destroyed_units(log_destruction=False)
    if self.statistics is not None:
        self.statistics.finish_creature_combat(
            attacker_owner=battle.attacker_owner,
            blocker_owner=battle.blocker_owner,
            attacker_creature_name=attacker.name,
            blocker_creature_name=blocker.name,
            attacker_aw=self.get_creature_attack_value(attacker),
            attacker_vw=self.get_creature_defense_value(attacker),
            blocker_aw=self.get_creature_attack_value(blocker),
            blocker_vw=self.get_creature_defense_value(blocker),
            attacker_hp_after=battle.attacker_hp_after,
            blocker_hp_after=battle.blocker_hp_after,
        )
    self.check_for_game_over()


def end_dice_battle(self) -> None:
    battles = list(getattr(self, "pending_dice_battles", []) or ([] if self.pending_dice_battle is None else [self.pending_dice_battle]))
    if not battles or not all(battle.resolution_complete for battle in battles):
        return
    for battle in battles:
        apply_prepared_dice_battle(self, battle, batched=True)
    for battle in battles:
        if battle.resolution_log:
            self.log(battle.resolution_log)
    self.cleanup_destroyed_units(log_destruction=False)
    for battle in battles:
        if self.statistics is not None:
            self.statistics.finish_creature_combat(
                attacker_owner=battle.attacker_owner,
                blocker_owner=battle.blocker_owner,
                attacker_creature_name=battle.attacker_snapshot.name,
                blocker_creature_name=battle.blocker_snapshot.name,
                attacker_aw=battle.attacker_snapshot.aw,
                attacker_vw=battle.attacker_snapshot.vw,
                blocker_aw=battle.blocker_snapshot.aw,
                blocker_vw=battle.blocker_snapshot.vw,
                attacker_hp_after=battle.attacker_hp_after,
                blocker_hp_after=battle.blocker_hp_after,
            )
    self.check_for_game_over()
    self.pending_dice_battle = None
    self.pending_dice_battles = []
    self.advance_combat_resolution()


def cleanup_destroyed_units(self, *, log_destruction: bool = True) -> None:
    changed = True
    while changed:
        changed = False
        for player in self.players:
            destroyed = [creature for creature in list(player.battlefield) if self.is_creature_destroyed(creature)]
            if not destroyed:
                continue
            changed = True
            for creature in destroyed:
                self.destroy_creature_immediately(
                    player,
                    creature,
                    "Kampfschaden",
                    died_in_combat=True,
                    log_destruction=log_destruction,
                )
