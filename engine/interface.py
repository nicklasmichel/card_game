from __future__ import annotations

from typing import List

from models import (
    Ability,
    BattlefieldCreature,
    ButtonSpec,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
    PHASE_RECYCLE_PAYMENT,
    PHASE_RESOURCE,
    PHASE_SUMMONING,
    ResourceCard,
)


def process_ai_turn(self) -> None:
    if self.phase in {PHASE_MULLIGAN, PHASE_GAME_OVER}:
        return
    ai_block_decision = self.phase == PHASE_DECLARE_BLOCKERS and not self.defending_player.is_human
    if self.active_player.is_human and not ai_block_decision:
        return
    if self.phase in {PHASE_ORDER_BLOCKERS, PHASE_DICE_BATTLE, PHASE_RECYCLE_PAYMENT, PHASE_FORCED_DISCARD}:
        return
    if not self.ai_turn_initialized:
        self.ai_turn_initialized = True

    if self.phase == PHASE_RESOURCE:
        if not self.active_player.summoner_tapped and self.active_player.deck:
            self.active_player.summoner_tapped = True
            drawn = self.active_player.draw_card()
            if drawn is not None:
                self.statistics.register_draw(self.active_player.player_id)
                if drawn.was_recycled:
                    self.statistics.register_recycled_card_drawn(self.active_player.player_id)
                self.log("Gegner tappt den Beschwörer und zieht eine Karte.")
        while self.active_player.resources_played_this_turn < 2:
            chosen = self.ai.choose_resource_card(self.active_player)
            if chosen is None:
                break
            self.ai_play_resource()
        self.phase = PHASE_SUMMONING
        self.log("Gegner wechselt in die Beschwörungsphase.")
        return

    if self.phase == PHASE_SUMMONING:
        self.ai_play_creatures()
        if self.phase == PHASE_SUMMONING:
            self.begin_attack_declaration()
        return

    if self.phase == PHASE_DECLARE_ATTACKERS and not self.active_player.is_human:
        self.ai_declare_attackers()
        return

    if self.phase == PHASE_DECLARE_BLOCKERS and not self.defending_player.is_human:
        self.ai_assign_blocks()
        self.begin_combat_resolution()
        return


def ai_play_resource(self) -> None:
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


def ai_play_creatures(self) -> None:
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
    for attacker in attackers:
        if not attacker.has_ability(Ability.VIGILANCE):
            attacker.tapped = True
    self.selected_attackers = [attacker.unit_id for attacker in attackers]
    self.statistics.register_attackers(self.active_player.player_id, len(attackers))
    if not attackers:
        self.log("Gegner greift nicht an.")
        self.end_turn()
        return
    self.block_assignments = {attacker.unit_id: [] for attacker in attackers}
    self.blocker_to_attackers.clear()
    self.phase = PHASE_DECLARE_BLOCKERS
    attacker_names = ", ".join(attacker.name for attacker in attackers)
    self.log(f"Gegner greift an mit: {attacker_names}. Wähle deine Blocker.")


def handle_click(self, area: str, item_id: int) -> None:
    if area == "player_summoner":
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
    if area == "enemy_creatures" and self.phase == PHASE_DECLARE_BLOCKERS and self.defending_player.is_human:
        self.toggle_selected_attack_target(item_id)
        return
    if area == "player_resources" and self.phase == PHASE_RECYCLE_PAYMENT:
        self.toggle_recycle_resource_selection(item_id)
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
        f"Züge: {row['turns_played']}",
        f"Lebenspunkte: Spieler {row['human_life_end']} | Gegner {row['ai_life_end']}",
        f"Ausgespielte Kreaturen: Spieler {row['human_creatures_played']} | Gegner {row['ai_creatures_played']}",
        f"Kreaturen-Kämpfe: {row['creature_combats']}",
        f"Zerstörte Kreaturen: Spieler {row['human_creatures_destroyed']} | Gegner {row['ai_creatures_destroyed']}",
        f"Spielerschaden: Spieler {row['human_player_damage_dealt']} | Gegner {row['ai_player_damage_dealt']}",
        f"Durchschnittliche Würfelvergleiche: {row['avg_dice_comparisons_per_combat']}",
        f"CSV Spielstatistik: {self.results_path}",
        f"CSV Kreaturen-Kämpfe: {self.creature_results_path}",
    ]
    self.game_over_summary_lines = summary
    print("\nSpielende")
    for line in summary:
        print(line)


def current_prompt(self) -> str:
    if self.phase == PHASE_MULLIGAN:
        return "Wähle Karten für den Mulligan oder behalte die Starthand."
    if self.phase == PHASE_RESOURCE:
        return "Lege bis zu 2 Handkarten als Ressource."
    if self.phase == PHASE_SUMMONING:
        return "Spiele Kreaturen aus, beginne den Kampf oder beende den Zug."
    if self.phase == PHASE_RECYCLE_PAYMENT:
        pending = self.pending_recycle_payment
        if pending is None:
            return "Wähle Recycle-Ressourcen aus."
        card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
        card_name = card.template.name if card is not None else "die Karte"
        return (
            f"Wähle {pending.required_count} Ressourcen für {card_name}. "
            f"Ausgewählt: {len(pending.selected_resource_ids)}/{pending.required_count}."
        )
    if self.phase == PHASE_FORCED_DISCARD:
        pending = self.pending_forced_discard
        if pending is None:
            return "Wähle Handkarten zum Abwerfen."
        return (
            f"Wähle {pending.required_count} Handkarte(n) für {pending.source_card_name}. "
            f"Ausgewählt: {len(pending.selected_card_ids)}/{pending.required_count}."
        )
    if self.phase == PHASE_DECLARE_ATTACKERS:
        return "Wähle Angreifer und bestätige."
    if self.phase == PHASE_DECLARE_BLOCKERS:
        return "Wähle einen Angreifer und ordne dann eigene Blocker zu."
    if self.phase == PHASE_ORDER_BLOCKERS:
        return "Lege die Reihenfolge für mehrere Blocker fest."
    if self.phase == PHASE_DICE_BATTLE:
        if self.pending_dice_battle is not None and self.pending_dice_battle.pending_comparison is not None:
            return "Anpassung ist möglich. Entscheide über Neu Würfeln oder Auflösen."
        return "Wähle deinen Würfel für den aktuellen Vergleich."
    return self.game_over_text


def get_button_specs(self) -> List[ButtonSpec]:
    if self.phase == PHASE_MULLIGAN:
        return [
            ButtonSpec("Mulligan bestätigen", True, "confirm_mulligan"),
            ButtonSpec("Hand behalten", True, "keep_mulligan"),
        ]
    if self.phase == PHASE_GAME_OVER:
        return [
            ButtonSpec("Neue Partie", True, "new_game"),
        ]
    human_response_phases = {
        PHASE_DECLARE_BLOCKERS,
        PHASE_ORDER_BLOCKERS,
        PHASE_DICE_BATTLE,
        PHASE_RECYCLE_PAYMENT,
        PHASE_FORCED_DISCARD,
    }
    if not self.active_player.is_human and self.phase not in human_response_phases:
        return []

    buttons: List[ButtonSpec] = []
    if self.phase == PHASE_RESOURCE:
        buttons.append(ButtonSpec("Zur Beschwörungsphase", True, "to_summoning"))
    elif self.phase == PHASE_SUMMONING:
        buttons.append(ButtonSpec("Kampfphase", True, "to_combat"))
        buttons.append(ButtonSpec("Zug beenden", True, "end_turn"))
    elif self.phase == PHASE_RECYCLE_PAYMENT:
        ready = (
            self.pending_recycle_payment is not None
            and len(self.pending_recycle_payment.selected_resource_ids) == self.pending_recycle_payment.required_count
        )
        buttons.append(ButtonSpec("Recycle bestätigen", ready, "confirm_recycle"))
        buttons.append(ButtonSpec("Abbrechen", True, "cancel_recycle"))
    elif self.phase == PHASE_FORCED_DISCARD:
        ready = (
            self.pending_forced_discard is not None
            and len(self.pending_forced_discard.selected_card_ids) == self.pending_forced_discard.required_count
        )
        buttons.append(ButtonSpec("Abwurf bestätigen", ready, "confirm_forced_discard"))
    elif self.phase == PHASE_DECLARE_ATTACKERS:
        attacker_count = len(self.selected_attackers)
        attack_label = "Angriff überspringen" if attacker_count <= 0 else f"{attacker_count} Angreifer bestätigen"
        buttons.append(ButtonSpec(attack_label, True, "confirm_attackers"))
    elif self.phase == PHASE_DECLARE_BLOCKERS:
        blocker_count = sum(len(blocker_ids) for blocker_ids in self.block_assignments.values())
        block_label = "Blocken überspringen" if blocker_count <= 0 else f"{blocker_count} Blocker bestätigen"
        buttons.append(ButtonSpec(block_label, True, "confirm_blocks"))
        buttons.append(ButtonSpec("Blocker löschen", True, "clear_blocks"))
    elif self.phase == PHASE_ORDER_BLOCKERS:
        ready = self.pending_order is not None and len(self.pending_order.chosen_order) == len(self.pending_order.blocker_ids)
        buttons.append(ButtonSpec("Reihenfolge speichern", ready, "confirm_order"))
        buttons.append(ButtonSpec("Reihenfolge reset", True, "reset_order"))
    elif self.phase == PHASE_DICE_BATTLE:
        if self.pending_dice_battle is not None and self.pending_dice_battle.pending_comparison is not None:
            buttons.append(ButtonSpec("Anpassung nutzen", True, "use_adaptation"))
            buttons.append(ButtonSpec("Vergleich werten", True, "resolve_comparison"))
        if self.pending_dice_battle is not None and self.pending_dice_battle.resolution_complete:
            button_label = "Nächster Kampf" if self.has_more_dice_battles_after_current() else "Kampf abschließen"
            buttons.append(ButtonSpec(button_label, True, "end_dice_battle"))
    return buttons
