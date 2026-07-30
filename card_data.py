from __future__ import annotations

from typing import Callable, Dict, List

from models import CardInstance, CardTemplate


def build_card_templates() -> Dict[str, CardTemplate]:
    templates = [
        CardTemplate("rekrut", "Rekrut", 1, 1, 1),
        CardTemplate("spaeher", "Spaeher", 1, 1, 2),
        CardTemplate("kaempfer", "Kaempfer", 2, 2, 2),
        CardTemplate("schildtraeger", "Schildtraeger", 2, 1, 3),
        CardTemplate("berserker", "Berserker", 2, 3, 1),
        CardTemplate("soldat", "Soldat", 3, 2, 3),
        CardTemplate("plaenkler", "Plaenkler", 3, 3, 2),
        CardTemplate("bollwerk", "Bollwerk", 3, 1, 4),
        CardTemplate("veteran", "Veteran", 4, 3, 3),
        CardTemplate("angreifer", "Angreifer", 4, 4, 2),
        CardTemplate("waechter", "Waechter", 4, 2, 4),
        CardTemplate("koloss", "Koloss", 5, 4, 4),
        CardTemplate("glaskanone", "Glaskanone", 5, 5, 3),
        CardTemplate("festungswache", "Festungswache", 5, 3, 5),
        CardTemplate("titan", "Titan", 6, 5, 5),
        CardTemplate("kriegsgolem", "Kriegsgolem", 8, 6, 6),
    ]
    return {template.template_id: template for template in templates}


def build_test_deck(
    templates: Dict[str, CardTemplate],
    make_instance_id: Callable[[], int],
) -> List[CardInstance]:
    decklist = {
        "rekrut": 3,
        "spaeher": 3,
        "kaempfer": 3,
        "schildtraeger": 2,
        "berserker": 2,
        "soldat": 3,
        "plaenkler": 2,
        "bollwerk": 2,
        "veteran": 2,
        "angreifer": 2,
        "waechter": 1,
        "koloss": 1,
        "glaskanone": 1,
        "festungswache": 1,
        "titan": 1,
        "kriegsgolem": 1,
    }
    deck: List[CardInstance] = []
    for template_id, copies in decklist.items():
        for _ in range(copies):
            deck.append(CardInstance(make_instance_id(), templates[template_id]))
    return deck
