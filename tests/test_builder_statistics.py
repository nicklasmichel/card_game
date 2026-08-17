from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.models import Ability
from stats.tracker import GameStatistics


class BuilderStatisticsTests(unittest.TestCase):
    def make_statistics(self, directory: Path) -> GameStatistics:
        return GameStatistics(
            game_id="builder-stats-test",
            seed=17,
            started_at="2026-08-16T12:00:00",
            start_player="Player 1",
            player_names={0: "Player 1", 1: "Player 2"},
            results_path=directory / "games.csv",
            creature_results_path=directory / "combats.csv",
            builder_build_results_path=directory / "builder-builds.csv",
        )

    def test_registers_paid_haste_separately_from_stat_cost_and_primary_ability(self) -> None:
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            statistics = self.make_statistics(directory)

            statistics.register_builder_creature_played(
                1,
                primary_ability=Ability.FLYING,
                has_haste=True,
                turn_number=7,
                aw=1,
                vw=0,
                sw=2,
                lw=2,
                stat_cost=4,
                total_cost=5,
            )

            counters = statistics.player_stats[1]
            self.assertEqual(counters.creatures_played, 1)
            self.assertEqual(counters.builder_flying_creatures_played, 1)
            self.assertEqual(counters.builder_haste_creatures_played, 1)
            self.assertEqual(counters.builder_stat_points_spent, 4)
            self.assertEqual(counters.builder_resources_spent, 5)

            statistics.finalize_game(
                winner="Player 2",
                human_life=0,
                ai_life=4,
                human_resources_remaining=5,
                ai_resources_remaining=5,
            )
            with statistics.builder_build_results_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["player_name"], "Player 2")
            self.assertEqual(rows[0]["primary_ability"], "FLYING")
            self.assertEqual(rows[0]["has_haste"], "1")
            self.assertEqual(rows[0]["stat_cost"], "4")
            self.assertEqual(rows[0]["total_cost"], "5")

    def test_rejects_invalid_primary_ability_without_mutating_counters(self) -> None:
        with TemporaryDirectory() as directory_name:
            statistics = self.make_statistics(Path(directory_name))

            with self.assertRaises(ValueError):
                statistics.register_builder_creature_played(
                    0,
                    primary_ability=Ability.HASTE,
                    has_haste=True,
                    turn_number=1,
                    aw=0,
                    vw=0,
                    sw=0,
                    lw=1,
                    stat_cost=0,
                    total_cost=1,
                )

            self.assertEqual(statistics.player_stats[0].creatures_played, 0)
            self.assertEqual(statistics.builder_creature_records, [])

    def test_concurrent_combats_keep_damage_attached_to_their_own_combat_id(self) -> None:
        with TemporaryDirectory() as directory_name:
            statistics = self.make_statistics(Path(directory_name))
            for combat_id, attacker_name, blocker_name, attacker_hp, blocker_hp in (
                (101, "Attacker A", "Blocker A", 5, 4),
                (102, "Attacker B", "Blocker B", 3, 6),
            ):
                statistics.start_creature_combat(
                    combat_id=combat_id,
                    attacker_owner=0,
                    blocker_owner=1,
                    attacker_creature_name=attacker_name,
                    blocker_creature_name=blocker_name,
                    attacker_aw=3,
                    attacker_vw=2,
                    blocker_aw=2,
                    blocker_vw=3,
                    attacker_hp_before=attacker_hp,
                    blocker_hp_before=blocker_hp,
                )

            statistics.register_dice_comparison(combat_id=101, attacker_damage=3, blocker_damage=0)
            statistics.register_dice_comparison(combat_id=102, attacker_damage=0, blocker_damage=2)
            statistics.finish_creature_combat(
                combat_id=101,
                attacker_owner=0,
                blocker_owner=1,
                attacker_creature_name="Attacker A",
                blocker_creature_name="Blocker A",
                attacker_aw=3,
                attacker_vw=2,
                blocker_aw=2,
                blocker_vw=3,
                attacker_hp_after=5,
                blocker_hp_after=1,
            )
            statistics.finish_creature_combat(
                combat_id=102,
                attacker_owner=0,
                blocker_owner=1,
                attacker_creature_name="Attacker B",
                blocker_creature_name="Blocker B",
                attacker_aw=3,
                attacker_vw=2,
                blocker_aw=2,
                blocker_vw=3,
                attacker_hp_after=1,
                blocker_hp_after=6,
            )

            records = {(record.combat_id, record.role): record for record in statistics.creature_records}
            self.assertEqual(records[(101, "Angreifer")].damage_dealt, 3)
            self.assertEqual(records[(101, "Blocker")].damage_taken, 3)
            self.assertEqual(records[(102, "Blocker")].damage_dealt, 2)
            self.assertEqual(records[(102, "Angreifer")].damage_taken, 2)
            self.assertTrue(all(record.damage_taken >= 0 for record in records.values()))
            self.assertEqual(statistics.pending_combats, {})

    def test_combat_finish_does_not_double_count_engine_owned_creature_removal(self) -> None:
        with TemporaryDirectory() as directory_name:
            statistics = self.make_statistics(Path(directory_name))
            statistics.start_creature_combat(
                combat_id=201,
                attacker_owner=0,
                blocker_owner=1,
                attacker_creature_name="Attacker",
                blocker_creature_name="Blocker",
                attacker_aw=3,
                attacker_vw=2,
                blocker_aw=2,
                blocker_vw=3,
                attacker_hp_before=3,
                blocker_hp_before=1,
            )
            statistics.register_dice_comparison(combat_id=201, attacker_damage=1, blocker_damage=0)
            # destroy_creature_immediately already recorded this removal.
            statistics.player_stats[1].creatures_destroyed = 1

            statistics.finish_creature_combat(
                combat_id=201,
                attacker_owner=0,
                blocker_owner=1,
                attacker_creature_name="Attacker",
                blocker_creature_name="Blocker",
                attacker_aw=3,
                attacker_vw=2,
                blocker_aw=2,
                blocker_vw=3,
                attacker_hp_after=3,
                blocker_hp_after=0,
            )

            self.assertEqual(statistics.player_stats[1].creatures_destroyed, 1)

    def test_game_result_schema_migration_preserves_mixed_historical_rows(self) -> None:
        with TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source_directory = root / "source"
            target_directory = root / "target"
            source_directory.mkdir()
            target_directory.mkdir()
            source = self.make_statistics(source_directory)
            source.finalize_game(
                winner="Player 1",
                human_life=7,
                ai_life=0,
                human_resources_remaining=4,
                ai_resources_remaining=4,
            )
            with source.results_path.open(newline="", encoding="utf-8") as handle:
                current_file_rows = list(csv.reader(handle))

            target = self.make_statistics(target_directory)
            with target.results_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["game_id", "timestamp", "seed", "winner"])
                writer.writerow(["legacy-game", "2026-01-01T00:00:00", "1", "Player 2"])
                writer.writerow(current_file_rows[1])

            target.finalize_game(
                winner="Player 1",
                human_life=5,
                ai_life=0,
                human_resources_remaining=5,
                ai_resources_remaining=5,
            )

            with target.results_path.open(newline="", encoding="utf-8") as handle:
                raw_rows = list(csv.reader(handle))
            with target.results_path.open(newline="", encoding="utf-8") as handle:
                migrated_rows = list(csv.DictReader(handle))

            self.assertEqual(len(migrated_rows), 3)
            self.assertEqual(migrated_rows[0]["game_id"], "legacy-game")
            self.assertEqual(migrated_rows[0]["winner"], "Player 2")
            self.assertEqual(migrated_rows[1]["human_life_end"], "7")
            self.assertEqual(migrated_rows[2]["human_life_end"], "5")
            self.assertTrue(all(len(values) == len(raw_rows[0]) for values in raw_rows[1:]))
            self.assertTrue(target.results_path.with_suffix(".csv.pre-schema-migration.bak").exists())


if __name__ == "__main__":
    unittest.main()
