from __future__ import annotations

from typing import Callable

from cards.air.creatures import AIR_CREATURES
from cards.earth.creatures import EARTH_CREATURES
from cards.fire.creatures import FIRE_CREATURES
from cards.water.creatures import WATER_CREATURES
from models import CardInstance, CardTemplate


DECK_DEFINITIONS: dict[str, list[tuple[str, int]]] = {
    "water": [
        ("water_wassertropfen", 3),
        ("water_kuestenkaempfer", 3),
        ("water_flusskrieger", 3),
        ("water_quellnymphe", 2),
        ("water_gezeitenheiler", 2),
        ("water_wellenformer", 2),
        ("water_tiefenjaeger", 2),
        ("water_uralter_leviathan", 1),
    ],
    "fire": [
        ("fire_funkenkobold", 3),
        ("fire_flammenrekrut", 3),
        ("fire_lavakrieger", 3),
        ("fire_brandstifter", 2),
        ("fire_flammenmagier", 2),
        ("fire_feuerwidder", 2),
        ("fire_magmabestie", 2),
        ("fire_infernodrache", 1),
    ],
    "air": [
        ("air_windgeist", 3),
        ("air_himmelsspaeher", 3),
        ("air_sturmfalke", 3),
        ("air_boeenreiter", 2),
        ("air_windklinge", 2),
        ("air_wolkenwaechter", 2),
        ("air_himmelsgreif", 2),
        ("air_sturmfuerst", 1),
    ],
    "earth": [
        ("earth_steinkobold", 3),
        ("earth_felsensoldat", 3),
        ("earth_erdgolem", 3),
        ("earth_schildwache", 2),
        ("earth_bastionshueter", 2),
        ("earth_granitkrieger", 2),
        ("earth_bergtroll", 2),
        ("earth_uralter_koloss", 1),
    ],
}


def build_card_templates() -> dict[str, CardTemplate]:
    templates = FIRE_CREATURES + WATER_CREATURES + EARTH_CREATURES + AIR_CREATURES
    return {template.template_id: template for template in templates}


def get_deck_templates(
    deck_name: str,
    templates: dict[str, CardTemplate],
) -> list[CardTemplate]:
    return [templates[template_id] for template_id, _copies in DECK_DEFINITIONS[deck_name]]


def build_test_deck(
    deck_name: str,
    templates: dict[str, CardTemplate],
    make_instance_id: Callable[[], int],
) -> list[CardInstance]:
    decklist = DECK_DEFINITIONS[deck_name]
    deck: list[CardInstance] = []
    for template_id, copies in decklist:
        for _ in range(copies):
            deck.append(CardInstance(make_instance_id(), templates[template_id]))
    return deck
