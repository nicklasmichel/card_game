from __future__ import annotations

from models import Ability, CardCost, CardTemplate, Element


AIR_CREATURES = [
    CardTemplate(
        template_id="air_windgeist",
        name="Windgeist",
        cost=CardCost(resources=1),
        aw=1,
        vw=1,
        element=Element.AIR,
    ),
    CardTemplate(
        template_id="air_himmelsspaeher",
        name="Himmelsspäher",
        cost=CardCost(resources=3),
        aw=2,
        vw=2,
        element=Element.AIR,
    ),
    CardTemplate(
        template_id="air_sturmfalke",
        name="Sturmfalke",
        cost=CardCost(resources=4),
        aw=3,
        vw=3,
        element=Element.AIR,
    ),
    CardTemplate(
        template_id="air_boeenreiter",
        name="Böenreiter",
        cost=CardCost(resources=2),
        aw=2,
        vw=1,
        element=Element.AIR,
        abilities=frozenset({Ability.HASTE}),
    ),
    CardTemplate(
        template_id="air_windklinge",
        name="Windklinge",
        cost=CardCost(resources=4, recycle=1),
        aw=4,
        vw=2,
        element=Element.AIR,
        abilities=frozenset({Ability.HASTE}),
    ),
    CardTemplate(
        template_id="air_wolkenwaechter",
        name="Wolkenwächter",
        cost=CardCost(resources=3),
        aw=2,
        vw=2,
        element=Element.AIR,
        abilities=frozenset({Ability.VIGILANCE}),
    ),
    CardTemplate(
        template_id="air_himmelsgreif",
        name="Himmelsgreif",
        cost=CardCost(resources=5, recycle=1),
        aw=4,
        vw=4,
        element=Element.AIR,
        abilities=frozenset({Ability.VIGILANCE}),
    ),
    CardTemplate(
        template_id="air_sturmfuerst",
        name="Sturmfürst",
        cost=CardCost(resources=6, recycle=2),
        aw=5,
        vw=5,
        element=Element.AIR,
        abilities=frozenset({Ability.HASTE, Ability.VIGILANCE}),
    ),
]
