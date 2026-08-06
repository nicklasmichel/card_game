from enum import Enum


class Element(Enum):
    FIRE = "Feuer"
    WATER = "Wasser"
    EARTH = "Erde"
    AIR = "Luft"


class Ability(Enum):
    ENRAGED = "Wütend"
    IGNITE = "Entzuenden"
    TRAMPLE = "Trampelnd"
    HASTE = "Schnell"
    FLYING = "Fliegend"
    DEFENDER = "Verteidiger"
    PROVOKE = "Provozieren"
    REGENERATION = "Regeneration"
    ADAPTATION = "Anpassung"


class CardType(Enum):
    CREATURE = "Kreatur"
    RITUAL = "Ritual"
    SPELL = "Zauber"


class SpellEffect(Enum):
    DEAL_DAMAGE_TO_CREATURE = "Schaden an Kreatur"
    DEAL_DAMAGE_TO_CREATURE_OR_PLAYER = "Schaden an Kreatur oder Spieler"
    DEAL_DAMAGE_TO_ALL_ENEMY_CREATURES = "Schaden an alle gegnerischen Kreaturen"
    DEAL_DAMAGE_TO_ALL_CREATURES = "Schaden an alle Kreaturen"
    SACRIFICE_FOR_DAMAGE = "Kreatur opfern und Schaden verursachen"
    DRAW_AND_SELF_DAMAGE = "Karten ziehen und Eigenschaden"
    DRAW_CARDS = "Karten ziehen"
    DECK_TO_TAPPED_RESOURCES = "Deckkarten getappt als Ressourcen ins Spiel"
    REDUCE_CREATURE_COST_THIS_TURN = "Kreaturen kosten in diesem Zug weniger"
    GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN = "Angriff bis Zugende erhoehen"
    GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT = "Angreifer fssr diesen Kampf verstssrken"
    GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT = "Eigene Angreifer fuer diesen Kampf verstaerken"
    GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN = "Schnell oder Fliegend bis Zugende"
    DRAW_TWO_THEN_DISCARD_ONE = "Zwei ziehen, eine abwerfen"
    DISCARD_HAND_AND_DRAW_THREE = "Hand abwerfen und drei ziehen"
    RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND = "Kreaturenkarten aus eigenem Ablagestapel auf die Hand"
    DISCARD_HAND_AND_DRAW = "Hand abwerfen und Karten ziehen"
    RETURN_CREATURES_TO_HAND = "Kreaturen auf die Haende ihrer Besitzer zuruecknehmen"
    BUFF_ATTACKERS_DICE_THIS_TURN = "Angreifer erhalten Wssrfelbonus"
    RETURN_TWO_CREATURES_TO_HAND = "Zwei Kreaturen auf die Hand"
    RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND = "Eigene und gegnerische Kreatur auf die Hand"
    MODIFY_DIE_RESULT = "Wssrfelergebnis verssndern"
    DAMAGE_AFTER_OWN_CREATURE_DESTROYED = "Schaden nach Zerstoerung"
    DAMAGE_DECLARED_BLOCKER = "Schaden an Blocker"
    DAMAGE_OPPONENT_WHEN_TARGETED = "Gegenfeuer"
    RETALIATE_DICE_DAMAGE = "Vergeltung nach Wssrfelschaden"
    RETURN_OWN_FIGHTING_CREATURE_TO_HAND = "Eigene kaempfende Kreatur auf die Hand"
    REROLL_OPEN_DIE = "Offenen Wssrfel neu werfen"
    DOUBLE_UNBLOCKED_ATTACK_DAMAGE = "Direkten Angriffsschaden verdoppeln"
    DRAW_PER_DEATH_THIS_TURN = "Pro gestorbener Kreatur Karten ziehen"


class ReactionTrigger(Enum):
    SPELL_CAST = "Zauber wurde gespielt"
    AFTER_ATTACKERS_DECLARED = "Angreifer wurden deklariert"
    AFTER_BLOCKERS_DECLARED = "Blocker wurden deklariert"
    BEFORE_FIRST_COMBAT = "Kampf beginnt gleich"
    AFTER_DICE_REVEALED = "Wssrfel wurden geworfen"
    BEFORE_DICE_COMPARISON = "Ausgewsshlte Wssrfel warten auf Auswertung"
    AFTER_DICE_COMPARISON = "Wssrfelvergleich wurde abgeschlossen"
    BEFORE_DIRECT_ATTACK_DAMAGE = "Ungeblockter Angriff verursacht gleich Schaden"
    OWN_CREATURE_DESTROYED = "Eigene Kreatur wurde zerstoert"
    BLOCKER_DECLARED = "Blocker wurde deklariert"
    OWN_CREATURE_TARGETED = "Eigene Kreatur wurde Ziel eines Zaubers"
    OWN_CREATURE_DAMAGED_IN_DICE_COMPARISON = "Eigene Kreatur erlitt Schaden in einem Wssrfelvergleich"


class SpellTargetMode(Enum):
    NONE = "Kein Ziel"
    CREATURE = "Kreatur"
    CREATURE_OR_PLAYER = "Kreatur oder Spieler"
    DISCARD_CREATURE_CARD = "Kreaturenkarte aus eigenem Ablagestapel"
