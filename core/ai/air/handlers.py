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
class VerwirbelungHandler:
    template_id: str = "air_spell_verwirbelung"

    def _comparison(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> dict[str, Any]:
        return ai._evaluate_air_bounce_plan(
            player,
            engine,
            card,
            hand=kwargs["hand"],
            available_resources=kwargs["available_resources"],
            total_resources=kwargs["total_resources"],
        )

    def score_ritual(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int, int] | None:
        comparison = self._comparison(ai, player, engine, card, hand=list(player.hand), available_resources=player.available_resources(), total_resources=player.total_resources())
        return (2 if comparison["is_useful"] else -2, int(comparison["value"] * 10), 1 if len(comparison["target_ids"]) == 2 else 0)

    def score_reaction(self, ai, player: PlayerState, engine, card: CardInstance) -> tuple[int, int] | None:
        comparison = self._comparison(ai, player, engine, card, hand=list(player.hand), available_resources=player.available_resources(), total_resources=player.total_resources())
        return (max(-4, int(comparison["value"] * 2)), 1 if len(comparison["target_ids"]) == 2 else 0)

    def choose_target_ref(self, ai, player: PlayerState, engine, card: CardInstance, pending) -> SpellTargetRef | None:
        comparison = self._comparison(ai, player, engine, card, hand=list(player.hand), available_resources=player.available_resources(), total_resources=player.total_resources())
        if not comparison["is_useful"]:
            return None
        selected_ids = {target.creature_id for target in pending.selected_targets if target.creature_id is not None}
        for target_id in comparison["target_ids"]:
            if target_id in selected_ids:
                continue
            creature = engine.get_unit_by_id(target_id)
            if creature is not None:
                return SpellTargetRef("creature", creature_id=creature.unit_id)
        return None

    def play_value(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        return self._comparison(ai, player, engine, card, **kwargs)["value"]

    def has_live_use(self, ai, player: PlayerState, engine, card: CardInstance, **kwargs) -> bool | None:
        return self._comparison(ai, player, engine, card, **kwargs)["is_useful"]

    def keep_adjustment(self, ai, player: PlayerState, enemy: PlayerState, engine, card: CardInstance, **kwargs) -> float | None:
        comparison = self._comparison(ai, player, engine, card, **kwargs)
        return 2.1 if comparison["is_useful"] else -2.6


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
            "_evaluate_air_windruf_plan",
            "_evaluate_air_sturmruf_plan",
            "_evaluate_air_himmelswende_plan",
            "_evaluate_air_orkanwende_plan",
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
        if self.comparison_method_name == "_evaluate_air_global_attack_bonus_reaction_plan":
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
    comparison_method_name: str = "_evaluate_air_cost_reduction_support_plan"
    keep_positive: float = 2.4
    keep_negative: float = -2.4


@dataclass(slots=True)
class JagdwindHandler(ComparisonRitualHandler):
    template_id: str = "air_spell_jagdwind"
    comparison_method_name: str = "_evaluate_air_global_attack_bonus_reaction_plan"
    keep_positive: float = 2.6
    keep_negative: float = -2.8
    reaction_floor: int = -4
    reaction_bonus_metric: str = "is_lethal"


@dataclass(slots=True)
class SturmjagdHandler(ComparisonRitualHandler):
    template_id: str = "air_spell_sturmjagd"
    comparison_method_name: str = "_evaluate_air_global_attack_bonus_reaction_plan"
    keep_positive: float = 2.4
    keep_negative: float = -2.8
    reaction_floor: int = -4
    reaction_bonus_metric: str = "is_lethal"


@dataclass(slots=True)
class OrkanwendeHandler(ComparisonRitualHandler):
    template_id: str = "air_ritual_orkanwende"
    comparison_method_name: str = "_evaluate_air_orkanwende_plan"
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
class VerwehungHandler:
    template_id: str = "air_spell_verwehung"

    def _comparison(self, ai, player: PlayerState, engine, card: CardInstance, *, hand, available_resources, total_resources) -> dict[str, Any]:
        return ai._evaluate_air_verwehung_plan(
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
        target_creature = engine.get_unit_by_id(comparison["target_id"])
        if target_creature is None:
            return None
        return SpellTargetRef("creature", creature_id=target_creature.unit_id)

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
class HimmelswendeHandler(ComparisonRitualHandler):
    template_id: str = "air_ritual_himmelswende"
    comparison_method_name: str = "_evaluate_air_himmelswende_plan"
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
        return (2 if comparison["is_useful"] else -2, int(comparison["value"] * 10), 1 if comparison["draw_count"] >= 3 else 0)


SPECIALIZED_AIR_HANDLERS: tuple[AirCardHandler, ...] = (
    ComparisonRitualHandler(
        template_id="air_ritual_aufwind",
        comparison_method_name="_evaluate_air_cost_reduction_support_plan",
        keep_positive=2.8,
        keep_negative=-3.2,
    ),
    RueckenwindHandler(),
    ComparisonRitualHandler(
        template_id="air_ritual_windruf",
        comparison_method_name="_evaluate_air_windruf_plan",
        keep_positive=2.3,
        keep_negative=-2.2,
    ),
    ComparisonRitualHandler(
        template_id="air_ritual_sturmruf",
        comparison_method_name="_evaluate_air_sturmruf_plan",
        keep_positive=2.8,
        keep_negative=-3.0,
    ),
    HimmelswendeHandler(),
    VerwirbelungHandler(),
    VerwehungHandler(),
    JagdwindHandler(),
    SturmjagdHandler(),
    OrkanwendeHandler(),
)
