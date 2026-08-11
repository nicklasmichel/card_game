from __future__ import annotations

import importlib
import inspect
from typing import Iterable

import core.config as config
from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.game_mode import is_builder_mode
from core.models import Ability, PHASE_BUILDER_ABILITY, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_MAIN_1


def builder_debug_level() -> int:
    return max(0, int(getattr(config, "BUILDER_AI_DEBUG", 0)))


def builder_debug_enabled() -> bool:
    return builder_debug_level() > 0 and is_builder_mode()


def builder_debug_verbose() -> bool:
    return builder_debug_level() >= 2 and builder_debug_enabled()


def builder_debug_top_n() -> int:
    return max(1, int(getattr(config, "BUILDER_AI_DEBUG_TOP_N", 5)))


def builder_debug_build_top_n() -> int:
    return max(1, int(getattr(config, "BUILDER_AI_DEBUG_BUILD_TOP_N", builder_debug_top_n())))


def builder_debug_precision() -> int:
    return max(0, int(getattr(config, "BUILDER_AI_DEBUG_FLOAT_PRECISION", 2)))


def builder_debug_include_weights() -> bool:
    return bool(getattr(config, "BUILDER_AI_DEBUG_INCLUDE_WEIGHTS", 1))


def builder_debug_include_fingerprints() -> bool:
    return bool(getattr(config, "BUILDER_AI_DEBUG_INCLUDE_FINGERPRINTS", 1))


def log_builder_runtime_action(engine, action: dict) -> None:
    if not builder_debug_enabled():
        return
    player = getattr(engine, "active_player", None)
    if player is None:
        return
    emit_builder_debug_line(
        engine,
        "RUNTIME",
        player=player,
        decision="runtime",
        pairs=(
            ("action", action.get("kind")),
            ("description", action.get("description")),
        ),
    )


def ensure_builder_weights_logged(engine) -> None:
    if not builder_debug_verbose() or not builder_debug_include_weights():
        return
    if getattr(engine, "_builder_ai_debug_weights_logged", False):
        return
    setattr(engine, "_builder_ai_debug_weights_logged", True)
    for module_name, weight_name, value in _iter_weight_rows():
        emit_builder_debug_line(
            engine,
            "AI WEIGHTS",
            player=getattr(engine, "active_player", None) or getattr(engine, "ai_player", None),
            decision="weights",
            pairs=(
                ("module", module_name),
                ("name", weight_name),
                ("value", value),
            ),
        )


def emit_builder_debug_line(engine, prefix: str, *, player=None, decision: str, phase: str | None = None, pairs: Iterable[tuple[str, object]] = ()) -> None:
    if not builder_debug_enabled():
        return
    actor = _actor_label(player)
    line_pairs: list[tuple[str, object]] = [
        ("turn", getattr(engine, "turn_number", "-")),
        ("actor", actor),
        ("phase", _phase_label(getattr(engine, "phase", phase) if phase is None else phase)),
        ("decision", decision),
        ("source", "simulation" if getattr(engine, "simulation_mode", False) else "game"),
    ]
    line_pairs.extend(pairs)
    payload = " ".join(f"{key}={_format_value(value)}" for key, value in line_pairs if value is not None)
    engine.log(f"[{prefix}] {payload}")


def log_builder_state(engine, player, *, decision: str, snapshot=None, enemy=None) -> None:
    if not builder_debug_verbose():
        return
    ensure_builder_weights_logged(engine)
    if snapshot is None:
        from .snapshot import build_builder_snapshot

        snapshot = build_builder_snapshot(player, engine)
    if enemy is None:
        enemy = engine.players[1 - player.player_id]
    from .cap_strategy import compute_builder_cap_context

    cap_context = compute_builder_cap_context(
        player,
        engine,
        creature_cap=getattr(engine, "BUILDER_CREATURE_CAP", 5),
        resource_budget=player.total_resources(),
    )
    emit_builder_debug_line(
        engine,
        "AI STATE",
        player=player,
        decision=decision,
        pairs=(
            ("own_life", snapshot.own_life),
            ("enemy_life", snapshot.enemy_life),
            ("own_res", f"{snapshot.own_ready_resources}/{snapshot.own_total_resources}"),
            ("enemy_res", f"{snapshot.enemy_ready_resources}/{snapshot.enemy_total_resources}"),
            ("res_cap", getattr(engine, "BUILDER_MAX_RESOURCES", "-")),
            ("own_slots", f"{snapshot.own_creature_count}/{getattr(engine, 'BUILDER_CREATURE_CAP', 5)}"),
            ("enemy_slots", f"{snapshot.enemy_creature_count}/{getattr(engine, 'BUILDER_CREATURE_CAP', 5)}"),
            ("own_board", snapshot.own_board_value),
            ("enemy_board", snapshot.enemy_board_value),
            ("survival_urgency", _call_optional("core.ai.builder.turn_policy", "_base_survival_pressure", snapshot)),
            ("cap_pressure", cap_context.cap_pressure),
            ("replacement_value", cap_context.replacement_value),
            ("best_replacement_value", cap_context.best_replacement_value),
            ("weakest_unit", cap_context.weakest_unit_id),
            ("weakest_unit_value", cap_context.weakest_unit_value),
        ),
    )
    enemy_units = list(enemy.battlefield)
    for side_name, owner, units in (("own", player, list(player.battlefield)), ("enemy", enemy, enemy_units)):
        for unit in sorted(units, key=lambda current: current.unit_id):
            can_attack, attack_reason = _attack_status(unit)
            can_block, block_reason = _block_status(unit, enemy_units if side_name == "own" else list(player.battlefield))
            emit_builder_debug_line(
                engine,
                "AI STATE",
                player=player,
                decision=decision,
                pairs=(
                    ("side", side_name),
                    ("unit", unit.unit_id),
                    ("owner", owner.player_id),
                    ("stats", f"{getattr(unit, 'aw', 0)}/{getattr(unit, 'vw', 0)}/{getattr(unit, 'sw', 0)}"),
                    ("hp", f"{getattr(unit, 'current_hp', 0)}/{getattr(unit, 'lw', 0)}"),
                    ("injured", max(0, getattr(unit, "lw", 0) - getattr(unit, "current_hp", 0))),
                    ("tapped", _is_tapped(unit)),
                    ("ready", _is_ready(unit)),
                    ("sick", _is_summoning_sick(unit)),
                    ("can_attack", can_attack),
                    ("attack_reason", attack_reason),
                    ("can_block", can_block),
                    ("block_reason", block_reason),
                ),
            )


def log_builder_fingerprint(engine, player, *, decision: str, before: tuple, after: tuple) -> None:
    if not builder_debug_verbose() or not builder_debug_include_fingerprints():
        return
    emit_builder_debug_line(engine, "AI STATE", player=player, decision=decision, pairs=(("fingerprint_before", before),))
    emit_builder_debug_line(
        engine,
        "AI STATE",
        player=player,
        decision=decision,
        pairs=(("fingerprint_after", after), ("unchanged", before == after)),
    )


def select_scored_rows(scored_rows: list[tuple[object, object]], *, top_n: int, mandatory_keys: set[tuple]) -> list[tuple[object, object]]:
    selected: list[tuple[object, object]] = []
    seen: set[tuple] = set()
    for row in scored_rows[:top_n]:
        key = _candidate_row_key(row[0])
        if key in seen:
            continue
        selected.append(row)
        seen.add(key)
    for row in scored_rows:
        key = _candidate_row_key(row[0])
        if key in mandatory_keys and key not in seen:
            selected.append(row)
            seen.add(key)
    selected.sort(key=lambda row: _scored_row_sort_key(row[0], row[1]), reverse=True)
    return selected


def turn_score_gap(decisions: list) -> tuple[float, object | None]:
    if len(decisions) < 2:
        return 0.0, None
    return round(decisions[0].score.total - decisions[1].score.total, builder_debug_precision()), decisions[1]


def score_delta_keys(primary_score, secondary_score, *, limit: int = 3) -> str:
    fields = [
        field_name
        for field_name, value in primary_score.__dict__.items()
        if isinstance(value, (int, float)) and field_name not in {"total", "baseline_attack_score", "projected_attack_score"}
    ]
    ranked = sorted(
        ((abs(getattr(primary_score, field_name, 0.0) - getattr(secondary_score, field_name, 0.0)), field_name) for field_name in fields),
        reverse=True,
    )
    parts = []
    for _, field_name in ranked[:limit]:
        delta = getattr(primary_score, field_name, 0.0) - getattr(secondary_score, field_name, 0.0)
        parts.append(f"{field_name}:{_format_float(delta, signed=True)}")
    return ",".join(parts) or "-"


def contribution_pairs(score, *, only_non_zero: bool = False) -> tuple[tuple[str, object], ...]:
    pairs: list[tuple[str, object]] = []
    for name, raw, weight, contribution in getattr(score, "debug_contributions", ()):
        if only_non_zero and abs(contribution) <= 1e-9:
            continue
        pairs.extend(
            (
                (f"{name}_raw", raw),
                (f"{name}_weight", weight),
                (f"{name}_contribution", contribution),
            )
        )
    return tuple(pairs)


def _candidate_row_key(candidate) -> tuple:
    if hasattr(candidate, "assignments"):
        return ("block", tuple(getattr(candidate, "assignments", ())))
    if hasattr(candidate, "attacker_ids"):
        return ("attack", tuple(getattr(candidate, "attacker_ids", ())), tuple(getattr(candidate, "enraged_targets", ())))
    if hasattr(candidate, "signature"):
        return ("build", tuple(getattr(candidate, "signature", ())))
    if hasattr(candidate, "action_kind"):
        current = getattr(candidate, "creature_candidate", None)
        signature = None if current is None else getattr(current, "signature", ())
        return ("turn", getattr(candidate, "action_kind", ""), signature)
    return ("unknown", repr(candidate))


def _scored_row_sort_key(candidate, score) -> tuple:
    return (getattr(score, "total", 0.0), _candidate_row_key(candidate))


def _format_value(value) -> str:
    if isinstance(value, float):
        return _format_float(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "-"
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if not items:
            return "[]"
        return "[" + ",".join(_format_value(item) for item in items) + "]"
    if isinstance(value, dict):
        items = sorted((str(key), value[key]) for key in value)
        return "{" + ",".join(f"{key}:{_format_value(current)}" for key, current in items) + "}"
    if isinstance(value, str):
        return value.replace(" ", "_")
    if hasattr(value, "value"):
        return str(getattr(value, "value"))
    return str(value)


def _format_float(value: float, *, signed: bool = False) -> str:
    precision = builder_debug_precision()
    spec = f"+.{precision}f" if signed else f".{precision}f"
    return format(float(value), spec)


def _actor_label(player) -> str:
    if player is None:
        return "-"
    return f"p{player.player_id}:{str(player.name).replace(' ', '_')}"


def _phase_label(phase: str | None) -> str:
    mapping = {
        PHASE_MAIN_1: "main",
        PHASE_BUILDER_ABILITY: "ability",
        PHASE_DECLARE_ATTACKERS: "attack",
        PHASE_DECLARE_BLOCKERS: "block",
    }
    return mapping.get(phase, str(phase).replace(" ", "_").lower() if phase is not None else "-")


def _is_tapped(unit) -> bool:
    return bool(getattr(unit, "tapped", False))


def _is_summoning_sick(unit) -> bool:
    return bool(getattr(unit, "summoning_sick", getattr(unit, "summoning_sickness", False)))


def _is_ready(unit) -> bool:
    if hasattr(unit, "is_ready"):
        return bool(unit.is_ready())
    return not _is_tapped(unit) and not _is_summoning_sick(unit)


def _attack_status(unit) -> tuple[bool, str]:
    if _is_tapped(unit):
        return False, "tapped"
    if _is_summoning_sick(unit) and not _has_ability(unit, Ability.HASTE):
        return False, "summoning_sick"
    return True, "-"


def _block_status(unit, enemy_units: list) -> tuple[bool, str]:
    if bool(getattr(unit, "cannot_block", False)):
        return False, "cannot_block"
    if _is_tapped(unit):
        return False, "tapped"
    if int(getattr(unit, "vw", 0)) <= 0:
        return False, "defense_zero"
    if not enemy_units:
        return True, "-"
    from .combat_eval import can_legally_block

    if any(can_legally_block(enemy, unit, require_ready=False) for enemy in enemy_units):
        return True, "-"
    return False, "no_legal_targets"


def _has_ability(unit, ability: Ability) -> bool:
    if hasattr(unit, "has_ability"):
        return bool(unit.has_ability(ability))
    return ability in set(getattr(unit, "abilities", ()))


def _iter_weight_rows() -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []
    builder_config = importlib.import_module("core.ai.builder.config")
    config_weights = getattr(builder_config, "BUILDER_AI_WEIGHTS")
    for field_name in sorted(config_weights.__dataclass_fields__):
        rows.append(("builder_config", field_name, float(getattr(config_weights, field_name))))

    module_specs = [
        ("attack_policy", "core.ai.builder.attack_policy"),
        ("block_policy", "core.ai.builder.block_policy"),
        ("cap_strategy", "core.ai.builder.cap_strategy"),
        ("scoring", "core.ai.builder.scoring"),
        ("turn_policy", "core.ai.builder.turn_policy"),
    ]
    for short_name, module_path in module_specs:
        module = importlib.import_module(module_path)
        for attr_name, value in inspect.getmembers(module):
            if not attr_name.isupper():
                continue
            if isinstance(value, (int, float)):
                if not BUILDER_ABILITIES_ENABLED and _weight_entry_is_ability_related(attr_name, attr_name):
                    continue
                rows.append((short_name, attr_name, float(value)))
                continue
            if isinstance(value, dict):
                for dict_key, dict_value in sorted(value.items(), key=lambda item: str(getattr(item[0], "value", item[0]))):
                    if not isinstance(dict_value, (int, float)):
                        continue
                    if not BUILDER_ABILITIES_ENABLED and _weight_entry_is_ability_related(attr_name, dict_key):
                        continue
                    rows.append((short_name, f"{attr_name}.{getattr(dict_key, 'value', dict_key)}", float(dict_value)))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def _weight_entry_is_ability_related(attr_name: str, dict_key) -> bool:
    if "ABILITY" in attr_name or "SYNERGY" in attr_name:
        return True
    if isinstance(dict_key, Ability):
        return True
    if isinstance(dict_key, str):
        lowered = dict_key.lower()
        if any(token in lowered for token in ("haste", "flying", "trample", "vigil", "life", "rage", "provoke", "touch")):
            return True
    return False


def _call_optional(module_name: str, attr_name: str, *args):
    module = importlib.import_module(module_name)
    fn = getattr(module, attr_name)
    return fn(*args)
