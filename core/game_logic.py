from __future__ import annotations

from datetime import datetime
from pathlib import Path
from random import Random
from typing import Dict, List, Optional

from core.ai_logic import SimpleAI
from cards import build_card_templates, build_test_deck
from cards.registry import get_deck_templates
from core.config import AI_DECK_NAME, ENABLE_MULLIGAN, GAME_MODE, HUMAN_DECK_NAME, STARTING_HAND_SIZE
from core.models import (
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
from stats import CREATURE_RESULTS_PATH, GAME_RESULTS_PATH, GameStatistics


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
    from engine.flow import (
        apply_ai_mulligan,
        apply_human_mulligan,
        auto_advance_human_summoning_phase_if_needed,
        auto_resolve_human_no_blockers_if_needed,
        available_attackers,
        available_blockers,
        begin_first_turn,
        begin_forced_discard,
        choose_cards_to_discard_for_ai,
        confirm_forced_discard,
        discard_cards,
        enter_summoning_phase,
        get_creature_by_id,
        get_selected_hand_card,
        get_unit_by_id,
        get_unit_owner,
        handle_action,
        handle_human_timeout,
        has_more_dice_battles_after_current,
        has_playable_creature_in_hand,
        resolve_stalled_dice_battle_if_needed,
        start_turn,
        toggle_forced_discard_selection,
        toggle_hand_card,
    )
    from engine.resources import (
        activate_summoner_draw,
        begin_recycle_payment,
        can_activate_summoner_draw,
        can_play_card,
        cancel_recycle_payment,
        confirm_recycle_payment,
        format_card_cost,
        play_hand_card_as_creature,
        play_hand_card_as_resource,
        play_selected_card_as_resource,
        play_selected_creature_card,
        resolve_creature_play,
        resolve_end_of_turn_returns,
        toggle_recycle_resource_selection,
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

