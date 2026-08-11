from enum import Enum


class Element(Enum):
    FIRE = "Feuer"
    WATER = "Wasser"
    EARTH = "Erde"
    AIR = "Luft"


class Ability(Enum):
    ENRAGED = "Wuetend"
    TRAMPLE = "trample"
    HASTE = "haste"
    FLYING = "flying"
    VIGILANT = "Wachsam"
    LIFE_STEAL = "Lebensraub"
    MAGIC_RESISTANT = "Magieresistent"
    DEATHTOUCH = "Deathtouch"
    LIFELINK = "Lifelink"
    VIGILANCE = "Vigilance"
    PROVOKE = "Provoke"


class CardType(Enum):
    CREATURE = "Kreatur"
    RITUAL = "Ritual"
    SPELL = "Zauber"
