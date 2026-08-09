from __future__ import annotations

from core.config import STARTING_LIFE
from core.game_mode import is_builder_mode
from core.models import (
    BattlefieldCreature,
    CardCost,
    CardInstance,
    CardTemplate,
    CardType,
    Element,
    PendingBuilderCreatureBuild,
    PHASE_BUILDER_CREATURE,
    PHASE_MAIN_1,
    PlayerState,
    ResourceCard,
)
from stats import GameStatistics
from datetime import datetime


BUILDER_MAX_RESOURCES = 10
BUILDER_STARTING_RESOURCES = 1
BUILDER_RESOURCE_TEMPLATE_ID = "builder_resource"
BUILDER_PREVIEW_TEMPLATE_ID = "builder_creature_preview"


def builder_resource_template(self) -> CardTemplate:
    return CardTemplate(
        template_id=BUILDER_RESOURCE_TEMPLATE_ID,
        name="Ressource",
        cost=CardCost(),
        aw=0,
        vw=0,
        element=Element.AIR,
        card_type=CardType.RITUAL,
    )


def builder_mode_active(self) -> bool:
    return is_builder_mode()


def initialize_builder_game(self) -> None:
    self.players = [
        PlayerState(0, "Spieler", True, summoner_key="builder", life=STARTING_LIFE),
        PlayerState(1, "Gegner", False, summoner_key="builder", life=STARTING_LIFE),
    ]
    self.turn_number = 0
    self.phase = PHASE_MAIN_1
    self.pending_builder_creature = None
    self.builder_creature_counter = 0
    self.selected_hand_ids.clear()
    for player in self.players:
        player.deck.clear()
        player.hand.clear()
        player.discard_pile.clear()
        player.battlefield.clear()
        player.resources.clear()
        player.resources_played_this_turn = 0
        player.main_action_used_this_turn = False
        player.summoner_passive_draw_used_this_turn = False
        player.creature_cost_reduction_this_turn = 0
        player.summoner_tapped = False
        player.turns_started = 0
        player.mulligan_used = True
        player.resources.append(ResourceCard(template=builder_resource_template(self), resource_id=self.make_instance_id(), tapped=False))
    self.starting_player_id = self.rng.choice([0, 1])
    self.active_player_index = self.starting_player_id
    self.statistics = GameStatistics(
        game_id=self.game_id,
        seed=self.seed,
        started_at=datetime.now().isoformat(timespec="seconds"),
        start_player=self.players[self.starting_player_id].name,
        player_names={0: "Spieler", 1: "Gegner"},
    )
    self.log("Neue Partie im Builder-Modus gestartet.")
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
    self.log(f"Zug {self.turn_number}: {player.name} ist am Zug.")
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
    return can_take_builder_main_action(self, player)


def begin_builder_creature_build(self) -> bool:
    if not builder_mode_active(self) or not can_builder_open_creature_build(self, self.active_player) or not self.active_player.is_human:
        return False
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


def builder_creature_build_is_valid(self, pending: PendingBuilderCreatureBuild | None = None) -> bool:
    current = self.pending_builder_creature if pending is None else pending
    if current is None:
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


def finish_builder_main_action(self) -> None:
    if self.available_attackers(self.active_player):
        self.phase = PHASE_MAIN_1
        return
    self.log("Keine bereiten Kreaturen fuer einen Angriff. Der Zug endet automatisch.")
    self.end_turn()


def create_builder_creature(self, player: PlayerState, *, aw: int, vw: int, sw: int, lw: int):
    self.builder_creature_counter += 1
    template = CardTemplate(
        template_id=f"builder_creature_{self.builder_creature_counter}",
        name=f"Kreatur {self.builder_creature_counter}",
        cost=CardCost(resources=aw + vw + sw + max(0, lw - 1)),
        aw=aw,
        vw=vw,
        lw=lw,
        sw=sw,
        element=Element.AIR,
        abilities=frozenset(),
        rules_text="",
        allow_zero_stats=True,
    )
    instance_id = self.make_instance_id()
    built = BattlefieldCreature.from_card(CardInstance(instance_id, template))
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
        name="Neue Kreatur",
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
    preview.tapped = True
    preview.summoning_sick = True
    setattr(preview, "is_builder_preview", True)
    return preview


def confirm_builder_creature_build(self) -> bool:
    pending = self.pending_builder_creature
    if self.phase != PHASE_BUILDER_CREATURE or pending is None or not builder_creature_build_is_valid(self, pending):
        return False
    spent = pending.spent_resources
    if not builder_spend_ready_resources(self, self.active_player, spent):
        return False
    creature = create_builder_creature(self, self.active_player, aw=pending.aw, vw=pending.vw, sw=pending.sw, lw=pending.lw)
    self.active_player.main_action_used_this_turn = True
    self.phase = PHASE_MAIN_1
    self.pending_builder_creature = None
    if self.statistics is not None:
        self.statistics.register_creature_played(self.active_player.player_id, 0)
    self.log(
        f"{self.active_player.name} baut {creature.name} "
        f"(A {creature.aw} / V {creature.vw} / S {creature.sw} / L {creature.lw})"
        f" fuer {spent} Ressource(n)."
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
    self.log(f"{player.name} erhoeht seine Ressourcen auf {player.total_resources()}/{BUILDER_MAX_RESOURCES}.")
    finish_builder_main_action(self)
    return True
