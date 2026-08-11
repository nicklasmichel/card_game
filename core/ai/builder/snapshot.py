from __future__ import annotations

from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.models import Ability, PlayerState

from .scoring import estimate_creature_board_value
from .types import BuilderStrategicSnapshot


def build_builder_snapshot(player: PlayerState, engine) -> BuilderStrategicSnapshot:
    enemy = engine.players[1 - player.player_id]
    own_creatures = list(player.battlefield)
    enemy_creatures = list(enemy.battlefield)

    own_board_value = sum(estimate_creature_board_value(creature) for creature in own_creatures)
    enemy_board_value = sum(estimate_creature_board_value(creature) for creature in enemy_creatures)

    own_total_aw = sum(creature.aw for creature in own_creatures)
    own_total_vw = sum(creature.vw for creature in own_creatures)
    own_total_sw = sum(creature.sw for creature in own_creatures)
    own_total_current_hp = sum(creature.current_hp for creature in own_creatures)
    enemy_total_aw = sum(creature.aw for creature in enemy_creatures)
    enemy_total_vw = sum(creature.vw for creature in enemy_creatures)
    enemy_total_sw = sum(creature.sw for creature in enemy_creatures)
    enemy_total_current_hp = sum(creature.current_hp for creature in enemy_creatures)

    own_flying_count = sum(1 for creature in own_creatures if creature.has_ability(Ability.FLYING))
    enemy_flying_count = sum(1 for creature in enemy_creatures if creature.has_ability(Ability.FLYING))
    own_ready_attacker_count = len(engine.available_attackers(player))
    enemy_potential_attacker_count = len(engine.available_attackers(enemy))

    own_hand_count = 0
    enemy_hand_count = 0
    if BUILDER_ABILITIES_ENABLED:
        own_hand_count = len(getattr(player, "hand", ()))
        enemy_hand_count = len(getattr(enemy, "hand", ()))
        if not hasattr(player, "hand") and hasattr(engine, "hand_signature") and getattr(engine, "player_id", None) == player.player_id:
            own_hand_count = len(engine.hand_signature)
        if not hasattr(enemy, "hand") and hasattr(engine, "hand_signature") and getattr(engine, "player_id", None) == enemy.player_id:
            enemy_hand_count = len(engine.hand_signature)

    return BuilderStrategicSnapshot(
        own_life=player.life,
        enemy_life=enemy.life,
        own_total_resources=player.total_resources(),
        own_ready_resources=player.available_resources(),
        enemy_total_resources=enemy.total_resources(),
        enemy_ready_resources=enemy.available_resources(),
        own_hand_count=own_hand_count,
        enemy_hand_count=enemy_hand_count,
        own_creature_count=len(own_creatures),
        enemy_creature_count=len(enemy_creatures),
        own_board_value=round(own_board_value, 3),
        enemy_board_value=round(enemy_board_value, 3),
        own_total_aw=own_total_aw,
        own_total_vw=own_total_vw,
        own_total_sw=own_total_sw,
        own_total_current_hp=own_total_current_hp,
        enemy_total_aw=enemy_total_aw,
        enemy_total_vw=enemy_total_vw,
        enemy_total_sw=enemy_total_sw,
        enemy_total_current_hp=enemy_total_current_hp,
        own_flying_count=own_flying_count,
        enemy_flying_count=enemy_flying_count,
        own_ready_attacker_count=own_ready_attacker_count,
        enemy_potential_attacker_count=enemy_potential_attacker_count,
        own_has_board=bool(own_creatures),
        enemy_has_board=bool(enemy_creatures),
        life_difference=player.life - enemy.life,
        resource_difference=player.total_resources() - enemy.total_resources(),
        board_value_difference=round(own_board_value - enemy_board_value, 3),
    )
