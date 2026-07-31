from enum import Enum


class Element(Enum):
    FIRE = "Feuer"
    WATER = "Wasser"
    EARTH = "Erde"
    AIR = "Luft"


class Ability(Enum):
    IGNITE = "Entzünden"
    TRAMPLE = "Trampelschaden"
    HASTE = "Eile"
    VIGILANCE = "Wachsamkeit"
    DEFENDER = "Verteidiger"
    STEADFAST = "Unerschütterlich"
    REGENERATION = "Regeneration"
    ADAPTATION = "Anpassung"
