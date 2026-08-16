from __future__ import annotations

import unittest
from unittest.mock import patch

from core.builder_rules import (
    BUILDER_ABILITIES_ENABLED,
    BUILDER_CREATURE_CAP,
    BUILDER_HASTE_COST,
    BUILDER_PRIMARY_ABILITIES,
    validate_builder_creature_abilities,
)
from core.config import STARTING_LIFE
from core.game_logic import GameEngine
from core.models import Ability, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_GAME_OVER, PHASE_MAIN_1, PlayerState, ResourceCard
from ui.layout_sidepanel import get_overview_phase_label


class BuilderModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine()
        self.engine.log_messages.clear()
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_MAIN_1

    def make_builder_resource(self, *, tapped: bool = False) -> ResourceCard:
        return ResourceCard(
            template=self.engine.builder_resource_template(),
            resource_id=self.engine.make_instance_id(),
            tapped=tapped,
        )

    def set_builder_resources(self, player, total: int, *, tapped: int = 0) -> None:
        player.resources = [self.make_builder_resource(tapped=index < tapped) for index in range(total)]

    def make_builder_creature(self, owner_id: int, *, aw: int, vw: int, sw: int, lw: int, ready: bool = True, abilities: tuple[Ability, ...] = ()):
        player = self.engine.players[owner_id]
        creature = self.engine.create_builder_creature(
            player,
            aw=aw,
            vw=vw,
            sw=sw,
            lw=lw,
            abilities=frozenset(abilities or (Ability.VIGILANCE,)),
        )
        creature.tapped = not ready
        creature.summoning_sick = not ready
        return creature

    def choose_builder_ability(self, ability: Ability) -> None:
        self.engine.toggle_builder_creature_ability(ability)

    def build_pending_creature(self, ability: Ability) -> None:
        self.choose_builder_ability(ability)
        self.assertTrue(self.engine.confirm_builder_creature_build())

    def combat_result_messages(self) -> list[str]:
        return [
            message
            for message in self.engine.log_messages
            if "rolls" in message and "wins and deals" in message
        ]

    def test_engine_starts_directly_in_builder_mode(self) -> None:
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(len(self.engine.human_player.hand), 0)

    def test_builder_start_state_has_no_ability_system_data(self) -> None:
        self.assertFalse(BUILDER_ABILITIES_ENABLED)
        for player in self.engine.players:
            self.assertEqual(player.life, STARTING_LIFE)
            self.assertEqual(player.total_resources(), 0)
            self.assertEqual(player.available_resources(), 0)
            self.assertEqual(len(player.hand), 0)
            self.assertEqual(player.deck, [])
            self.assertEqual(player.discard_pile, [])
        self.assertEqual(self.engine.builder_shared_deck, [])
        self.assertEqual(self.engine.builder_shared_discard, [])

    def test_resource_and_creature_build_are_mutually_exclusive(self) -> None:
        player = self.engine.human_player
        self.engine.builder_add_resource(player)
        self.assertTrue(player.main_action_used_this_turn)
        self.assertEqual(player.total_resources(), 1)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertFalse(self.engine.begin_builder_creature_build())

    def test_builder_resource_cap_is_10(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 10)
        self.assertFalse(self.engine.can_builder_add_resource(player))
        self.assertFalse(self.engine.builder_add_resource(player))

    def test_creature_build_with_zero_resources_uses_default_free_ability_and_can_confirm(self) -> None:
        player = self.engine.human_player
        self.assertTrue(self.engine.can_builder_open_creature_build(player))
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.assertEqual(len(player.battlefield), 0)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.assertEqual((creature.aw, creature.vw, creature.sw, creature.lw, creature.current_hp), (0, 0, 0, 1, 1))
        self.assertTrue(creature.has_ability(Ability.FLYING))
        self.assertFalse(creature.has_ability(Ability.HASTE))
        self.assertTrue(creature.tapped)
        self.assertTrue(creature.summoning_sick)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertIsNone(self.engine.pending_builder_creature)

    def test_creature_build_distributes_resources_across_stats(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 5)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.engine.adjust_builder_creature_stat("vw", 2)
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.engine.adjust_builder_creature_stat("lw", 1)
        self.choose_builder_ability(Ability.VIGILANCE)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.assertEqual((creature.aw, creature.vw, creature.sw, creature.lw, creature.current_hp), (1, 2, 1, 2, 2))
        self.assertTrue(creature.has_ability(Ability.VIGILANCE))
        self.assertTrue(creature.tapped)
        self.assertEqual(sum(1 for resource in player.resources if resource.tapped), 5)

    def test_builder_preview_creature_is_not_tapped_before_creation(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 3)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.engine.adjust_builder_creature_stat("lw", 1)
        self.choose_builder_ability(Ability.VIGILANCE)
        preview = self.engine.get_builder_preview_creature(player)
        self.assertIsNotNone(preview)
        self.assertFalse(preview.tapped)
        self.assertTrue(preview.summoning_sick)
        self.assertTrue(preview.has_ability(Ability.VIGILANCE))
        self.assertEqual((preview.aw, preview.vw, preview.sw, preview.lw, preview.current_hp), (1, 0, 1, 2, 2))

    def test_builder_creature_cap_is_enforced_per_player(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 10)
        for _ in range(BUILDER_CREATURE_CAP):
            self.assertIsNotNone(self.engine.create_builder_creature(player, aw=1, vw=1, sw=1, lw=2, abilities=frozenset()))
        self.assertEqual(len(player.battlefield), BUILDER_CREATURE_CAP)
        self.assertFalse(self.engine.can_builder_open_creature_build(player))
        self.assertFalse(self.engine.begin_builder_creature_build())
        self.assertIsNone(self.engine.create_builder_creature(player, aw=1, vw=1, sw=1, lw=2, abilities=frozenset()))
        self.assertLess(len(self.engine.ai_player.battlefield), BUILDER_CREATURE_CAP)

    def test_builder_can_create_new_creature_again_after_one_dies(self) -> None:
        player = self.engine.human_player
        for _ in range(BUILDER_CREATURE_CAP):
            creature = self.engine.create_builder_creature(player, aw=1, vw=1, sw=1, lw=1, abilities=frozenset())
            creature.current_hp = 1
        player.battlefield[0].current_hp = 0
        self.engine.cleanup_destroyed_units()
        self.assertEqual(len(player.battlefield), BUILDER_CREATURE_CAP - 1)
        self.assertTrue(self.engine.can_builder_open_creature_build(player))

    def test_new_builder_creature_cannot_block_in_next_enemy_turn_until_own_upkeep(self) -> None:
        player = self.engine.human_player
        created = self.engine.create_builder_creature(player, aw=1, vw=1, sw=2, lw=2, abilities=frozenset())
        attacker = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True)
        self.assertFalse(self.engine.can_creature_block_attacker(created, attacker))

        self.engine.active_player_index = player.player_id
        self.engine.start_turn()
        self.assertFalse(created.tapped)
        self.assertFalse(created.summoning_sick)
        self.assertTrue(self.engine.can_creature_block_attacker(created, attacker))

    def test_new_builder_creature_cannot_attack_same_turn(self) -> None:
        player = self.engine.human_player
        created = self.engine.create_builder_creature(player, aw=1, vw=1, sw=2, lw=2, abilities=frozenset())
        self.engine.active_player_index = player.player_id
        self.assertFalse(created.is_ready())
        self.assertEqual(self.engine.available_attackers(player), [])

    def test_ready_phase_readies_resources_and_creatures(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 3, tapped=3)
        creature = self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=False)
        self.engine.start_turn()
        self.assertEqual(player.available_resources(), 3)
        self.assertFalse(creature.tapped)
        self.assertFalse(creature.summoning_sick)

    def test_attack_does_not_draw_any_builder_card(self) -> None:
        attacker = self.make_builder_creature(0, aw=1, vw=1, sw=2, lw=2, ready=True)
        self.engine.active_player_index = 0
        self.engine.block_assignments = {attacker.unit_id: None}
        start_hand = len(self.engine.human_player.hand)
        self.engine.begin_combat_resolution()
        if self.engine.phase != PHASE_GAME_OVER:
            self.engine.enter_second_main_phase()
        self.assertEqual(len(self.engine.human_player.hand), start_hand)
        self.assertEqual(self.engine.builder_shared_deck, [])

    def test_ability_phase_is_fully_skipped_from_active_builder_flow(self) -> None:
        player = self.engine.human_player
        self.assertTrue(self.engine.builder_add_resource(player))
        self.assertNotIn("ability phase", " ".join(self.engine.log_messages).lower())
        self.assertEqual(self.engine.active_player, self.engine.ai_player)

    def test_turn_ends_automatically_when_no_creature_can_attack(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 1)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.choose_builder_ability(Ability.VIGILANCE)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertIn("No creatures can attack. Combat is skipped and the turn ends.", self.engine.log_messages)

    def test_runtime_rejects_manual_ability_actions(self) -> None:
        self.engine.phase = "Builder ability"
        self.assertFalse(self.engine.begin_builder_ability_use(123))
        self.assertFalse(self.engine.choose_builder_ability_mode("grant_ability"))
        self.assertFalse(self.engine.select_builder_ability_target(1))
        self.assertFalse(self.engine.resolve_builder_ability_use())
        self.assertFalse(self.engine.skip_builder_ability_phase())

    def test_zero_stats_are_safe(self) -> None:
        attacker = self.make_builder_creature(0, aw=0, vw=0, sw=0, lw=1, ready=True)
        blocker = self.make_builder_creature(1, aw=0, vw=0, sw=0, lw=1, ready=True)
        self.engine.active_player_index = 0
        with patch.object(self.engine.rng, "randint", side_effect=[]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        self.assertEqual(self.engine.pending_dice_battle.attack_sum, 0)
        self.assertEqual(self.engine.pending_dice_battle.defense_sum, 0)

    def test_builder_single_duel_logs_complete_result_once_before_cleanup(self) -> None:
        attacker = self.make_builder_creature(0, aw=2, vw=1, sw=1, lw=1, ready=True)
        blocker = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=1, ready=True)
        self.engine.log_messages.clear()

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertEqual(self.combat_result_messages(), [])
        self.engine.end_dice_battle()
        results = self.combat_result_messages()
        self.assertEqual(len(results), 1)
        self.assertIn(f"{attacker.name} rolls [6, 6] = 12, {blocker.name} rolls [1] = 1.", results[0])
        self.assertIn(f"{attacker.name} wins and deals 1 damage to {blocker.name}.", results[0])
        self.assertIn(f"{blocker.name} is destroyed.", results[0])
        self.assertFalse(any("Combat damage destroys" in message for message in self.engine.log_messages))

    def test_builder_single_duel_tie_goes_to_attacker_without_reroll(self) -> None:
        attacker = self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=True)
        blocker = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)

        with patch.object(self.engine.rng, "randint", side_effect=[4, 4]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        battle = self.engine.pending_dice_battle
        self.assertIsNotNone(battle)
        self.assertEqual(battle.attack_sum, 4)
        self.assertEqual(battle.defense_sum, 4)
        self.assertEqual(battle.winner, "attacker")
        self.assertEqual(battle.reroll_count, 0)
        self.assertEqual(len(battle.history), 1)
        self.assertIn("wins", battle.history[0].outcome_text)

    def test_builder_multiple_blocked_combats_log_each_duel_once_in_stable_order(self) -> None:
        attacker_one = self.make_builder_creature(0, aw=2, vw=1, sw=1, lw=2, ready=True)
        attacker_two = self.make_builder_creature(0, aw=2, vw=1, sw=2, lw=2, ready=True)
        blocker_one = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        blocker_two = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=1, ready=True)
        self.engine.block_assignments = {
            attacker_one.unit_id: blocker_one.unit_id,
            attacker_two.unit_id: blocker_two.unit_id,
        }
        self.engine.log_messages.clear()

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1, 5, 5, 1]):
            self.engine.begin_combat_resolution()

        self.assertEqual(self.engine.phase, "Wuerfelkampf")
        self.engine.end_dice_battle()

        results = self.combat_result_messages()
        self.assertEqual(len(results), 2)
        self.assertLess(
            self.engine.log_messages.index(results[0]),
            self.engine.log_messages.index(results[1]),
        )
        self.assertIn(attacker_one.name, results[0])
        self.assertIn(blocker_one.name, results[0])
        self.assertIn(f"{blocker_one.name} remains at 1 life.", results[0])
        self.assertIn(attacker_two.name, results[1])
        self.assertIn(blocker_two.name, results[1])
        self.assertIn(f"{blocker_two.name} is destroyed.", results[1])

    def test_builder_mixed_blocked_and_unblocked_attack_logs_both_paths(self) -> None:
        blocked_attacker = self.make_builder_creature(0, aw=2, vw=1, sw=1, lw=2, ready=True)
        direct_attacker = self.make_builder_creature(0, aw=1, vw=1, sw=2, lw=2, ready=True)
        blocker = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.engine.block_assignments = {
            blocked_attacker.unit_id: blocker.unit_id,
            direct_attacker.unit_id: None,
        }
        self.engine.log_messages.clear()

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1]):
            self.engine.begin_combat_resolution()

        self.engine.end_dice_battle()

        results = self.combat_result_messages()
        self.assertEqual(len(results), 1)
        self.assertIn(blocked_attacker.name, results[0])
        self.assertTrue(
            any(
                message == f"{direct_attacker.name} is unblocked and deals {direct_attacker.sw} damage to {self.engine.ai_player.name}."
                for message in self.engine.log_messages
            )
        )

    def test_builder_combat_logging_has_no_duplicate_destroy_messages(self) -> None:
        attacker_one = self.make_builder_creature(0, aw=2, vw=1, sw=1, lw=2, ready=True)
        attacker_two = self.make_builder_creature(0, aw=2, vw=1, sw=2, lw=2, ready=True)
        blocker_one = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=1, ready=True)
        blocker_two = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=1, ready=True)
        self.engine.block_assignments = {
            attacker_one.unit_id: blocker_one.unit_id,
            attacker_two.unit_id: blocker_two.unit_id,
        }
        self.engine.log_messages.clear()

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1, 5, 5, 1]):
            self.engine.begin_combat_resolution()

        self.engine.end_dice_battle()

        joined = "\n".join(self.engine.log_messages)
        self.assertEqual(joined.count(f"{blocker_one.name} is destroyed."), 1)
        self.assertEqual(joined.count(f"{blocker_two.name} is destroyed."), 1)
        self.assertNotIn(f"Combat damage destroys {blocker_one.name}.", joined)
        self.assertNotIn(f"Combat damage destroys {blocker_two.name}.", joined)

    def test_builder_multiple_blocked_combats_log_complete_result_lines_for_each_duel(self) -> None:
        attacker_one = self.make_builder_creature(0, aw=2, vw=1, sw=1, lw=2, ready=True)
        attacker_two = self.make_builder_creature(0, aw=2, vw=1, sw=1, lw=2, ready=True)
        blocker_one = self.make_builder_creature(1, aw=1, vw=2, sw=1, lw=2, ready=True)
        blocker_two = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)
        self.engine.block_assignments = {
            attacker_one.unit_id: blocker_one.unit_id,
            attacker_two.unit_id: blocker_two.unit_id,
        }
        self.engine.log_messages.clear()

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1, 1, 5, 5, 1]):
            self.engine.begin_combat_resolution()

        self.engine.end_dice_battle()

        results = self.combat_result_messages()
        self.assertEqual(len(results), 2)
        for message in results:
            self.assertIn("rolls [", message)
            self.assertIn(" = ", message)
            self.assertIn("wins and deals", message)
            self.assertTrue("remains at" in message or "is destroyed." in message)

    def test_builder_ui_offers_no_ability_actions(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = 0
        labels = [button.label for button in self.engine.get_button_specs()]
        self.assertNotIn("Grant ability", labels)
        self.assertNotIn("Play card", labels)
        self.assertNotIn("Skip ability", labels)

    def test_builder_main_buttons_use_new_labels(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        self.engine.active_player_index = self.engine.human_player.player_id
        labels = [button.label for button in self.engine.get_button_specs()]
        self.assertEqual(labels, ["Add Resource", "Build Creature"])

    def test_builder_main_phase_label_uses_main(self) -> None:
        self.assertEqual(get_overview_phase_label(PHASE_MAIN_1), "Main Phase")

    def test_builder_creature_stat_buttons_use_requested_order_and_labels(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 4)
        self.assertTrue(self.engine.begin_builder_creature_build())
        labels = [button.label for button in self.engine.get_button_specs()]
        self.assertEqual(
            labels[:8],
            ["+1 Atk", "-1 Atk", "+1 Def", "-1 Def", "+1 Dmg", "-1 Dmg", "+1 HP", "-1 HP"],
        )

    def test_builder_creature_requires_one_primary_and_optionally_paid_haste(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 4)
        self.assertTrue(self.engine.begin_builder_creature_build())
        pending = self.engine.pending_builder_creature
        self.assertIsNotNone(pending)
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.engine.adjust_builder_creature_stat("vw", 1)
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.assertEqual(pending.spent_resources, 3)
        self.assertFalse(self.engine.builder_creature_build_is_valid())
        for ability in BUILDER_PRIMARY_ABILITIES:
            self.choose_builder_ability(ability)
            self.assertEqual(pending.selected_primary_ability, ability)
            self.assertEqual(pending.selected_abilities, frozenset({ability}))
            self.assertEqual(pending.spent_resources, 3)
            self.assertEqual(self.engine.builder_remaining_ready_resources(), 1)
        self.choose_builder_ability(Ability.HASTE)
        self.assertEqual(pending.selected_abilities, frozenset({Ability.TRAMPLE, Ability.HASTE}))
        self.assertEqual(pending.spent_resources, 4)
        self.assertEqual(self.engine.builder_remaining_ready_resources(), 0)
        self.assertTrue(self.engine.builder_creature_build_is_valid())

    def test_haste_toggle_consumes_and_refunds_one_shared_resource(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        pending = self.engine.pending_builder_creature
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.engine.adjust_builder_creature_stat("sw", 1)

        haste_button = next(
            button for button in self.engine.get_button_specs()
            if button.action == "builder_select_ability_haste"
        )
        self.assertFalse(haste_button.enabled)
        self.engine.adjust_builder_creature_stat("aw", -1)
        self.assertTrue(
            next(
                button for button in self.engine.get_button_specs()
                if button.action == "builder_select_ability_haste"
            ).enabled
        )

        self.choose_builder_ability(Ability.HASTE)
        self.assertTrue(pending.has_haste)
        self.assertEqual(pending.stat_cost, 1)
        self.assertEqual(pending.ability_cost, BUILDER_HASTE_COST)
        self.assertEqual(pending.spent_resources, 2)
        self.choose_builder_ability(Ability.HASTE)
        self.assertFalse(pending.has_haste)
        self.assertEqual(pending.spent_resources, 1)

    def test_five_resource_build_uses_four_stats_with_haste_and_free_primary(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 5)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.choose_builder_ability(Ability.TRAMPLE)
        for _ in range(4):
            self.engine.adjust_builder_creature_stat("sw", 1)
        self.choose_builder_ability(Ability.HASTE)

        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.assertEqual((creature.aw, creature.vw, creature.sw, creature.lw), (0, 0, 4, 1))
        self.assertEqual(creature.cost.resources, 5)
        self.assertEqual(creature.abilities, frozenset({Ability.TRAMPLE, Ability.HASTE}))
        counters = self.engine.statistics.player_stats[player.player_id]
        self.assertEqual(counters.builder_trample_creatures_played, 1)
        self.assertEqual(counters.builder_haste_creatures_played, 1)
        self.assertEqual(counters.builder_stat_points_spent, 4)
        self.assertEqual(counters.builder_resources_spent, 5)

    def test_ai_builder_execution_registers_primary_haste_and_cost_split(self) -> None:
        player = self.engine.ai_player
        self.engine.active_player_index = player.player_id
        self.set_builder_resources(player, 3)
        self.engine.pending_ai_action = {
            "kind": "builder_create_creature",
            "plan": {
                "aw": 0,
                "vw": 1,
                "sw": 1,
                "lw": 1,
                "ability": Ability.FLYING,
                "abilities": frozenset({Ability.FLYING, Ability.HASTE}),
                "haste": True,
                "cost": 3,
            },
        }

        self.engine.execute_prepared_ai_action()

        counters = self.engine.statistics.player_stats[player.player_id]
        self.assertEqual(counters.creatures_played, 1)
        self.assertEqual(counters.builder_flying_creatures_played, 1)
        self.assertEqual(counters.builder_haste_creatures_played, 1)
        self.assertEqual(counters.builder_stat_points_spent, 2)
        self.assertEqual(counters.builder_resources_spent, 3)
        self.assertEqual(len(self.engine.statistics.builder_creature_records), 1)

    def test_haste_creature_enters_ready_and_can_attack_same_turn(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.choose_builder_ability(Ability.HASTE)
        preview = self.engine.get_builder_preview_creature(player)
        self.assertIsNotNone(preview)
        self.assertTrue(preview.has_ability(Ability.HASTE))
        self.assertFalse(preview.summoning_sick)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.assertTrue(creature.has_ability(Ability.HASTE))
        self.assertFalse(creature.tapped)
        self.assertFalse(creature.summoning_sick)
        self.assertIn(creature, self.engine.available_attackers(player))

    def test_haste_creature_can_block_next_enemy_turn_if_not_used_to_attack(self) -> None:
        player = self.engine.human_player
        enemy = self.engine.ai_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("vw", 1)
        self.choose_builder_ability(Ability.HASTE)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        attacker = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True)
        self.engine.active_player_index = enemy.player_id
        self.assertTrue(self.engine.can_creature_block_attacker(creature, attacker))
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {attacker.unit_id: creature.unit_id}
        self.engine.finish_block_assignment(ai_assignment_prepared=True)
        self.assertIn(
            f"[COMBAT BLOCKS] turn={self.engine.turn_number} defender=Player_1 "
            f"assignments={creature.name.replace(' ', '_')}>{attacker.name.replace(' ', '_')}",
            self.engine.pending_log_file_lines,
        )

    def test_haste_creature_taps_normally_when_it_attacks(self) -> None:
        player = self.engine.human_player
        enemy = self.engine.ai_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.choose_builder_ability(Ability.HASTE)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.engine.active_player_index = player.player_id
        self.engine.active_player.is_human = True
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id]
        enemy.life = 10
        attack_turn = self.engine.turn_number
        self.engine.confirm_attackers()
        self.assertTrue(creature.tapped)
        self.assertIn(
            f"[COMBAT ATTACKERS] turn={attack_turn} player=Player_1 "
            f"creatures={creature.name.replace(' ', '_')}",
            self.engine.pending_log_file_lines,
        )

    def test_flying_can_only_be_blocked_by_flying(self) -> None:
        flying_attacker = self.make_builder_creature(0, aw=1, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.FLYING,))
        ground_blocker = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True, abilities=(Ability.TRAMPLE,))
        flying_blocker = self.make_builder_creature(1, aw=1, vw=0, sw=1, lw=2, ready=True, abilities=(Ability.FLYING,))

        self.assertFalse(self.engine.can_creature_block_attacker(ground_blocker, flying_attacker))
        self.assertTrue(self.engine.can_creature_block_attacker(flying_blocker, flying_attacker))

    def test_flying_can_block_flying_and_non_flying_attackers(self) -> None:
        flying_blocker = self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, ready=True, abilities=(Ability.FLYING,))
        flying_attacker = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.FLYING,))
        ground_attacker = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.TRAMPLE,))

        self.assertTrue(self.engine.can_creature_block_attacker(flying_blocker, flying_attacker))
        self.assertTrue(self.engine.can_creature_block_attacker(flying_blocker, ground_attacker))

    def test_vigilance_creature_enters_tapped_and_cannot_attack_same_turn(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.choose_builder_ability(Ability.VIGILANCE)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.assertTrue(creature.has_ability(Ability.VIGILANCE))
        self.assertTrue(creature.tapped)
        self.assertTrue(creature.summoning_sick)
        self.assertNotIn(creature, self.engine.available_attackers(player))

    def test_vigilance_does_not_tap_when_attacking(self) -> None:
        player = self.engine.human_player
        enemy = self.engine.ai_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.build_pending_creature(Ability.VIGILANCE)
        creature = player.battlefield[-1]

        self.engine.active_player_index = player.player_id
        self.engine.start_turn()
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [creature.unit_id]
        enemy.life = 10
        self.engine.confirm_attackers()

        self.assertFalse(creature.tapped)

    def test_trample_deals_excess_damage_to_player_on_attacking_win(self) -> None:
        attacker = self.make_builder_creature(0, aw=2, vw=1, sw=5, lw=2, ready=True, abilities=(Ability.TRAMPLE,))
        blocker = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True, abilities=(Ability.VIGILANCE,))
        blocker.current_hp = 2
        self.engine.active_player_index = 0
        self.engine.ai_player.life = 10

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertEqual(self.engine.pending_dice_battle.trample_damage, 3)
        self.assertEqual(self.engine.ai_player.life, 10)
        self.engine.end_dice_battle()
        self.assertEqual(self.engine.ai_player.life, 7)

    def test_trample_does_not_damage_player_on_attacker_loss(self) -> None:
        attacker = self.make_builder_creature(0, aw=1, vw=1, sw=5, lw=2, ready=True, abilities=(Ability.TRAMPLE,))
        blocker = self.make_builder_creature(1, aw=2, vw=1, sw=1, lw=5, ready=True, abilities=(Ability.VIGILANCE,))
        self.engine.active_player_index = 0
        self.engine.ai_player.life = 10

        with patch.object(self.engine.rng, "randint", side_effect=[1, 6, 6]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertEqual(self.engine.pending_dice_battle.trample_damage, 0)
        self.engine.end_dice_battle()
        self.assertEqual(self.engine.ai_player.life, 10)

    def test_trample_does_not_trigger_when_blocking(self) -> None:
        attacker = self.make_builder_creature(1, aw=1, vw=1, sw=2, lw=2, ready=True, abilities=(Ability.VIGILANCE,))
        blocker = self.make_builder_creature(0, aw=2, vw=1, sw=5, lw=2, ready=True, abilities=(Ability.TRAMPLE,))
        self.engine.active_player_index = 1
        self.engine.human_player.life = 10

        with patch.object(self.engine.rng, "randint", side_effect=[1, 6, 6]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertEqual(self.engine.pending_dice_battle.trample_damage, 0)
        self.engine.end_dice_battle()
        self.assertEqual(self.engine.human_player.life, 10)

    def test_dice_battle_button_uses_resolve_combat_label(self) -> None:
        attacker = self.make_builder_creature(0, aw=2, vw=1, sw=2, lw=2, ready=True)
        blocker = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        labels = [button.label for button in self.engine.get_button_specs()]
        self.assertEqual(labels, ["Resolve Combat"])

    def test_creature_damage_is_applied_only_when_resolve_combat_is_pressed(self) -> None:
        attacker = self.make_builder_creature(0, aw=2, vw=1, sw=2, lw=2, ready=True)
        blocker = self.make_builder_creature(1, aw=1, vw=1, sw=1, lw=2, ready=True)

        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)

        self.assertEqual(blocker.current_hp, 2)
        self.assertEqual(attacker.current_hp, 2)
        self.engine.end_dice_battle()
        self.assertEqual(blocker.current_hp, 0)
        self.assertEqual(attacker.current_hp, 2)

    def test_selected_builder_ability_cannot_be_changed_after_creation(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.choose_builder_ability(Ability.FLYING)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.engine.toggle_builder_creature_ability(Ability.HASTE)
        self.assertFalse(creature.has_ability(Ability.HASTE))
        self.assertTrue(creature.has_ability(Ability.FLYING))
        self.assertEqual(creature.builder_ability, Ability.FLYING)

    def test_builder_ui_exposes_three_primary_buttons_and_paid_haste_toggle(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 2)
        self.assertTrue(self.engine.begin_builder_creature_build())
        labels = [button.label for button in self.engine.get_button_specs() if button.action.startswith("builder_select_ability_")]
        self.assertIn(f"Haste ({BUILDER_HASTE_COST})", labels)
        self.assertIn("Flying", labels)
        self.assertIn("Vigilance", labels)
        self.assertIn("Trample", labels)

    def test_old_ability_state_does_not_affect_new_builder_game(self) -> None:
        self.engine.human_player.hand = [object()]
        self.engine.builder_shared_deck = [object()]
        self.engine.builder_shared_discard = [object()]
        self.engine.initialize_builder_game()
        self.assertEqual(self.engine.human_player.hand, [])
        self.assertEqual(self.engine.builder_shared_deck, [])
        self.assertEqual(self.engine.builder_shared_discard, [])

    def test_builder_ai_actions_stay_legal_in_smoke_game(self) -> None:
        self.engine.players = [
            PlayerState(0, "Player", False, summoner_key="builder", life=10),
            PlayerState(1, "Enemy", False, summoner_key="builder", life=10),
        ]
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_MAIN_1
        self.engine.turn_number = 0
        self.engine.reset_combat_state()

        steps = 0
        while self.engine.phase != PHASE_GAME_OVER and steps < 20:
            steps += 1
            if self.engine.phase in {PHASE_MAIN_1, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS}:
                if not self.engine.prepare_ai_turn_action():
                    break
                self.engine.execute_prepared_ai_action()
                continue
            if self.engine.phase == "Wuerfelkampf":
                self.engine.end_dice_battle()
                continue
            break

        self.assertGreaterEqual(steps, 6)
        self.assertTrue(all(len(player.battlefield) <= BUILDER_CREATURE_CAP for player in self.engine.players))
        self.assertTrue(
            all(
                validate_builder_creature_abilities(creature.abilities)
                and creature.builder_ability in BUILDER_PRIMARY_ABILITIES
                for player in self.engine.players
                for creature in player.battlefield
            )
        )
        self.assertTrue(all(len(player.hand) == 0 for player in self.engine.players))

    def test_vanilla_builder_emits_no_provoke_or_ability_prompts_in_smoke_game(self) -> None:
        self.engine.players = [
            PlayerState(0, "Player", False, summoner_key="builder", life=10),
            PlayerState(1, "Enemy", False, summoner_key="builder", life=10),
        ]
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_MAIN_1
        self.engine.turn_number = 0
        self.engine.reset_combat_state()

        steps = 0
        while self.engine.phase != PHASE_GAME_OVER and steps < 20:
            steps += 1
            if self.engine.phase in {PHASE_MAIN_1, PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS}:
                if not self.engine.prepare_ai_turn_action():
                    break
                self.engine.execute_prepared_ai_action()
                continue
            if self.engine.phase == "Wuerfelkampf":
                self.engine.end_dice_battle()
                continue
            break

        joined = "\n".join(self.engine.log_messages)
        self.assertNotIn("Provoke", joined)
        self.assertNotIn("forced blockers", joined)
        self.assertNotIn("ability", joined.lower())


if __name__ == "__main__":
    unittest.main()
