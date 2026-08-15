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


class ControllerKind(str, Enum):
    """Describes who is allowed to make decisions for a player."""

    LOCAL_HUMAN = "local_human"
    REMOTE_HUMAN = "remote_human"
    AI = "ai"


class MatchMode(str, Enum):
    """High-level match topology, independent from the UI used to start it."""

    PVE = "pve"
    PVP = "pvp"
