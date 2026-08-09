from __future__ import annotations

from typing import List

from core.game_mode import is_builder_mode
from core.models import (
    Ability,
    ButtonSpec,
    CardType,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PHASE_MULLIGAN,
    PHASE_REACTION,
    PHASE_RECYCLE_PAYMENT,
    PHASE_SPELL_TARGETING,
    ResourceCard,
    SpellEffect,
    SpellTargetRef,
)


def clear_pending_ai_action(self) -> None:
    self.pending_ai_action = None


def has_pending_ai_action(self) -> bool:
    return self.pending_ai_action is not None


def _format_ai_target_name(self, target: SpellTargetRef) -> str:
    if target.target_type == "player":
        return self.get_player_by_id(target.player_id or 0).name
    if target.target_type == "creature":
        creature = self.get_unit_by_id(target.creature_id or -1)
        return creature.name if creature is not None else "ungueltiges Ziel"
    if target.target_type == "discard_card":
        card = self.resolve_target_discard_card(target)
        return card.template.name if card is not None else "ungueltige Karte"
    return target.target_type


def _build_ai_spell_targeting_action(self) -> dict | None:
    pending = self.pending_spell_cast
    card = self.get_card_from_pending_spell(pending)
    if pending is None or card is None:
        return None
    controller = self.get_player_by_id(pending.controller_id)
    recycle_ids = list(pending.selected_recycle_resource_ids)
    selected_targets = list(pending.selected_targets)
    sacrifice_creature_id = pending.selected_sacrifice_creature_id
    selected_keyword_ability = pending.selected_keyword_ability
    selected_combat_bonus_mode = pending.selected_combat_bonus_mode
    shadow_pending = type("ShadowPending", (), {})()
    shadow_pending.selected_targets = selected_targets
    shadow_pending.selected_sacrifice_creature_id = sacrifice_creature_id

    for _ in range(5):
        if card.template.recycle_cost > 0 and len(recycle_ids) < card.template.recycle_cost:
            recycle_ids = self.ai.choose_resources_to_recycle(controller, card.template.recycle_cost)
            if len(recycle_ids) != card.template.recycle_cost:
                return None
            continue
        if card.template.sacrifice_own_creature_on_cast and sacrifice_creature_id is None:
            creature = self.ai.choose_sacrifice_creature(controller, self, card)
            if creature is None:
                return None
            sacrifice_creature_id = creature.unit_id
            shadow_pending.selected_sacrifice_creature_id = sacrifice_creature_id
            continue
        if (
            card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN
            and selected_targets
            and selected_keyword_ability is None
        ):
            creature = self.resolve_target_creature(selected_targets[0])
            selected_keyword_ability = self.ai.choose_tailwind_ability(creature)
            continue
        if (
            card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT
            and card.template.template_id in {"air_spell_jagdwind", "air_spell_sturmjagd"}
            and selected_combat_bonus_mode is None
        ):
            selected_combat_bonus_mode = self.ai.choose_global_attack_bonus_mode(controller, self, card)
            if selected_combat_bonus_mode is None:
                return None
            continue
        target = self.ai.choose_spell_target_ref(controller, self, card, shadow_pending)
        if target is None:
            break
        if card.template.spell_effect in {
            SpellEffect.RETURN_CREATURES_TO_HAND,
            SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND,
        }:
            if target.target_type == "creature":
                remaining_targets = [existing for existing in selected_targets if existing.creature_id != target.creature_id]
            else:
                remaining_targets = [existing for existing in selected_targets if existing.card_instance_id != target.card_instance_id]
            selected_targets = (remaining_targets + [target])[: card.template.spell_amount]
        else:
            selected_targets = [target]
        shadow_pending.selected_targets = selected_targets
        if card.template.spell_effect not in {
            SpellEffect.RETURN_CREATURES_TO_HAND,
            SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND,
        }:
            break
        if len(selected_targets) >= card.template.spell_amount:
            break

    shadow_pending.card_instance_id = pending.card_instance_id
    shadow_pending.controller_id = pending.controller_id
    shadow_pending.origin_phase = pending.origin_phase
    shadow_pending.selected_recycle_resource_ids = recycle_ids
    shadow_pending.selected_keyword_ability = selected_keyword_ability
    shadow_pending.selected_combat_bonus_mode = selected_combat_bonus_mode
    original_pending = self.pending_spell_cast
    try:
        self.pending_spell_cast = shadow_pending
        if not self.pending_spell_ready():
            return None
    finally:
        self.pending_spell_cast = original_pending

    target_names = ", ".join(_format_ai_target_name(self, target) for target in selected_targets) if selected_targets else "ohne Ziel"
    return {
        "kind": "spell_targeting",
        "description": f"Gegner bestaetigt {card.template.name} ({target_names}).",
        "recycle_resource_ids": recycle_ids,
        "selected_targets": selected_targets,
        "selected_sacrifice_creature_id": sacrifice_creature_id,
        "selected_keyword_ability": selected_keyword_ability,
        "selected_combat_bonus_mode": selected_combat_bonus_mode,
    }


def prepare_ai_turn_action(self) -> bool:
    if self.pending_ai_action is not None:
        return True
    if self.phase in {
        PHASE_MULLIGAN,
        PHASE_GAME_OVER,
        PHASE_DICE_BATTLE,
        PHASE_RECYCLE_PAYMENT,
        PHASE_FORCED_DISCARD,
        PHASE_BUILDER_CREATURE,
    }:
        return False
    ai_block_decision = self.phase == PHASE_DECLARE_BLOCKERS and not self.defending_player.is_human
    ai_reaction_decision = self.phase == PHASE_REACTION and self.reaction_priority_player_id == self.ai_player.player_id
    ai_spell_targeting = (
        self.phase == PHASE_SPELL_TARGETING
        and self.pending_spell_cast is not None
        and self.pending_spell_cast.controller_id == self.ai_player.player_id
    )
    if self.active_player.is_human and not ai_block_decision and not ai_reaction_decision and not ai_spell_targeting:
        return False
    if not self.ai_turn_initialized:
        self.ai_turn_initialized = True

    if is_builder_mode() and self.phase == PHASE_MAIN_1:
        if not self.active_player.main_action_used_this_turn:
            main_action = self.ai.choose_builder_main_action(self.active_player, self)
            if main_action == "resource" and self.can_builder_add_resource(self.active_player):
                self.pending_ai_action = {
                    "kind": "builder_add_resource",
                    "description": "Gegner erhoeht seine Ressourcen.",
                }
                return True
            if main_action == "creature":
                plan = self.ai.choose_builder_creature_plan(self.active_player, self)
                if plan is not None:
                    self.pending_ai_action = {
                        "kind": "builder_create_creature",
                        "description": "Gegner baut eine Kreatur.",
                        "plan": plan,
                    }
                    return True
        self.pending_ai_action = (
            {
                "kind": "to_combat" if self.available_attackers(self.active_player) else "end_turn",
                "description": "Gegner wechselt in die Kampfphase." if self.available_attackers(self.active_player) else "Gegner beendet seinen Zug.",
            }
        )
        return True

    if self.phase in {PHASE_MAIN_1, PHASE_MAIN_2}:
        resource_card = self.ai.choose_resource_card_for_main_phase(self.active_player, self, self.phase)
        if resource_card is not None:
            next_resource_index = self.active_player.resources_played_this_turn + 1
            self.pending_ai_action = {
                "kind": "play_resource",
                "description": f"Gegner legt Ressource {next_resource_index}/2 ({resource_card.template.name}).",
                "card_id": resource_card.instance_id,
            }
            return True
        chosen = self.ai.choose_main_phase_card(self.active_player, self)
        if (
            chosen is not None
            and chosen.template.card_type in {CardType.RITUAL, CardType.SPELL}
            and self.can_play_card(self.active_player, chosen)
        ):
            self.pending_ai_action = {
                "kind": "cast_spell",
                "description": f"Gegner spielt {chosen.template.name}.",
                "card_id": chosen.instance_id,
                "origin_phase": self.phase,
            }
            return True
        if chosen is not None and chosen.template.card_type == CardType.CREATURE and self.can_play_card(self.active_player, chosen):
            recycle_ids = self.ai.choose_resources_to_recycle(self.active_player, chosen.template.recycle_cost)
            if len(recycle_ids) == chosen.template.recycle_cost:
                self.pending_ai_action = {
                    "kind": "play_creature",
                    "description": f"Gegner spielt {chosen.template.name}.",
                    "card_id": chosen.instance_id,
                    "recycle_resource_ids": recycle_ids,
                }
                return True
        self.pending_ai_action = (
            {
                "kind": "to_combat" if self.available_attackers(self.active_player) else "end_turn",
                "description": (
                    "Gegner wechselt in die Kampfphase."
                    if self.available_attackers(self.active_player)
                    else "Gegner beendet seinen Zug."
                ),
            }
            if self.phase == PHASE_MAIN_1
            else {
                "kind": "end_turn",
                "description": "Gegner beendet seinen Zug.",
            }
        )
        return True

    if self.phase == PHASE_SPELL_TARGETING and ai_spell_targeting:
        self.pending_ai_action = _build_ai_spell_targeting_action(self)
        if self.pending_ai_action is None:
            self.cancel_pending_spell_cast()
            return False
        return True

    if self.phase == PHASE_DECLARE_ATTACKERS and not self.active_player.is_human:
        attackers = self.ai.choose_attackers_for_player(self.active_player, self, self.available_attackers(self.active_player))
        attacker_names = ", ".join(attacker.name for attacker in attackers)
        self.pending_ai_action = {
            "kind": "declare_attackers",
            "description": "Gegner greift nicht an." if not attackers else f"Gegner greift an mit: {attacker_names}.",
            "attacker_ids": [attacker.unit_id for attacker in attackers],
        }
        return True

    if self.phase == PHASE_REACTION and self.reaction_priority_player_id == self.ai_player.player_id:
        chosen = self.ai.choose_spell(self.ai_player.hand, self)
        window_title = self.get_reaction_window_title()
        if chosen is None:
            self.pending_ai_action = {
                "kind": "reaction_pass",
                "description": f"Gegner passt in {window_title}.",
            }
        else:
            self.pending_ai_action = {
                "kind": "cast_spell",
                "description": f"Gegner spielt {chosen.template.name} in {window_title}.",
                "card_id": chosen.instance_id,
                "origin_phase": PHASE_REACTION,
            }
        return True

    if self.phase == PHASE_DECLARE_BLOCKERS and not self.defending_player.is_human:
        self.pending_ai_action = {
            "kind": "declare_blocks",
            "description": "Gegner weist seine Blocker zu.",
        }
        return True
    return False


def execute_prepared_ai_action(self) -> None:
    action = self.pending_ai_action
    self.pending_ai_action = None
    if action is None:
        return
    kind = action["kind"]
    if kind == "play_resource":
        chosen = next((card for card in self.active_player.hand if card.instance_id == action["card_id"]), None)
        if chosen is not None and self.active_player.resources_played_this_turn < 2:
            self.ai_play_resource(chosen)
            if hasattr(self.ai, "_mark_turn_plan_step_completed"):
                self.ai._mark_turn_plan_step_completed("play_resource", card_instance_id=chosen.instance_id)
        return
    if kind == "builder_add_resource":
        self.builder_add_resource(self.active_player)
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("builder_add_resource")
        return
    if kind == "builder_create_creature":
        plan = action.get("plan", {})
        creature = self.create_builder_creature(
            self.active_player,
            aw=int(plan.get("aw", 0)),
            vw=int(plan.get("vw", 0)),
            sw=int(plan.get("sw", 0)),
            lw=int(plan.get("lw", 1)),
        ) if self.builder_spend_ready_resources(self.active_player, int(plan.get("cost", 0))) else None
        if creature is not None:
            self.active_player.main_action_used_this_turn = True
            if self.statistics is not None:
                self.statistics.register_creature_played(self.active_player.player_id, 0)
            self.log(
                f"{self.active_player.name} baut {creature.name} "
                f"(A {creature.aw} / V {creature.vw} / S {creature.sw} / L {creature.lw}) "
                f"fuer {int(plan.get('cost', 0))} Ressource(n)."
            )
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("builder_create_creature")
        return
    if kind == "cast_spell":
        card = next((card for card in self.ai_player.hand if card.instance_id == action["card_id"]), None)
        if card is not None:
            self.begin_spell_cast_from_card(card, action["origin_phase"])
            if hasattr(self.ai, "_mark_turn_plan_step_completed"):
                self.ai._mark_turn_plan_step_completed("cast_spell", card_instance_id=card.instance_id)
        return
    if kind == "play_creature":
        chosen = next((card for card in self.active_player.hand if card.instance_id == action["card_id"]), None)
        if chosen is not None and self.can_play_card(self.active_player, chosen):
            self.resolve_creature_play(chosen, action.get("recycle_resource_ids", []))
            if hasattr(self.ai, "_mark_turn_plan_step_completed"):
                self.ai._mark_turn_plan_step_completed("play_creature", card_instance_id=chosen.instance_id)
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
        return
    if kind == "spell_targeting":
        pending = self.pending_spell_cast
        if pending is None:
            return
        pending.selected_recycle_resource_ids = list(action.get("recycle_resource_ids", []))
        pending.selected_targets = list(action.get("selected_targets", []))
        pending.selected_sacrifice_creature_id = action.get("selected_sacrifice_creature_id")
        pending.selected_keyword_ability = action.get("selected_keyword_ability")
        pending.selected_combat_bonus_mode = action.get("selected_combat_bonus_mode")
        if self.pending_spell_ready():
            self.confirm_pending_spell_cast()
        return
    if kind == "declare_attackers":
        attacker_ids = set(action.get("attacker_ids", []))
        attackers = [attacker for attacker in self.available_attackers(self.active_player) if attacker.unit_id in attacker_ids]
        self.selected_attackers = [attacker.unit_id for attacker in attackers]
        self.confirm_attackers()
        if hasattr(self.ai, "_mark_turn_plan_step_completed"):
            self.ai._mark_turn_plan_step_completed("declare_attackers")
        return
    if kind == "reaction_pass":
        self.pass_reaction()
        return
    if kind == "declare_blocks":
        self.ai_assign_blocks()
        self.finish_block_assignment()


def process_ai_turn(self) -> None:
    if not self.prepare_ai_turn_action():
        return
    self.execute_prepared_ai_action()


def ai_play_resource(self, chosen=None) -> None:
    if chosen is None:
        chosen = self.ai.choose_resource_card(self.active_player)
    if chosen is None:
        return
    self.active_player.hand = [
        card for card in self.active_player.hand if card.instance_id != chosen.instance_id
    ]
    comes_in_tapped = self.active_player.resources_played_this_turn >= 1
    self.active_player.resources.append(
        ResourceCard(template=chosen.template, resource_id=chosen.instance_id, tapped=comes_in_tapped)
    )
    self.active_player.resources_played_this_turn += 1
    self.statistics.register_resource_played(self.active_player.player_id)
    self.log(self.format_resource_play_log(self.active_player, chosen.template.name))
    self.register_hand_card_played(self.active_player)


def ai_play_creatures(self) -> None:
    while True:
        spell = self.ai.choose_ritual(self.active_player, self)
        if spell is None:
            break
        self.begin_spell_cast_from_card(spell, PHASE_MAIN_1)
        if self.phase != PHASE_MAIN_1:
            return
    while True:
        chosen = self.ai.choose_playable_creature(self.active_player)
        if chosen is None:
            break
        if not self.can_play_card(self.active_player, chosen):
            break
        recycle_ids = self.ai.choose_resources_to_recycle(self.active_player, chosen.template.recycle_cost)
        if len(recycle_ids) != chosen.template.recycle_cost:
            break
        if not self.resolve_creature_play(chosen, recycle_ids):
            break
        if self.phase != PHASE_MAIN_1:
            break


def ai_declare_attackers(self) -> None:
    attackers = self.ai.choose_attackers(self.available_attackers(self.active_player))
    self.selected_attackers = [attacker.unit_id for attacker in attackers]
    self.confirm_attackers()


def handle_click(self, area: str, item_id: int) -> None:
    if self.phase == PHASE_SPELL_TARGETING:
        if area == "player_creatures":
            self.select_spell_target_ref(SpellTargetRef("creature", creature_id=item_id))
            return
        if area == "enemy_creatures":
            self.select_spell_target_ref(SpellTargetRef("creature", creature_id=item_id))
            return
        if area == "discard_cards":
            self.select_spell_target_ref(SpellTargetRef("discard_card", card_instance_id=item_id))
            return
        if area == "player_summoner":
            self.select_spell_target_ref(SpellTargetRef("player", player_id=item_id))
            return
        if area == "enemy_summoner":
            self.select_spell_target_ref(SpellTargetRef("player", player_id=item_id))
            return
    if area == "player_summoner":
        if self.phase == PHASE_SPELL_TARGETING:
            self.select_spell_target_ref(SpellTargetRef("player", player_id=self.human_player.player_id))
            return
        self.activate_summoner_draw(self.human_player)
        return
    if area == "hand":
        self.toggle_hand_card(item_id)
        return
    if area == "player_creatures":
        if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
            self.toggle_attacker(item_id)
        elif self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
            self.toggle_blocker_assignment(item_id)
        elif self.phase == PHASE_DECLARE_BLOCKERS and self.active_player.is_human:
            attacker = self.get_unit_by_id(item_id)
            if attacker is None or self.get_unit_owner(item_id) != self.active_player:
                return
            if item_id not in self.block_assignments or not attacker.has_ability(Ability.ENRAGED):
                return
            if self.selected_attack_target_id == item_id:
                self.selected_attack_target_id = None
            else:
                self.selected_attack_target_id = item_id
        return
    if area == "enemy_creatures":
        if self.phase == PHASE_SPELL_TARGETING:
            self.select_spell_target_ref(SpellTargetRef("creature", creature_id=item_id))
            return
        if self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
            self.toggle_selected_attack_target(item_id)
            return
        if self.phase == PHASE_DECLARE_BLOCKERS and self.active_player.is_human:
            self.toggle_selected_attack_target(item_id)
            return
    if area == "enemy_summoner" and self.phase == PHASE_SPELL_TARGETING:
        self.select_spell_target_ref(SpellTargetRef("player", player_id=item_id))
        return
    if area == "player_resources" and self.phase == PHASE_RECYCLE_PAYMENT:
        self.toggle_recycle_resource_selection(item_id)
        return
    if area == "player_resources" and self.phase == PHASE_SPELL_TARGETING:
        self.toggle_pending_spell_recycle_resource(item_id)


def request_end_turn(self) -> None:
    if self.phase in {PHASE_MAIN_1, PHASE_MAIN_2}:
        self.begin_main_phase_priority_window(self.phase, self.end_turn)
        return
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
        self.game_over_text = "Unentschieden. Beide Spieler haben 0 oder weniger Lebenspunkte."
        self.log(self.game_over_text)
        self.persist_game_results_once()
        return
    loser = dead_players[0]
    winner = self.players[1 - loser.player_id]
    self.phase = PHASE_GAME_OVER
    self.game_over_text = f"{winner.name} gewinnt. {loser.name} hat 0 oder weniger Lebenspunkte."
    self.log(self.game_over_text)
    self.persist_game_results_once()


def persist_game_results_once(self) -> None:
    if self.game_over_saved or self.statistics is None:
        return
    self.game_over_saved = True
    if self.players[0].life <= 0 and self.players[1].life <= 0:
        winner_name = "Unentschieden"
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
        f"Sieger: {row['winner']}",
        f"Zuege: {row['turns_played']}",
        f"Lebenspunkte: Spieler {row['human_life_end']} | Gegner {row['ai_life_end']}",
        f"Ausgespielte Kreaturen: Spieler {row['human_creatures_played']} | Gegner {row['ai_creatures_played']}",
        f"Kreaturen-Kaempfe: {row['creature_combats']}",
        f"Zerstoerte Kreaturen: Spieler {row['human_creatures_destroyed']} | Gegner {row['ai_creatures_destroyed']}",
        f"Spielerschaden: Spieler {row['human_player_damage_dealt']} | Gegner {row['ai_player_damage_dealt']}",
        f"Durchschnittliche Kampf-Runden: {row['avg_dice_comparisons_per_combat']}",
        f"CSV Spielstatistik: {self.results_path}",
        f"CSV Kreaturen-Kaempfe: {self.creature_results_path}",
    ]
    self.game_over_summary_lines = summary
    print("\nSpielende")
    for line in summary:
        print(line)


def current_prompt(self) -> str:
    if self.pending_ai_action is not None:
        return self.pending_ai_action.get("description", "Gegnerische Aktion wartet auf Bestaetigung.")
    if is_builder_mode() and self.phase == PHASE_BUILDER_CREATURE:
        return "Verteile bereite Ressourcen auf Angriff, Verteidigung, Schaden und Leben."
    if self.phase == PHASE_MULLIGAN:
        return "Waehle Karten fuer den Mulligan oder behalte die Starthand."
    if is_builder_mode() and self.phase == PHASE_MAIN_1:
        if not self.active_player.main_action_used_this_turn:
            return "Waehle deine Hauptaktion."
        return "Waehle Angriff oder beende den Zug."
    if self.phase == PHASE_MAIN_1:
        return f"Ressourcen: {self.active_player.resources_played_this_turn}/2"
    if self.phase == PHASE_MAIN_2:
        return f"Ressourcen: {self.active_player.resources_played_this_turn}/2"
    if self.phase == PHASE_SPELL_TARGETING:
        return self.describe_pending_spell_requirements()
    if self.phase == PHASE_RECYCLE_PAYMENT:
        pending = self.pending_recycle_payment
        if pending is None:
            return "Waehle Recycle-Ressourcen aus."
        card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
        card_name = card.template.name if card is not None else "die Karte"
        return (
            f"Waehle {pending.required_count} Ressourcen fuer {card_name}. "
            f"Ausgewaehlt: {len(pending.selected_resource_ids)}/{pending.required_count}."
        )
    if self.phase == PHASE_FORCED_DISCARD:
        pending = self.pending_forced_discard
        if pending is None:
            return "Waehle Handkarten zum Abwerfen."
        return (
            f"Waehle {pending.required_count} Handkarte(n) fuer {pending.source_card_name}. "
            f"Ausgewaehlt: {len(pending.selected_card_ids)}/{pending.required_count}."
        )
    if self.phase == PHASE_DECLARE_ATTACKERS:
        return "Waehle deine Angreifer."
    if self.phase == PHASE_DECLARE_BLOCKERS:
        if self.active_player.is_human and self.selected_attack_target_id is not None:
            attacker = self.get_unit_by_id(self.selected_attack_target_id)
            if attacker is not None:
                return f"Wuetend: Waehle einen legalen Blocker fuer {attacker.name} oder klicke die Kreatur erneut zum Abbrechen."
        if self.selected_blocker_id is not None:
            blocker = self.get_unit_by_id(self.selected_blocker_id)
            if blocker is not None:
                return f"{blocker.name} ist als Blocker ausgewaehlt. Waehle einen Angreifer."
        if self.active_player.is_human:
            return "Optional: Waehle fuer Wuetend-Angreifer erzwungene Blocker. Danach weiter."
        return "Waehle fuer jeden Angreifer hoechstens einen Blocker."
    if self.phase == PHASE_REACTION:
        trigger = self.get_reaction_window_title()
        detail = self.get_reaction_window_description()
        player = self.get_player_by_id(self.reaction_priority_player_id) if self.reaction_priority_player_id is not None else None
        name = player.name if player is not None else "-"
        return f"{trigger}. {detail} {name} ist als Naechstes mit Reagieren oder Passen am Zug."
    if self.phase == PHASE_DICE_BATTLE:
        return "Der W6-Summenkampf wurde ausgewertet."
    return self.game_over_text


def get_button_specs(self) -> List[ButtonSpec]:
    if self.phase == PHASE_MULLIGAN:
        return [
            ButtonSpec("Weiter", True, "confirm_mulligan"),
            ButtonSpec("Hand behalten", True, "keep_mulligan"),
        ]
    if self.phase == PHASE_GAME_OVER:
        return [
            ButtonSpec("Neue Partie", True, "new_game"),
        ]
    if self.pending_ai_action is not None:
        return []

    if is_builder_mode() and self.phase == PHASE_BUILDER_CREATURE and self.active_player.is_human:
        pending = self.pending_builder_creature
        if pending is None:
            return []
        spent = self.builder_creature_build_cost()
        plus_enabled = spent < pending.available_resources
        return [
            ButtonSpec("Angriff -", pending.aw > pending.base_aw, "builder_aw_down"),
            ButtonSpec("Angriff +", plus_enabled, "builder_aw_up"),
            ButtonSpec("Verteidigung -", pending.vw > pending.base_vw, "builder_vw_down"),
            ButtonSpec("Verteidigung +", plus_enabled, "builder_vw_up"),
            ButtonSpec("Schaden -", pending.sw > pending.base_sw, "builder_sw_down"),
            ButtonSpec("Schaden +", plus_enabled, "builder_sw_up"),
            ButtonSpec("Leben -", pending.lw > pending.base_lw, "builder_lw_down"),
            ButtonSpec("Leben +", plus_enabled, "builder_lw_up"),
            ButtonSpec("Kreatur erstellen", self.builder_creature_build_is_valid(), "builder_confirm_creature"),
            ButtonSpec("Abbrechen", True, "builder_cancel_creature"),
        ]

    human_response_phases = {
        PHASE_DECLARE_BLOCKERS,
        PHASE_DICE_BATTLE,
        PHASE_RECYCLE_PAYMENT,
        PHASE_FORCED_DISCARD,
    }
    human_has_reaction_priority = self.phase == PHASE_REACTION and self.reaction_priority_player_id == self.human_player.player_id
    human_controls_pending_spell = (
        self.phase == PHASE_SPELL_TARGETING
        and self.pending_spell_cast is not None
        and self.pending_spell_cast.controller_id == self.human_player.player_id
    )
    if (
        not self.active_player.is_human
        and self.phase not in human_response_phases
        and not human_has_reaction_priority
        and not human_controls_pending_spell
    ):
        return []

    buttons: List[ButtonSpec] = []
    if is_builder_mode() and self.phase == PHASE_MAIN_1:
        if not self.active_player.main_action_used_this_turn:
            buttons.append(ButtonSpec("Ressource", self.can_builder_add_resource(self.active_player), "builder_add_resource"))
            buttons.append(ButtonSpec("Kreatur", self.can_builder_open_creature_build(self.active_player), "builder_open_creature"))
            return buttons
        if self.available_attackers(self.active_player):
            buttons.append(ButtonSpec("Zum Kampf", True, "to_combat"))
            buttons.append(ButtonSpec("Zug beenden", True, "end_turn"))
        return buttons
    if self.phase == PHASE_MAIN_1:
        if self.available_attackers(self.active_player):
            buttons.append(ButtonSpec("Zum Kampf", True, "to_combat"))
        else:
            buttons.append(ButtonSpec("Zug beenden", True, "end_turn"))
    elif self.phase == PHASE_MAIN_2:
        buttons.append(ButtonSpec("Zug beenden", True, "end_turn"))
    elif self.phase == PHASE_SPELL_TARGETING:
        pending = self.pending_spell_cast
        pending_card = self.get_card_from_pending_spell(pending) if pending is not None else None
        if (
            pending_card is not None
            and pending_card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN
            and pending is not None
            and pending.selected_targets
            and pending.selected_keyword_ability is None
        ):
            buttons.append(ButtonSpec("Schnell", True, "choose_tailwind_haste"))
            buttons.append(ButtonSpec("Fliegend", True, "choose_tailwind_flying"))
        if (
            pending_card is not None
            and pending_card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT
            and pending_card.template.template_id in {"air_spell_jagdwind", "air_spell_sturmjagd"}
            and pending is not None
            and pending.selected_combat_bonus_mode is None
        ):
            buttons.append(ButtonSpec(f"+{pending_card.template.combat_aw_bonus} Angriff", True, "choose_global_bonus_attack"))
            buttons.append(ButtonSpec(f"+{pending_card.template.combat_sw_bonus} Schaden", True, "choose_global_bonus_damage"))
        buttons.append(ButtonSpec("Weiter", self.pending_spell_ready(), "confirm_spell_target"))
        buttons.append(ButtonSpec("Abbrechen", True, "cancel_spell_target"))
    elif self.phase == PHASE_RECYCLE_PAYMENT:
        ready = (
            self.pending_recycle_payment is not None
            and len(self.pending_recycle_payment.selected_resource_ids) == self.pending_recycle_payment.required_count
        )
        buttons.append(ButtonSpec("Weiter", ready, "confirm_recycle"))
        buttons.append(ButtonSpec("Abbrechen", True, "cancel_recycle"))
    elif self.phase == PHASE_FORCED_DISCARD:
        ready = (
            self.pending_forced_discard is not None
            and len(self.pending_forced_discard.selected_card_ids) == self.pending_forced_discard.required_count
        )
        buttons.append(ButtonSpec("Weiter", ready, "confirm_forced_discard"))
    elif self.phase == PHASE_DECLARE_ATTACKERS:
        attacker_count = len(self.selected_attackers)
        attack_label = "Angriff ueberspringen" if attacker_count <= 0 else "Weiter"
        buttons.append(ButtonSpec(attack_label, True, "confirm_attackers"))
    elif self.phase == PHASE_DECLARE_BLOCKERS:
        blocker_count = sum(1 for blocker_id in self.block_assignments.values() if blocker_id is not None)
        block_label = "Blocken ueberspringen" if blocker_count <= 0 else "Weiter"
        buttons.append(ButtonSpec(block_label, True, "confirm_blocks"))
        buttons.append(ButtonSpec("Block entfernen", True, "clear_blocks"))
    elif self.phase == PHASE_DICE_BATTLE:
        if self.pending_dice_battle is not None and self.pending_dice_battle.resolution_complete:
            button_label = "Naechster Kampf" if self.has_more_dice_battles_after_current() else "Kampf abschliessen"
            buttons.append(ButtonSpec(button_label, True, "end_dice_battle"))
    elif self.phase == PHASE_REACTION:
        buttons.append(ButtonSpec("Passen", True, "pass_reaction"))
    return buttons
