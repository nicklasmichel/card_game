from __future__ import annotations

from datetime import datetime
from random import Random
from threading import Lock
from typing import Dict, List, Optional

from core.ai_logic import SimpleAI
from core.builder_rules import BUILDER_CREATURE_CAP, BUILDER_MAX_RESOURCES
from core.config import STARTING_LIFE
from core.models import (
    Ability,
    BattlefieldCreature,
    ButtonSpec,
    CardCost,
    CardInstance,
    CardType,
    DiceRoundRecord,
    Element,
    PendingBuilderAbilityUse,
    PendingBuilderCreatureBuild,
    PendingDirectAttack,
    PHASE_BUILDER_ABILITY,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PendingDiceBattle,
    PlayerState,
    ResourceCard,
)
from stats import CREATURE_RESULTS_PATH, GAME_RESULTS_PATH, LOG_PATH, GameStatistics


class GameEngine:
    from engine.builder import (
        _can_grant_builder_ability_to_creature,
        adjust_builder_creature_stat,
        begin_builder_creature_build,
        begin_builder_ability_use,
        builder_draw_ability_card,
        builder_add_resource,
        builder_pass_main_action,
        builder_pending_ability_ready,
        builder_creature_build_cost,
        builder_creature_build_is_valid,
        can_builder_use_ability_card,
        get_builder_preview_creature,
        get_builder_card_ability,
        builder_mode_active,
        builder_remaining_ready_resources,
        builder_resource_template,
        builder_spend_ready_resources,
        cancel_builder_ability_use,
        choose_builder_ability_mode,
        toggle_builder_creature_ability,
        cancel_builder_creature_build,
        can_builder_add_resource,
        can_builder_open_creature_build,
        can_take_builder_main_action,
        confirm_builder_creature_build,
        create_builder_creature,
        discard_builder_ability_card,
        finish_builder_main_action,
        finish_builder_turn_after_combat,
        initialize_builder_game,
        resolve_builder_ability_use,
        select_builder_ability_target,
        skip_builder_ability_phase,
        start_builder_turn,
    )
    BUILDER_CREATURE_CAP = BUILDER_CREATURE_CAP
    BUILDER_MAX_RESOURCES = BUILDER_MAX_RESOURCES

    from engine.combat import (
        advance_combat_resolution,
        advance_after_attackers_declared,
        _apply_pending_direct_attack,
        ai_assign_blocks,
        begin_post_combat_window,
        begin_pre_first_combat_window,
        begin_attack_declaration,
        begin_combat_resolution,
        begin_next_pending_direct_attack,
        can_creature_be_forced_to_block_attacker,
        can_creature_block_attacker,
        cleanup_destroyed_units,
        clear_block_assignments,
        confirm_attackers,
        create_pending_dice_battle,
        get_legal_enraged_targets,
        set_enraged_block_assignment,
        ai_assign_enraged_blocks,
        end_dice_battle,
        finish_block_assignment,
        resolve_pending_direct_attack_after_reaction,
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
        clear_pending_ai_action,
        current_prompt,
        execute_prepared_ai_action,
        end_turn,
        request_end_turn,
        get_button_specs,
        handle_click,
        has_pending_ai_action,
        is_ai_thinking,
        persist_game_results_once,
        poll_ai_thinking,
        prepare_ai_turn_action,
        process_ai_turn,
        start_ai_thinking,
        cancel_ai_thinking,
    )
    from engine.flow import (
        auto_resolve_human_no_blockers_if_needed,
        available_attackers,
        available_blockers,
        begin_first_turn,
        begin_main_phase_priority_window,
        clear_end_of_turn_temporary_effects,
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
        is_own_main_phase,
        resolve_stalled_dice_battle_if_needed,
        request_combat_transition,
        start_turn,
        toggle_hand_card,
    )
    from engine.resources import (
        format_card_cost,
        format_resource_play_log,
        get_card_cost_to_pay,
        handle_creature_player_damage_triggers,
        play_hand_card_in_summoning_zone,
        resolve_end_of_turn_returns,
    )
    from engine.destroy import destroy_creature_immediately
    from engine.turns import (
        clear_combat_temporary_effects,
    )

    def __init__(self) -> None:
        self.templates = {}
        self.players: List[PlayerState] = []
        self.active_player_index = 0
        self.starting_player_id = 0
        self.turn_number = 0
        self.phase = PHASE_MAIN_1
        self.game_over_text = ""
        self.log_messages: List[str] = []
        self.pending_log_file_lines: List[str] = []
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
        self.selected_attack_target_id: Optional[int] = None
        self.block_assignments: Dict[int, Optional[int]] = {}
        self.enraged_forced_attackers: set[int] = set()
        self.pending_dice_battle: Optional[PendingDiceBattle] = None
        self.pending_dice_battles: List[PendingDiceBattle] = []
        self.pending_direct_attack: Optional[PendingDirectAttack] = None
        self.pending_direct_attacks: List[PendingDirectAttack] = []
        self.combat_queue: List[int] = []
        self.current_attack_index = 0
        self.blocked_attackers: set[int] = set()
        self.combat_id_counter = 0
        self.ai_turn_initialized = False
        self.pending_ai_action: Optional[dict] = None
        self.ai_thinking = False
        self.ai_think_result: Optional[dict] = None
        self.ai_think_error: Optional[str] = None
        self.ai_think_thread = None
        self.ai_think_token = 0
        self.ai_think_lock = Lock()
        self.pending_builder_creature: Optional[PendingBuilderCreatureBuild] = None
        self.pending_builder_ability: Optional[PendingBuilderAbilityUse] = None
        self.builder_creature_counter = 0
        self.builder_shared_deck: List[CardInstance] = []
        self.builder_shared_discard: List[CardInstance] = []
        self.builder_ability_used_this_turn = False
        self.builder_created_this_turn_ids: set[int] = set()
        self.exit_requested = False
        self.pending_visual_events: List[dict] = []
        self.creatures_died_this_turn = 0
        self.debug_log_to_messages = False

        self.start_new_game()

    @property
    def human_player(self) -> PlayerState:
        return self.players[0]

    @property
    def ai_player(self) -> PlayerState:
        return self.players[1]

    @property
    def player_one(self) -> PlayerState:
        return self.players[0]

    @property
    def player_two(self) -> PlayerState:
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

    def get_template_max_lw(self, template) -> int:
        return template.effective_lw

    def get_template_damage_value(self, template) -> int:
        return template.effective_sw

    def get_creature_max_lw(self, creature: BattlefieldCreature) -> int:
        return creature.lw

    def get_creature_damage_value(self, creature: BattlefieldCreature) -> int:
        return creature.sw + getattr(creature, "temporary_combat_sw_bonus", 0)

    def get_creature_current_lw(self, creature: BattlefieldCreature) -> int:
        return creature.current_hp

    def get_creature_current_hp(self, creature: BattlefieldCreature) -> int:
        return self.get_creature_current_lw(creature)

    def is_creature_destroyed(self, creature: BattlefieldCreature) -> bool:
        return self.get_creature_current_lw(creature) <= 0

    @property
    def defending_player(self) -> PlayerState:
        return self.players[1 - self.active_player_index]

    def make_instance_id(self) -> int:
        instance_id = self.next_instance_id
        self.next_instance_id += 1
        return instance_id

    def _write_log_line(self, message: str) -> None:
        self.pending_log_file_lines.append(message)

    def flush_log_file_writes(self, max_lines: int | None = None) -> None:
        if not self.pending_log_file_lines:
            return
        line_count = len(self.pending_log_file_lines) if max_lines is None else min(len(self.pending_log_file_lines), max_lines)
        lines = self.pending_log_file_lines[:line_count]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write("\n".join(lines) + "\n")
        del self.pending_log_file_lines[:line_count]

    def log(self, message: str) -> None:
        self.log_messages.append(message)
        self._write_log_line(message)

    def debug_log(self, message: str) -> None:
        if self.debug_log_to_messages:
            self.log_messages.append(message)
        self._write_log_line(message)

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
        self.flush_log_file_writes()
        self.cancel_ai_thinking()
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
        self.phase = PHASE_MAIN_1
        self.game_over_saved = False
        self.exit_requested = False
        self.pending_visual_events.clear()
        self.reset_combat_state()
        self.initialize_builder_game()
        return

    def start_test_combat(self) -> None:
        self.initialize_builder_game()
        for player in self.players:
            player.life = STARTING_LIFE
            player.turns_started = 0
            player.main_action_used_this_turn = False

        human_creature = self.create_builder_creature(
            self.human_player,
            aw=2,
            vw=1,
            sw=1,
            lw=2,
            abilities=frozenset(),
        )
        ai_creature = self.create_builder_creature(
            self.ai_player,
            aw=2,
            vw=1,
            sw=1,
            lw=2,
            abilities=frozenset(),
        )
        if human_creature is None or ai_creature is None:
            raise RuntimeError("Builder test combat setup failed to create creatures.")
        human_creature.tapped = False
        human_creature.summoning_sick = False
        ai_creature.tapped = False
        ai_creature.summoning_sick = False
        self.active_player_index = 0
        self.starting_player_id = 0
        self.turn_number = 1
        self.phase = PHASE_DICE_BATTLE
        self.statistics = GameStatistics(
            game_id=self.game_id,
            seed=self.seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            start_player=self.human_player.name,
            player_names={0: self.human_player.name, 1: self.ai_player.name},
        )
        self.log(f"Testkampf gestartet: {human_creature.name} gegen {ai_creature.name}.")
        self.start_dice_battle(human_creature.unit_id, ai_creature.unit_id)

    def reset_combat_state(self) -> None:
        self.cancel_ai_thinking()
        self.selected_attackers = []
        self.selected_blocker_id = None
        self.selected_attack_target_id = None
        self.block_assignments = {}
        self.enraged_forced_attackers = set()
        self.pending_dice_battle = None
        self.pending_dice_battles = []
        self.pending_direct_attack = None
        self.pending_direct_attacks = []
        self.combat_queue = []
        self.current_attack_index = 0
        self.blocked_attackers = set()
        self.pending_ai_action = None
        self.pending_builder_ability = None

