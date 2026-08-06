from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean
from typing import Any

from core.models import CardType


PHASE_BUCKETS = ("main_1", "combat", "main_2", "reaction", "other")


def phase_bucket(phase: str) -> str:
    if phase == "main_1":
        return "main_1"
    if phase in {"declare_attackers", "declare_blockers", "order_blockers", "dice_battle"}:
        return "combat"
    if phase == "main_2":
        return "main_2"
    if phase in {"reaction", "spell_targeting"}:
        return "reaction"
    return "other"


@dataclass
class CardTelemetry:
    drawn: int = 0
    played: int = 0
    played_as_resource: int = 0
    discarded: int = 0
    recycled: int = 0
    in_hand_at_end: int = 0
    play_turns: list[int] = field(default_factory=list)
    player_damage: int = 0
    creature_damage: int = 0
    cards_drawn: int = 0
    creatures_removed: int = 0
    resources_generated: int = 0
    successful_uses: int = 0
    ineffective_uses: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["average_play_turn"] = round(mean(self.play_turns), 3) if self.play_turns else None
        return payload


@dataclass
class PhaseCounters:
    resources: int = 0
    creatures: int = 0
    rituals: int = 0
    spells: int = 0
    reserved_resources: int = 0
    unused_ready_resources: int = 0
    held_for_main_2: int = 0


@dataclass
class PlayerTelemetry:
    player_id: int
    name: str
    deck: str
    card_stats: dict[str, CardTelemetry] = field(default_factory=dict)
    phase_stats: dict[str, PhaseCounters] = field(default_factory=lambda: {bucket: PhaseCounters() for bucket in PHASE_BUCKETS})
    max_hand_size: int = 0
    hand_sizes: list[int] = field(default_factory=list)
    max_resources: int = 0
    resource_counts: list[int] = field(default_factory=list)
    resources_first_regular: int = 0
    resources_second_regular: int = 0
    resources_first_main_1: int = 0
    resources_first_main_2: int = 0
    resources_second_main_1: int = 0
    resources_second_main_2: int = 0
    ramp_resources_gained: int = 0
    recycled_resources_lost: int = 0
    turns_with_unused_ready_resources: int = 0
    turns_with_reserved_resources: int = 0
    turns_reserved_resources_used: int = 0
    cards_drawn: int = 0
    creatures_played: int = 0
    rituals_played: int = 0
    spells_played: int = 0
    resources_played_as_cards: int = 0
    player_damage_dealt: int = 0
    creature_damage_dealt: int = 0
    creatures_died: int = 0
    maximum_board_width: int = 0
    air_attacker_counts: list[int] = field(default_factory=list)
    air_three_attacker_combats: int = 0
    air_passive_triggers: int = 0
    air_haste_attackers: int = 0
    air_flying_attackers: int = 0
    air_unblocked_flying_damage: int = 0
    air_unblocked_attacks: int = 0
    air_damage_by_turn_cutoff: dict[int, int] = field(default_factory=lambda: {3: 0, 4: 0, 5: 0, 6: 0})
    air_first_player_damage_turn: int | None = None
    air_first_three_attacker_turn: int | None = None
    air_global_buffs: int = 0
    air_global_buff_extra_damage: int = 0
    air_bounce_uses: int = 0
    air_turbulenz_drawn: int = 0
    air_nachwehen_drawn: int = 0
    fire_passive_triggers: int = 0
    fire_turns_under_ten: int = 0
    fire_bonus_cards_drawn: int = 0
    fire_holzvorrat_uses: int = 0
    fire_kohlevorrat_uses: int = 0
    fire_first_creature_turn: int | None = None
    fire_first_big_creature_turn: int | None = None
    fire_damage_spells_by_amount: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0})
    fire_burn_on_creatures: int = 0
    fire_burn_on_players: int = 0
    fire_burn_overkill: int = 0
    fire_fliers_removed_by_burn: int = 0
    fire_hitzewelle_enemy_kills: int = 0
    fire_hitzewelle_own_kills: int = 0
    fire_hitzewelle_swing: int = 0
    fire_feuerwelle_enemy_kills: int = 0
    fire_feuerwelle_own_kills: int = 0
    fire_feuerwelle_swing: int = 0
    fire_wutanfall_extra_player_damage: int = 0
    fire_raserei_extra_player_damage: int = 0
    fire_buff_changed_combats: int = 0
    fire_recycle_loss_on_buffs: int = 0
    fire_trample_damage: int = 0
    fire_reached_3_resources_turn: int | None = None
    fire_reached_4_resources_turn: int | None = None
    fire_reached_5_resources_turn: int | None = None
    mode_counts: dict[str, int] = field(default_factory=dict)
    mode_before_win: str | None = None
    mode_before_loss: str | None = None
    mode_changes: int = 0
    last_mode: str | None = None
    plan_revisions: int = 0
    invalid_plans: int = 0
    candidate_counts: list[int] = field(default_factory=list)
    planning_durations_ms: list[float] = field(default_factory=list)
    detectable_misplays: list[dict[str, Any]] = field(default_factory=list)

    def card_stat(self, template_id: str) -> CardTelemetry:
        if template_id not in self.card_stats:
            self.card_stats[template_id] = CardTelemetry()
        return self.card_stats[template_id]

    def snapshot_turn_state(self, hand_size: int, total_resources: int, board_width: int) -> None:
        self.max_hand_size = max(self.max_hand_size, hand_size)
        self.hand_sizes.append(hand_size)
        self.max_resources = max(self.max_resources, total_resources)
        self.resource_counts.append(total_resources)
        self.maximum_board_width = max(self.maximum_board_width, board_width)

    def register_mode(self, mode: str | None) -> None:
        if not mode:
            return
        self.mode_counts[mode] = self.mode_counts.get(mode, 0) + 1
        if self.last_mode is not None and self.last_mode != mode:
            self.mode_changes += 1
        self.last_mode = mode


@dataclass
class ReplayRecord:
    seed: int
    decks: list[str]
    start_player: int
    winner: int | None
    end_reason: str
    turn_count: int
    actions: list[dict[str, Any]]
    turn_states: list[dict[str, Any]]
    modes: list[dict[str, Any]]
    plan_revisions: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    log: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GameTelemetry:
    seed: int
    decks: list[str]
    starting_player_id: int
    players: dict[int, PlayerTelemetry]
    actions: list[dict[str, Any]] = field(default_factory=list)
    turn_states: list[dict[str, Any]] = field(default_factory=list)
    modes: list[dict[str, Any]] = field(default_factory=list)
    plan_revisions: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    milestones: dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0
    winner_id: int | None = None
    loser_id: int | None = None
    end_reason: str = ""
    max_actions_in_single_turn: int = 0

    def player(self, player_id: int) -> PlayerTelemetry:
        return self.players[player_id]

    def to_replay(self, *, log: list[str]) -> ReplayRecord:
        return ReplayRecord(
            seed=self.seed,
            decks=self.decks,
            start_player=self.starting_player_id,
            winner=self.winner_id,
            end_reason=self.end_reason,
            turn_count=self.turn_count,
            actions=self.actions,
            turn_states=self.turn_states,
            modes=self.modes,
            plan_revisions=self.plan_revisions,
            anomalies=self.anomalies,
            log=log,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "decks": self.decks,
            "starting_player_id": self.starting_player_id,
            "turn_count": self.turn_count,
            "winner_id": self.winner_id,
            "loser_id": self.loser_id,
            "end_reason": self.end_reason,
            "max_actions_in_single_turn": self.max_actions_in_single_turn,
            "milestones": self.milestones,
            "players": {
                str(player_id): {
                    **{key: value for key, value in asdict(player).items() if key not in {"card_stats", "phase_stats"}},
                    "card_stats": {template_id: stats.to_dict() for template_id, stats in player.card_stats.items()},
                    "phase_stats": {phase: asdict(stats) for phase, stats in player.phase_stats.items()},
                }
                for player_id, player in self.players.items()
            },
            "actions": self.actions,
            "turn_states": self.turn_states,
            "modes": self.modes,
            "plan_revisions": self.plan_revisions,
            "anomalies": self.anomalies,
        }


@dataclass
class BatchSummary:
    total_games: int
    total_runtime_seconds: float
    results: list[GameTelemetry]
    replays: list[ReplayRecord]
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_games": self.total_games,
            "total_runtime_seconds": round(self.total_runtime_seconds, 3),
            "config": self.config,
            "games": [game.to_dict() for game in self.results],
            "replays": [replay.to_dict() for replay in self.replays],
        }

    def console_report(self) -> str:
        if not self.results:
            return "Keine Partien simuliert."
        air_wins = sum(1 for game in self.results if game.winner_id is not None and game.players[game.winner_id].deck == "air")
        fire_wins = sum(1 for game in self.results if game.winner_id is not None and game.players[game.winner_id].deck == "fire")
        unfinished = sum(1 for game in self.results if game.winner_id is None)
        avg_turns = mean(game.turn_count for game in self.results)
        shortest = min(game.turn_count for game in self.results)
        longest = max(game.turn_count for game in self.results)
        lines = [
            f"Partien: {self.total_games}",
            f"Luft Siege: {air_wins} ({air_wins / self.total_games:.1%})",
            f"Feuer Siege: {fire_wins} ({fire_wins / self.total_games:.1%})",
            f"Abbrueche: {unfinished}",
            f"Durchschnittliche Zugzahl: {avg_turns:.2f}",
            f"Kuerzeste Partie: {shortest}",
            f"Laengste Partie: {longest}",
            f"Laufzeit: {self.total_runtime_seconds:.2f}s",
        ]
        return "\n".join(lines)


def card_type_bucket(card_type: CardType) -> str:
    if card_type == CardType.CREATURE:
        return "creatures"
    if card_type == CardType.RITUAL:
        return "rituals"
    if card_type == CardType.SPELL:
        return "spells"
    return "other"
