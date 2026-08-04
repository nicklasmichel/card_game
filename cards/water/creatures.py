from __future__ import annotations

from core.models import Ability, CardCost, CardTemplate, Element


WATER_CREATURES = [
    CardTemplate(
        template_id="water_creature_wassertropfen",
        name="Wassertropfen",
        cost=CardCost(resources=1),
        aw=1,
        vw=1,
        element=Element.WATER,
    ),
    CardTemplate(
        template_id="water_creature_kuestenkaempfer",
        name="Kuestenkaempfer",
        cost=CardCost(resources=2),
        aw=2,
        vw=2,
        element=Element.WATER,
    ),
    CardTemplate(
        template_id="water_creature_flusskrieger",
        name="Flusskrieger",
        cost=CardCost(resources=2, recycle=1),
        aw=3,
        vw=3,
        element=Element.WATER,
    ),
    CardTemplate(
        template_id="water_creature_quellnymphe",
        name="Quellnymphe",
        cost=CardCost(resources=2),
        aw=1,
        vw=2,
        element=Element.WATER,
        abilities=frozenset({Ability.REGENERATION}),
    ),
    CardTemplate(
        template_id="water_creature_gezeitenheiler",
        name="Gezeitenheiler",
        cost=CardCost(resources=4),
        aw=3,
        vw=4,
        element=Element.WATER,
        abilities=frozenset({Ability.REGENERATION}),
    ),
    CardTemplate(
        template_id="water_creature_wellenformer",
        name="Wellenformer",
        cost=CardCost(resources=3),
        aw=3,
        vw=2,
        element=Element.WATER,
        abilities=frozenset({Ability.ADAPTATION}),
    ),
    CardTemplate(
        template_id="water_creature_tiefenjaeger",
        name="Tiefenjaeger",
        cost=CardCost(resources=5),
        aw=5,
        vw=4,
        element=Element.WATER,
        abilities=frozenset({Ability.ADAPTATION}),
    ),
    CardTemplate(
        template_id="water_creature_uralter_leviathan",
        name="Uralter Leviathan",
        cost=CardCost(resources=6),
        aw=4,
        vw=6,
        element=Element.WATER,
        abilities=frozenset({Ability.REGENERATION, Ability.ADAPTATION}),
    ),
]
