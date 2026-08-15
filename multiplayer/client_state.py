from __future__ import annotations

from typing import Any

from core.game_logic import GameEngine
from core.models import (
    Ability,
    BattlefieldCreature,
    CardCost,
    CardInstance,
    CardTemplate,
    CardType,
    CombatUnitSnapshot,
    ControllerKind,
    DiceRoundRecord,
    Element,
    MatchMode,
    PendingBuilderAbilityUse,
    PendingBuilderCreatureBuild,
    PendingDiceBattle,
    PendingDirectAttack,
    PHASE_DECLARE_BLOCKERS,
    PHASE_GAME_OVER,
    PlayerState,
    ResourceCard,
)
from multiplayer.snapshot import GameStateSnapshot


def _deserialize_cost(data: dict[str, Any]) -> CardCost:
    return CardCost(resources=data["resources"], recycle=data["recycle"])


def _deserialize_template(data: dict[str, Any]) -> CardTemplate:
    return CardTemplate(
        template_id=data["template_id"],
        name=data["name"],
        cost=_deserialize_cost(data["cost"]),
        aw=data["aw"],
        vw=data["vw"],
        lw=data["lw"],
        sw=data["sw"],
        element=Element[data["element"]],
        abilities=frozenset(Ability[name] for name in data["abilities"]),
        builder_ability=(Ability[data["builder_ability"]] if data["builder_ability"] else None),
        card_type=CardType[data["card_type"]],
        rules_text=data["rules_text"],
        return_to_deck_end_of_turn=data["return_to_deck_end_of_turn"],
        cannot_block=data["cannot_block"],
        must_attack_each_turn=data["must_attack_each_turn"],
        all_attackers_die_bonus=data["all_attackers_die_bonus"],
        allow_zero_stats=data["allow_zero_stats"],
        draw_on_attack=data["draw_on_attack"],
        draw_on_death=data["draw_on_death"],
        draw_on_player_damage=data["draw_on_player_damage"],
        tap_enemy_creature_on_play=data["tap_enemy_creature_on_play"],
        return_other_own_haste_on_combat_death=data["return_other_own_haste_on_combat_death"],
        own_flying_attack_aura=data["own_flying_attack_aura"],
    )


def _deserialize_card(data: dict[str, Any]) -> CardInstance:
    return CardInstance(
        instance_id=data["instance_id"],
        template=_deserialize_template(data["template"]),
        was_recycled=data["was_recycled"],
    )


def _hidden_template() -> CardTemplate:
    return CardTemplate(
        template_id="network_hidden_card",
        name="Hidden card",
        cost=CardCost(),
        aw=1,
        vw=0,
        lw=1,
        sw=1,
        element=Element.AIR,
        rules_text="",
    )


def _hidden_cards(count: int, *, id_offset: int) -> list[CardInstance]:
    template = _hidden_template()
    return [
        CardInstance(instance_id=-(id_offset + index + 1), template=template)
        for index in range(count)
    ]


def _deserialize_resource(data: dict[str, Any]) -> ResourceCard:
    return ResourceCard(
        resource_id=data["resource_id"],
        tapped=data["tapped"],
        template=_deserialize_template(data["template"]),
    )


def _deserialize_creature(data: dict[str, Any]) -> BattlefieldCreature:
    return BattlefieldCreature(
        unit_id=data["unit_id"],
        template_id=data["template_id"],
        name=data["name"],
        cost=_deserialize_cost(data["cost"]),
        aw=data["aw"],
        vw=data["vw"],
        lw=data["lw"],
        sw=data["sw"],
        element=Element[data["element"]],
        abilities=frozenset(Ability[name] for name in data["abilities"]),
        builder_ability=(Ability[data["builder_ability"]] if data["builder_ability"] else None),
        rules_text=data["rules_text"],
        return_to_deck_end_of_turn=data["return_to_deck_end_of_turn"],
        cannot_block=data["cannot_block"],
        must_attack_each_turn=data["must_attack_each_turn"],
        all_attackers_die_bonus=data["all_attackers_die_bonus"],
        draw_on_attack=data["draw_on_attack"],
        draw_on_death=data["draw_on_death"],
        draw_on_player_damage=data["draw_on_player_damage"],
        tap_enemy_creature_on_play=data["tap_enemy_creature_on_play"],
        return_other_own_haste_on_combat_death=data["return_other_own_haste_on_combat_death"],
        own_flying_attack_aura=data["own_flying_attack_aura"],
        current_hp=data["current_hp"],
        temporary_aw_bonus=data["temporary_aw_bonus"],
        temporary_combat_aw_bonus=data["temporary_combat_aw_bonus"],
        temporary_combat_sw_bonus=data["temporary_combat_sw_bonus"],
        temporary_abilities={Ability[name] for name in data["temporary_abilities"]},
        tapped=data["tapped"],
        summoning_sick=data["summoning_sick"],
    )


def _deserialize_player(data: dict[str, Any], local_player_id: int) -> PlayerState:
    player_id = data["player_id"]
    controller_kind = (
        ControllerKind.LOCAL_HUMAN
        if player_id == local_player_id
        else ControllerKind.REMOTE_HUMAN
    )
    player = PlayerState(
        player_id=player_id,
        name=data["name"],
        is_human=True,
        summoner_key=data["summoner_key"],
        life=data["life"],
        controller_kind=controller_kind,
    )
    player.deck = _hidden_cards(data["deck_count"], id_offset=100_000 + player_id * 10_000)
    if data["hand_cards"] is None:
        player.hand = _hidden_cards(data["hand_count"], id_offset=200_000 + player_id * 10_000)
    else:
        player.hand = [_deserialize_card(card) for card in data["hand_cards"]]
    player.discard_pile = [_deserialize_card(card) for card in data["discard_pile"]]
    player.battlefield = [_deserialize_creature(creature) for creature in data["battlefield"]]
    player.resources = [_deserialize_resource(resource) for resource in data["resources"]]
    player.resources_played_this_turn = data["resources_played_this_turn"]
    player.main_action_used_this_turn = data["main_action_used_this_turn"]
    player.summoner_passive_draw_used_this_turn = data["summoner_passive_draw_used_this_turn"]
    player.creature_cost_reduction_this_turn = data["creature_cost_reduction_this_turn"]
    player.summoner_tapped = data["summoner_tapped"]
    player.turns_started = data["turns_started"]
    player.mulligan_used = data["mulligan_used"]
    return player


def _deserialize_builder_creature(data: dict[str, Any] | None) -> PendingBuilderCreatureBuild | None:
    if data is None:
        return None
    return PendingBuilderCreatureBuild(
        base_aw=data["base_aw"],
        base_vw=data["base_vw"],
        base_sw=data["base_sw"],
        base_lw=data["base_lw"],
        aw=data["aw"],
        vw=data["vw"],
        sw=data["sw"],
        lw=data["lw"],
        available_resources=data["available_resources"],
        selected_ability=(Ability[data["selected_ability"]] if data["selected_ability"] else None),
    )


def _deserialize_builder_ability(data: dict[str, Any] | None) -> PendingBuilderAbilityUse | None:
    if data is None:
        return None
    return PendingBuilderAbilityUse(
        card_instance_id=data["card_instance_id"],
        mode=data["mode"],
        selected_target_id=data["selected_target_id"],
        selected_stat=data["selected_stat"],
    )


def _deserialize_combat_unit(data: dict[str, Any]) -> CombatUnitSnapshot:
    return CombatUnitSnapshot(
        unit_id=data["unit_id"],
        template_id=data["template_id"],
        name=data["name"],
        cost=_deserialize_cost(data["cost"]),
        aw=data["aw"],
        vw=data["vw"],
        lw=data["lw"],
        sw=data["sw"],
        current_hp=data["current_hp"],
        element=Element[data["element"]],
        abilities=frozenset(Ability[name] for name in data["abilities"]),
        rules_text=data["rules_text"],
        tapped=data["tapped"],
    )


def _deserialize_dice_battle(data: dict[str, Any] | None) -> PendingDiceBattle | None:
    if data is None:
        return None
    return PendingDiceBattle(
        attacker_id=data["attacker_id"],
        blocker_id=data["blocker_id"],
        attacker_owner=data["attacker_owner"],
        blocker_owner=data["blocker_owner"],
        attacker_snapshot=_deserialize_combat_unit(data["attacker_snapshot"]),
        blocker_snapshot=_deserialize_combat_unit(data["blocker_snapshot"]),
        attacker_rolls=list(data["attacker_rolls"]),
        blocker_rolls=list(data["blocker_rolls"]),
        attack_sum=data["attack_sum"],
        defense_sum=data["defense_sum"],
        reroll_count=data["reroll_count"],
        winner=data["winner"],
        creature_damage=data["creature_damage"],
        trample_damage=data["trample_damage"],
        history=[
            DiceRoundRecord(
                round_number=record["round_number"],
                attacker_rolls=list(record["attacker_rolls"]),
                blocker_rolls=list(record["blocker_rolls"]),
                attack_sum=record["attack_sum"],
                defense_sum=record["defense_sum"],
                outcome_text=record["outcome_text"],
            )
            for record in data["history"]
        ],
        resolution_complete=data["resolution_complete"],
        result_applied=data["result_applied"],
        attacker_hp_after=data["attacker_hp_after"],
        blocker_hp_after=data["blocker_hp_after"],
        resolution_log=data["resolution_log"],
    )


def _deserialize_direct_attack(data: dict[str, Any] | None) -> PendingDirectAttack | None:
    if data is None:
        return None
    return PendingDirectAttack(
        attacker_id=data["attacker_id"],
        attacker_owner=data["attacker_owner"],
        defending_player_id=data["defending_player_id"],
        base_damage=data["base_damage"],
    )


class ClientGameView(GameEngine):
    """Non-authoritative engine-shaped view reconstructed from host snapshots."""

    def __init__(self, local_player_id: int) -> None:
        self.local_view_player_id = local_player_id
        self.snapshot_revision = -1
        super().__init__(auto_start=False, match_mode=MatchMode.PVP)

    @property
    def human_player(self) -> PlayerState:
        return self.players[self.local_view_player_id]

    @property
    def ai_player(self) -> PlayerState:
        return self.players[1 - self.local_view_player_id]

    @property
    def player_one(self) -> PlayerState:
        return self.human_player

    @property
    def player_two(self) -> PlayerState:
        return self.ai_player

    def get_button_specs(self):
        if not self.local_player_has_primary_decision():
            return []
        return super().get_button_specs()

    def current_prompt(self) -> str:
        if not self.local_player_has_primary_decision():
            return f"Waiting for {self.active_player.name}."
        return super().current_prompt()

    def local_player_has_primary_decision(self) -> bool:
        if self.phase == PHASE_GAME_OVER:
            return self.local_view_player_id == 0
        if self.phase == PHASE_DECLARE_BLOCKERS:
            return self.defending_player.player_id == self.local_view_player_id
        return self.active_player.player_id == self.local_view_player_id

    def apply_snapshot(self, snapshot: GameStateSnapshot) -> bool:
        if snapshot.viewer_player_id != self.local_view_player_id:
            raise ValueError("Snapshot belongs to a different player view.")
        if snapshot.revision < self.snapshot_revision:
            return False
        state = snapshot.state
        players = [_deserialize_player(player, self.local_view_player_id) for player in state["players"]]
        players.sort(key=lambda player: player.player_id)
        if [player.player_id for player in players] != list(range(len(players))):
            raise ValueError("Snapshot player IDs must be contiguous and zero-based.")
        self.players = players
        self.game_id = state["game_id"]
        self.turn_number = state["turn_number"]
        self.phase = state["phase"]
        self.active_player_index = state["active_player_id"]
        self.starting_player_id = state["starting_player_id"]
        self.game_over_text = state["game_over_text"]
        self.game_over_summary_lines = []
        self.builder_shared_deck = _hidden_cards(
            state["builder_shared_deck_count"],
            id_offset=300_000,
        )
        self.builder_shared_discard = [
            _deserialize_card(card) for card in state["builder_shared_discard"]
        ]
        self.builder_ability_used_this_turn = state["builder_ability_used_this_turn"]
        self.selected_hand_ids = list(state["selected_hand_ids"])
        self.selected_attackers = list(state["selected_attackers"])
        self.selected_blocker_id = state["selected_blocker_id"]
        self.selected_attack_target_id = state["selected_attack_target_id"]
        self.block_assignments = {
            int(attacker_id): blocker_id
            for attacker_id, blocker_id in state["block_assignments"].items()
        }
        self.enraged_forced_attackers = set(state["enraged_forced_attackers"])
        self.pending_builder_creature = _deserialize_builder_creature(
            state["pending_builder_creature"]
        )
        self.pending_builder_ability = _deserialize_builder_ability(
            state["pending_builder_ability"]
        )
        self.pending_dice_battle = _deserialize_dice_battle(state["pending_dice_battle"])
        self.pending_dice_battles = [
            _deserialize_dice_battle(battle) for battle in state["pending_dice_battles"]
        ]
        self.pending_direct_attack = _deserialize_direct_attack(state["pending_direct_attack"])
        self.pending_direct_attacks = [
            _deserialize_direct_attack(attack) for attack in state["pending_direct_attacks"]
        ]
        self.combat_queue = list(state["combat_queue"])
        self.current_attack_index = state["current_attack_index"]
        self.blocked_attackers = set(state["blocked_attackers"])
        self.exit_requested = state["exit_requested"]
        self.pending_visual_events.clear()
        templates: dict[str, CardTemplate] = {}
        for player in self.players:
            for card in player.hand + player.discard_pile:
                if card.template.template_id != "network_hidden_card":
                    templates[card.template.template_id] = card.template
            for resource in player.resources:
                templates[resource.template.template_id] = resource.template
        for card in self.builder_shared_discard:
            templates[card.template.template_id] = card.template
        self.templates = templates
        self.snapshot_revision = snapshot.revision
        return True
