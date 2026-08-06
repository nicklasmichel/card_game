from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlayerCounters:
    cards_drawn: int = 0
    resources_played: int = 0
    creatures_played: int = 0
    recycled_resources: int = 0
    recycled_cards_played: int = 0
    total_recycle_cost_paid: int = 0
    max_recycle_paid_once: int = 0
    recycled_cards_drawn_again: int = 0
    attackers_declared: int = 0
    unblocked_attacks: int = 0
    creatures_destroyed: int = 0
    player_damage_dealt: int = 0
    creature_damage_dealt: int = 0
    rituals_played: int = 0
    spells_played: int = 0
    spell_damage_dealt: int = 0
    spell_self_damage_taken: int = 0
    hitzeschub_swung_comparisons: int = 0
    letzter_funke_damage: int = 0
    brandzeichen_destroyed_blockers: int = 0
    gegenfeuer_damage: int = 0
    flammenzorn_destroyed_creatures: int = 0


@dataclass
class CreatureCombatRecord:
    game_id: str
    combat_id: int
    timestamp: str
    player_name: str
    creature_name: str
    aw: int
    vw: int
    role: str
    won: int
    lost: int
    survived: int
    damage_dealt: int
    damage_taken: int
    dice_comparisons: int


@dataclass
class PendingCombatStats:
    combat_id: int
    attacker_owner: int
    blocker_owner: int
    attacker_creature_name: str
    blocker_creature_name: str
    attacker_aw: int
    attacker_vw: int
    blocker_aw: int
    blocker_vw: int
    attacker_hp_before: int
    blocker_hp_before: int
    dice_comparisons: int = 0
    attacker_damage_dealt: int = 0
    blocker_damage_dealt: int = 0
