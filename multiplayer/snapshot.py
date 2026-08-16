from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from core.models import PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS


SNAPSHOT_VERSION = 2


class SnapshotValidationError(ValueError):
    """Raised when a game-state snapshot is malformed or corrupted."""


def _new_snapshot_id() -> str:
    return uuid4().hex


def _validate_json_value(value: Any, label: str) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SnapshotValidationError(f"{label} contains a non-finite number.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SnapshotValidationError(f"{label} contains a non-string key.")
            _validate_json_value(item, f"{label}.{key}")
        return
    raise SnapshotValidationError(f"{label} contains a non-JSON value: {type(value).__name__}.")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _state_hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(state).encode("utf-8")).hexdigest()


def _serialize_cost(cost) -> dict[str, int]:
    return {"resources": cost.resources, "recycle": cost.recycle}


def _serialize_template(template) -> dict[str, Any]:
    return {
        "template_id": template.template_id,
        "name": template.name,
        "cost": _serialize_cost(template.cost),
        "aw": template.aw,
        "vw": template.vw,
        "lw": template.lw,
        "sw": template.sw,
        "element": template.element.name,
        "abilities": sorted(ability.name for ability in template.abilities),
        "builder_ability": template.builder_ability.name if template.builder_ability else None,
        "card_type": template.card_type.name,
        "rules_text": template.rules_text,
        "return_to_deck_end_of_turn": template.return_to_deck_end_of_turn,
        "cannot_block": template.cannot_block,
        "must_attack_each_turn": template.must_attack_each_turn,
        "all_attackers_die_bonus": template.all_attackers_die_bonus,
        "allow_zero_stats": template.allow_zero_stats,
        "draw_on_attack": template.draw_on_attack,
        "draw_on_death": template.draw_on_death,
        "draw_on_player_damage": template.draw_on_player_damage,
        "tap_enemy_creature_on_play": template.tap_enemy_creature_on_play,
        "return_other_own_haste_on_combat_death": template.return_other_own_haste_on_combat_death,
        "own_flying_attack_aura": template.own_flying_attack_aura,
    }


def _serialize_card(card) -> dict[str, Any]:
    return {
        "instance_id": card.instance_id,
        "template": _serialize_template(card.template),
        "was_recycled": card.was_recycled,
    }


def _serialize_resource(resource) -> dict[str, Any]:
    return {
        "resource_id": resource.resource_id,
        "tapped": resource.tapped,
        "template": _serialize_template(resource.template),
    }


def _serialize_creature(creature) -> dict[str, Any]:
    return {
        "unit_id": creature.unit_id,
        "template_id": creature.template_id,
        "name": creature.name,
        "cost": _serialize_cost(creature.cost),
        "aw": creature.aw,
        "vw": creature.vw,
        "lw": creature.lw,
        "sw": creature.sw,
        "element": creature.element.name,
        "abilities": sorted(ability.name for ability in creature.abilities),
        "builder_ability": creature.builder_ability.name if creature.builder_ability else None,
        "rules_text": creature.rules_text,
        "return_to_deck_end_of_turn": creature.return_to_deck_end_of_turn,
        "cannot_block": creature.cannot_block,
        "must_attack_each_turn": creature.must_attack_each_turn,
        "all_attackers_die_bonus": creature.all_attackers_die_bonus,
        "draw_on_attack": creature.draw_on_attack,
        "draw_on_death": creature.draw_on_death,
        "draw_on_player_damage": creature.draw_on_player_damage,
        "tap_enemy_creature_on_play": creature.tap_enemy_creature_on_play,
        "return_other_own_haste_on_combat_death": creature.return_other_own_haste_on_combat_death,
        "own_flying_attack_aura": creature.own_flying_attack_aura,
        "current_hp": creature.current_hp,
        "temporary_aw_bonus": creature.temporary_aw_bonus,
        "temporary_combat_aw_bonus": creature.temporary_combat_aw_bonus,
        "temporary_combat_sw_bonus": creature.temporary_combat_sw_bonus,
        "temporary_abilities": sorted(ability.name for ability in creature.temporary_abilities),
        "tapped": creature.tapped,
        "summoning_sick": creature.summoning_sick,
    }


def _serialize_player(player, *, reveal_hand: bool) -> dict[str, Any]:
    return {
        "player_id": player.player_id,
        "name": player.name,
        "controller_kind": player.controller_kind.value,
        "summoner_key": player.summoner_key,
        "life": player.life,
        "deck_count": len(player.deck),
        "hand_count": len(player.hand),
        "hand_cards": [_serialize_card(card) for card in player.hand] if reveal_hand else None,
        "discard_pile": [_serialize_card(card) for card in player.discard_pile],
        "battlefield": [_serialize_creature(creature) for creature in player.battlefield],
        "resources": [_serialize_resource(resource) for resource in player.resources],
        "resources_played_this_turn": player.resources_played_this_turn,
        "main_action_used_this_turn": player.main_action_used_this_turn,
        "summoner_passive_draw_used_this_turn": player.summoner_passive_draw_used_this_turn,
        "creature_cost_reduction_this_turn": player.creature_cost_reduction_this_turn,
        "summoner_tapped": player.summoner_tapped,
        "turns_started": player.turns_started,
        "mulligan_used": player.mulligan_used,
    }


def _serialize_builder_creature(pending) -> dict[str, Any] | None:
    if pending is None:
        return None
    return {
        "base_aw": pending.base_aw,
        "base_vw": pending.base_vw,
        "base_sw": pending.base_sw,
        "base_lw": pending.base_lw,
        "aw": pending.aw,
        "vw": pending.vw,
        "sw": pending.sw,
        "lw": pending.lw,
        "available_resources": pending.available_resources,
        "selected_ability": pending.selected_ability.name if pending.selected_ability else None,
    }


def _serialize_builder_ability(pending) -> dict[str, Any] | None:
    if pending is None:
        return None
    return {
        "card_instance_id": pending.card_instance_id,
        "mode": pending.mode,
        "selected_target_id": pending.selected_target_id,
        "selected_stat": pending.selected_stat,
    }


def _serialize_combat_unit(unit) -> dict[str, Any]:
    return {
        "unit_id": unit.unit_id,
        "template_id": unit.template_id,
        "name": unit.name,
        "cost": _serialize_cost(unit.cost),
        "aw": unit.aw,
        "vw": unit.vw,
        "lw": unit.lw,
        "sw": unit.sw,
        "current_hp": unit.current_hp,
        "element": unit.element.name,
        "abilities": sorted(ability.name for ability in unit.abilities),
        "rules_text": unit.rules_text,
        "tapped": unit.tapped,
    }


def _serialize_dice_round(round_record) -> dict[str, Any]:
    return {
        "round_number": round_record.round_number,
        "attacker_rolls": list(round_record.attacker_rolls),
        "blocker_rolls": list(round_record.blocker_rolls),
        "attack_sum": round_record.attack_sum,
        "defense_sum": round_record.defense_sum,
        "outcome_text": round_record.outcome_text,
    }


def _serialize_dice_battle(battle) -> dict[str, Any] | None:
    if battle is None:
        return None
    return {
        "attacker_id": battle.attacker_id,
        "blocker_id": battle.blocker_id,
        "attacker_owner": battle.attacker_owner,
        "blocker_owner": battle.blocker_owner,
        "attacker_snapshot": _serialize_combat_unit(battle.attacker_snapshot),
        "blocker_snapshot": _serialize_combat_unit(battle.blocker_snapshot),
        "attacker_rolls": list(battle.attacker_rolls),
        "blocker_rolls": list(battle.blocker_rolls),
        "attack_sum": battle.attack_sum,
        "defense_sum": battle.defense_sum,
        "reroll_count": battle.reroll_count,
        "winner": battle.winner,
        "creature_damage": battle.creature_damage,
        "trample_damage": battle.trample_damage,
        "history": [_serialize_dice_round(record) for record in battle.history],
        "resolution_complete": battle.resolution_complete,
        "result_applied": battle.result_applied,
        "attacker_hp_after": battle.attacker_hp_after,
        "blocker_hp_after": battle.blocker_hp_after,
        "resolution_log": battle.resolution_log,
    }


def _serialize_direct_attack(attack) -> dict[str, Any] | None:
    if attack is None:
        return None
    return {
        "attacker_id": attack.attacker_id,
        "attacker_owner": attack.attacker_owner,
        "defending_player_id": attack.defending_player_id,
        "base_damage": attack.base_damage,
    }


def _visible_block_assignments(engine, viewer_player_id: int | None, reveal_all: bool) -> dict[str, int | None]:
    assignments = engine.block_assignments
    if (
        not reveal_all
        and engine.phase == PHASE_DECLARE_BLOCKERS
        and viewer_player_id == engine.active_player.player_id
    ):
        assignments = {
            attacker_id: blocker_id
            for attacker_id, blocker_id in assignments.items()
            if attacker_id in engine.enraged_forced_attackers
        }
    return {str(attacker_id): blocker_id for attacker_id, blocker_id in assignments.items()}


def build_snapshot_state(
    engine,
    viewer_player_id: int | None,
    *,
    reveal_all: bool = False,
) -> dict[str, Any]:
    if not reveal_all and viewer_player_id not in {player.player_id for player in engine.players}:
        raise ValueError(f"Unknown viewer_player_id: {viewer_player_id}")
    active_player_id = engine.active_player.player_id
    defending_player_id = engine.defending_player.player_id
    viewer_is_active = reveal_all or viewer_player_id == active_player_id
    viewer_is_defending = reveal_all or viewer_player_id == defending_player_id
    selected_attackers = list(engine.selected_attackers)
    if not reveal_all and engine.phase == PHASE_DECLARE_ATTACKERS and not viewer_is_active:
        selected_attackers = []
    return {
        "game_id": engine.game_id,
        "match_mode": engine.match_mode.value,
        "turn_number": engine.turn_number,
        "phase": engine.phase,
        "active_player_id": active_player_id,
        "defending_player_id": defending_player_id,
        "starting_player_id": engine.starting_player_id,
        "game_over_text": engine.game_over_text,
        "players": [
            _serialize_player(
                player,
                reveal_hand=reveal_all or player.player_id == viewer_player_id,
            )
            for player in engine.players
        ],
        "builder_shared_deck_count": len(engine.builder_shared_deck),
        "builder_shared_discard": [_serialize_card(card) for card in engine.builder_shared_discard],
        "builder_ability_used_this_turn": engine.builder_ability_used_this_turn,
        "selected_hand_ids": list(engine.selected_hand_ids) if viewer_is_active else [],
        "selected_attackers": selected_attackers,
        "selected_blocker_id": engine.selected_blocker_id if viewer_is_defending else None,
        "selected_attack_target_id": engine.selected_attack_target_id if viewer_is_active else None,
        "block_assignments": _visible_block_assignments(engine, viewer_player_id, reveal_all),
        "enraged_forced_attackers": sorted(engine.enraged_forced_attackers),
        "pending_builder_creature": (
            _serialize_builder_creature(engine.pending_builder_creature) if viewer_is_active else None
        ),
        "pending_builder_ability": (
            _serialize_builder_ability(engine.pending_builder_ability) if viewer_is_active else None
        ),
        "pending_dice_battle": _serialize_dice_battle(engine.pending_dice_battle),
        "pending_dice_battles": [
            _serialize_dice_battle(battle) for battle in engine.pending_dice_battles
        ],
        "pending_direct_attack": _serialize_direct_attack(engine.pending_direct_attack),
        "pending_direct_attacks": [
            _serialize_direct_attack(attack) for attack in engine.pending_direct_attacks
        ],
        "combat_queue": list(engine.combat_queue),
        "current_attack_index": engine.current_attack_index,
        "blocked_attackers": sorted(engine.blocked_attackers),
        "exit_requested": engine.exit_requested,
        "public_log_messages": list(getattr(engine, "public_log_messages", [])),
    }


def authoritative_state_hash(engine) -> str:
    return _state_hash(build_snapshot_state(engine, None, reveal_all=True))


@dataclass(frozen=True, slots=True)
class GameStateSnapshot:
    revision: int
    viewer_player_id: int
    state: dict[str, Any]
    snapshot_id: str = field(default_factory=_new_snapshot_id)
    version: int = SNAPSHOT_VERSION
    state_hash: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise SnapshotValidationError("revision must be an integer >= 0.")
        if (
            isinstance(self.viewer_player_id, bool)
            or not isinstance(self.viewer_player_id, int)
            or self.viewer_player_id < 0
        ):
            raise SnapshotValidationError("viewer_player_id must be an integer >= 0.")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id.strip():
            raise SnapshotValidationError("snapshot_id must be a non-empty string.")
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise SnapshotValidationError("version must be an integer.")
        if self.version != SNAPSHOT_VERSION:
            raise SnapshotValidationError(
                f"Unsupported snapshot version {self.version}; expected {SNAPSHOT_VERSION}."
            )
        if not isinstance(self.state, dict):
            raise SnapshotValidationError("state must be a JSON object.")
        state = dict(self.state)
        _validate_json_value(state, "state")
        players = state.get("players")
        if not isinstance(players, list) or not players:
            raise SnapshotValidationError("state.players must be a non-empty list.")
        viewer = next(
            (
                player
                for player in players
                if isinstance(player, dict) and player.get("player_id") == self.viewer_player_id
            ),
            None,
        )
        if viewer is None:
            raise SnapshotValidationError("viewer_player_id is not present in state.players.")
        for player in players:
            if not isinstance(player, dict):
                raise SnapshotValidationError("Every state.players entry must be an object.")
            hand_cards = player.get("hand_cards")
            if player is viewer:
                if not isinstance(hand_cards, list):
                    raise SnapshotValidationError("The viewer hand must be visible.")
            elif hand_cards is not None:
                raise SnapshotValidationError("An opponent hand must be hidden.")
        expected_hash = _state_hash(state)
        if self.state_hash and self.state_hash != expected_hash:
            raise SnapshotValidationError("Snapshot state_hash does not match its state.")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "state_hash", expected_hash)

    @classmethod
    def from_engine(cls, engine, viewer_player_id: int, revision: int) -> GameStateSnapshot:
        return cls(
            revision=revision,
            viewer_player_id=viewer_player_id,
            state=build_snapshot_state(engine, viewer_player_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_type": "game_state_snapshot",
            "version": self.version,
            "snapshot_id": self.snapshot_id,
            "revision": self.revision,
            "viewer_player_id": self.viewer_player_id,
            "state_hash": self.state_hash,
            "state": self.state,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameStateSnapshot:
        if not isinstance(data, dict):
            raise SnapshotValidationError("Snapshot must be a JSON object.")
        expected_fields = {
            "message_type",
            "version",
            "snapshot_id",
            "revision",
            "viewer_player_id",
            "state_hash",
            "state",
        }
        if set(data) != expected_fields:
            raise SnapshotValidationError("Snapshot fields do not match the schema.")
        if data["message_type"] != "game_state_snapshot":
            raise SnapshotValidationError("Invalid snapshot message_type.")
        state_hash = data["state_hash"]
        if not isinstance(state_hash, str) or len(state_hash) != 64:
            raise SnapshotValidationError("Snapshot state_hash must be a SHA-256 hex digest.")
        return cls(
            revision=data["revision"],
            viewer_player_id=data["viewer_player_id"],
            state=data["state"],
            snapshot_id=data["snapshot_id"],
            version=data["version"],
            state_hash=state_hash,
        )

    @classmethod
    def from_json(cls, raw: str) -> GameStateSnapshot:
        if not isinstance(raw, str):
            raise SnapshotValidationError("Snapshot wire message must be text.")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SnapshotValidationError("Snapshot is not valid JSON.") from exc
        return cls.from_dict(data)
