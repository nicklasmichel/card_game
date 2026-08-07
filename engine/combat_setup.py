from __future__ import annotations

from core.models import (
    Ability,
    PendingDirectAttack,
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
    if not blocker.is_ready():
        return False
    if attacker.has_ability(Ability.FLYING) and not blocker.has_ability(Ability.FLYING):
        return False
    return True


def begin_attack_declaration(self) -> None:
    if self.phase != PHASE_MAIN_1:
        return
    available_attackers = self.available_attackers(self.active_player)
    if not available_attackers:
        self.log("Keine Kreaturen koennen angreifen.")
        return
    self.phase = PHASE_DECLARE_ATTACKERS
    self.selected_attackers = [creature.unit_id for creature in self.get_mandatory_attackers(self.active_player)]
    if self.selected_attackers:
        names = ", ".join(
            creature.name
            for creature in (self.get_unit_by_id(creature_id) for creature_id in self.selected_attackers)
            if creature is not None
        )
        self.log(f"Diese Kreaturen muessen angreifen: {names}.")
    self.log("Waehle deine Angreifer.")


def toggle_attacker(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_ATTACKERS or not self.active_player.is_human:
        return
    creature = self.get_unit_by_id(creature_id)
    if creature is None or self.get_unit_owner(creature_id) != self.active_player:
        return
    if not creature.is_ready():
        self.log("Diese Kreatur kann nicht angreifen.")
        return
    if creature_id in self.selected_attackers:
        if getattr(creature, "must_attack_each_turn", False):
            self.log(f"{creature.name} muss in diesem Zug angreifen.")
            return
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
    mandatory_ids = {creature.unit_id for creature in self.get_mandatory_attackers(self.active_player)}
    for attacker_id in mandatory_ids:
        if attacker_id not in self.selected_attackers:
            attacker = self.get_unit_by_id(attacker_id)
            if attacker is not None and attacker.is_ready():
                attackers.append(attacker)
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
        self.log("Keine Angreifer gewaehlt.")
        self.enter_second_main_phase()
        return
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
    self.advance_after_attackers_declared()


def advance_after_attackers_declared(self) -> None:
    if self.defending_player.is_human:
        if not self.available_blockers(self.defending_player):
            self.log("Keine Kreaturen koennen blocken. Schaden geht automatisch durch.")
            self.begin_pre_first_combat_window()
            return
        self.phase = PHASE_DECLARE_BLOCKERS
        self.selected_blocker_id = None
        self.log("Waehle fuer jeden Angreifer hoechstens einen Blocker.")
        return
    if not self.available_blockers(self.defending_player):
        self.log("Gegner hat keine Kreaturen zum Blocken. Schaden geht automatisch durch.")
        self.begin_pre_first_combat_window()
        return
    self.phase = PHASE_DECLARE_BLOCKERS
    self.selected_blocker_id = None
    self.log("Gegner ueberlegt seine Blocker.")


def toggle_blocker_assignment(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS or not self.defending_player.is_human:
        return
    blocker = self.get_unit_by_id(creature_id)
    if blocker is None or self.get_unit_owner(creature_id) != self.defending_player:
        return
    if not blocker.is_ready():
        self.log("Diese Kreatur kann nicht blocken.")
        return
    if self.selected_blocker_id == creature_id:
        self.selected_blocker_id = None
        return
    if self.selected_blocker_id is None:
        self.selected_blocker_id = creature_id
        self.log(f"{blocker.name} als Blocker ausgewaehlt. Waehle jetzt einen Angreifer.")
        return
    self.selected_blocker_id = creature_id
    self.log(f"{blocker.name} als Blocker ausgewaehlt. Waehle jetzt einen Angreifer.")


def toggle_selected_attack_target(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS or not self.defending_player.is_human:
        return
    if creature_id not in self.block_assignments:
        return
    attacker = self.get_unit_by_id(creature_id)
    blocker = self.get_unit_by_id(self.selected_blocker_id or -1)
    if attacker is None:
        return
    if blocker is None:
        currently_assigned = self.block_assignments.get(creature_id)
        if currently_assigned is not None:
            old_blocker = self.get_unit_by_id(currently_assigned)
            self.block_assignments[creature_id] = None
            if old_blocker is not None:
                self.log(f"{old_blocker.name} blockt {attacker.name} nicht mehr.")
        else:
            self.log("Waehle zuerst einen Blocker aus.")
        return
    if not self.can_creature_block_attacker(blocker, attacker):
        self.log(f"{blocker.name} kann {attacker.name} nicht blocken.")
        return
    if any(
        assigned_blocker_id == blocker.unit_id and existing_attacker_id != attacker.unit_id
        for existing_attacker_id, assigned_blocker_id in self.block_assignments.items()
    ):
        self.log(f"{blocker.name} blockt bereits einen anderen Angreifer.")
        return
    old_blocker_id = self.block_assignments.get(attacker.unit_id)
    if old_blocker_id == blocker.unit_id:
        self.block_assignments[attacker.unit_id] = None
        self.log(f"{blocker.name} blockt {attacker.name} nicht mehr.")
        return
    self.block_assignments[attacker.unit_id] = blocker.unit_id
    self.selected_blocker_id = None
    self.log(f"{blocker.name} blockt {attacker.name}.")


def clear_block_assignments(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    self.block_assignments = {attacker_id: None for attacker_id in self.block_assignments}
    self.selected_blocker_id = None
    self.log("Alle Blockzuweisungen wurden geloescht.")


def finish_block_assignment(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    if self.statistics is not None:
        for blocker_id in self.block_assignments.values():
            self.statistics.register_block_assignment(1 if blocker_id is not None else 0)
    self.begin_pre_first_combat_window()


def begin_pre_first_combat_window(self) -> None:
    self.begin_general_spell_window(
        trigger=ReactionTrigger.COMBAT_START,
        first_responder_id=self.active_player.player_id,
        resume_phase=PHASE_REACTION,
        continuation=self.begin_combat_resolution,
    )


def begin_post_combat_window(self) -> None:
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
    assignments = self.ai.choose_blockers_for_attackers(attackers, available_blockers, self.block_assignments)
    for attacker_id, blocker_id in assignments.items():
        attacker = self.get_unit_by_id(attacker_id)
        blocker = self.get_unit_by_id(blocker_id) if blocker_id is not None else None
        if attacker is None or blocker is None:
            continue
        if not self.can_creature_block_attacker(blocker, attacker):
            continue
        if blocker.unit_id in [assigned for assigned in self.block_assignments.values() if assigned is not None]:
            continue
        self.block_assignments[attacker_id] = blocker_id
        self.log(f"{self.defending_player.name} blockt {attacker.name} mit {blocker.name}.")


def begin_combat_resolution(self) -> None:
    attacker_ids = set(self.block_assignments.keys())
    ordered_attackers = [
        creature.unit_id
        for creature in self.active_player.battlefield
        if creature.unit_id in attacker_ids
    ]
    self.combat_happened_this_sequence = bool(ordered_attackers)
    self.combat_queue = ordered_attackers
    self.blocked_attackers = {
        attacker_id for attacker_id, blocker_id in self.block_assignments.items() if blocker_id is not None
    }
    self.current_attack_index = 0
    self.pending_dice_battle = None
    self.pending_direct_attack = None
    self.pending_direct_attacks = []
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
                self.log(f"{attacker.name} bleibt geblockt und verursacht keinen direkten Schaden.")
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
    self.log(f"{attacker.name} ist ungeblockt und verursacht {damage} Schaden an {self.defending_player.name}.")
    self.handle_creature_player_damage_triggers(self.active_player, attacker, damage)
    self.check_for_game_over()
