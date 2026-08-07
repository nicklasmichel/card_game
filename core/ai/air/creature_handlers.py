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
        template_id="air_creature_windschwinge",
        guideline="Kleiner Flieger mit hohem Recyclepreis. Gut fuer fruehen Luftdruck, aber nur sinnvoll, wenn der Ressourceneinsatz den Schaden rechtfertigt.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_sturmschwinge",
        guideline="Mittlerer Flieger mit Recycle 2. Stark in Rennsituationen und fuer die dritte Angreifer-Kreatur, aber langfristig teuer.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_windgeist",
        guideline="Sofortiger Tempo-Angreifer auf eins. Stark, wenn er direkt Druck macht oder den dritten Angreifer ermoeglicht.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_sturmgeist",
        guideline="Schneller Zwei-Mana-Angreifer mit hohem AW und ohne Blockwert. Spielen, wenn der Sofortangriff den offenen Gegenschlag wert ist.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkanschwinge",
        guideline="Starker Flieger mit Recycle 3. Nur spielen, wenn schwer blockbarer SW-3-Druck den langfristigen Ressourcenverlust aufwiegt.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkangeist",
        guideline="Oberer Schnell-Angreifer mit viel AW, aber geringem SW. Gut fuer Tempozuege, dritte Angreifer und sofortigen Druck.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_windwesen",
        guideline="Flexibler Vanilla-Einser. Einer der wenigen Luft-Blocker und deshalb defensiv wertvoller als die reinen Tempo-Kreaturen.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_sturmwesen",
        guideline="Solider Zwei-Mana-Body mit echter Blockfaehigkeit. Gut zum Stabilisieren und als normale Kurvenkreatur.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkanwesen",
        guideline="Groesstes Vanilla-Luftwesen. Wertvoll, wenn Blockfaehigkeit gebraucht wird oder Tempo-Kreaturen nicht reichen.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_luftelementar",
        guideline="All-in-Finisher mit Fliegend, Schnell und SW 3. Sehr stark fuer unmittelbaren Druck oder lethal setups, aber der Recyclepreis ist hoch.",
    ),
)
