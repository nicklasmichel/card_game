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
    PHASE_DICE_BATTLE,
    ReactionContext,
    ReactionTrigger,
)


def make_combat_unit_snapshot(self, creature: BattlefieldCreature) -> CombatUnitSnapshot:
    return CombatUnitSnapshot(
        unit_id=creature.unit_id,
        template_id=getattr(creature, "template_id", None),
        name=creature.name,
        cost=creature.cost,
        aw=self.get_creature_attack_value(creature),
        vw=self.get_creature_defense_value(creature),
        current_hp=self.get_creature_current_hp(creature),
        element=creature.element,
        abilities=creature.abilities,
        rules_text=getattr(creature, "rules_text", ""),
        tapped=creature.tapped,
    )


def get_attackers_die_bonus(self) -> int:
    return 0


def get_attacker_die_bonus_sources(self, attacker: BattlefieldCreature, attacker_owner) -> list[tuple[str, int]]:
    sources: list[tuple[str, int]] = [("AW", self.get_creature_attack_value(attacker))]
    sturmformation_bonus = getattr(attacker_owner, "attackers_die_bonus_this_turn", 0)
    if sturmformation_bonus > 0:
        sources.append(("Sturmformation", sturmformation_bonus))
    return sources


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
            attacker_aw=self.get_creature_attack_value(attacker),
            attacker_vw=self.get_creature_defense_value(attacker),
            blocker_aw=self.get_creature_attack_value(blocker),
            blocker_vw=self.get_creature_defense_value(blocker),
            attacker_hp_before=self.get_creature_current_hp(attacker),
            blocker_hp_before=self.get_creature_current_hp(blocker),
        )
    self.pending_dice_battle = PendingDiceBattle(
        attacker_id=attacker_id,
        blocker_id=blocker_id,
        attacker_owner=attacker_owner.player_id,
        blocker_owner=blocker_owner.player_id,
        attacker_dice=[
            DieResult(
                self.rng.randint(1, 20),
                sum(amount for _label, amount in get_attacker_die_bonus_sources(self, attacker, attacker_owner)),
                bonus_breakdown=get_attacker_die_bonus_sources(self, attacker, attacker_owner),
            )
            for _ in range(self.get_creature_attack_value(attacker))
        ],
        blocker_dice=[
            DieResult(
                self.rng.randint(1, 20),
                self.get_creature_attack_value(blocker),
                bonus_breakdown=[("AW", self.get_creature_attack_value(blocker))],
            )
            for _ in range(self.get_creature_defense_value(blocker))
        ],
        attacker_snapshot=make_combat_unit_snapshot(self, attacker),
        blocker_snapshot=make_combat_unit_snapshot(self, blocker),
        ai_strategy_name=strategy.name,
        ai_choose_die=lambda dice, strategy=strategy: strategy.choose(dice, self.rng),
    )
    battle = self.pending_dice_battle
    self.log(f"Wuerfelkampf startet: {attacker.name} gegen {blocker.name}.")
    setattr(attacker, "owner_id", battle.attacker_owner)
    setattr(blocker, "owner_id", battle.blocker_owner)
    self.set_open_die_targets(
        [
            {
                "die": die,
                "player_id": battle.attacker_owner,
                "die_role": "attacker",
                "die_index": index,
                "source_creature_id": battle.attacker_id,
                "is_valid": lambda die=die: self.pending_dice_battle is battle and die in battle.attacker_dice and not battle.resolution_complete,
            }
            for index, die in enumerate(battle.attacker_dice)
        ]
        + [
            {
                "die": die,
                "player_id": battle.blocker_owner,
                "die_role": "blocker",
                "die_index": index,
                "source_creature_id": battle.blocker_id,
                "is_valid": lambda die=die: self.pending_dice_battle is battle and die in battle.blocker_dice and not battle.resolution_complete,
            }
            for index, die in enumerate(battle.blocker_dice)
        ]
    )
    self.begin_general_spell_window(
        trigger=ReactionTrigger.AFTER_DICE_REVEALED,
        first_responder_id=1 - self.active_player.player_id,
        resume_phase=PHASE_DICE_BATTLE,
        continuation=self.resume_dice_battle_after_roll_window,
        attacker_creature=attacker,
        blocker_creature=blocker,
    )


def resume_dice_battle_after_roll_window(self) -> None:
    self.clear_open_die_targets()


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
    attacker = self.get_unit_by_id(battle.attacker_id)
    blocker = self.get_unit_by_id(battle.blocker_id)
    if attacker is not None:
        setattr(attacker, "owner_id", battle.attacker_owner)
    if blocker is not None:
        setattr(blocker, "owner_id", battle.blocker_owner)
    self.set_open_die_targets(
        [
            {
                "die": comparison.attacker_die,
                "player_id": battle.attacker_owner,
                "die_role": "attacker",
                "die_index": battle.attacker_dice.index(comparison.attacker_die),
                "source_creature_id": battle.attacker_id,
                "is_valid": lambda die=comparison.attacker_die: (
                    self.pending_dice_battle is battle
                    and battle.pending_comparison is comparison
                    and comparison.attacker_die is die
                ),
            },
            {
                "die": comparison.blocker_die,
                "player_id": battle.blocker_owner,
                "die_role": "blocker",
                "die_index": battle.blocker_dice.index(comparison.blocker_die),
                "source_creature_id": battle.blocker_id,
                "is_valid": lambda die=comparison.blocker_die: (
                    self.pending_dice_battle is battle
                    and battle.pending_comparison is comparison
                    and comparison.blocker_die is die
                ),
            },
        ]
    )
    self.begin_general_spell_window(
        trigger=ReactionTrigger.BEFORE_DICE_COMPARISON,
        first_responder_id=1 - self.human_player.player_id if self.human_player.player_id == battle.attacker_owner else self.human_player.player_id,
        resume_phase=PHASE_DICE_BATTLE,
        continuation=self.continue_pending_comparison_after_reaction,
        attacker_die=comparison.attacker_die,
        blocker_die=comparison.blocker_die,
        attacker_creature=attacker,
        blocker_creature=blocker,
    )


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
    would_be_destroyed = self.get_creature_current_hp(ai_unit) <= 1 and would_take_damage
    if not self.ai.should_use_adaptation(ai_unit, own_die, enemy_die, would_take_damage, would_be_destroyed, tie):
        return

    own_die.base_roll = self.rng.randint(1, 20)
    if ai_is_attacker:
        battle.attacker_used_adaptation = True
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

    comparison.attacker_die.used = True
    comparison.blocker_die.used = True
    battle.pending_comparison = None
    self.apply_comparison_result(battle, comparison)


def continue_pending_comparison_after_reaction(self) -> None:
    battle = self.pending_dice_battle
    if battle is None or battle.pending_comparison is None:
        return
    self.clear_open_die_targets()
    if self.get_unit_by_id(battle.attacker_id) is None or self.get_unit_by_id(battle.blocker_id) is None:
        battle.pending_comparison = None
        battle.resolution_complete = True
        self.end_dice_battle()
        return
    comparison = battle.pending_comparison
    self.apply_ai_adaptation_if_needed(battle, comparison)
    if self.human_can_use_adaptation(battle, comparison):
        comparison.human_can_adapt = True
        self.log("Anpassung verfuegbar. Entscheide ueber Neu Wuerfeln oder Aufloesen.")
        return
    self.resolve_pending_comparison(use_human_adaptation=False)


def apply_comparison_result(self, battle: PendingDiceBattle, comparison: PendingComparison) -> None:
    attacker = self.get_unit_by_id(battle.attacker_id)
    blocker = self.get_unit_by_id(battle.blocker_id)
    if attacker is None or blocker is None:
        battle.resolution_complete = True
        self.end_dice_battle()
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
        outcome = f"{attacker.name} gewinnt den Wuerfelvergleich und verursacht {attacker_damage} Schaden."
        attacker_label = f"{comparison.attacker_die.display()} | Runde {round_number}: Gewonnen"
        blocker_label = f"{comparison.blocker_die.display()} | Runde {round_number}: Verloren"
    elif comparison.attacker_die.total < comparison.blocker_die.total:
        blocker_damage = 1
        attacker.current_hp -= blocker_damage
        self.queue_creature_damage_event("attacker", blocker_damage, blocker.element)
        outcome = f"{blocker.name} gewinnt den Wuerfelvergleich und verursacht {blocker_damage} Schaden."
        attacker_label = f"{comparison.attacker_die.display()} | Runde {round_number}: Verloren"
        blocker_label = f"{comparison.blocker_die.display()} | Runde {round_number}: Gewonnen"
    else:
        attacker.current_hp -= 1
        blocker.current_hp -= 1
        attacker_damage = 1
        blocker_damage = 1
        self.queue_creature_damage_event("attacker", 1, blocker.element)
        self.queue_creature_damage_event("blocker", 1, attacker.element)
        attacker_label = f"{comparison.attacker_die.display()} | Runde {round_number}: Gleichstand"
        blocker_label = f"{comparison.blocker_die.display()} | Runde {round_number}: Gleichstand"
        outcome = "Gleichstand. Beide Kreaturen erhalten 1 Schaden."

    if self.statistics is not None:
        self.statistics.register_dice_comparison(attacker_damage=attacker_damage, blocker_damage=blocker_damage)
    comparison.attacker_die.comparison_label = attacker_label
    comparison.blocker_die.comparison_label = blocker_label
    battle.attacker_snapshot.current_hp = self.get_creature_current_hp(attacker)
    battle.blocker_snapshot.current_hp = self.get_creature_current_hp(blocker)
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
    contexts: list[ReactionContext] = []
    if blocker_damage > 0:
        setattr(attacker, "owner_id", battle.attacker_owner)
        setattr(blocker, "owner_id", battle.blocker_owner)
        contexts.append(
            ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_DAMAGED_IN_DICE_COMPARISON,
                active_player=self.active_player,
                source_player=self.get_player_by_id(battle.attacker_owner),
                source_creature=attacker,
                opposing_creature=blocker,
                damage_amount=blocker_damage,
            )
        )
    if attacker_damage > 0:
        setattr(attacker, "owner_id", battle.attacker_owner)
        setattr(blocker, "owner_id", battle.blocker_owner)
        contexts.append(
            ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_DAMAGED_IN_DICE_COMPARISON,
                active_player=self.active_player,
                source_player=self.get_player_by_id(battle.blocker_owner),
                source_creature=blocker,
                opposing_creature=attacker,
                damage_amount=attacker_damage,
            )
        )
    destroyed = []
    if self.is_creature_destroyed(attacker):
        destroyed.append((self.get_player_by_id(battle.attacker_owner), attacker))
    if self.is_creature_destroyed(blocker):
        destroyed.append((self.get_player_by_id(battle.blocker_owner), blocker))
    for owner, creature in destroyed:
        setattr(creature, "owner_id", owner.player_id)
        contexts.append(
            ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_DESTROYED,
                active_player=self.active_player,
                source_player=owner,
                source_creature=creature,
            )
        )
    self.pending_post_comparison = (battle, attacker, blocker)
    if contexts:
        self.begin_triggered_reaction_window(
            context=contexts[0],
            first_responder_id=1 - contexts[0].source_player.player_id,
            resume_phase=PHASE_DICE_BATTLE,
            continuation=self.resume_post_comparison_resolution,
            base_stack_size=len(self.spell_stack),
        )
        return
    self.resume_post_comparison_resolution()


def resume_post_comparison_resolution(self) -> None:
    if self.pending_post_comparison is None:
        return
    battle, attacker, blocker = self.pending_post_comparison
    if self.pending_dice_battle is None:
        self.pending_post_comparison = None
        return
    self.begin_general_spell_window(
        trigger=ReactionTrigger.AFTER_DICE_COMPARISON,
        first_responder_id=self.defending_player.player_id,
        resume_phase=PHASE_DICE_BATTLE,
        continuation=self.finish_post_comparison_priority_window,
        attacker_creature=attacker,
        blocker_creature=blocker,
    )


def finish_post_comparison_priority_window(self) -> None:
    if self.pending_post_comparison is None:
        return
    battle, _attacker, _blocker = self.pending_post_comparison
    self.pending_post_comparison = None
    live_attacker = self.get_unit_by_id(battle.attacker_id)
    live_blocker = self.get_unit_by_id(battle.blocker_id)
    if live_attacker is None or live_blocker is None:
        if self.pending_dice_battle is not None:
            self.pending_dice_battle.resolution_complete = True
            self.end_dice_battle()
        return
    self.finalize_or_continue_dice_battle(battle, live_attacker, live_blocker)


def finalize_or_continue_dice_battle(
    self,
    battle: PendingDiceBattle,
    attacker: BattlefieldCreature,
    blocker: BattlefieldCreature,
) -> None:
    attacker_hp_after = self.get_creature_current_hp(attacker)
    blocker_hp_after = self.get_creature_current_hp(blocker)
    attacker_alive = not self.is_creature_destroyed(attacker)
    blocker_alive = not self.is_creature_destroyed(blocker)
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
            attacker_aw=self.get_creature_attack_value(attacker),
            attacker_vw=self.get_creature_defense_value(attacker),
            blocker_aw=self.get_creature_attack_value(blocker),
            blocker_vw=self.get_creature_defense_value(blocker),
            attacker_hp_after=attacker_hp_after,
            blocker_hp_after=blocker_hp_after,
        )
    self.log(f"Gegnerische Wuerfelstrategie: {battle.ai_strategy_name}.")
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
    self.log(f"{attacker.name} verursacht {remaining_attack_dice} Trampelschaden an {self.defending_player.name}.")
    self.check_for_game_over()


def cleanup_destroyed_units(self) -> None:
    changed = True
    while changed:
        changed = False
        for player in self.players:
            destroyed = [creature for creature in list(player.battlefield) if self.is_creature_destroyed(creature)]
            if not destroyed:
                continue
            changed = True
            for creature in destroyed:
                self.remove_creature_from_combat(creature.unit_id)
                self.creatures_died_this_turn += 1
                template = self.templates.get(creature.template_id)
                if template is not None:
                    player.discard_pile.append(CardInstance(self.make_instance_id(), template))
                self.log(f"{creature.name} wird zerstoert und auf den Ablagestapel gelegt.")
                if creature in player.battlefield:
                    player.battlefield.remove(creature)
