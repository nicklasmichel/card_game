from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.models import CardInstance, PlayerState, SpellEffect, SpellTargetRef


class AirCardHandler(Protocol):
    template_id: str

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None: ...

    def score_reaction(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int] | None: ...

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None: ...

    def play_value(
        self,
        ai,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> float | None: ...

    def has_live_use(
        self,
        ai,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> bool | None: ...

    def keep_adjustment(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> float | None: ...


@dataclass(slots=True)
class WindstossHandler:
    template_id: str = "air_spell_windstoss"

    def _get_open_die_owner(self, engine, target: SpellTargetRef):
        open_target = engine.open_die_targets.get(target.open_die_id)
        if open_target is None:
            return None
        player_id = open_target.get("player_id")
        if player_id is None:
            return None
        return engine.players[player_id]

    def _score_target(self, ai, player: PlayerState, engine, target: SpellTargetRef) -> float:
        die = engine.resolve_target_open_die(target)
        if die is None:
            return -999.0
        owner = self._get_open_die_owner(engine, target)
        if owner is None:
            return -999.0
        expected_shift = 10.5 - die.base_roll
        if owner.player_id != player.player_id:
            expected_shift = die.base_roll - 10.5

        battle = engine.pending_dice_battle
        comparison = getattr(battle, "pending_comparison", None) if battle is not None else None
        if comparison is not None and (die is comparison.attacker_die or die is comparison.blocker_die):
            attacker = engine.get_unit_by_id(battle.attacker_id)
            blocker = engine.get_unit_by_id(battle.blocker_id)
            if attacker is None or blocker is None:
                return expected_shift * 0.4
            own_is_attacker = battle.attacker_owner == player.player_id
            own_die = comparison.attacker_die if own_is_attacker else comparison.blocker_die
            enemy_die = comparison.blocker_die if own_is_attacker else comparison.attacker_die
            own_unit = attacker if own_is_attacker else blocker
            enemy_unit = blocker if own_is_attacker else attacker
            margin = own_die.total - enemy_die.total
            future_margin = margin + expected_shift if owner.player_id == player.player_id else margin - expected_shift
            current_loss = margin <= 0
            future_loss = future_margin <= 0
            score = expected_shift * 0.55
            if current_loss and not future_loss:
                score += 6.0 + ai._air_creature_board_value(own_unit) * 0.55
            if not current_loss and future_loss:
                score -= 5.0 + ai._air_creature_board_value(own_unit) * 0.45
            if current_loss:
                score += min(5.5, ai._air_creature_board_value(own_unit) * 0.35)
            if margin > 0 and die is enemy_die:
                score += min(3.0, expected_shift * 0.4)
            if margin <= 0 and die is own_die:
                score += min(3.5, (10.5 - die.base_roll) * 0.5)
            if own_unit.current_hp <= 1 and current_loss:
                score += 3.2
            if enemy_unit.current_hp <= 1 and margin > 0 and die is enemy_die:
                score += 1.2
            return score

        score = expected_shift * 0.35
        if owner.player_id == player.player_id and die.base_roll <= 4:
            score += 1.4
        if owner.player_id != player.player_id and die.base_roll >= 17:
            score += 1.4
        if owner.player_id == player.player_id and die.base_roll >= 14:
            score -= 2.4
        if owner.player_id != player.player_id and die.base_roll <= 7:
            score -= 2.1
        return score

    def best_target(self, ai, player: PlayerState, engine) -> tuple[SpellTargetRef | None, float]:
        candidates = engine.get_open_die_target_refs()
        if not candidates:
            return None, -999.0
        scored = [(self._score_target(ai, player, engine, target), target) for target in candidates]
        best_score, best_target = max(scored, key=lambda item: item[0])
        return best_target, best_score

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        _target, target_score = self.best_target(ai, player, engine)
        return (2 if target_score >= 2.0 else 1 if target_score >= 0.9 else 0, int(target_score * 10), 0)

    def score_reaction(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int] | None:
        _target, target_score = self.best_target(ai, player, engine)
        return (max(-4, int(target_score * 2)), 0)

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None:
        chosen, score = self.best_target(ai, player, engine)
        if chosen is None or score <= 0.65:
            return None
        return chosen

    def play_value(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        _target, score = self.best_target(ai, player, engine)
        return score

    def has_live_use(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> bool | None:
        return engine.has_valid_open_die_target()

    def keep_adjustment(self, ai, player: PlayerState, enemy: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        return 1.6 if engine.has_valid_open_die_target() else -1.8


@dataclass(slots=True)
class ComparisonRitualHandler:
    template_id: str
    comparison_method_name: str
    keep_positive: float
    keep_negative: float
    reaction_floor: int | None = None
    reaction_bonus_metric: str | None = None
    ritual_bonus_metric: str | None = None

    def _comparison(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> dict[str, Any]:
        method = getattr(ai, self.comparison_method_name)
        if self.comparison_method_name in {
            "_evaluate_air_cost_reduction_support_plan",
            "_evaluate_air_attack_bonus_support_plan",
            "_evaluate_air_windwechsel_plan",
            "_evaluate_air_sturmformation_plan",
            "_evaluate_air_turbulenz_plan",
        }:
            return method(
                player,
                engine,
                card,
                hand=kwargs["hand"],
                available_resources=kwargs["available_resources"],
                total_resources=kwargs["total_resources"],
                own_creature_count=kwargs["own_creature_count"],
                ready_attacker_count=kwargs["ready_attacker_count"],
                creature_discount=kwargs["creature_discount"],
            )
        if self.comparison_method_name == "_evaluate_air_nachwehen_plan":
            return method(
                player,
                engine,
                card,
                hand=kwargs["hand"],
                available_resources=kwargs["available_resources"],
                total_resources=kwargs["total_resources"],
            )
        if self.comparison_method_name in {
            "_evaluate_air_boeenschub_reaction_plan",
            "_evaluate_air_windrausch_reaction_plan",
        }:
            return method(player, engine, card)
        raise ValueError(f"Unsupported comparison method for air handler: {self.comparison_method_name}")

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        bonus = 0
        if self.ritual_bonus_metric is not None:
            metric = comparison.get(self.ritual_bonus_metric)
            bonus = 1 if metric else 0
        return (2 if comparison["is_useful"] else -2, int(comparison["value"] * 10), bonus)

    def score_reaction(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int] | None:
        if self.reaction_floor is None:
            return None
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        bonus = 0
        if self.reaction_bonus_metric is not None:
            metric = comparison.get(self.reaction_bonus_metric)
            if isinstance(metric, bool):
                bonus = 1 if metric else 0
            elif isinstance(metric, int):
                bonus = 1 if metric > 0 else 0
        return (max(self.reaction_floor, int(comparison["value"] * 2)), bonus)

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None:
        return None

    def play_value(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        return self._comparison(ai, player, engine, card, **kwargs)["value"]

    def has_live_use(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> bool | None:
        return self._comparison(ai, player, engine, card, **kwargs)["is_useful"]

    def keep_adjustment(self, ai, player: PlayerState, enemy: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        comparison = self._comparison(ai, player, engine, card, **kwargs)
        return self.keep_positive if comparison["is_useful"] else self.keep_negative


@dataclass(slots=True)
class RueckenwindHandler(ComparisonRitualHandler):
    template_id: str = "air_ritual_rueckenwind"
    comparison_method_name: str = "_evaluate_air_attack_bonus_support_plan"
    keep_positive: float = 2.4
    keep_negative: float = -2.4

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        return (
            2 if comparison["is_useful"] else -2,
            int(comparison["value"] * 10),
            1 if comparison.get("target_id") is not None else 0,
        )

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None:
        if ai._planned_rueckenwind_target_id is not None:
            chosen = next((creature for creature in player.battlefield if creature.unit_id == ai._planned_rueckenwind_target_id), None)
            if chosen is not None:
                return SpellTargetRef("creature", creature_id=chosen.unit_id)
        legal_target_ids = {creature.unit_id for creature in player.battlefield if creature.current_hp > 0}
        if not legal_target_ids:
            return None
        enemy = engine.players[1 - player.player_id]
        best_plan = ai._estimate_best_air_attack_plan(
            player,
            enemy,
            list(player.hand),
            [],
            attack_bonus_amount=card.template.spell_amount,
        )
        if best_plan["target_id"] is None or best_plan["target_id"] not in legal_target_ids:
            fallback_candidates = list(engine.available_attackers(player))
            if not fallback_candidates:
                fallback_candidates = [creature for creature in player.battlefield if creature.current_hp > 0]
            if not fallback_candidates:
                return None
            chosen = max(
                fallback_candidates,
                key=lambda creature: (
                    engine.get_creature_attack_value(creature),
                    1 if creature.has_ability(Ability.FLYING) else 0,
                    1 if creature.has_ability(Ability.HASTE) else 0,
                    creature.current_hp,
                ),
            )
            return SpellTargetRef("creature", creature_id=chosen.unit_id)
        return SpellTargetRef("creature", creature_id=best_plan["target_id"])


@dataclass(slots=True)
class BoeenschubHandler(ComparisonRitualHandler):
    template_id: str = "air_spell_boeenschub"
    comparison_method_name: str = "_evaluate_air_boeenschub_reaction_plan"
    keep_positive: float = 2.6
    keep_negative: float = -2.8
    reaction_floor: int = -4
    reaction_bonus_metric: str = "target_id"

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None:
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        if comparison["target_id"] is None or not comparison["is_useful"]:
            return None
        return SpellTargetRef("creature", creature_id=comparison["target_id"])


@dataclass(slots=True)
class WindrauschHandler(ComparisonRitualHandler):
    template_id: str = "air_spell_windrausch"
    comparison_method_name: str = "_evaluate_air_windrausch_reaction_plan"
    keep_positive: float = 2.4
    keep_negative: float = -2.8
    reaction_floor: int = -4
    reaction_bonus_metric: str = "is_lethal"

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        return (2 if comparison["is_useful"] else 0, int(comparison["value"] * 10), 1 if comparison["is_lethal"] else 0)


@dataclass(slots=True)
class NachwehenHandler(ComparisonRitualHandler):
    template_id: str = "air_spell_nachwehen"
    comparison_method_name: str = "_evaluate_air_nachwehen_plan"
    keep_positive: float = 2.3
    keep_negative: float = -3.0
    reaction_floor: int = -4
    reaction_bonus_metric: str = "draw_count"

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        return (2 if comparison["is_useful"] else 0, int(comparison["value"] * 10), 1 if comparison["draw_count"] >= 6 else 0)

    def score_reaction(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int] | None:
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        return (max(-4, int(comparison["value"] * 2)), 1 if comparison["draw_count"] >= 6 else 0)


@dataclass(slots=True)
class AusweichenHandler:
    template_id: str = "air_spell_ausweichen"

    def _comparison(self, ai, player: PlayerState, engine, card: CardInstance, *, hand, available_resources, total_resources) -> dict[str, Any]:
        return ai._evaluate_air_ausweichen_plan(
            player,
            engine,
            card,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        comparison = self._comparison(ai, player, engine, card, hand=list(player.hand), available_resources=player.available_resources(), total_resources=player.total_resources())
        return (2 if comparison["is_useful"] else -2, int(comparison["value"] * 10), 1 if comparison["recast_target"] else 0)

    def score_reaction(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int] | None:
        comparison = self._comparison(ai, player, engine, card, hand=list(player.hand), available_resources=player.available_resources(), total_resources=player.total_resources())
        return (max(-3, int(comparison["value"] * 2)), 1 if comparison["recast_target"] else 0)

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None:
        comparison = self._comparison(ai, player, engine, card, hand=list(player.hand), available_resources=player.available_resources(), total_resources=player.total_resources())
        if comparison["target_id"] is None or not comparison["is_useful"]:
            return None
        own_creature = engine.get_unit_by_id(comparison["target_id"])
        if own_creature is None:
            return None
        return SpellTargetRef("creature", creature_id=own_creature.unit_id)

    def play_value(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        comparison = self._comparison(ai, player, engine, card, hand=kwargs["hand"], available_resources=kwargs["available_resources"], total_resources=kwargs["total_resources"])
        return comparison["value"]

    def has_live_use(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> bool | None:
        comparison = self._comparison(ai, player, engine, card, hand=kwargs["hand"], available_resources=kwargs["available_resources"], total_resources=kwargs["total_resources"])
        return comparison["is_useful"]

    def keep_adjustment(self, ai, player: PlayerState, enemy: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        comparison = self._comparison(ai, player, engine, card, hand=kwargs["hand"], available_resources=kwargs["available_resources"], total_resources=kwargs["total_resources"])
        return 2.4 if comparison["is_useful"] else -3.0


@dataclass(slots=True)
class TurbulenzHandler(ComparisonRitualHandler):
    template_id: str = "air_ritual_turbulenz"
    comparison_method_name: str = "_evaluate_air_turbulenz_plan"
    keep_positive: float = 3.0
    keep_negative: float = -3.2

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        comparison = self._comparison(
            ai,
            player,
            engine,
            card,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            own_creature_count=len(player.battlefield),
            ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
            creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
        )
        return (
            2 if comparison["is_useful"] else -2,
            int(comparison["value"] * 10),
            1 if any(
                engine.get_unit_owner(target_id) == engine.human_player
                for target_id in comparison.get("target_ids", [])
                if engine.get_unit_by_id(target_id) is not None
            ) else 0,
        )

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None:
        if ai._planned_turbulenz_target_ids:
            selected_ids = {target.creature_id for target in pending.selected_targets if target.creature_id is not None}
            for target_id in ai._planned_turbulenz_target_ids:
                if target_id in selected_ids:
                    continue
                creature = engine.get_unit_by_id(target_id)
                if creature is not None:
                    return SpellTargetRef("creature", creature_id=creature.unit_id)
        enemy = engine.players[1 - player.player_id]
        selected_ids = {target.creature_id for target in pending.selected_targets if target.creature_id is not None}
        candidates = [creature for creature in player.battlefield + enemy.battlefield if creature.unit_id not in selected_ids]
        if not candidates:
            return None
        chosen = max(
            candidates,
            key=lambda creature: (
                1 if engine.get_unit_owner(creature.unit_id) == enemy else 0,
                creature.aw + creature.current_hp,
                creature.aw,
            ),
        )
        return SpellTargetRef("creature", creature_id=chosen.unit_id)


SPECIALIZED_AIR_HANDLERS: tuple[AirCardHandler, ...] = (
    ComparisonRitualHandler(
        template_id="air_ritual_aufwind",
        comparison_method_name="_evaluate_air_cost_reduction_support_plan",
        keep_positive=2.8,
        keep_negative=-3.2,
    ),
    RueckenwindHandler(),
    ComparisonRitualHandler(
        template_id="air_ritual_windwechsel",
        comparison_method_name="_evaluate_air_windwechsel_plan",
        keep_positive=2.3,
        keep_negative=-2.2,
    ),
    ComparisonRitualHandler(
        template_id="air_ritual_sturmformation",
        comparison_method_name="_evaluate_air_sturmformation_plan",
        keep_positive=2.8,
        keep_negative=-3.0,
    ),
    TurbulenzHandler(),
    WindstossHandler(),
    AusweichenHandler(),
    BoeenschubHandler(),
    WindrauschHandler(),
    NachwehenHandler(),
)
