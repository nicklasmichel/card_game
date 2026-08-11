from __future__ import annotations

from datetime import datetime

from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_CREATURE_CAP, BUILDER_MAX_RESOURCES
from core.config import STARTING_LIFE
from core.game_mode import is_builder_mode
from core.models import (
    Ability,
    BattlefieldCreature,
    CardCost,
    CardInstance,
    CardTemplate,
    CardType,
    Element,
    PendingBuilderAbilityUse,
    PendingBuilderCreatureBuild,
    PHASE_BUILDER_ABILITY,
    PHASE_BUILDER_CREATURE,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PlayerState,
    ResourceCard,
)
from stats import GameStatistics


BUILDER_RESOURCE_TEMPLATE_ID = "builder_resource"
BUILDER_PREVIEW_TEMPLATE_ID = "builder_creature_preview"
BUILDER_ABILITY_PHASE_CARD_LIMIT = 1
BUILDER_SHARED_ABILITY_COUNTS = 4
BUILDER_SHARED_ABILITY_SEQUENCE = (
    Ability.DEATHTOUCH,
    Ability.FLYING,
    Ability.HASTE,
    Ability.LIFELINK,
    Ability.TRAMPLE,
    Ability.VIGILANCE,
    Ability.PROVOKE,
)
BUILDER_ABILITY_OPTIONS = (
    Ability.HASTE,
    Ability.FLYING,
    Ability.ENRAGED,
    Ability.TRAMPLE,
    Ability.VIGILANT,
    Ability.LIFE_STEAL,
)
BUILDER_ABILITY_LABELS = {
    Ability.DEATHTOUCH: "Deathtouch",
    Ability.FLYING: "Flying",
    Ability.HASTE: "Haste",
    Ability.LIFELINK: "Lifelink",
    Ability.TRAMPLE: "Trample",
    Ability.VIGILANCE: "Vigilance",
    Ability.PROVOKE: "Provoke",
    Ability.LIFE_STEAL: "Lifelink",
    Ability.VIGILANT: "Vigilance",
    Ability.ENRAGED: "Provoke",
}
BUILDER_ABILITY_RULES_TEXT = {
    Ability.DEATHTOUCH: "Grant Deathtouch, +1 stat, or deal 1 damage to a creature.",
    Ability.FLYING: "Grant Flying, +1 stat, or deal 1 damage to a creature.",
    Ability.HASTE: "Grant Haste, +1 stat, or deal 1 damage to a creature.",
    Ability.LIFELINK: "Grant Lifelink, +1 stat, or deal 1 damage to a creature.",
    Ability.TRAMPLE: "Grant Trample, +1 stat, or deal 1 damage to a creature.",
    Ability.VIGILANCE: "Grant Vigilance, +1 stat, or deal 1 damage to a creature.",
    Ability.PROVOKE: "Grant Provoke, +1 stat, or deal 1 damage to a creature.",
}


def builder_resource_template(self) -> CardTemplate:
    return CardTemplate(
        template_id=BUILDER_RESOURCE_TEMPLATE_ID,
        name="Resource",
        cost=CardCost(),
        aw=0,
        vw=0,
        element=Element.AIR,
        card_type=CardType.RITUAL,
    )


def builder_mode_active(self) -> bool:
    return is_builder_mode()


def builder_abilities_enabled(self) -> bool:
    return builder_mode_active(self) and BUILDER_ABILITIES_ENABLED


def _builder_ability_template(self, ability: Ability) -> CardTemplate:
    template_id = f"builder_ability_{ability.name.lower()}"
    template = self.templates.get(template_id)
    if template is not None:
        return template
    template = CardTemplate(
        template_id=template_id,
        name=BUILDER_ABILITY_LABELS[ability],
        cost=CardCost(),
        aw=0,
        vw=0,
        element=Element.AIR,
        card_type=CardType.SPELL,
        rules_text=BUILDER_ABILITY_RULES_TEXT[ability],
    )
    self.templates[template_id] = template
    return template


def _build_builder_shared_ability_deck(self) -> list[CardInstance]:
    deck: list[CardInstance] = []
    for ability in BUILDER_SHARED_ABILITY_SEQUENCE:
        template = _builder_ability_template(self, ability)
        for _ in range(BUILDER_SHARED_ABILITY_COUNTS):
            deck.append(CardInstance(self.make_instance_id(), template))
    self.rng.shuffle(deck)
    return deck


def get_builder_card_ability(self, card: CardInstance | None) -> Ability | None:
    if card is None:
        return None
    for ability in BUILDER_SHARED_ABILITY_SEQUENCE:
        if card.template.template_id == f"builder_ability_{ability.name.lower()}":
            return ability
    return None


def builder_draw_ability_card(self, player: PlayerState, source_name: str) -> CardInstance | None:
    if not builder_abilities_enabled(self):
        return None
    if not self.builder_shared_deck:
        if self.builder_shared_discard:
            self.builder_shared_deck = list(self.builder_shared_discard)
            self.builder_shared_discard = []
            self.rng.shuffle(self.builder_shared_deck)
            self.log("The builder discard pile is shuffled into a new shared deck.")
        else:
            return None
    drawn = self.builder_shared_deck.pop()
    player.hand.append(drawn)
    if self.statistics is not None:
        self.statistics.register_draw(player.player_id)
    self.log(f"{player.name} draws 1 ability card from {source_name}.")
    return drawn


def discard_builder_ability_card(self, player: PlayerState, card_instance_id: int) -> CardInstance | None:
    card = next((existing for existing in player.hand if existing.instance_id == card_instance_id), None)
    if card is None:
        return None
    player.hand = [existing for existing in player.hand if existing.instance_id != card_instance_id]
    self.builder_shared_discard.append(card)
    self.selected_hand_ids.clear()
    return card


def initialize_builder_game(self) -> None:
    self.players = [
        PlayerState(0, "Player", True, summoner_key="builder", life=STARTING_LIFE),
        PlayerState(1, "Enemy", False, summoner_key="builder", life=STARTING_LIFE),
    ]
    self.turn_number = 0
    self.phase = PHASE_MAIN_1
    self.pending_builder_creature = None
    self.pending_builder_ability = None
    self.builder_creature_counter = 0
    self.builder_shared_deck = _build_builder_shared_ability_deck(self) if BUILDER_ABILITIES_ENABLED else []
    self.builder_shared_discard = []
    self.builder_ability_used_this_turn = False
    self.builder_created_this_turn_ids = set()
    self.selected_hand_ids.clear()
    for player in self.players:
        player.deck.clear()
        player.discard_pile.clear()
        player.hand.clear()
        player.battlefield.clear()
        player.resources.clear()
        player.resources_played_this_turn = 0
        player.main_action_used_this_turn = False
        player.summoner_passive_draw_used_this_turn = False
        player.creature_cost_reduction_this_turn = 0
        player.summoner_tapped = False
        player.turns_started = 0
        player.mulligan_used = True
    self.starting_player_id = self.rng.choice([0, 1])
    self.active_player_index = self.starting_player_id
    self.statistics = GameStatistics(
        game_id=self.game_id,
        seed=self.seed,
        started_at=datetime.now().isoformat(timespec="seconds"),
        start_player=self.players[self.starting_player_id].name,
        player_names={0: "Player", 1: "Enemy"},
    )
    self.log("New game started in builder mode.")
    self.start_turn()


def start_builder_turn(self) -> None:
    if hasattr(self.ai, "clear_active_turn_plan"):
        self.ai.clear_active_turn_plan()
    player = self.active_player
    self.turn_number += 1
    self.creatures_died_this_turn = 0
    player.untap_for_turn()
    player.main_action_used_this_turn = False
    self.pending_builder_creature = None
    self.pending_builder_ability = None
    self.builder_ability_used_this_turn = False
    self.builder_created_this_turn_ids = set()
    self.attack_declared_this_turn = False
    self.log(f"Turn {self.turn_number}: {player.name} is active.")
    player.turns_started += 1
    self.phase = PHASE_MAIN_1
    self.selected_hand_ids.clear()
    self.selected_attackers.clear()
    self.selected_blocker_id = None
    self.ai_turn_initialized = False
    self.pending_ai_action = None
    if self.statistics is not None:
        self.statistics.register_turn_count(self.turn_number)
    self.check_for_game_over()


def can_take_builder_main_action(self, player: PlayerState) -> bool:
    return player == self.active_player and self.phase == PHASE_MAIN_1 and not player.main_action_used_this_turn


def can_builder_add_resource(self, player: PlayerState) -> bool:
    return can_take_builder_main_action(self, player) and player.total_resources() < BUILDER_MAX_RESOURCES


def can_builder_open_creature_build(self, player: PlayerState) -> bool:
    return can_take_builder_main_action(self, player) and len(player.battlefield) < BUILDER_CREATURE_CAP


def begin_builder_creature_build(self) -> bool:
    if not builder_mode_active(self) or not can_builder_open_creature_build(self, self.active_player) or not self.active_player.is_human:
        if builder_mode_active(self) and self.active_player.is_human and len(self.active_player.battlefield) >= BUILDER_CREATURE_CAP:
            self.log(f"Creature cap reached ({len(self.active_player.battlefield)}/{BUILDER_CREATURE_CAP}).")
        return False
    if self.active_player.available_resources() <= 0:
        creature = create_builder_creature(
            self,
            self.active_player,
            aw=0,
            vw=0,
            sw=0,
            lw=1,
            abilities=frozenset(),
        )
        self.builder_created_this_turn_ids.add(creature.unit_id)
        self.active_player.main_action_used_this_turn = True
        if self.statistics is not None:
            self.statistics.register_creature_played(self.active_player.player_id, 0)
        self.log(
            f"{self.active_player.name} creates {creature.name} "
            f"(A {creature.aw} / D {creature.vw} / DMG {creature.sw} / Life {creature.lw}) "
            f"for 0 resource(s)."
        )
        finish_builder_main_action(self)
        return True
    self.pending_builder_creature = PendingBuilderCreatureBuild(available_resources=self.active_player.available_resources())
    self.phase = PHASE_BUILDER_CREATURE
    return True


def cancel_builder_creature_build(self) -> None:
    if self.phase != PHASE_BUILDER_CREATURE:
        return
    self.pending_builder_creature = None
    self.phase = PHASE_MAIN_1


def builder_creature_build_cost(self, pending: PendingBuilderCreatureBuild | None = None) -> int:
    current = self.pending_builder_creature if pending is None else pending
    return 0 if current is None else current.spent_resources


def adjust_builder_creature_stat(self, stat_name: str, delta: int) -> None:
    pending = self.pending_builder_creature
    if self.phase != PHASE_BUILDER_CREATURE or pending is None or delta == 0:
        return
    minimums = {
        "aw": pending.base_aw,
        "vw": pending.base_vw,
        "sw": pending.base_sw,
        "lw": pending.base_lw,
    }
    current_value = getattr(pending, stat_name)
    next_value = current_value + delta
    if next_value < minimums[stat_name]:
        return
    original_value = current_value
    setattr(pending, stat_name, next_value)
    if pending.spent_resources > pending.available_resources:
        setattr(pending, stat_name, original_value)


def toggle_builder_creature_ability(self, ability: Ability) -> None:
    return


def builder_creature_build_is_valid(self, pending: PendingBuilderCreatureBuild | None = None) -> bool:
    current = self.pending_builder_creature if pending is None else pending
    if current is None:
        return False
    if current.spent_resources <= 0:
        return False
    return current.spent_resources <= current.available_resources and current.lw >= 1 and current.aw >= 0 and current.vw >= 0 and current.sw >= 0


def builder_remaining_ready_resources(self, pending: PendingBuilderCreatureBuild | None = None) -> int:
    current = self.pending_builder_creature if pending is None else pending
    if current is None:
        return 0
    return max(0, current.available_resources - current.spent_resources)


def builder_spend_ready_resources(self, player: PlayerState, amount: int) -> bool:
    if amount <= 0:
        return True
    tapped = player.tap_resources_for_cost(amount)
    return len(tapped) == amount


def _advance_to_builder_ability_phase(self) -> None:
    self.pending_builder_creature = None
    self.pending_builder_ability = None
    self.selected_hand_ids.clear()
    self.phase = PHASE_BUILDER_ABILITY


def builder_has_any_ability_targets(self, player: PlayerState) -> bool:
    if not builder_abilities_enabled(self):
        return False
    if any(existing.current_hp > 0 for existing in player.battlefield):
        return True
    enemy = self.players[1 - player.player_id]
    return any(existing.current_hp > 0 for existing in enemy.battlefield)


def _builder_should_skip_first_turn_draw(self, player: PlayerState) -> bool:
    return player.player_id == self.starting_player_id and player.turns_started <= 1


def advance_builder_after_ability_phase(self) -> None:
    if self.available_attackers(self.active_player):
        return
    self.log("No creatures can attack. Combat is skipped and the turn ends.")
    self.end_turn()


def finish_builder_main_action(self) -> None:
    if not builder_abilities_enabled(self):
        self.pending_builder_creature = None
        self.pending_builder_ability = None
        self.selected_hand_ids.clear()
        self.phase = PHASE_MAIN_1
        if self.available_attackers(self.active_player):
            self.begin_attack_declaration()
            return
        self.log("No creatures can attack. Combat is skipped and the turn ends.")
        self.end_turn()
        return
    _advance_to_builder_ability_phase(self)
    if not builder_has_any_ability_targets(self, self.active_player):
        self.log("No creatures are in play. The ability phase is skipped.")
        self.skip_builder_ability_phase()


def create_builder_creature(
    self,
    player: PlayerState,
    *,
    aw: int,
    vw: int,
    sw: int,
    lw: int,
    abilities: frozenset[Ability] = frozenset(),
):
    if len(player.battlefield) >= BUILDER_CREATURE_CAP:
        return None
    self.builder_creature_counter += 1
    template = CardTemplate(
        template_id=f"builder_creature_{self.builder_creature_counter}",
        name=f"Creature {self.builder_creature_counter}",
        cost=CardCost(resources=aw + vw + sw + max(0, lw - 1)),
        aw=aw,
        vw=vw,
        lw=lw,
        sw=sw,
        element=Element.AIR,
        abilities=abilities,
        rules_text="",
        allow_zero_stats=True,
    )
    self.templates[template.template_id] = template
    instance_id = self.make_instance_id()
    built = BattlefieldCreature.from_card(CardInstance(instance_id, template))
    built.current_hp = lw
    built.tapped = True
    built.summoning_sick = True
    player.battlefield.append(built)
    return built


def get_builder_preview_creature(self, player: PlayerState) -> BattlefieldCreature | None:
    pending = self.pending_builder_creature
    if (
        not builder_mode_active(self)
        or self.phase != PHASE_BUILDER_CREATURE
        or pending is None
        or player.player_id != self.active_player.player_id
        or not player.is_human
    ):
        return None
    template = CardTemplate(
        template_id=BUILDER_PREVIEW_TEMPLATE_ID,
        name="New Creature",
        cost=CardCost(resources=pending.spent_resources),
        aw=pending.aw,
        vw=pending.vw,
        lw=pending.lw,
        sw=pending.sw,
        element=Element.AIR,
        abilities=frozenset(),
        rules_text="",
        allow_zero_stats=True,
    )
    preview = BattlefieldCreature.from_card(CardInstance(-(player.player_id + 1), template))
    preview.current_hp = pending.lw
    preview.tapped = False
    preview.summoning_sick = True
    setattr(preview, "is_builder_preview", True)
    return preview


def confirm_builder_creature_build(self) -> bool:
    pending = self.pending_builder_creature
    if self.phase != PHASE_BUILDER_CREATURE or pending is None or not builder_creature_build_is_valid(self, pending):
        return False
    if len(self.active_player.battlefield) >= BUILDER_CREATURE_CAP:
        self.log(f"Creature cap reached ({len(self.active_player.battlefield)}/{BUILDER_CREATURE_CAP}).")
        return False
    spent = pending.spent_resources
    if not builder_spend_ready_resources(self, self.active_player, spent):
        return False
    creature = create_builder_creature(
        self,
        self.active_player,
        aw=pending.aw,
        vw=pending.vw,
        sw=pending.sw,
        lw=pending.lw,
        abilities=frozenset(),
    )
    self.builder_created_this_turn_ids.add(creature.unit_id)
    self.active_player.main_action_used_this_turn = True
    self.pending_builder_creature = None
    if self.statistics is not None:
        self.statistics.register_creature_played(self.active_player.player_id, 0)
    self.log(
        f"{self.active_player.name} creates {creature.name} "
        f"(A {creature.aw} / D {creature.vw} / DMG {creature.sw} / Life {creature.lw}) "
        f"for {spent} resource(s)."
    )
    finish_builder_main_action(self)
    return True


def builder_add_resource(self, player: PlayerState) -> bool:
    if not can_builder_add_resource(self, player):
        return False
    player.resources.append(
        ResourceCard(
            template=builder_resource_template(self),
            resource_id=self.make_instance_id(),
            tapped=False,
        )
    )
    player.main_action_used_this_turn = True
    if self.statistics is not None:
        self.statistics.register_resource_played(player.player_id)
    self.log(f"{player.name} increases resources to {player.total_resources()}/{BUILDER_MAX_RESOURCES}.")
    finish_builder_main_action(self)
    return True


def builder_pass_main_action(self, player: PlayerState) -> bool:
    if not can_take_builder_main_action(self, player):
        return False
    player.main_action_used_this_turn = True
    self.log(f"{player.name} passes the build phase.")
    finish_builder_main_action(self)
    return True


def can_builder_use_ability_card(self, player: PlayerState) -> bool:
    return (
        builder_abilities_enabled(self)
        and player == self.active_player
        and self.phase == PHASE_BUILDER_ABILITY
        and not self.builder_ability_used_this_turn
        and bool(player.hand)
    )


def begin_builder_ability_use(self, card_instance_id: int) -> bool:
    if not builder_abilities_enabled(self):
        return False
    if not can_builder_use_ability_card(self, self.active_player):
        return False
    card = next((existing for existing in self.active_player.hand if existing.instance_id == card_instance_id), None)
    if card is None or get_builder_card_ability(self, card) is None:
        return False
    self.pending_builder_ability = PendingBuilderAbilityUse(card_instance_id=card_instance_id)
    self.selected_hand_ids = [card_instance_id]
    return True


def cancel_builder_ability_use(self) -> None:
    if self.phase != PHASE_BUILDER_ABILITY:
        return
    self.pending_builder_ability = None
    self.selected_hand_ids.clear()


def choose_builder_ability_mode(self, mode: str, stat_name: str | None = None) -> bool:
    if not builder_abilities_enabled(self):
        return False
    pending = self.pending_builder_ability
    if self.phase != PHASE_BUILDER_ABILITY or pending is None:
        return False
    if mode not in {"grant_ability", "add_stat", "deal_damage"}:
        return False
    if mode == "add_stat" and stat_name not in {"aw", "vw", "sw", "lw"}:
        return False
    pending.mode = mode
    pending.selected_stat = stat_name
    pending.selected_target_id = None
    return True


def _can_grant_builder_ability_to_creature(self, creature: BattlefieldCreature, ability: Ability) -> bool:
    owner = self.get_unit_owner(creature.unit_id)
    if owner != self.active_player:
        return False
    distinct_abilities = set(creature.abilities)
    normalized_distinct = {
        Ability.VIGILANCE if value == Ability.VIGILANT else Ability.LIFELINK if value == Ability.LIFE_STEAL else Ability.PROVOKE if value == Ability.ENRAGED else value
        for value in distinct_abilities
    }
    if ability in normalized_distinct:
        return False
    if len(normalized_distinct) >= 2:
        return False
    if ability == Ability.HASTE and creature.unit_id not in self.builder_created_this_turn_ids:
        return False
    return True


def _can_select_builder_ability_target(self, creature: BattlefieldCreature, pending: PendingBuilderAbilityUse) -> bool:
    card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
    granted_ability = get_builder_card_ability(self, card)
    if granted_ability is None or creature is None:
        return False
    if pending.mode == "grant_ability":
        return _can_grant_builder_ability_to_creature(self, creature, granted_ability)
    if pending.mode == "add_stat":
        return self.get_unit_owner(creature.unit_id) == self.active_player
    if pending.mode == "deal_damage":
        return self.get_unit_owner(creature.unit_id) is not None
    return False


def select_builder_ability_target(self, creature_id: int) -> bool:
    if not builder_abilities_enabled(self):
        return False
    pending = self.pending_builder_ability
    if self.phase != PHASE_BUILDER_ABILITY or pending is None or pending.mode is None:
        return False
    creature = self.get_unit_by_id(creature_id)
    if creature is None:
        return False
    if not _can_select_builder_ability_target(self, creature, pending):
        return False
    pending.selected_target_id = creature_id
    return True


def builder_pending_ability_ready(self) -> bool:
    if not builder_abilities_enabled(self):
        return False
    pending = self.pending_builder_ability
    if pending is None or pending.mode is None or pending.selected_target_id is None:
        return False
    if pending.mode == "add_stat" and pending.selected_stat is None:
        return False
    creature = self.get_unit_by_id(pending.selected_target_id)
    return creature is not None and _can_select_builder_ability_target(self, creature, pending)


def resolve_builder_ability_use(self) -> bool:
    if not builder_abilities_enabled(self):
        return False
    pending = self.pending_builder_ability
    if self.phase != PHASE_BUILDER_ABILITY or pending is None or not builder_pending_ability_ready(self):
        return False
    target = self.get_unit_by_id(pending.selected_target_id or -1)
    card = next((existing for existing in self.active_player.hand if existing.instance_id == pending.card_instance_id), None)
    granted_ability = get_builder_card_ability(self, card)
    if target is None or card is None or granted_ability is None:
        return False
    if pending.mode == "grant_ability":
        target.abilities = frozenset(set(target.abilities) | {granted_ability})
        if granted_ability == Ability.HASTE and target.unit_id in self.builder_created_this_turn_ids:
            target.tapped = False
        self.log(f"{self.active_player.name} gives {BUILDER_ABILITY_LABELS[granted_ability]} to {target.name}.")
    elif pending.mode == "add_stat":
        if pending.selected_stat == "aw":
            target.aw += 1
        elif pending.selected_stat == "vw":
            target.vw += 1
        elif pending.selected_stat == "sw":
            target.sw += 1
        elif pending.selected_stat == "lw":
            target.lw += 1
            target.current_hp += 1
        self.log(f"{self.active_player.name} gives +1 {pending.selected_stat.upper()} to {target.name}.")
    elif pending.mode == "deal_damage":
        target.current_hp -= 1
        self.log(f"{self.active_player.name} deals 1 damage to {target.name}.")
        self.cleanup_destroyed_units()
        self.check_for_game_over()
        if self.phase == PHASE_GAME_OVER:
            return True
    discard_builder_ability_card(self, self.active_player, pending.card_instance_id)
    self.pending_builder_ability = None
    self.builder_ability_used_this_turn = True
    advance_builder_after_ability_phase(self)
    return True


def skip_builder_ability_phase(self) -> bool:
    if not builder_abilities_enabled(self):
        return False
    if self.phase != PHASE_BUILDER_ABILITY:
        return False
    self.pending_builder_ability = None
    self.selected_hand_ids.clear()
    self.builder_ability_used_this_turn = True
    advance_builder_after_ability_phase(self)
    return True


def finish_builder_turn_after_combat(self) -> None:
    if builder_abilities_enabled(self) and self.attack_declared_this_turn and not _builder_should_skip_first_turn_draw(self, self.active_player):
        self.builder_draw_ability_card(self.active_player, "Attack phase")
