from __future__ import annotations

from random import Random

from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.ai.builder import choose_builder_attackers as choose_builder_attackers_v2
from core.ai.builder import choose_builder_creature_plan as choose_builder_creature_plan_v2
from core.ai.builder import choose_builder_main_action as choose_builder_main_action_v2
from core.ai.builder.turn_policy import choose_builder_turn_plan as choose_builder_turn_plan_v2
from core.models import Ability, BattlefieldCreature, PlayerState


class HeuristicStrategicAI:
    def __init__(self, rng: Random) -> None:
        self.rng = rng
        self._last_builder_attack_candidate = None
        self._last_builder_enraged_targets: dict[int, int] = {}

    def prepare_next_action(self, player, engine):
        return None

    def notify_action_resolved(self, action_type: str, *, card_instance_id: int | None = None) -> None:
        return None

    def reset_for_turn(self) -> None:
        self._last_builder_attack_candidate = None
        self._last_builder_enraged_targets = {}

    def choose_attackers_for_player(self, player, engine, creatures):
        return choose_builder_attackers_v2(player, engine)

    def choose_enraged_block_target(self, attacker: BattlefieldCreature, legal_targets, engine):
        if not legal_targets:
            return None
        planned_blocker_id = self._last_builder_enraged_targets.get(attacker.unit_id)
        if planned_blocker_id is not None:
            planned = next((blocker for blocker in legal_targets if blocker.unit_id == planned_blocker_id), None)
            if planned is not None:
                return planned

        def score(blocker: BattlefieldCreature) -> tuple[float, float, float, float, float]:
            attack_sum = max(0, engine.get_creature_attack_value(attacker)) * 3.5
            defense_sum = max(0, engine.get_creature_defense_value(blocker)) * 3.5
            likely_win = attack_sum - defense_sum
            lethal_value = 1.0 if attacker.sw >= blocker.current_hp else 0.0
            overflow_value = max(0, attacker.sw - blocker.current_hp) if attacker.has_ability(Ability.TRAMPLE) else 0
            threat_value = blocker.sw * 1.6 + blocker.current_hp * 0.4 + blocker.aw * 0.2
            return lethal_value, overflow_value, likely_win, threat_value, -blocker.current_hp

        best = max(legal_targets, key=score)
        if score(best)[0] <= 0.0 and score(best)[2] < -2.5 and score(best)[3] < 2.5:
            return None
        return best

    def choose_builder_main_action(self, player: PlayerState, engine) -> str:
        return choose_builder_main_action_v2(player, engine)

    def choose_builder_turn_plan(self, player: PlayerState, engine):
        return choose_builder_turn_plan_v2(player, engine)

    def choose_builder_creature_plan(self, player: PlayerState, engine) -> dict | None:
        return choose_builder_creature_plan_v2(player, engine)

    def choose_builder_runtime_main_action(self, player: PlayerState, engine) -> str:
        enemy = engine.players[1 - player.player_id]
        if len(player.battlefield) >= engine.BUILDER_CREATURE_CAP:
            return "resource" if engine.can_builder_add_resource(player) else "pass"
        if player.total_resources() < 3 and player.total_resources() < engine.BUILDER_MAX_RESOURCES:
            return "resource" if engine.can_builder_add_resource(player) else "creature"
        if not player.battlefield and enemy.battlefield and player.available_resources() >= 1:
            return "creature"
        if player.life <= enemy.life and player.available_resources() >= 1:
            return "creature"
        if player.total_resources() < 5 and len(player.battlefield) >= len(enemy.battlefield) and engine.can_builder_add_resource(player):
            return "resource"
        if player.available_resources() >= 1:
            return "creature"
        return "resource" if engine.can_builder_add_resource(player) else "pass"

    def choose_builder_runtime_creature_plan(self, player: PlayerState, engine) -> dict | None:
        budget = max(1, player.available_resources())
        enemy = engine.players[1 - player.player_id]
        aw = vw = sw = 0
        lw = 1
        if player.life <= 4 or len(player.battlefield) < len(enemy.battlefield):
            for index in range(budget):
                if index % 3 == 0:
                    vw += 1
                elif index % 3 == 1:
                    lw += 1
                else:
                    sw += 1
            aw = max(1, budget // 3)
            if aw + vw + sw + (lw - 1) > budget:
                vw = max(0, vw - 1)
        else:
            aw = max(1, budget // 3)
            sw = max(1, budget // 3)
            remaining = budget - aw - sw
            while remaining > 0:
                if vw <= lw - 1:
                    vw += 1
                else:
                    lw += 1
                remaining -= 1
        cost = aw + vw + sw + max(0, lw - 1)
        while cost > budget and lw > 1:
            lw -= 1
            cost = aw + vw + sw + max(0, lw - 1)
        while cost > budget and vw > 0:
            vw -= 1
            cost = aw + vw + sw + max(0, lw - 1)
        while cost > budget and aw > 1:
            aw -= 1
            cost = aw + vw + sw + max(0, lw - 1)
        while cost > budget and sw > 0:
            sw -= 1
            cost = aw + vw + sw + max(0, lw - 1)
        if cost <= 0:
            return None
        return {"aw": aw, "vw": vw, "sw": sw, "lw": lw, "cost": cost}

    def choose_builder_runtime_ability_action(self, player: PlayerState, engine) -> dict | None:
        if not BUILDER_ABILITIES_ENABLED or not player.hand:
            return None
        enemy = engine.players[1 - player.player_id]
        for card in list(player.hand):
            granted = engine.get_builder_card_ability(card)
            if granted is None:
                continue
            if granted == Ability.HASTE:
                candidates = [
                    creature
                    for creature in player.battlefield
                    if creature.unit_id in engine.builder_created_this_turn_ids
                    and engine._can_grant_builder_ability_to_creature(creature, granted)
                ]
                if candidates:
                    target = max(candidates, key=lambda creature: (creature.aw + creature.sw, creature.current_hp))
                    return {"card_id": card.instance_id, "mode": "grant_ability", "target_id": target.unit_id}
            candidates = [creature for creature in player.battlefield if engine._can_grant_builder_ability_to_creature(creature, granted)]
            if candidates and granted != Ability.HASTE:
                target = max(candidates, key=lambda creature: (creature.sw + creature.aw + creature.current_hp, len(creature.abilities)))
                return {"card_id": card.instance_id, "mode": "grant_ability", "target_id": target.unit_id}
            kill_target = next((creature for creature in enemy.battlefield if creature.current_hp <= 1), None)
            if kill_target is not None:
                return {"card_id": card.instance_id, "mode": "deal_damage", "target_id": kill_target.unit_id}
            if player.battlefield:
                target = max(player.battlefield, key=lambda creature: (creature.sw + creature.aw + creature.current_hp, len(creature.abilities)))
                stat = "sw" if target.sw <= target.aw else "aw"
                if player.life <= enemy.life and target.current_hp <= 2:
                    stat = "lw"
                return {"card_id": card.instance_id, "mode": "add_stat", "stat": stat, "target_id": target.unit_id}
        return None


StrategicAI = HeuristicStrategicAI
SimpleAI = HeuristicStrategicAI
