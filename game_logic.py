from __future__ import annotations

from datetime import datetime
from pathlib import Path
from random import Random
from typing import Dict, List, Optional

from ai_logic import SimpleAI
from cards import build_card_templates, build_test_deck
from cards.registry import get_deck_templates
from config import AI_DECK_NAME, ENABLE_MULLIGAN, GAME_MODE, HUMAN_DECK_NAME, STARTING_HAND_SIZE
from models import (
    Ability,
    BattlefieldCreature,
    ButtonSpec,
    CardCost,
    CardInstance,
    DieResult,
    DiceRoundRecord,
    Element,
    PendingComparison,
    PendingForcedDiscard,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_SUMMONING,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
    PHASE_RECYCLE_PAYMENT,
    PHASE_RESOURCE,
    PendingBlockOrder,
    PendingDiceBattle,
    PendingRecyclePayment,
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
        end_dice_battle,
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
        self.pending_recycle_payment: Optional[PendingRecyclePayment] = None
        self.pending_forced_discard: Optional[PendingForcedDiscard] = None
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

    def queue_creature_damage_event(
        self,
        target_role: str,
        amount: int,
        source_element: Element,
    ) -> None:
        self.pending_visual_events.append(
            {
                "type": "creature_damage",
                "target_role": target_role,
                "amount": amount,
                "source_element": source_element,
            }
        )

    def queue_recycle_reveal_event(self, player_id: int, template_ids: List[str]) -> None:
        self.pending_visual_events.append(
            {
                "type": "recycle_reveal",
                "player_id": player_id,
                "template_ids": template_ids,
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
            player.discard_pile.clear()
            player.battlefield.clear()
            player.resources.clear()
            player.resources_played_this_turn = 0
            player.summoner_tapped = False
            player.turns_started = 0
            player.mulligan_used = False
            for _ in range(STARTING_HAND_SIZE):
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
            player.discard_pile.clear()
            player.battlefield.clear()
            player.resources.clear()
            player.resources_played_this_turn = 0
            player.summoner_tapped = False
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
                if drawn.was_recycled:
                    self.statistics.register_recycled_card_drawn(player.player_id)
                self.log(f"{player.name} zieht eine Karte.")
            else:
                self.log(f"{player.name} kann keine Karte ziehen.")
        else:
            self.log(f"{player.name} ist Startspieler und zieht im ersten Zug keine Karte.")
        player.turns_started += 1
        player.resources_played_this_turn = 0
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
        self.pending_recycle_payment = None
        self.pending_forced_discard = None
        self.combat_queue = []
        self.current_attack_index = 0
        self.current_blocker_order = []
        self.current_blocker_index = 0

    def available_attackers(self, player: PlayerState) -> List[BattlefieldCreature]:
        return [creature for creature in player.battlefield if creature.is_ready()]

    def available_blockers(self, player: PlayerState) -> List[BattlefieldCreature]:
        return [
            creature
            for creature in player.battlefield
            if creature.is_ready() and not getattr(creature, "cannot_block", False)
        ]

    def choose_cards_to_discard_for_ai(self, player: PlayerState, count: int) -> List[CardInstance]:
        if count <= 0 or not player.hand:
            return []
        return sorted(
            player.hand,
            key=lambda card: (
                card.template.cost.total_value,
                card.template.aw + card.template.vw,
                len(card.template.abilities),
            ),
        )[:count]

    def discard_cards(self, player: PlayerState, cards: List[CardInstance], source_card_name: str) -> None:
        if not cards:
            return
        card_ids = {card.instance_id for card in cards}
        player.hand = [card for card in player.hand if card.instance_id not in card_ids]
        player.discard_pile.extend(cards)
        discarded_names = ", ".join(card.template.name for card in cards)
        self.log(f"{player.name} wirft durch {source_card_name} ab: {discarded_names}.")

    def begin_forced_discard(self, target_player: PlayerState, count: int, source_card_name: str, return_phase: str) -> bool:
        required_count = min(count, len(target_player.hand))
        if required_count <= 0:
            return False
        if not target_player.is_human:
            cards = self.choose_cards_to_discard_for_ai(target_player, required_count)
            self.discard_cards(target_player, cards, source_card_name)
            return False
        self.pending_forced_discard = PendingForcedDiscard(
            target_player_id=target_player.player_id,
            required_count=required_count,
            selected_card_ids=[],
            source_card_name=source_card_name,
            return_phase=return_phase,
        )
        self.phase = PHASE_FORCED_DISCARD
        self.selected_hand_ids.clear()
        self.log(f"Wähle {required_count} Handkarte(n), die du durch {source_card_name} abwerfen musst.")
        return True

    def toggle_forced_discard_selection(self, card_id: int) -> None:
        pending = self.pending_forced_discard
        if pending is None or self.phase != PHASE_FORCED_DISCARD:
            return
        if pending.target_player_id != self.human_player.player_id:
            return
        if not any(card.instance_id == card_id for card in self.human_player.hand):
            return
        if card_id in pending.selected_card_ids:
            pending.selected_card_ids.remove(card_id)
        elif len(pending.selected_card_ids) < pending.required_count:
            pending.selected_card_ids.append(card_id)
        else:
            self.log("Es wurden bereits genug Handkarten zum Abwerfen ausgewählt.")
            return
        self.selected_hand_ids = list(pending.selected_card_ids)

    def confirm_forced_discard(self) -> None:
        pending = self.pending_forced_discard
        if pending is None or self.phase != PHASE_FORCED_DISCARD:
            return
        if pending.target_player_id != self.human_player.player_id:
            return
        if len(pending.selected_card_ids) != pending.required_count:
            self.log("Wähle genau die benötigte Anzahl an Handkarten zum Abwerfen.")
            return
        cards = [
            card
            for card in self.human_player.hand
            if card.instance_id in pending.selected_card_ids
        ]
        if len(cards) != pending.required_count:
            self.log("Mindestens eine ausgewählte Handkarte ist nicht mehr verfügbar.")
            return
        self.discard_cards(self.human_player, cards, pending.source_card_name)
        self.pending_forced_discard = None
        self.selected_hand_ids.clear()
        self.phase = pending.return_phase
        if self.active_player.is_human:
            self.auto_advance_human_summoning_phase_if_needed()

    def resolve_end_of_turn_returns(self, player: PlayerState) -> None:
        returning = [
            creature
            for creature in player.battlefield
            if getattr(creature, "return_to_deck_end_of_turn", False)
        ]
        if not returning:
            return
        returning_ids = {creature.unit_id for creature in returning}
        player.battlefield = [
            creature for creature in player.battlefield if creature.unit_id not in returning_ids
        ]
        for creature in returning:
            player.deck.append(CardInstance(self.make_instance_id(), self.templates[creature.template_id]))
        self.rng.shuffle(player.deck)
        names = ", ".join(creature.name for creature in returning)
        self.log(f"{names} wird/werden am Ende des Zuges zurück ins Deck gemischt.")

    def can_activate_summoner_draw(self, player: PlayerState) -> bool:
        return (
            player == self.active_player
            and player.is_human
            and self.phase in {PHASE_RESOURCE, PHASE_SUMMONING}
            and not player.summoner_tapped
            and bool(player.deck)
            and self.pending_recycle_payment is None
            and self.pending_forced_discard is None
        )

    def activate_summoner_draw(self, player: PlayerState) -> bool:
        if player != self.active_player:
            return False
        if player.summoner_tapped:
            self.log("Der Beschwörer ist bereits getappt.")
            return False
        if self.phase not in {PHASE_RESOURCE, PHASE_SUMMONING}:
            self.log("Der Beschwörer kann gerade nicht aktiviert werden.")
            return False
        if not player.deck:
            self.log("Es kann keine Karte gezogen werden.")
            return False
        player.summoner_tapped = True
        drawn = player.draw_card()
        if drawn is not None:
            self.statistics.register_draw(player.player_id)
            if drawn.was_recycled:
                self.statistics.register_recycled_card_drawn(player.player_id)
            self.log(f"{player.name} tappt den Beschwörer und zieht eine Karte.")
            return True
        self.log("Es kann keine Karte gezogen werden.")
        return False

    def has_playable_creature_in_hand(self, player: PlayerState) -> bool:
        return any(self.can_play_card(player, card) for card in player.hand)

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
        if battle.resolution_complete:
            return
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
            battle.resolution_complete = True
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

    def has_more_dice_battles_after_current(self) -> bool:
        battle = self.pending_dice_battle
        if battle is None:
            return False

        attacker = self.get_unit_by_id(battle.attacker_id)
        if attacker is not None and attacker.current_hp > 0:
            for blocker_id in self.current_blocker_order[self.current_blocker_index :]:
                blocker = self.get_unit_by_id(blocker_id)
                if blocker is not None and blocker.current_hp > 0:
                    return True

        for attacker_id in self.combat_queue[self.current_attack_index + 1 :]:
            next_attacker = self.get_unit_by_id(attacker_id)
            if next_attacker is None or next_attacker.current_hp <= 0:
                continue
            for blocker_id in self.block_assignments.get(attacker_id, []):
                blocker = self.get_unit_by_id(blocker_id)
                if blocker is not None and blocker.current_hp > 0:
                    return True
        return False

    def format_card_cost(self, cost: CardCost) -> str:
        if cost.resources > 0 and cost.recycle > 0:
            return f"{cost.resources} + Recycle {cost.recycle}"
        if cost.resources > 0:
            return str(cost.resources)
        return f"Recycle {cost.recycle}"

    def can_play_card(self, player: PlayerState, card: CardInstance) -> bool:
        return player.can_pay(card.template.cost)

    def begin_recycle_payment(self, card_instance_id: int) -> bool:
        if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
            return False
        card = next((existing for existing in self.active_player.hand if existing.instance_id == card_instance_id), None)
        if card is None:
            self.log("Diese Handkarte kann nicht gespielt werden.")
            return False
        if not self.can_play_card(self.active_player, card):
            self.log("Nicht genügend Ressourcen oder Recyclekosten können nicht bezahlt werden.")
            return False
        if card.template.recycle_cost <= 0:
            return self.resolve_creature_play(card)
        self.pending_recycle_payment = PendingRecyclePayment(
            card_instance_id=card.instance_id,
            required_count=card.template.recycle_cost,
            selected_resource_ids=[],
        )
        self.phase = PHASE_RECYCLE_PAYMENT
        self.selected_hand_ids = [card.instance_id]
        self.log(
            f"Wähle {card.template.recycle_cost} Ressourcen für Recycle von {card.template.name} und bestätige dann."
        )
        return True

    def toggle_recycle_resource_selection(self, resource_id: int) -> None:
        if self.pending_recycle_payment is None or self.phase != PHASE_RECYCLE_PAYMENT:
            return
        resource = next(
            (
                existing
                for existing in self.active_player.resources
                if existing.resource_id == resource_id
            ),
            None,
        )
        if resource is None:
            return
        selected = self.pending_recycle_payment.selected_resource_ids
        if resource_id in selected:
            selected.remove(resource_id)
            return
        if len(selected) >= self.pending_recycle_payment.required_count:
            self.log("Es wurden bereits genug Ressourcen für Recycle ausgewählt.")
            return
        selected.append(resource_id)

    def cancel_recycle_payment(self) -> None:
        if self.pending_recycle_payment is None:
            return
        self.pending_recycle_payment = None
        self.phase = PHASE_SUMMONING
        self.selected_hand_ids.clear()
        self.log("Recycle-Auswahl abgebrochen.")

    def confirm_recycle_payment(self) -> None:
        pending = self.pending_recycle_payment
        if pending is None or self.phase != PHASE_RECYCLE_PAYMENT:
            return
        card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
        if card is None:
            self.cancel_recycle_payment()
            return
        if len(pending.selected_resource_ids) != pending.required_count:
            self.log("Wähle genau die benötigte Anzahl an Ressourcen für Recycle.")
            return
        if not self.can_play_card(self.active_player, card):
            self.log("Die Kosten können nicht mehr vollständig bezahlt werden.")
            return
        self.pending_recycle_payment = None
        self.phase = PHASE_SUMMONING
        if not self.resolve_creature_play(card, recycle_resource_ids=list(pending.selected_resource_ids)):
            self.pending_recycle_payment = pending
            self.phase = PHASE_RECYCLE_PAYMENT
            return

    def resolve_creature_play(self, card: CardInstance, recycle_resource_ids: List[int] | None = None) -> bool:
        cost = card.template.cost
        if not self.can_play_card(self.active_player, card):
            self.log("Nicht genügend Ressourcen oder Recyclekosten können nicht bezahlt werden.")
            return False
        if cost.recycle > 0 and recycle_resource_ids is None:
            self.log("Recycle-Ressourcen wurden nicht ausgewählt.")
            return False
        if recycle_resource_ids is not None and len(recycle_resource_ids) != cost.recycle:
            self.log("Die Anzahl ausgewählter Recycle-Ressourcen ist ungültig.")
            return False
        if recycle_resource_ids is not None and len(set(recycle_resource_ids)) != len(recycle_resource_ids):
            self.log("Eine Ressource kann für Recycle nicht mehrfach ausgewählt werden.")
            return False

        available_resource_ids = {
            resource.resource_id
            for resource in self.active_player.resources
            if resource.resource_id is not None
        }
        if recycle_resource_ids is not None and any(resource_id not in available_resource_ids for resource_id in recycle_resource_ids):
            self.log("Mindestens eine ausgewählte Recycle-Ressource ist nicht mehr verfügbar.")
            return False

        tapped_resources = self.active_player.tap_resources_for_cost(cost.resources)
        if len(tapped_resources) != cost.resources:
            self.log("Nicht genügend bereite Ressourcen.")
            return False

        recycled_templates: List[str] = []
        if recycle_resource_ids:
            resources_to_recycle = [
                resource
                for resource in self.active_player.resources
                if resource.resource_id in recycle_resource_ids
            ]
            if len(resources_to_recycle) != len(recycle_resource_ids):
                self.log("Recycle konnte nicht vollständig bezahlt werden.")
                return False
            self.active_player.resources = [
                resource
                for resource in self.active_player.resources
                if resource.resource_id not in recycle_resource_ids
            ]
            recycled_cards = [
                CardInstance(self.make_instance_id(), resource.template, was_recycled=True)
                for resource in resources_to_recycle
            ]
            recycled_templates = [resource.template.template_id for resource in resources_to_recycle]
            self.active_player.deck.extend(recycled_cards)
            self.rng.shuffle(self.active_player.deck)
            self.queue_recycle_reveal_event(self.active_player.player_id, recycled_templates)
            if self.statistics is not None:
                self.statistics.register_recycle_payment(self.active_player.player_id, card.template.recycle_cost)

        self.active_player.hand = [
            existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
        ]
        self.active_player.battlefield.append(BattlefieldCreature.from_card(card))
        self.selected_hand_ids.clear()
        self.statistics.register_creature_played(
            self.active_player.player_id,
            card.template.recycle_cost,
        )
        self.log(
            f"{self.active_player.name} spielt {card.template.name} "
            f"({card.template.aw}/{card.template.vw}) für {self.format_card_cost(card.template.cost)}."
        )
        if card.template.self_damage_on_play > 0:
            self.active_player.life -= card.template.self_damage_on_play
            self.queue_player_damage_event(
                target_player_id=self.active_player.player_id,
                amount=card.template.self_damage_on_play,
                source_element=card.template.element,
            )
            self.log(
                f"{self.active_player.name} erleidet {card.template.self_damage_on_play} Schaden durch {card.template.name}."
            )
            self.check_for_game_over()
            if self.phase == PHASE_GAME_OVER:
                return True
        if card.template.opponent_damage_on_play > 0:
            self.defending_player.life -= card.template.opponent_damage_on_play
            self.queue_player_damage_event(
                target_player_id=self.defending_player.player_id,
                amount=card.template.opponent_damage_on_play,
                source_element=card.template.element,
                attacker_id=card.instance_id,
            )
            self.statistics.register_player_damage(
                self.active_player.player_id,
                card.template.opponent_damage_on_play,
            )
            self.log(
                f"{card.template.name} verursacht beim Ausspielen {card.template.opponent_damage_on_play} Schaden an {self.defending_player.name}."
            )
            self.check_for_game_over()
            if self.phase == PHASE_GAME_OVER:
                return True
        self.begin_forced_discard(
            self.active_player,
            card.template.discard_self_on_play,
            card.template.name,
            PHASE_SUMMONING,
        )
        if self.phase == PHASE_FORCED_DISCARD:
            return True
        self.begin_forced_discard(
            self.defending_player,
            card.template.discard_opponent_on_play,
            card.template.name,
            PHASE_SUMMONING,
        )
        if self.phase == PHASE_FORCED_DISCARD:
            return True
        if recycled_templates:
            recycled_names = ", ".join(self.templates[template_id].name for template_id in recycled_templates)
            self.log(f"Recycle aufgedeckt und zurück ins Deck gemischt: {recycled_names}.")
        self.auto_advance_human_summoning_phase_if_needed()
        return True

    def get_selected_hand_card(self) -> Optional[CardInstance]:
        if len(self.selected_hand_ids) != 1:
            return None
        selected_id = self.selected_hand_ids[0]
        for card in self.active_player.hand:
            if card.instance_id == selected_id:
                return card
        return None

    def toggle_hand_card(self, card_id: int) -> None:
        if self.pending_recycle_payment is not None:
            return
        if self.phase == PHASE_FORCED_DISCARD:
            self.toggle_forced_discard_selection(card_id)
            return
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
            PHASE_FORCED_DISCARD,
        }
        if self.phase == PHASE_GAME_OVER or (not self.active_player.is_human and self.phase not in human_response_phases):
            return

        if action == "play_resource":
            self.play_selected_card_as_resource()
        elif action == "to_summoning":
            self.enter_summoning_phase()
        elif action == "play_creature":
            self.play_selected_creature_card()
        elif action == "confirm_recycle":
            self.confirm_recycle_payment()
        elif action == "cancel_recycle":
            self.cancel_recycle_payment()
        elif action == "confirm_forced_discard":
            self.confirm_forced_discard()
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
        elif action == "end_dice_battle":
            self.end_dice_battle()
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
        if self.phase == PHASE_RECYCLE_PAYMENT and self.active_player.is_human:
            self.log("Zeit abgelaufen. Recycle-Auswahl wurde abgebrochen.")
            self.cancel_recycle_payment()
            return
        if self.phase == PHASE_FORCED_DISCARD and self.pending_forced_discard is not None:
            required = self.pending_forced_discard.required_count
            chosen = self.human_player.hand[:required]
            self.pending_forced_discard.selected_card_ids = [card.instance_id for card in chosen]
            self.selected_hand_ids = list(self.pending_forced_discard.selected_card_ids)
            self.log("Zeit abgelaufen. Handkarten wurden automatisch abgeworfen.")
            self.confirm_forced_discard()
            return
        if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
            self.log("Zeit abgelaufen. Kein Angriff deklariert.")
            self.confirm_attackers()
            return
        if self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
            self.log("Zeit abgelaufen. Keine Blocker deklariert.")
            self.finish_block_assignment()

    def play_selected_card_as_resource(self) -> None:
        if self.phase != PHASE_RESOURCE or self.active_player.resources_played_this_turn >= 2:
            return
        card = self.get_selected_hand_card()
        if card is None:
            self.log("Keine Handkarte als Ressource ausgewählt.")
            return
        self.play_hand_card_as_resource(card.instance_id)

    def play_hand_card_as_resource(self, card_id: int) -> None:
        if self.phase != PHASE_RESOURCE or self.active_player.resources_played_this_turn >= 2 or not self.active_player.is_human:
            return
        card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
        if card is None:
            self.log("Diese Handkarte kann nicht als Ressource gespielt werden.")
            return
        self.active_player.hand = [
            existing for existing in self.active_player.hand if existing.instance_id != card.instance_id
        ]
        self.active_player.resources.append(ResourceCard(template=card.template, resource_id=card.instance_id))
        self.active_player.resources_played_this_turn += 1
        self.selected_hand_ids.clear()
        self.statistics.register_resource_played(self.active_player.player_id)
        self.log(f"{self.active_player.name} legt {card.template.name} als Ressource.")
        if self.active_player.resources_played_this_turn >= 2:
            self.enter_summoning_phase()

    def play_selected_creature_card(self) -> None:
        if self.phase != PHASE_SUMMONING:
            return
        card = self.get_selected_hand_card()
        if card is None:
            self.log("Keine Kreatur-Karte ausgewählt.")
            return
        self.begin_recycle_payment(card.instance_id)

    def play_hand_card_as_creature(self, card_id: int) -> None:
        if self.phase != PHASE_SUMMONING or not self.active_player.is_human:
            return
        self.begin_recycle_payment(card_id)




