from __future__ import annotations

from core.builder_rules import BUILDER_ABILITIES_ENABLED
from engine.combat_dice import apply_life_steal_healing, apply_prepared_dice_battle

from core.ai.builder import choose_builder_blocks
from core.game_mode import is_builder_mode
from core.models import (
    Ability,
    PendingDirectAttack,
    PHASE_BUILDER_ABILITY,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_REACTION,
    ReactionTrigger,
)


def can_creature_block_attacker(self, blocker, attacker) -> bool:
    if blocker is None or attacker is None:
        return False
    if getattr(blocker, "cannot_block", False):
        return False
    if self.get_creature_defense_value(blocker) <= 0:
        return False
    if is_builder_mode():
        if blocker.tapped:
            return False
    elif not blocker.is_ready():
        return False
    if attacker.has_ability(Ability.FLYING) and not blocker.has_ability(Ability.FLYING):
        return False
    return True


def can_creature_be_forced_to_block_attacker(self, blocker, attacker) -> bool:
    if blocker is None or attacker is None:
        return False
    if attacker.has_ability(Ability.PROVOKE) or attacker.has_ability(Ability.ENRAGED):
        return True
    if getattr(blocker, "cannot_block", False):
        return False
    if is_builder_mode():
        if blocker.tapped:
            return False
    elif not blocker.is_ready():
        return False
    if attacker.has_ability(Ability.FLYING) and not blocker.has_ability(Ability.FLYING):
        return False
    return True


def get_legal_enraged_targets(self, attacker) -> list:
    if attacker is None or not (attacker.has_ability(Ability.ENRAGED) or attacker.has_ability(Ability.PROVOKE)):
        return []
    used_blockers = {blocker_id for blocker_id in self.block_assignments.values() if blocker_id is not None}
    legal_targets = []
    for blocker in self.defending_player.battlefield:
        if blocker.unit_id in used_blockers:
            continue
        if self.can_creature_be_forced_to_block_attacker(blocker, attacker):
            legal_targets.append(blocker)
    return legal_targets


def set_enraged_block_assignment(self, attacker_id: int, blocker_id: int | None) -> bool:
    attacker = self.get_unit_by_id(attacker_id)
    if attacker is None or attacker_id not in self.block_assignments or not (
        attacker.has_ability(Ability.ENRAGED) or attacker.has_ability(Ability.PROVOKE)
    ):
        return False
    if blocker_id is None:
        old_blocker_id = self.block_assignments.get(attacker_id)
        self.block_assignments[attacker_id] = None
        self.enraged_forced_attackers.discard(attacker_id)
        if old_blocker_id is not None:
            old_blocker = self.get_unit_by_id(old_blocker_id)
            if old_blocker is not None:
                self.log(f"{old_blocker.name} no longer blocks {attacker.name} by force.")
        return True
    blocker = self.get_unit_by_id(blocker_id)
    if blocker is None:
        return False
    if any(
        assigned_blocker_id == blocker.unit_id and existing_attacker_id != attacker.unit_id
        for existing_attacker_id, assigned_blocker_id in self.block_assignments.items()
    ):
        return False
    if not self.can_creature_be_forced_to_block_attacker(blocker, attacker):
        return False
    self.block_assignments[attacker_id] = blocker.unit_id
    self.enraged_forced_attackers.add(attacker_id)
    return True


def ai_assign_enraged_blocks(self) -> None:
    attackers = [
        attacker
        for attacker in (self.get_unit_by_id(attacker_id) for attacker_id in self.block_assignments)
        if attacker is not None and (attacker.has_ability(Ability.ENRAGED) or attacker.has_ability(Ability.PROVOKE))
    ]
    for attacker in attackers:
        blocker = self.ai.choose_enraged_block_target(attacker, self.get_legal_enraged_targets(attacker), self)
        if blocker is None:
            continue
        if self.set_enraged_block_assignment(attacker.unit_id, blocker.unit_id):
            self.log(f"{attacker.name} forces {blocker.name} to block.")


def begin_attack_declaration(self) -> None:
    if self.phase != PHASE_MAIN_1 and not (is_builder_mode() and self.phase == PHASE_BUILDER_ABILITY):
        return
    available_attackers = self.available_attackers(self.active_player)
    if not available_attackers:
        self.log("No creatures can attack." if is_builder_mode() else "Keine Kreaturen koennen angreifen.")
        return
    self.phase = PHASE_DECLARE_ATTACKERS
    self.selected_attackers = []
    self.log("Choose your attackers." if is_builder_mode() else "Waehle deine Angreifer.")


def toggle_attacker(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_ATTACKERS or not self.active_player.is_human:
        return
    creature = self.get_unit_by_id(creature_id)
    if creature is None or self.get_unit_owner(creature_id) != self.active_player:
        return
    if not creature.is_ready():
        self.log("This creature cannot attack.")
        return
    if creature_id in self.selected_attackers:
        self.selected_attackers.remove(creature_id)
        return
    self.selected_attackers.append(creature_id)


def confirm_attackers(self) -> None:
    if self.phase != PHASE_DECLARE_ATTACKERS:
        return
    attackers = [
        creature
        for creature in (self.get_unit_by_id(creature_id) for creature_id in self.selected_attackers)
        if creature is not None and creature.is_ready()
    ]
    deduped_ids: list[int] = []
    for attacker in attackers:
        if attacker.unit_id not in deduped_ids:
            deduped_ids.append(attacker.unit_id)
    attackers = [self.get_unit_by_id(attacker_id) for attacker_id in deduped_ids]
    attackers = [attacker for attacker in attackers if attacker is not None]
    self.selected_attackers = [attacker.unit_id for attacker in attackers]
    if self.statistics is not None:
        self.statistics.register_attackers(self.active_player.player_id, len(attackers))
    if not attackers:
        self.log("No attackers selected." if is_builder_mode() else "Keine Angreifer gewaehlt.")
        self.attack_declared_this_turn = False
        self.enter_second_main_phase()
        return
    self.attack_declared_this_turn = True
    if getattr(self.active_player, "summoner_key", "") == "air" and not self.active_player.summoner_passive_draw_used_this_turn and len(attackers) >= 3:
        self.active_player.summoner_passive_draw_used_this_turn = True
        drawn = self.draw_card_for_player(self.active_player, "Beschwoerer-Passiv")
        if drawn is not None:
            self.log(f"{self.active_player.name} zieht 1 Karte durch den Beschwoerer.")
        elif self.phase != PHASE_GAME_OVER:
            self.log("Es kann keine Karte durch den Beschwoerer gezogen werden.")
        if self.phase == PHASE_GAME_OVER:
            return
    for attacker in attackers:
        if getattr(attacker, "draw_on_attack", 0) <= 0:
            continue
        for _ in range(attacker.draw_on_attack):
            drawn = self.draw_card_for_player(self.active_player, attacker.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return
        self.log(f"{attacker.name} laesst {self.active_player.name} beim Angriff {attacker.draw_on_attack} Karte(n) ziehen.")
    self.block_assignments = {attacker.unit_id: None for attacker in attackers}
    self.enraged_forced_attackers = set()
    self.selected_attack_target_id = None
    self.advance_after_attackers_declared()


def advance_after_attackers_declared(self) -> None:
    if not self.defending_player.is_human:
        self.phase = PHASE_DECLARE_BLOCKERS
        self.selected_blocker_id = None
        if self.active_player.is_human and (not is_builder_mode() or BUILDER_ABILITIES_ENABLED):
            self.log("Optional: choose forced blockers for Provoke attackers, then continue.")
            return
        self.ai_assign_enraged_blocks()
        if not self.available_blockers(self.defending_player):
            self.log("Enemy has no creatures to block. Damage goes through automatically.")
            self.begin_pre_first_combat_window()
            return
        self.log("Enemy is choosing blockers.")
        self.ai_assign_blocks()
        self.finish_block_assignment()
        return
    if self.defending_player.is_human:
        self.ai_assign_enraged_blocks()
        if not self.available_blockers(self.defending_player):
            self.log("No creatures can block. Damage goes through automatically.")
            self.begin_pre_first_combat_window()
            return
        self.phase = PHASE_DECLARE_BLOCKERS
        self.selected_blocker_id = None
        self.log("Choose at most one blocker for each attacker.")
        return


def toggle_blocker_assignment(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS or not self.defending_player.is_human:
        return
    blocker = self.get_unit_by_id(creature_id)
    if blocker is None or self.get_unit_owner(creature_id) != self.defending_player:
        return
    if is_builder_mode():
        if blocker.tapped:
            self.log("This creature cannot block.")
            return
    elif not blocker.is_ready():
        self.log("This creature cannot block.")
        return
    if self.selected_blocker_id == creature_id:
        self.selected_blocker_id = None
        return
    if self.selected_blocker_id is None:
        self.selected_blocker_id = creature_id
        self.log(f"{blocker.name} selected as blocker. Choose an attacker.")
        return
    self.selected_blocker_id = creature_id
    self.log(f"{blocker.name} selected as blocker. Choose an attacker.")


def toggle_selected_attack_target(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    if self.defending_player.is_human:
        if creature_id not in self.block_assignments:
            return
        attacker = self.get_unit_by_id(creature_id)
        blocker = self.get_unit_by_id(self.selected_blocker_id or -1)
        if attacker is None:
            return
        if attacker.unit_id in self.enraged_forced_attackers:
            self.log(f"{attacker.name} already has a forced blocker.")
            return
        if blocker is None:
            currently_assigned = self.block_assignments.get(creature_id)
            if currently_assigned is not None and attacker.unit_id not in self.enraged_forced_attackers:
                old_blocker = self.get_unit_by_id(currently_assigned)
                self.block_assignments[creature_id] = None
                if old_blocker is not None:
                    self.log(f"{old_blocker.name} no longer blocks {attacker.name}.")
            else:
                self.log("Choose a blocker first.")
            return
        if not self.can_creature_block_attacker(blocker, attacker):
            self.log(f"{blocker.name} cannot block {attacker.name}.")
            return
        if any(
            assigned_blocker_id == blocker.unit_id and existing_attacker_id != attacker.unit_id
            for existing_attacker_id, assigned_blocker_id in self.block_assignments.items()
        ):
            self.log(f"{blocker.name} already blocks another attacker.")
            return
        old_blocker_id = self.block_assignments.get(attacker.unit_id)
        if old_blocker_id == blocker.unit_id:
            self.block_assignments[attacker.unit_id] = None
            self.log(f"{blocker.name} no longer blocks {attacker.name}.")
            return
        self.block_assignments[attacker.unit_id] = blocker.unit_id
        self.selected_blocker_id = None
        self.log(f"{blocker.name} blocks {attacker.name}.")
        return
    if not self.active_player.is_human:
        return
    attacker = self.get_unit_by_id(self.selected_attack_target_id or -1)
    blocker = self.get_unit_by_id(creature_id)
    if attacker is None:
        self.log("Choose a Provoke attacker first.")
        return
    if blocker is None or self.get_unit_owner(blocker.unit_id) != self.defending_player:
        return
    if attacker.unit_id not in self.block_assignments or not (
        attacker.has_ability(Ability.ENRAGED) or attacker.has_ability(Ability.PROVOKE)
    ):
        return
    current_blocker_id = self.block_assignments.get(attacker.unit_id)
    if current_blocker_id == blocker.unit_id and attacker.unit_id in self.enraged_forced_attackers:
        self.set_enraged_block_assignment(attacker.unit_id, None)
        return
    if not self.set_enraged_block_assignment(attacker.unit_id, blocker.unit_id):
        self.log(f"{blocker.name} cannot be forced to block {attacker.name}.")
        return
    self.log(f"{attacker.name} forces {blocker.name} to block.")


def clear_block_assignments(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    self.block_assignments = {attacker_id: None for attacker_id in self.block_assignments}
    self.selected_blocker_id = None
    self.selected_attack_target_id = None
    self.enraged_forced_attackers = set()
    self.log("All block assignments were cleared.")


def finish_block_assignment(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    if not self.defending_player.is_human and self.active_player.is_human:
        self.ai_assign_blocks()
    if self.statistics is not None:
        for blocker_id in self.block_assignments.values():
            self.statistics.register_block_assignment(1 if blocker_id is not None else 0)
    self.begin_pre_first_combat_window()


def begin_pre_first_combat_window(self) -> None:
    if is_builder_mode():
        self.begin_combat_resolution()
        return
    self.begin_general_spell_window(
        trigger=ReactionTrigger.COMBAT_START,
        first_responder_id=self.active_player.player_id,
        resume_phase=PHASE_REACTION,
        continuation=self.begin_combat_resolution,
    )


def begin_post_combat_window(self) -> None:
    self.selected_attackers.clear()
    self.selected_blocker_id = None
    self.selected_attack_target_id = None
    if is_builder_mode():
        self.enter_second_main_phase()
        return
    self.begin_general_spell_window(
        trigger=ReactionTrigger.COMBAT_END,
        first_responder_id=self.active_player.player_id,
        resume_phase=PHASE_REACTION,
        continuation=self.enter_second_main_phase,
    )


def ai_assign_blocks(self) -> None:
    attackers = [
        attacker
        for attacker in (self.get_unit_by_id(attacker_id) for attacker_id in self.block_assignments)
        if attacker is not None
    ]
    available_blockers = self.available_blockers(self.defending_player)
    if is_builder_mode():
        assignments = choose_builder_blocks(self.defending_player, self)
    else:
        assignments = self.ai.choose_blockers_for_attackers(attackers, available_blockers, self.block_assignments)
    for attacker_id, blocker_id in assignments.items():
        if attacker_id in self.enraged_forced_attackers:
            continue
        attacker = self.get_unit_by_id(attacker_id)
        blocker = self.get_unit_by_id(blocker_id) if blocker_id is not None else None
        if attacker is None or blocker is None:
            continue
        if not self.can_creature_block_attacker(blocker, attacker):
            continue
        if blocker.unit_id in [assigned for assigned in self.block_assignments.values() if assigned is not None]:
            continue
        self.block_assignments[attacker_id] = blocker_id
        self.log(f"{self.defending_player.name} blocks {attacker.name} with {blocker.name}.")


def begin_combat_resolution(self) -> None:
    attacker_ids = set(self.block_assignments.keys())
    ordered_attackers = [
        creature.unit_id
        for creature in self.active_player.battlefield
        if creature.unit_id in attacker_ids
    ]
    if ordered_attackers:
        self.attack_declared_this_turn = True
    self.combat_happened_this_sequence = bool(ordered_attackers)
    self.combat_queue = ordered_attackers
    self.blocked_attackers = {
        attacker_id for attacker_id, blocker_id in self.block_assignments.items() if blocker_id is not None
    }
    self.current_attack_index = 0
    self.pending_dice_battle = None
    self.pending_dice_battles = []
    self.pending_direct_attack = None
    self.pending_direct_attacks = []
    for attacker_id in ordered_attackers:
        attacker = self.get_unit_by_id(attacker_id)
        if attacker is None or self.is_creature_destroyed(attacker):
            continue
        blocker_id = self.block_assignments.get(attacker_id)
        if blocker_id is None:
            if attacker_id in self.blocked_attackers:
                continue
            self.pending_direct_attacks.append(
                PendingDirectAttack(
                    attacker_id=attacker.unit_id,
                    attacker_owner=self.active_player.player_id,
                    defending_player_id=self.defending_player.player_id,
                    base_damage=self.get_creature_damage_value(attacker),
                )
            )
            continue
        blocker = self.get_unit_by_id(blocker_id)
        if blocker is None or self.is_creature_destroyed(blocker):
            self.block_assignments[attacker_id] = None
            self.pending_direct_attacks.append(
                PendingDirectAttack(
                    attacker_id=attacker.unit_id,
                    attacker_owner=self.active_player.player_id,
                    defending_player_id=self.defending_player.player_id,
                    base_damage=self.get_creature_damage_value(attacker),
                )
            )
            continue
        battle = self.create_pending_dice_battle(attacker_id, blocker_id)
        if battle is not None:
            self.pending_dice_battles.append(battle)
    self.current_attack_index = len(self.combat_queue)
    if self.pending_dice_battles:
        self.pending_dice_battle = self.pending_dice_battles[0]
        if len(self.pending_dice_battles) == 1:
            apply_prepared_dice_battle(self, self.pending_dice_battle)
        else:
            for battle in self.pending_dice_battles:
                apply_prepared_dice_battle(self, battle, batched=True)
            self.cleanup_destroyed_units(log_destruction=not is_builder_mode())
        self.phase = PHASE_DICE_BATTLE
        return
    self.advance_combat_resolution()


def begin_next_pending_direct_attack(self) -> bool:
    if self.pending_direct_attack is not None:
        self._apply_pending_direct_attack(self.pending_direct_attack)
        self.pending_direct_attack = None
        return self.phase == PHASE_GAME_OVER
    while self.pending_direct_attacks:
        pending = self.pending_direct_attacks.pop(0)
        attacker = self.get_unit_by_id(pending.attacker_id)
        if attacker is None or self.get_unit_owner(attacker.unit_id) != self.active_player:
            continue
        self._apply_pending_direct_attack(pending)
        if self.phase == PHASE_GAME_OVER:
            return True
    return False


def advance_combat_resolution(self) -> None:
    while self.phase != PHASE_GAME_OVER:
        if self.pending_dice_battle is not None:
            self.phase = PHASE_DICE_BATTLE
            return
        if self.pending_direct_attack is not None:
            return
        if self.current_attack_index >= len(self.combat_queue):
            if self.begin_next_pending_direct_attack():
                return
            if getattr(self, "combat_happened_this_sequence", False):
                self.begin_post_combat_window()
            else:
                self.enter_second_main_phase()
            return
        attacker_id = self.combat_queue[self.current_attack_index]
        attacker = self.get_unit_by_id(attacker_id)
        if attacker is None or self.is_creature_destroyed(attacker):
            self.current_attack_index += 1
            continue
        blocker_id = self.block_assignments.get(attacker_id)
        if blocker_id is None:
            if attacker_id in self.blocked_attackers:
                self.log(f"{attacker.name} remains blocked and deals no direct damage.")
                self.current_attack_index += 1
                continue
            self.pending_direct_attacks.append(
                PendingDirectAttack(
                    attacker_id=attacker.unit_id,
                    attacker_owner=self.active_player.player_id,
                    defending_player_id=self.defending_player.player_id,
                    base_damage=self.get_creature_damage_value(attacker),
                )
            )
            self.current_attack_index += 1
            continue
        blocker = self.get_unit_by_id(blocker_id)
        if blocker is None or self.is_creature_destroyed(blocker):
            self.block_assignments[attacker_id] = None
            continue
        self.start_dice_battle(attacker_id, blocker_id)
        if self.pending_dice_battle is not None:
            self.phase = PHASE_DICE_BATTLE
            return


def resolve_pending_direct_attack_after_reaction(self) -> None:
    pending = self.pending_direct_attack
    if pending is None:
        self.advance_combat_resolution()
        return
    self.pending_direct_attack = None
    self._apply_pending_direct_attack(pending)
    if self.phase == PHASE_GAME_OVER:
        return
    self.current_attack_index += 1
    self.advance_combat_resolution()


def _apply_pending_direct_attack(self, pending) -> None:
    attacker = self.get_unit_by_id(pending.attacker_id)
    if attacker is None or self.get_unit_owner(attacker.unit_id) != self.active_player:
        return
    damage = self.get_creature_damage_value(attacker)
    if not (attacker.has_ability(Ability.VIGILANT) or attacker.has_ability(Ability.VIGILANCE)):
        attacker.tapped = True
    self.defending_player.life -= damage
    self.queue_player_damage_event(
        target_player_id=self.defending_player.player_id,
        amount=damage,
        source_element=attacker.element,
        attacker_id=attacker.unit_id,
    )
    if self.statistics is not None:
        self.statistics.register_unblocked_attack(self.active_player.player_id, damage)
    self.log(f"{attacker.name} is unblocked and deals {damage} damage to {self.defending_player.name}.")
    apply_life_steal_healing(self, attacker, damage)
    self.handle_creature_player_damage_triggers(self.active_player, attacker, damage)
    self.check_for_game_over()
