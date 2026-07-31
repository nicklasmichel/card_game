from __future__ import annotations

from models import Ability, CardTemplate, Element


WATER_CREATURES = [
    CardTemplate("water_wassertropfen", "Wassertropfen", 1, 1, 1, Element.WATER),
    CardTemplate("water_kuestenkaempfer", "Küstenkämpfer", 2, 2, 2, Element.WATER),
    CardTemplate("water_flusskrieger", "Flusskrieger", 3, 3, 3, Element.WATER),
    CardTemplate("water_quellnymphe", "Quellnymphe", 2, 1, 2, Element.WATER, frozenset({Ability.REGENERATION})),
    CardTemplate("water_gezeitenheiler", "Gezeitenheiler", 4, 3, 4, Element.WATER, frozenset({Ability.REGENERATION})),
    CardTemplate("water_wellenformer", "Wellenformer", 3, 3, 2, Element.WATER, frozenset({Ability.ADAPTATION})),
    CardTemplate("water_tiefenjaeger", "Tiefenjäger", 5, 5, 4, Element.WATER, frozenset({Ability.ADAPTATION})),
    CardTemplate("water_uralter_leviathan", "Uralter Leviathan", 6, 4, 6, Element.WATER, frozenset({Ability.REGENERATION, Ability.ADAPTATION})),
]

