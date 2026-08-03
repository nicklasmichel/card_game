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
        ("fire_creature_funkenwicht", 2),
        ("fire_creature_bombenwicht", 2),
        ("fire_creature_funkenkobold", 2),
        ("fire_creature_flammenrekrut", 2),
        ("fire_creature_lavakrieger", 2),
        ("fire_creature_brandstifter", 2),
        ("fire_creature_flammenmagier", 2),
        ("fire_creature_feuerwidder", 2),
        ("fire_creature_magmabestie", 2),
        ("fire_creature_infernodrache", 2),
        ("fire_ritual_funkenwurf", 2),
        ("fire_ritual_feuerball", 2),
        ("fire_ritual_flammenwelle", 2),
        ("fire_ritual_brandopfer", 2),
        ("fire_ritual_verbotene_glut", 2),
        ("fire_spell_hitzeschub", 2),
        ("fire_spell_letzter_funke", 2),
        ("fire_spell_brandzeichen", 2),
        ("fire_spell_gegenfeuer", 2),
        ("fire_spell_flammenzorn", 2),
    ],
    "air": [
        ("air_creature_boeengeist", 2),
        ("air_creature_windgeist", 2),
        ("air_creature_windhuscher", 2),
        ("air_creature_boeenreiter", 2),
        ("air_creature_sturmfalke", 2),
        ("air_creature_himmelsspaeher", 2),
        ("air_creature_windklinge", 2),
        ("air_creature_himmelsgreif", 2),
        ("air_creature_wolkenwaechter", 2),
        ("air_creature_sturmfuerst", 2),
        ("air_ritual_aufwind", 2),
        ("air_ritual_rueckenwind", 2),
        ("air_ritual_windwechsel", 2),
        ("air_ritual_sturmformation", 2),
        ("air_ritual_turbulenz", 2),
        ("air_spell_ausweichen", 2),
        ("air_spell_windstoss", 2),
        ("air_spell_boeenschub", 2),
        ("air_spell_windrausch", 2),
        ("air_spell_nachwehen", 2),
    ],
    "earth": [
        ("earth_creature_steinkobold", 3),
        ("earth_creature_felsensoldat", 3),
        ("earth_creature_erdgolem", 3),
        ("earth_creature_schildwache", 2),
        ("earth_creature_bastionshueter", 2),
        ("earth_creature_granitkrieger", 2),
        ("earth_creature_bergtroll", 2),
        ("earth_creature_uralter_koloss", 1),
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
        if deck_name in {"fire", "air"}:
            total_cards = sum(copies for _template_id, copies in decklist)
            if total_cards != 40:
                deck_label = "Feuerdeck" if deck_name == "fire" else "Luftdeck"
                raise ValueError(f"{deck_label} muss genau 40 Karten enthalten, gefunden: {total_cards}")


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
