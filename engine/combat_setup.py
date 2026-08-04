from __future__ import annotations

from core.models import (
    Ability,
    PendingBlockOrder,
    PendingDirectAttack,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_ORDER_BLOCKERS,
    PHASE_SUMMONING,
    PHASE_REACTION,
    ReactionContext,
    ReactionTrigger,
)


def can_creature_block_attacker(self, blocker, attacker) -> bool:
    if blocker is None or attacker is None:
        return False
    if getattr(blocker, "cannot_block", False):
        return False
    if attacker.has_ability(Ability.FLYING) and not blocker.has_ability(Ability.FLYING):
        return False
    return True


def begin_attack_declaration(self) -> None:
    if self.phase != PHASE_SUMMONING:
        return
    available_attackers = self.available_attackers(self.active_player)
    if not available_attackers:
        self.log("Keine Kreaturen koennen angreifen. Kampfphase endet automatisch.")
        self.end_turn()
        return
    self.phase = PHASE_DECLARE_ATTACKERS
    self.selected_attackers = [creature.unit_id for creature in self.get_mandatory_attackers(self.active_player)]
    self.selected_provoke_attacker_id = None
    self.provoke_assignments.clear()
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
        if self.selected_provoke_attacker_id == creature_id:
            self.selected_provoke_attacker_id = None
        self.provoke_assignments.pop(creature_id, None)
        return
    self.selected_attackers.append(creature_id)
    if creature.has_ability(Ability.PROVOKE):
        self.selected_provoke_attacker_id = creature_id


def toggle_provoke_target(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_ATTACKERS or not self.active_player.is_human:
        return
    attacker_id = self.selected_provoke_attacker_id
    if attacker_id is None or attacker_id not in self.selected_attackers:
        self.log("Waehle zuerst einen eigenen Angreifer mit Provozieren aus.")
        return
    attacker = self.get_unit_by_id(attacker_id)
    target = self.get_unit_by_id(creature_id)
    if attacker is None or target is None or self.get_unit_owner(creature_id) != self.defending_player:
        return
    if not attacker.has_ability(Ability.PROVOKE):
        return
    if not self.can_creature_block_attacker(target, attacker):
        self.log(f"{target.name} kann {attacker.name} nicht blocken.")
        return
    if self.provoke_assignments.get(attacker_id) == creature_id:
        del self.provoke_assignments[attacker_id]
        self.log(f"{attacker.name} provoziert {target.name} nicht mehr.")
        return
    self.provoke_assignments[attacker_id] = creature_id
    self.log(f"{attacker.name} provoziert {target.name}.")


def prepare_provoke_assignments(self, attackers) -> None:
    defender_blockers = self.available_blockers(self.defending_player)
    if not defender_blockers:
        self.provoke_assignments.clear()
        return
    assignments: dict[int, int] = {}
    for attacker in attackers:
        if not attacker.has_ability(Ability.PROVOKE):
            continue
        valid_blockers = [blocker for blocker in defender_blockers if self.can_creature_block_attacker(blocker, attacker)]
        blockers_by_id = {blocker.unit_id: blocker for blocker in valid_blockers}
        if self.active_player.is_human:
            target_id = self.provoke_assignments.get(attacker.unit_id)
            if target_id in blockers_by_id:
                assignments[attacker.unit_id] = target_id
            continue
        chosen = self.ai.choose_provoke_target(attacker, valid_blockers)
        if chosen is not None:
            assignments[attacker.unit_id] = chosen.unit_id
    self.provoke_assignments = assignments


def auto_assign_required_blockers(self) -> None:
    if not self.provoke_assignments:
        return
    blockers_by_id = {blocker.unit_id: blocker for blocker in self.available_blockers(self.defending_player)}
    assignments_by_blocker: dict[int, list[int]] = {}
    for attacker_id, blocker_id in self.provoke_assignments.items():
        attacker = self.get_unit_by_id(attacker_id)
        blocker = blockers_by_id.get(blocker_id)
        if attacker is None or blocker is None:
            continue
        if not self.can_creature_block_attacker(blocker, attacker):
            continue
        assignments_by_blocker.setdefault(blocker_id, []).append(attacker_id)

    for blocker_id, attacker_ids in assignments_by_blocker.items():
        blocker = blockers_by_id.get(blocker_id)
        if blocker is None:
            continue
        for attacker_id in attacker_ids[:blocker.block_capacity()]:
            if blocker_id in self.block_assignments.get(attacker_id, []):
                continue
            self.block_assignments.setdefault(attacker_id, []).append(blocker_id)
            self.blocker_to_attackers.setdefault(blocker_id, []).append(attacker_id)
            attacker = self.get_unit_by_id(attacker_id)
            if attacker is not None:
                self.log(f"{blocker.name} muss {attacker.name} durch Provozieren blocken.")


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
    for attacker in attackers:
        attacker.tapped = True
    self.selected_attackers = [attacker.unit_id for attacker in attackers]
    if self.statistics is not None:
        self.statistics.register_attackers(self.active_player.player_id, len(attackers))
    if not attackers:
        self.log("Keine Angreifer gewaehlt.")
        self.end_turn()
        return
    self.block_assignments = {attacker.unit_id: [] for attacker in attackers}
    self.blocker_to_attackers.clear()
    self.prepare_provoke_assignments(attackers)
    if self.defending_player.is_human:
        if not self.available_blockers(self.defending_player):
            self.log("Keine Kreaturen koennen blocken. Schaden geht automatisch durch.")
            self.begin_combat_resolution()
            return
        self.phase = PHASE_DECLARE_BLOCKERS
        self.selected_blocker_id = None
        self.selected_provoke_attacker_id = None
        self.selected_attack_target_id = attackers[0].unit_id if len(attackers) == 1 else None
        self.auto_assign_required_blockers()
        self.log("Waehle einen Angreifer und ordne dann eigene Blocker zu.")
        return
    if not self.available_blockers(self.defending_player):
        self.log("Gegner hat keine Kreaturen zum Blocken. Schaden geht automatisch durch.")
        self.begin_combat_resolution()
        return
    self.phase = PHASE_DECLARE_BLOCKERS
    self.selected_blocker_id = None
    self.selected_provoke_attacker_id = None
    self.selected_attack_target_id = attackers[0].unit_id if len(attackers) == 1 else None
    self.auto_assign_required_blockers()
    self.log("Gegner ueberlegt seine Blocker.")


def toggle_selected_attack_target(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS or not self.defending_player.is_human:
        return
    if creature_id not in self.block_assignments:
        return
    self.selected_attack_target_id = None if self.selected_attack_target_id == creature_id else creature_id
    attacker = self.get_unit_by_id(creature_id)
    if attacker is not None:
        self.log(f"Blockziel ausgewaehlt: {attacker.name}.")


def toggle_blocker_assignment(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS or not self.defending_player.is_human:
        return
    creature = self.get_unit_by_id(creature_id)
    if creature is None or self.get_unit_owner(creature_id) != self.defending_player:
        return
    assigned_attackers = self.blocker_to_attackers.get(creature_id, [])
    if not creature.is_ready() and not assigned_attackers:
        self.log("Diese Kreatur kann nicht blocken.")
        return
    if self.selected_attack_target_id is None:
        self.selected_blocker_id = creature_id
        self.log("Waehle zuerst einen Angreifer als Blockziel aus.")
        return
    attacker_id = self.selected_attack_target_id
    if attacker_id not in self.block_assignments:
        return
    attacker = self.get_unit_by_id(attacker_id)
    if attacker is None:
        return
    if not self.can_creature_block_attacker(creature, attacker):
        self.log(f"{creature.name} kann {attacker.name} nicht blocken.")
        return
    self.selected_blocker_id = creature_id
    if self.provoke_assignments.get(attacker_id) == creature_id and attacker_id in assigned_attackers:
        self.log(f"{creature.name} muss diesen Angreifer durch Provozieren blocken.")
        return
    if attacker_id in assigned_attackers:
        self.block_assignments[attacker_id] = [
            blocker_id for blocker_id in self.block_assignments[attacker_id] if blocker_id != creature_id
        ]
        self.blocker_to_attackers[creature_id] = [
            existing_attacker_id
            for existing_attacker_id in assigned_attackers
            if existing_attacker_id != attacker_id
        ]
        if not self.blocker_to_attackers[creature_id]:
            del self.blocker_to_attackers[creature_id]
        self.log(f"{creature.name} blockt {attacker.name} nicht mehr.")
        return
    if len(assigned_attackers) >= creature.block_capacity():
        self.log(f"{creature.name} kann in dieser Kampfphase keine weiteren Angreifer blocken.")
        return
    self.block_assignments[attacker_id].append(creature_id)
    self.blocker_to_attackers.setdefault(creature_id, []).append(attacker_id)
    self.log(f"{creature.name} blockt {attacker.name}.")


def clear_block_assignments(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    self.block_assignments = {attacker_id: [] for attacker_id in self.block_assignments}
    self.blocker_to_attackers.clear()
    self.selected_blocker_id = None
    if len(self.block_assignments) != 1:
        self.selected_attack_target_id = None
    self.auto_assign_required_blockers()
    self.log("Alle Blockzuweisungen wurden geloescht.")


def finish_block_assignment(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    for blocker_id in self.blocker_to_attackers:
        blocker = self.get_unit_by_id(blocker_id)
        if blocker is not None:
            blocker.tapped = True
    if self.statistics is not None:
        for blocker_ids in self.block_assignments.values():
            self.statistics.register_block_assignment(len(blocker_ids))
    self.begin_combat_resolution()


def ai_assign_blocks(self) -> None:
    attackers = [
        attacker
        for attacker in (self.get_unit_by_id(attacker_id) for attacker_id in self.block_assignments)
        if attacker is not None
    ]
    available_blockers = self.available_blockers(self.defending_player)
    assignments = self.ai.choose_blockers_for_attackers(attackers, available_blockers, self.block_assignments)
    for attacker_id, blocker_ids in assignments.items():
        attacker = self.get_unit_by_id(attacker_id)
        if attacker is None:
            continue
        for blocker_id in blocker_ids:
            blocker = self.get_unit_by_id(blocker_id)
            if blocker is None or blocker_id in self.block_assignments[attacker_id]:
                continue
            if not self.can_creature_block_attacker(blocker, attacker):
                continue
            self.block_assignments[attacker_id].append(blocker_id)
            self.blocker_to_attackers.setdefault(blocker_id, []).append(attacker_id)
            self.log(f"{self.defending_player.name} blockt {attacker.name} mit {blocker.name}.")
    for blocker_id in self.blocker_to_attackers:
        blocker = self.get_unit_by_id(blocker_id)
        if blocker is not None:
            blocker.tapped = True
    if self.statistics is not None:
        for blocker_ids in self.block_assignments.values():
            self.statistics.register_block_assignment(len(blocker_ids))


def begin_combat_resolution(self) -> None:
    attacker_ids = set(self.block_assignments.keys())
    ordered_attackers = [
        creature.unit_id
        for creature in self.active_player.battlefield
        if creature.unit_id in attacker_ids
    ]
    self.combat_queue = ordered_attackers
    self.blocked_attackers = {
        attacker_id for attacker_id, blocker_ids in self.block_assignments.items() if blocker_ids
    }
    self.current_attack_index = 0
    self.current_blocker_order = []
    self.current_blocker_index = 0
    self.pending_order = None
    self.pending_dice_battle = None
    self.pending_direct_attack = None
    self.advance_combat_resolution()


def advance_combat_resolution(self) -> None:
    while self.phase != PHASE_GAME_OVER:
        if self.pending_dice_battle is not None:
            self.phase = PHASE_DICE_BATTLE
            return
        if self.pending_direct_attack is not None:
            return
        if self.pending_order is not None:
            self.phase = PHASE_ORDER_BLOCKERS
            return
        if self.current_blocker_order:
            attacker = self.get_unit_by_id(self.combat_queue[self.current_attack_index])
            if attacker is None or self.is_creature_destroyed(attacker):
                self.current_blocker_order = []
                self.current_blocker_index = 0
                self.current_attack_index += 1
                continue
            while self.current_blocker_index < len(self.current_blocker_order):
                blocker_id = self.current_blocker_order[self.current_blocker_index]
                blocker = self.get_unit_by_id(blocker_id)
                self.current_blocker_index += 1
                if blocker is None or self.is_creature_destroyed(blocker):
                    continue
                self.start_dice_battle(attacker.unit_id, blocker.unit_id)
                if self.pending_dice_battle is not None:
                    self.phase = PHASE_DICE_BATTLE
                    return
            self.current_blocker_order = []
            self.current_blocker_index = 0
            self.current_attack_index += 1
            continue
        if self.current_attack_index >= len(self.combat_queue):
            self.end_turn()
            return

        attacker_id = self.combat_queue[self.current_attack_index]
        attacker = self.get_unit_by_id(attacker_id)
        if attacker is None or self.is_creature_destroyed(attacker):
            self.current_attack_index += 1
            continue

        blockers = [
            blocker_id
            for blocker_id in self.block_assignments.get(attacker_id, [])
            if self.get_unit_by_id(blocker_id) is not None
        ]
        if not blockers:
            if attacker_id in self.blocked_attackers:
                self.log(f"{attacker.name} bleibt geblockt und verursacht keinen direkten Schaden.")
                self.current_attack_index += 1
                continue
            self.pending_direct_attack = PendingDirectAttack(
                attacker_id=attacker.unit_id,
                attacker_owner=self.active_player.player_id,
                defending_player_id=self.defending_player.player_id,
                base_damage=self.get_creature_attack_value(attacker),
            )
            self.begin_general_spell_window(
                trigger=ReactionTrigger.BEFORE_DIRECT_ATTACK_DAMAGE,
                first_responder_id=self.defending_player.player_id,
                resume_phase=PHASE_REACTION,
                continuation=self.resolve_pending_direct_attack_after_reaction,
                attacker_creature=attacker,
                damage_amount=self.get_creature_attack_value(attacker),
                pending_damage_attacker_id=attacker.unit_id,
            )
            return

        if len(blockers) == 1:
            self.current_blocker_order = blockers
            self.current_blocker_index = 0
            continue

        attacker_owner = self.get_unit_owner(attacker_id)
        if attacker_owner is None:
            self.current_attack_index += 1
            continue
        if attacker_owner.is_human:
            self.pending_order = PendingBlockOrder(attacker_id=attacker_id, blocker_ids=blockers)
            self.phase = PHASE_ORDER_BLOCKERS
            self.log(f"{attacker.name} wurde mehrfach geblockt. Lege die Reihenfolge fest.")
            return

        ordered = self.ai.choose_block_order(
            [self.get_unit_by_id(blocker_id) for blocker_id in blockers if self.get_unit_by_id(blocker_id) is not None]
        )
        self.current_blocker_order = [blocker.unit_id for blocker in ordered]
        self.current_blocker_index = 0
        self.log(f"KI legt die Blockreihenfolge fuer {attacker.name} fest.")


def resolve_pending_direct_attack_after_reaction(self) -> None:
    pending = self.pending_direct_attack
    if pending is None:
        return
    self.pending_direct_attack = None
    attacker = self.get_unit_by_id(pending.attacker_id)
    if attacker is not None and self.get_unit_owner(attacker.unit_id) == self.active_player:
        damage = pending.base_damage * pending.damage_multiplier
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
        self.check_for_game_over()
        if self.phase == PHASE_GAME_OVER:
            return
    self.current_attack_index += 1
    self.advance_combat_resolution()


def confirm_block_order(self) -> None:
    if self.pending_order is None:
        return
    if len(self.pending_order.chosen_order) != len(self.pending_order.blocker_ids):
        self.log("Die Blockreihenfolge ist noch nicht vollstaendig.")
        return
    self.current_blocker_order = list(self.pending_order.chosen_order)
    self.current_blocker_index = 0
    self.pending_order = None
    self.advance_combat_resolution()


def choose_next_block_order_item(self, blocker_id: int) -> None:
    if self.pending_order is None:
        return
    if blocker_id not in self.pending_order.blocker_ids:
        return
    if blocker_id in self.pending_order.chosen_order:
        self.log("Dieser Blocker wurde bereits in die Reihenfolge aufgenommen.")
        return
    self.pending_order.chosen_order.append(blocker_id)
    blocker = self.get_unit_by_id(blocker_id)
    if blocker is not None:
        self.log(f"Reihenfolge erweitert um {blocker.name}.")
    if len(self.pending_order.chosen_order) == len(self.pending_order.blocker_ids):
        self.confirm_block_order()
