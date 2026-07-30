from __future__ import annotations

from datetime import datetime
from pathlib import Path
from random import Random
from typing import Dict, List, Optional

from ai_logic import SimpleAI
from card_data import build_card_templates, build_test_deck
from models import (
    BattlefieldUnit,
    ButtonSpec,
    CardInstance,
    DieResult,
    DiceRoundRecord,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MAIN,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
    PHASE_RESOURCE,
    PendingBlockOrder,
    PendingDiceBattle,
    PlayerState,
    ResourceCard,
)
from game_statistics import GAME_RESULTS_PATH, UNIT_RESULTS_PATH, GameStatistics


class GameEngine:
    def __init__(self) -> None:
        self.templates = build_card_templates()
        self.players: List[PlayerState] = []
        self.active_player_index = 0
        self.starting_player_id = 0
        self.turn_number = 0
        self.phase = PHASE_MULLIGAN
        self.game_over_text = ""
        self.log_messages: List[str] = []
        self.game_over_summary_lines: List[str] = []
        self.results_path = Path.cwd() / GAME_RESULTS_PATH
        self.unit_results_path = Path.cwd() / UNIT_RESULTS_PATH

        self.rng = Random()
        self.ai = SimpleAI(self.rng)
        self.seed = 0
        self.game_id = ""
        self.statistics: Optional[GameStatistics] = None
        self.game_over_saved = False

        self.next_instance_id = 1
        self.selected_hand_ids: List[int] = []
        self.selected_attackers: List[int] = []
        self.selected_blocker_id: Optional[int] = None
        self.block_assignments: Dict[int, List[int]] = {}
        self.blocker_to_attacker: Dict[int, int] = {}
        self.pending_order: Optional[PendingBlockOrder] = None
        self.pending_dice_battle: Optional[PendingDiceBattle] = None
        self.combat_queue: List[int] = []
        self.current_attack_index = 0
        self.current_blocker_order: List[int] = []
        self.current_blocker_index = 0
        self.combat_id_counter = 0
        self.ai_turn_initialized = False
        self.exit_requested = False

        self.start_new_game()

    @property
    def human_player(self) -> PlayerState:
        return self.players[0]

    @property
    def ai_player(self) -> PlayerState:
        return self.players[1]

    @property
    def active_player(self) -> PlayerState:
        return self.players[self.active_player_index]

    @property
    def defending_player(self) -> PlayerState:
        return self.players[1 - self.active_player_index]

    def make_instance_id(self) -> int:
        instance_id = self.next_instance_id
        self.next_instance_id += 1
        return instance_id

    def log(self, message: str) -> None:
        self.log_messages.append(message)
        self.log_messages = self.log_messages[-18:]

    def start_new_game(self) -> None:
        self.seed = Random().randrange(1, 10**12)
        self.rng = Random(self.seed)
        self.ai = SimpleAI(self.rng)
        self.game_id = f"game-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{self.seed}"
        self.next_instance_id = 1
        self.players = [
            PlayerState(0, "Spieler", True),
            PlayerState(1, "Gegner", False),
        ]
        self.log_messages.clear()
        self.game_over_summary_lines.clear()
        self.game_over_text = ""
        self.turn_number = 0
        self.phase = PHASE_MULLIGAN
        self.game_over_saved = False
        self.exit_requested = False
        self.reset_combat_state()

        for player in self.players:
            player.life = 20
            player.deck = build_test_deck(self.templates, self.make_instance_id)
            self.rng.shuffle(player.deck)
            player.hand.clear()
            player.battlefield.clear()
            player.resources.clear()
            player.resource_played_this_turn = False
            player.turns_started = 0
            player.mulligan_used = False
            for _ in range(5):
                drawn = player.draw_card()
                if drawn is not None:
                    continue

        self.starting_player_id = self.rng.choice([0, 1])
        self.statistics = GameStatistics(
            game_id=self.game_id,
            seed=self.seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            start_player=self.players[self.starting_player_id].name,
            player_names={0: "Spieler", 1: "Gegner"},
        )
        self.log(f"Neue Partie gestartet. Seed: {self.seed}")
        self.log(f"Startspieler: {self.players[self.starting_player_id].name}")
        self.apply_ai_mulligan()
        self.phase = PHASE_MULLIGAN
        self.selected_hand_ids.clear()
        self.log("Waehle beliebige Karten fuer deinen einmaligen Mulligan oder behalte die Hand.")

    def apply_ai_mulligan(self) -> None:
        ai_indices = self.ai.mulligan_indices(self.ai_player.hand)
        if not ai_indices:
            self.ai_player.mulligan_used = True
            return
        to_replace = [self.ai_player.hand[index] for index in ai_indices]
        self.ai_player.hand = [
            card for idx, card in enumerate(self.ai_player.hand) if idx not in ai_indices
        ]
        self.ai_player.deck.extend(to_replace)
        self.rng.shuffle(self.ai_player.deck)
        for _ in to_replace:
            self.ai_player.draw_card()
        self.ai_player.mulligan_used = True
        self.log(f"Gegner fuehrt einen Mulligan mit {len(to_replace)} Karten durch.")

    def apply_human_mulligan(self) -> None:
        if self.human_player.mulligan_used:
            return
        if self.selected_hand_ids:
            to_replace = [
                card for card in self.human_player.hand if card.instance_id in self.selected_hand_ids
            ]
            self.human_player.hand = [
                card for card in self.human_player.hand if card.instance_id not in self.selected_hand_ids
            ]
            self.human_player.deck.extend(to_replace)
            self.rng.shuffle(self.human_player.deck)
            for _ in to_replace:
                self.human_player.draw_card()
            self.log(f"Spieler tauscht {len(to_replace)} Karten per Mulligan.")
        else:
            self.log("Spieler behaelt seine Starthand.")
        self.human_player.mulligan_used = True
        self.selected_hand_ids.clear()
        self.begin_first_turn()

    def begin_first_turn(self) -> None:
        self.active_player_index = self.starting_player_id
        self.turn_number = 0
        self.start_turn()

    def start_turn(self) -> None:
        player = self.active_player
        self.turn_number += 1
        player.untap_for_turn()
        draw_allowed = not (
            player.player_id == self.starting_player_id and player.turns_started == 0
        )
        if draw_allowed:
            drawn = player.draw_card()
            if drawn is not None:
                self.statistics.register_draw(player.player_id)
                self.log(f"{player.name} zieht eine Karte.")
            else:
                self.log(f"{player.name} kann keine Karte ziehen.")
        else:
            self.log(f"{player.name} ist Startspieler und zieht im ersten Zug keine Karte.")
        player.turns_started += 1
        player.resource_played_this_turn = False
        self.phase = PHASE_RESOURCE
        self.selected_hand_ids.clear()
        self.selected_attackers.clear()
        self.selected_blocker_id = None
        self.ai_turn_initialized = False
        self.statistics.register_turn_count(self.turn_number)
        self.log(f"Zug {self.turn_number}: {player.name} ist am Zug.")
        self.check_for_game_over()

    def reset_combat_state(self) -> None:
        self.selected_attackers = []
        self.selected_blocker_id = None
        self.block_assignments = {}
        self.blocker_to_attacker = {}
        self.pending_order = None
        self.pending_dice_battle = None
        self.combat_queue = []
        self.current_attack_index = 0
        self.current_blocker_order = []
        self.current_blocker_index = 0

    def available_attackers(self, player: PlayerState) -> List[BattlefieldUnit]:
        return [unit for unit in player.battlefield if unit.is_ready()]

    def available_blockers(self, player: PlayerState) -> List[BattlefieldUnit]:
        return [unit for unit in player.battlefield if unit.is_ready()]

    def get_unit_by_id(self, unit_id: int) -> Optional[BattlefieldUnit]:
        for player in self.players:
            for unit in player.battlefield:
                if unit.unit_id == unit_id:
                    return unit
        return None

    def get_unit_owner(self, unit_id: int) -> Optional[PlayerState]:
        for player in self.players:
            for unit in player.battlefield:
                if unit.unit_id == unit_id:
                    return player
        return None

    def get_selected_hand_card(self) -> Optional[CardInstance]:
        if len(self.selected_hand_ids) != 1:
            return None
        selected_id = self.selected_hand_ids[0]
        for card in self.active_player.hand:
            if card.instance_id == selected_id:
                return card
        return None

    def toggle_hand_card(self, card_id: int) -> None:
        if self.phase == PHASE_MULLIGAN:
            if card_id in self.selected_hand_ids:
                self.selected_hand_ids.remove(card_id)
            else:
                self.selected_hand_ids.append(card_id)
            return
        if self.active_player.is_human and self.phase in {PHASE_RESOURCE, PHASE_MAIN}:
            if card_id in self.selected_hand_ids:
                self.selected_hand_ids.clear()
            else:
                self.selected_hand_ids = [card_id]

    def handle_action(self, action: str) -> None:
        if action == "exit_game":
            self.exit_requested = True
            return
        if action == "new_game":
            self.start_new_game()
            return

        if self.phase == PHASE_MULLIGAN:
            if action in {"confirm_mulligan", "keep_mulligan"}:
                self.apply_human_mulligan()
            return

        if self.phase == PHASE_GAME_OVER or not self.active_player.is_human:
            return

        if action == "play_resource":
            self.play_selected_card_as_resource()
        elif action == "to_main":
            self.phase = PHASE_MAIN
            self.log("Hauptphase begonnen.")
        elif action == "play_unit":
            self.play_selected_unit_card()
        elif action == "to_combat":
            self.begin_attack_declaration()
        elif action == "confirm_attackers":
            self.confirm_attackers()
        elif action == "clear_blocks":
            self.clear_block_assignments()
        elif action == "confirm_blocks":
            self.finish_block_assignment()
        elif action == "reset_order" and self.pending_order is not None:
            self.pending_order.chosen_order.clear()
            self.log("Blockreihenfolge zurueckgesetzt.")
        elif action == "confirm_order":
            self.confirm_block_order()
        elif action == "end_turn":
            self.end_turn()

    def play_selected_card_as_resource(self) -> None:
        if self.phase != PHASE_RESOURCE or self.active_player.resource_played_this_turn:
            return
        card = self.get_selected_hand_card()
        if card is None:
            self.log("Keine Handkarte als Ressource ausgewaehlt.")
            return
        self.active_player.hand = [
            existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
        ]
        self.active_player.resources.append(ResourceCard(source_name=card.template.name))
        self.active_player.resource_played_this_turn = True
        self.selected_hand_ids.clear()
        self.statistics.register_resource_played(self.active_player.player_id)
        self.log(f"{self.active_player.name} legt {card.template.name} als Ressource.")

    def play_selected_unit_card(self) -> None:
        if self.phase != PHASE_MAIN:
            return
        card = self.get_selected_hand_card()
        if card is None:
            self.log("Keine Unit-Karte ausgewaehlt.")
            return
        if not self.active_player.pay_cost(card.template.cost):
            self.log("Nicht genuegend Ressourcen.")
            return
        self.active_player.hand = [
            existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
        ]
        self.active_player.battlefield.append(BattlefieldUnit.from_card(card))
        self.selected_hand_ids.clear()
        self.statistics.register_unit_played(self.active_player.player_id)
        self.log(
            f"{self.active_player.name} spielt {card.template.name} "
            f"({card.template.aw}/{card.template.vw}) fuer {card.template.cost}."
        )

    def begin_attack_declaration(self) -> None:
        if self.phase != PHASE_MAIN:
            return
        self.phase = PHASE_DECLARE_ATTACKERS
        self.selected_attackers.clear()
        self.log("Waehle deine Angreifer.")

    def toggle_attacker(self, unit_id: int) -> None:
        if self.phase != PHASE_DECLARE_ATTACKERS or not self.active_player.is_human:
            return
        unit = self.get_unit_by_id(unit_id)
        if unit is None or self.get_unit_owner(unit_id) != self.active_player:
            return
        if not unit.is_ready():
            self.log("Diese Unit kann nicht angreifen.")
            return
        if unit_id in self.selected_attackers:
            self.selected_attackers.remove(unit_id)
        else:
            self.selected_attackers.append(unit_id)

    def confirm_attackers(self) -> None:
        if self.phase != PHASE_DECLARE_ATTACKERS:
            return
        attackers = [
            unit
            for unit in (self.get_unit_by_id(unit_id) for unit_id in self.selected_attackers)
            if unit is not None and unit.is_ready()
        ]
        for attacker in attackers:
            attacker.tapped = True
        self.selected_attackers = [attacker.unit_id for attacker in attackers]
        self.statistics.register_attackers(self.active_player.player_id, len(attackers))
        if not attackers:
            self.log("Keine Angreifer gewaehlt.")
            self.end_turn()
            return
        self.block_assignments = {attacker.unit_id: [] for attacker in attackers}
        self.blocker_to_attacker.clear()
        if self.defending_player.is_human:
            self.phase = PHASE_DECLARE_BLOCKERS
            self.selected_blocker_id = None
            self.log("Waehle Blocker und klicke danach auf den zu blockenden Angreifer.")
        else:
            self.ai_assign_blocks()
            self.begin_combat_resolution()

    def toggle_selected_blocker(self, unit_id: int) -> None:
        if self.phase != PHASE_DECLARE_BLOCKERS or not self.defending_player.is_human:
            return
        unit = self.get_unit_by_id(unit_id)
        if unit is None or self.get_unit_owner(unit_id) != self.defending_player:
            return
        if not unit.is_ready():
            self.log("Diese Unit kann nicht blocken.")
            return
        self.selected_blocker_id = None if self.selected_blocker_id == unit_id else unit_id

    def assign_selected_blocker(self, attacker_id: int) -> None:
        if self.phase != PHASE_DECLARE_BLOCKERS or self.selected_blocker_id is None:
            return
        if attacker_id not in self.block_assignments:
            return
        previous = self.blocker_to_attacker.get(self.selected_blocker_id)
        if previous == attacker_id:
            self.block_assignments[attacker_id] = [
                blocker_id
                for blocker_id in self.block_assignments[attacker_id]
                if blocker_id != self.selected_blocker_id
            ]
            del self.blocker_to_attacker[self.selected_blocker_id]
            self.log("Blockzuweisung entfernt.")
            return
        if previous is not None:
            self.block_assignments[previous] = [
                blocker_id
                for blocker_id in self.block_assignments[previous]
                if blocker_id != self.selected_blocker_id
            ]
        self.block_assignments[attacker_id].append(self.selected_blocker_id)
        self.blocker_to_attacker[self.selected_blocker_id] = attacker_id
        blocker = self.get_unit_by_id(self.selected_blocker_id)
        attacker = self.get_unit_by_id(attacker_id)
        if blocker is not None and attacker is not None:
            self.log(f"{blocker.name} blockt {attacker.name}.")

    def clear_block_assignments(self) -> None:
        if self.phase != PHASE_DECLARE_BLOCKERS:
            return
        self.block_assignments = {attacker_id: [] for attacker_id in self.block_assignments}
        self.blocker_to_attacker.clear()
        self.selected_blocker_id = None
        self.log("Alle Blockzuweisungen wurden geloescht.")

    def finish_block_assignment(self) -> None:
        if self.phase != PHASE_DECLARE_BLOCKERS:
            return
        for blocker_id in self.blocker_to_attacker:
            blocker = self.get_unit_by_id(blocker_id)
            if blocker is not None:
                blocker.tapped = True
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
        for attacker in sorted(attackers, key=lambda unit: (-unit.aw, unit.current_hp)):
            blocker = self.ai.choose_blocker(attacker, available_blockers)
            if blocker is None:
                continue
            self.block_assignments[attacker.unit_id].append(blocker.unit_id)
            self.blocker_to_attacker[blocker.unit_id] = attacker.unit_id
            blocker.tapped = True
            available_blockers = [unit for unit in available_blockers if unit.unit_id != blocker.unit_id]
            self.log(f"{self.defending_player.name} blockt {attacker.name} mit {blocker.name}.")
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
            self.log(f"KI legt die Blockreihenfolge fuer {attacker.name} fest.")

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

    def start_dice_battle(self, attacker_id: int, blocker_id: int) -> None:
        attacker = self.get_unit_by_id(attacker_id)
        blocker = self.get_unit_by_id(blocker_id)
        attacker_owner = self.get_unit_owner(attacker_id)
        blocker_owner = self.get_unit_owner(blocker_id)
        if attacker is None or blocker is None or attacker_owner is None or blocker_owner is None:
            return
        strategy = self.ai.choose_die_strategy()
        self.combat_id_counter += 1
        self.statistics.start_unit_combat(
            combat_id=self.combat_id_counter,
            attacker_owner=attacker_owner.player_id,
            blocker_owner=blocker_owner.player_id,
            attacker_name=attacker.name,
            blocker_name=blocker.name,
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
            ai_strategy_name=strategy.name,
            ai_choose_die=lambda dice, strategy=strategy: strategy.choose(dice, self.rng),
        )
        self.log(f"Wuerfelkampf startet: {attacker.name} gegen {blocker.name}.")

    def choose_human_die(self, visible_index: int) -> None:
        battle = self.pending_dice_battle
        if battle is None:
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

        attacker = self.get_unit_by_id(battle.attacker_id)
        blocker = self.get_unit_by_id(battle.blocker_id)
        if attacker is None or blocker is None:
            return

        attacker_damage = 0
        blocker_damage = 0
        if human_is_attacker:
            if chosen_human_die.total > chosen_enemy_die.total:
                blocker.current_hp -= 1
                attacker_damage = 1
                outcome = f"{attacker.name} gewinnt den Wuerfelvergleich."
            elif chosen_human_die.total < chosen_enemy_die.total:
                attacker.current_hp -= 1
                blocker_damage = 1
                outcome = f"{blocker.name} gewinnt den Wuerfelvergleich."
            else:
                attacker.current_hp -= 1
                blocker.current_hp -= 1
                attacker_damage = 1
                blocker_damage = 1
                outcome = "Gleichstand. Beide Units erhalten 1 Schaden."
            human_unit = attacker
            enemy_unit = blocker
        else:
            if chosen_human_die.total > chosen_enemy_die.total:
                attacker.current_hp -= 1
                blocker_damage = 1
                outcome = f"{blocker.name} gewinnt den Wuerfelvergleich."
            elif chosen_human_die.total < chosen_enemy_die.total:
                blocker.current_hp -= 1
                attacker_damage = 1
                outcome = f"{attacker.name} gewinnt den Wuerfelvergleich."
            else:
                attacker.current_hp -= 1
                blocker.current_hp -= 1
                attacker_damage = 1
                blocker_damage = 1
                outcome = "Gleichstand. Beide Units erhalten 1 Schaden."
            human_unit = blocker
            enemy_unit = attacker

        self.statistics.register_dice_comparison(attacker_damage=attacker_damage, blocker_damage=blocker_damage)
        battle.history.append(
            DiceRoundRecord(
                round_number=len(battle.history) + 1,
                human_unit_name=human_unit.name,
                human_result=chosen_human_die.display(),
                enemy_unit_name=enemy_unit.name,
                enemy_result=chosen_enemy_die.display(),
                outcome_text=outcome,
            )
        )
        self.log(
            f"{human_unit.name}: {chosen_human_die.display()} | "
            f"{enemy_unit.name}: {chosen_enemy_die.display()} -> {outcome}"
        )

        attacker_hp_after = attacker.current_hp
        blocker_hp_after = blocker.current_hp
        attacker_alive = attacker.current_hp > 0
        blocker_alive = blocker.current_hp > 0
        attacker_dice_left = any(not die.used for die in battle.attacker_dice)
        blocker_dice_left = any(not die.used for die in battle.blocker_dice)

        self.cleanup_destroyed_units()
        if attacker_alive and blocker_alive and attacker_dice_left and blocker_dice_left:
            return

        self.statistics.finish_unit_combat(
            attacker_owner=battle.attacker_owner,
            blocker_owner=battle.blocker_owner,
            attacker_name=attacker.name,
            blocker_name=blocker.name,
            attacker_aw=attacker.aw,
            attacker_vw=attacker.vw,
            blocker_aw=blocker.aw,
            blocker_vw=blocker.vw,
            attacker_hp_after=attacker_hp_after,
            blocker_hp_after=blocker_hp_after,
        )
        self.log(f"Gegnerische Wuerfelstrategie: {battle.ai_strategy_name}.")
        self.pending_dice_battle = None
        self.advance_combat_resolution()

    def cleanup_destroyed_units(self) -> None:
        for player in self.players:
            destroyed = [unit for unit in player.battlefield if unit.current_hp <= 0]
            for unit in destroyed:
                self.log(f"{unit.name} wird zerstoert und entfernt.")
            player.battlefield = [unit for unit in player.battlefield if unit.current_hp > 0]

    def process_ai_turn(self) -> None:
        if self.phase in {PHASE_MULLIGAN, PHASE_GAME_OVER}:
            return
        if self.active_player.is_human:
            return
        if self.phase in {PHASE_DECLARE_BLOCKERS, PHASE_ORDER_BLOCKERS, PHASE_DICE_BATTLE}:
            return
        if not self.ai_turn_initialized:
            self.ai_turn_initialized = True
            self.log("Gegner wertet seinen Zug aus.")

        if self.phase == PHASE_RESOURCE:
            self.ai_play_resource()
            self.phase = PHASE_MAIN
            self.log("Gegner wechselt in die Hauptphase.")
            return

        if self.phase == PHASE_MAIN:
            self.ai_play_units()
            self.ai_declare_attackers()

    def ai_play_resource(self) -> None:
        chosen = self.ai.choose_resource_card(self.active_player)
        if chosen is None:
            return
        self.active_player.hand = [
            card for card in self.active_player.hand if card.instance_id != chosen.instance_id
        ]
        self.active_player.resources.append(ResourceCard(source_name=chosen.template.name))
        self.active_player.resource_played_this_turn = True
        self.statistics.register_resource_played(self.active_player.player_id)
        self.log(f"Gegner legt {chosen.template.name} als Ressource.")

    def ai_play_units(self) -> None:
        while True:
            chosen = self.ai.choose_playable_unit(self.active_player)
            if chosen is None:
                break
            self.active_player.pay_cost(chosen.template.cost)
            self.active_player.hand = [
                card for card in self.active_player.hand if card.instance_id != chosen.instance_id
            ]
            self.active_player.battlefield.append(BattlefieldUnit.from_card(chosen))
            self.statistics.register_unit_played(self.active_player.player_id)
            self.log(
                f"Gegner spielt {chosen.template.name} ({chosen.template.aw}/{chosen.template.vw}) "
                f"fuer {chosen.template.cost}."
            )

    def ai_declare_attackers(self) -> None:
        attackers = self.ai.choose_attackers(self.available_attackers(self.active_player))
        for attacker in attackers:
            attacker.tapped = True
        self.selected_attackers = [attacker.unit_id for attacker in attackers]
        self.statistics.register_attackers(self.active_player.player_id, len(attackers))
        if not attackers:
            self.log("Gegner greift nicht an.")
            self.end_turn()
            return
        self.block_assignments = {attacker.unit_id: [] for attacker in attackers}
        self.blocker_to_attacker.clear()
        self.phase = PHASE_DECLARE_BLOCKERS
        self.log(f"Gegner greift mit {len(attackers)} Units an. Waehle deine Blocker.")

    def handle_click(self, area: str, item_id: int) -> None:
        if area == "hand":
            self.toggle_hand_card(item_id)
            return
        if area == "player_units":
            if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
                self.toggle_attacker(item_id)
            elif self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
                self.toggle_selected_blocker(item_id)
            return
        if area == "enemy_units" and self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
            self.assign_selected_blocker(item_id)
            return
        if area == "order_blockers" and self.pending_order is not None:
            self.choose_next_block_order_item(item_id)
            return
        if area == "human_dice":
            self.choose_human_die(item_id)

    def end_turn(self) -> None:
        self.check_for_game_over()
        if self.phase == PHASE_GAME_OVER:
            return
        self.reset_combat_state()
        self.active_player_index = 1 - self.active_player_index
        self.start_turn()

    def check_for_game_over(self) -> None:
        if self.phase == PHASE_GAME_OVER:
            return
        loser = next((player for player in self.players if player.life <= 0), None)
        if loser is None:
            return
        winner = self.players[1 - loser.player_id]
        self.phase = PHASE_GAME_OVER
        self.game_over_text = f"{winner.name} gewinnt. {loser.name} hat 0 oder weniger Lebenspunkte."
        self.log(self.game_over_text)
        self.persist_game_results_once()

    def persist_game_results_once(self) -> None:
        if self.game_over_saved or self.statistics is None:
            return
        self.game_over_saved = True
        row = self.statistics.finalize_game(
            winner=self.players[1].name if self.players[0].life <= 0 else self.players[0].name,
            human_life=self.human_player.life,
            ai_life=self.ai_player.life,
        )
        summary = [
            f"Sieger: {row['winner']}",
            f"Zuege: {row['turns_played']}",
            f"Lebenspunkte: Spieler {row['human_life_end']} | Gegner {row['ai_life_end']}",
            f"Ausgespielte Units: Spieler {row['human_units_played']} | Gegner {row['ai_units_played']}",
            f"Unit-Kaempfe: {row['unit_combats']}",
            f"Zerstoerte Units: Spieler {row['human_units_destroyed']} | Gegner {row['ai_units_destroyed']}",
            f"Spielerschaden: Spieler {row['human_player_damage_dealt']} | Gegner {row['ai_player_damage_dealt']}",
            f"Durchschnittliche Wuerfelvergleiche: {row['avg_dice_comparisons_per_combat']}",
            f"CSV Spielstatistik: {self.results_path}",
            f"CSV Unit-Kaempfe: {self.unit_results_path}",
        ]
        self.game_over_summary_lines = summary
        print("\nSpielende")
        for line in summary:
            print(line)

    def current_prompt(self) -> str:
        if self.phase == PHASE_MULLIGAN:
            return "Waehle Karten fuer den Mulligan oder behalte die Starthand."
        if self.phase == PHASE_RESOURCE:
            return "Lege optional eine Ressource und gehe dann in die Hauptphase."
        if self.phase == PHASE_MAIN:
            return "Spiele Units aus, beginne den Kampf oder beende den Zug."
        if self.phase == PHASE_DECLARE_ATTACKERS:
            return "Waehle Angreifer und bestaetige."
        if self.phase == PHASE_DECLARE_BLOCKERS:
            return "Waehle einen Blocker und klicke danach auf einen Angreifer."
        if self.phase == PHASE_ORDER_BLOCKERS:
            return "Lege die Reihenfolge fuer mehrere Blocker fest."
        if self.phase == PHASE_DICE_BATTLE:
            return "Waehle deinen Wuerfel fuer den aktuellen Vergleich."
        return self.game_over_text

    def get_button_specs(self) -> List[ButtonSpec]:
        if self.phase == PHASE_MULLIGAN:
            return [
                ButtonSpec("Mulligan bestaetigen", True, "confirm_mulligan"),
                ButtonSpec("Hand behalten", True, "keep_mulligan"),
                ButtonSpec("Beenden", True, "exit_game"),
            ]
        if self.phase == PHASE_GAME_OVER:
            return [
                ButtonSpec("Neue Partie", True, "new_game"),
                ButtonSpec("Beenden", True, "exit_game"),
            ]
        if not self.active_player.is_human:
            return [ButtonSpec("Beenden", True, "exit_game")]

        buttons: List[ButtonSpec] = []
        if self.phase == PHASE_RESOURCE:
            buttons.append(
                ButtonSpec(
                    "Als Ressource",
                    bool(self.selected_hand_ids) and not self.active_player.resource_played_this_turn,
                    "play_resource",
                )
            )
            buttons.append(ButtonSpec("Zur Hauptphase", True, "to_main"))
        elif self.phase == PHASE_MAIN:
            selected = self.get_selected_hand_card()
            can_play = selected is not None and self.active_player.can_pay(selected.template.cost)
            buttons.append(ButtonSpec("Unit spielen", can_play, "play_unit"))
            buttons.append(ButtonSpec("Kampfphase", True, "to_combat"))
            buttons.append(ButtonSpec("Zug beenden", True, "end_turn"))
        elif self.phase == PHASE_DECLARE_ATTACKERS:
            buttons.append(ButtonSpec("Angriff bestaetigen", True, "confirm_attackers"))
        elif self.phase == PHASE_DECLARE_BLOCKERS:
            buttons.append(ButtonSpec("Blocker bestaetigen", True, "confirm_blocks"))
            buttons.append(ButtonSpec("Blocker loeschen", True, "clear_blocks"))
        elif self.phase == PHASE_ORDER_BLOCKERS:
            ready = self.pending_order is not None and len(self.pending_order.chosen_order) == len(self.pending_order.blocker_ids)
            buttons.append(ButtonSpec("Reihenfolge speichern", ready, "confirm_order"))
            buttons.append(ButtonSpec("Reihenfolge reset", True, "reset_order"))
        buttons.append(ButtonSpec("Beenden", True, "exit_game"))
        return buttons
