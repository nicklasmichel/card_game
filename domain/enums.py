from enum import Enum


class Element(Enum):
    FIRE = "Feuer"
    WATER = "Wasser"
    EARTH = "Erde"
    AIR = "Luft"


class Ability(Enum):
    ENRAGED = "Wuetend"
    TRAMPLE = "Trampelnd"
    HASTE = "Schnell"
    FLYING = "Fliegend"


class CardType(Enum):
    CREATURE = "Kreatur"
    RITUAL = "Ritual"
    SPELL = "Zauber"


class SpellTiming(Enum):
    INSTANT = "Spontanzauber"
    COMBAT = "Kampfzauber"


class SpellEffect(Enum):
    DEAL_DAMAGE_TO_CREATURE = "Schaden an Kreatur"
    DEAL_DAMAGE_TO_CREATURE_OR_PLAYER = "Schaden an Kreatur oder Spieler"
    DEAL_DAMAGE_TO_ALL_ENEMY_CREATURES = "Schaden an alle gegnerischen Kreaturen"
    DEAL_DAMAGE_TO_ALL_CREATURES = "Schaden an alle Kreaturen"
    DEAL_DAMAGE_TO_ALL_CREATURES_AND_PLAYERS = "Schaden an alle Kreaturen und Spieler"
    SACRIFICE_FOR_DAMAGE = "Kreatur opfern und Schaden verursachen"
    DRAW_AND_SELF_DAMAGE = "Karten ziehen und Eigenschaden"
    DRAW_CARDS = "Karten ziehen"
    DECK_TO_TAPPED_RESOURCES = "Deckkarten getappt als Ressourcen ins Spiel"
    REDUCE_CREATURE_COST_THIS_TURN = "Kreaturen kosten in diesem Zug weniger"
    GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN = "Angriff bis Zugende erhoehen"
    GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT = "Angreifer fuer diesen Kampf verstaerken"
    GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT = "Eigene Angreifer fuer diesen Kampf verstaerken"
    GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN = "Schnell oder Fliegend bis Zugende"
    DRAW_TWO_THEN_DISCARD_ONE = "Zwei ziehen, eine abwerfen"
    DISCARD_HAND_AND_DRAW_THREE = "Hand abwerfen und drei ziehen"
    RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND = "Kreaturenkarten aus eigenem Ablagestapel auf die Hand"
    DISCARD_HAND_AND_DRAW = "Hand abwerfen und Karten ziehen"
    RETURN_CREATURES_TO_HAND = "Kreaturen auf die Haende ihrer Besitzer zuruecknehmen"
    RETURN_TWO_CREATURES_TO_HAND = "Zwei Kreaturen auf die Hand"
    RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND = "Eigene und gegnerische Kreatur auf die Hand"
    RETURN_OWN_FIGHTING_CREATURE_TO_HAND = "Eigene kaempfende Kreatur auf die Hand"
    DRAW_PER_DEATH_THIS_TURN = "Pro gestorbener Kreatur Karten ziehen"


class ReactionTrigger(Enum):
    SPELL_CAST = "Zauber wurde gespielt"
    MAIN_1_PRIORITY = "Hauptphase 1"
    MAIN_2_PRIORITY = "Hauptphase 2"
    COMBAT_START = "Kampfbeginn"
    COMBAT_END = "Kampfende"
    OWN_CREATURE_DESTROYED = "Eigene Kreatur wurde zerstoert"
    OWN_CREATURE_TARGETED = "Eigene Kreatur wurde Ziel eines Zaubers"


class SpellTargetMode(Enum):
    NONE = "Kein Ziel"
    CREATURE = "Kreatur"
    CREATURE_OR_PLAYER = "Kreatur oder Spieler"
    DISCARD_CREATURE_CARD = "Kreaturenkarte aus eigenem Ablagestapel"
