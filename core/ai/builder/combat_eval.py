from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from core.models import Ability, BattlefieldCreature

from .turn_projection import normalize_builder_abilities
from .types import BuilderCreatureCandidate


@dataclass(frozen=True)
class BuilderCombatantView:
    aw: int
    vw: int
    sw: int
    lw: int
    current_hp: int
    abilities: frozenset[Ability]
    ready: bool = True
    cannot_block: bool = False
    name: str = ""

    def has_ability(self, ability: Ability) -> bool:
        return ability in self.abilities


@dataclass(frozen=True)
class BuilderCombatEstimate:
    attacker_win_probability: float
    defender_win_probability: float
    raw_tie_probability: float
    expected_damage_to_defender: float
    expected_damage_to_attacker: float
    expected_player_damage: float
    expected_attacker_heal: float
    expected_defender_heal: float
    defender_death_probability: float
    attacker_death_probability: float


@dataclass(frozen=True)
class BuilderUnblockedAttackEstimate:
    player_damage: float
    attacker_heal: float


@dataclass(frozen=True)
class DiceWinEstimate:
    attacker_win_probability: float
    defender_win_probability: float
    raw_tie_probability: float


def build_candidate_combatant_view(
    candidate: BuilderCreatureCandidate,
    *,
    current_hp: int | None = None,
    ready: bool = True,
) -> BuilderCombatantView:
    return BuilderCombatantView(
        aw=candidate.aw,
        vw=candidate.vw,
        sw=candidate.sw,
        lw=candidate.lw,
        current_hp=candidate.lw if current_hp is None else max(0, min(candidate.lw, current_hp)),
        abilities=normalize_builder_abilities(frozenset(candidate.abilities)),
        ready=ready,
        cannot_block=False,
        name="candidate",
    )


def coerce_builder_combatant(subject, *, ready: bool | None = None) -> BuilderCombatantView:
    if isinstance(subject, BuilderCombatantView):
        if ready is None or ready == subject.ready:
            return subject
        return BuilderCombatantView(
            aw=subject.aw,
            vw=subject.vw,
            sw=subject.sw,
            lw=subject.lw,
            current_hp=subject.current_hp,
            abilities=subject.abilities,
            ready=ready,
            cannot_block=subject.cannot_block,
            name=subject.name,
        )
    if isinstance(subject, BuilderCreatureCandidate):
        return build_candidate_combatant_view(subject, ready=True if ready is None else ready)
    if isinstance(subject, BattlefieldCreature):
        return BuilderCombatantView(
            aw=subject.aw,
            vw=subject.vw,
            sw=subject.sw,
            lw=subject.lw,
            current_hp=subject.current_hp,
            abilities=normalize_builder_abilities(frozenset(subject.abilities)),
            ready=subject.is_ready() if ready is None else ready,
            cannot_block=getattr(subject, "cannot_block", False),
            name=subject.name,
        )
    if all(hasattr(subject, attribute) for attribute in ("aw", "vw", "sw", "lw", "current_hp", "abilities")):
        computed_ready = (
            ready
            if ready is not None
            else bool(getattr(subject, "is_ready", lambda: not getattr(subject, "tapped", False))())
        )
        return BuilderCombatantView(
            aw=int(subject.aw),
            vw=int(subject.vw),
            sw=int(subject.sw),
            lw=int(subject.lw),
            current_hp=int(subject.current_hp),
            abilities=normalize_builder_abilities(frozenset(subject.abilities)),
            ready=computed_ready,
            cannot_block=bool(getattr(subject, "cannot_block", False)),
            name=str(getattr(subject, "name", "")),
        )
    raise TypeError(f"Unsupported combatant type: {type(subject)!r}")


@lru_cache(maxsize=None)
def get_d6_sum_distribution(num_dice: int) -> dict[int, float]:
    if num_dice < 0:
        raise ValueError("num_dice must be >= 0")
    if num_dice == 0:
        return {0: 1.0}
    counts = {0: 1}
    for _ in range(num_dice):
        next_counts: dict[int, int] = {}
        for total, ways in counts.items():
            for face in range(1, 7):
                next_counts[total + face] = next_counts.get(total + face, 0) + ways
        counts = next_counts
    total_outcomes = 6 ** num_dice
    return {total: ways / total_outcomes for total, ways in sorted(counts.items())}


@lru_cache(maxsize=None)
def estimate_dice_win_probabilities(attacker_aw: int, defender_vw: int) -> DiceWinEstimate:
    if attacker_aw < 0 or defender_vw < 0:
        raise ValueError("dice counts must be >= 0")
    if attacker_aw == 0 and defender_vw > 0:
        return DiceWinEstimate(0.0, 1.0, 0.0)
    if defender_vw == 0 and attacker_aw > 0:
        return DiceWinEstimate(1.0, 0.0, 0.0)
    if attacker_aw == 0 and defender_vw == 0:
        return DiceWinEstimate(1.0, 0.0, 1.0)

    attacker_distribution = get_d6_sum_distribution(attacker_aw)
    defender_distribution = get_d6_sum_distribution(defender_vw)
    attacker_raw = 0.0
    defender_raw = 0.0
    tie_raw = 0.0
    for attacker_sum, attacker_probability in attacker_distribution.items():
        for defender_sum, defender_probability in defender_distribution.items():
            probability = attacker_probability * defender_probability
            if attacker_sum > defender_sum:
                attacker_raw += probability
            elif defender_sum > attacker_sum:
                defender_raw += probability
            else:
                tie_raw += probability
    if tie_raw >= 1.0:
        return DiceWinEstimate(1.0, 0.0, 1.0)
    return DiceWinEstimate(attacker_raw + tie_raw, defender_raw, tie_raw)


def can_legally_block(attacker, blocker, *, require_ready: bool = True) -> bool:
    attacker_view = coerce_builder_combatant(attacker)
    blocker_view = coerce_builder_combatant(blocker)
    if blocker_view.cannot_block:
        return False
    if blocker_view.vw <= 0:
        return False
    if require_ready and not blocker_view.ready:
        return False
    if attacker_view.has_ability(Ability.FLYING) and not blocker_view.has_ability(Ability.FLYING):
        return False
    return True


def can_legally_be_forced_to_block(attacker, blocker, *, require_ready: bool = True) -> bool:
    attacker_view = coerce_builder_combatant(attacker)
    blocker_view = coerce_builder_combatant(blocker)
    if blocker_view.cannot_block:
        return False
    if require_ready and not blocker_view.ready:
        return False
    if attacker_view.has_ability(Ability.FLYING) and not blocker_view.has_ability(Ability.FLYING):
        return False
    return True


def estimate_builder_combat(attacker, defender) -> BuilderCombatEstimate:
    attacker_view = coerce_builder_combatant(attacker)
    defender_view = coerce_builder_combatant(defender)
    dice = estimate_dice_win_probabilities(attacker_view.aw, defender_view.vw)

    effective_damage_to_defender = min(attacker_view.sw, max(0, defender_view.current_hp))
    effective_damage_to_attacker = min(defender_view.sw, max(0, attacker_view.current_hp))
    trample_overflow = (
        max(0, attacker_view.sw - defender_view.current_hp)
        if attacker_view.has_ability(Ability.TRAMPLE)
        else 0
    )

    attacker_missing_hp = max(0, attacker_view.lw - attacker_view.current_hp)
    defender_missing_hp = max(0, defender_view.lw - defender_view.current_hp)
    attacker_heal_on_win = (
        min(attacker_missing_hp, effective_damage_to_defender + trample_overflow)
        if attacker_view.has_ability(Ability.LIFE_STEAL)
        else 0
    )
    defender_heal_on_win = (
        min(defender_missing_hp, effective_damage_to_attacker)
        if defender_view.has_ability(Ability.LIFE_STEAL)
        else 0
    )

    return BuilderCombatEstimate(
        attacker_win_probability=dice.attacker_win_probability,
        defender_win_probability=dice.defender_win_probability,
        raw_tie_probability=dice.raw_tie_probability,
        expected_damage_to_defender=dice.attacker_win_probability * effective_damage_to_defender,
        expected_damage_to_attacker=dice.defender_win_probability * effective_damage_to_attacker,
        expected_player_damage=dice.attacker_win_probability * trample_overflow,
        expected_attacker_heal=dice.attacker_win_probability * attacker_heal_on_win,
        expected_defender_heal=dice.defender_win_probability * defender_heal_on_win,
        defender_death_probability=dice.attacker_win_probability if attacker_view.sw >= defender_view.current_hp else 0.0,
        attacker_death_probability=dice.defender_win_probability if defender_view.sw >= attacker_view.current_hp else 0.0,
    )


def estimate_unblocked_attack(attacker) -> BuilderUnblockedAttackEstimate:
    attacker_view = coerce_builder_combatant(attacker)
    missing_hp = max(0, attacker_view.lw - attacker_view.current_hp)
    heal = min(missing_hp, attacker_view.sw) if attacker_view.has_ability(Ability.LIFE_STEAL) else 0
    return BuilderUnblockedAttackEstimate(
        player_damage=float(attacker_view.sw),
        attacker_heal=float(heal),
    )
