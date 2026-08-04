from __future__ import annotations

from typing import List

from core.models import (
    Ability,
    ButtonSpec,
    CardType,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
    PHASE_REACTION,
    PHASE_RECYCLE_PAYMENT,
    PHASE_RESOURCE,
    PHASE_SPELL_TARGETING,
    PHASE_SUMMONING,
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
        return creature.name if creature is not None else "ungÃ¼ltiges Ziel"
    if target.target_type == "die":
        role = "Angreifer" if target.die_role == "attacker" else "Blocker"
        index = 1 if target.die_index is None else target.die_index + 1
        return f"{role}-WÃ¼rfel {index}"
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
        target = self.ai.choose_spell_target_ref(controller, self, card, shadow_pending)
        if target is None:
            break
        if card.template.spell_effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            remaining_targets = [existing for existing in selected_targets if existing.creature_id != target.creature_id]
            selected_targets = (remaining_targets + [target])[:2]
        else:
            selected_targets = [target]
        shadow_pending.selected_targets = selected_targets
        if card.template.spell_effect != SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
            break
        if len(selected_targets) >= 2:
            break

    target_names = ", ".join(_format_ai_target_name(self, target) for target in selected_targets) if selected_targets else "ohne Ziel"
    return {
        "kind": "spell_targeting",
        "description": f"Gegner wird {card.template.name} bestÃ¤tigen ({target_names}).",
        "recycle_resource_ids": recycle_ids,
        "selected_targets": selected_targets,
        "selected_sacrifice_creature_id": sacrifice_creature_id,
        "selected_keyword_ability": selected_keyword_ability,
    }


def prepare_ai_turn_action(self) -> bool:
    if self.pending_ai_action is not None:
        return True
    if self.phase in {
        PHASE_MULLIGAN,
        PHASE_GAME_OVER,
        PHASE_ORDER_BLOCKERS,
        PHASE_DICE_BATTLE,
        PHASE_RECYCLE_PAYMENT,
        PHASE_FORCED_DISCARD,
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

    if self.phase == PHASE_RESOURCE:
        planned_resources = self.ai.choose_resource_cards_to_play(self.active_player, self)
        parts: list[str] = []
        if planned_resources:
            resource_names = ", ".join(card.template.name for card in planned_resources)
            parts.append(f"als Ressourcen legen: {resource_names}")
        else:
            parts.append("keine weiteren Ressourcen legen")
            parts.append("in die Beschwörungsphase wechseln")
        self.pending_ai_action = {
            "kind": "resource_phase",
            "description": "Gegner wird " + ", ".join(parts) + ".",
            "resource_card_ids": [card.instance_id for card in planned_resources],
        }
        return True

    if self.phase == PHASE_SUMMONING:
        chosen = self.ai.choose_main_phase_card(self.active_player, self)
        if (
            chosen is not None
            and chosen.template.card_type in {CardType.RITUAL, CardType.SPELL}
            and self.can_play_card(self.active_player, chosen)
        ):
            self.pending_ai_action = {
                "kind": "cast_spell",
                "description": f"Gegner wird {chosen.template.name} spielen.",
                "card_id": chosen.instance_id,
                "origin_phase": PHASE_SUMMONING,
            }
            return True
        if chosen is not None and chosen.template.card_type == CardType.CREATURE:
            recycle_ids = self.ai.choose_resources_to_recycle(self.active_player, chosen.template.recycle_cost)
            if len(recycle_ids) == chosen.template.recycle_cost:
                self.pending_ai_action = {
                    "kind": "play_creature",
                    "description": f"Gegner wird {chosen.template.name} ausspielen.",
                    "card_id": chosen.instance_id,
                    "recycle_resource_ids": recycle_ids,
                }
                return True
        if not self.available_attackers(self.active_player):
            self.begin_attack_declaration()
            return False
        self.pending_ai_action = {
            "kind": "to_combat",
            "description": "Gegner wird in die Kampfphase wechseln.",
        }
        return True

    if self.phase == PHASE_SPELL_TARGETING and ai_spell_targeting:
        self.pending_ai_action = _build_ai_spell_targeting_action(self)
        return self.pending_ai_action is not None

    if self.phase == PHASE_DECLARE_ATTACKERS and not self.active_player.is_human:
        attackers = self.ai.choose_attackers(self.available_attackers(self.active_player))
        attacker_names = ", ".join(attacker.name for attacker in attackers)
        self.pending_ai_action = {
            "kind": "declare_attackers",
            "description": "Gegner wird nicht angreifen." if not attackers else f"Gegner wird angreifen mit: {attacker_names}.",
            "attacker_ids": [attacker.unit_id for attacker in attackers],
        }
        return True

    if self.phase == PHASE_REACTION and self.reaction_priority_player_id == self.ai_player.player_id:
        chosen = self.ai.choose_spell(self.ai_player.hand, self)
        if chosen is None:
            self.pending_ai_action = {
                "kind": "reaction_pass",
                "description": "Gegner wird im Reaktionsfenster passen.",
            }
        else:
            self.pending_ai_action = {
                "kind": "cast_spell",
                "description": f"Gegner wird {chosen.template.name} als Reaktion spielen.",
                "card_id": chosen.instance_id,
                "origin_phase": PHASE_REACTION,
            }
        return True

    if self.phase == PHASE_DECLARE_BLOCKERS and not self.defending_player.is_human:
        self.pending_ai_action = {
            "kind": "declare_blocks",
            "description": "Gegner wird seine Blocker zuweisen.",
        }
        return True
    return False


def execute_prepared_ai_action(self) -> None:
    action = self.pending_ai_action
    self.pending_ai_action = None
    if action is None:
        return
    kind = action["kind"]
    if kind == "resource_phase":
        for card_id in action.get("resource_card_ids", []):
            chosen = next((card for card in self.active_player.hand if card.instance_id == card_id), None)
            if chosen is None or self.active_player.resources_played_this_turn >= 2:
                continue
            self.ai_play_resource(chosen)
        self.phase = PHASE_SUMMONING
        self.log("Gegner wechselt in die BeschwÃ¶rungsphase.")
        return
    if kind == "cast_spell":
        card = next((card for card in self.ai_player.hand if card.instance_id == action["card_id"]), None)
        if card is not None:
            self.begin_spell_cast_from_card(card, action["origin_phase"])
        return
    if kind == "play_creature":
        chosen = next((card for card in self.active_player.hand if card.instance_id == action["card_id"]), None)
        if chosen is not None:
            self.resolve_creature_play(chosen, action.get("recycle_resource_ids", []))
        return
    if kind == "to_combat":
        self.begin_attack_declaration()
        return
    if kind == "spell_targeting":
        pending = self.pending_spell_cast
        if pending is None:
            return
        pending.selected_recycle_resource_ids = list(action.get("recycle_resource_ids", []))
        pending.selected_targets = list(action.get("selected_targets", []))
        pending.selected_sacrifice_creature_id = action.get("selected_sacrifice_creature_id")
        pending.selected_keyword_ability = action.get("selected_keyword_ability")
        if self.pending_spell_ready():
            self.confirm_pending_spell_cast()
        return
    if kind == "declare_attackers":
        attacker_ids = set(action.get("attacker_ids", []))
        attackers = [attacker for attacker in self.available_attackers(self.active_player) if attacker.unit_id in attacker_ids]
        self.selected_attackers = [attacker.unit_id for attacker in attackers]
        self.confirm_attackers()
        return
    if kind == "reaction_pass":
        self.pass_reaction()
        return
    if kind == "declare_blocks":
        self.ai_assign_blocks()
        self.finish_block_assignment()
        return


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
    self.active_player.resources.append(ResourceCard(template=chosen.template, resource_id=chosen.instance_id))
    self.active_player.resources_played_this_turn += 1
    self.statistics.register_resource_played(self.active_player.player_id)
    self.log(f"Gegner legt {chosen.template.name} als Ressource.")
    self.register_hand_card_played(self.active_player)


def ai_play_creatures(self) -> None:
    while True:
        spell = self.ai.choose_ritual(self.active_player, self)
        if spell is None:
            break
        self.begin_spell_cast_from_card(spell, PHASE_SUMMONING)
        if self.phase != PHASE_SUMMONING:
            return
    while True:
        chosen = self.ai.choose_playable_creature(self.active_player)
        if chosen is None:
            break
        recycle_ids = self.ai.choose_resources_to_recycle(self.active_player, chosen.template.recycle_cost)
        if len(recycle_ids) != chosen.template.recycle_cost:
            break
        if not self.resolve_creature_play(chosen, recycle_ids):
            break
        if self.phase != PHASE_SUMMONING:
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
        if area == "player_summoner":
            self.select_spell_target_ref(SpellTargetRef("player", player_id=item_id))
            return
        if area == "enemy_summoner":
            self.select_spell_target_ref(SpellTargetRef("player", player_id=item_id))
            return
        if area == "human_dice":
            self.select_spell_combat_die(item_id)
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
        return
    if area == "enemy_creatures":
        if self.phase == PHASE_DECLARE_ATTACKERS and self.active_player.is_human:
            self.toggle_provoke_target(item_id)
            return
        if self.phase == PHASE_SPELL_TARGETING:
            self.select_spell_target_ref(SpellTargetRef("creature", creature_id=item_id))
            return
        if self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
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
        human_resources_remaining=len(self.human_player.resources),
        ai_resources_remaining=len(self.ai_player.resources),
    )
    summary = [
        f"Sieger: {row['winner']}",
        f"Zuege: {row['turns_played']}",
        f"Lebenspunkte: Spieler {row['human_life_end']} | Gegner {row['ai_life_end']}",
        f"Ausgespielte Kreaturen: Spieler {row['human_creatures_played']} | Gegner {row['ai_creatures_played']}",
        f"Kreaturen-KÃ¤mpfe: {row['creature_combats']}",
        f"Zerstoerte Kreaturen: Spieler {row['human_creatures_destroyed']} | Gegner {row['ai_creatures_destroyed']}",
        f"Spielerschaden: Spieler {row['human_player_damage_dealt']} | Gegner {row['ai_player_damage_dealt']}",
                f"Durchschnittliche WÃ¼rfelvergleiche: {row['avg_dice_comparisons_per_combat']}",
        f"CSV Spielstatistik: {self.results_path}",
        f"CSV Kreaturen-KÃ¤mpfe: {self.creature_results_path}",
    ]
    self.game_over_summary_lines = summary
    print("\nSpielende")
    for line in summary:
        print(line)


def current_prompt(self) -> str:
    if self.pending_ai_action is not None:
        return self.pending_ai_action.get("description", "Gegnerische Aktion wartet auf BestÃ¤tigung.")
    if self.phase == PHASE_MULLIGAN:
        return "WÃ¤hle Karten fÃ¼r den Mulligan oder behalte die Starthand."
    if self.phase == PHASE_RESOURCE:
        return "Lege bis zu 2 Handkarten als Ressource."
    if self.phase == PHASE_SUMMONING:
        return "Spiele Kreaturen, Rituale oder Zauber aus, beginne den Kampf oder beende den Zug."
    if self.phase == PHASE_SPELL_TARGETING:
        return self.describe_pending_spell_requirements()
    if self.phase == PHASE_RECYCLE_PAYMENT:
        pending = self.pending_recycle_payment
        if pending is None:
            return "WÃ¤hle Recycle-Ressourcen aus."
        card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
        card_name = card.template.name if card is not None else "die Karte"
        return (
            f"WÃ¤hle {pending.required_count} Ressourcen fÃ¼r {card_name}. "
            f"AusgewÃ¤hlt: {len(pending.selected_resource_ids)}/{pending.required_count}."
        )
    if self.phase == PHASE_FORCED_DISCARD:
        pending = self.pending_forced_discard
        if pending is None:
            return "WÃ¤hle Handkarten zum Abwerfen."
        return (
            f"WÃ¤hle {pending.required_count} Handkarte(n) fÃ¼r {pending.source_card_name}. "
            f"AusgewÃ¤hlt: {len(pending.selected_card_ids)}/{pending.required_count}."
        )
    if self.phase == PHASE_DECLARE_ATTACKERS:
        if self.selected_provoke_attacker_id is not None:
            attacker = self.get_unit_by_id(self.selected_provoke_attacker_id)
            if attacker is not None and attacker.has_ability(Ability.PROVOKE):
                return f"WÃ¤hle Angreifer. {attacker.name} kann eine gegnerische Kreatur provozieren."
        return "WÃ¤hle Angreifer und bestÃ¤tige."
    if self.phase == PHASE_DECLARE_BLOCKERS:
        return "WÃ¤hle einen Angreifer und ordne dann eigene Blocker zu."
    if self.phase == PHASE_REACTION:
        trigger = self.get_reaction_window_title()
        detail = self.get_reaction_window_description()
        player = self.get_player_by_id(self.reaction_priority_player_id) if self.reaction_priority_player_id is not None else None
        name = player.name if player is not None else "-"
        return f"{trigger}. {detail} {name} ist als NÃ¤chstes mit Reagieren oder Passen am Zug."
    if self.phase == PHASE_ORDER_BLOCKERS:
        return "Lege die Reihenfolge fÃ¼r mehrere Blocker fest."
    if self.phase == PHASE_DICE_BATTLE:
        if self.pending_dice_battle is not None and self.pending_dice_battle.pending_comparison is not None:
            return "Anpassung ist mÃ¶glich. Entscheide Ã¼ber Neu WÃ¼rfeln oder AuflÃ¶sen."
        return "WÃ¤hle deinen WÃ¼rfel fÃ¼r den aktuellen Vergleich."
    return self.game_over_text


def get_button_specs(self) -> List[ButtonSpec]:
    if self.phase == PHASE_MULLIGAN:
        return [
            ButtonSpec("Mulligan bestÃ¤tigen", True, "confirm_mulligan"),
            ButtonSpec("Hand behalten", True, "keep_mulligan"),
        ]
    if self.phase == PHASE_GAME_OVER:
        return [
            ButtonSpec("Neue Partie", True, "new_game"),
        ]
    if self.pending_ai_action is not None:
        return [ButtonSpec("BestÃ¤tigen", True, "confirm_ai_action")]

    human_response_phases = {
        PHASE_DECLARE_BLOCKERS,
        PHASE_ORDER_BLOCKERS,
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
    if self.phase == PHASE_RESOURCE:
        buttons.append(ButtonSpec("Zur BeschwÃ¶rungsphase", True, "to_summoning"))
    elif self.phase == PHASE_SUMMONING:
        if self.available_attackers(self.active_player):
            buttons.append(ButtonSpec("Kampfphase", True, "to_combat"))
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
        buttons.append(ButtonSpec("Zauber bestÃ¤tigen", self.pending_spell_ready(), "confirm_spell_target"))
        buttons.append(ButtonSpec("Abbrechen", True, "cancel_spell_target"))
    elif self.phase == PHASE_RECYCLE_PAYMENT:
        ready = (
            self.pending_recycle_payment is not None
            and len(self.pending_recycle_payment.selected_resource_ids) == self.pending_recycle_payment.required_count
        )
        buttons.append(ButtonSpec("Recycle bestÃ¤tigen", ready, "confirm_recycle"))
        buttons.append(ButtonSpec("Abbrechen", True, "cancel_recycle"))
    elif self.phase == PHASE_FORCED_DISCARD:
        ready = (
            self.pending_forced_discard is not None
            and len(self.pending_forced_discard.selected_card_ids) == self.pending_forced_discard.required_count
        )
        buttons.append(ButtonSpec("Abwurf bestÃ¤tigen", ready, "confirm_forced_discard"))
    elif self.phase == PHASE_DECLARE_ATTACKERS:
        attacker_count = len(self.selected_attackers)
        attack_label = "Angriff Ã¼berspringen" if attacker_count <= 0 else f"{attacker_count} Angreifer bestÃ¤tigen"
        buttons.append(ButtonSpec(attack_label, True, "confirm_attackers"))
    elif self.phase == PHASE_DECLARE_BLOCKERS:
        blocker_count = sum(len(blocker_ids) for blocker_ids in self.block_assignments.values())
        block_label = "Blocken Ã¼berspringen" if blocker_count <= 0 else f"{blocker_count} Blocker bestÃ¤tigen"
        buttons.append(ButtonSpec(block_label, True, "confirm_blocks"))
        buttons.append(ButtonSpec("Blocker lÃ¶schen", True, "clear_blocks"))
    elif self.phase == PHASE_ORDER_BLOCKERS:
        ready = self.pending_order is not None and len(self.pending_order.chosen_order) == len(self.pending_order.blocker_ids)
        buttons.append(ButtonSpec("Reihenfolge speichern", ready, "confirm_order"))
        buttons.append(ButtonSpec("Reihenfolge reset", True, "reset_order"))
    elif self.phase == PHASE_DICE_BATTLE:
        if self.pending_dice_battle is not None and self.pending_dice_battle.pending_comparison is not None:
            buttons.append(ButtonSpec("Anpassung nutzen", True, "use_adaptation"))
            buttons.append(ButtonSpec("Vergleich werten", True, "resolve_comparison"))
        if self.pending_dice_battle is not None and self.pending_dice_battle.resolution_complete:
            button_label = "NÃ¤chster Kampf" if self.has_more_dice_battles_after_current() else "Kampf abschlieÃen"
            buttons.append(ButtonSpec(button_label, True, "end_dice_battle"))
    elif self.phase == PHASE_REACTION:
        buttons.append(ButtonSpec("Passen", True, "pass_reaction"))
    return buttons
