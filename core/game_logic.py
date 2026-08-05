from __future__ import annotations

from datetime import datetime
from random import Random
from typing import Dict, List, Optional

from core.ai_logic import SimpleAI
from cards import build_card_templates, build_test_deck, validate_deck_definitions
from cards.registry import get_deck_templates
from core.config import AI_DECK_NAME, ENABLE_MULLIGAN, GAME_MODE, HUMAN_DECK_NAME, STARTING_HAND_SIZE
from core.models import (
    Ability,
    BattlefieldCreature,
    ButtonSpec,
    CardCost,
    CardInstance,
    CardType,
    DieResult,
    DiceRoundRecord,
    Element,
    PendingComparison,
    PendingDirectAttack,
    PendingForcedDiscard,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
    PHASE_REACTION,
    PHASE_RECYCLE_PAYMENT,
    PHASE_SPELL_TARGETING,
    PendingBlockOrder,
    PendingDiceBattle,
    PendingRecyclePayment,
    PendingSpellCast,
    PlayerState,
    ReactionContext,
    ResourceCard,
    SpellTargetRef,
    StackItem,
)
from stats import CREATURE_RESULTS_PATH, GAME_RESULTS_PATH, LOG_PATH, GameStatistics


class GameEngine:
    from engine.combat import (
        advance_combat_resolution,
        advance_after_attackers_declared,
        advance_after_blockers_declared,
        ai_assign_blocks,
        auto_assign_required_blockers,
        begin_pre_first_combat_window,
        apply_ai_adaptation_if_needed,
        apply_comparison_result,
        apply_trample_if_needed,
        begin_attack_declaration,
        begin_combat_resolution,
        begin_next_pending_direct_attack,
        can_creature_block_attacker,
        choose_human_die,
        choose_next_block_order_item,
        cleanup_destroyed_units,
        continue_pending_comparison_after_reaction,
        clear_block_assignments,
        confirm_attackers,
        confirm_block_order,
        end_dice_battle,
        finish_post_comparison_priority_window,
        finalize_or_continue_dice_battle,
        finish_block_assignment,
        resume_dice_battle_after_roll_window,
        get_attackers_die_bonus,
        get_human_combat_creature,
        human_can_use_adaptation,
        prepare_provoke_assignments,
        resolve_pending_direct_attack_after_reaction,
        resolve_pending_comparison,
        resume_post_comparison_resolution,
        start_dice_battle,
        toggle_provoke_target,
        toggle_attacker,
        toggle_blocker_assignment,
        toggle_selected_attack_target,
    )
    from engine.interface import (
        ai_declare_attackers,
        ai_play_creatures,
        ai_play_resource,
        check_for_game_over,
        clear_pending_ai_action,
        current_prompt,
        execute_prepared_ai_action,
        end_turn,
        get_button_specs,
        handle_click,
        has_pending_ai_action,
        persist_game_results_once,
        prepare_ai_turn_action,
        process_ai_turn,
    )
    from engine.flow import (
        apply_ai_mulligan,
        apply_human_mulligan,
        auto_resolve_human_no_blockers_if_needed,
        available_attackers,
        available_blockers,
        begin_first_turn,
        begin_forced_discard,
        clear_end_of_turn_temporary_effects,
        choose_cards_to_discard_for_ai,
        confirm_forced_discard,
        discard_cards,
        draw_card_for_player,
        enter_combat_or_second_main,
        enter_second_main_phase,
        get_creature_by_id,
        get_selected_hand_card,
        get_mandatory_attackers,
        get_unit_by_id,
        get_unit_owner,
        handle_action,
        handle_human_timeout,
        has_more_dice_battles_after_current,
        has_playable_creature_in_hand,
        is_own_main_phase,
        lose_game_from_empty_deck,
        resolve_stalled_dice_battle_if_needed,
        start_turn,
        toggle_forced_discard_selection,
        toggle_hand_card,
    )
    from engine.resources import (
        activate_summoner_draw,
        begin_recycle_payment,
        can_activate_summoner_draw,
        cancel_recycle_payment,
        confirm_recycle_payment,
        format_card_cost,
        get_card_cost_to_pay,
        handle_creature_player_damage_triggers,
        play_hand_card_in_summoning_zone,
        play_hand_card_as_creature,
        play_hand_card_as_resource,
        play_selected_card_as_resource,
        play_selected_creature_card,
        register_hand_card_played,
        resolve_creature_play,
        resolve_end_of_turn_returns,
        toggle_recycle_resource_selection,
    )
    from engine.spells import (
        begin_spell_from_hand,
        begin_spell_cast,
        begin_spell_cast_from_card,
        begin_reaction_window,
        build_spell_reaction_context,
        begin_general_spell_window,
        begin_triggered_reaction_window,
        can_play_card,
        can_react_with_card,
        cancel_pending_spell_cast,
        cleanup_destroyed_units_for_spells,
        commit_spell_cast,
        confirm_pending_spell_cast,
        deal_spell_damage_to_player,
        describe_pending_spell_requirements,
        destroy_creature_immediately,
        finish_reaction_window,
        finish_spell_resolution_after_reaction,
        get_card_from_pending_spell,
        get_current_attacker_creatures,
        get_valid_discard_creature_target_refs,
        get_context_die_for_player,
        get_open_die_target_refs,
        get_player_by_id,
        get_player_combat_dice,
        get_reaction_window_profile,
        get_reaction_window_description,
        get_reaction_window_title,
        has_valid_open_die_target,
        has_valid_verwehung_target,
        has_valid_attacker_combat_bonus_targets,
        has_valid_jagdwind_target,
        has_valid_combat_die_target,
        is_general_spell_window_trigger,
        is_spell_card,
        pass_reaction,
        pending_spell_ready,
        reaction_window_allows_die_targets,
        reaction_window_is_combat_window,
        reaction_window_shows_stack_preview,
        remove_creature_from_combat,
        clear_open_die_targets,
        resolve_spell_stack_to,
        resolve_stack_item,
        resolve_target_discard_card,
        resolve_target_discard_card_for_controller,
        resolve_target_open_die,
        resolve_target_creature,
        resume_stack_resolution,
        select_pending_spell_keyword,
        select_spell_combat_die,
        select_spell_target_ref,
        set_open_die_targets,
        toggle_pending_spell_recycle_resource,
    )
    from engine.turns import (
        clear_combat_temporary_effects,
    )

    def __init__(self) -> None:
        self.templates = build_card_templates()
        validate_deck_definitions(self.templates)
        self.players: List[PlayerState] = []
        self.active_player_index = 0
        self.starting_player_id = 0
        self.turn_number = 0
        self.phase = PHASE_MULLIGAN if ENABLE_MULLIGAN else PHASE_MAIN_1
        self.game_over_text = ""
        self.log_messages: List[str] = []
        self.game_over_summary_lines: List[str] = []
        self.results_path = GAME_RESULTS_PATH
        self.creature_results_path = CREATURE_RESULTS_PATH
        self.log_path = LOG_PATH

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
        self.selected_provoke_attacker_id: Optional[int] = None
        self.selected_attack_target_id: Optional[int] = None
        self.block_assignments: Dict[int, List[int]] = {}
        self.blocker_to_attackers: Dict[int, List[int]] = {}
        self.provoke_assignments: Dict[int, int] = {}
        self.pending_order: Optional[PendingBlockOrder] = None
        self.pending_dice_battle: Optional[PendingDiceBattle] = None
        self.pending_recycle_payment: Optional[PendingRecyclePayment] = None
        self.pending_forced_discard: Optional[PendingForcedDiscard] = None
        self.pending_spell_cast: Optional[PendingSpellCast] = None
        self.spell_stack: List[StackItem] = []
        self.reaction_context: Optional[ReactionContext] = None
        self.reaction_priority_player_id: Optional[int] = None
        self.reaction_pass_count = 0
        self.reaction_base_stack_size = 0
        self.reaction_resume_phase = PHASE_MAIN_1
        self.reaction_continuation = None
        self.pending_stack_resolution_base_size = 0
        self.pending_stack_resolution_continuation = None
        self.resolving_stack = False
        self.pending_post_comparison = None
        self.pending_direct_attack: Optional[PendingDirectAttack] = None
        self.pending_direct_attacks: List[PendingDirectAttack] = []
        self.combat_queue: List[int] = []
        self.current_attack_index = 0
        self.current_blocker_order: List[int] = []
        self.current_blocker_index = 0
        self.blocked_attackers: set[int] = set()
        self.combat_id_counter = 0
        self.ai_turn_initialized = False
        self.pending_ai_action: Optional[dict] = None
        self.exit_requested = False
        self.pending_visual_events: List[dict] = []
        self.creatures_died_this_turn = 0
        self.next_open_die_id = 1
        self.open_die_targets: Dict[int, dict] = {}

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

    def get_own_flying_attack_aura_bonus(self, player: PlayerState) -> int:
        return sum(
            getattr(creature, "own_flying_attack_aura", 0)
            for creature in player.battlefield
            if creature.current_hp > 0
        )

    def get_creature_stat_bonuses(self, creature: BattlefieldCreature) -> tuple[int, int]:
        owner = self.get_unit_owner(creature.unit_id)
        if owner is None:
            return 0, 0
        flying_aw_bonus = self.get_own_flying_attack_aura_bonus(owner)
        if flying_aw_bonus <= 0:
            return 0, 0
        aw_bonus = flying_aw_bonus if creature.has_ability(Ability.FLYING) else 0
        vw_bonus = 0
        return aw_bonus, vw_bonus

    def get_creature_attack_value(self, creature: BattlefieldCreature) -> int:
        aw_bonus, _ = self.get_creature_stat_bonuses(creature)
        return (
            creature.aw
            + getattr(creature, "temporary_aw_bonus", 0)
            + getattr(creature, "temporary_combat_aw_bonus", 0)
            + aw_bonus
        )

    def get_creature_defense_value(self, creature: BattlefieldCreature) -> int:
        _, vw_bonus = self.get_creature_stat_bonuses(creature)
        return creature.vw + vw_bonus

    def get_creature_current_hp(self, creature: BattlefieldCreature) -> int:
        _, vw_bonus = self.get_creature_stat_bonuses(creature)
        return creature.current_hp + vw_bonus

    def is_creature_destroyed(self, creature: BattlefieldCreature) -> bool:
        return self.get_creature_current_hp(creature) <= 0

    @property
    def defending_player(self) -> PlayerState:
        return self.players[1 - self.active_player_index]

    def make_instance_id(self) -> int:
        instance_id = self.next_instance_id
        self.next_instance_id += 1
        return instance_id

    def log(self, message: str) -> None:
        self.log_messages.append(message)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(message + "\n")

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
            player.summoner_passive_draw_used_this_turn = False
            player.creature_cost_reduction_this_turn = 0
            player.attackers_die_bonus_this_turn = 0
            player.direct_attack_damage_multiplier_this_turn.clear()
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
            player.summoner_passive_draw_used_this_turn = False
            player.creature_cost_reduction_this_turn = 0
            player.attackers_die_bonus_this_turn = 0
            player.direct_attack_damage_multiplier_this_turn.clear()
            player.summoner_tapped = False
            player.turns_started = 0
            player.mulligan_used = False

        human_template = self.rng.choice(get_deck_templates(HUMAN_DECK_NAME, self.templates))
        ai_template = self.rng.choice(get_deck_templates(AI_DECK_NAME, self.templates))
        while human_template.card_type != CardType.CREATURE:
            human_template = self.rng.choice(get_deck_templates(HUMAN_DECK_NAME, self.templates))
        while ai_template.card_type != CardType.CREATURE:
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
        self.selected_provoke_attacker_id = None
        self.selected_attack_target_id = None
        self.block_assignments = {}
        self.blocker_to_attackers = {}
        self.provoke_assignments = {}
        self.pending_order = None
        self.pending_dice_battle = None
        self.pending_recycle_payment = None
        self.pending_forced_discard = None
        self.pending_spell_cast = None
        self.spell_stack = []
        self.reaction_context = None
        self.reaction_priority_player_id = None
        self.reaction_pass_count = 0
        self.reaction_base_stack_size = 0
        self.reaction_resume_phase = PHASE_MAIN_1
        self.reaction_continuation = None
        self.pending_stack_resolution_base_size = 0
        self.pending_stack_resolution_continuation = None
        self.resolving_stack = False
        self.pending_post_comparison = None
        self.pending_direct_attack = None
        self.pending_direct_attacks = []
        self.combat_queue = []
        self.current_attack_index = 0
        self.current_blocker_order = []
        self.current_blocker_index = 0
        self.blocked_attackers = set()
        self.pending_ai_action = None

