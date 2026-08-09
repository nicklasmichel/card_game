from __future__ import annotations

import unittest
from unittest.mock import patch

import core.config as config
from core.game_logic import GameEngine
from core.models import PHASE_BUILDER_CREATURE, PHASE_GAME_OVER, PHASE_MAIN_1, PlayerState, ResourceCard


class BuilderModeTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(config, "GAME_MODE", "builder")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = GameEngine()
        self.engine.log_messages.clear()

    def make_builder_resource(self, *, tapped: bool = False) -> ResourceCard:
        return ResourceCard(
            template=self.engine.builder_resource_template(),
            resource_id=self.engine.make_instance_id(),
            tapped=tapped,
        )

    def set_builder_resources(self, player, total: int, *, tapped: int = 0) -> None:
        player.resources = [self.make_builder_resource(tapped=index < tapped) for index in range(total)]

    def test_normal_mode_still_starts_with_decks_and_hands(self) -> None:
        with patch.object(config, "GAME_MODE", "normal"):
            engine = GameEngine()
        self.assertEqual(engine.phase, "Mulligan")
        self.assertTrue(engine.human_player.deck)
        self.assertTrue(engine.ai_player.deck)
        self.assertEqual(len(engine.human_player.hand), 5)
        self.assertEqual(len(engine.ai_player.hand), 5)

    def test_builder_start_has_no_deck_or_hand_and_one_ready_resource(self) -> None:
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        for player in self.engine.players:
            self.assertEqual(player.life, 10)
            self.assertEqual(player.total_resources(), 1)
            self.assertEqual(player.available_resources(), 1)
            self.assertEqual(player.hand, [])
            self.assertEqual(player.deck, [])

    def test_builder_resource_action_adds_one_ready_resource_and_consumes_main_action(self) -> None:
        player = self.engine.human_player
        self.engine.active_player_index = player.player_id
        self.engine.phase = PHASE_MAIN_1

        self.assertTrue(self.engine.builder_add_resource(player))

        self.assertEqual(player.total_resources(), 2)
        self.assertEqual(player.available_resources(), 2)
        self.assertTrue(player.main_action_used_this_turn)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertIn("Keine bereiten Kreaturen fuer einen Angriff. Der Zug endet automatisch.", self.engine.log_messages)

    def test_builder_creature_build_spends_exact_resources_and_creates_creature(self) -> None:
        player = self.engine.human_player
        self.engine.active_player_index = player.player_id
        self.engine.phase = PHASE_MAIN_1
        self.set_builder_resources(player, 4)

        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 2)
        self.engine.adjust_builder_creature_stat("vw", 1)
        self.engine.adjust_builder_creature_stat("lw", 1)

        self.assertEqual(self.engine.phase, PHASE_BUILDER_CREATURE)
        self.assertEqual(self.engine.builder_creature_build_cost(), 4)
        self.assertTrue(self.engine.confirm_builder_creature_build())

        self.assertEqual(len(player.battlefield), 1)
        creature = player.battlefield[0]
        self.assertEqual((creature.aw, creature.vw, creature.sw, creature.lw), (2, 1, 0, 2))
        self.assertEqual(player.available_resources(), 0)
        self.assertEqual(sum(1 for resource in player.resources if resource.tapped), 4)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertIn("Keine bereiten Kreaturen fuer einen Angriff. Der Zug endet automatisch.", self.engine.log_messages)

    def test_builder_creature_build_can_leave_resources_ready(self) -> None:
        player = self.engine.human_player
        self.engine.active_player_index = player.player_id
        self.engine.phase = PHASE_MAIN_1
        self.set_builder_resources(player, 5)

        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.engine.adjust_builder_creature_stat("vw", 1)
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.assertTrue(self.engine.confirm_builder_creature_build())

        self.assertEqual(player.available_resources(), 2)
        self.assertEqual(sum(1 for resource in player.resources if resource.tapped), 3)

    def test_builder_preview_creature_reflects_pending_stats(self) -> None:
        player = self.engine.human_player
        self.engine.active_player_index = player.player_id
        self.engine.phase = PHASE_MAIN_1
        self.set_builder_resources(player, 5)

        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 2)
        self.engine.adjust_builder_creature_stat("vw", 1)
        self.engine.adjust_builder_creature_stat("lw", 1)

        preview = self.engine.get_builder_preview_creature(player)

        self.assertIsNotNone(preview)
        self.assertEqual(preview.template_id, "builder_creature_preview")
        self.assertEqual(preview.name, "Neue Kreatur")
        self.assertEqual((preview.aw, preview.vw, preview.sw, preview.lw), (2, 1, 0, 2))
        self.assertEqual(preview.cost.resources, 4)
        self.assertTrue(getattr(preview, "is_builder_preview", False))
        self.assertTrue(preview.tapped)
        self.assertTrue(preview.summoning_sick)

    def test_builder_keeps_second_step_only_when_ready_attacker_exists(self) -> None:
        player = self.engine.human_player
        self.engine.active_player_index = player.player_id
        self.engine.phase = PHASE_MAIN_1
        ready_attacker = self.engine.create_builder_creature(player, aw=1, vw=1, sw=1, lw=1)
        ready_attacker.tapped = False
        ready_attacker.summoning_sick = False

        self.assertTrue(self.engine.builder_add_resource(player))

        self.assertEqual(self.engine.active_player, player)
        labels = [button.label for button in self.engine.get_button_specs()]
        self.assertEqual(labels, ["Zum Kampf", "Zug beenden"])

    def test_builder_resource_action_is_blocked_at_ten_resources(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 10)

        self.assertFalse(self.engine.can_builder_add_resource(player))
        self.assertFalse(self.engine.builder_add_resource(player))
        self.assertEqual(player.total_resources(), 10)

    def test_builder_resources_refresh_at_start_of_next_turn(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 4, tapped=3)
        self.engine.active_player_index = player.player_id

        self.engine.start_turn()

        self.assertEqual(player.available_resources(), 4)

    def test_builder_creature_has_summoning_sickness_then_can_attack_next_turn(self) -> None:
        player = self.engine.human_player
        self.engine.active_player_index = player.player_id
        self.engine.phase = PHASE_MAIN_1
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[0]

        self.assertFalse(creature.is_ready())
        self.assertNotIn(creature, self.engine.available_attackers(player))

        self.engine.active_player_index = player.player_id
        self.engine.start_turn()

        self.assertTrue(creature.is_ready())
        self.assertIn(creature, self.engine.available_attackers(player))
        self.engine.block_assignments = {creature.unit_id: None}
        self.engine.begin_combat_resolution()
        self.assertLess(self.engine.ai_player.life, 10)

    def test_builder_ai_creature_plan_is_legal(self) -> None:
        player = self.engine.ai_player
        self.set_builder_resources(player, 6)

        plan = self.engine.ai.choose_builder_creature_plan(player, self.engine)

        self.assertIsNotNone(plan)
        self.assertGreaterEqual(plan["cost"], 1)
        self.assertLessEqual(plan["cost"], player.available_resources())
        self.assertEqual(plan["cost"], plan["aw"] + plan["vw"] + plan["sw"] + max(0, plan["lw"] - 1))

    def test_builder_ai_can_take_actions_and_complete_smoke_game(self) -> None:
        self.engine.players = [
            PlayerState(0, "Spieler", False, summoner_key="builder", life=10, resources=[self.make_builder_resource()]),
            PlayerState(1, "Gegner", False, summoner_key="builder", life=10, resources=[self.make_builder_resource()]),
        ]
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_MAIN_1
        self.engine.turn_number = 0
        self.engine.reset_combat_state()

        steps = 0
        while self.engine.phase != PHASE_GAME_OVER and steps < 60:
            steps += 1
            if self.engine.phase in {PHASE_MAIN_1}:
                if not self.engine.prepare_ai_turn_action():
                    break
                self.engine.execute_prepared_ai_action()
                continue
            if self.engine.phase == "Angreifer waehlen":
                self.engine.process_ai_turn()
                continue
            if self.engine.phase == "Blocker waehlen":
                self.engine.process_ai_turn()
                continue
            if self.engine.phase == "Wuerfelkampf":
                self.engine.end_dice_battle()
                continue
            break

        total_creatures = len(self.engine.human_player.battlefield) + len(self.engine.ai_player.battlefield)
        total_resources = self.engine.human_player.total_resources() + self.engine.ai_player.total_resources()
        self.assertGreaterEqual(steps, 6)
        self.assertTrue(total_creatures > 0 or total_resources > 2)


if __name__ == "__main__":
    unittest.main()
