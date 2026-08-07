from __future__ import annotations

from typing import Callable

from cards.air import AIR_CREATURES, AIR_RITUALS, AIR_SPELLS
from cards.earth.creatures import EARTH_CREATURES
from cards.fire import FIRE_CREATURES, FIRE_RITUALS, FIRE_SPELLS
from cards.water.creatures import WATER_CREATURES
from core.models import CardInstance, CardTemplate


DECK_DEFINITIONS: dict[str, list[tuple[str, int]]] = {
    "water": [
        ("water_creature_wassertropfen", 3),
        ("water_creature_kuestenkaempfer", 3),
        ("water_creature_flusskrieger", 3),
        ("water_creature_quellnymphe", 2),
        ("water_creature_gezeitenheiler", 2),
        ("water_creature_wellenformer", 2),
        ("water_creature_tiefenjaeger", 2),
        ("water_creature_uralter_leviathan", 1),
    ],
    "fire": [
        ("fire_creature_glutwesen", 2),
        ("fire_creature_flammenwesen", 2),
        ("fire_creature_glutbrecher", 2),
        ("fire_creature_flammenbrecher", 2),
        ("fire_creature_gluthetzer", 2),
        ("fire_creature_flammenhetzer", 2),
        ("fire_creature_infernowesen", 2),
        ("fire_creature_infernobestie", 2),
        ("fire_creature_hoellenbestie", 2),
        ("fire_ritual_holzvorrat", 2),
        ("fire_ritual_kohlevorrat", 2),
        ("fire_ritual_glutvision", 2),
        ("fire_ritual_flammenvision", 2),
        ("fire_ritual_hitzewelle", 2),
        ("fire_ritual_feuerwelle", 2),
        ("fire_spell_wutanfall", 2),
        ("fire_spell_raserei", 2),
        ("fire_spell_versengen", 2),
        ("fire_spell_verbrennen", 2),
        ("fire_spell_verkohlen", 2),
    ],
    "air": [
        ("air_creature_windschwinge", 2),
        ("air_creature_sturmschwinge", 2),
        ("air_creature_orkanschwinge", 2),
        ("air_creature_windgeist", 2),
        ("air_creature_sturmgeist", 2),
        ("air_creature_orkangeist", 2),
        ("air_creature_windwesen", 2),
        ("air_creature_sturmwesen", 2),
        ("air_creature_orkanwesen", 2),
        ("air_creature_luftelementar", 2),
        ("air_ritual_aufwind", 2),
        ("air_ritual_rueckenwind", 2),
        ("air_ritual_windruf", 2),
        ("air_ritual_sturmruf", 2),
        ("air_ritual_himmelswende", 2),
        ("air_ritual_orkanwende", 2),
        ("air_spell_verwehung", 2),
        ("air_spell_verwirbelung", 2),
        ("air_spell_jagdwind", 2),
        ("air_spell_sturmjagd", 2),
    ],
    "earth": [
        ("earth_creature_steinwesen", 2),
        ("earth_creature_felswesen", 2),
        ("earth_creature_steinwaechter", 2),
        ("earth_creature_granitwaechter", 2),
        ("earth_creature_felsgolem", 2),
        ("earth_creature_granitgolem", 2),
        ("earth_creature_gebirgstitan", 2),
        ("earth_creature_gebirgskoloss", 2),
    ],
}


def build_card_templates() -> dict[str, CardTemplate]:
    templates = FIRE_CREATURES + FIRE_RITUALS + FIRE_SPELLS + WATER_CREATURES + EARTH_CREATURES + AIR_CREATURES + AIR_RITUALS + AIR_SPELLS
    return {template.template_id: template for template in templates}


def validate_deck_definitions(templates: dict[str, CardTemplate]) -> None:
    for deck_name, decklist in DECK_DEFINITIONS.items():
        missing = [template_id for template_id, _copies in decklist if template_id not in templates]
        if missing:
            raise ValueError(f"Deck {deck_name} referenziert unbekannte Karten: {', '.join(missing)}")
        if deck_name in {"air", "fire"}:
            total_cards = sum(copies for _template_id, copies in decklist)
            if total_cards != 40:
                raise ValueError(f"{deck_name.capitalize()}deck muss genau 40 Karten enthalten, gefunden: {total_cards}")


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
