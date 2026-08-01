from __future__ import annotations

from core.models import (
    Ability,
    PendingBlockOrder,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_SUMMONING,
    PHASE_ORDER_BLOCKERS,
)


def begin_attack_declaration(self) -> None:
    if self.phase != PHASE_SUMMONING:
        return
    available_attackers = self.available_attackers(self.active_player)
    if not available_attackers:
        self.log("Keine Kreaturen kÃ¶nnen angreifen. Kampfphase endet automatisch.")
        self.end_turn()
        return
    self.phase = PHASE_DECLARE_ATTACKERS
    self.selected_attackers.clear()
    self.log("WÃ¤hle deine Angreifer.")


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
        self.selected_attackers.remove(creature_id)
    else:
        self.selected_attackers.append(creature_id)


def confirm_attackers(self) -> None:
    if self.phase != PHASE_DECLARE_ATTACKERS:
        return
    attackers = [
        creature
        for creature in (self.get_unit_by_id(creature_id) for creature_id in self.selected_attackers)
        if creature is not None and creature.is_ready()
    ]
    for attacker in attackers:
        if not attacker.has_ability(Ability.VIGILANCE):
            attacker.tapped = True
    self.selected_attackers = [attacker.unit_id for attacker in attackers]
    if self.statistics is not None:
        self.statistics.register_attackers(self.active_player.player_id, len(attackers))
    if not attackers:
        self.log("Keine Angreifer gewÃ¤hlt.")
        self.end_turn()
        return
    self.block_assignments = {attacker.unit_id: [] for attacker in attackers}
    self.blocker_to_attackers.clear()
    if self.defending_player.is_human:
        if not self.available_blockers(self.defending_player):
            self.log("Keine Kreaturen kÃ¶nnen blocken. Schaden geht automatisch durch.")
            self.begin_combat_resolution()
            return
        self.phase = PHASE_DECLARE_BLOCKERS
        self.selected_blocker_id = None
        self.selected_attack_target_id = attackers[0].unit_id if len(attackers) == 1 else None
        self.log("WÃ¤hle einen Angreifer und ordne dann eigene Blocker zu.")
    else:
        if not self.available_blockers(self.defending_player):
            self.log("Gegner hat keine Kreaturen zum Blocken. Schaden geht automatisch durch.")
            self.begin_combat_resolution()
            return
        self.phase = PHASE_DECLARE_BLOCKERS
        self.selected_blocker_id = None
        self.selected_attack_target_id = attackers[0].unit_id if len(attackers) == 1 else None
        self.log("Gegner Ã¼berlegt seine Blocker.")


def toggle_selected_attack_target(self, creature_id: int) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS or not self.defending_player.is_human:
        return
    if creature_id not in self.block_assignments:
        return
    self.selected_attack_target_id = None if self.selected_attack_target_id == creature_id else creature_id
    attacker = self.get_unit_by_id(creature_id)
    if attacker is not None:
        self.log(f"Blockziel ausgewÃ¤hlt: {attacker.name}.")


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
        self.log("WÃ¤hle zuerst einen Angreifer als Blockziel aus.")
        return
    attacker_id = self.selected_attack_target_id
    if attacker_id not in self.block_assignments:
        return
    self.selected_blocker_id = creature_id
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
        attacker = self.get_unit_by_id(attacker_id)
        if attacker is not None:
            self.log(f"{creature.name} blockt {attacker.name} nicht mehr.")
        return
    if len(assigned_attackers) >= creature.block_capacity():
        self.log(f"{creature.name} kann in dieser Kampfphase keine weiteren Angreifer blocken.")
        return
    self.block_assignments[attacker_id].append(creature_id)
    self.blocker_to_attackers.setdefault(creature_id, []).append(attacker_id)
    attacker = self.get_unit_by_id(attacker_id)
    if attacker is not None:
        self.log(f"{creature.name} blockt {attacker.name}.")


def clear_block_assignments(self) -> None:
    if self.phase != PHASE_DECLARE_BLOCKERS:
        return
    self.block_assignments = {attacker_id: [] for attacker_id in self.block_assignments}
    self.blocker_to_attackers.clear()
    self.selected_blocker_id = None
    if len(self.block_assignments) != 1:
        self.selected_attack_target_id = None
    self.log("Alle Blockzuweisungen wurden gelÃ¶scht.")


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
    assignments = self.ai.choose_blockers_for_attackers(attackers, available_blockers)
    for attacker_id, blocker_ids in assignments.items():
        attacker = self.get_unit_by_id(attacker_id)
        if attacker is None:
            continue
        for blocker_id in blocker_ids:
            blocker = self.get_unit_by_id(blocker_id)
            if blocker is None:
                continue
            self.block_assignments[attacker_id].append(blocker_id)
            self.blocker_to_attackers.setdefault(blocker_id, []).append(attacker_id)
            blocker.tapped = True
            self.log(f"{self.defending_player.name} blockt {attacker.name} mit {blocker.name}.")
    if self.statistics is not None:
        for blocker_ids in self.block_assignments.values():
            self.statistics.register_block_assignment(len(blocker_ids))


def begin_combat_resolution(self) -> None:
    self.combat_queue = list(self.block_assignments.keys())
    self.current_attack_index = 0
    self.current_blocker_order = []
    self.current_blocker_index = 0
    self.pending_order = None
    self.pending_dice_battle = None
    self.advance_combat_resolution()


def advance_combat_resolution(self) -> None:
    while self.phase != PHASE_GAME_OVER:
        if self.pending_dice_battle is not None:
            self.phase = PHASE_DICE_BATTLE
            return
        if self.pending_order is not None:
            self.phase = PHASE_ORDER_BLOCKERS
            return
        if self.current_blocker_order:
            attacker = self.get_unit_by_id(self.combat_queue[self.current_attack_index])
            if attacker is None or attacker.current_hp <= 0:
                self.current_blocker_order = []
                self.current_blocker_index = 0
                self.current_attack_index += 1
                continue
            while self.current_blocker_index < len(self.current_blocker_order):
                blocker_id = self.current_blocker_order[self.current_blocker_index]
                blocker = self.get_unit_by_id(blocker_id)
                self.current_blocker_index += 1
                if blocker is None or blocker.current_hp <= 0:
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
        if attacker is None or attacker.current_hp <= 0:
            self.current_attack_index += 1
            continue

        blockers = [
            blocker_id
            for blocker_id in self.block_assignments.get(attacker_id, [])
            if self.get_unit_by_id(blocker_id) is not None
        ]
        if not blockers:
            self.defending_player.life -= attacker.aw
            self.queue_player_damage_event(
                target_player_id=self.defending_player.player_id,
                amount=attacker.aw,
                source_element=attacker.element,
                attacker_id=attacker.unit_id,
            )
            if self.statistics is not None:
                self.statistics.register_unblocked_attack(self.active_player.player_id, attacker.aw)
            self.log(
                f"{attacker.name} ist ungeblockt und verursacht {attacker.aw} Schaden an {self.defending_player.name}."
            )
            self.check_for_game_over()
            self.current_attack_index += 1
            continue

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
        self.log(f"KI legt die Blockreihenfolge fÃ¼r {attacker.name} fest.")


def confirm_block_order(self) -> None:
    if self.pending_order is None:
        return
    if len(self.pending_order.chosen_order) != len(self.pending_order.blocker_ids):
        self.log("Die Blockreihenfolge ist noch nicht vollstÃ¤ndig.")
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
