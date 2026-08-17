from __future__ import annotations

from collections.abc import Iterable

BUILDER_MAX_RESOURCES = 10
BUILDER_CREATURE_CAP = 5
BUILDER_ABILITY_COST = 0
BUILDER_HASTE_COST = 1
BUILDER_ABILITIES_ENABLED = False
BUILDER_CREATURE_ABILITIES_ENABLED = False
BUILDER_BASE_STAT_VALUE = 1

BUILDER_PRIMARY_ABILITY_NAMES = (
    "FLYING",
    "VIGILANCE",
    "TRAMPLE",
)
BUILDER_PRIMARY_ABILITY_NAME_SET = frozenset(BUILDER_PRIMARY_ABILITY_NAMES)
BUILDER_CREATURE_ABILITY_NAMES = (
    "HASTE",
    *BUILDER_PRIMARY_ABILITY_NAMES,
)
BUILDER_CREATURE_ABILITY_NAME_SET = frozenset(BUILDER_CREATURE_ABILITY_NAMES)


def builder_creature_stat_cost(*, aw: int, vw: int, sw: int, lw: int) -> int:
    return sum(max(0, value - BUILDER_BASE_STAT_VALUE) for value in (aw, vw, sw, lw))


def calculate_builder_creature_cost(*, aw: int, vw: int, sw: int, lw: int, has_haste: bool = False) -> int:
    return builder_creature_stat_cost(aw=aw, vw=vw, sw=sw, lw=lw) + (BUILDER_HASTE_COST if has_haste else 0)


def _resolve_builder_ability(name: str):
    from domain.enums import Ability

    return getattr(Ability, name)


def get_builder_creature_abilities() -> tuple:
    if not BUILDER_CREATURE_ABILITIES_ENABLED:
        return ()
    return tuple(_resolve_builder_ability(name) for name in BUILDER_CREATURE_ABILITY_NAMES)


def get_builder_primary_abilities() -> tuple:
    return tuple(_resolve_builder_ability(name) for name in BUILDER_PRIMARY_ABILITY_NAMES)


def normalize_builder_creature_ability(ability):
    if ability is None:
        return None
    ability_name = getattr(ability, "name", str(ability))
    if ability_name == "VIGILANT":
        return _resolve_builder_ability("VIGILANCE")
    if ability_name in BUILDER_CREATURE_ABILITY_NAME_SET:
        return _resolve_builder_ability(ability_name)
    return ability


def is_valid_builder_creature_ability(ability) -> bool:
    if ability is None:
        return False
    return getattr(normalize_builder_creature_ability(ability), "name", "") in BUILDER_CREATURE_ABILITY_NAME_SET


def validate_builder_creature_ability(ability):
    normalized = normalize_builder_creature_ability(ability)
    if getattr(normalized, "name", "") not in BUILDER_CREATURE_ABILITY_NAME_SET:
        raise ValueError(f"Invalid builder creature ability: {ability!r}")
    return normalized


def is_valid_builder_primary_ability(ability) -> bool:
    if ability is None:
        return False
    return getattr(normalize_builder_creature_ability(ability), "name", "") in BUILDER_PRIMARY_ABILITY_NAME_SET


def validate_builder_primary_ability(ability):
    normalized = normalize_builder_creature_ability(ability)
    if getattr(normalized, "name", "") not in BUILDER_PRIMARY_ABILITY_NAME_SET:
        raise ValueError(f"Invalid builder primary ability: {ability!r}")
    return normalized


def normalize_builder_creature_abilities(abilities: Iterable) -> frozenset:
    return frozenset(validate_builder_creature_ability(ability) for ability in abilities)


def validate_builder_creature_abilities(abilities: Iterable) -> frozenset:
    normalized = normalize_builder_creature_abilities(abilities)
    if not BUILDER_CREATURE_ABILITIES_ENABLED:
        if normalized:
            raise ValueError("Builder creature abilities are disabled in vanilla mode")
        return normalized
    haste = _resolve_builder_ability("HASTE")
    primary = [ability for ability in normalized if is_valid_builder_primary_ability(ability)]
    if len(primary) != 1:
        raise ValueError(f"Builder creatures require exactly one primary ability, got {sorted(ability.name for ability in normalized)!r}")
    if normalized - {primary[0], haste}:
        raise ValueError(f"Invalid builder creature ability combination: {sorted(ability.name for ability in normalized)!r}")
    return normalized


def coerce_builder_creature_ability(ability_or_abilities) -> object | None:
    if ability_or_abilities is None:
        return None
    if hasattr(ability_or_abilities, "name"):
        return validate_builder_creature_ability(ability_or_abilities)
    abilities = [validate_builder_creature_ability(ability) for ability in ability_or_abilities]
    if not abilities:
        return None
    if len(abilities) != 1:
        raise ValueError(f"Builder creatures require exactly one ability, got {abilities!r}")
    return abilities[0]


def builder_creature_ability_set(primary_ability, *, has_haste: bool = False) -> frozenset:
    if not BUILDER_CREATURE_ABILITIES_ENABLED:
        if primary_ability is not None or has_haste:
            raise ValueError("Builder creature abilities are disabled in vanilla mode")
        return frozenset()
    if primary_ability is None:
        return frozenset()
    abilities = {validate_builder_primary_ability(primary_ability)}
    if has_haste:
        abilities.add(_resolve_builder_ability("HASTE"))
    return frozenset(abilities)


BUILDER_CREATURE_ABILITIES = get_builder_creature_abilities()
BUILDER_CREATURE_ABILITY_SET = frozenset(BUILDER_CREATURE_ABILITIES)
BUILDER_PRIMARY_ABILITIES = get_builder_primary_abilities()
BUILDER_PRIMARY_ABILITY_SET = frozenset(BUILDER_PRIMARY_ABILITIES)
