from __future__ import annotations

from dataclasses import replace
from typing import List

from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_CREATURE_ABILITIES
from engine.builder import BUILDER_ABILITY_LABELS, BUILDER_CREATURE_ABILITY_RULES_TEXT, get_builder_creature_ability_label
from core.ai.builder import build_builder_runtime_fingerprint, materialize_builder_turn_decision
from core.ai.builder.attack_policy import log_builder_attack_decision
from core.ai.builder.debug import log_builder_runtime_action
from core.models import (
    Ability,
    ButtonSpec,
    PHASE_BUILDER_ABILITY,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
)


def clear_pending_ai_action(self) -> None:
    self.pending_ai_action = None


def has_pending_ai_action(self) -> bool:
    return self.pending_ai_action is not None


def _actor_name(self) -> str:
    return self.active_player.name


def _format_builder_creature_plan(plan: dict) -> str:
    text = (
        f"A {int(plan.get('aw', 0))} / D {int(plan.get('vw', 0))} / "
        f"DMG {int(plan.get('sw', 0))} / Life {int(plan.get('lw', 1))}"
    )
    text += f" / {get_builder_creature_ability_label(plan.get('ability'))}"
    return text


def prepare_ai_turn_action(self) -> bool:
    if self.pending_ai_action is not None:
        return True
    if self.phase in {PHASE_GAME_OVER, PHASE_DICE_BATTLE, PHASE_BUILDER_CREATURE}:
        return False

    ai_main_or_attack = not self.active_player.is_human and self.phase in {
        PHASE_MAIN_1,
        PHASE_BUILDER_ABILITY,
        PHASE_DECLARE_ATTACKERS,
    }
    ai_blocks = self.phase == PHASE_DECLARE_BLOCKERS and not self.defending_player.is_human
    if not ai_main_or_attack and not ai_blocks:
        return False

    if not self.ai_turn_initialized:
        self.ai_turn_initialized = True

    if self.phase == PHASE_MAIN_1:
        planner_decision = self.ai.choose_builder_turn_plan(self.active_player, self)
        if planner_decision.action_candidate.action_kind == "resource" and self.can_builder_add_resource(self.active_player):
            self.pending_ai_action = {
                "kind": "builder_add_resource",
                "description": f"{_actor_name(self)} will add a resource.",
                "turn_decision": planner_decision,
            }
            return True
        if planner_decision.action_candidate.action_kind == "creature" and planner_decision.action_candidate.creature_candidate is not None:
            candidate = planner_decision.action_candidate.creature_candidate
            if 0 <= candidate.cost <= self.active_player.available_resources():
                plan = {
                    "aw": candidate.aw,
                    "vw": candidate.vw,
                    "sw": candidate.sw,
                    "lw": candidate.lw,
                    "ability": candidate.builder_ability,
                    "haste": candidate.has_haste,
                    "haste_cost": candidate.haste_cost,
                    "cost": candidate.cost,
                    "candidate_signature": getattr(candidate, "key", candidate.signature),
                }
                self.pending_ai_action = {
                    "kind": "builder_create_creature",
                    "description": f"{_actor_name(self)} will build {_format_builder_creature_plan(plan)}.",
                    "turn_decision": planner_decision,
                    "plan": plan,
                }
                return True
        if planner_decision.action_candidate.action_kind in {"continue", "pass"}:
            has_attackers = bool(self.available_attackers(self.active_player))
            self.pending_ai_action = {
                "kind": "to_combat" if has_attackers else "end_turn",
                "description": (
                    f"{_actor_name(self)} will enter combat."
                    if has_attackers
                    else f"{_actor_name(self)} will end the turn."
                ),
                "turn_decision": planner_decision,
            }
            return True
        action = self.ai.choose_builder_runtime_main_action(self.active_player, self)
        if action == "resource" and self.can_builder_add_resource(self.active_player):
            self.pending_ai_action = {
                "kind": "builder_add_resource",
                "description": f"{_actor_name(self)} will add a resource.",
            }
            return True
        if action == "creature":
            plan = self.ai.choose_builder_runtime_creature_plan(self.active_player, self)
            if plan is not None:
                self.pending_ai_action = {
                    "kind": "builder_create_creature",
                    "description": f"{_actor_name(self)} will build {_format_builder_creature_plan(plan)}.",
                    "plan": plan,
                }
                return True
        self.pending_ai_action = {
            "kind": "builder_pass_main_action",
            "description": f"{_actor_name(self)} will pass the main action.",
        }
        return True

    if self.phase == PHASE_BUILDER_ABILITY:
        if not BUILDER_ABILITIES_ENABLED:
            has_attackers = bool(self.available_attackers(self.active_player))
            self.pending_ai_action = {
                "kind": "to_combat" if has_attackers else "end_turn",
                "description": (
                    f"{_actor_name(self)} will enter combat."
                    if has_attackers
                    else f"{_actor_name(self)} will end the turn."
                ),
            }
            return True
        planner_decision = self.ai.choose_builder_turn_plan(self.active_player, self)
        planned_ability = planner_decision.ability_action
        if planned_ability.action_kind == "skip":
            planned_attack_ids = (
                tuple(planner_decision.predicted_attack_decision.candidate.attacker_ids)
                if planner_decision.predicted_attack_decision is not None
                else tuple()
            )
            self.pending_ai_action = {
                "kind": "to_combat" if planned_attack_ids else "end_turn",
                "description": (
                    f"{_actor_name(self)} will enter combat."
                    if planned_attack_ids
                    else f"{_actor_name(self)} will end the turn."
                ),
                "turn_decision": planner_decision,
            }
            return True
        self.pending_ai_action = {
            "kind": "builder_use_ability",
            "description": f"{_actor_name(self)} will use an ability card.",
            "ability_action": {
                "card_id": planned_ability.card_instance_id,
                "mode": planned_ability.action_kind,
                "target_id": planned_ability.target_id,
                "stat": planned_ability.selected_stat,
            },
            "turn_decision": planner_decision,
        }
        return True

    if self.phase == PHASE_DECLARE_ATTACKERS:
        planner_decision = self.ai.choose_builder_turn_plan(self.active_player, self)
        attack_decision = planner_decision.predicted_attack_decision
        if attack_decision is not None:
            log_builder_attack_decision(self, self.active_player, attack_decision)
        attacker_ids = list(attack_decision.candidate.attacker_ids) if attack_decision is not None else []
        lookup = {creature.unit_id: creature for creature in self.available_attackers(self.active_player)}
        attackers = [lookup[attacker_id] for attacker_id in attacker_ids if attacker_id in lookup]
        attacker_names = ", ".join(attacker.name for attacker in attackers)
        self.pending_ai_action = {
            "kind": "declare_attackers",
            "description": (
                f"{_actor_name(self)} will not attack."
                if not attackers
                else f"{_actor_name(self)} will attack with: {attacker_names}."
            ),
            "attacker_ids": [attacker.unit_id for attacker in attackers],
            "turn_decision": planner_decision,
        }
        return True

    if self.phase == PHASE_DECLARE_BLOCKERS:
        self.pending_ai_action = {
            "kind": "declare_blocks",
            "description": f"{self.defending_player.name} will assign blockers.",
        }
        return True

    return False


def execute_prepared_ai_action(self) -> None:
    action = self.pending_ai_action
    self.pending_ai_action = None
    if action is None:
        return
    log_builder_runtime_action(self, action)
    kind = action["kind"]

    if kind == "builder_add_resource":
        self.builder_add_resource(self.active_player)
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("builder_add_resource")
        return

    if kind == "builder_pass_main_action":
        self.builder_pass_main_action(self.active_player)
        return

    if kind == "builder_create_creature":
        plan = action.get("plan", {})
        creature = None
        if self.can_builder_open_creature_build(self.active_player):
            if self.builder_spend_ready_resources(self.active_player, int(plan.get("cost", 0))):
                creature = self.create_builder_creature(
                    self.active_player,
                    aw=int(plan.get("aw", 0)),
                    vw=int(plan.get("vw", 0)),
                    sw=int(plan.get("sw", 0)),
                    lw=int(plan.get("lw", 1)),
                    ability=plan.get("ability"),
                )
        if creature is not None:
            self.builder_created_this_turn_ids.add(creature.unit_id)
            self.active_player.main_action_used_this_turn = True
            if self.statistics is not None:
                self.statistics.register_creature_played(self.active_player.player_id, 0)
            self.log(
                f"{self.active_player.name} creates {creature.name} "
                f"(A {creature.aw} / D {creature.vw} / DMG {creature.sw} / Life {creature.lw}"
                f" / {get_builder_creature_ability_label(creature.builder_ability)}) "
                f"for {int(plan.get('cost', 0))} resource(s)."
            )
            self.finish_builder_main_action()
            turn_decision = action.get("turn_decision")
            if turn_decision is not None and turn_decision.action_candidate.creature_candidate is not None:
                synthetic_id = next(
                    (
                        attacker_id
                        for attacker_id in getattr(turn_decision.predicted_attack_decision.candidate, "attacker_ids", ())
                        if attacker_id < 0
                    ),
                    None,
                )
                target_id = turn_decision.ability_action.target_id
                if synthetic_id is None and target_id is not None and target_id < 0:
                    synthetic_id = target_id
                if synthetic_id is not None:
                    materialized = materialize_builder_turn_decision(
                        turn_decision,
                        synthetic_unit_id=synthetic_id,
                        actual_unit_id=creature.unit_id,
                        post_main_signature=build_builder_runtime_fingerprint(self.active_player, self),
                    )
                    setattr(self.ai, "_last_builder_turn_decision", materialized)
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("builder_create_creature")
        return

    if kind == "builder_use_ability":
        if not BUILDER_ABILITIES_ENABLED:
            return
        ability_action = action.get("ability_action", {})
        if self.begin_builder_ability_use(int(ability_action.get("card_id", -1))):
            self.choose_builder_ability_mode(ability_action.get("mode", ""), ability_action.get("stat"))
            self.select_builder_ability_target(int(ability_action.get("target_id", -1)))
            self.resolve_builder_ability_use()
            turn_decision = action.get("turn_decision")
            if turn_decision is not None:
                updated = replace(
                    turn_decision,
                    post_ability_signature=build_builder_runtime_fingerprint(self.active_player, self),
                )
                setattr(self.ai, "_last_builder_turn_decision", updated)
        return

    if kind == "declare_attackers":
        attacker_ids = set(action.get("attacker_ids", []))
        attackers = [attacker for attacker in self.available_attackers(self.active_player) if attacker.unit_id in attacker_ids]
        self.selected_attackers = [attacker.unit_id for attacker in attackers]
        self.confirm_attackers()
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("declare_attackers")
        return

    if kind == "declare_blocks":
        self.ai_assign_blocks()
        self.finish_block_assignment()
        return

    if kind == "to_combat":
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("to_combat")
        self.request_combat_transition()
        return

    if kind == "end_turn":
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("end_turn")
        self.request_end_turn()


def process_ai_turn(self) -> None:
    if not self.prepare_ai_turn_action():
        return
    self.execute_prepared_ai_action()


def ai_play_resource(self, chosen=None) -> None:
    return


def ai_play_creatures(self) -> None:
    return


def ai_declare_attackers(self) -> None:
    attackers = self.ai.choose_attackers(self.available_attackers(self.active_player))
    self.selected_attackers = [attacker.unit_id for attacker in attackers]
    self.confirm_attackers()


def handle_click(self, area: str, item_id: int) -> None:
    if area == "hand":
        self.toggle_hand_card(item_id)
        return

    if area == "player_1_creatures":
        if self.phase == PHASE_BUILDER_ABILITY and self.active_player.is_human:
            self.select_builder_ability_target(item_id)
            return
        if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
            self.toggle_attacker(item_id)
            return
        if self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
            self.toggle_blocker_assignment(item_id)
            return
        if self.phase == PHASE_DECLARE_BLOCKERS and self.active_player.is_human:
            attacker = self.get_unit_by_id(item_id)
            if attacker is None or self.get_unit_owner(item_id) != self.active_player:
                return
            if item_id not in self.block_assignments or not (
                attacker.has_ability(Ability.ENRAGED) or attacker.has_ability(Ability.PROVOKE)
            ):
                return
            self.selected_attack_target_id = None if self.selected_attack_target_id == item_id else item_id
        return

    if area == "player_2_creatures":
        if self.phase == PHASE_BUILDER_ABILITY and self.active_player.is_human:
            self.select_builder_ability_target(item_id)
            return
        if self.phase == PHASE_DECLARE_BLOCKERS:
            self.toggle_selected_attack_target(item_id)


def request_end_turn(self) -> None:
    self.end_turn()


def end_turn(self) -> None:
    self.check_for_game_over()
    if self.phase == PHASE_GAME_OVER:
        return
    self.resolve_end_of_turn_returns(self.active_player)
    self.clear_end_of_turn_temporary_effects()
    self.check_for_game_over()
    if self.phase == PHASE_GAME_OVER:
        return
    self.reset_combat_state()
    self.active_player_index = 1 - self.active_player_index
    self.start_turn()


def check_for_game_over(self) -> None:
    if self.phase == PHASE_GAME_OVER:
        return
    dead_players = [player for player in self.players if player.life <= 0]
    if not dead_players:
        return
    if len(dead_players) == 2:
        self.phase = PHASE_GAME_OVER
        self.game_over_text = "Draw. Both players have 0 or less life."
        self.log(self.game_over_text)
        self.persist_game_results_once()
        return
    loser = dead_players[0]
    winner = self.players[1 - loser.player_id]
    self.phase = PHASE_GAME_OVER
    self.game_over_text = f"{winner.name} wins. {loser.name} has 0 or less life."
    self.log(self.game_over_text)
    self.persist_game_results_once()


def persist_game_results_once(self) -> None:
    if self.game_over_saved or self.statistics is None:
        return
    self.game_over_saved = True
    if self.players[0].life <= 0 and self.players[1].life <= 0:
        winner_name = "Draw"
    else:
        winner_name = self.players[1].name if self.players[0].life <= 0 else self.players[0].name
    row = self.statistics.finalize_game(
        winner=winner_name,
        human_life=self.human_player.life,
        ai_life=self.ai_player.life,
        human_resources_remaining=len(self.human_player.resources),
        ai_resources_remaining=len(self.ai_player.resources),
    )
    summary = [
        f"Winner: {row['winner']}",
        f"Turns: {row['turns_played']}",
        f"Life: Player 1 {row['human_life_end']} | Player 2 {row['ai_life_end']}",
        f"Creatures played: Player 1 {row['human_creatures_played']} | Player 2 {row['ai_creatures_played']}",
        f"Creature combats: {row['creature_combats']}",
        f"Creatures destroyed: Player 1 {row['human_creatures_destroyed']} | Player 2 {row['ai_creatures_destroyed']}",
        f"Player damage: Player 1 {row['human_player_damage_dealt']} | Player 2 {row['ai_player_damage_dealt']}",
        f"Average combat rounds: {row['avg_dice_comparisons_per_combat']}",
        f"CSV game stats: {self.results_path}",
        f"CSV creature combats: {self.creature_results_path}",
    ]
    self.game_over_summary_lines = summary
    print("\nGame Over")
    for line in summary:
        print(line)


def current_prompt(self) -> str:
    if self.pending_ai_action is not None:
        return self.pending_ai_action.get("description", "Player 2 action is waiting for confirmation.")
    if self.phase == PHASE_BUILDER_CREATURE:
        return "Distribute ready resources across stats and choose exactly one free ability."
    if self.phase == PHASE_BUILDER_ABILITY:
        if not BUILDER_ABILITIES_ENABLED:
            return "Attack or end the turn."
        if not self.builder_ability_used_this_turn:
            return "Optionally use exactly one ability card."
        return "Attack or end the turn."
    if self.phase == PHASE_MAIN_1:
        if not self.active_player.main_action_used_this_turn:
            return "Choose your main action."
        return "The build phase is complete."
    if self.phase == PHASE_DECLARE_ATTACKERS:
        return "Choose your attackers."
    if self.phase == PHASE_DECLARE_BLOCKERS:
        if BUILDER_ABILITIES_ENABLED and self.active_player.is_human and self.selected_attack_target_id is not None:
            attacker = self.get_unit_by_id(self.selected_attack_target_id)
            if attacker is not None:
                return f"Provoke: choose a legal blocker for {attacker.name}, or click the creature again to cancel."
        if self.selected_blocker_id is not None:
            blocker = self.get_unit_by_id(self.selected_blocker_id)
            if blocker is not None:
                return f"{blocker.name} is selected as blocker. Choose an attacker."
        if BUILDER_ABILITIES_ENABLED and self.active_player.is_human:
            return "Optional: choose forced blockers for Provoke attackers, then continue."
        return "Choose at most one blocker for each attacker."
    if self.phase == PHASE_DICE_BATTLE:
        return "The W6 combat has been resolved."
    return self.game_over_text


def get_button_specs(self) -> List[ButtonSpec]:
    if self.phase == PHASE_GAME_OVER:
        return [ButtonSpec("New game", True, "new_game")]
    if self.pending_ai_action is not None:
        return [ButtonSpec("Next", True, "confirm_ai_action")]

    if self.phase == PHASE_BUILDER_CREATURE and self.active_player.is_human:
        pending = self.pending_builder_creature
        if pending is None:
            return []
        spent = self.builder_creature_build_cost()
        plus_enabled = spent < pending.available_resources
        buttons = [
            ButtonSpec("+1 Atk", plus_enabled, "builder_aw_up"),
            ButtonSpec("-1 Atk", pending.aw > pending.base_aw, "builder_aw_down"),
            ButtonSpec("+1 Def", plus_enabled, "builder_vw_up"),
            ButtonSpec("-1 Def", pending.vw > pending.base_vw, "builder_vw_down"),
            ButtonSpec("+1 Dmg", plus_enabled, "builder_sw_up"),
            ButtonSpec("-1 Dmg", pending.sw > pending.base_sw, "builder_sw_down"),
            ButtonSpec("+1 HP", plus_enabled, "builder_lw_up"),
            ButtonSpec("-1 HP", pending.lw > pending.base_lw, "builder_lw_down"),
        ]
        for ability in BUILDER_CREATURE_ABILITIES:
            buttons.append(ButtonSpec(BUILDER_ABILITY_LABELS[ability], True, f"builder_select_ability_{ability.name.lower()}"))
        buttons.extend(
            [
            ButtonSpec("Create creature", self.builder_creature_build_is_valid(), "builder_confirm_creature"),
            ButtonSpec("Cancel", True, "builder_cancel_creature"),
            ]
        )
        return buttons

    if self.phase == PHASE_BUILDER_ABILITY and self.active_player.is_human:
        if not BUILDER_ABILITIES_ENABLED:
            if self.available_attackers(self.active_player):
                return [ButtonSpec("To combat", True, "to_combat"), ButtonSpec("End turn", True, "end_turn")]
            return [ButtonSpec("End turn", True, "end_turn")]
        buttons: list[ButtonSpec] = []
        pending = self.pending_builder_ability
        if not self.builder_ability_used_this_turn:
            if pending is not None:
                card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
                ability = self.get_builder_card_ability(card)
                label = BUILDER_ABILITY_LABELS.get(ability, "Ability") if ability is not None else "Ability"
                buttons.extend(
                    [
                        ButtonSpec(label, False, "builder_ability_label"),
                        ButtonSpec("Grant ability", True, "builder_mode_grant_ability"),
                        ButtonSpec("Deal 1 damage", True, "builder_mode_damage"),
                        ButtonSpec("Play card", self.builder_pending_ability_ready(), "builder_confirm_ability"),
                        ButtonSpec("Cancel", True, "builder_cancel_ability"),
                    ]
                )
            buttons.append(ButtonSpec("Skip", True, "builder_skip_ability"))
            return buttons
        if self.available_attackers(self.active_player):
            return [ButtonSpec("To combat", True, "to_combat"), ButtonSpec("End turn", True, "end_turn")]
        return [ButtonSpec("End turn", True, "end_turn")]

    human_response_phases = {PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE}
    if not self.active_player.is_human and self.phase not in human_response_phases:
        return []

    if self.phase == PHASE_MAIN_1:
        if not self.active_player.main_action_used_this_turn:
            resource_enabled = self.can_builder_add_resource(self.active_player)
            creature_enabled = self.can_builder_open_creature_build(self.active_player)
            if resource_enabled or creature_enabled:
                return [
                    ButtonSpec("Add Resource", resource_enabled, "builder_add_resource"),
                    ButtonSpec("Build Creature", creature_enabled, "builder_open_creature"),
                ]
            if self.available_attackers(self.active_player):
                return [ButtonSpec("To combat", True, "to_combat"), ButtonSpec("End turn", True, "end_turn")]
            return [ButtonSpec("End turn", True, "end_turn")]
        return []

    if self.phase == PHASE_DECLARE_ATTACKERS:
        attack_label = "Skip attack" if len(self.selected_attackers) <= 0 else "Next"
        return [ButtonSpec(attack_label, True, "confirm_attackers")]

    if self.phase == PHASE_DECLARE_BLOCKERS:
        blocker_count = sum(1 for blocker_id in self.block_assignments.values() if blocker_id is not None)
        block_label = "Skip blocks" if blocker_count <= 0 else "Next"
        return [ButtonSpec(block_label, True, "confirm_blocks"), ButtonSpec("Clear blocks", True, "clear_blocks")]

    if self.phase == PHASE_DICE_BATTLE and self.pending_dice_battle is not None and self.pending_dice_battle.resolution_complete:
        return [ButtonSpec("Resolve Combat", True, "end_dice_battle")]

    return []
