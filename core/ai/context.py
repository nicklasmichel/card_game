from __future__ import annotations

from dataclasses import dataclass

from core.models import BattlefieldCreature, CardInstance, PlayerState, SpellTargetRef


@dataclass(slots=True)
class AIContext:
    player: PlayerState
    enemy: PlayerState
    phase: str
    reaction_trigger: str | None
    hand: tuple[CardInstance, ...]
    battlefield: tuple[BattlefieldCreature, ...]
    enemy_battlefield: tuple[BattlefieldCreature, ...]
    available_resources: int
    total_resources: int
    tapped_resource_ids: tuple[int, ...]
    creatures_died_this_turn: int
    open_die_targets: tuple[SpellTargetRef, ...]


def build_ai_context(engine, player: PlayerState) -> AIContext:
    enemy = engine.players[1 - player.player_id]
    trigger = None
    if getattr(engine, "reaction_context", None) is not None:
        trigger = engine.reaction_context.trigger.value
    return AIContext(
        player=player,
        enemy=enemy,
        phase=engine.phase,
        reaction_trigger=trigger,
        hand=tuple(player.hand),
        battlefield=tuple(player.battlefield),
        enemy_battlefield=tuple(enemy.battlefield),
        available_resources=player.available_resources(),
        total_resources=player.total_resources(),
        tapped_resource_ids=tuple(
            resource.resource_id
            for resource in player.resources
            if getattr(resource, "tapped", False) and resource.resource_id is not None
        ),
        creatures_died_this_turn=engine.creatures_died_this_turn,
        open_die_targets=tuple(engine.get_open_die_target_refs()) if hasattr(engine, "get_open_die_target_refs") else (),
    )
