from __future__ import annotations

from models import Ability, CardTemplate, Element


FIRE_CREATURES = [
    CardTemplate("fire_funkenkobold", "Funkenkobold", 1, 1, 1, Element.FIRE),
    CardTemplate("fire_flammenrekrut", "Flammenrekrut", 2, 3, 1, Element.FIRE),
    CardTemplate("fire_lavakrieger", "Lavakrieger", 3, 5, 1, Element.FIRE),
    CardTemplate("fire_brandstifter", "Brandstifter", 2, 2, 1, Element.FIRE, frozenset({Ability.IGNITE})),
    CardTemplate("fire_flammenmagier", "Flammenmagier", 4, 4, 3, Element.FIRE, frozenset({Ability.IGNITE})),
    CardTemplate("fire_feuerwidder", "Feuerwidder", 3, 3, 2, Element.FIRE, frozenset({Ability.TRAMPLE})),
    CardTemplate("fire_magmabestie", "Magmabestie", 5, 5, 4, Element.FIRE, frozenset({Ability.TRAMPLE})),
    CardTemplate("fire_infernodrache", "Infernodrache", 6, 6, 4, Element.FIRE, frozenset({Ability.IGNITE, Ability.TRAMPLE})),
]
