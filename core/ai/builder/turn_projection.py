from __future__ import annotations

from dataclasses import dataclass

from core.models import Ability, BattlefieldCreature, PlayerState

from .turn_types import BuilderTurnActionCandidate, ProjectedPlayerView, ProjectedUnitView
from .types import BuilderCreatureCandidate

SYNTHETIC_UNIT_BASE_ID = 1000000


@dataclass(frozen=True)
class BuilderTurnProjection:
    player_id: int
    enemy_id: int
    action_kind: str
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
        return [unit for unit in player.battlefield if unit.is_ready() and not unit.cannot_block and unit.vw > 0]

    def get_unit_by_id(self, unit_id: int):
        return self._unit_map.get(unit_id)

    def log(self, message: str) -> None:
        return


def build_current_turn_projection(player: PlayerState, engine) -> BuilderTurnProjection:
    enemy = engine.players[1 - player.player_id]
    own_units = tuple(_coerce_unit_view(creature) for creature in player.battlefield)
    enemy_units = tuple(_coerce_unit_view(creature) for creature in enemy.battlefield)
    state_signature = _build_state_signature(player, enemy, own_units, enemy_units)
    return BuilderTurnProjection(
        player_id=player.player_id,
        enemy_id=enemy.player_id,
        action_kind="current",
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
        state_signature=state_signature,
    )


def project_resource_action(base_projection: BuilderTurnProjection) -> BuilderTurnProjection:
    return BuilderTurnProjection(
        player_id=base_projection.player_id,
        enemy_id=base_projection.enemy_id,
        action_kind="resource",
        own_life=base_projection.own_life,
        enemy_life=base_projection.enemy_life,
        own_total_resources=base_projection.own_total_resources + 1,
        own_ready_resources=base_projection.own_ready_resources + 1,
        enemy_total_resources=base_projection.enemy_total_resources,
        enemy_ready_resources=base_projection.enemy_ready_resources,
        own_units=base_projection.own_units,
        enemy_units=base_projection.enemy_units,
        available_attacker_ids=base_projection.available_attacker_ids,
        hypothetical_unit_id=None,
        candidate_signature=("resource",),
        state_signature=base_projection.state_signature,
    )


def project_creature_action(
    base_projection: BuilderTurnProjection,
    action_candidate: BuilderTurnActionCandidate,
) -> BuilderTurnProjection:
    candidate = action_candidate.creature_candidate
    if candidate is None:
        raise ValueError("creature action requires a creature candidate")
    synthetic_id = synthetic_unit_id_for_candidate(candidate)
    is_haste = Ability.HASTE in candidate.abilities
    projected_unit = ProjectedUnitView(
        unit_id=synthetic_id,
        name="Projected Builder Creature",
        aw=candidate.aw,
        vw=candidate.vw,
        sw=candidate.sw,
        lw=candidate.lw,
        current_hp=candidate.lw,
        abilities=frozenset(candidate.abilities),
        tapped=not is_haste,
        summoning_sickness=not is_haste,
        cannot_block=False,
        debug_label="projected",
    )
    own_units = tuple(list(base_projection.own_units) + [projected_unit])
    available_attacker_ids = list(base_projection.available_attacker_ids)
    if projected_unit.is_ready():
        available_attacker_ids.append(projected_unit.unit_id)
    return BuilderTurnProjection(
        player_id=base_projection.player_id,
        enemy_id=base_projection.enemy_id,
        action_kind="creature",
        own_life=base_projection.own_life,
        enemy_life=base_projection.enemy_life,
        own_total_resources=base_projection.own_total_resources,
        own_ready_resources=max(0, base_projection.own_ready_resources - candidate.cost),
        enemy_total_resources=base_projection.enemy_total_resources,
        enemy_ready_resources=base_projection.enemy_ready_resources,
        own_units=own_units,
        enemy_units=base_projection.enemy_units,
        available_attacker_ids=tuple(sorted(available_attacker_ids)),
        hypothetical_unit_id=projected_unit.unit_id,
        candidate_signature=("creature",) + candidate.signature,
        state_signature=base_projection.state_signature,
    )


def synthetic_unit_id_for_candidate(candidate: BuilderCreatureCandidate) -> int:
    ability_mask = 0
    for bit, ability in enumerate(sorted(candidate.abilities, key=lambda item: item.value), start=1):
        ability_mask += bit * 7
    encoded = (
        candidate.aw * 10000
        + candidate.vw * 1000
        + candidate.sw * 100
        + candidate.lw * 10
        + ability_mask
    )
    return -(SYNTHETIC_UNIT_BASE_ID + encoded)


def _coerce_unit_view(creature: BattlefieldCreature) -> ProjectedUnitView:
    return ProjectedUnitView(
        unit_id=creature.unit_id,
        name=creature.name,
        aw=creature.aw,
        vw=creature.vw,
        sw=creature.sw,
        lw=creature.lw,
        current_hp=creature.current_hp,
        abilities=frozenset(creature.abilities),
        tapped=creature.tapped,
        summoning_sickness=creature.summoning_sick,
        cannot_block=getattr(creature, "cannot_block", False),
        debug_label=creature.name,
    )


def _build_state_signature(player, enemy, own_units: tuple[ProjectedUnitView, ...], enemy_units: tuple[ProjectedUnitView, ...]) -> tuple:
    return (
        player.player_id,
        player.life,
        enemy.life,
        player.total_resources(),
        player.available_resources(),
        enemy.total_resources(),
        enemy.available_resources(),
        tuple(_unit_signature(unit) for unit in own_units),
        tuple(_unit_signature(unit) for unit in enemy_units),
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
