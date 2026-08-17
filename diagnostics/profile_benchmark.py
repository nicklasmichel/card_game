from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from random import Random
from statistics import fmean
from time import perf_counter
from typing import Callable, Iterable

from core.ai.builder.combat_eval import estimate_dice_win_probabilities
from core.builder_rules import BUILDER_CREATURE_CAP, BUILDER_CREATURE_STAT_CAP
from core.config import STARTING_LIFE
from core.models import (
    PHASE_BUILDER_ABILITY,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
)
from diagnostics.invariants import GameInvariantError, validate_game_invariants, validate_prepared_action
from diagnostics.soak import (
    BuilderBuildSample,
    DecisionTiming,
    _builder_build_sample,
    _clear_search_metrics,
    _create_soak_engine,
    _phase_label,
    _search_metrics_for_phase,
    _state_progress_signature,
    _state_snapshot,
)


PROFILE_NAMES = ("aggressive", "defensive", "balanced", "random")
TARGET_PLAYER_ID = 1
ProgressCallback = Callable[[dict], None]


@dataclass(frozen=True)
class ProfileBenchmarkConfig:
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
class ResourceCurveSample:
    turn: int
    target_resources: int
    opponent_resources: int
    target_board: int
    opponent_board: int


@dataclass(frozen=True)
class DiceCalibrationSample:
    turn: int
    target_role: str
    expected_win_probability: float
    actual_win: int
    attacker_aw: int
    blocker_vw: int


@dataclass(frozen=True)
class DecisionAudit:
    turn: int
    phase: str
    code: str
    severity: str
    detail: str
    chosen_score: float | None = None
    alternative_score: float | None = None


@dataclass(frozen=True)
class ProfileGameResult:
    profile: str
    seed: int
    starting_player_id: int
    completed: bool
    winner_id: int | None
    turns: int
    steps: int
    elapsed_ms: float
    player_life: tuple[int, int]
    target_damage_to_player: int
    opponent_damage_to_player: int
    target_creature_kills: int
    target_creature_deaths: int
    target_attack_phases: int
    target_no_attack_count: int
    target_declared_attackers: int
    target_full_board_passes: int
    target_main_actions: dict[str, int]
    target_builds: tuple[BuilderBuildSample, ...]
    opponent_builds: tuple[BuilderBuildSample, ...]
    resource_curve: tuple[ResourceCurveSample, ...]
    dice_samples: tuple[DiceCalibrationSample, ...]
    decision_audits: tuple[DecisionAudit, ...]
    decision_timings: tuple[DecisionTiming, ...]
    final_snapshot: dict | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def target_won(self) -> bool:
        return self.completed and self.winner_id == TARGET_PLAYER_ID

    def to_dict(self) -> dict:
        data = asdict(self)
        data["player_life"] = list(self.player_life)
        data["target_won"] = self.target_won
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileGameResult":
        return cls(
            profile=str(data["profile"]),
            seed=int(data["seed"]),
            starting_player_id=int(data["starting_player_id"]),
            completed=bool(data["completed"]),
            winner_id=(None if data.get("winner_id") is None else int(data["winner_id"])),
            turns=int(data["turns"]),
            steps=int(data["steps"]),
            elapsed_ms=float(data["elapsed_ms"]),
            player_life=tuple(int(value) for value in data["player_life"]),
            target_damage_to_player=int(data["target_damage_to_player"]),
            opponent_damage_to_player=int(data["opponent_damage_to_player"]),
            target_creature_kills=int(data["target_creature_kills"]),
            target_creature_deaths=int(data["target_creature_deaths"]),
            target_attack_phases=int(data["target_attack_phases"]),
            target_no_attack_count=int(data["target_no_attack_count"]),
            target_declared_attackers=int(data["target_declared_attackers"]),
            target_full_board_passes=int(data["target_full_board_passes"]),
            target_main_actions={str(name): int(count) for name, count in data["target_main_actions"].items()},
            target_builds=tuple(BuilderBuildSample.from_dict(sample) for sample in data.get("target_builds", ())),
            opponent_builds=tuple(BuilderBuildSample.from_dict(sample) for sample in data.get("opponent_builds", ())),
            resource_curve=tuple(ResourceCurveSample(**sample) for sample in data.get("resource_curve", ())),
            dice_samples=tuple(DiceCalibrationSample(**sample) for sample in data.get("dice_samples", ())),
            decision_audits=tuple(DecisionAudit(**sample) for sample in data.get("decision_audits", ())),
            decision_timings=tuple(DecisionTiming.from_dict(sample) for sample in data.get("decision_timings", ())),
            final_snapshot=data.get("final_snapshot"),
            failure_code=data.get("failure_code"),
            failure_message=data.get("failure_message"),
        )


class _BenchmarkFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FixedOpponentProfile:
    """Small deterministic policies used as independent benchmark opponents.

    These policies intentionally do not call the production AI.  They are not
    meant to be optimal; each supplies a stable pressure pattern that makes a
    regression in the production AI reproducible.
    """

    def __init__(self, name: str, seed: int) -> None:
        if name not in PROFILE_NAMES:
            raise ValueError(f"unknown opponent profile {name!r}")
        self.name = name
        salt = PROFILE_NAMES.index(name) + 1
        self.rng = Random((seed + 1) * 1009 + salt * 7919)
        self.build_number = 0

    def prepare_action(self, engine) -> dict:
        if engine.phase == PHASE_MAIN_1:
            return self._main_action(engine)
        if engine.phase == PHASE_BUILDER_ABILITY:
            return self._advance_to_combat(engine)
        if engine.phase == PHASE_DECLARE_ATTACKERS:
            return self._attack_action(engine)
        if engine.phase == PHASE_DECLARE_BLOCKERS:
            return self._block_action(engine)
        raise ValueError(f"profile cannot act in phase {engine.phase!r}")

    @staticmethod
    def _advance_to_combat(engine) -> dict:
        has_attackers = bool(engine.available_attackers(engine.active_player))
        return {
            "kind": "to_combat" if has_attackers else "end_turn",
            "description": "Benchmark profile advances the turn.",
        }

    def _main_action(self, engine) -> dict:
        player = engine.active_player
        enemy = engine.defending_player
        can_resource = engine.can_builder_add_resource(player)
        can_build = engine.can_builder_open_creature_build(player)
        own_count = len(player.battlefield)
        enemy_count = len(enemy.battlefield)

        if can_resource and (not can_build or self._wants_resource(player, own_count, enemy_count)):
            return {
                "kind": "builder_add_resource",
                "description": f"{self.name} benchmark profile adds a resource.",
            }
        if can_build:
            plan = self._creature_plan(player.available_resources())
            return {
                "kind": "builder_create_creature",
                "description": f"{self.name} benchmark profile builds a creature.",
                "plan": plan,
            }
        return self._advance_to_combat(engine)

    def _wants_resource(self, player, own_count: int, enemy_count: int) -> bool:
        resources = player.total_resources()
        if own_count == 0:
            return False
        if self.name == "aggressive":
            return resources < 4 and own_count >= max(1, resources - 1)
        if self.name == "defensive":
            return resources < 6 and own_count >= max(1, enemy_count)
        if self.name == "balanced":
            return resources < 5 and own_count >= max(1, enemy_count)
        # Stable seeded variation exercises irregular resource curves.
        pressure = enemy_count > own_count
        return resources < 7 and not pressure and self.rng.random() < 0.62

    def _creature_plan(self, spend: int) -> dict:
        stats = [0, 0, 0, 1]
        if self.name == "aggressive":
            order = (0, 2, 0, 2, 3, 1)
        elif self.name == "defensive":
            order = (1, 3, 1, 3, 2, 0)
        elif self.name == "balanced":
            rotation = self.build_number % 4
            order = tuple((rotation + offset) % 4 for offset in (0, 1, 2, 3, 0, 2, 1, 3))
        else:
            order = tuple(self.rng.randrange(4) for _ in range(max(1, spend)))
        for index in range(spend):
            stat_index = order[index % len(order)]
            if stats[stat_index] >= BUILDER_CREATURE_STAT_CAP:
                available_indexes = [
                    current
                    for current in range(4)
                    if stats[current] < BUILDER_CREATURE_STAT_CAP
                ]
                if not available_indexes:
                    break
                stat_index = self.rng.choice(available_indexes) if self.name == "random" else available_indexes[0]
            stats[stat_index] += 1
        self.build_number += 1
        return {
            "aw": stats[0],
            "vw": stats[1],
            "sw": stats[2],
            "lw": stats[3],
            "cost": spend,
        }

    def _attack_action(self, engine) -> dict:
        attackers = list(engine.available_attackers(engine.active_player))
        mandatory_ids = {unit.unit_id for unit in engine.get_mandatory_attackers(engine.active_player)}
        chosen = [unit for unit in attackers if unit.unit_id in mandatory_ids]
        optional = [unit for unit in attackers if unit.unit_id not in mandatory_ids]
        congested = min(len(engine.active_player.battlefield), len(engine.defending_player.battlefield)) >= 4
        stalled_turns = int(getattr(engine, "builder_stalled_turns", 0))
        full_economy = (
            engine.active_player.total_resources() >= engine.BUILDER_MAX_RESOURCES
            and engine.defending_player.total_resources() >= engine.BUILDER_MAX_RESOURCES
        )
        if congested and full_economy:
            stalled_turns = max(
                stalled_turns,
                int(getattr(engine, "builder_player_damage_stalled_turns", stalled_turns)),
            )
        profile_forces_progress = congested and (
            (self.name == "balanced" and stalled_turns >= 16)
            or (self.name == "defensive" and stalled_turns >= 24)
        )
        if self.name == "aggressive" or profile_forces_progress:
            chosen.extend(optional)
        elif self.name == "defensive":
            if sum(unit.sw for unit in attackers) >= engine.defending_player.life:
                chosen.extend(optional)
            else:
                chosen.extend(unit for unit in optional if self._safe_attacker(engine, unit, threshold=0.68))
        elif self.name == "balanced":
            chosen.extend(unit for unit in optional if self._safe_attacker(engine, unit, threshold=0.50))
        else:
            chosen.extend(unit for unit in optional if self.rng.random() < 0.58)
        chosen_ids = sorted({unit.unit_id for unit in chosen})
        return {
            "kind": "declare_attackers",
            "description": f"{self.name} benchmark profile declares attackers.",
            "attacker_ids": chosen_ids,
        }

    @staticmethod
    def _safe_attacker(engine, attacker, *, threshold: float) -> bool:
        legal_blockers = [
            blocker
            for blocker in engine.available_blockers(engine.defending_player)
            if engine.can_creature_block_attacker(blocker, attacker)
        ]
        if not legal_blockers:
            return True
        worst_win_probability = min(
            estimate_dice_win_probabilities(attacker.aw, blocker.vw, engine.combat_die_sides).attacker_win_probability
            for blocker in legal_blockers
        )
        survivable = all(attacker.current_hp > blocker.sw for blocker in legal_blockers)
        can_kill = any(attacker.sw >= blocker.current_hp for blocker in legal_blockers)
        return worst_win_probability >= threshold and (survivable or can_kill)

    def _block_action(self, engine) -> dict:
        result = dict(engine.block_assignments)
        used = {blocker_id for blocker_id in result.values() if blocker_id is not None}
        blockers = list(engine.available_blockers(engine.defending_player))
        attackers = [engine.get_unit_by_id(attacker_id) for attacker_id in result]
        attackers = [attacker for attacker in attackers if attacker is not None]
        attackers.sort(key=lambda unit: (unit.sw, unit.aw, unit.current_hp, -unit.unit_id), reverse=True)

        for attacker in attackers:
            if result.get(attacker.unit_id) is not None:
                continue
            legal = [
                blocker
                for blocker in blockers
                if blocker.unit_id not in used and engine.can_creature_block_attacker(blocker, attacker)
            ]
            if not legal or not self._wants_block(engine, attacker, legal):
                continue
            blocker = self._choose_blocker(engine, attacker, legal)
            result[attacker.unit_id] = blocker.unit_id
            used.add(blocker.unit_id)
        return {
            "kind": "declare_blocks",
            "description": f"{self.name} benchmark profile assigns blockers.",
            "block_assignments": result,
        }

    def _wants_block(self, engine, attacker, legal_blockers: list) -> bool:
        if self.name == "defensive":
            return True
        lethal = attacker.sw >= engine.defending_player.life
        if self.name == "aggressive":
            kill_chance = max(
                estimate_dice_win_probabilities(attacker.aw, blocker.vw, engine.combat_die_sides).defender_win_probability
                for blocker in legal_blockers
            )
            return lethal or kill_chance >= 0.60
        if self.name == "balanced":
            return lethal or attacker.sw >= 2 or any(
                estimate_dice_win_probabilities(attacker.aw, blocker.vw, engine.combat_die_sides).defender_win_probability >= 0.50
                for blocker in legal_blockers
            )
        return lethal or self.rng.random() < 0.68

    def _choose_blocker(self, engine, attacker, legal_blockers: list):
        def score(blocker) -> tuple:
            win_probability = estimate_dice_win_probabilities(
                attacker.aw, blocker.vw, engine.combat_die_sides
            ).defender_win_probability
            kills = 1 if blocker.sw >= attacker.current_hp else 0
            survives_hit = 1 if blocker.current_hp > attacker.sw else 0
            value = blocker.aw + blocker.vw + blocker.sw + blocker.current_hp
            if self.name == "defensive":
                return (win_probability, survives_hit, kills, -value, -blocker.unit_id)
            if self.name == "aggressive":
                return (kills, win_probability, -value, survives_hit, -blocker.unit_id)
            if self.name == "random":
                return (self.rng.random(),)
            return (win_probability + 0.12 * kills + 0.08 * survives_hit, -value, -blocker.unit_id)

        return max(legal_blockers, key=score)


def _acting_player_id(engine, phase: str) -> int:
    return engine.defending_player.player_id if phase == PHASE_DECLARE_BLOCKERS else engine.active_player.player_id


def _record_target_audits(engine, phase: str, action: dict) -> list[DecisionAudit]:
    audits: list[DecisionAudit] = []
    turn = int(engine.turn_number)
    if phase == PHASE_MAIN_1:
        decision = action.get("turn_decision")
        alternatives = tuple(getattr(engine.ai, "_last_builder_turn_alternatives", ()))
        if decision is not None and alternatives:
            chosen = float(decision.score.selection_score)
            best = max(float(candidate.score.selection_score) for candidate in alternatives)
            if chosen + 1e-6 < best:
                audits.append(DecisionAudit(
                    turn, "main", "main_selection_inversion", "error",
                    "Chosen main action scored below another evaluated action.", chosen, best,
                ))
    elif phase == PHASE_DECLARE_ATTACKERS:
        decision = getattr(action.get("turn_decision"), "predicted_attack_decision", None)
        if decision is None:
            return audits
        scored = tuple(getattr(decision, "scored_candidates", ()))
        chosen_ids = tuple(getattr(decision.candidate, "attacker_ids", ()))
        chosen_score = float(decision.score.total)
        if scored:
            best_score = max(float(score.total) for _candidate, score in scored)
            if chosen_score + 1e-6 < best_score:
                audits.append(DecisionAudit(
                    turn, "attackers", "attack_selection_inversion", "error",
                    "Chosen attack scored below another evaluated attack.", chosen_score, best_score,
                ))
            lethal = [
                float(score.total)
                for _candidate, score in scored
                if score.guaranteed_player_damage >= engine.defending_player.life > 0
            ]
            if lethal and decision.score.guaranteed_player_damage < engine.defending_player.life:
                audits.append(DecisionAudit(
                    turn, "attackers", "missed_guaranteed_lethal", "error",
                    "An evaluated guaranteed-lethal attack was not selected.", chosen_score, max(lethal),
                ))
            attacking_scores = [float(score.total) for candidate, score in scored if candidate.attacker_ids]
            if not chosen_ids and attacking_scores and max(attacking_scores) > chosen_score + 2.0:
                audits.append(DecisionAudit(
                    turn, "attackers", "high_margin_no_attack", "warning",
                    "No attack was selected despite a much higher-scoring attack candidate.",
                    chosen_score, max(attacking_scores),
                ))
        metadata = decision.search_metadata
        if not metadata.exact_search:
            audits.append(DecisionAudit(
                turn, "attackers", "inexact_attack_search", "info",
                f"Attack search was pruned ({metadata.evaluated_attack_candidates}/"
                f"{metadata.generated_attack_candidates} attack candidates).",
            ))
        if bool(getattr(decision.score, "counter_fallback_used", False)):
            audits.append(DecisionAudit(
                turn, "attackers", "counter_search_fallback", "info",
                str(getattr(decision.score, "counter_fallback_reason", "fallback")),
            ))
    elif phase == PHASE_DECLARE_BLOCKERS:
        scored = tuple(getattr(engine.ai, "_last_builder_block_scored_candidates", ()))
        chosen_score = getattr(engine.ai, "_last_builder_block_score", None)
        if scored and chosen_score is not None:
            chosen = float(chosen_score.total)
            best = max(float(score.total) for _candidate, score in scored)
            if chosen + 1e-6 < best:
                audits.append(DecisionAudit(
                    turn, "blockers", "block_selection_inversion", "error",
                    "Chosen blocks scored below another evaluated assignment.", chosen, best,
                ))
    return audits


def _dice_sample_for_target(engine) -> DiceCalibrationSample | None:
    battle = engine.pending_dice_battle
    if battle is None or battle.winner not in {"attacker", "blocker"}:
        return None
    if TARGET_PLAYER_ID not in {battle.attacker_owner, battle.blocker_owner}:
        return None
    estimate = estimate_dice_win_probabilities(
        battle.attacker_snapshot.aw,
        battle.blocker_snapshot.vw,
        engine.combat_die_sides,
    )
    if battle.attacker_owner == TARGET_PLAYER_ID:
        expected = estimate.attacker_win_probability
        actual = int(battle.winner == "attacker")
        role = "attacker"
    else:
        expected = estimate.defender_win_probability
        actual = int(battle.winner == "blocker")
        role = "blocker"
    return DiceCalibrationSample(
        turn=engine.turn_number,
        target_role=role,
        expected_win_probability=round(expected, 6),
        actual_win=actual,
        attacker_aw=battle.attacker_snapshot.aw,
        blocker_vw=battle.blocker_snapshot.vw,
    )


def run_profile_game(
    profile_name: str,
    seed: int,
    starting_player_id: int,
    config: ProfileBenchmarkConfig | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> ProfileGameResult:
    """Run production AI (Player 2) against one independent fixed profile."""
    config = config or ProfileBenchmarkConfig()
    started_at = perf_counter()
    engine = _create_soak_engine(
        seed,
        starting_life=config.starting_life,
        starting_player_id=starting_player_id,
    )
    profile = FixedOpponentProfile(profile_name, seed * 2 + starting_player_id)
    timings: list[DecisionTiming] = []
    target_builds: list[BuilderBuildSample] = []
    opponent_builds: list[BuilderBuildSample] = []
    curve: list[ResourceCurveSample] = []
    dice_samples: list[DiceCalibrationSample] = []
    audits: list[DecisionAudit] = []
    target_main_actions: Counter[str] = Counter()
    target_attack_phases = 0
    target_no_attack_count = 0
    target_declared_attackers = 0
    target_full_board_passes = 0
    target_damage = 0
    opponent_damage = 0
    target_kills = 0
    target_deaths = 0
    recorded_turns: set[int] = set()
    recorded_combats: set[int] = set()
    steps = 0

    try:
        validate_game_invariants(engine)
        while engine.phase != PHASE_GAME_OVER:
            if steps >= config.max_steps:
                raise _BenchmarkFailure("step_limit", f"game exceeded {config.max_steps} engine steps")
            if engine.turn_number > config.max_turns:
                raise _BenchmarkFailure("turn_limit", f"game exceeded {config.max_turns} turns")
            if perf_counter() - started_at > config.game_timeout_seconds:
                raise _BenchmarkFailure("game_timeout", f"game exceeded {config.game_timeout_seconds:.1f} seconds")

            if engine.turn_number not in recorded_turns:
                recorded_turns.add(engine.turn_number)
                curve.append(ResourceCurveSample(
                    turn=engine.turn_number,
                    target_resources=engine.players[TARGET_PLAYER_ID].total_resources(),
                    opponent_resources=engine.players[1 - TARGET_PLAYER_ID].total_resources(),
                    target_board=len(engine.players[TARGET_PLAYER_ID].battlefield),
                    opponent_board=len(engine.players[1 - TARGET_PLAYER_ID].battlefield),
                ))

            steps += 1
            phase = engine.phase
            before_signature = _state_progress_signature(engine)
            before_life = [player.life for player in engine.players]
            before_units = {
                player.player_id: {creature.unit_id for creature in player.battlefield}
                for player in engine.players
            }

            if phase in {PHASE_MAIN_1, PHASE_BUILDER_ABILITY, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS}:
                actor_id = _acting_player_id(engine, phase)
                decision_state = _state_snapshot(engine)
                _clear_search_metrics(engine)
                decision_started_at = perf_counter()
                if actor_id == TARGET_PLAYER_ID:
                    prepared = engine.prepare_ai_turn_action()
                    action = engine.pending_ai_action
                else:
                    action = profile.prepare_action(engine)
                    engine.pending_ai_action = action
                    prepared = True
                elapsed_ms = (perf_counter() - decision_started_at) * 1_000
                if not prepared or not isinstance(action, dict):
                    raise _BenchmarkFailure(
                        "ai_prepare_failed",
                        f"no action in turn {engine.turn_number}, phase {_phase_label(phase)}",
                    )
                validate_prepared_action(engine, action)
                if elapsed_ms > config.decision_timeout_seconds * 1_000:
                    raise _BenchmarkFailure(
                        "decision_timeout",
                        f"turn {engine.turn_number} {_phase_label(phase)} took {elapsed_ms:.1f} ms",
                    )

                if actor_id == TARGET_PLAYER_ID:
                    sample = DecisionTiming(
                        turn=engine.turn_number,
                        player_id=actor_id,
                        phase=_phase_label(phase),
                        action=str(action.get("kind", "none")),
                        elapsed_ms=elapsed_ms,
                        search_metrics=_search_metrics_for_phase(engine, phase),
                        state_snapshot=(decision_state if elapsed_ms >= config.slow_snapshot_threshold_ms else None),
                    )
                    timings.append(sample)
                    audits.extend(_record_target_audits(engine, phase, action))
                    if phase == PHASE_MAIN_1:
                        target_main_actions[str(action.get("kind", "unknown"))] += 1
                    elif phase == PHASE_DECLARE_ATTACKERS:
                        attacker_ids = list(action.get("attacker_ids", ()))
                        target_attack_phases += 1
                        target_declared_attackers += len(attacker_ids)
                        if not attacker_ids:
                            target_no_attack_count += 1
                            if len(engine.active_player.battlefield) >= BUILDER_CREATURE_CAP:
                                target_full_board_passes += 1

                build_sample = _builder_build_sample(engine, action)
                acting_board_before = len(engine.players[actor_id].battlefield)
                engine.execute_prepared_ai_action()
                if build_sample is not None and len(engine.players[actor_id].battlefield) > acting_board_before:
                    if actor_id == TARGET_PLAYER_ID:
                        target_builds.append(build_sample)
                    else:
                        opponent_builds.append(build_sample)
                if progress_callback is not None:
                    progress_callback({
                        "event": "decision",
                        "profile": profile_name,
                        "seed": seed,
                        "starting_player_id": starting_player_id,
                        "turn": engine.turn_number,
                        "actor_id": actor_id,
                        "phase": _phase_label(phase),
                        "action": action.get("kind"),
                        "elapsed_ms": elapsed_ms,
                    })
            elif phase == PHASE_DICE_BATTLE:
                battle = engine.pending_dice_battle
                combat_id = int(getattr(battle, "combat_id", 0)) if battle is not None else 0
                if combat_id not in recorded_combats:
                    recorded_combats.add(combat_id)
                    dice_sample = _dice_sample_for_target(engine)
                    if dice_sample is not None:
                        dice_samples.append(dice_sample)
                engine.end_dice_battle()
            else:
                raise _BenchmarkFailure("unsupported_phase", f"cannot advance phase {phase!r}")

            after_life = [player.life for player in engine.players]
            target_damage += max(0, before_life[1 - TARGET_PLAYER_ID] - after_life[1 - TARGET_PLAYER_ID])
            opponent_damage += max(0, before_life[TARGET_PLAYER_ID] - after_life[TARGET_PLAYER_ID])
            after_units = {
                player.player_id: {creature.unit_id for creature in player.battlefield}
                for player in engine.players
            }
            target_kills += len(before_units[1 - TARGET_PLAYER_ID] - after_units[1 - TARGET_PLAYER_ID])
            target_deaths += len(before_units[TARGET_PLAYER_ID] - after_units[TARGET_PLAYER_ID])

            validate_game_invariants(engine)
            if engine.phase != PHASE_GAME_OVER and _state_progress_signature(engine) == before_signature:
                raise _BenchmarkFailure(
                    "no_progress",
                    f"turn {engine.turn_number} remained in {_phase_label(engine.phase)}",
                )

        if engine.players[0].life <= 0 and engine.players[1].life <= 0:
            winner_id = None
        elif engine.players[0].life > 0:
            winner_id = 0
        else:
            winner_id = 1
        return ProfileGameResult(
            profile=profile_name,
            seed=seed,
            starting_player_id=starting_player_id,
            completed=True,
            winner_id=winner_id,
            turns=engine.turn_number,
            steps=steps,
            elapsed_ms=(perf_counter() - started_at) * 1_000,
            player_life=(engine.players[0].life, engine.players[1].life),
            target_damage_to_player=target_damage,
            opponent_damage_to_player=opponent_damage,
            target_creature_kills=target_kills,
            target_creature_deaths=target_deaths,
            target_attack_phases=target_attack_phases,
            target_no_attack_count=target_no_attack_count,
            target_declared_attackers=target_declared_attackers,
            target_full_board_passes=target_full_board_passes,
            target_main_actions=dict(target_main_actions),
            target_builds=tuple(target_builds),
            opponent_builds=tuple(opponent_builds),
            resource_curve=tuple(curve),
            dice_samples=tuple(dice_samples),
            decision_audits=tuple(audits),
            decision_timings=tuple(timings),
            final_snapshot=_state_snapshot(engine),
        )
    except (GameInvariantError, _BenchmarkFailure, Exception) as error:
        if isinstance(error, GameInvariantError):
            code = "invariant_violation"
        elif isinstance(error, _BenchmarkFailure):
            code = error.code
        else:
            code = "exception"
        return ProfileGameResult(
            profile=profile_name,
            seed=seed,
            starting_player_id=starting_player_id,
            completed=False,
            winner_id=None,
            turns=int(getattr(engine, "turn_number", 0)),
            steps=steps,
            elapsed_ms=(perf_counter() - started_at) * 1_000,
            player_life=tuple(player.life for player in engine.players),
            target_damage_to_player=target_damage,
            opponent_damage_to_player=opponent_damage,
            target_creature_kills=target_kills,
            target_creature_deaths=target_deaths,
            target_attack_phases=target_attack_phases,
            target_no_attack_count=target_no_attack_count,
            target_declared_attackers=target_declared_attackers,
            target_full_board_passes=target_full_board_passes,
            target_main_actions=dict(target_main_actions),
            target_builds=tuple(target_builds),
            opponent_builds=tuple(opponent_builds),
            resource_curve=tuple(curve),
            dice_samples=tuple(dice_samples),
            decision_audits=tuple(audits),
            decision_timings=tuple(timings),
            final_snapshot=_state_snapshot(engine),
            failure_code=code,
            failure_message=f"{type(error).__name__}: {error}",
        )


def _average(values: Iterable[float]) -> float:
    resolved = list(values)
    return round(fmean(resolved), 4) if resolved else 0.0


def _build_report(results: list[ProfileGameResult], player_id: int) -> dict:
    samples = [
        sample
        for result in results
        for sample in (result.target_builds if player_id == TARGET_PLAYER_ID else result.opponent_builds)
    ]
    return {
        "count": len(samples),
        "average_stats": {
            stat: _average(float(getattr(sample, stat)) for sample in samples)
            for stat in ("aw", "vw", "sw", "lw")
        },
        "damage_one_count": sum(sample.sw == 1 for sample in samples),
        "damage_one_rate": round(sum(sample.sw == 1 for sample in samples) / len(samples), 4) if samples else 0.0,
    }


def _curve_report(results: list[ProfileGameResult]) -> list[dict]:
    by_index: dict[int, list[ResourceCurveSample]] = defaultdict(list)
    for result in results:
        for index, sample in enumerate(result.resource_curve, start=1):
            by_index[index].append(sample)
    return [
        {
            "turn_sample": index,
            "games": len(samples),
            "target_resources": _average(sample.target_resources for sample in samples),
            "opponent_resources": _average(sample.opponent_resources for sample in samples),
            "target_board": _average(sample.target_board for sample in samples),
            "opponent_board": _average(sample.opponent_board for sample in samples),
        }
        for index, samples in sorted(by_index.items())
    ]


def _aggregate_results(results: list[ProfileGameResult]) -> dict:
    completed = [result for result in results if result.completed]
    target_wins = sum(result.target_won for result in completed)
    dice = [sample for result in completed for sample in result.dice_samples]
    timings = [sample for result in completed for sample in result.decision_timings]
    audits = [audit for result in completed for audit in result.decision_audits]
    attack_phases = sum(result.target_attack_phases for result in completed)
    target_builds = _build_report(completed, TARGET_PLAYER_ID)
    return {
        "games": len(results),
        "completed": len(completed),
        "failed": len(results) - len(completed),
        "target_wins": target_wins,
        "target_win_rate": round(target_wins / len(completed), 4) if completed else 0.0,
        "average_turns": _average(result.turns for result in completed),
        "average_game_ms": _average(result.elapsed_ms for result in completed),
        "target_damage_to_player": sum(result.target_damage_to_player for result in completed),
        "opponent_damage_to_player": sum(result.opponent_damage_to_player for result in completed),
        "target_creature_kills": sum(result.target_creature_kills for result in completed),
        "target_creature_deaths": sum(result.target_creature_deaths for result in completed),
        "attacks": {
            "phases": attack_phases,
            "declared_attackers": sum(result.target_declared_attackers for result in completed),
            "no_attack_count": sum(result.target_no_attack_count for result in completed),
            "no_attack_rate": round(
                sum(result.target_no_attack_count for result in completed) / attack_phases, 4
            ) if attack_phases else 0.0,
            "full_board_passes": sum(result.target_full_board_passes for result in completed),
        },
        "main_actions": dict(sorted(sum((Counter(result.target_main_actions) for result in completed), Counter()).items())),
        "target_builds": target_builds,
        "opponent_builds": _build_report(completed, 1 - TARGET_PLAYER_ID),
        "dice_calibration": {
            "samples": len(dice),
            "expected_wins": round(sum(sample.expected_win_probability for sample in dice), 4),
            "actual_wins": sum(sample.actual_win for sample in dice),
            "expected_win_rate": _average(sample.expected_win_probability for sample in dice),
            "actual_win_rate": _average(sample.actual_win for sample in dice),
            "brier_score": _average(
                (sample.actual_win - sample.expected_win_probability) ** 2 for sample in dice
            ),
        },
        "decision_quality": {
            "audits": len(audits),
            "error_count": sum(audit.severity == "error" for audit in audits),
            "warning_count": sum(audit.severity == "warning" for audit in audits),
            "codes": dict(sorted(Counter(audit.code for audit in audits).items())),
        },
        "decision_timing": {
            "count": len(timings),
            "average_ms": _average(sample.elapsed_ms for sample in timings),
            "max_ms": round(max((sample.elapsed_ms for sample in timings), default=0.0), 4),
        },
        "resource_curve": _curve_report(completed),
    }


@dataclass(frozen=True)
class ProfileBenchmarkSummary:
    config: ProfileBenchmarkConfig
    results: tuple[ProfileGameResult, ...]

    @property
    def successful(self) -> bool:
        return all(result.completed for result in self.results)

    def to_dict(self) -> dict:
        results = list(self.results)
        by_profile = {
            profile: _aggregate_results([result for result in results if result.profile == profile])
            for profile in PROFILE_NAMES
            if any(result.profile == profile for result in results)
        }
        by_starting_role = {
            "target_starts": _aggregate_results([result for result in results if result.starting_player_id == TARGET_PLAYER_ID]),
            "opponent_starts": _aggregate_results([result for result in results if result.starting_player_id != TARGET_PLAYER_ID]),
        }
        return {
            "config": asdict(self.config),
            "target_player_id": TARGET_PLAYER_ID,
            "profiles": by_profile,
            "starting_roles": by_starting_role,
            "overall": _aggregate_results(results),
            "failures": [result.to_dict() for result in results if not result.completed],
            "reproducible_findings": _reproducible_findings(results),
            "games": [result.to_dict() for result in results],
        }


def _reproducible_findings(results: list[ProfileGameResult]) -> list[dict]:
    occurrences: dict[tuple[str, str], list[tuple[int, int, DecisionAudit]]] = defaultdict(list)
    for result in results:
        for audit in result.decision_audits:
            if audit.severity not in {"error", "warning"}:
                continue
            occurrences[(result.profile, audit.code)].append((result.seed, result.starting_player_id, audit))
    findings = []
    for (profile, code), samples in sorted(occurrences.items()):
        distinct_seeds = sorted({seed for seed, _starter, _audit in samples})
        if len(distinct_seeds) < 2:
            continue
        findings.append({
            "profile": profile,
            "code": code,
            "occurrences": len(samples),
            "seeds": distinct_seeds,
            "examples": [
                {
                    "seed": seed,
                    "starting_player_id": starter,
                    **asdict(audit),
                }
                for seed, starter, audit in samples[:5]
            ],
        })
    return findings


def run_profile_benchmark(
    seeds: Iterable[int],
    config: ProfileBenchmarkConfig | None = None,
    *,
    profiles: Iterable[str] = PROFILE_NAMES,
    workers: int = 1,
    result_callback: Callable[[int, int, ProfileGameResult], None] | None = None,
) -> ProfileBenchmarkSummary:
    config = config or ProfileBenchmarkConfig()
    seed_values = tuple(int(seed) for seed in seeds)
    profile_values = tuple(profiles)
    for profile in profile_values:
        if profile not in PROFILE_NAMES:
            raise ValueError(f"unknown opponent profile {profile!r}")
    if workers <= 0:
        raise ValueError("workers must be positive")
    jobs = [
        (profile, seed, starting_player_id)
        for profile in profile_values
        for seed in seed_values
        for starting_player_id in (0, 1)
    ]
    results: list[ProfileGameResult] = []
    if workers == 1:
        for index, (profile, seed, starting_player_id) in enumerate(jobs, start=1):
            result = run_profile_game(profile, seed, starting_player_id, config)
            results.append(result)
            if result_callback is not None:
                result_callback(index, len(jobs), result)
    else:
        indexed_results: dict[int, ProfileGameResult] = {}
        with ProcessPoolExecutor(max_workers=workers) as executor:
            pending = {
                executor.submit(run_profile_game, profile, seed, starting_player_id, config): job_index
                for job_index, (profile, seed, starting_player_id) in enumerate(jobs)
            }
            completed_count = 0
            for future in as_completed(pending):
                job_index = pending[future]
                result = future.result()
                indexed_results[job_index] = result
                completed_count += 1
                if result_callback is not None:
                    result_callback(completed_count, len(jobs), result)
        results = [indexed_results[index] for index in range(len(jobs))]
    return ProfileBenchmarkSummary(config=config, results=tuple(results))


def format_markdown_report(report: dict) -> str:
    overall = report["overall"]
    lines = [
        "# AI profile benchmark",
        "",
        f"Production AI: Player {report['target_player_id'] + 1}; fixed profiles: Player 1.",
        "Each seed is played twice with the starting player mirrored.",
        "",
        "## Overall",
        "",
        f"- Completed: {overall['completed']}/{overall['games']}",
        f"- AI wins: {overall['target_wins']} ({overall['target_win_rate'] * 100:.1f}%)",
        f"- Average turns: {overall['average_turns']:.2f}",
        f"- No-attack rate: {overall['attacks']['no_attack_rate'] * 100:.1f}%",
        f"- Full-board passes: {overall['attacks']['full_board_passes']}",
        f"- Target build averages: {overall['target_builds']['average_stats']}",
        f"- DMG-1 build rate: {overall['target_builds']['damage_one_rate'] * 100:.1f}%",
        f"- Dice expected/actual wins: {overall['dice_calibration']['expected_wins']:.2f} / "
        f"{overall['dice_calibration']['actual_wins']}",
        f"- Decision audit errors/warnings: {overall['decision_quality']['error_count']} / "
        f"{overall['decision_quality']['warning_count']}",
        "",
        "## Profiles",
        "",
        "| Profile | Games | AI win rate | Avg turns | No attack | AI DMG-1 builds | Kills / deaths |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, profile in report["profiles"].items():
        lines.append(
            f"| {name} | {profile['completed']}/{profile['games']} | "
            f"{profile['target_win_rate'] * 100:.1f}% | {profile['average_turns']:.2f} | "
            f"{profile['attacks']['no_attack_rate'] * 100:.1f}% | "
            f"{profile['target_builds']['damage_one_rate'] * 100:.1f}% | "
            f"{profile['target_creature_kills']} / {profile['target_creature_deaths']} |"
        )
    lines.extend(["", "## Starting-player split", ""])
    for name, split in report["starting_roles"].items():
        lines.append(
            f"- {name.replace('_', ' ')}: {split['target_wins']}/{split['completed']} AI wins "
            f"({split['target_win_rate'] * 100:.1f}%)"
        )
    lines.extend(["", "## Reproducible findings", ""])
    findings = report["reproducible_findings"]
    if findings:
        for finding in findings:
            lines.append(
                f"- `{finding['code']}` vs {finding['profile']}: "
                f"{finding['occurrences']} occurrences, seeds {finding['seeds']}"
            )
    else:
        lines.append("No error or warning audit repeated across two seeds.")
    if report["failures"]:
        lines.extend(["", "## Failed games", ""])
        for failure in report["failures"]:
            lines.append(
                f"- {failure['profile']} seed {failure['seed']} starter {failure['starting_player_id']}: "
                f"{failure['failure_code']} — {failure['failure_message']}"
            )
    return "\n".join(lines) + "\n"
