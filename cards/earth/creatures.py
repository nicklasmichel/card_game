from __future__ import annotations

from models import Ability, CardTemplate, Element


EARTH_CREATURES = [
    CardTemplate("earth_steinkobold", "Steinkobold", 1, 1, 1, Element.EARTH),
    CardTemplate("earth_felsensoldat", "Felsensoldat", 2, 1, 3, Element.EARTH),
    CardTemplate("earth_erdgolem", "Erdgolem", 3, 1, 5, Element.EARTH),
    CardTemplate("earth_schildwache", "Schildwache", 2, 1, 3, Element.EARTH, frozenset({Ability.DEFENDER})),
    CardTemplate("earth_bastionshueter", "Bastionshüter", 4, 3, 5, Element.EARTH, frozenset({Ability.DEFENDER})),
    CardTemplate("earth_granitkrieger", "Granitkrieger", 3, 2, 4, Element.EARTH, frozenset({Ability.STEADFAST})),
    CardTemplate("earth_bergtroll", "Bergtroll", 5, 4, 6, Element.EARTH, frozenset({Ability.STEADFAST})),
    CardTemplate("earth_uralter_koloss", "Uralter Koloss", 6, 5, 6, Element.EARTH, frozenset({Ability.DEFENDER, Ability.STEADFAST})),
]

