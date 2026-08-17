from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from core.builder_rules import BUILDER_ABILITIES_ENABLED, BUILDER_CREATURE_CAP, BUILDER_PRIMARY_ABILITIES
from core.models import Ability, BattlefieldCreature, PlayerState

from .turn_types import BuilderAbilityActionCandidate, BuilderTurnActionCandidate, ProjectedPlayerView, ProjectedUnitView
from .types import BuilderCreatureCandidate

SYNTHETIC_UNIT_BASE_ID = 1000000


def normalize_builder_abilities(abilities) -> frozenset[Ability]:
    return _normalize_builder_abilities_cached(frozenset(abilities))


@lru_cache(maxsize=128)
def _normalize_builder_abilities_cached(abilities: frozenset[Ability]) -> frozenset[Ability]:
    normalized = set(abilities)
    if Ability.LIFELINK in normalized:
        normalized.add(Ability.LIFE_STEAL)
    if Ability.LIFE_STEAL in normalized:
        normalized.add(Ability.LIFELINK)
    if Ability.VIGILANCE in normalized:
        normalized.add(Ability.VIGILANT)
    if Ability.VIGILANT in normalized:
        normalized.add(Ability.VIGILANCE)
    if Ability.PROVOKE in normalized:
        normalized.add(Ability.ENRAGED)
    if Ability.ENRAGED in normalized:
        normalized.add(Ability.PROVOKE)
    return frozenset(normalized)


@dataclass(frozen=True)
class BuilderTurnProjection:
    player_id: int
    enemy_id: int
    action_kind: str
    combat_die_sides: int
    own_life: int
    enemy_life: int
    own_total_resources: int
    own_ready_resources: int
    enemy_total_resources: int
    enemy_ready_resources: int
    own_units: tuple[ProjectedUnitView, ...]
    enemy_units: tuple[ProjectedUnitView, ...]
    available_attacker_ids: tuple[int, ...]
    hypothetical_unit_id: int | None
    candidate_signature: tuple
    state_signature: tuple
    builder_stalled_turns: int = 0
    builder_player_damage_stalled_turns: int = 0
    hand_signature: tuple = ()
    used_card_instance_id: int | None = None

    def __post_init__(self) -> None:
        own_player = ProjectedPlayerView(
            player_id=self.player_id,
            name=f"Player {self.player_id}",
            is_human=False,
            life=self.own_life,
            battlefield=self.own_units,
            ready_resources=self.own_ready_resources,
            total_resource_count=self.own_total_resources,
        )
        enemy_player = ProjectedPlayerView(
            player_id=self.enemy_id,
            name=f"Player {self.enemy_id}",
            is_human=False,
            life=self.enemy_life,
            battlefield=self.enemy_units,
            ready_resources=self.enemy_ready_resources,
            total_resource_count=self.enemy_total_resources,
        )
        unit_map = {unit.unit_id: unit for unit in self.own_units + self.enemy_units}
        players = [None, None]
        players[self.player_id] = own_player
        players[self.enemy_id] = enemy_player
        object.__setattr__(self, "players", tuple(players))
        object.__setattr__(self, "_unit_map", unit_map)
        object.__setattr__(self, "block_assignments", {})
        object.__setattr__(self, "enraged_forced_attackers", set())

    def available_attackers(self, player: ProjectedPlayerView) -> list[ProjectedUnitView]:
        if player.player_id != self.player_id:
            return [unit for unit in player.battlefield if unit.is_ready()]
        return [self._unit_map[unit_id] for unit_id in self.available_attacker_ids if unit_id in self._unit_map]

    def available_blockers(self, player: ProjectedPlayerView) -> list[ProjectedUnitView]:
        return [unit for unit in player.battlefield if not unit.tapped and not unit.cannot_block]

    def get_unit_by_id(self, unit_id: int):
        return self._unit_map.get(unit_id)

    def log(self, message: str) -> None:
        return


def build_current_turn_projection(player: PlayerState, engine) -> BuilderTurnProjection:
    enemy = engine.players[1 - player.player_id]
    own_units = tuple(_coerce_unit_view(creature) for creature in player.battlefield)
    enemy_units = tuple(_coerce_unit_view(creature) for creature in enemy.battlefield)
    hand_signature = ()
    if BUILDER_ABILITIES_ENABLED:
        hand_signature = tuple(sorted((card.instance_id, getattr(engine.get_builder_card_ability(card), "value", "")) for card in player.hand))
    return BuilderTurnProjection(
        player_id=player.player_id,
        enemy_id=enemy.player_id,
        action_kind="current",
        combat_die_sides=int(getattr(engine, "combat_die_sides", 6)),
        own_life=player.life,
        enemy_life=enemy.life,
        own_total_resources=player.total_resources(),
        own_ready_resources=player.available_resources(),
        enemy_total_resources=enemy.total_resources(),
        enemy_ready_resources=enemy.available_resources(),
        own_units=own_units,
        enemy_units=enemy_units,
        available_attacker_ids=tuple(unit.unit_id for unit in own_units if unit.is_ready()),
        hypothetical_unit_id=None,
        candidate_signature=("current",),
        state_signature=_build_state_signature(
            player.player_id,
            enemy.player_id,
            player.life,
            enemy.life,
            player.total_resources(),
            player.available_resources(),
            enemy.total_resources(),
            enemy.available_resources(),
            own_units,
            enemy_units,
            tuple(unit.unit_id for unit in own_units if unit.is_ready()),
            hand_signature,
            None,
        ),
        builder_stalled_turns=int(getattr(engine, "builder_stalled_turns", 0)),
        builder_player_damage_stalled_turns=int(
            getattr(engine, "builder_player_damage_stalled_turns", getattr(engine, "builder_stalled_turns", 0))
        ),
        hand_signature=hand_signature,
    )


def project_resource_action(base_projection: BuilderTurnProjection) -> BuilderTurnProjection:
    return _rebuild_projection(
        base_projection,
        action_kind="resource",
        own_total_resources=base_projection.own_total_resources + 1,
        own_ready_resources=base_projection.own_ready_resources + 1,
        candidate_signature=("resource",),
    )


def project_pass_action(base_projection: BuilderTurnProjection) -> BuilderTurnProjection:
    return _rebuild_projection(
        base_projection,
        action_kind="pass",
        candidate_signature=("pass",),
    )


def project_creature_action(
    base_projection: BuilderTurnProjection,
    action_candidate: BuilderTurnActionCandidate,
) -> BuilderTurnProjection:
    candidate = action_candidate.creature_candidate
    if candidate is None:
        raise ValueError("creature action requires a creature candidate")
    if len(base_projection.own_units) >= BUILDER_CREATURE_CAP:
        return _rebuild_projection(
            base_projection,
            action_kind="creature_cap_blocked",
            candidate_signature=base_projection.candidate_signature + ("cap_blocked",),
        )
    synthetic_id = synthetic_unit_id_for_candidate(candidate)
    projected_unit = ProjectedUnitView(
        unit_id=synthetic_id,
        name="Projected Builder Creature",
        aw=candidate.aw,
        vw=candidate.vw,
        sw=candidate.sw,
        lw=candidate.lw,
        current_hp=candidate.lw,
        abilities=normalize_builder_abilities(candidate.abilities),
        tapped=candidate.enters_tapped,
        summoning_sickness=candidate.enters_tapped,
        cannot_block=False,
        debug_label="projected",
    )
    own_units = tuple(list(base_projection.own_units) + [projected_unit])
    return _rebuild_projection(
        base_projection,
        action_kind="creature",
        own_units=own_units,
        own_ready_resources=max(0, base_projection.own_ready_resources - candidate.cost),
        hypothetical_unit_id=projected_unit.unit_id,
        candidate_signature=("creature",) + candidate.key,
    )


def project_ability_action(
    base_projection: BuilderTurnProjection,
    ability_action: BuilderAbilityActionCandidate,
) -> BuilderTurnProjection:
    if not BUILDER_ABILITIES_ENABLED:
        return _rebuild_projection(
            base_projection,
            action_kind=f"{base_projection.action_kind}:skip",
            candidate_signature=base_projection.candidate_signature + ("skip",),
            hand_signature=(),
            used_card_instance_id=None,
        )
    if ability_action.action_kind == "skip":
        return _rebuild_projection(
            base_projection,
            action_kind=f"{base_projection.action_kind}:skip",
            candidate_signature=base_projection.candidate_signature + ("skip",),
        )

    own_units = list(base_projection.own_units)
    enemy_units = list(base_projection.enemy_units)
    target = base_projection.get_unit_by_id(ability_action.target_id or -1)
    if target is None:
        return _rebuild_projection(base_projection, action_kind=f"{base_projection.action_kind}:invalid")

    def replace_target(updated: ProjectedUnitView) -> None:
        target_list = own_units if updated.unit_id in {unit.unit_id for unit in own_units} else enemy_units
        for index, unit in enumerate(target_list):
            if unit.unit_id == updated.unit_id:
                target_list[index] = updated
                return

    if ability_action.action_kind == "grant_ability" and ability_action.card_ability is not None:
        updated = ProjectedUnitView(
            unit_id=target.unit_id,
            name=target.name,
            aw=target.aw,
            vw=target.vw,
            sw=target.sw,
            lw=target.lw,
            current_hp=target.current_hp,
            abilities=normalize_builder_abilities(set(target.abilities) | {ability_action.card_ability}),
            tapped=False if ability_action.card_ability == Ability.HASTE else target.tapped,
            summoning_sickness=target.summoning_sickness,
            cannot_block=target.cannot_block,
            debug_label=target.debug_label,
        )
        replace_target(updated)
    elif ability_action.action_kind == "add_stat" and ability_action.selected_stat is not None:
        aw = target.aw + (1 if ability_action.selected_stat == "aw" else 0)
        vw = target.vw + (1 if ability_action.selected_stat == "vw" else 0)
        sw = target.sw + (1 if ability_action.selected_stat == "sw" else 0)
        lw = target.lw + (1 if ability_action.selected_stat == "lw" else 0)
        current_hp = target.current_hp + (1 if ability_action.selected_stat == "lw" else 0)
        updated = ProjectedUnitView(
            unit_id=target.unit_id,
            name=target.name,
            aw=aw,
            vw=vw,
            sw=sw,
            lw=lw,
            current_hp=current_hp,
            abilities=target.abilities,
            tapped=target.tapped,
            summoning_sickness=target.summoning_sickness,
            cannot_block=target.cannot_block,
            debug_label=target.debug_label,
        )
        replace_target(updated)
    elif ability_action.action_kind == "deal_damage":
        updated_hp = target.current_hp - 1
        if updated_hp > 0:
            updated = ProjectedUnitView(
                unit_id=target.unit_id,
                name=target.name,
                aw=target.aw,
                vw=target.vw,
                sw=target.sw,
                lw=target.lw,
                current_hp=updated_hp,
                abilities=target.abilities,
                tapped=target.tapped,
                summoning_sickness=target.summoning_sickness,
                cannot_block=target.cannot_block,
                debug_label=target.debug_label,
            )
            replace_target(updated)
        else:
            own_units = [unit for unit in own_units if unit.unit_id != target.unit_id]
            enemy_units = [unit for unit in enemy_units if unit.unit_id != target.unit_id]

    return _rebuild_projection(
        base_projection,
        action_kind=f"{base_projection.action_kind}:{ability_action.action_kind}",
        own_units=tuple(own_units),
        enemy_units=tuple(enemy_units),
        hand_signature=tuple(item for item in base_projection.hand_signature if item[0] != ability_action.card_instance_id),
        used_card_instance_id=ability_action.card_instance_id,
        candidate_signature=base_projection.candidate_signature + (
            ability_action.action_kind,
            ability_action.card_instance_id,
            ability_action.target_id,
            ability_action.selected_stat,
        ),
    )


def project_attack_to_next_turn(
    base_projection: BuilderTurnProjection,
    attacker_ids: tuple[int, ...],
    block_assignment: tuple[tuple[int, int], ...] = (),
) -> BuilderTurnProjection:
    from .combat_eval import estimate_unblocked_attack, project_builder_combat_outcome

    attacked_ids = set(attacker_ids)
    assignment_map = dict(block_assignment)
    attackers = {unit.unit_id: unit for unit in base_projection.own_units}
    blockers = {unit.unit_id: unit for unit in base_projection.enemy_units}
    post_hp: dict[int, int] = {}
    removed_attacker_ids: set[int] = set()
    removed_blocker_ids: set[int] = set()
    player_damage = 0.0

    for attacker_id, blocker_id in assignment_map.items():
        attacker = attackers.get(attacker_id)
        blocker = blockers.get(blocker_id)
        if attacker is None or blocker is None:
            continue
        outcome = project_builder_combat_outcome(attacker, blocker, base_projection.combat_die_sides)
        player_damage += outcome.player_damage

        if not outcome.attacker_survives:
            removed_attacker_ids.add(attacker_id)
        else:
            post_hp[attacker_id] = outcome.attacker_remaining_hp

        if not outcome.defender_survives:
            removed_blocker_ids.add(blocker_id)
        else:
            post_hp[blocker_id] = outcome.defender_remaining_hp

    for attacker_id in attacked_ids:
        if attacker_id in assignment_map or attacker_id in removed_attacker_ids:
            continue
        attacker = attackers.get(attacker_id)
        if attacker is None:
            continue
        unblocked = estimate_unblocked_attack(attacker)
        player_damage += unblocked.player_damage
        healed_hp = min(int(attacker.lw), int(attacker.current_hp) + int(round(unblocked.attacker_heal)))
        post_hp[attacker_id] = healed_hp

    next_active_units = tuple(
        _advance_unit_to_controller_turn_start(unit, current_hp=post_hp.get(unit.unit_id))
        for unit in base_projection.enemy_units
        if unit.unit_id not in removed_blocker_ids
    )
    next_inactive_units = tuple(
        _advance_attacker_unit_to_opponent_turn(
            unit,
            attacked=unit.unit_id in attacked_ids,
            current_hp=post_hp.get(unit.unit_id),
        )
        for unit in base_projection.own_units
        if unit.unit_id not in removed_attacker_ids
    )
    next_active_life = max(0.0, float(base_projection.enemy_life) - float(player_damage))
    made_progress = bool(removed_attacker_ids or removed_blocker_ids or player_damage > 0.0)
    return BuilderTurnProjection(
        player_id=base_projection.enemy_id,
        enemy_id=base_projection.player_id,
        action_kind=f"{base_projection.action_kind}:next_turn",
        combat_die_sides=base_projection.combat_die_sides,
        own_life=next_active_life,
        enemy_life=float(base_projection.own_life),
        own_total_resources=base_projection.enemy_total_resources,
        own_ready_resources=base_projection.enemy_total_resources,
        enemy_total_resources=base_projection.own_total_resources,
        enemy_ready_resources=base_projection.own_ready_resources,
        own_units=next_active_units,
        enemy_units=next_inactive_units,
        available_attacker_ids=tuple(unit.unit_id for unit in next_active_units if unit.is_ready()),
        hypothetical_unit_id=None,
        candidate_signature=base_projection.candidate_signature + ("next_turn", tuple(sorted(attacked_ids))),
        state_signature=_build_state_signature(
            base_projection.enemy_id,
            base_projection.player_id,
            next_active_life,
            float(base_projection.own_life),
            base_projection.enemy_total_resources,
            base_projection.enemy_total_resources,
            base_projection.own_total_resources,
            base_projection.own_ready_resources,
            next_active_units,
            next_inactive_units,
            tuple(unit.unit_id for unit in next_active_units if unit.is_ready()),
            (),
            None,
        ),
        builder_stalled_turns=(
            0
            if made_progress
            else max(0, int(base_projection.builder_stalled_turns) + 1)
        ),
        builder_player_damage_stalled_turns=(
            0
            if player_damage > 0.0
            else max(0, int(base_projection.builder_player_damage_stalled_turns) + 1)
        ),
    )


def synthetic_unit_id_for_candidate(candidate: BuilderCreatureCandidate) -> int:
    ability_index = 0
    if candidate.builder_ability in BUILDER_PRIMARY_ABILITIES:
        primary_index = BUILDER_PRIMARY_ABILITIES.index(candidate.builder_ability)
        ability_index = primary_index * 2 + (2 if candidate.has_haste else 1)
    encoded = (
        candidate.aw * 10000
        + candidate.vw * 1000
        + candidate.sw * 100
        + candidate.lw * 10
        + ability_index
    )
    return -(SYNTHETIC_UNIT_BASE_ID + encoded)


def _rebuild_projection(
    base_projection: BuilderTurnProjection,
    *,
    action_kind: str,
    own_total_resources: int | None = None,
    own_ready_resources: int | None = None,
    enemy_total_resources: int | None = None,
    enemy_ready_resources: int | None = None,
    own_units: tuple[ProjectedUnitView, ...] | None = None,
    enemy_units: tuple[ProjectedUnitView, ...] | None = None,
    available_attacker_ids: tuple[int, ...] | None = None,
    hypothetical_unit_id: int | None | object = ...,
    candidate_signature: tuple | None = None,
    hand_signature: tuple | None = None,
    used_card_instance_id: int | None | object = ...,
) -> BuilderTurnProjection:
    resolved_own_units = base_projection.own_units if own_units is None else own_units
    resolved_enemy_units = base_projection.enemy_units if enemy_units is None else enemy_units
    resolved_attackers = (
        tuple(unit.unit_id for unit in resolved_own_units if unit.is_ready())
        if available_attacker_ids is None
        else available_attacker_ids
    )
    resolved_hypothetical = base_projection.hypothetical_unit_id if hypothetical_unit_id is ... else hypothetical_unit_id
    resolved_hand = base_projection.hand_signature if hand_signature is None else hand_signature
    resolved_used_card = base_projection.used_card_instance_id if used_card_instance_id is ... else used_card_instance_id
    state_signature = _build_state_signature(
        base_projection.player_id,
        base_projection.enemy_id,
        base_projection.own_life,
        base_projection.enemy_life,
        base_projection.own_total_resources if own_total_resources is None else own_total_resources,
        base_projection.own_ready_resources if own_ready_resources is None else own_ready_resources,
        base_projection.enemy_total_resources if enemy_total_resources is None else enemy_total_resources,
        base_projection.enemy_ready_resources if enemy_ready_resources is None else enemy_ready_resources,
        resolved_own_units,
        resolved_enemy_units,
        resolved_attackers,
        resolved_hand,
        resolved_used_card,
    )
    return BuilderTurnProjection(
        player_id=base_projection.player_id,
        enemy_id=base_projection.enemy_id,
        action_kind=action_kind,
        combat_die_sides=base_projection.combat_die_sides,
        own_life=base_projection.own_life,
        enemy_life=base_projection.enemy_life,
        own_total_resources=base_projection.own_total_resources if own_total_resources is None else own_total_resources,
        own_ready_resources=base_projection.own_ready_resources if own_ready_resources is None else own_ready_resources,
        enemy_total_resources=base_projection.enemy_total_resources if enemy_total_resources is None else enemy_total_resources,
        enemy_ready_resources=base_projection.enemy_ready_resources if enemy_ready_resources is None else enemy_ready_resources,
        own_units=resolved_own_units,
        enemy_units=resolved_enemy_units,
        available_attacker_ids=resolved_attackers,
        hypothetical_unit_id=resolved_hypothetical,
        candidate_signature=base_projection.candidate_signature if candidate_signature is None else candidate_signature,
        state_signature=state_signature,
        builder_stalled_turns=base_projection.builder_stalled_turns,
        builder_player_damage_stalled_turns=base_projection.builder_player_damage_stalled_turns,
        hand_signature=resolved_hand,
        used_card_instance_id=resolved_used_card,
    )


def _coerce_unit_view(creature: BattlefieldCreature) -> ProjectedUnitView:
    return ProjectedUnitView(
        unit_id=creature.unit_id,
        name=creature.name,
        aw=creature.aw,
        vw=creature.vw,
        sw=creature.sw,
        lw=creature.lw,
        current_hp=creature.current_hp,
        abilities=normalize_builder_abilities(frozenset(creature.abilities)),
        tapped=creature.tapped,
        summoning_sickness=creature.summoning_sick,
        cannot_block=getattr(creature, "cannot_block", False),
        debug_label=creature.name,
    )


def _advance_unit_to_controller_turn_start(unit: ProjectedUnitView, *, current_hp: int | None = None) -> ProjectedUnitView:
    return ProjectedUnitView(
        unit_id=unit.unit_id,
        name=unit.name,
        aw=unit.aw,
        vw=unit.vw,
        sw=unit.sw,
        lw=unit.lw,
        current_hp=unit.current_hp if current_hp is None else current_hp,
        abilities=unit.abilities,
        tapped=False,
        summoning_sickness=False,
        cannot_block=unit.cannot_block,
        debug_label=unit.debug_label,
    )


def _advance_attacker_unit_to_opponent_turn(
    unit: ProjectedUnitView,
    *,
    attacked: bool,
    current_hp: int | None = None,
) -> ProjectedUnitView:
    remains_ready = unit.has_ability(Ability.VIGILANCE) or unit.has_ability(Ability.VIGILANT)
    return ProjectedUnitView(
        unit_id=unit.unit_id,
        name=unit.name,
        aw=unit.aw,
        vw=unit.vw,
        sw=unit.sw,
        lw=unit.lw,
        current_hp=unit.current_hp if current_hp is None else current_hp,
        abilities=unit.abilities,
        tapped=bool(unit.tapped or (attacked and not remains_ready)),
        summoning_sickness=unit.summoning_sickness,
        cannot_block=unit.cannot_block,
        debug_label=unit.debug_label,
    )


def _build_state_signature(
    player_id: int,
    enemy_id: int,
    own_life: int,
    enemy_life: int,
    own_total_resources: int,
    own_ready_resources: int,
    enemy_total_resources: int,
    enemy_ready_resources: int,
    own_units: tuple[ProjectedUnitView, ...],
    enemy_units: tuple[ProjectedUnitView, ...],
    available_attacker_ids: tuple[int, ...],
    hand_signature: tuple,
    used_card_instance_id: int | None,
) -> tuple:
    return (
        player_id,
        enemy_id,
        own_life,
        enemy_life,
        own_total_resources,
        own_ready_resources,
        enemy_total_resources,
        enemy_ready_resources,
        tuple(_unit_signature(unit) for unit in own_units),
        tuple(_unit_signature(unit) for unit in enemy_units),
        available_attacker_ids,
        hand_signature,
        used_card_instance_id,
    )


def _unit_signature(unit: ProjectedUnitView) -> tuple:
    return (
        unit.unit_id,
        unit.aw,
        unit.vw,
        unit.sw,
        unit.lw,
        unit.current_hp,
        unit.tapped,
        unit.summoning_sickness,
        tuple(sorted(ability.value for ability in unit.abilities)),
    )
