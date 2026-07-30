from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List


GAME_RESULTS_PATH = Path("game_results.csv")
UNIT_RESULTS_PATH = Path("unit_combat_results.csv")


@dataclass
class PlayerCounters:
    cards_drawn: int = 0
    resources_played: int = 0
    units_played: int = 0
    attackers_declared: int = 0
    unblocked_attacks: int = 0
    units_destroyed: int = 0
    player_damage_dealt: int = 0
    unit_damage_dealt: int = 0


@dataclass
class UnitCombatRecord:
    game_id: str
    combat_id: int
    timestamp: str
    player_name: str
    unit_name: str
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
    attacker_name: str
    blocker_name: str
    attacker_aw: int
    attacker_vw: int
    blocker_aw: int
    blocker_vw: int
    attacker_hp_before: int
    blocker_hp_before: int
    dice_comparisons: int = 0
    attacker_damage_dealt: int = 0
    blocker_damage_dealt: int = 0


@dataclass
class GameStatistics:
    game_id: str
    seed: int
    started_at: str
    start_player: str
    player_names: Dict[int, str]
    results_path: Path = GAME_RESULTS_PATH
    unit_results_path: Path = UNIT_RESULTS_PATH
    player_stats: Dict[int, PlayerCounters] = field(
        default_factory=lambda: {0: PlayerCounters(), 1: PlayerCounters()}
    )
    normal_blocks: int = 0
    multi_blocks: int = 0
    unit_combats: int = 0
    total_dice_comparisons: int = 0
    mutual_destructions: int = 0
    combats_without_destruction: int = 0
    current_turns: int = 0
    current_pending_combat: PendingCombatStats | None = None
    unit_records: List[UnitCombatRecord] = field(default_factory=list)
    winner: str = ""

    def register_turn_count(self, turn_number: int) -> None:
        self.current_turns = turn_number

    def register_draw(self, player_id: int) -> None:
        self.player_stats[player_id].cards_drawn += 1

    def register_resource_played(self, player_id: int) -> None:
        self.player_stats[player_id].resources_played += 1

    def register_unit_played(self, player_id: int) -> None:
        self.player_stats[player_id].units_played += 1

    def register_attackers(self, player_id: int, count: int) -> None:
        self.player_stats[player_id].attackers_declared += count

    def register_unblocked_attack(self, player_id: int, damage: int) -> None:
        self.player_stats[player_id].unblocked_attacks += 1
        self.player_stats[player_id].player_damage_dealt += damage

    def register_block_assignment(self, blocker_count: int) -> None:
        if blocker_count == 1:
            self.normal_blocks += 1
        elif blocker_count > 1:
            self.multi_blocks += 1

    def start_unit_combat(
        self,
        combat_id: int,
        attacker_owner: int,
        blocker_owner: int,
        attacker_name: str,
        blocker_name: str,
        attacker_aw: int,
        attacker_vw: int,
        blocker_aw: int,
        blocker_vw: int,
        attacker_hp_before: int,
        blocker_hp_before: int,
    ) -> None:
        self.unit_combats += 1
        self.current_pending_combat = PendingCombatStats(
            combat_id=combat_id,
            attacker_owner=attacker_owner,
            blocker_owner=blocker_owner,
            attacker_name=attacker_name,
            blocker_name=blocker_name,
            attacker_aw=attacker_aw,
            attacker_vw=attacker_vw,
            blocker_aw=blocker_aw,
            blocker_vw=blocker_vw,
            attacker_hp_before=attacker_hp_before,
            blocker_hp_before=blocker_hp_before,
        )

    def register_dice_comparison(
        self,
        attacker_damage: int,
        blocker_damage: int,
    ) -> None:
        if self.current_pending_combat is None:
            return
        self.current_pending_combat.dice_comparisons += 1
        self.current_pending_combat.attacker_damage_dealt += attacker_damage
        self.current_pending_combat.blocker_damage_dealt += blocker_damage
        self.total_dice_comparisons += 1
        self.player_stats[self.current_pending_combat.attacker_owner].unit_damage_dealt += attacker_damage
        self.player_stats[self.current_pending_combat.blocker_owner].unit_damage_dealt += blocker_damage

    def finish_unit_combat(
        self,
        attacker_owner: int,
        blocker_owner: int,
        attacker_name: str,
        blocker_name: str,
        attacker_aw: int,
        attacker_vw: int,
        blocker_aw: int,
        blocker_vw: int,
        attacker_hp_after: int,
        blocker_hp_after: int,
    ) -> None:
        if self.current_pending_combat is None:
            return

        pending = self.current_pending_combat
        attacker_damage_taken = pending.attacker_hp_before - max(attacker_hp_after, 0)
        blocker_damage_taken = pending.blocker_hp_before - max(blocker_hp_after, 0)
        attacker_destroyed = attacker_hp_after <= 0
        blocker_destroyed = blocker_hp_after <= 0

        if attacker_destroyed and blocker_destroyed:
            self.mutual_destructions += 1
        if not attacker_destroyed and not blocker_destroyed:
            self.combats_without_destruction += 1
        if attacker_destroyed:
            self.player_stats[attacker_owner].units_destroyed += 1
        if blocker_destroyed:
            self.player_stats[blocker_owner].units_destroyed += 1

        timestamp = datetime.now().isoformat(timespec="seconds")
        self.unit_records.extend(
            [
                UnitCombatRecord(
                    game_id=self.game_id,
                    combat_id=pending.combat_id,
                    timestamp=timestamp,
                    player_name=self.player_names[attacker_owner],
                    unit_name=attacker_name,
                    aw=attacker_aw,
                    vw=attacker_vw,
                    role="Angreifer",
                    won=1 if blocker_destroyed and not attacker_destroyed else 0,
                    lost=1 if attacker_destroyed else 0,
                    survived=1 if not attacker_destroyed else 0,
                    damage_dealt=pending.attacker_damage_dealt,
                    damage_taken=attacker_damage_taken,
                    dice_comparisons=pending.dice_comparisons,
                ),
                UnitCombatRecord(
                    game_id=self.game_id,
                    combat_id=pending.combat_id,
                    timestamp=timestamp,
                    player_name=self.player_names[blocker_owner],
                    unit_name=blocker_name,
                    aw=blocker_aw,
                    vw=blocker_vw,
                    role="Blocker",
                    won=1 if attacker_destroyed and not blocker_destroyed else 0,
                    lost=1 if blocker_destroyed else 0,
                    survived=1 if not blocker_destroyed else 0,
                    damage_dealt=pending.blocker_damage_dealt,
                    damage_taken=blocker_damage_taken,
                    dice_comparisons=pending.dice_comparisons,
                ),
            ]
        )
        self.current_pending_combat = None

    def finalize_game(self, winner: str, human_life: int, ai_life: int) -> Dict[str, str]:
        self.winner = winner
        average = self.total_dice_comparisons / self.unit_combats if self.unit_combats else 0.0
        row = {
            "game_id": self.game_id,
            "timestamp": self.started_at,
            "seed": str(self.seed),
            "winner": winner,
            "turns_played": str(self.current_turns),
            "human_life_end": str(human_life),
            "ai_life_end": str(ai_life),
            "human_cards_drawn": str(self.player_stats[0].cards_drawn),
            "ai_cards_drawn": str(self.player_stats[1].cards_drawn),
            "human_resources_played": str(self.player_stats[0].resources_played),
            "ai_resources_played": str(self.player_stats[1].resources_played),
            "human_units_played": str(self.player_stats[0].units_played),
            "ai_units_played": str(self.player_stats[1].units_played),
            "human_attackers_declared": str(self.player_stats[0].attackers_declared),
            "ai_attackers_declared": str(self.player_stats[1].attackers_declared),
            "human_unblocked_attacks": str(self.player_stats[0].unblocked_attacks),
            "ai_unblocked_attacks": str(self.player_stats[1].unblocked_attacks),
            "normal_blocks": str(self.normal_blocks),
            "multi_blocks": str(self.multi_blocks),
            "unit_combats": str(self.unit_combats),
            "dice_comparisons": str(self.total_dice_comparisons),
            "human_units_destroyed": str(self.player_stats[0].units_destroyed),
            "ai_units_destroyed": str(self.player_stats[1].units_destroyed),
            "mutual_destructions": str(self.mutual_destructions),
            "combats_without_destruction": str(self.combats_without_destruction),
            "human_player_damage_dealt": str(self.player_stats[0].player_damage_dealt),
            "ai_player_damage_dealt": str(self.player_stats[1].player_damage_dealt),
            "human_unit_damage_dealt": str(self.player_stats[0].unit_damage_dealt),
            "ai_unit_damage_dealt": str(self.player_stats[1].unit_damage_dealt),
            "avg_dice_comparisons_per_combat": f"{average:.2f}",
            "start_player": self.start_player,
        }
        self.append_game_result(row)
        self.append_unit_results()
        return row

    def append_game_result(self, row: Dict[str, str]) -> None:
        fieldnames = list(row.keys())
        write_header = not self.results_path.exists()
        with self.results_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def append_unit_results(self) -> None:
        fieldnames = [
            "game_id",
            "combat_id",
            "timestamp",
            "player_name",
            "unit_name",
            "aw",
            "vw",
            "role",
            "won",
            "lost",
            "survived",
            "damage_dealt",
            "damage_taken",
            "dice_comparisons",
        ]
        write_header = not self.unit_results_path.exists()
        with self.unit_results_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            for record in self.unit_records:
                writer.writerow(record.__dict__)
