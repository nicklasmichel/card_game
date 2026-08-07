from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from random import Random
from time import perf_counter
from typing import Any

from cards import build_card_templates, build_test_deck, validate_deck_definitions
from core.ai.simple_ai import HeuristicStrategicAI
from core.game_logic import GameEngine
from core.models import (
    Ability,
    CardInstance,
    CardType,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PHASE_REACTION,
    PHASE_SPELL_TARGETING,
    PlayerState,
    ReactionTrigger,
    ResourceCard,
    SpellEffect,
    SpellTargetRef,
)
from simulation.telemetry import GameTelemetry, PHASE_BUCKETS, PlayerTelemetry, ReplayRecord, card_type_bucket, phase_bucket
from stats import GameStatistics


@dataclass
class SimulationConfig:
    decks: tuple[str, str] = ("air", "fire")
    seed: int = 1
    starting_player_id: int | None = None
    max_turns: int = 60
    max_actions_per_turn: int = 250
    capture_replay: bool = True
    fixed_start_player: bool = False


class SimulationGameEngine(GameEngine):
    def __init__(self, config: SimulationConfig) -> None:
        self.simulation_config = config
        self.simulation_mode = True
        self._sim_reference_player_id = 1
        self._ai_by_player_id: dict[int, HeuristicStrategicAI] = {}
        self.telemetry: GameTelemetry | None = None
        self._turn_action_count = 0
        self._current_plan_modes: dict[int, dict[str, Any]] = {}
        self._last_spell_origin_phase: str | None = None
        self._disabled_reaction_card_ids: set[int] = set()
        super().__init__()

    @property
    def ai_player(self) -> PlayerState:
        if getattr(self, "simulation_mode", False):
            return self.players[self._sim_reference_player_id]
        return self.players[1]

    @property
    def human_player(self) -> PlayerState:
        if getattr(self, "simulation_mode", False):
            return self.players[1 - self._sim_reference_player_id]
        return self.players[0]

    def _set_reference_player(self, player_id: int) -> HeuristicStrategicAI:
        self._sim_reference_player_id = player_id
        self.ai = self._ai_by_player_id[player_id]
        return self.ai

    def log(self, message: str) -> None:
        self.log_messages.append(message)

    def persist_game_results_once(self) -> None:
        if self.game_over_saved or self.statistics is None:
            return
        self.game_over_saved = True
        winner = None
        loser = None
        if self.players[0].life <= 0 and self.players[1].life > 0:
            winner, loser = 1, 0
        elif self.players[1].life <= 0 and self.players[0].life > 0:
            winner, loser = 0, 1
        elif self.players[0].life > self.players[1].life:
            winner, loser = 0, 1
        elif self.players[1].life > self.players[0].life:
            winner, loser = 1, 0
        if self.telemetry is not None:
            self.telemetry.winner_id = winner
            self.telemetry.loser_id = loser
            self.telemetry.turn_count = self.turn_number
            if not self.telemetry.end_reason:
                self.telemetry.end_reason = "game_over"

    def start_new_game(self) -> None:
        self.seed = self.simulation_config.seed
        self.rng = Random(self.seed)
        self._ai_by_player_id = {
            0: HeuristicStrategicAI(self.rng),
            1: HeuristicStrategicAI(self.rng),
        }
        self.ai = self._ai_by_player_id[1]
        self.game_id = f"sim-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{self.seed}"
        self.templates = build_card_templates()
        validate_deck_definitions(self.templates)
        self.next_instance_id = 1
        self.players = [
            PlayerState(0, self.simulation_config.decks[0], False),
            PlayerState(1, self.simulation_config.decks[1], False),
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
        for player in self.players:
            player.summoner_key = self.simulation_config.decks[player.player_id]
            player.life = 20
            player.deck = build_test_deck(player.summoner_key, self.templates, self.make_instance_id)
            self.rng.shuffle(player.deck)
            player.hand.clear()
            player.discard_pile.clear()
            player.battlefield.clear()
            player.resources.clear()
            player.resources_played_this_turn = 0
            player.summoner_passive_draw_used_this_turn = False
            player.creature_cost_reduction_this_turn = 0
            player.attackers_die_bonus_this_turn = 0
            player.summoner_tapped = False
            player.turns_started = 0
            player.mulligan_used = True
            for _ in range(5):
                player.draw_card()
        self.starting_player_id = self.simulation_config.starting_player_id if self.simulation_config.starting_player_id is not None else self.rng.choice([0, 1])
        self.statistics = GameStatistics(
            game_id=self.game_id,
            seed=self.seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            start_player=self.players[self.starting_player_id].name,
            player_names={0: self.players[0].name, 1: self.players[1].name},
        )
        self.telemetry = GameTelemetry(
            seed=self.seed,
            decks=list(self.simulation_config.decks),
            starting_player_id=self.starting_player_id,
            players={
                0: PlayerTelemetry(0, self.players[0].name, self.players[0].summoner_key),
                1: PlayerTelemetry(1, self.players[1].name, self.players[1].summoner_key),
            },
        )
        self.log(f"Neue Partie gestartet. Seed: {self.seed}")
        self.log(f"Startspieler: {self.players[self.starting_player_id].name}")
        self.log("Mulligan ist deaktiviert. Das Spiel startet direkt.")
        self.begin_first_turn()

    def _record_turn_state(self) -> None:
        if self.telemetry is None:
            return
        self.telemetry.turn_states.append(
            {
                "turn": self.turn_number,
                "phase": self.phase,
                "active_player": self.active_player.player_id,
                "players": {
                    str(player.player_id): {
                        "life": player.life,
                        "hand": len(player.hand),
                        "resources_ready": player.available_resources(),
                        "resources_total": player.total_resources(),
                        "board": len(player.battlefield),
                    }
                    for player in self.players
                },
            }
        )
        for player in self.players:
            self.telemetry.player(player.player_id).snapshot_turn_state(
                hand_size=len(player.hand),
                total_resources=player.total_resources(),
                board_width=len(player.battlefield),
            )

    def start_turn(self) -> None:
        super().start_turn()
        self._turn_action_count = 0
        self._disabled_reaction_card_ids.clear()
        if self.telemetry is None:
            return
        self._record_turn_state()
        for player in self.players:
            telemetry = self.telemetry.player(player.player_id)
            if player.summoner_key == "fire" and player.life < 10:
                telemetry.fire_turns_under_ten += 1
            resources = player.total_resources()
            if player.summoner_key == "fire":
                if resources >= 3 and telemetry.fire_reached_3_resources_turn is None:
                    telemetry.fire_reached_3_resources_turn = self.turn_number
                if resources >= 4 and telemetry.fire_reached_4_resources_turn is None:
                    telemetry.fire_reached_4_resources_turn = self.turn_number
                if resources >= 5 and telemetry.fire_reached_5_resources_turn is None:
                    telemetry.fire_reached_5_resources_turn = self.turn_number

    def draw_card_for_player(self, player: PlayerState, source_name: str):
        before = len(player.hand)
        drawn = super().draw_card_for_player(player, source_name)
        if drawn is None or self.telemetry is None:
            return drawn
        telemetry = self.telemetry.player(player.player_id)
        telemetry.cards_drawn += 1
        telemetry.card_stat(drawn.template.template_id).drawn += 1
        if source_name == "Beschwoerer-Passiv" and player.summoner_key == "fire":
            telemetry.fire_passive_triggers += 1
            telemetry.fire_bonus_cards_drawn += 1
        if before < len(player.hand) and player.summoner_key == "air" and source_name == "Beschwoerer-Passiv":
            telemetry.air_passive_triggers += 1
        return drawn

    def play_card_as_resource_for_player(self, player: PlayerState, card: CardInstance) -> bool:
        if self.phase not in {PHASE_MAIN_1, PHASE_MAIN_2} or self.active_player != player or player.resources_played_this_turn >= 2:
            return False
        player.hand = [existing for existing in player.hand if existing.instance_id != card.instance_id]
        comes_in_tapped = player.resources_played_this_turn >= 1
        player.resources.append(ResourceCard(template=card.template, resource_id=card.instance_id, tapped=comes_in_tapped))
        player.resources_played_this_turn += 1
        if self.statistics is not None:
            self.statistics.register_resource_played(player.player_id)
        if self.telemetry is not None:
            phase_name = phase_bucket(self.phase)
            telemetry = self.telemetry.player(player.player_id)
            telemetry.resources_played_as_cards += 1
            telemetry.card_stat(card.template.template_id).played_as_resource += 1
            telemetry.phase_stats[phase_name].resources += 1
            if player.resources_played_this_turn == 1:
                telemetry.resources_first_regular += 1
                if self.phase == PHASE_MAIN_1:
                    telemetry.resources_first_main_1 += 1
                else:
                    telemetry.resources_first_main_2 += 1
            elif player.resources_played_this_turn == 2:
                telemetry.resources_second_regular += 1
                if self.phase == PHASE_MAIN_1:
                    telemetry.resources_second_main_1 += 1
                else:
                    telemetry.resources_second_main_2 += 1
        state_text = "getappt" if comes_in_tapped else "bereit"
        self.log(f"{player.name} legt {card.template.name} als Ressource ({state_text}).")
        return True

    def resolve_creature_play(self, card: CardInstance, recycle_resource_ids: list[int] | None = None) -> bool:
        player = self.active_player
        phase_name = phase_bucket(self.phase)
        before_resources = player.total_resources()
        success = super().resolve_creature_play(card, recycle_resource_ids)
        if not success or self.telemetry is None:
            return success
        telemetry = self.telemetry.player(player.player_id)
        telemetry.creatures_played += 1
        telemetry.phase_stats[phase_name].creatures += 1
        stats = telemetry.card_stat(card.template.template_id)
        stats.played += 1
        stats.play_turns.append(self.turn_number)
        if telemetry.fire_first_creature_turn is None and player.summoner_key == "fire":
            telemetry.fire_first_creature_turn = self.turn_number
        if player.summoner_key == "fire" and card.template.resource_cost >= 4 and telemetry.fire_first_big_creature_turn is None:
            telemetry.fire_first_big_creature_turn = self.turn_number
        if recycle_resource_ids:
            telemetry.recycled_resources_lost += len(recycle_resource_ids)
            stats.recycled += len(recycle_resource_ids)
        if player.total_resources() > before_resources and player.summoner_key == "fire":
            telemetry.ramp_resources_gained += player.total_resources() - before_resources
        return success

    def begin_spell_cast_from_card(self, card: CardInstance, origin_phase: str) -> bool:
        controller_id = self.active_player.player_id if origin_phase in {PHASE_MAIN_1, PHASE_MAIN_2} else self.reaction_priority_player_id
        if controller_id is not None:
            self._set_reference_player(controller_id)
        self._last_spell_origin_phase = origin_phase
        return super().begin_spell_cast_from_card(card, origin_phase)

    def finish_spell_resolution_after_reaction(self) -> None:
        if self.phase == PHASE_REACTION and self.reaction_context is None and self.reaction_priority_player_id is None:
            if self._last_spell_origin_phase in {PHASE_MAIN_1, PHASE_MAIN_2}:
                self.phase = self._last_spell_origin_phase
        return super().finish_spell_resolution_after_reaction()

    def commit_spell_cast(
        self,
        card: CardInstance,
        origin_phase: str,
        targets: list[SpellTargetRef],
        sacrifice_creature_id: int | None = None,
        selected_keyword_ability: Ability | None = None,
        recycle_resource_ids: list[int] | None = None,
    ) -> bool:
        controller_id = self.active_player.player_id if origin_phase in {PHASE_MAIN_1, PHASE_MAIN_2} else self.reaction_priority_player_id
        before_enemy_board = len(self.defending_player.battlefield)
        before_own_board = len(self.active_player.battlefield)
        before_enemy_life = self.defending_player.life
        before_own_life = self.active_player.life
        before_total_resources = self.active_player.total_resources()
        if controller_id is not None:
            self._set_reference_player(controller_id)
        result = super().commit_spell_cast(
            card,
            origin_phase,
            targets,
            sacrifice_creature_id=sacrifice_creature_id,
            selected_keyword_ability=selected_keyword_ability,
            recycle_resource_ids=recycle_resource_ids,
        )
        if not result or self.telemetry is None or controller_id is None:
            return result
        controller = self.players[controller_id]
        telemetry = self.telemetry.player(controller.player_id)
        phase_name = phase_bucket(origin_phase)
        bucket = card_type_bucket(card.template.card_type)
        if bucket == "rituals":
            telemetry.rituals_played += 1
            telemetry.phase_stats[phase_name].rituals += 1
        elif bucket == "spells":
            telemetry.spells_played += 1
            telemetry.phase_stats[phase_name].spells += 1
        stats = telemetry.card_stat(card.template.template_id)
        stats.played += 1
        stats.play_turns.append(self.turn_number)
        damage = max(0, before_enemy_life - self.players[1 - controller_id].life)
        self_damage = max(0, before_own_life - controller.life)
        if damage > 0:
            stats.player_damage += damage
        if self_damage > 0:
            self.telemetry.player(controller.player_id).player_damage_dealt += 0
        if controller.summoner_key == "fire":
            if card.template.template_id == "fire_ritual_holzvorrat":
                telemetry.fire_holzvorrat_uses += 1
            elif card.template.template_id == "fire_ritual_kohlevorrat":
                telemetry.fire_kohlevorrat_uses += 1
            elif card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
                amount = card.template.spell_amount
                telemetry.fire_damage_spells_by_amount[amount] += 1
                if targets and targets[0].target_type == "player":
                    telemetry.fire_burn_on_players += 1
                elif targets and targets[0].target_type == "creature":
                    telemetry.fire_burn_on_creatures += 1
            elif card.template.template_id == "fire_spell_wutanfall":
                telemetry.fire_recycle_loss_on_buffs += card.template.recycle_cost
            elif card.template.template_id == "fire_spell_raserei":
                telemetry.fire_recycle_loss_on_buffs += card.template.recycle_cost
        gained_resources = max(0, controller.total_resources() - before_total_resources)
        if gained_resources > 0:
            telemetry.ramp_resources_gained += gained_resources
            stats.resources_generated += gained_resources
        removed_creatures = max(0, before_enemy_board - len(self.players[1 - controller_id].battlefield))
        if removed_creatures > 0:
            stats.creatures_removed += removed_creatures
            stats.successful_uses += 1
        elif damage > 0 or gained_resources > 0:
            stats.successful_uses += 1
        else:
            stats.ineffective_uses += 1
        if controller.summoner_key == "fire" and card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER and targets:
            target = targets[0]
            if target.target_type == "creature":
                creature = self.get_unit_by_id(target.creature_id or -1)
                if creature is None:
                    return result
            elif target.target_type == "player":
                lethal_threshold = before_enemy_life
                if damage < card.template.spell_amount and lethal_threshold > 0:
                    telemetry.detectable_misplays.append(
                        {
                            "kind": "burn_reduced_or_prevented",
                            "seed": self.seed,
                            "turn": self.turn_number,
                            "phase": origin_phase,
                            "player": controller.player_id,
                            "card": card.template.template_id,
                        }
                    )
        return result

    def discard_cards(self, player: PlayerState, cards: list[CardInstance], source_card_name: str) -> None:
        if self.telemetry is not None:
            telemetry = self.telemetry.player(player.player_id)
            for card in cards:
                telemetry.card_stat(card.template.template_id).discarded += 1
        return super().discard_cards(player, cards, source_card_name)

    def destroy_creature_immediately(self, owner, creature, source_name: str, *, died_in_combat: bool = False):
        if self.telemetry is not None:
            self.telemetry.player(owner.player_id).creatures_died += 1
        return super().destroy_creature_immediately(owner, creature, source_name, died_in_combat=died_in_combat)

    def deal_spell_damage_to_player(self, controller_id: int, player, amount: int, source_name: str) -> None:
        if self.telemetry is not None:
            self.telemetry.player(controller_id).player_damage_dealt += amount
        return super().deal_spell_damage_to_player(controller_id, player, amount, source_name)

    def start_dice_battle(self, attacker_id: int, blocker_id: int) -> None:
        owner = self.get_unit_owner(attacker_id)
        if owner is not None:
            self._set_reference_player(owner.player_id)
        return super().start_dice_battle(attacker_id, blocker_id)

    def apply_trample_if_needed(self, attacker, blocker, attacker_owner, damage_dealt: int) -> None:
        before = self.players[1 - attacker_owner.player_id].life
        result = super().apply_trample_if_needed(attacker, blocker, attacker_owner, damage_dealt)
        if self.telemetry is not None:
            trample_damage = max(0, before - self.players[1 - attacker_owner.player_id].life)
            if trample_damage > 0:
                self.telemetry.player(attacker_owner.player_id).fire_trample_damage += trample_damage
        return result

    def resolve_pending_direct_attack_after_reaction(self) -> None:
        before = self.defending_player.life
        pending = self.pending_direct_attack
        attacker = self.get_unit_by_id(pending.attacker_id) if pending is not None else None
        before_sw = self.get_creature_damage_value(attacker) if attacker is not None else 0
        super().resolve_pending_direct_attack_after_reaction()
        if self.telemetry is None or pending is None or attacker is None:
            return
        damage = max(0, before - self.defending_player.life)
        owner_telemetry = self.telemetry.player(self.active_player.player_id)
        owner_telemetry.player_damage_dealt += damage
        if self.active_player.summoner_key == "air":
            owner_telemetry.air_unblocked_attacks += 1
            if attacker.has_ability(Ability.FLYING):
                owner_telemetry.air_unblocked_flying_damage += damage
            if owner_telemetry.air_first_player_damage_turn is None and damage > 0:
                owner_telemetry.air_first_player_damage_turn = self.turn_number
            for turn_cutoff in (3, 4, 5, 6):
                if self.turn_number <= turn_cutoff:
                    owner_telemetry.air_damage_by_turn_cutoff[turn_cutoff] += damage
        if self.active_player.summoner_key == "fire":
            bonus = max(0, self.get_creature_attack_value(attacker) - attacker.aw)
            if bonus > 0:
                if bonus >= 6:
                    owner_telemetry.fire_raserei_extra_player_damage += max(0, damage - before_sw)
                else:
                    owner_telemetry.fire_wutanfall_extra_player_damage += max(0, damage - before_sw)

    def confirm_attackers(self) -> None:
        attackers = [self.get_unit_by_id(unit_id) for unit_id in self.selected_attackers]
        attackers = [creature for creature in attackers if creature is not None]
        super().confirm_attackers()
        if self.telemetry is None or not attackers:
            return
        telemetry = self.telemetry.player(self.active_player.player_id)
        telemetry.phase_stats["combat"].creatures += 0
        if self.active_player.summoner_key == "air":
            telemetry.air_attacker_counts.append(len(attackers))
            if len(attackers) >= 3:
                telemetry.air_three_attacker_combats += 1
                if telemetry.air_first_three_attacker_turn is None:
                    telemetry.air_first_three_attacker_turn = self.turn_number
            telemetry.air_haste_attackers += sum(1 for creature in attackers if creature.has_ability(Ability.HASTE))
            telemetry.air_flying_attackers += sum(1 for creature in attackers if creature.has_ability(Ability.FLYING))

    def _record_mode(self, player_id: int, plan: Any, duration_ms: float, candidate_count: int | None = None) -> None:
        if self.telemetry is None or plan is None:
            return
        telemetry = self.telemetry.player(player_id)
        telemetry.register_mode(getattr(plan, "strategy_mode", ""))
        telemetry.plan_revisions += 1
        telemetry.planning_durations_ms.append(duration_ms)
        if candidate_count is not None:
            telemetry.candidate_counts.append(candidate_count)
        self.telemetry.modes.append(
            {
                "turn": self.turn_number,
                "phase": self.phase,
                "player": player_id,
                "mode": getattr(plan, "strategy_mode", ""),
                "primary_goal": getattr(plan, "primary_goal", ""),
                "reason_codes": list(getattr(plan, "strategy_reason_codes", ()) or ()),
            }
        )
        self.telemetry.plan_revisions.append(
            {
                "turn": self.turn_number,
                "phase": self.phase,
                "player": player_id,
                "plan_id": getattr(plan, "plan_id", None),
                "revision": getattr(plan, "revision", None),
                "mode": getattr(plan, "strategy_mode", ""),
            }
        )

    def _record_payload_mode(self, player_id: int, payload: dict[str, Any], duration_ms: float, candidate_count: int | None = None) -> None:
        if self.telemetry is None or not payload:
            return
        telemetry = self.telemetry.player(player_id)
        mode = str(payload.get("strategy_mode", ""))
        goal = str(payload.get("primary_goal", ""))
        reasons = list(payload.get("strategy_reason_codes", ()) or payload.get("reason_codes", ()) or ())
        if mode:
            telemetry.register_mode(mode)
            telemetry.plan_revisions += 1
            telemetry.planning_durations_ms.append(duration_ms)
            if candidate_count is not None:
                telemetry.candidate_counts.append(candidate_count)
            self.telemetry.modes.append(
                {
                    "turn": self.turn_number,
                    "phase": self.phase,
                    "player": player_id,
                    "mode": mode,
                    "primary_goal": goal,
                    "reason_codes": reasons,
                }
            )

    def _prepare_turn_plan(self, player: PlayerState) -> None:
        ai = self._set_reference_player(player.player_id)
        started = perf_counter()
        payload = ai.prepare_next_action(player, self)
        duration_ms = (perf_counter() - started) * 1000.0
        if payload is None:
            return
        plan = ai._get_active_turn_plan()
        candidate_count = ai._last_air_candidate_stats.get("generated") if hasattr(ai, "_last_air_candidate_stats") else None
        if plan is not None:
            self._record_mode(player.player_id, plan, duration_ms, candidate_count)
        else:
            self._record_payload_mode(player.player_id, payload, duration_ms, candidate_count)

    def _record_action(self, player_id: int, kind: str, **details) -> None:
        if self.telemetry is None:
            return
        self._turn_action_count += 1
        self.telemetry.max_actions_in_single_turn = max(self.telemetry.max_actions_in_single_turn, self._turn_action_count)
        self.telemetry.actions.append(
            {
                "turn": self.turn_number,
                "phase": self.phase,
                "player": player_id,
                "kind": kind,
                **details,
            }
        )

    def _auto_select_spell_targets(self) -> bool:
        pending = self.pending_spell_cast
        if pending is None:
            return False
        player = self.players[pending.controller_id]
        ai = self._set_reference_player(player.player_id)
        card = self.get_card_from_pending_spell(pending)
        if card is None:
            self.cancel_pending_spell_cast()
            return False
        shadow_pending = pending
        if card.template.recycle_cost > 0 and len(shadow_pending.selected_recycle_resource_ids) < card.template.recycle_cost:
            shadow_pending.selected_recycle_resource_ids = ai.choose_resources_to_recycle(player, card.template.recycle_cost)
        for _ in range(6):
            if self.pending_spell_ready():
                break
            target = ai.choose_spell_target_ref(player, self, card, shadow_pending)
            if target is None:
                break
            if card.template.spell_effect in {
                SpellEffect.RETURN_CREATURES_TO_HAND,
                SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND,
            }:
                existing = [
                    current
                    for current in shadow_pending.selected_targets
                    if current.creature_id != target.creature_id and current.card_instance_id != target.card_instance_id
                ]
                shadow_pending.selected_targets = (existing + [target])[: card.template.spell_amount]
            else:
                shadow_pending.selected_targets = [target]
        if self.pending_spell_ready():
            self.confirm_pending_spell_cast()
            return True
        self.cancel_pending_spell_cast()
        if self.telemetry is not None:
            self.telemetry.anomalies.append(
                {
                    "kind": "spell_targeting_cancelled",
                    "seed": self.seed,
                    "turn": self.turn_number,
                    "phase": self.phase,
                    "player": player.player_id,
                    "card": card.template.template_id,
                }
            )
        if card.instance_id is not None and pending.origin_phase == PHASE_REACTION:
            self._disabled_reaction_card_ids.add(card.instance_id)
        return True

    def _auto_assign_blocks(self) -> None:
        self.ai_assign_blocks()
        self.finish_block_assignment()

    def process_next_simulation_action(self) -> bool:
        if self.phase == PHASE_GAME_OVER:
            return False
        if self.turn_number > self.simulation_config.max_turns:
            if self.telemetry is not None:
                self.telemetry.end_reason = "max_turns"
            self.phase = PHASE_GAME_OVER
            self.persist_game_results_once()
            return False
        if self._turn_action_count >= self.simulation_config.max_actions_per_turn:
            if self.telemetry is not None:
                self.telemetry.end_reason = "max_actions_per_turn"
                self.telemetry.anomalies.append(
                    {
                        "kind": "stuck_action_loop",
                        "seed": self.seed,
                        "turn": self.turn_number,
                        "phase": self.phase,
                    }
                )
            self.phase = PHASE_GAME_OVER
            self.persist_game_results_once()
            return False
        if self.phase in {PHASE_MAIN_1, PHASE_MAIN_2} and self._turn_action_count == 0:
            self._prepare_turn_plan(self.active_player)
        if self.phase in {PHASE_MAIN_1, PHASE_MAIN_2}:
            player = self.active_player
            ai = self._set_reference_player(player.player_id)
            resource = ai.choose_resource_card_for_main_phase(player, self, self.phase)
            if resource is not None:
                self._record_action(player.player_id, "play_resource", card=resource.template.template_id)
                self.play_card_as_resource_for_player(player, resource)
                return True
            chosen = ai.choose_main_phase_card(player, self)
            if chosen is not None and chosen.template.card_type in {CardType.RITUAL, CardType.SPELL} and self.can_play_card(player, chosen):
                self._record_action(player.player_id, "cast_spell", card=chosen.template.template_id)
                self.begin_spell_cast_from_card(chosen, self.phase)
                return True
            if chosen is not None and chosen.template.card_type == CardType.CREATURE and self.can_play_card(player, chosen):
                recycle_ids = ai.choose_resources_to_recycle(player, chosen.template.recycle_cost)
                self._record_action(player.player_id, "play_creature", card=chosen.template.template_id)
                self.resolve_creature_play(chosen, recycle_ids)
                return True
            if self.phase == PHASE_MAIN_1:
                if self.available_attackers(player):
                    self._record_action(player.player_id, "to_combat")
                    self.enter_combat_or_second_main()
                else:
                    self._record_action(player.player_id, "end_turn")
                    self.end_turn()
                return True
            self._record_action(player.player_id, "end_turn")
            self.end_turn()
            return True
        if self.phase == PHASE_SPELL_TARGETING:
            pending = self.pending_spell_cast
            if pending is None:
                return False
            self._record_action(pending.controller_id, "spell_targeting")
            return self._auto_select_spell_targets()
        if self.phase == PHASE_DECLARE_ATTACKERS:
            player = self.active_player
            ai = self._set_reference_player(player.player_id)
            attackers = ai.choose_attackers_for_player(player, self, self.available_attackers(player))
            self.selected_attackers = [attacker.unit_id for attacker in attackers]
            self._record_action(player.player_id, "declare_attackers", attackers=[attacker.template_id for attacker in attackers])
            self.confirm_attackers()
            return True
        if self.phase == PHASE_DECLARE_BLOCKERS:
            self._record_action(self.defending_player.player_id, "declare_blocks")
            self._auto_assign_blocks()
            return True
        if self.phase == PHASE_REACTION:
            player_id = self.reaction_priority_player_id
            if player_id is None:
                return False
            player = self.players[player_id]
            ai = self._set_reference_player(player.player_id)
            chosen = ai.choose_spell(player.hand, self)
            if chosen is not None and chosen.instance_id in self._disabled_reaction_card_ids:
                chosen = None
            if chosen is None:
                self._record_action(player.player_id, "reaction_pass")
                self.pass_reaction()
            else:
                self._record_action(player.player_id, "reaction_spell", card=chosen.template.template_id)
                self.begin_spell_cast_from_card(chosen, PHASE_REACTION)
            return True
        if self.phase == PHASE_DICE_BATTLE:
            self._record_action(self.active_player.player_id, "dice_progress")
            self.end_dice_battle()
            return True
        if self.phase == PHASE_FORCED_DISCARD:
            pending = self.pending_forced_discard
            if pending is None:
                return False
            player = self.players[pending.target_player_id]
            ai = self._set_reference_player(player.player_id)
            cards = ai.choose_cards_to_discard(player, self, pending.required_count, pending.source_card_name)
            self._record_action(player.player_id, "forced_discard", cards=[card.template.template_id for card in cards])
            self.discard_cards(player, cards, pending.source_card_name)
            self.pending_forced_discard = None
            self.phase = pending.return_phase
            if self.resolving_stack:
                self.resume_stack_resolution()
            return True
        return False

    def run_to_completion(self) -> ReplayRecord:
        while self.phase != PHASE_GAME_OVER:
            progressed = self.process_next_simulation_action()
            if not progressed:
                if self.telemetry is not None:
                    self.telemetry.end_reason = self.telemetry.end_reason or "no_progress"
                    self.telemetry.anomalies.append(
                        {
                            "kind": "no_progress",
                            "seed": self.seed,
                            "turn": self.turn_number,
                            "phase": self.phase,
                        }
                    )
                self.phase = PHASE_GAME_OVER
                break
        if self.telemetry is not None:
            for player in self.players:
                telemetry = self.telemetry.player(player.player_id)
                for card in player.hand:
                    telemetry.card_stat(card.template.template_id).in_hand_at_end += 1
                if self.telemetry.winner_id == player.player_id:
                    telemetry.mode_before_win = telemetry.last_mode
                else:
                    telemetry.mode_before_loss = telemetry.last_mode
        self.persist_game_results_once()
        assert self.telemetry is not None
        return self.telemetry.to_replay(log=list(self.log_messages))
