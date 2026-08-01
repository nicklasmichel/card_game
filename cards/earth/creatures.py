from __future__ import annotations

from models import Ability, CardCost, CardTemplate, Element


EARTH_CREATURES = [
    CardTemplate(
        template_id="earth_steinkobold",
        name="Steinkobold",
        cost=CardCost(resources=1),
        aw=1,
        vw=1,
        element=Element.EARTH,
    ),
    CardTemplate(
        template_id="earth_felsensoldat",
        name="Felsensoldat",
        cost=CardCost(resources=2),
        aw=1,
        vw=3,
        element=Element.EARTH,
    ),
    CardTemplate(
        template_id="earth_erdgolem",
        name="Erdgolem",
        cost=CardCost(resources=3, recycle=1),
        aw=1,
        vw=5,
        element=Element.EARTH,
    ),
    CardTemplate(
        template_id="earth_schildwache",
        name="Schildwache",
        cost=CardCost(resources=2),
        aw=1,
        vw=3,
        element=Element.EARTH,
        abilities=frozenset({Ability.DEFENDER}),
    ),
    CardTemplate(
        template_id="earth_bastionshueter",
        name="Bastionshüter",
        cost=CardCost(resources=4),
        aw=3,
        vw=5,
        element=Element.EARTH,
        abilities=frozenset({Ability.DEFENDER}),
    ),
    CardTemplate(
        template_id="earth_granitkrieger",
        name="Granitkrieger",
        cost=CardCost(resources=3),
        aw=2,
        vw=4,
        element=Element.EARTH,
        abilities=frozenset({Ability.STEADFAST}),
    ),
    CardTemplate(
        template_id="earth_bergtroll",
        name="Bergtroll",
        cost=CardCost(resources=5),
        aw=4,
        vw=6,
        element=Element.EARTH,
        abilities=frozenset({Ability.STEADFAST}),
    ),
    CardTemplate(
        template_id="earth_uralter_koloss",
        name="Uralter Koloss",
        cost=CardCost(resources=4, recycle=2),
        aw=5,
        vw=6,
        element=Element.EARTH,
        abilities=frozenset({Ability.DEFENDER, Ability.STEADFAST}),
    ),
]
