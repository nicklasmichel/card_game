from __future__ import annotations

from datetime import datetime
from pathlib import Path
from random import Random
from typing import Dict, List, Optional

from ai_logic import SimpleAI
from cards import build_card_templates, build_test_deck
from cards.registry import get_deck_templates
from config import AI_DECK_NAME, ENABLE_MULLIGAN, GAME_MODE, HUMAN_DECK_NAME
from models import (
    Ability,
    BattlefieldCreature,
    ButtonSpec,
    CardInstance,
    DieResult,
    DiceRoundRecord,
    Element,
    PendingComparison,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_SUMMONING,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
    PHASE_RESOURCE,
    PendingBlockOrder,
    PendingDiceBattle,
    PlayerState,
    ResourceCard,
)
from game_statistics import CREATURE_RESULTS_PATH, GAME_RESULTS_PATH, GameStatistics


class GameEngine:
    from engine.combat import (
        advance_combat_resolution,
        ai_assign_blocks,
        apply_ai_adaptation_if_needed,
        apply_comparison_result,
        apply_trample_if_needed,
        begin_attack_declaration,
        begin_combat_resolution,
        choose_human_die,
        choose_next_block_order_item,
        cleanup_destroyed_units,
        clear_block_assignments,
        confirm_attackers,
        confirm_block_order,
        finalize_or_continue_dice_battle,
        finish_block_assignment,
        get_human_combat_creature,
        human_can_use_adaptation,
        resolve_pending_comparison,
        start_dice_battle,
        toggle_attacker,
        toggle_blocker_assignment,
        toggle_selected_attack_target,
    )
    from engine.interface import (
        ai_declare_attackers,
        ai_play_creatures,
        ai_play_resource,
        check_for_game_over,
        current_prompt,
        end_turn,
        get_button_specs,
        handle_click,
        persist_game_results_once,
        process_ai_turn,
    )

    def __init__(self) -> None:
        self.templates = build_card_templates()
        self.players: List[PlayerState] = []
        self.active_player_index = 0
        self.starting_player_id = 0
        self.turn_number = 0
        self.phase = PHASE_MULLIGAN if ENABLE_MULLIGAN else PHASE_RESOURCE
        self.game_over_text = ""
        self.log_messages: List[str] = []
        self.game_over_summary_lines: List[str] = []
        self.results_path = Path.cwd() / GAME_RESULTS_PATH
        self.creature_results_path = Path.cwd() / CREATURE_RESULTS_PATH

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
        self.selected_attack_target_id: Optional[int] = None
        self.block_assignments: Dict[int, List[int]] = {}
        self.blocker_to_attackers: Dict[int, List[int]] = {}
        self.pending_order: Optional[PendingBlockOrder] = None
        self.pending_dice_battle: Optional[PendingDiceBattle] = None
        self.combat_queue: List[int] = []
        self.current_attack_index = 0
        self.current_blocker_order: List[int] = []
        self.current_blocker_index = 0
        self.combat_id_counter = 0
        self.ai_turn_initialized = False
        self.exit_requested = False
        self.pending_visual_events: List[dict] = []

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

    def queue_player_damage_event(
        self,
        target_player_id: int,
        amount: int,
        source_element: Element,
        attacker_id: int | None = None,
    ) -> None:
        self.pending_visual_events.append(
            {
                "type": "player_damage",
                "target_player_id": target_player_id,
                "amount": amount,
                "source_element": source_element,
                "attacker_id": attacker_id,
            }
        )

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
        deck_names = {
            0: HUMAN_DECK_NAME,
            1: AI_DECK_NAME,
        }
        self.log_messages.clear()
        self.game_over_summary_lines.clear()
        self.game_over_text = ""
        self.turn_number = 0
        self.phase = PHASE_MULLIGAN
        self.game_over_saved = False
        self.exit_requested = False
        self.pending_visual_events.clear()
        self.reset_combat_state()
        if GAME_MODE == "test_combat":
            self.start_test_combat()
            return

        for player in self.players:
            player.summoner_key = deck_names[player.player_id]
            player.life = 20
            player.deck = build_test_deck(deck_names[player.player_id], self.templates, self.make_instance_id)
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
        self.selected_hand_ids.clear()
        if ENABLE_MULLIGAN:
            self.apply_ai_mulligan()
            self.phase = PHASE_MULLIGAN
            self.log("Wähle beliebige Karten für deinen einmaligen Mulligan oder behalte die Hand.")
        else:
            self.log("Mulligan ist deaktiviert. Das Spiel startet direkt.")
            self.begin_first_turn()

    def start_test_combat(self) -> None:
        for player in self.players:
            player.summoner_key = HUMAN_DECK_NAME if player.player_id == 0 else AI_DECK_NAME
            player.life = 20
            player.deck.clear()
            player.hand.clear()
            player.battlefield.clear()
            player.resources.clear()
            player.resource_played_this_turn = False
            player.turns_started = 0
            player.mulligan_used = False

        human_template = self.rng.choice(get_deck_templates(HUMAN_DECK_NAME, self.templates))
        ai_template = self.rng.choice(get_deck_templates(AI_DECK_NAME, self.templates))
        human_card = CardInstance(self.make_instance_id(), human_template)
        ai_card = CardInstance(self.make_instance_id(), ai_template)
        human_creature = BattlefieldCreature.from_card(human_card)
        ai_creature = BattlefieldCreature.from_card(ai_card)
        human_creature.tapped = False
        human_creature.summoning_sick = False
        ai_creature.tapped = False
        ai_creature.summoning_sick = False
        self.human_player.battlefield = [human_creature]
        self.ai_player.battlefield = [ai_creature]
        self.active_player_index = 0
        self.starting_player_id = 0
        self.turn_number = 1
        self.phase = PHASE_DICE_BATTLE
        self.statistics = GameStatistics(
            game_id=self.game_id,
            seed=self.seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            start_player=self.human_player.name,
            player_names={0: "Spieler", 1: "Gegner"},
        )
        self.log(f"Testkampf gestartet: {human_creature.name} gegen {ai_creature.name}.")
        self.start_dice_battle(human_creature.unit_id, ai_creature.unit_id)

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
        self.log(f"Gegner führt einen Mulligan mit {len(to_replace)} Karten durch.")

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
            self.log("Spieler behält seine Starthand.")
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
        self.selected_attack_target_id = None
        self.block_assignments = {}
        self.blocker_to_attackers = {}
        self.pending_order = None
        self.pending_dice_battle = None
        self.combat_queue = []
        self.current_attack_index = 0
        self.current_blocker_order = []
        self.current_blocker_index = 0

    def available_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
        return [creature for creature in player.battlefield if creature.is_ready()]

    def available_blockers(self, player: PlayerState) -> List[BattlefieldCreature]:
        return [creature for creature in player.battlefield if creature.is_ready()]

    def has_playable_creature_in_hand(self, player: PlayerState) -> bool:
        return any(player.can_pay(card.template.cost) for card in player.hand)

    def enter_summoning_phase(self) -> None:
        self.phase = PHASE_SUMMONING
        self.log("Beschwörungsphase begonnen.")
        self.auto_advance_human_summoning_phase_if_needed()

    def auto_advance_human_summoning_phase_if_needed(self) -> None:
        if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
            return
        if self.has_playable_creature_in_hand(self.active_player):
            return
        self.log("Keine Kreatur kann ausgespielt werden. Kampfphase beginnt automatisch.")
        self.begin_attack_declaration()

    def auto_resolve_human_no_blockers_if_needed(self) -> None:
        if self.phase != PHASE_DECLARE_BLOCKERS:
            return
        if not self.defending_player.is_human:
            return
        if self.available_blockers(self.defending_player):
            return
        self.log("Keine Kreaturen können blocken. Schaden geht automatisch durch.")
        self.finish_block_assignment()

    def resolve_stalled_dice_battle_if_needed(self) -> None:
        if self.phase != PHASE_DICE_BATTLE or self.pending_dice_battle is None:
            return
        battle = self.pending_dice_battle
        if battle.pending_comparison is not None:
            if not battle.pending_comparison.human_can_adapt:
                self.resolve_pending_comparison(use_human_adaptation=False)
            return
        human_is_attacker = battle.attacker_owner == self.human_player.player_id
        human_dice = battle.attacker_dice if human_is_attacker else battle.blocker_dice
        enemy_dice = battle.blocker_dice if human_is_attacker else battle.attacker_dice
        if any(not die.used for die in human_dice) and any(not die.used for die in enemy_dice):
            return
        attacker = self.get_unit_by_id(battle.attacker_id)
        blocker = self.get_unit_by_id(battle.blocker_id)
        if attacker is None or blocker is None:
            self.pending_dice_battle = None
            self.advance_combat_resolution()
            return
        self.finalize_or_continue_dice_battle(battle, attacker, blocker)

    def get_creature_by_id(self, creature_id: int) -> Optional[BattlefieldCreature]:
        for player in self.players:
            for creature in player.battlefield:
                if creature.unit_id == creature_id:
                    return creature
        return None

    def get_unit_by_id(self, unit_id: int) -> Optional[BattlefieldCreature]:
        return self.get_creature_by_id(unit_id)

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
        if self.active_player.is_human and self.phase in {PHASE_RESOURCE, PHASE_SUMMONING}:
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

        human_response_phases = {
            PHASE_DECLARE_BLOCKERS,
            PHASE_ORDER_BLOCKERS,
            PHASE_DICE_BATTLE,
        }
        if self.phase == PHASE_GAME_OVER or (not self.active_player.is_human and self.phase not in human_response_phases):
            return

        if action == "play_resource":
            self.play_selected_card_as_resource()
        elif action == "to_summoning":
            self.enter_summoning_phase()
        elif action == "play_creature":
            self.play_selected_creature_card()
        elif action == "to_combat":
            self.begin_attack_declaration()
        elif action == "confirm_attackers":
            self.confirm_attackers()
        elif action == "clear_blocks":
            self.clear_block_assignments()
        elif action == "confirm_blocks":
            self.finish_block_assignment()
        elif action == "skip_blocks":
            self.log("Keine Blocker zugewiesen. Schaden wird durchgelassen.")
            self.finish_block_assignment()
        elif action == "reset_order" and self.pending_order is not None:
            self.pending_order.chosen_order.clear()
            self.log("Blockreihenfolge zurückgesetzt.")
        elif action == "confirm_order":
            self.confirm_block_order()
        elif action == "use_adaptation":
            self.resolve_pending_comparison(use_human_adaptation=True)
        elif action == "resolve_comparison":
            self.resolve_pending_comparison(use_human_adaptation=False)
        elif action == "end_turn":
            self.end_turn()

    def handle_human_timeout(self) -> None:
        if self.phase == PHASE_MULLIGAN:
            self.log("Zeit abgelaufen. Spieler behält seine Starthand.")
            self.apply_human_mulligan()
            return
        if self.phase == PHASE_RESOURCE and self.active_player.is_human:
            self.log("Zeit abgelaufen. Keine Ressource gespielt.")
            self.enter_summoning_phase()
            return
        if self.phase == PHASE_SUMMONING and self.active_player.is_human:
            self.log("Zeit abgelaufen. Keine Kreatur gespielt.")
            self.begin_attack_declaration()
            return
        if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
            self.log("Zeit abgelaufen. Kein Angriff deklariert.")
            self.confirm_attackers()
            return
        if self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
            self.log("Zeit abgelaufen. Keine Blocker deklariert.")
            self.finish_block_assignment()

    def play_selected_card_as_resource(self) -> None:
        if self.phase != PHASE_RESOURCE or self.active_player.resource_played_this_turn:
            return
        card = self.get_selected_hand_card()
        if card is None:
            self.log("Keine Handkarte als Ressource ausgewählt.")
            return
        self.play_hand_card_as_resource(card.instance_id)

    def play_hand_card_as_resource(self, card_id: int) -> None:
        if self.phase != PHASE_RESOURCE or self.active_player.resource_played_this_turn or not self.active_player.is_human:
            return
        card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
        if card is None:
            self.log("Diese Handkarte kann nicht als Ressource gespielt werden.")
            return
        self.active_player.hand = [
            existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
        ]
        self.active_player.resources.append(ResourceCard(template=card.template))
        self.active_player.resource_played_this_turn = True
        self.selected_hand_ids.clear()
        self.statistics.register_resource_played(self.active_player.player_id)
        self.log(f"{self.active_player.name} legt {card.template.name} als Ressource.")
        self.enter_summoning_phase()

    def play_selected_creature_card(self) -> None:
        if self.phase != PHASE_SUMMONING:
            return
        card = self.get_selected_hand_card()
        if card is None:
            self.log("Keine Kreatur-Karte ausgewählt.")
            return
        self.play_hand_card_as_creature(card.instance_id)

    def play_hand_card_as_creature(self, card_id: int) -> None:
        if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
            return
        card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
        if card is None:
            self.log("Diese Handkarte kann nicht als Kreatur gespielt werden.")
            return
        if not self.active_player.pay_cost(card.template.cost):
            self.log("Nicht genügend Ressourcen.")
            return
        self.active_player.hand = [
            existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
        ]
        self.active_player.battlefield.append(BattlefieldCreature.from_card(card))
        self.selected_hand_ids.clear()
        self.statistics.register_creature_played(self.active_player.player_id)
        self.log(
            f"{self.active_player.name} spielt {card.template.name} "
            f"({card.template.aw}/{card.template.vw}) für {card.template.cost}."
        )
        self.auto_advance_human_summoning_phase_if_needed()




