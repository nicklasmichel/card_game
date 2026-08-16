from __future__ import annotations

from collections.abc import Iterable

from core.builder_rules import (
    BUILDER_CREATURE_CAP,
    BUILDER_MAX_RESOURCES,
    builder_creature_ability_set,
    calculate_builder_creature_cost,
    validate_builder_creature_abilities,
)
from core.models import Ability
from core.models import (
    PHASE_BUILDER_ABILITY,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
)


KNOWN_PHASES = frozenset(
    {
        PHASE_MAIN_1,
        PHASE_BUILDER_CREATURE,
        PHASE_BUILDER_ABILITY,
        PHASE_DECLARE_ATTACKERS,
        PHASE_DECLARE_BLOCKERS,
        PHASE_DICE_BATTLE,
        PHASE_GAME_OVER,
    }
)


class GameInvariantError(AssertionError):
    def __init__(self, violations: Iterable[str]) -> None:
        self.violations = tuple(violations)
        super().__init__("; ".join(self.violations))


def _append_duplicate_id_violations(violations: list[str], identifiers: list[tuple[int, str]]) -> None:
    owners: dict[int, list[str]] = {}
    for identifier, label in identifiers:
        owners.setdefault(identifier, []).append(label)
    for identifier, labels in owners.items():
        if len(labels) > 1:
            violations.append(f"duplicate object id {identifier}: {', '.join(labels)}")


def collect_game_invariant_violations(engine) -> list[str]:
    """Return violations of rules that must hold between completed game actions."""
    violations: list[str] = []
    players = list(getattr(engine, "players", ()))
    if len(players) != 2:
        return [f"expected exactly 2 players, found {len(players)}"]

    player_ids = [player.player_id for player in players]
    if set(player_ids) != {0, 1} or len(set(player_ids)) != 2:
        violations.append(f"player ids must be exactly 0 and 1, found {player_ids}")
    if getattr(engine, "active_player_index", -1) not in range(len(players)):
        violations.append(f"invalid active player index {getattr(engine, 'active_player_index', None)}")
    if getattr(engine, "phase", None) not in KNOWN_PHASES:
        violations.append(f"unknown phase {getattr(engine, 'phase', None)!r}")

    object_ids: list[tuple[int, str]] = []
    unit_owner: dict[int, object] = {}
    for player in players:
        total_resources = player.total_resources()
        available_resources = player.available_resources()
        if not 0 <= total_resources <= BUILDER_MAX_RESOURCES:
            violations.append(
                f"player {player.player_id} has {total_resources} resources; allowed range is 0..{BUILDER_MAX_RESOURCES}"
            )
        if not 0 <= available_resources <= total_resources:
            violations.append(
                f"player {player.player_id} has invalid ready resources {available_resources}/{total_resources}"
            )
        if len(player.battlefield) > BUILDER_CREATURE_CAP:
            violations.append(
                f"player {player.player_id} has {len(player.battlefield)} creatures; cap is {BUILDER_CREATURE_CAP}"
            )
        for resource in player.resources:
            object_ids.append((resource.resource_id, f"player {player.player_id} resource"))
        for creature in player.battlefield:
            unit_owner[creature.unit_id] = player
            object_ids.append((creature.unit_id, f"player {player.player_id} creature {creature.name}"))
            if min(creature.aw, creature.vw, creature.sw) < 0:
                violations.append(
                    f"creature {creature.unit_id} has negative combat stats {creature.aw}/{creature.vw}/{creature.sw}"
                )
            if creature.lw < 1:
                violations.append(f"creature {creature.unit_id} has invalid maximum life {creature.lw}")
            if not 1 <= creature.current_hp <= creature.lw:
                violations.append(
                    f"creature {creature.unit_id} has invalid current life {creature.current_hp}/{creature.lw}"
                )
            try:
                validated_abilities = validate_builder_creature_abilities(creature.abilities)
            except ValueError:
                violations.append(
                    f"creature {creature.unit_id} has invalid builder abilities {sorted(ability.name for ability in creature.abilities)!r}"
                )
            else:
                primary = next(ability for ability in validated_abilities if ability != Ability.HASTE)
                if creature.builder_ability != primary:
                    violations.append(
                        f"creature {creature.unit_id} primary ability does not match its ability set"
                    )
            expected_cost = calculate_builder_creature_cost(
                aw=creature.aw,
                vw=creature.vw,
                sw=creature.sw,
                lw=creature.lw,
                has_haste=Ability.HASTE in creature.abilities,
            )
            if creature.cost.resources != expected_cost:
                violations.append(
                    f"creature {creature.unit_id} costs {creature.cost.resources}; expected {expected_cost}"
                )
    _append_duplicate_id_violations(violations, object_ids)

    selected_attackers = list(getattr(engine, "selected_attackers", ()))
    if len(selected_attackers) != len(set(selected_attackers)):
        violations.append("selected attackers contain duplicates")
    if getattr(engine, "active_player_index", -1) in range(len(players)):
        active_player = engine.active_player
        defending_player = engine.defending_player
        if engine.phase in {PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS}:
            for attacker_id in selected_attackers:
                if unit_owner.get(attacker_id) is not active_player:
                    violations.append(f"selected attacker {attacker_id} is not controlled by the active player")
                elif engine.phase == PHASE_DECLARE_ATTACKERS and not engine.get_unit_by_id(attacker_id).is_ready():
                    violations.append(f"selected attacker {attacker_id} is not ready")

        assignments = dict(getattr(engine, "block_assignments", {}))
        blocker_ids = [blocker_id for blocker_id in assignments.values() if blocker_id is not None]
        if len(blocker_ids) != len(set(blocker_ids)):
            violations.append("a blocker is assigned to more than one attacker")
        if engine.phase == PHASE_DECLARE_BLOCKERS:
            for attacker_id, blocker_id in assignments.items():
                attacker = engine.get_unit_by_id(attacker_id)
                if attacker is None or unit_owner.get(attacker_id) is not active_player:
                    violations.append(f"block assignment references invalid attacker {attacker_id}")
                    continue
                if blocker_id is None:
                    continue
                blocker = engine.get_unit_by_id(blocker_id)
                if blocker is None or unit_owner.get(blocker_id) is not defending_player:
                    violations.append(f"block assignment references invalid blocker {blocker_id}")
                    continue
                if attacker_id in getattr(engine, "enraged_forced_attackers", set()):
                    legal = engine.can_creature_be_forced_to_block_attacker(blocker, attacker)
                else:
                    legal = engine.can_creature_block_attacker(blocker, attacker)
                if not legal:
                    violations.append(f"blocker {blocker_id} cannot legally block attacker {attacker_id}")

    if engine.phase == PHASE_DICE_BATTLE:
        pending_battles = list(getattr(engine, "pending_dice_battles", ()))
        if not pending_battles:
            violations.append("dice-combat phase has no pending battles")
        elif getattr(engine, "pending_dice_battle", None) not in pending_battles:
            violations.append("current dice battle is not part of the pending battle list")

    dead_players = [player for player in players if player.life <= 0]
    if engine.phase == PHASE_GAME_OVER and not dead_players:
        violations.append("game-over phase has no defeated player")
    if engine.phase != PHASE_GAME_OVER and dead_players:
        violations.append(
            "non-game-over state contains defeated player(s): "
            + ", ".join(str(player.player_id) for player in dead_players)
        )
    return violations


def validate_game_invariants(engine) -> None:
    violations = collect_game_invariant_violations(engine)
    if violations:
        raise GameInvariantError(violations)


def collect_prepared_action_violations(engine, action: object) -> list[str]:
    violations: list[str] = []
    if not isinstance(action, dict):
        return [f"prepared AI action must be a dict, found {type(action).__name__}"]
    kind = action.get("kind")
    phase = engine.phase

    allowed_by_phase = {
        PHASE_MAIN_1: {
            "builder_add_resource",
            "builder_create_creature",
            "builder_pass_main_action",
            "to_combat",
            "end_turn",
        },
        PHASE_BUILDER_ABILITY: {"builder_use_ability", "to_combat", "end_turn"},
        PHASE_DECLARE_ATTACKERS: {"declare_attackers"},
        PHASE_DECLARE_BLOCKERS: {"declare_blocks"},
    }
    if kind not in allowed_by_phase.get(phase, set()):
        return [f"action {kind!r} is not allowed in phase {phase!r}"]

    if kind == "builder_add_resource" and not engine.can_builder_add_resource(engine.active_player):
        violations.append("AI tried to add a resource when that action was illegal")
    elif kind == "builder_pass_main_action" and not engine.can_take_builder_main_action(engine.active_player):
        violations.append("AI tried to pass after its main action was no longer available")
    elif kind == "builder_create_creature":
        plan = action.get("plan")
        if not isinstance(plan, dict):
            violations.append("creature action has no valid plan")
        elif not engine.can_builder_open_creature_build(engine.active_player):
            violations.append("AI tried to build while the creature cap or phase disallowed it")
        else:
            try:
                aw = int(plan.get("aw"))
                vw = int(plan.get("vw"))
                sw = int(plan.get("sw"))
                lw = int(plan.get("lw"))
                cost = int(plan.get("cost"))
            except (TypeError, ValueError):
                violations.append("creature plan contains non-integer stats or cost")
            else:
                try:
                    abilities = frozenset(plan.get("abilities", ()))
                    if not abilities:
                        abilities = builder_creature_ability_set(
                            plan.get("ability"),
                            has_haste=bool(plan.get("haste", False)),
                        )
                    validate_builder_creature_abilities(abilities)
                except (TypeError, ValueError):
                    violations.append(f"creature plan has invalid abilities {plan.get('abilities')!r}")
                    abilities = frozenset()
                expected_cost = calculate_builder_creature_cost(
                    aw=aw,
                    vw=vw,
                    sw=sw,
                    lw=lw,
                    has_haste=Ability.HASTE in abilities,
                )
                if min(aw, vw, sw) < 0 or lw < 1:
                    violations.append(f"creature plan has invalid stats {aw}/{vw}/{sw}/{lw}")
                if cost != expected_cost:
                    violations.append(f"creature plan cost {cost} does not match expected cost {expected_cost}")
                if not 0 <= cost <= engine.active_player.available_resources():
                    violations.append(
                        f"creature plan costs {cost} with only {engine.active_player.available_resources()} ready resources"
                    )
    elif kind == "to_combat" and not engine.available_attackers(engine.active_player):
        violations.append("AI tried to enter combat without an available attacker")
    elif kind == "declare_attackers":
        attacker_ids = list(action.get("attacker_ids", ()))
        legal_ids = {creature.unit_id for creature in engine.available_attackers(engine.active_player)}
        if len(attacker_ids) != len(set(attacker_ids)):
            violations.append("AI declared the same attacker more than once")
        illegal_ids = sorted(set(attacker_ids) - legal_ids)
        if illegal_ids:
            violations.append(f"AI declared illegal attacker ids {illegal_ids}")
    elif kind == "declare_blocks":
        assignments = action.get("block_assignments")
        if not isinstance(assignments, dict):
            violations.append("block action has no assignment mapping")
        else:
            expected_attackers = set(engine.block_assignments)
            if set(assignments) != expected_attackers:
                violations.append(
                    f"block action covers attackers {sorted(assignments)} instead of {sorted(expected_attackers)}"
                )
            used: set[int] = set()
            for attacker_id, blocker_id in assignments.items():
                if blocker_id is None:
                    continue
                attacker = engine.get_unit_by_id(attacker_id)
                blocker = engine.get_unit_by_id(blocker_id)
                if attacker is None or engine.get_unit_owner(attacker_id) is not engine.active_player:
                    violations.append(f"block action references invalid attacker {attacker_id}")
                    continue
                if blocker is None or engine.get_unit_owner(blocker_id) is not engine.defending_player:
                    violations.append(f"block action references invalid blocker {blocker_id}")
                    continue
                if blocker_id in used:
                    violations.append(f"blocker {blocker_id} is assigned more than once")
                used.add(blocker_id)
                if attacker_id in getattr(engine, "enraged_forced_attackers", set()):
                    legal = engine.can_creature_be_forced_to_block_attacker(blocker, attacker)
                else:
                    legal = engine.can_creature_block_attacker(blocker, attacker)
                if not legal:
                    violations.append(f"blocker {blocker_id} cannot legally block attacker {attacker_id}")
    return violations


def validate_prepared_action(engine, action: object) -> None:
    violations = collect_prepared_action_violations(engine, action)
    if violations:
        raise GameInvariantError(violations)
