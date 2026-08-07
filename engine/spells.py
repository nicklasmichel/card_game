from __future__ import annotations

from typing import Callable, Optional

from core.models import (
    Ability,
    CardInstance,
    CardType,
    Element,
    MAIN_PHASES,
    PendingSpellCast,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PHASE_REACTION,
    PHASE_SPELL_TARGETING,
    ReactionContext,
    ReactionTrigger,
    ResourceCard,
    SpellEffect,
    SpellTiming,
    SpellTargetMode,
    SpellTargetRef,
    StackItem,
)


GENERAL_SPELL_WINDOW_TRIGGERS = {
    ReactionTrigger.MAIN_1_PRIORITY,
    ReactionTrigger.MAIN_2_PRIORITY,
    ReactionTrigger.COMBAT_START,
    ReactionTrigger.COMBAT_END,
}

MAIN_PHASE_PRIORITY_TRIGGERS = {
    ReactionTrigger.MAIN_1_PRIORITY,
    ReactionTrigger.MAIN_2_PRIORITY,
}

REACTION_WINDOW_PROFILES = {
    ReactionTrigger.SPELL_CAST: {
        "title": "Reaktionsfenster",
        "description": "Ein Zauber wurde gespielt. Passende Zauber koennen jetzt darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": False,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.MAIN_1_PRIORITY: {
        "title": "Hauptphase 1",
        "description": "Vor dem Kampf koennen nur Spontanzauber gespielt werden.",
        "is_general_window": True,
        "is_combat_window": False,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.MAIN_2_PRIORITY: {
        "title": "Hauptphase 2",
        "description": "Vor Zugende koennen nur Spontanzauber gespielt werden.",
        "is_general_window": True,
        "is_combat_window": False,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.COMBAT_START: {
        "title": "Kampfbeginn",
        "description": "Nach Angreifern, Blockern und Reihenfolge koennen nur Kampfzauber gespielt werden.",
        "is_general_window": True,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.COMBAT_END: {
        "title": "Kampfende",
        "description": "Der Kampf ist beendet. Vor der zweiten Hauptphase koennen nur Kampfzauber gespielt werden.",
        "is_general_window": True,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.OWN_CREATURE_DESTROYED: {
        "title": "Reaktionsfenster",
        "description": "Eine eigene Kreatur wurde zerstoert. Passende Zauber koennen darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.OWN_CREATURE_TARGETED: {
        "title": "Reaktionsfenster",
        "description": "Eine eigene Kreatur wurde als Ziel gewÃ¤hlt. Passende Zauber koennen darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": False,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
}


def get_player_by_id(self, player_id: int):
    return self.players[player_id]


def is_general_spell_window_trigger(self, trigger: ReactionTrigger) -> bool:
    return trigger in GENERAL_SPELL_WINDOW_TRIGGERS


def get_reaction_window_title(self, context: ReactionContext | None = None) -> str:
    active_context = context or self.reaction_context
    if active_context is None:
        return "Reaktionsfenster"
    return get_reaction_window_profile(self, active_context).get("title", "Reaktionsfenster")


def get_reaction_window_description(self, context: ReactionContext | None = None) -> str:
    active_context = context or self.reaction_context
    if active_context is None:
        return "-"
    return get_reaction_window_profile(self, active_context).get("description", active_context.trigger.value)


def get_reaction_window_profile(self, context: ReactionContext | None = None) -> dict:
    active_context = context or self.reaction_context
    if active_context is None:
        return {
            "title": "Reaktionsfenster",
            "description": "-",
            "is_general_window": False,
            "is_combat_window": False,
            "shows_stack_preview": True,
            "allows_die_targets": False,
        }
    return REACTION_WINDOW_PROFILES.get(
        active_context.trigger,
        {
            "title": "Reaktionsfenster",
            "description": active_context.trigger.value,
            "is_general_window": False,
            "is_combat_window": False,
            "shows_stack_preview": True,
            "allows_die_targets": False,
        },
    )


def reaction_window_is_combat_window(self, context: ReactionContext | None = None) -> bool:
    return bool(get_reaction_window_profile(self, context).get("is_combat_window", False))


def reaction_window_shows_stack_preview(self, context: ReactionContext | None = None) -> bool:
    return bool(get_reaction_window_profile(self, context).get("shows_stack_preview", True))


def is_combat_priority_window(self, context: ReactionContext | None = None) -> bool:
    active_context = context or self.reaction_context
    return active_context is not None and active_context.trigger in {
        ReactionTrigger.COMBAT_START,
        ReactionTrigger.COMBAT_END,
    }


def get_combat_window_eligible_player_ids(self, context: ReactionContext, first_responder_id: int) -> list[int]:
    ordered_ids = [first_responder_id, 1 - first_responder_id]
    return [
        player_id
        for player_id in ordered_ids
        if has_legal_reaction_for_player(self, self.get_player_by_id(player_id), context)
    ]


def log_combat_window_auto_passes(self, context: ReactionContext) -> None:
    title = self.get_reaction_window_title(context)
    self.log(f"{title} wird automatisch uebersprungen.")
    for player in self.players:
        self.log(f"{player.name} passt automatisch.")


def advance_combat_window_priority(self) -> None:
    context = self.reaction_context
    while self.reaction_sequence_index + 1 < len(self.reaction_sequence_player_ids):
        self.reaction_sequence_index += 1
        next_player_id = self.reaction_sequence_player_ids[self.reaction_sequence_index]
        next_player = self.get_player_by_id(next_player_id)
        if has_legal_reaction_for_player(self, next_player, context):
            self.reaction_priority_player_id = next_player_id
            self.log(f"{next_player.name} ist als Naechstes mit Reagieren oder Passen am Zug.")
            return
        self.log(f"{next_player.name} passt automatisch.")
    self.finish_reaction_window()


def begin_general_spell_window(
    self,
    *,
    trigger: ReactionTrigger,
    first_responder_id: int,
    resume_phase: str,
    continuation: Optional[Callable[[], None]] = None,
    **context_fields,
) -> None:
    if not self.is_general_spell_window_trigger(trigger):
        raise ValueError(f"{trigger.value} ist kein allgemeines Zauberfenster.")
    self.begin_reaction_window(
        context=ReactionContext(
            trigger=trigger,
            active_player=self.active_player,
            source_player=self.active_player,
            **context_fields,
        ),
        first_responder_id=first_responder_id,
        base_stack_size=len(self.spell_stack),
        resume_phase=resume_phase,
        continuation=continuation,
    )


def begin_triggered_reaction_window(
    self,
    *,
    context: ReactionContext,
    first_responder_id: int,
    resume_phase: str,
    continuation: Optional[Callable[[], None]] = None,
    base_stack_size: Optional[int] = None,
) -> None:
    self.begin_reaction_window(
        context=context,
        first_responder_id=first_responder_id,
        base_stack_size=len(self.spell_stack) if base_stack_size is None else base_stack_size,
        resume_phase=resume_phase,
        continuation=continuation,
    )


def is_spell_card(self, card: CardInstance) -> bool:
    return card.template.card_type in {CardType.RITUAL, CardType.SPELL}


def can_play_card(self, player, card: CardInstance) -> bool:
    if card.template.card_type == CardType.CREATURE:
        return player.can_pay(self.get_card_cost_to_pay(player, card))
    if not player.can_pay(card.template.cost):
        return False
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
        return len(get_valid_discard_creature_target_refs(self, player)) >= max(1, card.template.spell_amount)
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
        return count_valid_return_to_hand_targets(self) >= max(1, card.template.spell_amount)
    if card.template.card_type == CardType.RITUAL:
        return (
            player == self.active_player
            and self.phase in MAIN_PHASES
            and self.pending_spell_cast is None
            and not self.resolving_stack
            and (not card.template.sacrifice_own_creature_on_cast or bool(player.battlefield))
        )
    if card.template.card_type == CardType.SPELL:
        if self.phase in MAIN_PHASES and self.pending_spell_cast is None and not self.resolving_stack:
            return is_spell_legal_in_main_phase(self, player, card)
        return self.can_react_with_card(player, card)
    return False


def can_react_with_card(self, player, card: CardInstance) -> bool:
    if card.template.card_type != CardType.SPELL:
        return False
    if self.phase != PHASE_REACTION or self.reaction_context is None:
        return False
    if self.reaction_priority_player_id != player.player_id:
        return False
    if not player.can_pay(card.template.cost):
        return False
    return is_spell_legal_in_reaction_context(self, player, card, self.reaction_context)


def is_spell_legal_in_main_phase(self, player, card: CardInstance) -> bool:
    return (
        card.template.card_type == CardType.SPELL
        and player == self.active_player
        and self.phase in {PHASE_MAIN_1, PHASE_MAIN_2}
        and getattr(card.template, "spell_timing", None) == SpellTiming.INSTANT
    )


def is_spell_legal_in_reaction_context(self, player, card: CardInstance, context: ReactionContext) -> bool:
    timing = getattr(card.template, "spell_timing", None)
    if timing == SpellTiming.COMBAT:
        legal_windows = set(getattr(card.template, "legal_reaction_windows", ()))
        if context.trigger not in legal_windows:
            return False
    elif timing == SpellTiming.INSTANT:
        if reaction_window_is_combat_window(self, context) or context.trigger in {
            ReactionTrigger.COMBAT_START,
            ReactionTrigger.COMBAT_END,
        }:
            return False
    if card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
        return bool(get_valid_turn_attack_bonus_targets(self, player, context))
    if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
        return bool(get_valid_damage_spell_targets(self, player, context))
    if card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
        return context.trigger == ReactionTrigger.COMBAT_START and has_valid_attacker_combat_bonus_targets(self, player, context)
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
        return count_valid_return_to_hand_targets(self) >= max(1, card.template.spell_amount)
    trigger = card.template.reaction_trigger
    if trigger is None:
        return True
    if trigger == ReactionTrigger.OWN_CREATURE_DESTROYED:
        owner_id = get_reaction_creature_owner_id(
            self,
            context.source_creature,
            fallback_player_id=getattr(context.source_player, "player_id", None),
        )
        return context.trigger == trigger and context.source_creature is not None and owner_id == player.player_id
    if trigger == ReactionTrigger.OWN_CREATURE_TARGETED:
        owner_id = get_reaction_creature_owner_id(self, context.target_creature)
        return (
            context.trigger == trigger
            and context.target_creature is not None
            and owner_id == player.player_id
            and context.source_player is not None
            and context.source_player.player_id != player.player_id
        )
    return context.trigger == ReactionTrigger.SPELL_CAST


def has_any_legal_reaction(self, context: ReactionContext) -> bool:
    for player in self.players:
        if has_legal_reaction_for_player(self, player, context):
            return True
    return False


def has_legal_reaction_for_player(self, player, context: ReactionContext) -> bool:
    for card in player.hand:
        if card.template.card_type != CardType.SPELL:
            continue
        if not player.can_pay(card.template.cost):
            continue
        if is_spell_legal_in_reaction_context(self, player, card, context):
            return True
    return False


def begin_spell_cast(self, card_id: int) -> bool:
    if not self.active_player.is_human or self.phase not in MAIN_PHASES:
        return False
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
    if card is None:
        self.log("Diese Karte ist nicht mehr auf der Hand.")
        return False
    if not self.can_play_card(self.active_player, card):
        self.log("Diese Karte kann gerade nicht gespielt werden.")
        return False
    return self.begin_spell_cast_from_card(card, self.phase)


def begin_spell_from_hand(self, card_id: int) -> bool:
    if self.phase != PHASE_REACTION or self.reaction_priority_player_id != self.human_player.player_id:
        return False
    card = next((existing for existing in self.human_player.hand if existing.instance_id == card_id), None)
    if card is None or not self.can_react_with_card(self.human_player, card):
        self.log("Dieser Zauber ist in diesem Fenster nicht legal.")
        return False
    return self.begin_spell_cast_from_card(card, PHASE_REACTION)


def begin_spell_cast_from_card(self, card: CardInstance, origin_phase: str) -> bool:
    controller = self.active_player if origin_phase in MAIN_PHASES else (
        self.get_player_by_id(self.reaction_priority_player_id) if self.reaction_priority_player_id is not None else None
    )
    if controller is None:
        return False
    if origin_phase in MAIN_PHASES:
        if not self.can_play_card(controller, card):
            self.log("Diese Karte kann gerade nicht gespielt werden.")
            return False
    elif origin_phase == PHASE_REACTION:
        if not self.can_react_with_card(controller, card):
            self.log("Dieser Zauber ist in diesem Fenster nicht legal.")
            return False
    if not spell_cast_needs_interaction(self, card):
        return self.commit_spell_cast(card, origin_phase, [])
    self.pending_spell_cast = PendingSpellCast(
        card_instance_id=card.instance_id,
        controller_id=self.active_player.player_id if origin_phase in MAIN_PHASES else self.reaction_priority_player_id,
        origin_phase=origin_phase,
    )
    self.phase = PHASE_SPELL_TARGETING
    self.selected_hand_ids = [card.instance_id]
    self.log(self.describe_pending_spell_requirements())
    return True


def describe_pending_spell_requirements(self) -> str:
    pending = self.pending_spell_cast
    if pending is None:
        return "Zauberziel waehlen."
    card = self.get_card_from_pending_spell(pending)
    if card is None:
        return "Zauberziel waehlen."
    controller = self.get_player_by_id(pending.controller_id)
    if card.template.recycle_cost > 0 and len(pending.selected_recycle_resource_ids) < card.template.recycle_cost:
        return (
            f"Waehle {card.template.recycle_cost} Ressourcen fuer Recycle von {card.template.name}. "
            f"Ausgewaehlt: {len(pending.selected_recycle_resource_ids)}/{card.template.recycle_cost}."
        )
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
        remaining = max(0, card.template.spell_amount - len(pending.selected_targets))
        if remaining > 0:
            return (
                f"Waehle {remaining} Kreaturenkarte(n) aus deinem Ablagestapel fuer {card.template.name}. "
                f"Ausgewaehlt: {len(pending.selected_targets)}/{card.template.spell_amount}."
            )
        return f"Bestaetige {card.template.name}."
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
        remaining = max(0, card.template.spell_amount - len(pending.selected_targets))
        if remaining > 0:
            return (
                f"Waehle {remaining} Kreatur(en) fuer {card.template.name}. "
                f"Ausgewaehlt: {len(pending.selected_targets)}/{card.template.spell_amount}."
            )
        return f"Bestaetige {card.template.name}."
    if card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
        parts = []
        if card.template.combat_aw_bonus:
            parts.append(f"+{card.template.combat_aw_bonus} AW")
        if card.template.combat_sw_bonus:
            parts.append(f"+{card.template.combat_sw_bonus} SW")
        return f"Bestaetige {card.template.name}. Eigene Angreifer erhalten fuer diesen Kampf {' und '.join(parts)}."
    if card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
        parts = []
        if card.template.combat_aw_bonus:
            parts.append(f"+{card.template.combat_aw_bonus} AW")
        if card.template.combat_sw_bonus:
            parts.append(f"+{card.template.combat_sw_bonus} SW")
        suffix = f" ({' und '.join(parts)})" if parts else ""
        return f"Waehle eine eigene kaempfende Kreatur als Ziel fuer {card.template.name}{suffix}."
    if card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        if not pending.selected_targets:
            return f"Waehle eine Kreatur als Ziel fuer {card.template.name}."
        if pending.selected_keyword_ability is None:
            return f"Waehle fuer {card.template.name} Schnell oder Fliegend."
        return f"Bestaetige {card.template.name}."
    if card.template.spell_effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
        own_available = bool(controller.battlefield)
        enemy_available = bool(self.players[1 - controller.player_id].battlefield)
        own_selected = any(is_target_controlled_by(self, target, controller.player_id) for target in pending.selected_targets)
        enemy_selected = any(is_target_controlled_by(self, target, 1 - controller.player_id) for target in pending.selected_targets)
        if own_available and not own_selected:
            return f"Waehle eine eigene Kreatur fuer {card.template.name}."
        if enemy_available and not enemy_selected:
            return f"Waehle eine gegnerische Kreatur fuer {card.template.name}."
        return f"Bestaetige {card.template.name}."
    if card.template.sacrifice_own_creature_on_cast and pending.selected_sacrifice_creature_id is None:
        return f"Waehle eine eigene Kreatur als Opfer fuer {card.template.name}."
    if card.template.target_mode == SpellTargetMode.CREATURE:
        return f"Waehle eine Kreatur als Ziel fuer {card.template.name}."
    if card.template.target_mode == SpellTargetMode.CREATURE_OR_PLAYER:
        return f"Waehle eine Kreatur oder einen Spieler als Ziel fuer {card.template.name}."
    return f"Bestaetige {card.template.name}."


def get_card_from_pending_spell(self, pending: PendingSpellCast | None = None) -> CardInstance | None:
    pending = pending or self.pending_spell_cast
    if pending is None:
        return None
    controller = self.get_player_by_id(pending.controller_id)
    return next((card for card in controller.hand if card.instance_id == pending.card_instance_id), None)


def select_pending_spell_keyword(self, ability: Ability) -> None:
    pending = self.pending_spell_cast
    if pending is None or self.phase != PHASE_SPELL_TARGETING:
        return
    card = self.get_card_from_pending_spell(pending)
    if card is None or card.template.spell_effect != SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        return
    if ability not in {Ability.HASTE, Ability.FLYING}:
        return
    if not pending.selected_targets:
        self.log("Waehle zuerst eine Kreatur als Ziel.")
        return
    pending.selected_keyword_ability = ability
    self.log(self.describe_pending_spell_requirements())


def select_spell_target_ref(self, target: SpellTargetRef) -> None:
    pending = self.pending_spell_cast
    if pending is None or self.phase != PHASE_SPELL_TARGETING:
        return
    card = self.get_card_from_pending_spell(pending)
    if card is None:
        self.cancel_pending_spell_cast()
        return
    controller = self.get_player_by_id(pending.controller_id)
    if card.template.recycle_cost > 0 and len(pending.selected_recycle_resource_ids) < card.template.recycle_cost:
        self.log("Waehle zuerst die Recycle-Ressourcen.")
        return
    if card.template.sacrifice_own_creature_on_cast and pending.selected_sacrifice_creature_id is None:
        if target.target_type != "creature":
            self.log("Waehle zuerst eine eigene Kreatur als Opfer.")
            return
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None or self.get_unit_owner(creature.unit_id) != controller:
            self.log("Du musst eine eigene Kreatur opfern.")
            return
        pending.selected_sacrifice_creature_id = creature.unit_id
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.target_mode == SpellTargetMode.NONE and card.template.spell_effect not in {
        SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND,
        SpellEffect.RETURN_CREATURES_TO_HAND,
    }:
        return
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
        if target.target_type != "discard_card":
            self.log("Dieser Zauber benoetigt Kreaturenkarten aus deinem Ablagestapel als Ziele.")
            return
        discard_card = resolve_target_discard_card(self, target)
        if discard_card is None:
            self.log("Diese Karte ist kein gueltiges Ziel mehr.")
            return
        remaining_targets = [existing for existing in pending.selected_targets if existing.card_instance_id != target.card_instance_id]
        pending.selected_targets = (remaining_targets + [target])[: card.template.spell_amount]
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
        if target.target_type != "creature":
            self.log("Dieser Zauber benoetigt Kreaturen als Ziele.")
            return
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None:
            self.log("Diese Kreatur ist nicht mehr im Spiel.")
            return
        if not can_target_creature_with_explicit_spell(self, creature):
            self.log("Diese Kreatur kann nicht als Ziel eines Zaubers gewaehlt werden.")
            return
        remaining_targets = [existing for existing in pending.selected_targets if existing.creature_id != target.creature_id]
        pending.selected_targets = (remaining_targets + [target])[: card.template.spell_amount]
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        if target.target_type != "creature":
            self.log("Dieser Zauber benoetigt eine Kreatur als Ziel.")
            return
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None or not can_target_creature_with_explicit_spell(self, creature):
            self.log("Diese Kreatur kann nicht als Ziel eines Zaubers gewaehlt werden.")
            return
        pending.selected_targets = [target]
        pending.selected_keyword_ability = None
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
        if target.target_type != "creature":
            self.log("Dieser Zauber benoetigt eine Kreatur als Ziel.")
            return
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None or not is_valid_turn_attack_bonus_target(self, controller, creature, self.reaction_context):
            self.log("Dieser Zauber kann nur eine eigene kaempfende Kreatur als Ziel waehlen.")
            return
        pending.selected_targets = [target]
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
        if target.target_type != "creature":
            self.log("Dieser Zauber benoetigt eine Kreatur als Ziel.")
            return
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None or not is_valid_damage_spell_target(self, controller, creature, self.reaction_context):
            self.log("Diese Kreatur ist in diesem Fenster kein gueltiges Ziel.")
            return
        pending.selected_targets = [target]
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.spell_effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
        if target.target_type != "creature":
            self.log("Dieser Zauber benoetigt Kreaturen als Ziele.")
            return
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None:
            self.log("Diese Kreatur ist nicht mehr im Spiel.")
            return
        if not can_target_creature_with_explicit_spell(self, creature):
            self.log("Diese Kreatur kann nicht als Ziel eines Zaubers gewaehlt werden.")
            return
        owner = self.get_unit_owner(creature.unit_id)
        if owner is None:
            self.log("Diese Kreatur ist nicht mehr im Spiel.")
            return
        own_available = bool(controller.battlefield)
        own_selected = any(is_target_controlled_by(self, existing, controller.player_id) for existing in pending.selected_targets)
        filtered_targets = [
            existing
            for existing in pending.selected_targets
            if is_target_controlled_by(self, existing, controller.player_id) != (owner.player_id == controller.player_id)
        ]
        if owner.player_id == controller.player_id:
            pending.selected_targets = [target] + filtered_targets
        else:
            if own_available and not own_selected:
                self.log("Waehle zuerst eine eigene Kreatur.")
                return
            pending.selected_targets = filtered_targets + [target]
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.target_mode == SpellTargetMode.CREATURE and target.target_type != "creature":
        self.log("Dieser Zauber benoetigt eine Kreatur als Ziel.")
        return
    if card.template.target_mode == SpellTargetMode.CREATURE and target.target_type == "creature":
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None or not can_target_creature_with_explicit_spell(self, creature):
            self.log("Diese Kreatur kann nicht als Ziel eines Zaubers gewaehlt werden.")
            return
        pending.selected_targets = [target]
    elif card.template.target_mode == SpellTargetMode.CREATURE_OR_PLAYER:
        if target.target_type == "creature":
            creature = self.get_unit_by_id(target.creature_id or -1)
            if creature is None or not can_target_creature_with_explicit_spell(self, creature):
                self.log("Diese Kreatur kann nicht als Ziel eines Zaubers gewaehlt werden.")
                return
        pending.selected_targets = [target]
    self.log(self.describe_pending_spell_requirements())


def toggle_pending_spell_recycle_resource(self, resource_id: int) -> None:
    pending = self.pending_spell_cast
    if pending is None or self.phase != PHASE_SPELL_TARGETING:
        return
    card = self.get_card_from_pending_spell(pending)
    if card is None or card.template.recycle_cost <= 0:
        return
    controller = self.get_player_by_id(pending.controller_id)
    if not any(existing.resource_id == resource_id for existing in controller.resources):
        return
    selected = pending.selected_recycle_resource_ids
    if resource_id in selected:
        selected.remove(resource_id)
    elif len(selected) < card.template.recycle_cost:
        selected.append(resource_id)
    else:
        self.log("Es wurden bereits genug Ressourcen fuer Recycle ausgewaehlt.")
        return
    self.log(self.describe_pending_spell_requirements())


def pending_spell_ready(self) -> bool:
    pending = self.pending_spell_cast
    if pending is None:
        return False
    card = self.get_card_from_pending_spell(pending)
    if card is None:
        return False
    if len(pending.selected_recycle_resource_ids) != card.template.recycle_cost:
        return False
    if card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        return len(pending.selected_targets) == 1 and pending.selected_keyword_ability is not None
    if card.template.spell_effect in {
        SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN,
    }:
        return len(pending.selected_targets) == 1
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
        return len(pending.selected_targets) == card.template.spell_amount
    if card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
        return len(pending.selected_targets) == card.template.spell_amount
    if card.template.spell_effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
        controller = self.get_player_by_id(pending.controller_id)
        own_required = 1 if controller.battlefield else 0
        enemy_required = 1 if self.players[1 - controller.player_id].battlefield else 0
        own_selected = sum(1 for target in pending.selected_targets if is_target_controlled_by(self, target, controller.player_id))
        enemy_selected = len(pending.selected_targets) - own_selected
        return own_selected >= own_required and enemy_selected >= enemy_required
    if card.template.sacrifice_own_creature_on_cast and pending.selected_sacrifice_creature_id is None:
        return False
    if card.template.target_mode == SpellTargetMode.NONE:
        return True
    return len(pending.selected_targets) == 1


def confirm_pending_spell_cast(self) -> bool:
    pending = self.pending_spell_cast
    if pending is None or not self.pending_spell_ready():
        self.log("Der Zauber ist noch nicht vollstaendig vorbereitet.")
        return False
    card = self.get_card_from_pending_spell(pending)
    if card is None:
        self.cancel_pending_spell_cast()
        return False
    origin_phase = pending.origin_phase
    targets = list(pending.selected_targets)
    sacrifice_creature_id = pending.selected_sacrifice_creature_id
    selected_keyword_ability = pending.selected_keyword_ability
    recycle_resource_ids = list(pending.selected_recycle_resource_ids)
    self.pending_spell_cast = None
    self.selected_hand_ids.clear()
    return self.commit_spell_cast(
        card,
        origin_phase,
        targets,
        sacrifice_creature_id,
        selected_keyword_ability,
        recycle_resource_ids,
    )


def cancel_pending_spell_cast(self) -> None:
    if self.pending_spell_cast is None:
        return
    origin_phase = self.pending_spell_cast.origin_phase
    self.pending_spell_cast = None
    self.selected_hand_ids.clear()
    self.phase = origin_phase
    self.log("Zauberabwicklung abgebrochen.")


def commit_spell_cast(
    self,
    card: CardInstance,
    origin_phase: str,
    targets: list[SpellTargetRef],
    sacrifice_creature_id: int | None = None,
    selected_keyword_ability: Ability | None = None,
    recycle_resource_ids: list[int] | None = None,
) -> bool:
    controller = self.active_player if origin_phase in MAIN_PHASES else self.get_player_by_id(self.reaction_priority_player_id)
    if not controller.can_pay(card.template.cost):
        self.log("Nicht genuegend Ressourcen fuer diesen Zauber.")
        return False
    if card.template.sacrifice_own_creature_on_cast and sacrifice_creature_id is None:
        self.log("Es muss eine eigene Kreatur geopfert werden.")
        return False
    recycle_resource_ids = recycle_resource_ids or []
    if card.template.recycle_cost > 0:
        if len(recycle_resource_ids) != card.template.recycle_cost:
            self.log("Die benoetigten Recycle-Ressourcen wurden nicht ausgewaehlt.")
            return False
        if len(set(recycle_resource_ids)) != len(recycle_resource_ids):
            self.log("Eine Ressource kann fuer Recycle nicht mehrfach verwendet werden.")
            return False
        available_resource_ids = {
            resource.resource_id
            for resource in controller.resources
            if resource.resource_id is not None
        }
        if any(resource_id not in available_resource_ids for resource_id in recycle_resource_ids):
            self.log("Mindestens eine ausgewaehlte Recycle-Ressource ist nicht mehr verfuegbar.")
            return False
    tapped_resources = controller.tap_resources_for_cost(card.template.resource_cost)
    if len(tapped_resources) != card.template.resource_cost:
        self.log("Nicht genuegend bereite Ressourcen.")
        return False
    if card.template.recycle_cost > 0:
        resources_to_recycle = [resource for resource in controller.resources if resource.resource_id in recycle_resource_ids]
        if len(resources_to_recycle) != card.template.recycle_cost:
            self.log("Recycle konnte nicht vollstaendig bezahlt werden.")
            return False
        controller.resources = [resource for resource in controller.resources if resource.resource_id not in recycle_resource_ids]
        recycled_cards = [CardInstance(self.make_instance_id(), resource.template, was_recycled=True) for resource in resources_to_recycle]
        controller.deck.extend(recycled_cards)
        self.rng.shuffle(controller.deck)
        self.queue_recycle_reveal_event(controller.player_id, [resource.template.template_id for resource in resources_to_recycle])
        if self.statistics is not None:
            self.statistics.register_recycle_payment(controller.player_id, card.template.recycle_cost)
    sacrificed_power = 0
    destroyed_context: ReactionContext | None = None
    if sacrifice_creature_id is not None:
        creature = self.get_unit_by_id(sacrifice_creature_id)
        if creature is None or self.get_unit_owner(sacrifice_creature_id) != controller:
            self.log("Die ausgewaehlte Opferkreatur ist nicht mehr verfuegbar.")
            return False
        sacrificed_power = self.get_creature_attack_value(creature)
        destroyed_context = self.destroy_creature_immediately(controller, creature, card.template.name)
    controller.hand = [existing for existing in controller.hand if existing.instance_id != card.instance_id]
    stack_item = StackItem(
        source_card=card,
        controller=controller,
        targets=targets,
        effect=card.template.spell_effect,
        context=self.reaction_context,
        amount=card.template.spell_amount,
        draw_count=card.template.spell_draw_count,
        sacrificed_creature_power=sacrificed_power,
        selected_keyword_ability=selected_keyword_ability,
    )
    self.spell_stack.append(stack_item)
    self.log(f"{controller.name} spielt {card.template.name}.")
    self.register_hand_card_played(controller)
    if self.statistics is not None:
        if card.template.card_type == CardType.RITUAL:
            self.statistics.register_ritual_played(controller.player_id)
        else:
            self.statistics.register_spell_played(controller.player_id)
    if origin_phase == PHASE_REACTION:
        self.phase = PHASE_REACTION
        if is_combat_priority_window(self) and self.reaction_sequence_player_ids:
            self.advance_combat_window_priority()
            return True
        self.reaction_pass_count = 0
        self.reaction_priority_player_id = 1 - controller.player_id
        return True
    context = destroyed_context or build_spell_reaction_context(self, controller, card, targets)
    first_responder = 1 - controller.player_id
    self.begin_triggered_reaction_window(
        context=context,
        first_responder_id=first_responder,
        resume_phase=origin_phase,
        continuation=self.finish_spell_resolution_after_reaction,
        base_stack_size=max(0, len(self.spell_stack) - 1),
    )
    return True


def finish_spell_resolution_after_reaction(self) -> None:
    return


def begin_reaction_window(
    self,
    context: ReactionContext,
    first_responder_id: int,
    base_stack_size: int,
    resume_phase: str,
    continuation: Optional[Callable[[], None]] = None,
) -> None:
    is_general_window = bool(get_reaction_window_profile(self, context).get("is_general_window", False))
    is_combat_window = is_combat_priority_window(self, context)
    if len(self.spell_stack) <= base_stack_size and context.trigger in MAIN_PHASE_PRIORITY_TRIGGERS and not has_any_legal_reaction(self, context):
        self.phase = resume_phase
        if continuation is not None:
            continuation()
        return
    if len(self.spell_stack) <= base_stack_size and is_general_window and is_combat_window:
        eligible_player_ids = get_combat_window_eligible_player_ids(self, context, first_responder_id)
        if not eligible_player_ids:
            log_combat_window_auto_passes(self, context)
            self.phase = resume_phase
            if continuation is not None:
                continuation()
            return
    if len(self.spell_stack) <= base_stack_size and not is_general_window and not has_any_legal_reaction(self, context):
        self.phase = resume_phase
        if continuation is not None:
            continuation()
        return
    self.reaction_context = context
    self.reaction_sequence_player_ids = []
    self.reaction_sequence_index = 0
    if is_general_window and is_combat_window:
        self.reaction_sequence_player_ids = get_combat_window_eligible_player_ids(self, context, first_responder_id)
        self.reaction_priority_player_id = self.reaction_sequence_player_ids[0]
    else:
        self.reaction_priority_player_id = first_responder_id
    self.reaction_pass_count = 1 if len(self.spell_stack) > base_stack_size else 0
    self.reaction_base_stack_size = base_stack_size
    self.reaction_resume_phase = resume_phase
    self.reaction_continuation = continuation
    self.phase = PHASE_REACTION
    title = self.get_reaction_window_title(context)
    description = self.get_reaction_window_description(context)
    current_player = self.get_player_by_id(self.reaction_priority_player_id)
    self.log(f"{title}: {description}")
    self.log(f"{current_player.name} ist als Naechstes mit Reagieren oder Passen am Zug.")
    if self.statistics is not None:
        self.statistics.register_reaction_chain_started()
    if not is_general_window and not has_legal_reaction_for_player(self, current_player, context):
        self.pass_reaction()


def pass_reaction(self) -> None:
    if self.phase != PHASE_REACTION or self.reaction_priority_player_id is None:
        return
    player = self.get_player_by_id(self.reaction_priority_player_id)
    context = self.reaction_context
    if is_combat_priority_window(self, context) and self.reaction_sequence_player_ids:
        self.log(f"{player.name} passt.")
        if self.statistics is not None:
            self.statistics.register_reaction_pass()
        self.advance_combat_window_priority()
        return
    self.reaction_pass_count += 1
    self.log(f"{player.name} passt.")
    if self.statistics is not None:
        self.statistics.register_reaction_pass()
    if self.reaction_pass_count >= 2:
        self.finish_reaction_window()
        return
    self.reaction_priority_player_id = 1 - player.player_id
    if context is None:
        return
    next_player = self.get_player_by_id(self.reaction_priority_player_id)
    if not has_legal_reaction_for_player(self, next_player, context):
        self.pass_reaction()


def finish_reaction_window(self) -> None:
    base_size = self.reaction_base_stack_size
    continuation = self.reaction_continuation
    resume_phase = self.reaction_resume_phase
    chain_length = max(0, len(self.spell_stack) - base_size)
    if self.statistics is not None:
        self.statistics.register_reaction_chain_length(chain_length)
    self.reaction_context = None
    self.reaction_priority_player_id = None
    self.reaction_pass_count = 0
    self.reaction_sequence_player_ids = []
    self.reaction_sequence_index = 0
    self.reaction_base_stack_size = 0
    self.reaction_resume_phase = PHASE_MAIN_1
    self.reaction_continuation = None
    self.phase = resume_phase
    self.resolve_spell_stack_to(base_size, continuation)


def resolve_spell_stack_to(self, base_size: int, continuation: Optional[Callable[[], None]] = None) -> None:
    self.resolving_stack = True
    self.pending_stack_resolution_base_size = base_size
    self.pending_stack_resolution_continuation = continuation
    while len(self.spell_stack) > base_size and self.phase != PHASE_GAME_OVER:
        item = self.spell_stack.pop()
        paused = self.resolve_stack_item(item)
        item.controller.discard_pile.append(item.source_card)
        if paused:
            return
    self.resolving_stack = False
    self.pending_stack_resolution_base_size = 0
    self.pending_stack_resolution_continuation = None
    if continuation is not None:
        continuation()


def resume_stack_resolution(self) -> None:
    continuation = self.pending_stack_resolution_continuation
    base_size = self.pending_stack_resolution_base_size
    self.resolve_spell_stack_to(base_size, continuation)


def resolve_stack_item(self, item: StackItem) -> bool:
    effect = item.effect
    if effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
        item.controller.creature_cost_reduction_this_turn += item.amount
        self.log(f"{item.source_card.template.name} reduziert Kreaturenkosten in diesem Zug um {item.amount}.")
        return False
    if effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
        creature = resolve_target_creature(self, item.targets[0] if item.targets else None)
        if creature is None or not is_valid_turn_attack_bonus_target(self, item.controller, creature, item.context):
            self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
            return False
        creature.temporary_combat_aw_bonus += item.source_card.template.combat_aw_bonus
        creature.temporary_combat_sw_bonus += item.source_card.template.combat_sw_bonus
        parts = []
        if item.source_card.template.combat_aw_bonus:
            parts.append(f"+{item.source_card.template.combat_aw_bonus} AW")
        if item.source_card.template.combat_sw_bonus:
            parts.append(f"+{item.source_card.template.combat_sw_bonus} SW")
        self.log(f"{creature.name} erhaelt fuer diesen Kampf {' und '.join(parts)}.")
        return False
    if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
        attackers = get_current_attacker_creatures(self, item.controller, item.context)
        if not attackers:
            self.log(f"{item.source_card.template.name} verpufft, es gibt keine eigenen Angreifer mehr.")
            return False
        for creature in attackers:
            creature.temporary_combat_aw_bonus += item.source_card.template.combat_aw_bonus
            creature.temporary_combat_sw_bonus += item.source_card.template.combat_sw_bonus
        parts = []
        if item.source_card.template.combat_aw_bonus:
            parts.append(f"+{item.source_card.template.combat_aw_bonus} AW")
        if item.source_card.template.combat_sw_bonus:
            parts.append(f"+{item.source_card.template.combat_sw_bonus} SW")
        self.log(f"Eigene Angreifer erhalten fuer diesen Kampf {' und '.join(parts)}.")
        return False
    if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        creature = resolve_target_creature(self, item.targets[0] if item.targets else None)
        if creature is None:
            self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
            return False
        if item.selected_keyword_ability is not None:
            creature.temporary_abilities.add(item.selected_keyword_ability)
        return False
    if effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
        returned_names: list[str] = []
        seen_card_ids: set[int] = set()
        for target in item.targets[: item.amount]:
            card = resolve_target_discard_card_for_controller(self, item.controller, target)
            if card is None or card.instance_id in seen_card_ids:
                continue
            seen_card_ids.add(card.instance_id)
            item.controller.discard_pile = [
                existing for existing in item.controller.discard_pile if existing.instance_id != card.instance_id
            ]
            item.controller.hand.append(card)
            returned_names.append(card.template.name)
            self.log(f"{item.controller.name} nimmt {card.template.name} aus dem Ablagestapel auf die Hand.")
        if not returned_names:
            self.log(f"{item.source_card.template.name} verpufft, die Ziele sind ungueltig.")
        return False
    if effect == SpellEffect.DISCARD_HAND_AND_DRAW:
        discarded_count = len(item.controller.hand)
        if item.controller.hand:
            item.controller.discard_pile.extend(item.controller.hand)
            item.controller.hand = []
        self.log(f"{item.controller.name} legt seine Hand ab und zieht {item.draw_count} Karten.")
        for _ in range(item.draw_count):
            drawn = self.draw_card_for_player(item.controller, item.source_card.template.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return False
        return False
    if effect == SpellEffect.RETURN_CREATURES_TO_HAND:
        returned_names: list[str] = []
        seen_creature_ids: set[int] = set()
        for target in item.targets[: item.amount]:
            creature = resolve_target_creature(self, target)
            if creature is None or creature.unit_id in seen_creature_ids:
                continue
            owner = self.get_unit_owner(creature.unit_id)
            if owner is None:
                continue
            seen_creature_ids.add(creature.unit_id)
            return_creature_to_hand(self, owner, creature)
            returned_names.append(f"{creature.name} ({owner.name})")
        if returned_names:
            self.log(f"{item.source_card.template.name} nimmt auf die Haende ihrer Besitzer zurueck: {', '.join(returned_names)}.")
        return False
    if effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
        returned_names: list[str] = []
        for target in item.targets:
            creature = resolve_target_creature(self, target)
            if creature is None:
                continue
            owner = self.get_unit_owner(creature.unit_id)
            if owner is None:
                continue
            return_creature_to_hand(self, owner, creature)
            returned_names.append(creature.name)
        if returned_names:
            self.log(f"{item.source_card.template.name} nimmt auf die Hand zurueck: {', '.join(returned_names)}.")
        return False
    if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
        creature = resolve_target_creature(self, item.targets[0] if item.targets else None)
        if creature is None or not is_valid_damage_spell_target(self, item.controller, creature, item.context):
            self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
            return False
        return resolve_spell_damage_to_creature(self, item, creature, item.amount)
    if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
        target = item.targets[0] if item.targets else None
        if target is None:
            self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
            return False
        if target.target_type == "creature":
            creature = resolve_target_creature(self, target)
            if creature is None:
                self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
                return False
            return resolve_spell_damage_to_creature(self, item, creature, item.amount)
        player = self.get_player_by_id(target.player_id or 0)
        deal_spell_damage_to_player(self, item.controller.player_id, player, item.amount, item.source_card.template.name)
        return False
    if effect == SpellEffect.DEAL_DAMAGE_TO_ALL_ENEMY_CREATURES:
        enemy = self.players[1 - item.controller.player_id]
        for creature in list(enemy.battlefield):
            creature.current_hp -= item.amount
            self.queue_creature_damage_event("blocker", item.amount, item.source_card.template.element)
            if self.statistics is not None:
                self.statistics.register_spell_damage(item.controller.player_id, item.amount)
        any_pause = cleanup_destroyed_units_for_spells(self)
        return any_pause
    if effect == SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES:
        return resolve_global_damage(self, item, item.amount, include_players=False)
    if effect == SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES_AND_PLAYERS:
        return resolve_global_damage(self, item, item.amount, include_players=True)
    if effect == SpellEffect.SACRIFICE_FOR_DAMAGE:
        amount = item.sacrificed_creature_power
        target = item.targets[0] if item.targets else None
        if target is None:
            self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
            return False
        if target.target_type == "creature":
            creature = resolve_target_creature(self, target)
            if creature is None:
                self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
                return False
            return resolve_spell_damage_to_creature(self, item, creature, amount)
        player = self.get_player_by_id(target.player_id or 0)
        deal_spell_damage_to_player(self, item.controller.player_id, player, amount, item.source_card.template.name)
        return False
    if effect == SpellEffect.DRAW_AND_SELF_DAMAGE:
        for _ in range(item.draw_count):
            drawn = self.draw_card_for_player(item.controller, item.source_card.template.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return False
        item.controller.life -= item.amount
        self.queue_player_damage_event(item.controller.player_id, item.amount, item.source_card.template.element)
        if self.statistics is not None:
            self.statistics.register_spell_self_damage(item.controller.player_id, item.amount)
        self.check_for_game_over()
        return False
    if effect == SpellEffect.DRAW_CARDS:
        self.log(f"{item.controller.name} zieht {item.draw_count} Karten.")
        for _ in range(item.draw_count):
            drawn = self.draw_card_for_player(item.controller, item.source_card.template.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return False
        return False
    if effect == SpellEffect.DECK_TO_TAPPED_RESOURCES:
        added = 0
        for _ in range(item.amount):
            if not item.controller.deck:
                self.lose_game_from_empty_deck(item.controller, item.source_card.template.name)
                return False
            top_card = item.controller.deck.pop()
            item.controller.resources.append(
                ResourceCard(template=top_card.template, resource_id=top_card.instance_id, tapped=True)
            )
            added += 1
        if added == 1:
            self.log(f"{item.controller.name} legt die oberste Karte seines Decks getappt als Ressource ins Spiel.")
        elif added > 1:
            self.log(f"{item.controller.name} legt {added} Karten seines Decks getappt als Ressourcen ins Spiel.")
        return False
    return False


def resolve_spell_damage_to_creature(self, item: StackItem, creature, amount: int) -> bool:
    creature.current_hp -= amount
    self.queue_creature_damage_event("blocker", amount, item.source_card.template.element)
    if self.statistics is not None:
        self.statistics.register_spell_damage(item.controller.player_id, amount)
    return cleanup_destroyed_units_for_spells(self)


def resolve_global_damage(self, item: StackItem, amount: int, *, include_players: bool) -> bool:
    if include_players:
        self.log(f"{item.source_card.template.name} fuegt allen Kreaturen und Spielern {amount} Schaden zu.")
    else:
        self.log(f"{item.source_card.template.name} fuegt allen Kreaturen {amount} Schaden zu.")
    if include_players:
        for player in self.players:
            player.life -= amount
            self.queue_player_damage_event(player.player_id, amount, item.source_card.template.element)
            if self.statistics is not None:
                if player.player_id == item.controller.player_id:
                    self.statistics.register_spell_self_damage(item.controller.player_id, amount)
                else:
                    self.statistics.register_player_damage(item.controller.player_id, amount)
    for player in self.players:
        for creature in list(player.battlefield):
            creature.current_hp -= amount
            self.queue_creature_damage_event("blocker", amount, item.source_card.template.element)
            if self.statistics is not None:
                self.statistics.register_spell_damage(item.controller.player_id, amount)
    cleanup_destroyed_units_for_spells(self)
    self.check_for_game_over()
    return False


def cleanup_destroyed_units_for_spells(self) -> bool:
    for player in self.players:
        destroyed = [creature for creature in list(player.battlefield) if self.is_creature_destroyed(creature)]
        for creature in destroyed:
            self.destroy_creature_immediately(player, creature, "Zauberschaden")
    return False


def should_return_creature_from_combat_death(self, owner, creature) -> bool:
    if not creature.has_ability(Ability.HASTE):
        return False
    return any(
        other.current_hp > 0
        and other.unit_id != creature.unit_id
        and getattr(other, "return_other_own_haste_on_combat_death", False)
        for other in owner.battlefield
    )


def destroy_creature_immediately(self, owner, creature, source_name: str, *, died_in_combat: bool = False) -> ReactionContext:
    remove_creature_from_combat(self, creature.unit_id)
    return_to_hand_after_death = died_in_combat and should_return_creature_from_combat_death(self, owner, creature)
    if creature in owner.battlefield:
        owner.battlefield.remove(creature)
    self.creatures_died_this_turn += 1
    setattr(creature, "owner_id", owner.player_id)
    destroyed_card = CardInstance(self.make_instance_id(), self.templates[creature.template_id])
    owner.discard_pile.append(destroyed_card)
    self.log(f"{source_name} zerstoert {creature.name}. {creature.name} geht auf den Ablagestapel.")
    draw_on_death = getattr(creature, "draw_on_death", 0)
    if draw_on_death > 0:
        for _ in range(draw_on_death):
            drawn = self.draw_card_for_player(owner, creature.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                break
        if self.phase != PHASE_GAME_OVER:
            self.log(f"{creature.name} laesst {owner.name} beim Sterben {draw_on_death} Karte(n) ziehen.")
    if return_to_hand_after_death:
        if destroyed_card in owner.discard_pile:
            owner.discard_pile.remove(destroyed_card)
        owner.hand.append(destroyed_card)
        self.log(f"Orkangeist nimmt {creature.name} auf die Hand zurueck.")
    if self.statistics is not None:
        self.statistics.player_stats[owner.player_id].creatures_destroyed += 1
    return ReactionContext(
        trigger=ReactionTrigger.OWN_CREATURE_DESTROYED,
        active_player=self.active_player,
        source_player=owner,
        source_creature=creature,
        damage_amount=0,
    )


def build_spell_reaction_context(self, controller, card: CardInstance, targets: list[SpellTargetRef]) -> ReactionContext:
    for target in targets:
        target_creature = resolve_target_creature(self, target) if target.target_type == "creature" else None
        if target_creature is None:
            continue
        owner = self.get_unit_owner(target_creature.unit_id)
        if owner is not None and owner.player_id != controller.player_id:
            setattr(target_creature, "owner_id", owner.player_id)
            return ReactionContext(
                trigger=ReactionTrigger.OWN_CREATURE_TARGETED,
                active_player=self.active_player,
                source_player=controller,
                source_card=card,
                target_creature=target_creature,
            )
    return ReactionContext(
        trigger=ReactionTrigger.SPELL_CAST,
        active_player=self.active_player,
        source_player=controller,
        source_card=card,
    )


def resolve_target_creature(self, target: SpellTargetRef | None):
    if target is None or target.target_type != "creature":
        return None
    return self.get_unit_by_id(target.creature_id or -1)


def resolve_target_discard_card(self, target: SpellTargetRef | None):
    if target is None or target.target_type != "discard_card" or target.card_instance_id is None:
        return None
    for player in self.players:
        card = next((existing for existing in player.discard_pile if existing.instance_id == target.card_instance_id), None)
        if card is not None:
            return card
    return None


def resolve_target_discard_card_for_controller(self, controller, target: SpellTargetRef | None):
    if target is None or target.target_type != "discard_card" or target.card_instance_id is None:
        return None
    return next((existing for existing in controller.discard_pile if existing.instance_id == target.card_instance_id), None)


def get_valid_discard_creature_target_refs(self, player) -> list[SpellTargetRef]:
    return [
        SpellTargetRef("discard_card", card_instance_id=card.instance_id)
        for card in player.discard_pile
        if card.template.card_type == CardType.CREATURE
    ]


def can_target_creature_with_explicit_spell(self, creature) -> bool:
    return creature is not None and not creature.has_ability(Ability.MAGIC_RESISTANT)


def count_valid_return_to_hand_targets(self) -> int:
    return sum(
        1
        for player in self.players
        for creature in player.battlefield
        if can_target_creature_with_explicit_spell(self, creature)
    )


def get_current_attacker_creatures(self, controller, context: ReactionContext | None = None) -> list:
    active_context = context or self.reaction_context
    if active_context is None or active_context.trigger != ReactionTrigger.COMBAT_START:
        return []
    return [
        creature
        for creature in controller.battlefield
        if creature.unit_id in self.block_assignments
    ]


def has_valid_attacker_combat_bonus_targets(self, controller, context: ReactionContext | None = None) -> bool:
    return bool(get_current_attacker_creatures(self, controller, context))


def get_valid_turn_attack_bonus_targets(self, controller, context: ReactionContext | None = None) -> list:
    active_context = context or self.reaction_context
    if active_context is None or active_context.trigger != ReactionTrigger.COMBAT_START:
        return []
    return [
        creature
        for creature in controller.battlefield
        if creature.unit_id in self.block_assignments
        and not self.is_creature_destroyed(creature)
        and can_target_creature_with_explicit_spell(self, creature)
    ]


def has_valid_turn_attack_bonus_targets(self, controller, context: ReactionContext | None = None) -> bool:
    return bool(get_valid_turn_attack_bonus_targets(self, controller, context))


def is_valid_turn_attack_bonus_target(self, controller, creature, context: ReactionContext | None = None) -> bool:
    return any(existing.unit_id == creature.unit_id for existing in get_valid_turn_attack_bonus_targets(self, controller, context))


def get_valid_damage_spell_targets(self, controller, context: ReactionContext | None = None) -> list:
    active_context = context or self.reaction_context
    if active_context is None or active_context.trigger not in {ReactionTrigger.COMBAT_START, ReactionTrigger.COMBAT_END}:
        return []
    return [
        creature
        for player in self.players
        for creature in player.battlefield
        if not self.is_creature_destroyed(creature)
        and can_target_creature_with_explicit_spell(self, creature)
    ]


def is_valid_damage_spell_target(self, controller, creature, context: ReactionContext | None = None) -> bool:
    return any(existing.unit_id == creature.unit_id for existing in get_valid_damage_spell_targets(self, controller, context))


def deal_spell_damage_to_player(self, controller_id: int, player, amount: int, source_name: str) -> None:
    player.life -= amount
    self.queue_player_damage_event(player.player_id, amount, Element.FIRE)
    if self.statistics is not None:
        self.statistics.register_spell_damage(controller_id, amount)
    self.log(f"{source_name} fuegt {player.name} {amount} Schaden zu.")
    self.check_for_game_over()


def is_target_controlled_by(self, target: SpellTargetRef, player_id: int) -> bool:
    creature = resolve_target_creature(self, target)
    if creature is None:
        return False
    owner = self.get_unit_owner(creature.unit_id)
    return owner is not None and owner.player_id == player_id


def return_creature_to_hand(self, owner, creature) -> None:
    remove_creature_from_combat(self, creature.unit_id)
    if creature in owner.battlefield:
        owner.battlefield.remove(creature)
    owner.hand.append(CardInstance(self.make_instance_id(), self.templates[creature.template_id]))


def get_reaction_creature_owner_id(self, creature, fallback_player_id: int | None = None) -> int | None:
    if creature is None:
        return fallback_player_id
    owner = self.get_unit_owner(getattr(creature, "unit_id", -1))
    if owner is not None:
        return owner.player_id
    owner_id = getattr(creature, "owner_id", None)
    if owner_id is not None:
        return owner_id
    return fallback_player_id


def spell_cast_needs_interaction(self, card: CardInstance) -> bool:
    if card.template.recycle_cost > 0:
        return True
    if card.template.sacrifice_own_creature_on_cast:
        return True
    if card.template.spell_effect in {
        SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN,
        SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN,
        SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND,
        SpellEffect.RETURN_CREATURES_TO_HAND,
        SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND,
    }:
        return True
    return card.template.target_mode != SpellTargetMode.NONE


def is_valid_verwehung_target(self, controller, creature) -> bool:
    return self.get_unit_owner(creature.unit_id) is not None and can_target_creature_with_explicit_spell(self, creature)


def has_valid_verwehung_target(self, controller) -> bool:
    return any(is_valid_verwehung_target(self, controller, creature) for creature in controller.battlefield)


def is_valid_jagdwind_target(self, controller, creature, context: ReactionContext | None = None) -> bool:
    return creature in get_current_attacker_creatures(self, controller, context)


def has_valid_jagdwind_target(self, controller, context: ReactionContext | None = None) -> bool:
    return any(is_valid_jagdwind_target(self, controller, creature, context) for creature in controller.battlefield)


def get_valid_sturmjagd_attackers(self, controller, context: ReactionContext | None = None) -> list:
    return get_current_attacker_creatures(self, controller, context)


def has_valid_sturmjagd_targets(self, controller, context: ReactionContext | None = None) -> bool:
    return bool(get_valid_sturmjagd_attackers(self, controller, context))


def get_player_combat_dice(self, player_id: int) -> tuple[str | None, list]:
    battle = self.pending_dice_battle
    if battle is None:
        return None, []
    if battle.attacker_owner == player_id:
        return "attacker", battle.attacker_rolls
    if battle.blocker_owner == player_id:
        return "blocker", battle.blocker_rolls
    return None, []


def has_valid_combat_die_target(self, controller) -> bool:
    _role, dice = get_player_combat_dice(self, controller.player_id)
    return bool(dice)


def remove_creature_from_combat(self, creature_id: int) -> None:
    was_attacker = creature_id in self.block_assignments
    if was_attacker:
        self.blocked_attackers.discard(creature_id)
        self.combat_queue = [attacker_id for attacker_id in self.combat_queue if attacker_id != creature_id]
        self.block_assignments.pop(creature_id, None)
        self.pending_direct_attacks = [
            attack for attack in self.pending_direct_attacks if attack.attacker_id != creature_id
        ]
        if self.pending_direct_attack is not None and self.pending_direct_attack.attacker_id == creature_id:
            self.pending_direct_attack = None
    for attacker_id, blocker_id in list(self.block_assignments.items()):
        if blocker_id == creature_id:
            self.block_assignments[attacker_id] = None
    battle = self.pending_dice_battle
    if battle is not None and creature_id in {battle.attacker_id, battle.blocker_id}:
        battle.resolution_complete = True

