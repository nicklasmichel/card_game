from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from statistics import fmean

from core.builder_rules import builder_creature_stat_cost, calculate_builder_creature_cost


GAME_START_PREFIX = "[GAME START] "
GAME_END_PREFIX = "[GAME END] "
LEGACY_GAME_START_PREFIX = "New game started in builder mode."
BUILD_PATTERN = re.compile(
    r"^(?P<player>.+?) creates (?P<creature>.+?) "
    r"\(A (?P<aw>\d+) / D (?P<vw>\d+) / DMG (?P<sw>\d+) / Life (?P<lw>\d+)"
    r"(?: / (?P<abilities>.+?))?\) for (?P<cost>\d+) resource\(s\)\.$"
)
TURN_PATTERN = re.compile(r"^Turn (?P<turn>\d+):")


@dataclass(frozen=True)
class PlaytestBuild:
    turn: int
    player: str
    creature: str
    aw: int
    vw: int
    sw: int
    lw: int
    abilities: tuple[str, ...]
    primary_ability: str
    has_haste: bool
    stat_cost: int
    total_cost: int
    expected_cost: int

    @property
    def cost_is_valid(self) -> bool:
        return self.total_cost == self.expected_cost

    @property
    def combination(self) -> str:
        return "+".join(ability.upper() for ability in self.abilities)


@dataclass(frozen=True)
class PlaytestDecision:
    turn: int
    actor: str
    phase: str
    decision: str
    elapsed_ms: float
    stop_reason: str


@dataclass(frozen=True)
class PlaytestAttack:
    turn: int
    player: str
    creatures: tuple[str, ...]


@dataclass(frozen=True)
class PlaytestBlocks:
    turn: int
    defender: str
    assignments: tuple[tuple[str, str], ...]


def analyze_latest_playtest(log_path: Path) -> dict[str, object]:
    lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    session_lines = _latest_session_lines(lines)
    metadata = _parse_metadata(session_lines)
    builds: list[PlaytestBuild] = []
    decisions: list[PlaytestDecision] = []
    attacks: list[PlaytestAttack] = []
    blocks: list[PlaytestBlocks] = []
    turns: list[int] = []
    current_turn = 0
    for line in session_lines:
        if match := TURN_PATTERN.match(line):
            current_turn = int(match.group("turn"))
            turns.append(current_turn)
        if build := _parse_build(line, turn=current_turn):
            builds.append(build)
        if decision := _parse_decision(line):
            decisions.append(decision)
        if attack := _parse_attack(line):
            attacks.append(attack)
        if block := _parse_blocks(line):
            blocks.append(block)
    end_metadata = next(
        (_parse_key_values(line.removeprefix(GAME_END_PREFIX)) for line in reversed(session_lines) if line.startswith(GAME_END_PREFIX)),
        {},
    )
    return {
        "game": {
            **metadata,
            "completed": end_metadata.get("status") == "completed" or any(" wins. " in line for line in session_lines),
            "winner": end_metadata.get("winner", "").replace("_", " ") or _winner_from_lines(session_lines),
            "last_turn": max(turns, default=int(end_metadata.get("turn", 0) or 0)),
            "log_lines": len(session_lines),
        },
        "builds": _build_report(builds, attacks, blocks),
        "ai_decisions": _decision_report(decisions),
        "raw": {
            "builds": [asdict(build) | {"cost_is_valid": build.cost_is_valid, "combination": build.combination} for build in builds],
            "ai_decisions": [asdict(decision) for decision in decisions],
            "attacks": [asdict(attack) for attack in attacks],
            "blocks": [asdict(block) for block in blocks],
        },
    }


def format_playtest_report(report: dict[str, object]) -> str:
    game = report["game"]
    builds = report["builds"]
    decisions = report["ai_decisions"]
    status = "completed" if game["completed"] else "incomplete/aborted"
    lines = [
        f"Game: {game.get('id', 'unknown')} ({status}), last turn {game['last_turn']}",
        f"Builds: {builds['count']} total, Haste {builds['haste_count']} ({builds['haste_rate'] * 100:.1f}%)",
        f"Ability combinations: {builds['combinations']}",
        (
            f"Haste used immediately: {builds['haste_immediate_use_count']}/{builds['haste_count']} "
            f"({builds['haste_immediate_use_rate'] * 100:.1f}%; "
            f"attacks {builds['haste_creation_turn_attack_count']}, blocks {builds['haste_next_turn_block_count']})"
        ),
    ]
    for player, player_report in builds["by_player"].items():
        lines.append(
            f"  {player}: {player_report['count']} builds, Haste {player_report['haste_count']} "
            f"({player_report['haste_rate'] * 100:.1f}%), avg stat cost {player_report['average_stat_cost']:.2f}"
        )
    lines.extend(
        (
            f"Build cost errors: {builds['invalid_cost_count']}",
            (
                f"AI decisions: {decisions['count']} total, avg {decisions['average_ms']:.1f}ms, "
                f"P95 {decisions['p95_ms']:.1f}ms, max {decisions['max_ms']:.1f}ms, "
                f">30s {decisions['over_30_seconds']}"
            ),
            f"AI search stops: {decisions['stop_reasons']}",
        )
    )
    if game.get("winner"):
        lines.append(f"Winner: {game['winner']}")
    return "\n".join(lines)


def _latest_session_lines(lines: list[str]) -> list[str]:
    marker_indexes = [index for index, line in enumerate(lines) if line.startswith(GAME_START_PREFIX)]
    if marker_indexes:
        return lines[marker_indexes[-1]:]
    legacy_indexes = [index for index, line in enumerate(lines) if line.startswith(LEGACY_GAME_START_PREFIX)]
    return lines[legacy_indexes[-1]:] if legacy_indexes else lines


def _parse_metadata(lines: list[str]) -> dict[str, object]:
    marker = next((line for line in lines if line.startswith(GAME_START_PREFIX)), "")
    values = _parse_key_values(marker.removeprefix(GAME_START_PREFIX))
    return {
        "id": values.get("id", "legacy-or-unknown"),
        "seed": int(values["seed"]) if values.get("seed", "").isdigit() else None,
        "mode": values.get("mode", "unknown"),
    }


def _parse_build(line: str, *, turn: int) -> PlaytestBuild | None:
    match = BUILD_PATTERN.match(line)
    if match is None:
        return None
    values = match.groupdict()
    abilities = tuple(part.strip() for part in (values["abilities"] or "").split("+") if part.strip())
    has_haste = any(ability.casefold() == "haste" for ability in abilities)
    primary = next((ability for ability in abilities if ability.casefold() != "haste"), "NONE")
    aw, vw, sw, lw = (int(values[name]) for name in ("aw", "vw", "sw", "lw"))
    stat_cost = builder_creature_stat_cost(aw=aw, vw=vw, sw=sw, lw=lw)
    return PlaytestBuild(
        turn=turn,
        player=values["player"],
        creature=values["creature"],
        aw=aw,
        vw=vw,
        sw=sw,
        lw=lw,
        abilities=abilities,
        primary_ability=primary,
        has_haste=has_haste,
        stat_cost=stat_cost,
        total_cost=int(values["cost"]),
        expected_cost=calculate_builder_creature_cost(aw=aw, vw=vw, sw=sw, lw=lw, has_haste=has_haste),
    )


def _parse_attack(line: str) -> PlaytestAttack | None:
    if not line.startswith("[COMBAT ATTACKERS] "):
        return None
    values = _parse_key_values(line.removeprefix("[COMBAT ATTACKERS] "))
    try:
        creatures = tuple(
            name.replace("_", " ")
            for name in values.get("creatures", "-").split(",")
            if name and name != "-"
        )
        return PlaytestAttack(
            turn=int(values.get("turn", 0)),
            player=values.get("player", "unknown").replace("_", " "),
            creatures=creatures,
        )
    except ValueError:
        return None


def _parse_blocks(line: str) -> PlaytestBlocks | None:
    if not line.startswith("[COMBAT BLOCKS] "):
        return None
    values = _parse_key_values(line.removeprefix("[COMBAT BLOCKS] "))
    try:
        assignments = tuple(
            tuple(name.replace("_", " ") for name in assignment.split(">", 1))
            for assignment in values.get("assignments", "-").split(",")
            if assignment and assignment != "-" and ">" in assignment
        )
        return PlaytestBlocks(
            turn=int(values.get("turn", 0)),
            defender=values.get("defender", "unknown").replace("_", " "),
            assignments=assignments,
        )
    except ValueError:
        return None


def _parse_decision(line: str) -> PlaytestDecision | None:
    if not line.startswith("[AI PERF] "):
        return None
    values = _parse_key_values(line.removeprefix("[AI PERF] "))
    if values.get("source") != "game" or "elapsed_ms" not in values:
        return None
    try:
        return PlaytestDecision(
            turn=int(values.get("turn", 0)),
            actor=values.get("actor", "unknown").replace("_", " "),
            phase=values.get("phase", "unknown"),
            decision=values.get("decision", "unknown"),
            elapsed_ms=float(values["elapsed_ms"]),
            stop_reason=values.get("stop_reason", "unknown"),
        )
    except ValueError:
        return None


def _parse_key_values(payload: str) -> dict[str, str]:
    return {
        key: value
        for token in payload.split()
        if "=" in token
        for key, value in (token.split("=", 1),)
    }


def _build_report(
    builds: list[PlaytestBuild],
    attacks: list[PlaytestAttack],
    blocks: list[PlaytestBlocks],
) -> dict[str, object]:
    by_player: dict[str, list[PlaytestBuild]] = {}
    for build in builds:
        by_player.setdefault(build.player, []).append(build)
    haste_count = sum(build.has_haste for build in builds)
    attack_keys = {
        (attack.turn, attack.player, creature)
        for attack in attacks
        for creature in attack.creatures
    }
    block_keys = {
        (block.turn, block.defender, blocker)
        for block in blocks
        for blocker, _attacker in block.assignments
    }
    haste_creation_attacks = {
        (build.turn, build.player, build.creature)
        for build in builds
        if build.has_haste and (build.turn, build.player, build.creature) in attack_keys
    }
    haste_next_turn_blocks = {
        (build.turn, build.player, build.creature)
        for build in builds
        if build.has_haste and (build.turn + 1, build.player, build.creature) in block_keys
    }
    haste_immediate_uses = haste_creation_attacks | haste_next_turn_blocks
    return {
        "count": len(builds),
        "haste_count": haste_count,
        "haste_rate": round(haste_count / len(builds), 4) if builds else 0.0,
        "invalid_cost_count": sum(not build.cost_is_valid for build in builds),
        "haste_creation_turn_attack_count": len(haste_creation_attacks),
        "haste_next_turn_block_count": len(haste_next_turn_blocks),
        "haste_immediate_use_count": len(haste_immediate_uses),
        "haste_immediate_use_rate": round(len(haste_immediate_uses) / haste_count, 4) if haste_count else 0.0,
        "primary_abilities": dict(sorted(Counter(build.primary_ability for build in builds).items())),
        "combinations": dict(sorted(Counter(build.combination for build in builds).items())),
        "by_player": {
            player: _player_build_report(player_builds, attack_keys, block_keys)
            for player, player_builds in sorted(by_player.items())
        },
    }


def _player_build_report(
    builds: list[PlaytestBuild],
    attack_keys: set[tuple[int, str, str]],
    block_keys: set[tuple[int, str, str]],
) -> dict[str, object]:
    haste_count = sum(build.has_haste for build in builds)
    immediate_use_count = sum(
        build.has_haste
        and (
            (build.turn, build.player, build.creature) in attack_keys
            or (build.turn + 1, build.player, build.creature) in block_keys
        )
        for build in builds
    )
    return {
        "count": len(builds),
        "haste_count": haste_count,
        "haste_rate": round(haste_count / len(builds), 4) if builds else 0.0,
        "haste_immediate_use_count": immediate_use_count,
        "haste_immediate_use_rate": round(immediate_use_count / haste_count, 4) if haste_count else 0.0,
        "average_stat_cost": round(fmean(build.stat_cost for build in builds), 2) if builds else 0.0,
        "average_total_cost": round(fmean(build.total_cost for build in builds), 2) if builds else 0.0,
        "primary_abilities": dict(sorted(Counter(build.primary_ability for build in builds).items())),
        "combinations": dict(sorted(Counter(build.combination for build in builds).items())),
    }


def _decision_report(decisions: list[PlaytestDecision]) -> dict[str, object]:
    elapsed = [decision.elapsed_ms for decision in decisions]
    return {
        "count": len(decisions),
        "average_ms": round(fmean(elapsed), 2) if elapsed else 0.0,
        "p95_ms": round(_percentile(elapsed, 95), 2),
        "max_ms": round(max(elapsed), 2) if elapsed else 0.0,
        "over_30_seconds": sum(value > 30_000 for value in elapsed),
        "stop_reasons": dict(sorted(Counter(decision.stop_reason for decision in decisions).items())),
        "by_phase": {
            phase: _timing_group([decision.elapsed_ms for decision in decisions if decision.phase == phase])
            for phase in sorted({decision.phase for decision in decisions})
        },
        "slowest": [
            asdict(decision)
            for decision in sorted(decisions, key=lambda current: current.elapsed_ms, reverse=True)[:10]
        ],
    }


def _timing_group(values: list[float]) -> dict[str, object]:
    return {
        "count": len(values),
        "average_ms": round(fmean(values), 2) if values else 0.0,
        "p95_ms": round(_percentile(values, 95), 2),
        "max_ms": round(max(values), 2) if values else 0.0,
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _winner_from_lines(lines: list[str]) -> str:
    for line in reversed(lines):
        if " wins. " in line:
            return line.split(" wins. ", 1)[0]
    return ""
