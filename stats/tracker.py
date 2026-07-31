from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .paths import CREATURE_RESULTS_PATH, GAME_RESULTS_PATH
from .records import CreatureCombatRecord, PendingCombatStats, PlayerCounters


@dataclass
class GameStatistics:
    game_id: str
    seed: int
    started_at: str
    start_player: str
    player_names: Dict[int, str]
    results_path: Path = GAME_RESULTS_PATH
    creature_results_path: Path = CREATURE_RESULTS_PATH
    player_stats: Dict[int, PlayerCounters] = field(default_factory=lambda: {0: PlayerCounters(), 1: PlayerCounters()})
    normal_blocks: int = 0
    multi_blocks: int = 0
    creature_combats: int = 0
    total_dice_comparisons: int = 0
    mutual_destructions: int = 0
    combats_without_destruction: int = 0
    current_turns: int = 0
    current_pending_combat: PendingCombatStats | None = None
    creature_records: List[CreatureCombatRecord] = field(default_factory=list)
    winner: str = ""

    def register_turn_count(self, turn_number: int) -> None:
        self.current_turns = turn_number

    def register_draw(self, player_id: int) -> None:
        self.player_stats[player_id].cards_drawn += 1

    def register_resource_played(self, player_id: int) -> None:
        self.player_stats[player_id].resources_played += 1

    def register_creature_played(self, player_id: int) -> None:
        self.player_stats[player_id].creatures_played += 1

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

    def start_creature_combat(
        self,
        combat_id: int,
        attacker_owner: int,
        blocker_owner: int,
        attacker_creature_name: str,
        blocker_creature_name: str,
        attacker_aw: int,
        attacker_vw: int,
        blocker_aw: int,
        blocker_vw: int,
        attacker_hp_before: int,
        blocker_hp_before: int,
    ) -> None:
        self.creature_combats += 1
        self.current_pending_combat = PendingCombatStats(
            combat_id=combat_id,
            attacker_owner=attacker_owner,
            blocker_owner=blocker_owner,
            attacker_creature_name=attacker_creature_name,
            blocker_creature_name=blocker_creature_name,
            attacker_aw=attacker_aw,
            attacker_vw=attacker_vw,
            blocker_aw=blocker_aw,
            blocker_vw=blocker_vw,
            attacker_hp_before=attacker_hp_before,
            blocker_hp_before=blocker_hp_before,
        )

    def register_dice_comparison(self, attacker_damage: int, blocker_damage: int) -> None:
        if self.current_pending_combat is None:
            return
        self.current_pending_combat.dice_comparisons += 1
        self.current_pending_combat.attacker_damage_dealt += attacker_damage
        self.current_pending_combat.blocker_damage_dealt += blocker_damage
        self.total_dice_comparisons += 1
        self.player_stats[self.current_pending_combat.attacker_owner].creature_damage_dealt += attacker_damage
        self.player_stats[self.current_pending_combat.blocker_owner].creature_damage_dealt += blocker_damage

    def finish_creature_combat(
        self,
        attacker_owner: int,
        blocker_owner: int,
        attacker_creature_name: str,
        blocker_creature_name: str,
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
            self.player_stats[attacker_owner].creatures_destroyed += 1
        if blocker_destroyed:
            self.player_stats[blocker_owner].creatures_destroyed += 1
        timestamp = datetime.now().isoformat(timespec="seconds")
        self.creature_records.extend([
            CreatureCombatRecord(
                game_id=self.game_id,
                combat_id=pending.combat_id,
                timestamp=timestamp,
                player_name=self.player_names[attacker_owner],
                creature_name=attacker_creature_name,
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
            CreatureCombatRecord(
                game_id=self.game_id,
                combat_id=pending.combat_id,
                timestamp=timestamp,
                player_name=self.player_names[blocker_owner],
                creature_name=blocker_creature_name,
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
        ])
        self.current_pending_combat = None

    def finalize_game(self, winner: str, human_life: int, ai_life: int) -> Dict[str, str]:
        self.winner = winner
        average = self.total_dice_comparisons / self.creature_combats if self.creature_combats else 0.0
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
            "human_creatures_played": str(self.player_stats[0].creatures_played),
            "ai_creatures_played": str(self.player_stats[1].creatures_played),
            "human_attackers_declared": str(self.player_stats[0].attackers_declared),
            "ai_attackers_declared": str(self.player_stats[1].attackers_declared),
            "human_unblocked_attacks": str(self.player_stats[0].unblocked_attacks),
            "ai_unblocked_attacks": str(self.player_stats[1].unblocked_attacks),
            "normal_blocks": str(self.normal_blocks),
            "multi_blocks": str(self.multi_blocks),
            "creature_combats": str(self.creature_combats),
            "dice_comparisons": str(self.total_dice_comparisons),
            "human_creatures_destroyed": str(self.player_stats[0].creatures_destroyed),
            "ai_creatures_destroyed": str(self.player_stats[1].creatures_destroyed),
            "mutual_destructions": str(self.mutual_destructions),
            "combats_without_destruction": str(self.combats_without_destruction),
            "human_player_damage_dealt": str(self.player_stats[0].player_damage_dealt),
            "ai_player_damage_dealt": str(self.player_stats[1].player_damage_dealt),
            "human_creature_damage_dealt": str(self.player_stats[0].creature_damage_dealt),
            "ai_creature_damage_dealt": str(self.player_stats[1].creature_damage_dealt),
            "avg_dice_comparisons_per_combat": f"{average:.2f}",
            "start_player": self.start_player,
        }
        self.append_game_result(row)
        self.append_creature_results()
        return row

    def append_game_result(self, row: Dict[str, str]) -> None:
        fieldnames = list(row.keys())
        write_header = not self.results_path.exists()
        with self.results_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def append_creature_results(self) -> None:
        fieldnames = [
            "game_id", "combat_id", "timestamp", "player_name", "creature_name", "aw", "vw",
            "role", "won", "lost", "survived", "damage_dealt", "damage_taken", "dice_comparisons",
        ]
        write_header = not self.creature_results_path.exists()
        with self.creature_results_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            for record in self.creature_records:
                writer.writerow(record.__dict__)
