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
        guideline="Kleiner Flieger nur ueber Recycle. Erzeugt Luftdruck und kann blocken, kostet aber dauerhaft Ressourcenbasis.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_sturmschwinge",
        guideline="Mittlerer Flieger nur ueber Recycle 2. Stark fuer schwer blockbaren Schaden, aber mit echter Langzeitstrafe.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_windgeist",
        guideline="Offensive Glaskanone ohne Schnell und ohne Blockwert. Hoher AW, aber erst ab dem Folgezug relevant.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_sturmgeist",
        guideline="Zwei-Mana-Glaskanone ohne Schnell und ohne Blockwert. Druck ueber AW, nicht ueber Haltbarkeit oder Soforttempo.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkanschwinge",
        guideline="Starker Flieger mit Recycle 3. Nur spielen, wenn schwer blockbarer SW-3-Druck den langfristigen Ressourcenverlust aufwiegt.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkangeist",
        guideline="Oberer Geist ohne Schnell und ohne Blockwert. Sehr hoher AW, aber bewusst fragil und erst im spaeteren Angriff relevant.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_windwesen",
        guideline="Kleine Schnell-Kreatur mit voller Tempofunktion. Kann sofort angreifen und dank VW 1 auch blocken.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_sturmwesen",
        guideline="Schnelle Zwei-Mana-Kreatur mit VW 2, aber nur LW 1. Soforttempo ja, falsche Tank-Bewertung nein.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_orkanwesen",
        guideline="Groesstes Schnell-Wesen mit VW 3, aber weiter nur LW 1. Sofortdruck und Blockoption, keine echte Haltbarkeit.",
    ),
    GenericAirCreatureHandler(
        template_id="air_creature_luftelementar",
        guideline="Explosiver Fliegend-und-Schnell-Finisher. Sehr stark fuer sofortigen Druck oder lethal setups, aber Recycle 3 ist ein harter Langzeitpreis.",
    ),
)
