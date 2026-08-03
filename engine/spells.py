from __future__ import annotations

from typing import Callable, Optional

from core.models import (
    Ability,
    CardInstance,
    CardType,
    Element,
    PendingSpellCast,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_GAME_OVER,
    PHASE_REACTION,
    PHASE_SPELL_TARGETING,
    PHASE_SUMMONING,
    ReactionContext,
    ReactionTrigger,
    SpellEffect,
    SpellTargetMode,
    SpellTargetRef,
    StackItem,
)


GENERAL_SPELL_WINDOW_TRIGGERS = {
    ReactionTrigger.AFTER_DICE_REVEALED,
    ReactionTrigger.AFTER_DICE_COMPARISON,
    ReactionTrigger.BEFORE_DIRECT_ATTACK_DAMAGE,
}

REACTION_WINDOW_PROFILES = {
    ReactionTrigger.SPELL_CAST: {
        "title": "Reaktionsfenster",
        "description": "Ein Zauber wurde gespielt. Passende Zauber können jetzt darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": False,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.AFTER_DICE_REVEALED: {
        "title": "Allgemeines Zauberfenster",
        "description": "Vor dem ersten Wuerfelvergleich können Zauber gespielt werden.",
        "is_general_window": True,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": True,
    },
    ReactionTrigger.AFTER_DICE_COMPARISON: {
        "title": "Allgemeines Zauberfenster",
        "description": "Nach dem Wuerfelvergleich können weitere Zauber gespielt werden.",
        "is_general_window": True,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": True,
    },
    ReactionTrigger.BEFORE_DIRECT_ATTACK_DAMAGE: {
        "title": "Allgemeines Zauberfenster",
        "description": "Vor dem direkten Schaden des ungeblockten Angreifers können Zauber gespielt werden.",
        "is_general_window": True,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.OWN_CREATURE_DESTROYED: {
        "title": "Reaktionsfenster",
        "description": "Eine eigene Kreatur wurde zerstoert. Passende Zauber können darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.BLOCKER_DECLARED: {
        "title": "Reaktionsfenster",
        "description": "Ein Blocker wurde deklariert. Passende Zauber können darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": True,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.OWN_CREATURE_TARGETED: {
        "title": "Reaktionsfenster",
        "description": "Eine eigene Kreatur wurde als Ziel gewaehlt. Passende Zauber können darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": False,
        "shows_stack_preview": True,
        "allows_die_targets": False,
    },
    ReactionTrigger.OWN_CREATURE_DAMAGED_IN_DICE_COMPARISON: {
        "title": "Reaktionsfenster",
        "description": "Eine eigene Kreatur hat im Wuerfelvergleich Schaden erhalten. Passende Zauber können darauf reagieren.",
        "is_general_window": False,
        "is_combat_window": True,
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


def reaction_window_allows_die_targets(self, context: ReactionContext | None = None) -> bool:
    return bool(get_reaction_window_profile(self, context).get("allows_die_targets", False))


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
    if card.template.card_type == CardType.RITUAL:
        return (
            player == self.active_player
            and self.phase == PHASE_SUMMONING
            and self.pending_spell_cast is None
            and not self.resolving_stack
            and (not card.template.sacrifice_own_creature_on_cast or bool(player.battlefield))
        )
    if card.template.card_type == CardType.SPELL:
        if (
            card.template.reaction_trigger is None
            and
            player == self.active_player
            and self.phase == PHASE_SUMMONING
            and self.pending_spell_cast is None
            and not self.resolving_stack
        ):
            return True
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
    return is_reaction_spell_legal_in_context(self, player, card, self.reaction_context)


def is_reaction_spell_legal_in_context(self, player, card: CardInstance, context: ReactionContext) -> bool:
    trigger = card.template.reaction_trigger
    if trigger is None:
        return True
    if trigger == ReactionTrigger.AFTER_DICE_REVEALED:
        return context.trigger == trigger and get_context_die_for_player(self, context, player.player_id) is not None
    if trigger == ReactionTrigger.OWN_CREATURE_DESTROYED:
        owner_id = get_reaction_creature_owner_id(
            self,
            context.source_creature,
            fallback_player_id=getattr(context.source_player, "player_id", None),
        )
        return context.trigger == trigger and context.source_creature is not None and owner_id == player.player_id
    if trigger == ReactionTrigger.BLOCKER_DECLARED:
        owner_id = get_reaction_creature_owner_id(self, context.target_creature)
        return (
            context.trigger == trigger
            and context.target_creature is not None
            and owner_id is not None
            and owner_id != player.player_id
        )
    if trigger == ReactionTrigger.OWN_CREATURE_TARGETED:
        owner_id = get_reaction_creature_owner_id(self, context.target_creature)
        return (
            context.trigger == trigger
            and context.target_creature is not None
            and owner_id == player.player_id
            and context.source_player is not None
            and context.source_player.player_id != player.player_id
        )
    if trigger == ReactionTrigger.OWN_CREATURE_DAMAGED_IN_DICE_COMPARISON:
        owner_id = get_reaction_creature_owner_id(
            self,
            context.source_creature,
            fallback_player_id=getattr(context.source_player, "player_id", None),
        )
        return context.trigger == trigger and context.source_creature is not None and owner_id == player.player_id
    return context.trigger == ReactionTrigger.SPELL_CAST


def has_any_legal_reaction(self, context: ReactionContext) -> bool:
    for player in self.players:
        for card in player.hand:
            if card.template.card_type != CardType.SPELL:
                continue
            if not player.can_pay(card.template.cost):
                continue
            if is_reaction_spell_legal_in_context(self, player, card, context):
                return True
    return False


def begin_spell_cast(self, card_id: int) -> bool:
    if not self.active_player.is_human or self.phase != PHASE_SUMMONING:
        return False
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_id), None)
    if card is None:
        self.log("Diese Karte ist nicht mehr auf der Hand.")
        return False
    if not self.can_play_card(self.active_player, card):
        self.log("Diese Karte kann gerade nicht gespielt werden.")
        return False
    return self.begin_spell_cast_from_card(card, PHASE_SUMMONING)


def begin_spell_from_hand(self, card_id: int) -> bool:
    if self.phase != PHASE_REACTION or self.reaction_priority_player_id != self.human_player.player_id:
        return False
    card = next((existing for existing in self.human_player.hand if existing.instance_id == card_id), None)
    if card is None or not self.can_react_with_card(self.human_player, card):
        self.log("Dieser Zauber ist in diesem Fenster nicht legal.")
        return False
    return self.begin_spell_cast_from_card(card, PHASE_REACTION)


def begin_spell_cast_from_card(self, card: CardInstance, origin_phase: str) -> bool:
    if not spell_cast_needs_interaction(self, card):
        return self.commit_spell_cast(card, origin_phase, [])
    self.pending_spell_cast = PendingSpellCast(
        card_instance_id=card.instance_id,
        controller_id=self.active_player.player_id if origin_phase == PHASE_SUMMONING else self.reaction_priority_player_id,
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
    if card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
        if has_valid_ausweichen_target(self, controller):
            return f"Waehle eine eigene kaempfende Kreatur fuer {card.template.name}."
        return f"Bestaetige {card.template.name}. Kein gueltiges Ziel vorhanden."
    if card.template.spell_effect in {
        SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE,
        SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE,
    }:
        if has_valid_combat_die_target(self, controller):
            return f"Waehle einen unbenutzten eigenen Kampfwuerfel fuer {card.template.name}."
        return f"Bestaetige {card.template.name}. Kein gueltiger Wuerfel vorhanden."
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
        SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND,
    }:
        return
    if card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        if target.target_type != "creature":
            self.log("Dieser Zauber benoetigt eine Kreatur als Ziel.")
            return
        pending.selected_targets = [target]
        pending.selected_keyword_ability = None
        self.log(self.describe_pending_spell_requirements())
        return
    if card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
        if target.target_type != "creature":
            self.log("Dieser Zauber benoetigt eine Kreatur als Ziel.")
            return
        creature = self.get_unit_by_id(target.creature_id or -1)
        if creature is None or not is_valid_ausweichen_target(self, controller, creature):
            self.log("Diese Kreatur ist fuer Ausweichen nicht gueltig.")
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
        pending.selected_targets = [target]
    elif card.template.target_mode == SpellTargetMode.CREATURE_OR_PLAYER:
        pending.selected_targets = [target]
    self.log(self.describe_pending_spell_requirements())


def select_spell_combat_die(self, visible_index: int) -> None:
    pending = self.pending_spell_cast
    if pending is None or self.phase != PHASE_SPELL_TARGETING:
        return
    card = self.get_card_from_pending_spell(pending)
    if card is None or card.template.spell_effect not in {
        SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE,
        SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE,
    }:
        return
    controller = self.get_player_by_id(pending.controller_id)
    target = get_spell_combat_die_target(self, controller.player_id, visible_index)
    if target is None:
        self.log("Dieser Wuerfel ist nicht gueltig.")
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
    if card.template.spell_effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
        controller = self.get_player_by_id(pending.controller_id)
        own_required = 1 if controller.battlefield else 0
        enemy_required = 1 if self.players[1 - controller.player_id].battlefield else 0
        own_selected = sum(1 for target in pending.selected_targets if is_target_controlled_by(self, target, controller.player_id))
        enemy_selected = len(pending.selected_targets) - own_selected
        return own_selected >= own_required and enemy_selected >= enemy_required
    if card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
        return len(pending.selected_targets) == 1 or not has_valid_ausweichen_target(self, self.get_player_by_id(pending.controller_id))
    if card.template.spell_effect in {
        SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE,
        SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE,
    }:
        return len(pending.selected_targets) == 1 or not has_valid_combat_die_target(self, self.get_player_by_id(pending.controller_id))
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
    controller = self.active_player if origin_phase == PHASE_SUMMONING else self.get_player_by_id(self.reaction_priority_player_id)
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
        sacrificed_power = creature.aw
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
    if self.statistics is not None:
        if card.template.card_type == CardType.RITUAL:
            self.statistics.register_ritual_played(controller.player_id)
        else:
            self.statistics.register_spell_played(controller.player_id)
    if origin_phase == PHASE_REACTION:
        self.reaction_pass_count = 0
        self.reaction_priority_player_id = 1 - controller.player_id
        self.phase = PHASE_REACTION
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
    if self.phase == PHASE_GAME_OVER:
        return
    if self.active_player.is_human and self.phase == PHASE_SUMMONING:
        self.auto_advance_human_summoning_phase_if_needed()


def begin_reaction_window(
    self,
    context: ReactionContext,
    first_responder_id: int,
    base_stack_size: int,
    resume_phase: str,
    continuation: Optional[Callable[[], None]] = None,
) -> None:
    if len(self.spell_stack) <= base_stack_size and not has_any_legal_reaction(self, context):
        self.phase = resume_phase
        if continuation is not None:
            continuation()
        return
    self.reaction_context = context
    self.reaction_priority_player_id = first_responder_id
    self.reaction_pass_count = 1 if len(self.spell_stack) > base_stack_size else 0
    self.reaction_base_stack_size = base_stack_size
    self.reaction_resume_phase = resume_phase
    self.reaction_continuation = continuation
    self.phase = PHASE_REACTION
    if self.statistics is not None:
        self.statistics.register_reaction_chain_started()


def pass_reaction(self) -> None:
    if self.phase != PHASE_REACTION or self.reaction_priority_player_id is None:
        return
    player = self.get_player_by_id(self.reaction_priority_player_id)
    self.reaction_pass_count += 1
    self.log(f"{player.name} passt.")
    if self.statistics is not None:
        self.statistics.register_reaction_pass()
    if self.reaction_pass_count >= 2:
        self.finish_reaction_window()
        return
    self.reaction_priority_player_id = 1 - player.player_id


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
    self.reaction_base_stack_size = 0
    self.reaction_resume_phase = PHASE_SUMMONING
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
        return False
    if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        creature = resolve_target_creature(self, item.targets[0] if item.targets else None)
        if creature is None:
            self.log(f"{item.source_card.template.name} verpufft, das Ziel ist ungueltig.")
            return False
        if item.selected_keyword_ability is not None:
            creature.temporary_abilities.add(item.selected_keyword_ability)
        return False
    if effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
        for _ in range(item.draw_count):
            drawn = self.draw_card_for_player(item.controller, item.source_card.template.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return False
        return self.begin_forced_discard(item.controller, 1, item.source_card.template.name, PHASE_SUMMONING)
    if effect == SpellEffect.BUFF_ATTACKERS_DICE_THIS_TURN:
        item.controller.attackers_die_bonus_this_turn += item.amount
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
    if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
        creature = resolve_target_creature(self, item.targets[0] if item.targets else None)
        if creature is None:
            return False
        owner = self.get_unit_owner(creature.unit_id)
        if owner is None or owner.player_id != item.controller.player_id:
            return False
        return_creature_to_hand(self, owner, creature)
        self.log(f"{item.source_card.template.name} nimmt {creature.name} auf die Hand zurueck.")
        return False
    if effect == SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE:
        die = resolve_target_die(self, item.targets[0] if item.targets else None, item.controller.player_id)
        if die is None:
            return False
        die.base_roll = self.rng.randint(1, 20)
        return False
    if effect == SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE:
        die = resolve_target_die(self, item.targets[0] if item.targets else None, item.controller.player_id)
        if die is None:
            return False
        die.add_bonus(item.source_card.template.name, item.amount)
        return False
    if effect == SpellEffect.DOUBLE_UNBLOCKED_ATTACK_DAMAGE:
        if self.pending_direct_attack is None:
            return False
        if self.pending_direct_attack.attacker_owner != item.controller.player_id:
            return False
        self.pending_direct_attack.damage_multiplier *= 2
        return False
    if effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
        draw_count = self.creatures_died_this_turn * item.amount
        for _ in range(draw_count):
            drawn = self.draw_card_for_player(item.controller, item.source_card.template.name)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return False
        return False
    if effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
        creature = resolve_target_creature(self, item.targets[0] if item.targets else None)
        if creature is None:
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
        if self.statistics is not None:
            self.statistics.register_flammenwelle_resolution(item.controller.player_id)
        return any_pause
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
            if drawn is not None and self.statistics is not None:
                self.statistics.register_verbotene_glut_draw(item.controller.player_id)
            if drawn is None and self.phase == PHASE_GAME_OVER:
                return False
        item.controller.life -= item.amount
        self.queue_player_damage_event(item.controller.player_id, item.amount, item.source_card.template.element)
        if self.statistics is not None:
            self.statistics.register_spell_self_damage(item.controller.player_id, item.amount)
        self.check_for_game_over()
        return False
    if effect == SpellEffect.MODIFY_DIE_RESULT:
        if item.context is None:
            return False
        die = get_context_die_for_player(self, item.context, item.controller.player_id)
        if die is None:
            self.log(f"{item.source_card.template.name} verpufft, kein eigener Wuerfel ist mehr vorhanden.")
            return False
        other_die = item.context.blocker_die if die is item.context.attacker_die else item.context.attacker_die
        before = die.total
        die.add_bonus(item.source_card.template.name, item.amount)
        if self.statistics is not None and other_die is not None and before <= other_die.total < die.total:
            self.statistics.register_hitzeschub_play(item.controller.player_id)
        return False
    if effect == SpellEffect.DAMAGE_AFTER_OWN_CREATURE_DESTROYED:
        return self.resolve_stack_item(
            StackItem(
                item.source_card,
                item.controller,
                item.targets,
                SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER,
                item.context,
                amount=item.amount,
            )
        )
    if effect == SpellEffect.DAMAGE_DECLARED_BLOCKER:
        if item.context is None or item.context.target_creature is None:
            return False
        blocker = self.get_unit_by_id(item.context.target_creature.unit_id)
        if blocker is None:
            self.log(f"{item.source_card.template.name} verpufft, der Blocker ist nicht mehr im Spiel.")
            return False
        return resolve_spell_damage_to_creature(self, item, blocker, item.amount, blocker_declared=True)
    if effect == SpellEffect.DAMAGE_OPPONENT_WHEN_TARGETED:
        if item.context is None or item.context.source_player is None:
            return False
        deal_spell_damage_to_player(self, item.controller.player_id, item.context.source_player, item.amount, item.source_card.template.name)
        if self.statistics is not None:
            self.statistics.register_gegenfeuer_damage(item.controller.player_id, item.amount)
        return False
    if effect == SpellEffect.RETALIATE_DICE_DAMAGE:
        if item.context is None or item.context.opposing_creature is None:
            return False
        creature = self.get_unit_by_id(item.context.opposing_creature.unit_id)
        if creature is None:
            return False
        return resolve_spell_damage_to_creature(self, item, creature, item.amount, retaliate=True)
    return False


def resolve_spell_damage_to_creature(self, item: StackItem, creature, amount: int, blocker_declared: bool = False, retaliate: bool = False) -> bool:
    creature.current_hp -= amount
    self.queue_creature_damage_event("blocker", amount, item.source_card.template.element)
    if self.statistics is not None:
        self.statistics.register_spell_damage(item.controller.player_id, amount)
    paused = cleanup_destroyed_units_for_spells(self)
    if blocker_declared and self.statistics is not None:
        self.statistics.register_brandzeichen_resolution(item.controller.player_id)
    if retaliate and self.statistics is not None:
        self.statistics.register_flammenzorn_resolution(item.controller.player_id)
    return paused


def cleanup_destroyed_units_for_spells(self) -> bool:
    contexts: list[ReactionContext] = []
    for player in self.players:
        destroyed = [creature for creature in list(player.battlefield) if creature.current_hp <= 0]
        for creature in destroyed:
            contexts.append(self.destroy_creature_immediately(player, creature, "Zauberschaden"))
    if contexts:
        first = contexts[0]
        self.begin_triggered_reaction_window(
            context=first,
            first_responder_id=1 - getattr(first.source_creature, "owner_id", first.active_player.player_id),
            resume_phase=PHASE_REACTION,
            continuation=self.resume_stack_resolution,
            base_stack_size=len(self.spell_stack),
        )
        return True
    return False


def destroy_creature_immediately(self, owner, creature, source_name: str) -> ReactionContext:
    remove_creature_from_combat(self, creature.unit_id)
    if creature in owner.battlefield:
        owner.battlefield.remove(creature)
    self.creatures_died_this_turn += 1
    setattr(creature, "owner_id", owner.player_id)
    owner.discard_pile.append(CardInstance(self.make_instance_id(), self.templates[creature.template_id]))
    self.log(f"{creature.name} wird durch {source_name} zerstoert und auf den Ablagestapel gelegt.")
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


def resolve_target_die(self, target: SpellTargetRef | None, player_id: int):
    if target is None or target.target_type != "die" or self.pending_dice_battle is None:
        return None
    battle = self.pending_dice_battle
    if target.player_id != player_id or target.die_index is None:
        return None
    if target.die_role == "attacker":
        if battle.attacker_owner != player_id or target.die_index >= len(battle.attacker_dice):
            return None
        die = battle.attacker_dice[target.die_index]
    elif target.die_role == "blocker":
        if battle.blocker_owner != player_id or target.die_index >= len(battle.blocker_dice):
            return None
        die = battle.blocker_dice[target.die_index]
    else:
        return None
    if die.used:
        return None
    return die


def deal_spell_damage_to_player(self, controller_id: int, player, amount: int, source_name: str) -> None:
    player.life -= amount
    self.queue_player_damage_event(player.player_id, amount, Element.FIRE)
    if self.statistics is not None:
        self.statistics.register_spell_damage(controller_id, amount)
        if source_name == "Feuerball" and player.player_id != controller_id:
            self.statistics.register_feuerball_player_damage(controller_id, amount)
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


def get_context_die_for_player(self, context: ReactionContext, player_id: int):
    if get_reaction_creature_owner_id(self, context.attacker_creature) == player_id:
        return context.attacker_die
    if get_reaction_creature_owner_id(self, context.blocker_creature) == player_id:
        return context.blocker_die
    return None


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
        SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN,
        SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND,
        SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND,
        SpellEffect.REROLL_OWN_UNUSED_COMBAT_DIE,
        SpellEffect.ADD_TWENTY_TO_OWN_UNUSED_COMBAT_DIE,
    }:
        return True
    return card.template.target_mode != SpellTargetMode.NONE


def is_valid_ausweichen_target(self, controller, creature) -> bool:
    battle = self.pending_dice_battle
    if battle is None:
        return False
    if self.get_unit_owner(creature.unit_id) != controller:
        return False
    return creature.unit_id in {battle.attacker_id, battle.blocker_id}


def has_valid_ausweichen_target(self, controller) -> bool:
    return any(is_valid_ausweichen_target(self, controller, creature) for creature in controller.battlefield)


def get_player_combat_dice(self, player_id: int) -> tuple[str | None, list]:
    battle = self.pending_dice_battle
    if battle is None:
        return None, []
    if battle.attacker_owner == player_id:
        return "attacker", battle.attacker_dice
    if battle.blocker_owner == player_id:
        return "blocker", battle.blocker_dice
    return None, []


def has_valid_combat_die_target(self, controller) -> bool:
    _role, dice = get_player_combat_dice(self, controller.player_id)
    return any(not die.used for die in dice)


def get_spell_combat_die_target(self, player_id: int, visible_index: int) -> SpellTargetRef | None:
    role, dice = get_player_combat_dice(self, player_id)
    if role is None:
        return None
    available_indexes = [index for index, die in enumerate(dice) if not die.used]
    if visible_index < 0 or visible_index >= len(available_indexes):
        return None
    return SpellTargetRef("die", player_id=player_id, die_index=available_indexes[visible_index], die_role=role)


def remove_creature_from_combat(self, creature_id: int) -> None:
    was_attacker = creature_id in self.block_assignments
    if was_attacker:
        self.blocked_attackers.discard(creature_id)
        self.combat_queue = [attacker_id for attacker_id in self.combat_queue if attacker_id != creature_id]
        self.block_assignments.pop(creature_id, None)
    self.blocker_to_attackers.pop(creature_id, None)
    if was_attacker:
        self.current_blocker_order = [blocker_id for blocker_id in self.current_blocker_order if blocker_id != creature_id]
    self.provoke_assignments.pop(creature_id, None)
    for blocker_id, attacker_ids in list(self.blocker_to_attackers.items()):
        self.blocker_to_attackers[blocker_id] = [attacker_id for attacker_id in attacker_ids if attacker_id != creature_id]
        if not self.blocker_to_attackers[blocker_id]:
            del self.blocker_to_attackers[blocker_id]
    if self.pending_order is not None:
        self.pending_order.blocker_ids = [blocker_id for blocker_id in self.pending_order.blocker_ids if blocker_id != creature_id]
        self.pending_order.chosen_order = [blocker_id for blocker_id in self.pending_order.chosen_order if blocker_id != creature_id]
    battle = self.pending_dice_battle
    if battle is not None and creature_id in {battle.attacker_id, battle.blocker_id}:
        battle.pending_comparison = None
        battle.resolution_complete = True
