from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .paths import BUILDER_BUILD_RESULTS_PATH, CREATURE_RESULTS_PATH, GAME_RESULTS_PATH
from .records import BuilderCreatureBuildRecord, CreatureCombatRecord, PendingCombatStats, PlayerCounters


@dataclass
class GameStatistics:
    game_id: str
    seed: int
    started_at: str
    start_player: str
    player_names: Dict[int, str]
    results_path: Path = GAME_RESULTS_PATH
    creature_results_path: Path = CREATURE_RESULTS_PATH
    builder_build_results_path: Path = BUILDER_BUILD_RESULTS_PATH
    player_stats: Dict[int, PlayerCounters] = field(default_factory=lambda: {0: PlayerCounters(), 1: PlayerCounters()})
    normal_blocks: int = 0
    multi_blocks: int = 0
    creature_combats: int = 0
    total_dice_comparisons: int = 0
    mutual_destructions: int = 0
    combats_without_destruction: int = 0
    current_turns: int = 0
    pending_combats: Dict[int, PendingCombatStats] = field(default_factory=dict)
    creature_records: List[CreatureCombatRecord] = field(default_factory=list)
    builder_creature_records: List[BuilderCreatureBuildRecord] = field(default_factory=list)
    winner: str = ""
    reaction_chains_started: int = 0
    reaction_chain_total_length: int = 0
    reaction_chain_max_length: int = 0
    reaction_passes: int = 0

    def register_turn_count(self, turn_number: int) -> None:
        self.current_turns = turn_number

    def register_draw(self, player_id: int) -> None:
        self.player_stats[player_id].cards_drawn += 1

    def register_recycled_card_drawn(self, player_id: int) -> None:
        self.player_stats[player_id].recycled_cards_drawn_again += 1

    def register_resource_played(self, player_id: int) -> None:
        self.player_stats[player_id].resources_played += 1

    def register_creature_played(self, player_id: int, recycle_cost: int = 0) -> None:
        self.player_stats[player_id].creatures_played += 1
        if recycle_cost > 0:
            self.player_stats[player_id].recycled_cards_played += 1
            self.player_stats[player_id].total_recycle_cost_paid += recycle_cost
            self.player_stats[player_id].max_recycle_paid_once = max(
                self.player_stats[player_id].max_recycle_paid_once,
                recycle_cost,
            )

    def register_builder_creature_played(
        self,
        player_id: int,
        *,
        primary_ability,
        has_haste: bool,
        turn_number: int,
        aw: int,
        vw: int,
        sw: int,
        lw: int,
        stat_cost: int,
        total_cost: int,
    ) -> None:
        ability_name = "NONE" if primary_ability is None else getattr(primary_ability, "name", str(primary_ability)).upper()
        primary_counter = {
            "FLYING": "builder_flying_creatures_played",
            "VIGILANCE": "builder_vigilance_creatures_played",
            "VIGILANT": "builder_vigilance_creatures_played",
            "TRAMPLE": "builder_trample_creatures_played",
        }.get(ability_name)
        if primary_counter is None and ability_name != "NONE":
            raise ValueError(f"Unsupported builder primary ability: {primary_ability!r}")
        self.register_creature_played(player_id)
        counters = self.player_stats[player_id]
        if primary_counter is not None:
            setattr(counters, primary_counter, getattr(counters, primary_counter) + 1)
        counters.builder_haste_creatures_played += int(has_haste)
        counters.builder_stat_points_spent += max(0, int(stat_cost))
        counters.builder_resources_spent += max(0, int(total_cost))
        self.builder_creature_records.append(
            BuilderCreatureBuildRecord(
                game_id=self.game_id,
                timestamp=datetime.now().isoformat(timespec="seconds"),
                turn=max(0, int(turn_number)),
                player_name=self.player_names[player_id],
                aw=int(aw),
                vw=int(vw),
                sw=int(sw),
                lw=int(lw),
                primary_ability="VIGILANCE" if ability_name == "VIGILANT" else ability_name,
                has_haste=int(has_haste),
                stat_cost=max(0, int(stat_cost)),
                total_cost=max(0, int(total_cost)),
            )
        )

    def register_recycle_payment(self, player_id: int, recycle_cost: int) -> None:
        self.player_stats[player_id].recycled_resources += recycle_cost

    def register_attackers(self, player_id: int, count: int) -> None:
        self.player_stats[player_id].attackers_declared += count

    def register_unblocked_attack(self, player_id: int, damage: int) -> None:
        self.player_stats[player_id].unblocked_attacks += 1
        self.player_stats[player_id].player_damage_dealt += damage

    def register_player_damage(self, player_id: int, damage: int) -> None:
        self.player_stats[player_id].player_damage_dealt += damage

    def register_ritual_played(self, player_id: int) -> None:
        self.player_stats[player_id].rituals_played += 1

    def register_spell_played(self, player_id: int) -> None:
        self.player_stats[player_id].spells_played += 1

    def register_reaction_chain_started(self) -> None:
        self.reaction_chains_started += 1

    def register_reaction_chain_length(self, length: int) -> None:
        self.reaction_chain_total_length += length
        self.reaction_chain_max_length = max(self.reaction_chain_max_length, length)

    def register_reaction_pass(self) -> None:
        self.reaction_passes += 1

    def register_spell_damage(self, player_id: int, damage: int) -> None:
        self.player_stats[player_id].spell_damage_dealt += damage

    def register_spell_self_damage(self, player_id: int, damage: int) -> None:
        self.player_stats[player_id].spell_self_damage_taken += damage

    def register_hitzeschub_play(self, player_id: int) -> None:
        self.player_stats[player_id].hitzeschub_swung_comparisons += 1

    def register_letzter_funke_damage(self, player_id: int, damage: int) -> None:
        self.player_stats[player_id].letzter_funke_damage += damage

    def register_brandzeichen_resolution(self, player_id: int) -> None:
        self.player_stats[player_id].brandzeichen_destroyed_blockers += 0

    def register_gegenfeuer_damage(self, player_id: int, damage: int) -> None:
        self.player_stats[player_id].gegenfeuer_damage += damage

    def register_flammenzorn_resolution(self, player_id: int) -> None:
        self.player_stats[player_id].flammenzorn_destroyed_creatures += 0

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
        self.pending_combats[combat_id] = PendingCombatStats(
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

    def register_dice_comparison(self, combat_id: int, attacker_damage: int, blocker_damage: int) -> None:
        pending = self.pending_combats.get(combat_id)
        if pending is None:
            return
        pending.dice_comparisons += 1
        pending.attacker_damage_dealt += attacker_damage
        pending.blocker_damage_dealt += blocker_damage
        self.total_dice_comparisons += 1
        self.player_stats[pending.attacker_owner].creature_damage_dealt += attacker_damage
        self.player_stats[pending.blocker_owner].creature_damage_dealt += blocker_damage

    def finish_creature_combat(
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
        attacker_hp_after: int,
        blocker_hp_after: int,
    ) -> None:
        pending = self.pending_combats.pop(combat_id, None)
        if pending is None:
            return
        # Damage is recorded at resolution time and is therefore exact even
        # when several battles are displayed/applied as one batch. Deriving it
        # from shared final HP double-counted damage and could become negative
        # after healing.
        attacker_damage_taken = pending.blocker_damage_dealt
        blocker_damage_taken = pending.attacker_damage_dealt
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

    def finalize_game(
        self,
        winner: str,
        human_life: int,
        ai_life: int,
        human_resources_remaining: int,
        ai_resources_remaining: int,
    ) -> Dict[str, str]:
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
            "human_resources_remaining": str(human_resources_remaining),
            "ai_resources_remaining": str(ai_resources_remaining),
            "human_creatures_played": str(self.player_stats[0].creatures_played),
            "ai_creatures_played": str(self.player_stats[1].creatures_played),
            "human_recycled_resources": str(self.player_stats[0].recycled_resources),
            "ai_recycled_resources": str(self.player_stats[1].recycled_resources),
            "human_recycled_cards_played": str(self.player_stats[0].recycled_cards_played),
            "ai_recycled_cards_played": str(self.player_stats[1].recycled_cards_played),
            "human_avg_recycle_cost": f"{(self.player_stats[0].total_recycle_cost_paid / self.player_stats[0].creatures_played) if self.player_stats[0].creatures_played else 0.0:.2f}",
            "ai_avg_recycle_cost": f"{(self.player_stats[1].total_recycle_cost_paid / self.player_stats[1].creatures_played) if self.player_stats[1].creatures_played else 0.0:.2f}",
            "human_max_recycle_paid_once": str(self.player_stats[0].max_recycle_paid_once),
            "ai_max_recycle_paid_once": str(self.player_stats[1].max_recycle_paid_once),
            "human_recycled_cards_drawn_again": str(self.player_stats[0].recycled_cards_drawn_again),
            "ai_recycled_cards_drawn_again": str(self.player_stats[1].recycled_cards_drawn_again),
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
            "human_rituals_played": str(self.player_stats[0].rituals_played),
            "ai_rituals_played": str(self.player_stats[1].rituals_played),
            "human_spells_played": str(self.player_stats[0].spells_played),
            "ai_spells_played": str(self.player_stats[1].spells_played),
            "reaction_chains_started": str(self.reaction_chains_started),
            "avg_reaction_chain_length": f"{(self.reaction_chain_total_length / self.reaction_chains_started) if self.reaction_chains_started else 0.0:.2f}",
            "max_reaction_chain_length": str(self.reaction_chain_max_length),
            "reaction_passes": str(self.reaction_passes),
            "human_spell_damage_dealt": str(self.player_stats[0].spell_damage_dealt),
            "ai_spell_damage_dealt": str(self.player_stats[1].spell_damage_dealt),
            "human_spell_self_damage_taken": str(self.player_stats[0].spell_self_damage_taken),
            "ai_spell_self_damage_taken": str(self.player_stats[1].spell_self_damage_taken),
            "avg_dice_comparisons_per_combat": f"{average:.2f}",
            "start_player": self.start_player,
        }
        self.append_game_result(row)
        self.append_creature_results()
        self.append_builder_creature_results()
        return row

    def append_game_result(self, row: Dict[str, str]) -> None:
        fieldnames = list(row.keys())
        if not self.results_path.exists() or self.results_path.stat().st_size == 0:
            with self.results_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(row)
            return

        with self.results_path.open(newline="", encoding="utf-8-sig") as handle:
            raw_rows = list(csv.reader(handle))
        existing_header = raw_rows[0] if raw_rows else []
        existing_rows = raw_rows[1:]
        schema_is_current = (
            existing_header[: len(fieldnames)] == fieldnames
            and all(len(values) == len(existing_header) for values in existing_rows)
        )
        if schema_is_current:
            with self.results_path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=existing_header)
                writer.writerow(row)
            return

        self._migrate_and_append_game_results(existing_header, existing_rows, row)

    def _migrate_and_append_game_results(
        self,
        existing_header: list[str],
        existing_rows: list[list[str]],
        row: Dict[str, str],
    ) -> None:
        current_fields = list(row.keys())
        schema_43 = current_fields[:11] + current_fields[11:41] + current_fields[-2:]
        schema_57 = current_fields[:-2] + [
            "human_verbotene_glut_cards_drawn",
            "ai_verbotene_glut_cards_drawn",
        ] + current_fields[-2:]
        schemas_by_width = {
            len(existing_header): existing_header,
            43: schema_43,
            len(current_fields): current_fields,
            57: schema_57,
        }
        migrated_fields = list(current_fields)
        for schema in (existing_header, schema_43, schema_57):
            for name in schema:
                if name not in migrated_fields:
                    migrated_fields.append(name)

        aliases = {
            "human_units_played": "human_creatures_played",
            "ai_units_played": "ai_creatures_played",
            "unit_combats": "creature_combats",
            "human_units_destroyed": "human_creatures_destroyed",
            "ai_units_destroyed": "ai_creatures_destroyed",
            "human_unit_damage_dealt": "human_creature_damage_dealt",
            "ai_unit_damage_dealt": "ai_creature_damage_dealt",
        }
        migrated_rows: list[dict[str, str]] = []
        for values in existing_rows:
            schema = schemas_by_width.get(len(values))
            if schema is None:
                schema = existing_header[: len(values)]
            migrated = dict(zip(schema, values))
            for old_name, current_name in aliases.items():
                if old_name in migrated and current_name not in migrated:
                    migrated[current_name] = migrated[old_name]
            migrated_rows.append(migrated)
        migrated_rows.append(dict(row))

        backup_path = self.results_path.with_suffix(self.results_path.suffix + ".pre-schema-migration.bak")
        if not backup_path.exists():
            shutil.copy2(self.results_path, backup_path)
        temporary_path = self.results_path.with_suffix(self.results_path.suffix + ".schema-migration.tmp")
        with temporary_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=migrated_fields)
            writer.writeheader()
            writer.writerows(migrated_rows)
        temporary_path.replace(self.results_path)

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

    def append_builder_creature_results(self) -> None:
        fieldnames = [
            "game_id", "timestamp", "turn", "player_name", "aw", "vw", "sw", "lw",
            "primary_ability", "has_haste", "stat_cost", "total_cost",
        ]
        write_header = not self.builder_build_results_path.exists()
        with self.builder_build_results_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            for record in self.builder_creature_records:
                writer.writerow(record.__dict__)
