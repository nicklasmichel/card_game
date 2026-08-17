from __future__ import annotations

from dataclasses import asdict, dataclass
from multiprocessing import get_context
from queue import Empty
from random import Random
from statistics import fmean
from time import monotonic, perf_counter
from typing import Callable, Iterable

from core.builder_rules import builder_creature_stat_cost
from core.ai.builder.combat_eval import build_candidate_combatant_view, can_legally_block
from core.ai_logic import SimpleAI
from core.config import STARTING_LIFE
from core.game_logic import GameEngine
from core.models import (
    ControllerKind,
    PHASE_BUILDER_ABILITY,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
)
from diagnostics.invariants import GameInvariantError, validate_game_invariants, validate_prepared_action


ProgressCallback = Callable[[dict], None]


@dataclass(frozen=True)
class SoakConfig:
    starting_life: int = STARTING_LIFE
    decision_timeout_seconds: float = 30.0
    game_timeout_seconds: float = 300.0
    max_turns: int = 200
    max_steps: int = 2_000
    slow_snapshot_threshold_ms: float = 1_000.0

    def __post_init__(self) -> None:
        if self.starting_life <= 0:
            raise ValueError("starting_life must be positive")
        if self.decision_timeout_seconds <= 0:
            raise ValueError("decision_timeout_seconds must be positive")
        if self.game_timeout_seconds <= 0:
            raise ValueError("game_timeout_seconds must be positive")
        if self.max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if self.slow_snapshot_threshold_ms < 0:
            raise ValueError("slow_snapshot_threshold_ms must not be negative")


@dataclass(frozen=True)
class DecisionTiming:
    turn: int
    player_id: int
    phase: str
    action: str
    elapsed_ms: float
    search_metrics: dict[str, object] | None = None
    state_snapshot: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionTiming":
        return cls(
            turn=int(data["turn"]),
            player_id=int(data["player_id"]),
            phase=str(data["phase"]),
            action=str(data["action"]),
            elapsed_ms=float(data["elapsed_ms"]),
            search_metrics=data.get("search_metrics"),
            state_snapshot=data.get("state_snapshot"),
        )


@dataclass(frozen=True)
class BuilderBuildSample:
    turn: int
    player_id: int
    aw: int
    vw: int
    sw: int
    lw: int
    primary_ability: str
    has_haste: bool
    stat_cost: int
    total_cost: int
    planned_immediate_attack: bool
    planned_immediate_block: bool = False
    projected_counter_damage: float = 0.0

    @property
    def combination(self) -> str:
        return f"{self.primary_ability}+HASTE" if self.has_haste else self.primary_ability

    @classmethod
    def from_dict(cls, data: dict) -> "BuilderBuildSample":
        return cls(
            turn=int(data["turn"]),
            player_id=int(data["player_id"]),
            aw=int(data["aw"]),
            vw=int(data["vw"]),
            sw=int(data["sw"]),
            lw=int(data["lw"]),
            primary_ability=str(data["primary_ability"]),
            has_haste=bool(data["has_haste"]),
            stat_cost=int(data["stat_cost"]),
            total_cost=int(data["total_cost"]),
            planned_immediate_attack=bool(data.get("planned_immediate_attack", False)),
            planned_immediate_block=bool(data.get("planned_immediate_block", False)),
            projected_counter_damage=float(data.get("projected_counter_damage", 0.0)),
        )


@dataclass(frozen=True)
class SoakGameResult:
    seed: int
    completed: bool
    winner: str | None
    turns: int
    steps: int
    elapsed_ms: float
    decision_timings: tuple[DecisionTiming, ...]
    last_phase: str
    player_life: tuple[int, int]
    builder_builds: tuple[BuilderBuildSample, ...] = ()
    final_snapshot: dict | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def max_decision_ms(self) -> float:
        return max((sample.elapsed_ms for sample in self.decision_timings), default=0.0)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["decision_timings"] = [asdict(sample) for sample in self.decision_timings]
        data["player_life"] = list(self.player_life)
        data["builder_builds"] = [asdict(sample) for sample in self.builder_builds]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SoakGameResult":
        return cls(
            seed=int(data["seed"]),
            completed=bool(data["completed"]),
            winner=data.get("winner"),
            turns=int(data["turns"]),
            steps=int(data["steps"]),
            elapsed_ms=float(data["elapsed_ms"]),
            decision_timings=tuple(
                DecisionTiming.from_dict(sample) for sample in data.get("decision_timings", ())
            ),
            last_phase=str(data.get("last_phase", "unknown")),
            player_life=tuple(int(value) for value in data.get("player_life", (0, 0))),
            builder_builds=tuple(
                BuilderBuildSample.from_dict(sample) for sample in data.get("builder_builds", ())
            ),
            final_snapshot=data.get("final_snapshot"),
            failure_code=data.get("failure_code"),
            failure_message=data.get("failure_message"),
        )


@dataclass(frozen=True)
class SoakSummary:
    config: SoakConfig
    results: tuple[SoakGameResult, ...]

    @property
    def failures(self) -> tuple[SoakGameResult, ...]:
        return tuple(result for result in self.results if not result.completed)

    @property
    def successful(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict:
        timed_decisions = [
            (result.seed, sample)
            for result in self.results
            for sample in result.decision_timings
        ]
        decisions = [sample for _seed, sample in timed_decisions]
        completed = [result for result in self.results if result.completed]
        outcomes: dict[str, int] = {}
        for result in completed:
            outcome = result.winner or "Unknown"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        phase_groups: dict[str, list[DecisionTiming]] = {}
        action_groups: dict[str, list[DecisionTiming]] = {}
        for sample in decisions:
            phase_groups.setdefault(sample.phase, []).append(sample)
            action_groups.setdefault(sample.action, []).append(sample)
        budget_ms = self.config.decision_timeout_seconds * 1_000
        decision_report = _timing_report(decisions, budget_ms)
        decision_report["by_phase"] = {
            name: _timing_report(samples, budget_ms)
            for name, samples in sorted(phase_groups.items())
        }
        decision_report["by_action"] = {
            name: _timing_report(samples, budget_ms)
            for name, samples in sorted(action_groups.items())
        }
        decision_report["search"] = _search_report(decisions)
        decision_report["slowest"] = [
            {
                "seed": seed,
                "turn": sample.turn,
                "player_id": sample.player_id,
                "phase": sample.phase,
                "action": sample.action,
                "elapsed_ms": round(sample.elapsed_ms, 2),
                "search_metrics": sample.search_metrics,
                "state_snapshot": sample.state_snapshot,
            }
            for seed, sample in sorted(
                timed_decisions,
                key=lambda item: item[1].elapsed_ms,
                reverse=True,
            )[:20]
        ]
        build_report = _builder_build_report(self.results)
        return {
            "config": asdict(self.config),
            "games": {
                "requested": len(self.results),
                "completed": len(completed),
                "failed": len(self.failures),
                "completion_rate": round(len(completed) / len(self.results), 4) if self.results else 0.0,
                "average_turns": round(fmean(result.turns for result in completed), 2) if completed else 0.0,
                "max_turns": max((result.turns for result in completed), default=0),
                "average_elapsed_ms": round(fmean(result.elapsed_ms for result in self.results), 2)
                if self.results
                else 0.0,
                "outcomes": outcomes,
            },
            "decisions": decision_report,
            "builder_builds": build_report,
            "failures": [
                {
                    "seed": result.seed,
                    "code": result.failure_code,
                    "message": result.failure_message,
                    "turn": result.turns,
                    "phase": result.last_phase,
                    "state_snapshot": result.final_snapshot,
                }
                for result in self.failures
            ],
            "results": [result.to_dict() for result in self.results],
        }


class _SoakFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _timing_report(samples: Iterable[DecisionTiming], budget_ms: float) -> dict[str, object]:
    values = [sample.elapsed_ms for sample in samples]
    return {
        "count": len(values),
        "average_ms": round(fmean(values), 2) if values else 0.0,
        "p50_ms": round(_percentile(values, 50), 2),
        "p95_ms": round(_percentile(values, 95), 2),
        "p99_ms": round(_percentile(values, 99), 2),
        "max_ms": round(max(values), 2) if values else 0.0,
        "over_budget": sum(value > budget_ms for value in values),
    }


def _search_report(samples: Iterable[DecisionTiming]) -> dict[str, object]:
    stop_reasons: dict[str, int] = {}
    counters: dict[str, list[float]] = {}
    for sample in samples:
        metrics = sample.search_metrics or {}
        stop_reason = str(metrics.get("stop_reason", "unavailable"))
        stop_reasons[stop_reason] = stop_reasons.get(stop_reason, 0) + 1
        for name, value in metrics.items():
            if name in {"elapsed_ms", "stop_reason"} or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            counters.setdefault(name, []).append(float(value))
    return {
        "stop_reasons": dict(sorted(stop_reasons.items())),
        "work_counters": {
            name: {
                "samples": len(values),
                "total": round(sum(values), 2),
                "average": round(fmean(values), 2),
                "max": round(max(values), 2),
            }
            for name, values in sorted(counters.items())
        },
    }


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * max(0.0, min(100.0, percentile)) / 100.0
    lower_index = int(position)
    upper_index = min(len(ordered) - 1, lower_index + 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _builder_build_report(results: Iterable[SoakGameResult]) -> dict[str, object]:
    samples = [sample for result in results for sample in result.builder_builds]
    haste_samples = [sample for sample in samples if sample.has_haste]
    haste_attack_count = sum(sample.planned_immediate_attack for sample in haste_samples)
    haste_block_count = sum(sample.planned_immediate_block for sample in haste_samples)
    haste_role_count = sum(
        sample.planned_immediate_attack or sample.planned_immediate_block
        for sample in haste_samples
    )
    primary_counts: dict[str, int] = {}
    combination_counts: dict[str, int] = {}
    for sample in samples:
        primary_counts[sample.primary_ability] = primary_counts.get(sample.primary_ability, 0) + 1
        combination_counts[sample.combination] = combination_counts.get(sample.combination, 0) + 1

    result_groups: dict[str, list[BuilderBuildSample]] = {"winner": [], "loser": [], "draw": []}
    for result in results:
        winner_id = None
        if result.winner == "Player 1":
            winner_id = 0
        elif result.winner == "Player 2":
            winner_id = 1
        for sample in result.builder_builds:
            if winner_id is None:
                result_groups["draw"].append(sample)
            elif sample.player_id == winner_id:
                result_groups["winner"].append(sample)
            else:
                result_groups["loser"].append(sample)

    return {
        "count": len(samples),
        "haste_count": len(haste_samples),
        "haste_rate": round(len(haste_samples) / len(samples), 4) if samples else 0.0,
        "haste_immediate_attack_count": haste_attack_count,
        "haste_immediate_attack_rate": (
            round(haste_attack_count / len(haste_samples), 4)
            if haste_samples
            else 0.0
        ),
        "haste_immediate_block_count": haste_block_count,
        "haste_immediate_block_rate": round(haste_block_count / len(haste_samples), 4) if haste_samples else 0.0,
        "haste_immediate_role_count": haste_role_count,
        "haste_immediate_role_rate": round(haste_role_count / len(haste_samples), 4) if haste_samples else 0.0,
        "haste_without_immediate_role_count": len(haste_samples) - haste_role_count,
        "primary_abilities": dict(sorted(primary_counts.items())),
        "combinations": dict(sorted(combination_counts.items())),
        "profiles": {
            "haste": _builder_profile_report(haste_samples),
            "no_haste": _builder_profile_report(sample for sample in samples if not sample.has_haste),
        },
        "by_result": {
            name: _builder_result_group_report(group)
            for name, group in result_groups.items()
        },
    }


def _builder_profile_report(samples: Iterable[BuilderBuildSample]) -> dict[str, object]:
    resolved = list(samples)
    if not resolved:
        return {
            "count": 0,
            "average_stats": {"aw": 0.0, "vw": 0.0, "sw": 0.0, "lw": 0.0},
            "average_stat_cost": 0.0,
            "average_total_cost": 0.0,
        }
    return {
        "count": len(resolved),
        "average_stats": {
            stat: round(fmean(getattr(sample, stat) for sample in resolved), 2)
            for stat in ("aw", "vw", "sw", "lw")
        },
        "average_stat_cost": round(fmean(sample.stat_cost for sample in resolved), 2),
        "average_total_cost": round(fmean(sample.total_cost for sample in resolved), 2),
    }


def _builder_result_group_report(samples: Iterable[BuilderBuildSample]) -> dict[str, object]:
    resolved = list(samples)
    haste_count = sum(sample.has_haste for sample in resolved)
    return {
        "count": len(resolved),
        "haste_count": haste_count,
        "haste_rate": round(haste_count / len(resolved), 4) if resolved else 0.0,
    }


def _phase_label(phase: str) -> str:
    return {
        PHASE_MAIN_1: "main",
        PHASE_BUILDER_CREATURE: "creature_building",
        PHASE_BUILDER_ABILITY: "ability",
        PHASE_DECLARE_ATTACKERS: "attackers",
        PHASE_DECLARE_BLOCKERS: "blockers",
        PHASE_DICE_BATTLE: "dice_combat",
        PHASE_GAME_OVER: "game_over",
    }.get(phase, str(phase))


def _state_snapshot(engine) -> dict:
    return {
        "turn": int(getattr(engine, "turn_number", 0)),
        "stalled_turns": int(getattr(engine, "builder_stalled_turns", 0)),
        "player_damage_stalled_turns": int(
            getattr(engine, "builder_player_damage_stalled_turns", getattr(engine, "builder_stalled_turns", 0))
        ),
        "phase": _phase_label(getattr(engine, "phase", "unknown")),
        "active_player_id": int(getattr(engine, "active_player_index", 0)),
        "players": [
            {
                "player_id": player.player_id,
                "life": player.life,
                "resources": {
                    "ready": player.available_resources(),
                    "total": player.total_resources(),
                },
                "creatures": [
                    {
                        "id": creature.unit_id,
                        "stats": [creature.aw, creature.vw, creature.sw, creature.lw],
                        "current_life": creature.current_hp,
                        "ability": (
                            getattr(creature.builder_ability, "name", None)
                            if creature.builder_ability is not None
                            else None
                        ),
                        "abilities": sorted(ability.name for ability in creature.abilities),
                        "tapped": bool(creature.tapped),
                        "summoning_sick": bool(creature.summoning_sick),
                    }
                    for creature in player.battlefield
                ],
            }
            for player in getattr(engine, "players", ())
        ],
        "selected_attackers": list(getattr(engine, "selected_attackers", ())),
        "block_assignments": [
            [attacker_id, blocker_id]
            for attacker_id, blocker_id in sorted(getattr(engine, "block_assignments", {}).items())
        ],
    }


def _clear_search_metrics(engine) -> None:
    for attribute in ("_last_builder_search_metrics", "_last_builder_block_search_metrics"):
        if hasattr(engine.ai, attribute):
            delattr(engine.ai, attribute)


def _search_metrics_for_phase(engine, phase: str) -> dict[str, object]:
    attribute = (
        "_last_builder_block_search_metrics"
        if phase == PHASE_DECLARE_BLOCKERS
        else "_last_builder_search_metrics"
    )
    metrics = getattr(engine.ai, attribute, None)
    if not isinstance(metrics, dict):
        return {"stop_reason": "cached_or_unavailable"}
    return {
        str(name): value
        for name, value in metrics.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }


def _builder_build_sample(engine, action: dict) -> BuilderBuildSample | None:
    if action.get("kind") != "builder_create_creature":
        return None
    plan = action.get("plan")
    if not isinstance(plan, dict):
        return None
    abilities = tuple(plan.get("abilities", ()))
    ability_names = {
        getattr(ability, "name", str(ability)).upper()
        for ability in abilities
    }
    primary = plan.get("ability")
    primary_name = getattr(primary, "name", str(primary)).upper() if primary is not None else ""
    if primary_name in {"", "NONE"}:
        primary_name = next((name for name in sorted(ability_names) if name != "HASTE"), "NONE")
    if primary_name == "VIGILANT":
        primary_name = "VIGILANCE"
    has_haste = bool(plan.get("haste", False)) or "HASTE" in ability_names
    aw = int(plan.get("aw", 0))
    vw = int(plan.get("vw", 0))
    sw = int(plan.get("sw", 0))
    lw = int(plan.get("lw", 1))
    turn_decision = action.get("turn_decision")
    predicted_attack = getattr(turn_decision, "predicted_attack_decision", None)
    predicted_candidate = getattr(predicted_attack, "candidate", None)
    immediate_attack = any(
        attacker_id < 0
        for attacker_id in getattr(predicted_candidate, "attacker_ids", ())
    )
    predicted_score = getattr(predicted_attack, "score", None)
    counter_attacker_ids = tuple(getattr(predicted_score, "projected_counter_attackers", ()))
    creature_candidate = getattr(getattr(turn_decision, "action_candidate", None), "creature_candidate", None)
    planned_immediate_block = False
    remains_ready = not immediate_attack or primary_name == "VIGILANCE"
    if has_haste and remains_ready and creature_candidate is not None:
        candidate_view = build_candidate_combatant_view(creature_candidate, ready=True)
        counterattackers = [
            attacker
            for attacker in (engine.get_unit_by_id(attacker_id) for attacker_id in counter_attacker_ids)
            if attacker is not None
        ]
        if not counterattackers:
            counterattackers = [
                attacker
                for attacker in engine.players[1 - engine.active_player.player_id].battlefield
                if attacker.current_hp > 0 and attacker.sw > 0
            ]
        planned_immediate_block = any(
            can_legally_block(attacker, candidate_view, require_ready=True)
            for attacker in counterattackers
        )
    return BuilderBuildSample(
        turn=int(getattr(engine, "turn_number", 0)),
        player_id=int(engine.active_player.player_id),
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
        primary_ability=primary_name,
        has_haste=has_haste,
        stat_cost=builder_creature_stat_cost(aw=aw, vw=vw, sw=sw, lw=lw),
        total_cost=int(plan.get("cost", 0)),
        planned_immediate_attack=immediate_attack,
        planned_immediate_block=planned_immediate_block,
        projected_counter_damage=float(getattr(predicted_score, "projected_counter_damage", 0.0)),
    )


def _create_soak_engine(
    seed: int,
    *,
    starting_life: int = STARTING_LIFE,
    starting_player_id: int | None = None,
) -> GameEngine:
    engine = GameEngine(auto_start=False)
    engine.seed = seed
    engine.rng = Random(seed)
    engine.ai = SimpleAI(engine.rng)
    engine.game_id = f"soak-{seed}"
    engine._write_log_line = lambda _message: None
    engine.debug_log = lambda _message: None
    engine.simulation_mode = True
    engine.initialize_builder_game(
        starting_player_id=seed % 2 if starting_player_id is None else starting_player_id,
        auto_begin=True,
        log_start=False,
    )
    for player in engine.players:
        player.life = starting_life
    engine.statistics = None
    engine.log_messages.clear()
    engine.pending_log_file_lines.clear()
    for player in engine.players:
        player.set_controller(ControllerKind.AI)
    return engine


def _state_progress_signature(engine) -> tuple:
    players = tuple(
        (
            player.player_id,
            player.life,
            tuple((resource.resource_id, resource.tapped) for resource in player.resources),
            tuple(
                (
                    creature.unit_id,
                    creature.aw,
                    creature.vw,
                    creature.sw,
                    creature.lw,
                    creature.current_hp,
                    creature.tapped,
                    creature.summoning_sick,
                )
                for creature in player.battlefield
            ),
        )
        for player in engine.players
    )
    return (
        engine.turn_number,
        engine.active_player_index,
        engine.phase,
        players,
        tuple(engine.selected_attackers),
        tuple(sorted(engine.block_assignments.items())),
        tuple(battle.attacker_id for battle in engine.pending_dice_battles),
        tuple(engine.combat_queue),
        tuple(attack.attacker_id for attack in engine.pending_direct_attacks),
    )


def _failure_result(
    *,
    seed: int,
    engine,
    steps: int,
    started_at: float,
    samples: list[DecisionTiming],
    builder_builds: list[BuilderBuildSample],
    code: str,
    message: str,
) -> SoakGameResult:
    players = list(getattr(engine, "players", ()))
    life = tuple(player.life for player in players[:2])
    if len(life) != 2:
        life = (0, 0)
    return SoakGameResult(
        seed=seed,
        completed=False,
        winner=None,
        turns=int(getattr(engine, "turn_number", 0)),
        steps=steps,
        elapsed_ms=(perf_counter() - started_at) * 1_000,
        decision_timings=tuple(samples),
        last_phase=_phase_label(getattr(engine, "phase", "unknown")),
        player_life=life,
        builder_builds=tuple(builder_builds),
        final_snapshot=_state_snapshot(engine),
        failure_code=code,
        failure_message=message,
    )


def run_single_game(
    seed: int,
    config: SoakConfig | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> SoakGameResult:
    """Run one deterministic AI-vs-AI game in the current process."""
    config = config or SoakConfig()
    started_at = perf_counter()
    engine = _create_soak_engine(seed, starting_life=config.starting_life)
    samples: list[DecisionTiming] = []
    builder_builds: list[BuilderBuildSample] = []
    steps = 0
    try:
        validate_game_invariants(engine)
        while engine.phase != PHASE_GAME_OVER:
            if steps >= config.max_steps:
                raise _SoakFailure("step_limit", f"game exceeded {config.max_steps} engine steps")
            if engine.turn_number > config.max_turns:
                raise _SoakFailure("turn_limit", f"game exceeded {config.max_turns} turns")

            steps += 1
            phase = engine.phase
            before = _state_progress_signature(engine)
            if phase in {PHASE_MAIN_1, PHASE_BUILDER_ABILITY, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS}:
                decision_state = _state_snapshot(engine)
                started_event = {
                    "event": "decision_started",
                    "seed": seed,
                    "step": steps,
                    "turn": engine.turn_number,
                    "player_id": (
                        engine.defending_player.player_id
                        if phase == PHASE_DECLARE_BLOCKERS
                        else engine.active_player.player_id
                    ),
                    "phase": _phase_label(phase),
                    "state_snapshot": decision_state,
                }
                if progress_callback is not None:
                    progress_callback(started_event)
                _clear_search_metrics(engine)
                decision_started_at = perf_counter()
                prepared = engine.prepare_ai_turn_action()
                elapsed_ms = (perf_counter() - decision_started_at) * 1_000
                action = engine.pending_ai_action
                search_metrics = _search_metrics_for_phase(engine, phase)
                sample = DecisionTiming(
                    turn=engine.turn_number,
                    player_id=started_event["player_id"],
                    phase=started_event["phase"],
                    action=str(action.get("kind", "none")) if isinstance(action, dict) else "none",
                    elapsed_ms=elapsed_ms,
                    search_metrics=search_metrics,
                    state_snapshot=(
                        decision_state
                        if elapsed_ms >= config.slow_snapshot_threshold_ms
                        else None
                    ),
                )
                samples.append(sample)
                if progress_callback is not None:
                    progress_callback({"event": "decision_finished", "sample": asdict(sample)})
                if elapsed_ms > config.decision_timeout_seconds * 1_000:
                    raise _SoakFailure(
                        "decision_timeout",
                        f"turn {engine.turn_number} {sample.phase} decision took {elapsed_ms:.1f} ms",
                    )
                if not prepared or action is None:
                    raise _SoakFailure(
                        "ai_prepare_failed",
                        f"AI produced no action in turn {engine.turn_number}, phase {sample.phase}",
                    )
                validate_prepared_action(engine, action)
                build_sample = _builder_build_sample(engine, action)
                battlefield_size = len(engine.active_player.battlefield)
                engine.execute_prepared_ai_action()
                if build_sample is not None and len(engine.players[build_sample.player_id].battlefield) > battlefield_size:
                    builder_builds.append(build_sample)
                    if progress_callback is not None:
                        progress_callback({"event": "builder_build", "sample": asdict(build_sample)})
            elif phase == PHASE_DICE_BATTLE:
                engine.end_dice_battle()
            else:
                raise _SoakFailure("unsupported_phase", f"runner cannot advance phase {phase!r}")

            validate_game_invariants(engine)
            if engine.phase != PHASE_GAME_OVER and _state_progress_signature(engine) == before:
                raise _SoakFailure(
                    "no_progress",
                    f"turn {engine.turn_number} remained unchanged in phase {_phase_label(engine.phase)}",
                )

        validate_game_invariants(engine)
        if engine.players[0].life <= 0 and engine.players[1].life <= 0:
            winner = "Draw"
        elif engine.players[0].life > 0:
            winner = engine.players[0].name
        else:
            winner = engine.players[1].name
        return SoakGameResult(
            seed=seed,
            completed=True,
            winner=winner,
            turns=engine.turn_number,
            steps=steps,
            elapsed_ms=(perf_counter() - started_at) * 1_000,
            decision_timings=tuple(samples),
            last_phase=_phase_label(engine.phase),
            player_life=(engine.players[0].life, engine.players[1].life),
            builder_builds=tuple(builder_builds),
            final_snapshot=_state_snapshot(engine),
        )
    except GameInvariantError as error:
        return _failure_result(
            seed=seed,
            engine=engine,
            steps=steps,
            started_at=started_at,
            samples=samples,
            builder_builds=builder_builds,
            code="invariant_violation",
            message=str(error),
        )
    except _SoakFailure as error:
        return _failure_result(
            seed=seed,
            engine=engine,
            steps=steps,
            started_at=started_at,
            samples=samples,
            builder_builds=builder_builds,
            code=error.code,
            message=str(error),
        )
    except Exception as error:
        return _failure_result(
            seed=seed,
            engine=engine,
            steps=steps,
            started_at=started_at,
            samples=samples,
            builder_builds=builder_builds,
            code="exception",
            message=f"{type(error).__name__}: {error}",
        )
    finally:
        engine.cancel_ai_thinking()


def _isolated_worker(queue, seed: int, config: SoakConfig) -> None:
    def emit(event: dict) -> None:
        queue.put(event)

    result = run_single_game(seed, config, progress_callback=emit)
    queue.put({"event": "result", "result": result.to_dict()})


def _terminate_process(process) -> None:
    if process.is_alive():
        process.terminate()
    process.join(timeout=2.0)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(timeout=2.0)


def _watchdog_failure(
    *,
    seed: int,
    code: str,
    message: str,
    elapsed_ms: float,
    latest_event: dict | None,
    samples: list[DecisionTiming],
    builder_builds: list[BuilderBuildSample],
) -> SoakGameResult:
    return SoakGameResult(
        seed=seed,
        completed=False,
        winner=None,
        turns=int((latest_event or {}).get("turn", 0)),
        steps=int((latest_event or {}).get("step", 0)),
        elapsed_ms=elapsed_ms,
        decision_timings=tuple(samples),
        last_phase=str((latest_event or {}).get("phase", "unknown")),
        player_life=(0, 0),
        builder_builds=tuple(builder_builds),
        final_snapshot=(latest_event or {}).get("state_snapshot"),
        failure_code=code,
        failure_message=message,
    )


def run_single_game_isolated(seed: int, config: SoakConfig | None = None) -> SoakGameResult:
    """Run a game in a child process so a stuck AI calculation can be terminated."""
    config = config or SoakConfig()
    context = get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_isolated_worker, args=(queue, seed, config), daemon=True)
    started_at = monotonic()
    decision_started_at: float | None = None
    latest_event: dict | None = None
    samples: list[DecisionTiming] = []
    builder_builds: list[BuilderBuildSample] = []
    process.start()
    try:
        while True:
            elapsed = monotonic() - started_at
            if elapsed >= config.game_timeout_seconds:
                _terminate_process(process)
                return _watchdog_failure(
                    seed=seed,
                    code="game_timeout",
                    message=f"game exceeded {config.game_timeout_seconds:.1f} seconds",
                    elapsed_ms=elapsed * 1_000,
                    latest_event=latest_event,
                    samples=samples,
                    builder_builds=builder_builds,
                )
            if decision_started_at is not None:
                decision_elapsed = monotonic() - decision_started_at
                if decision_elapsed >= config.decision_timeout_seconds:
                    _terminate_process(process)
                    return _watchdog_failure(
                        seed=seed,
                        code="decision_timeout",
                        message=(
                            f"turn {(latest_event or {}).get('turn', 0)} "
                            f"{(latest_event or {}).get('phase', 'unknown')} decision exceeded "
                            f"{config.decision_timeout_seconds:.1f} seconds"
                        ),
                        elapsed_ms=(monotonic() - started_at) * 1_000,
                        latest_event=latest_event,
                        samples=samples,
                        builder_builds=builder_builds,
                    )

            wait_seconds = min(0.25, max(0.01, config.game_timeout_seconds - elapsed))
            if decision_started_at is not None:
                wait_seconds = min(
                    wait_seconds,
                    max(0.01, config.decision_timeout_seconds - (monotonic() - decision_started_at)),
                )
            try:
                message = queue.get(timeout=wait_seconds)
            except Empty:
                if not process.is_alive():
                    try:
                        message = queue.get_nowait()
                    except Empty:
                        return _watchdog_failure(
                            seed=seed,
                            code="worker_exit",
                            message=f"worker exited with code {process.exitcode} without a result",
                            elapsed_ms=(monotonic() - started_at) * 1_000,
                            latest_event=latest_event,
                            samples=samples,
                            builder_builds=builder_builds,
                        )
                    else:
                        pass
                else:
                    continue

            event = message.get("event")
            if event == "decision_started":
                latest_event = message
                decision_started_at = monotonic()
            elif event == "decision_finished":
                samples.append(DecisionTiming.from_dict(message["sample"]))
                decision_started_at = None
            elif event == "builder_build":
                builder_builds.append(BuilderBuildSample.from_dict(message["sample"]))
            elif event == "result":
                process.join(timeout=2.0)
                return SoakGameResult.from_dict(message["result"])
    finally:
        _terminate_process(process)
        queue.close()
        queue.join_thread()


def run_soak(
    seeds: Iterable[int],
    config: SoakConfig | None = None,
    *,
    isolated: bool = True,
    result_callback: Callable[[int, int, SoakGameResult], None] | None = None,
) -> SoakSummary:
    config = config or SoakConfig()
    resolved_seeds = tuple(int(seed) for seed in seeds)
    results: list[SoakGameResult] = []
    runner = run_single_game_isolated if isolated else run_single_game
    for index, seed in enumerate(resolved_seeds, start=1):
        result = runner(seed, config)
        results.append(result)
        if result_callback is not None:
            result_callback(index, len(resolved_seeds), result)
    return SoakSummary(config=config, results=tuple(results))
