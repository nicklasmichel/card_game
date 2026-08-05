from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.models import CardInstance, PlayerState


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
class GenericAirCreatureHandler:
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
    ) -> float:
        return ai._generic_air_creature_keep_adjustment(
            player,
            enemy,
            card,
            hand,
            projected_available_resources=projected_available_resources,
            projected_total_resources=projected_total_resources,
        )


SPECIALIZED_AIR_CREATURE_HANDLERS: tuple[AirCreatureHandler, ...] = (
    GenericAirCreatureHandler(
        template_id="air_creature_sturmschwinge",
        guideline="Kleiner Flieger mit Recycle 1. Wertvoll fuer den dritten Angreifer, breite Angriffe und zuverlaessigen Druck durch die Luft.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_sturmgeist",
        guideline="Tempo-Schnellangreifer mit Recycle 2. Nur stark, wenn der Sofortangriff den Recyclepreis rechtfertigt.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_wolkenschwinge",
        guideline="Effizienter Flieger auf eins. Besser in Rennsituationen und gegen Gegner mit wenig Flugabwehr.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_wolkengeist",
        guideline="Effizienter Schnell-Angreifer auf eins. Besser, wenn sofort Druck oder der dritte Angreifer entsteht.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_windschwinge",
        guideline="Stabiler Mittelkurven-Flieger. Gut fuer wiederholbaren, schwer blockbaren Druck.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_windgeist",
        guideline="Offensiver Mittelkurven-Schnellangreifer. Gut fuer Tempozuege und breite Angriffe.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_himmelsschwinge",
        guideline="Widerstandsfaehiger Flieger. Stark, wenn der Gegner wenig fliegende Blocker hat.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_himmelsgeist",
        guideline="Obere Schnell-Kurve. Stark, wenn sofort Druck oder lethal setups moeglich sind.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkanschwinge",
        guideline="Grosser Flieger mit Recycle 1. Spielen, wenn langfristiger Luftdruck den Recyclepreis rechtfertigt.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkangeist",
        guideline="Grosser Schnell-Angreifer mit Recycle 1. Vor allem fuer decisive Tempo- und Lethal-Zuege.",
    ),
)
