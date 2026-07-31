from __future__ import annotations

from models import Ability, CardTemplate, Element


AIR_CREATURES = [
    CardTemplate("air_windgeist", "Windgeist", 1, 1, 1, Element.AIR),
    CardTemplate("air_himmelsspaeher", "Himmelsspäher", 2, 2, 2, Element.AIR),
    CardTemplate("air_sturmfalke", "Sturmfalke", 3, 4, 2, Element.AIR),
    CardTemplate("air_boeenreiter", "Böenreiter", 2, 2, 1, Element.AIR, frozenset({Ability.HASTE})),
    CardTemplate("air_windklinge", "Windklinge", 4, 5, 2, Element.AIR, frozenset({Ability.HASTE})),
    CardTemplate("air_wolkenwaechter", "Wolkenwächter", 3, 2, 3, Element.AIR, frozenset({Ability.VIGILANCE})),
    CardTemplate("air_himmelsgreif", "Himmelsgreif", 5, 4, 5, Element.AIR, frozenset({Ability.VIGILANCE})),
    CardTemplate("air_sturmfuerst", "Sturmfürst", 6, 5, 5, Element.AIR, frozenset({Ability.HASTE, Ability.VIGILANCE})),
]

