from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.models import Ability, CardInstance, CardType, PlayerState


class AirCreatureHandler(Protocol):
    template_id: str
    guideline: str

    def keep_adjustment(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        card: CardInstance,
        hand: list[CardInstance],
        *,
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> float: ...


@dataclass(frozen=True, slots=True)
class SimpleAirCreatureHandler:
    template_id: str
    guideline: str
    adjuster: callable

    def keep_adjustment(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        card: CardInstance,
        hand: list[CardInstance],
        *,
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> float:
        return self.adjuster(
            ai,
            player,
            enemy,
            card,
            hand,
            projected_available_resources=projected_available_resources,
            projected_total_resources=projected_total_resources,
        )


def _count_hand_or_board(player: PlayerState, hand: list[CardInstance], predicate) -> int:
    board_count = sum(1 for creature in player.battlefield if predicate(creature))
    hand_count = sum(1 for card in hand if predicate(card.template))
    return board_count + hand_count


def _has_probable_orkanreiter_support(player: PlayerState, hand: list[CardInstance]) -> bool:
    return _count_hand_or_board(
        player,
        hand,
        lambda unit: getattr(unit, "return_other_own_haste_on_combat_death", False),
    ) > 0


def _count_other_haste_sources(player: PlayerState, hand: list[CardInstance], current_card_id: int) -> int:
    board_haste = sum(1 for creature in player.battlefield if creature.has_ability(Ability.HASTE))
    hand_haste = sum(
        1
        for hand_card in hand
        if hand_card.instance_id != current_card_id
        and hand_card.template.card_type == CardType.CREATURE
        and hand_card.template.has_ability(Ability.HASTE)
    )
    return board_haste + hand_haste


def _count_other_fliers(player: PlayerState, hand: list[CardInstance], current_card_id: int) -> int:
    board_fliers = sum(1 for creature in player.battlefield if creature.has_ability(Ability.FLYING))
    hand_fliers = sum(
        1
        for hand_card in hand
        if hand_card.instance_id != current_card_id
        and hand_card.template.card_type == CardType.CREATURE
        and hand_card.template.has_ability(Ability.FLYING)
    )
    return board_fliers + hand_fliers


def _sturmkrieger(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    remaining_after_recycle = projected_total_resources - card.template.recycle_cost
    adjustment = 1.2 if ai._count_probable_attackers(player, hand) >= 3 else 0.3
    if remaining_after_recycle <= 1:
        adjustment -= 1.7
    if enemy.life <= max(2, ai._find_probable_unblocked_damage(player, enemy, hand)):
        adjustment += 1.0
    if _has_probable_orkanreiter_support(player, hand):
        adjustment += 0.5
    return adjustment


def _sturmfalke(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    adjustment = 1.8 if not any(creature.has_ability(Ability.FLYING) for creature in enemy.battlefield) else 0.9
    if any(hand_card.template.spell_effect.name == "DOUBLE_UNBLOCKED_ATTACK_DAMAGE" for hand_card in hand if hand_card.template.spell_effect is not None):
        adjustment += 1.4
    if projected_total_resources - card.template.recycle_cost <= 1:
        adjustment -= 1.8
    if _has_probable_orkanreiter_support(player, hand):
        adjustment += 0.4
    return adjustment


def _wolkenkrieger(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    if _has_probable_orkanreiter_support(player, hand):
        return 1.2
    dangerous_blocker = any(creature.aw >= card.template.vw for creature in enemy.battlefield if not creature.tapped)
    return -1.0 if dangerous_blocker and enemy.battlefield else 0.6


def _wolkenfalke(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    adjustment = 1.4 if not any(creature.has_ability(Ability.FLYING) for creature in enemy.battlefield) else 0.4
    if _count_hand_or_board(player, hand, lambda unit: getattr(unit, "own_flying_attack_aura", 0) > 0) > 0:
        adjustment += 0.8
    if any(hand_card.template.spell_effect.name == "DOUBLE_UNBLOCKED_ATTACK_DAMAGE" for hand_card in hand if hand_card.template.spell_effect is not None):
        adjustment += 0.8
    return adjustment


def _windkrieger(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    untapped_targets = [creature for creature in enemy.battlefield if not creature.tapped]
    if not untapped_targets:
        return 0.6
    best = max(untapped_targets, key=lambda creature: ai._air_creature_board_value(creature))
    return 1.2 + ai._air_creature_board_value(best) * 0.18


def _windfalke(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    adjustment = 0.9
    if enemy.battlefield:
        adjustment += 0.4
    if _count_hand_or_board(player, hand, lambda unit: getattr(unit, "own_flying_attack_aura", 0) > 0) > 0:
        adjustment += 0.4
    return adjustment


def _himmelskrieger(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    adjustment = 2.4
    if ai._count_probable_attackers(player, hand) >= 3:
        adjustment += 0.6
    if _has_probable_orkanreiter_support(player, hand):
        adjustment += 1.0
    return adjustment


def _himmelsfalke(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    adjustment = 2.1 if not any(creature.has_ability(Ability.FLYING) for creature in enemy.battlefield) else 0.8
    if _count_hand_or_board(player, hand, lambda unit: getattr(unit, "own_flying_attack_aura", 0) > 0) > 0:
        adjustment += 1.0
    if any(hand_card.template.spell_effect.name in {"GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN", "DOUBLE_UNBLOCKED_ATTACK_DAMAGE"} for hand_card in hand if hand_card.template.spell_effect is not None):
        adjustment += 0.9
    if projected_total_resources - card.template.recycle_cost <= 1:
        adjustment -= 1.0
    return adjustment


def _orkanreiter(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    haste_support = _count_other_haste_sources(player, hand, card.instance_id)
    if haste_support <= 0:
        return -1.4
    adjustment = 0.8 + haste_support * 1.1
    if any(
        hand_card.instance_id != card.instance_id
        and hand_card.template.template_id == "air_creature_himmelskrieger"
        for hand_card in hand
    ):
        adjustment += 1.0
    if projected_total_resources - card.template.recycle_cost <= 1:
        adjustment -= 1.4
    return adjustment


def _orkanfuerst(ai, player, enemy, card, hand, projected_available_resources: int, projected_total_resources: int) -> float:
    other_fliers = _count_other_fliers(player, hand, card.instance_id)
    adjustment = 0.5 + other_fliers * 1.35
    if any(hand_card.template.spell_effect.name == "DOUBLE_UNBLOCKED_ATTACK_DAMAGE" for hand_card in hand if hand_card.template.spell_effect is not None):
        adjustment += 0.8
    if projected_total_resources - card.template.recycle_cost <= 1 and other_fliers <= 1:
        adjustment -= 1.2
    return adjustment


SPECIALIZED_AIR_CREATURE_HANDLERS: tuple[AirCreatureHandler, ...] = (
    SimpleAirCreatureHandler(
        template_id="air_creature_sturmkrieger",
        guideline="Explosiver Schnell-Angreifer. Vor allem für dritten Angreifer, breiten Druck und klare Tempozüge nutzen; Recycle 1 bleibt ein echter Preis.",
        adjuster=_sturmkrieger,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_sturmfalke",
        guideline="Kostenloser Schnell-/Fliegend-Druck. Für ungeblockte Angriffe, Windrausch-Finisher und klare Tempofenster priorisieren; Recycle 2 nicht ohne echten Gewinn zahlen.",
        adjuster=_sturmfalke,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_wolkenkrieger",
        guideline="Fr?her Schnell-Angreifer mit Angriffspflicht. Nur ausspielen, wenn der n?chste Angriff nicht absehbar nutzlos ist.",
        adjuster=_wolkenkrieger,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_wolkenfalke",
        guideline="Reiner Offensiv-Flieger ohne Blockwert. Gegen fehlende Flugabwehr und mit Flieger-Synergien deutlich besser als in defensiven Lagen.",
        adjuster=_wolkenfalke,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_windkrieger",
        guideline="Tempo-Schnellangreifer mit ETB-Tap. Besonders gut, wenn ein echter Blocker oder Gegenangreifer aus dem Weg geraeumt wird.",
        adjuster=_windkrieger,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_windfalke",
        guideline="Kleiner Flieger mit Todes-Cantrip. Darf eher faire Kampftausche eingehen, ist aber nicht beliebig opferbar.",
        adjuster=_windfalke,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_himmelskrieger",
        guideline="Starker Tempo-Koerper ohne Kartenverlust. Sofortiger Druck und erneutes Ausspielen mit Orkanreiter sind sein Kern.",
        adjuster=_himmelskrieger,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_himmelsfalke",
        guideline="Wiederholbarer Kartenmotor über Spielerschaden. Besonders wertvoll, wenn realistisch ungeblockt getroffen wird.",
        adjuster=_himmelsfalke,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_orkanreiter",
        guideline="Schnell-Synergiezentrum. Erst stark mit mehreren anderen schnellen Kreaturen oder konkreten Rueckhol-Linien.",
        adjuster=_orkanreiter,
    ),
    SimpleAirCreatureHandler(
        template_id="air_creature_orkanfuerst",
        guideline="Flieger-Aura für breite Luftangriffe. Der Einsatz steigt deutlich mit jedem weiteren eigenen Flieger.",
        adjuster=_orkanfuerst,
    ),
)
