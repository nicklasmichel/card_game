from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import core.config as config
from core.game_logic import GameEngine
from core.models import (
    Ability,
    CardInstance,
    PHASE_BUILDER_ABILITY,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_GAME_OVER,
    PHASE_MAIN_1,
    PlayerState,
    ResourceCard,
)


class BuilderModeTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(config, "GAME_MODE", "builder")
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def make_ability_card(self, ability: Ability) -> CardInstance:
        template = self.engine.templates[f"builder_ability_{ability.name.lower()}"]
        return CardInstance(self.engine.make_instance_id(), template)

    def make_ready_builder_creature(
        self,
        owner_id: int,
        *,
        aw: int,
        vw: int,
        sw: int,
        lw: int,
        abilities: tuple[Ability, ...] = (),
        current_hp: int | None = None,
        tapped: bool = False,
        summoning_sick: bool = False,
    ):
        player = self.engine.players[owner_id]
        creature = self.engine.create_builder_creature(
            player,
            aw=aw,
            vw=vw,
            sw=sw,
            lw=lw,
            abilities=frozenset(abilities),
        )
        creature.tapped = tapped
        creature.summoning_sick = summoning_sick
        if current_hp is not None:
            creature.current_hp = current_hp
        return creature

    def give_human_card(self, ability: Ability) -> CardInstance:
        card = self.make_ability_card(ability)
        self.engine.human_player.hand = [card]
        self.engine.selected_hand_ids.clear()
        return card

    def move_to_ability_phase(self) -> None:
        self.engine.phase = PHASE_BUILDER_ABILITY
        self.engine.builder_ability_used_this_turn = False
        self.engine.pending_builder_ability = None
        self.engine.selected_hand_ids.clear()

    def test_mode_switch_between_deck_and_builder(self) -> None:
        with patch.object(config, "GAME_MODE", "deck"):
            normal_engine = GameEngine()
        self.assertEqual(normal_engine.phase, "Mulligan")
        self.assertEqual(len(normal_engine.human_player.hand), 5)

        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(len(self.engine.human_player.hand), 1)

    def test_builder_start_state_has_10_life_0_resources_and_1_card(self) -> None:
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        for player in self.engine.players:
            self.assertEqual(player.life, 10)
            self.assertEqual(player.total_resources(), 0)
            self.assertEqual(player.available_resources(), 0)
            self.assertEqual(len(player.hand), 1)
            self.assertEqual(player.deck, [])
            self.assertEqual(player.discard_pile, [])
        self.assertEqual(len(self.engine.builder_shared_deck), 26)
        self.assertEqual(len(self.engine.builder_shared_discard), 0)

    def test_resource_and_creature_build_are_mutually_exclusive(self) -> None:
        player = self.engine.human_player
        self.engine.builder_add_resource(player)
        self.assertTrue(player.main_action_used_this_turn)
        self.assertEqual(player.total_resources(), 1)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertFalse(self.engine.begin_builder_creature_build())

    def test_builder_resource_cap_is_10(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 10)
        self.assertFalse(self.engine.can_builder_add_resource(player))
        self.assertFalse(self.engine.builder_add_resource(player))

    def test_creature_build_with_zero_resources_creates_default_creature_immediately(self) -> None:
        player = self.engine.human_player
        self.assertTrue(self.engine.can_builder_open_creature_build(player))
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.assertEqual(len(player.battlefield), 1)
        creature = player.battlefield[0]
        self.assertEqual((creature.aw, creature.vw, creature.sw, creature.lw, creature.current_hp), (0, 0, 0, 1, 1))
        self.assertTrue(creature.summoning_sick)
        self.assertEqual(self.engine.phase, PHASE_BUILDER_ABILITY)
        self.assertIsNone(self.engine.pending_builder_creature)

    def test_creature_build_distributes_resources_across_stats(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 5)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.engine.adjust_builder_creature_stat("vw", 2)
        self.engine.adjust_builder_creature_stat("sw", 1)
        self.engine.adjust_builder_creature_stat("lw", 1)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        creature = player.battlefield[-1]
        self.assertEqual((creature.aw, creature.vw, creature.sw, creature.lw, creature.current_hp), (1, 2, 1, 2, 2))
        self.assertEqual(sum(1 for resource in player.resources if resource.tapped), 5)

    def test_ready_phase_readies_resources_and_creatures(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 3, tapped=3)
        creature = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2, tapped=True, summoning_sick=True)
        self.engine.start_turn()
        self.assertEqual(player.available_resources(), 3)
        self.assertFalse(creature.tapped)
        self.assertFalse(creature.summoning_sick)

    def test_only_one_ability_card_can_be_used_per_turn(self) -> None:
        creature = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2)
        self.give_human_card(Ability.FLYING)
        self.move_to_ability_phase()
        card = self.engine.human_player.hand[0]
        self.assertTrue(self.engine.begin_builder_ability_use(card.instance_id))
        self.assertTrue(self.engine.choose_builder_ability_mode("grant_ability"))
        self.assertTrue(self.engine.select_builder_ability_target(creature.unit_id))
        self.assertTrue(self.engine.resolve_builder_ability_use())
        self.assertTrue(self.engine.builder_ability_used_this_turn)
        second = self.make_ability_card(Ability.TRAMPLE)
        self.engine.human_player.hand.append(second)
        self.assertFalse(self.engine.begin_builder_ability_use(second.instance_id))

    def test_all_three_builder_card_modes_work(self) -> None:
        creature = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2)
        enemy = self.make_ready_builder_creature(1, aw=1, vw=1, sw=1, lw=1)

        grant_card = self.give_human_card(Ability.FLYING)
        self.move_to_ability_phase()
        self.engine.begin_builder_ability_use(grant_card.instance_id)
        self.engine.choose_builder_ability_mode("grant_ability")
        self.engine.select_builder_ability_target(creature.unit_id)
        self.engine.resolve_builder_ability_use()
        self.assertIn(Ability.FLYING, creature.abilities)

        stat_card = self.give_human_card(Ability.TRAMPLE)
        self.move_to_ability_phase()
        self.engine.begin_builder_ability_use(stat_card.instance_id)
        self.engine.choose_builder_ability_mode("add_stat", "sw")
        self.engine.select_builder_ability_target(creature.unit_id)
        self.engine.resolve_builder_ability_use()
        self.assertEqual(creature.sw, 2)

        damage_card = self.give_human_card(Ability.DEATHTOUCH)
        self.move_to_ability_phase()
        self.engine.begin_builder_ability_use(damage_card.instance_id)
        self.engine.choose_builder_ability_mode("deal_damage")
        self.engine.select_builder_ability_target(enemy.unit_id)
        self.engine.resolve_builder_ability_use()
        self.assertNotIn(enemy, self.engine.ai_player.battlefield)

    def test_played_card_is_discarded_and_effect_stays_on_creature(self) -> None:
        creature = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2)
        card = self.give_human_card(Ability.FLYING)
        self.move_to_ability_phase()
        self.engine.begin_builder_ability_use(card.instance_id)
        self.engine.choose_builder_ability_mode("grant_ability")
        self.engine.select_builder_ability_target(creature.unit_id)
        self.engine.resolve_builder_ability_use()
        self.assertEqual(len(self.engine.human_player.hand), 0)
        self.assertEqual(len(self.engine.builder_shared_discard), 1)
        self.assertIn(Ability.FLYING, creature.abilities)

    def test_creature_can_only_have_two_distinct_abilities_but_stat_bonus_is_still_legal(self) -> None:
        creature = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2, abilities=(Ability.FLYING, Ability.TRAMPLE))
        card = self.give_human_card(Ability.VIGILANCE)
        self.move_to_ability_phase()
        self.engine.begin_builder_ability_use(card.instance_id)
        self.engine.choose_builder_ability_mode("grant_ability")
        self.assertFalse(self.engine.select_builder_ability_target(creature.unit_id))

        self.engine.choose_builder_ability_mode("add_stat", "aw")
        self.assertTrue(self.engine.select_builder_ability_target(creature.unit_id))
        self.assertTrue(self.engine.resolve_builder_ability_use())
        self.assertEqual(creature.aw, 2)

    def test_draw_exactly_one_card_after_attack_but_not_without_attack(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=2, lw=2)
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 1
        self.engine.human_player.turns_started = 1
        start_hand = len(self.engine.human_player.hand)
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.begin_combat_resolution()
        if self.engine.phase != PHASE_GAME_OVER:
            self.engine.enter_second_main_phase()
        self.assertEqual(len(self.engine.human_player.hand), start_hand + 1)

        self.engine.active_player_index = 0
        self.engine.attack_declared_this_turn = False
        hand_after = len(self.engine.human_player.hand)
        self.engine.enter_second_main_phase()
        self.assertEqual(len(self.engine.human_player.hand), hand_after)

    def test_draw_happens_even_if_attack_is_blocked_and_attacker_dies(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=1)
        blocker = self.make_ready_builder_creature(1, aw=2, vw=1, sw=2, lw=2)
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 1
        self.engine.human_player.turns_started = 1
        self.engine.block_assignments = {attacker.unit_id: blocker.unit_id}
        start_hand = len(self.engine.human_player.hand)
        with patch.object(self.engine.rng, "randint", side_effect=[1, 6, 6]):
            self.engine.begin_combat_resolution()
            self.engine.end_dice_battle()
        if self.engine.phase != PHASE_GAME_OVER:
            self.engine.enter_second_main_phase()
        self.assertEqual(len(self.engine.human_player.hand), start_hand + 1)

    def test_starting_player_does_not_draw_ability_card_in_first_turn(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=1)
        self.engine.active_player_index = 0
        self.engine.starting_player_id = 0
        self.engine.human_player.turns_started = 1
        self.engine.block_assignments = {attacker.unit_id: None}
        start_hand = len(self.engine.human_player.hand)
        self.engine.begin_combat_resolution()
        if self.engine.phase != PHASE_GAME_OVER:
            self.engine.enter_second_main_phase()
        self.assertEqual(len(self.engine.human_player.hand), start_hand)

    def test_ability_phase_is_auto_skipped_without_any_creatures(self) -> None:
        player = self.engine.human_player
        self.assertTrue(self.engine.builder_add_resource(player))
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertIn("No creatures are in play. The ability phase is skipped.", self.engine.log_messages)

    def test_turn_ends_automatically_when_no_creature_can_attack(self) -> None:
        player = self.engine.human_player
        self.set_builder_resources(player, 1)
        self.assertTrue(self.engine.begin_builder_creature_build())
        self.engine.adjust_builder_creature_stat("aw", 1)
        self.assertTrue(self.engine.confirm_builder_creature_build())
        self.assertEqual(self.engine.phase, PHASE_BUILDER_ABILITY)
        self.assertTrue(self.engine.skip_builder_ability_phase())
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)
        self.assertEqual(self.engine.active_player, self.engine.ai_player)
        self.assertIn("No creatures can attack. Combat is skipped and the turn ends.", self.engine.log_messages)

    def test_shared_discard_is_reshuffled_when_deck_is_empty(self) -> None:
        player = self.engine.human_player
        self.engine.builder_shared_deck = []
        self.engine.builder_shared_discard = [self.make_ability_card(Ability.HASTE)]
        drawn = self.engine.builder_draw_ability_card(player, "Test")
        self.assertIsNotNone(drawn)
        self.assertEqual(len(player.hand), 2)
        self.assertEqual(len(self.engine.builder_shared_deck), 0)
        self.assertEqual(len(self.engine.builder_shared_discard), 0)

    def test_deathtouch_destroys_without_changing_trample_math(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=2, vw=1, sw=3, lw=3, abilities=(Ability.DEATHTOUCH, Ability.TRAMPLE))
        blocker = self.make_ready_builder_creature(1, aw=1, vw=1, sw=1, lw=5, current_hp=5)
        self.engine.active_player_index = 0
        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        self.assertEqual(self.engine.pending_dice_battle.trample_damage, 0)
        self.assertLessEqual(blocker.current_hp, 0)

    def test_flying_can_only_be_blocked_by_flying_unless_provoked(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2, abilities=(Ability.FLYING,))
        ground_blocker = self.make_ready_builder_creature(1, aw=1, vw=1, sw=1, lw=2)
        self.assertFalse(self.engine.can_creature_block_attacker(ground_blocker, attacker))

        provoking_attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2, abilities=(Ability.FLYING, Ability.PROVOKE))
        self.engine.block_assignments = {provoking_attacker.unit_id: None}
        self.assertTrue(self.engine.set_enraged_block_assignment(provoking_attacker.unit_id, ground_blocker.unit_id))

    def test_haste_can_only_be_granted_on_creation_turn(self) -> None:
        old_creature = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2)
        new_creature = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2, summoning_sick=True)
        self.engine.builder_created_this_turn_ids = {new_creature.unit_id}
        card = self.give_human_card(Ability.HASTE)
        self.move_to_ability_phase()
        self.engine.begin_builder_ability_use(card.instance_id)
        self.engine.choose_builder_ability_mode("grant_ability")
        self.assertFalse(self.engine.select_builder_ability_target(old_creature.unit_id))
        self.assertTrue(self.engine.select_builder_ability_target(new_creature.unit_id))

    def test_lifelink_heals_self_and_caps_at_max_life(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=4, lw=5, abilities=(Ability.LIFELINK,), current_hp=2)
        self.engine.active_player_index = 0
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.begin_combat_resolution()
        self.assertEqual(attacker.current_hp, 5)

    def test_trample_uses_remaining_blocker_life(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=2, vw=1, sw=6, lw=3, abilities=(Ability.TRAMPLE,))
        blocker = self.make_ready_builder_creature(1, aw=1, vw=1, sw=1, lw=4, current_hp=2)
        self.engine.active_player_index = 0
        with patch.object(self.engine.rng, "randint", side_effect=[6, 6, 1]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        self.assertEqual(self.engine.pending_dice_battle.trample_damage, 4)

    def test_vigilance_keeps_attacker_ready(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=2, lw=2, abilities=(Ability.VIGILANCE,))
        self.engine.active_player_index = 0
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.begin_combat_resolution()
        self.assertFalse(attacker.tapped)

    def test_provoke_can_force_tapped_or_ground_blockers(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=1, vw=1, sw=2, lw=2, abilities=(Ability.FLYING, Ability.PROVOKE))
        tapped_ground = self.make_ready_builder_creature(1, aw=0, vw=0, sw=1, lw=1, tapped=True)
        self.engine.block_assignments = {attacker.unit_id: None}
        self.assertTrue(self.engine.set_enraged_block_assignment(attacker.unit_id, tapped_ground.unit_id))

    def test_single_blocking_is_enforced(self) -> None:
        attacker_one = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2)
        attacker_two = self.make_ready_builder_creature(0, aw=1, vw=1, sw=1, lw=2)
        blocker = self.make_ready_builder_creature(1, aw=1, vw=1, sw=1, lw=2)
        self.engine.ai_player.is_human = True
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {attacker_one.unit_id: None, attacker_two.unit_id: None}
        self.engine.toggle_blocker_assignment(blocker.unit_id)
        self.engine.toggle_selected_attack_target(attacker_one.unit_id)
        self.engine.toggle_blocker_assignment(blocker.unit_id)
        self.engine.toggle_selected_attack_target(attacker_two.unit_id)
        self.assertEqual(self.engine.block_assignments[attacker_one.unit_id], blocker.unit_id)
        self.assertIsNone(self.engine.block_assignments[attacker_two.unit_id])

    def test_zero_stats_are_safe(self) -> None:
        attacker = self.make_ready_builder_creature(0, aw=0, vw=0, sw=0, lw=1)
        blocker = self.make_ready_builder_creature(1, aw=0, vw=0, sw=0, lw=1)
        self.engine.active_player_index = 0
        with patch.object(self.engine.rng, "randint", side_effect=[]):
            self.engine.start_dice_battle(attacker.unit_id, blocker.unit_id)
        self.assertEqual(self.engine.pending_dice_battle.attack_sum, 0)
        self.assertEqual(self.engine.pending_dice_battle.defense_sum, 0)

    def test_builder_ai_actions_stay_legal_in_smoke_game(self) -> None:
        self.engine.players = [
            PlayerState(0, "Player", False, summoner_key="builder", life=10),
            PlayerState(1, "Enemy", False, summoner_key="builder", life=10),
        ]
        self.engine.builder_shared_deck = self.engine.builder_shared_deck or [self.make_ability_card(Ability.FLYING)]
        self.engine.builder_shared_discard = []
        self.engine.human_player.hand = [self.make_ability_card(Ability.FLYING)]
        self.engine.ai_player.hand = [self.make_ability_card(Ability.TRAMPLE)]
        self.engine.active_player_index = 0
        self.engine.phase = PHASE_MAIN_1
        self.engine.turn_number = 0
        self.engine.reset_combat_state()

        steps = 0
        while self.engine.phase != PHASE_GAME_OVER and steps < 60:
            steps += 1
            if self.engine.phase in {PHASE_MAIN_1, PHASE_BUILDER_ABILITY, "Angreifer waehlen", "Blocker waehlen"}:
                if not self.engine.prepare_ai_turn_action():
                    break
                self.engine.execute_prepared_ai_action()
                continue
            if self.engine.phase == "Wuerfelkampf":
                self.engine.end_dice_battle()
                continue
            break

        self.assertGreaterEqual(steps, 8)
        for attacker_id, blocker_id in self.engine.block_assignments.items():
            if blocker_id is None:
                continue
            blocker = self.engine.get_unit_by_id(blocker_id)
            attacker = self.engine.get_unit_by_id(attacker_id)
            self.assertIsNotNone(blocker)
            self.assertIsNotNone(attacker)
            self.assertTrue(
                self.engine.can_creature_block_attacker(blocker, attacker)
                or attacker.has_ability(Ability.PROVOKE)
            )
        self.assertTrue(all(math.isfinite(player.life) for player in self.engine.players))

    def test_builder_ai_can_enter_attack_declaration_from_ability_phase(self) -> None:
        self.engine.players = [
            PlayerState(0, "Player", False, summoner_key="builder", life=10),
            PlayerState(1, "Enemy", False, summoner_key="builder", life=10),
        ]
        self.engine.active_player_index = 1
        self.engine.phase = PHASE_BUILDER_ABILITY
        self.engine.builder_ability_used_this_turn = True
        attacker = self.make_ready_builder_creature(1, aw=1, vw=1, sw=2, lw=2, summoning_sick=False)
        attacker.tapped = False
        self.assertEqual(self.engine.phase, PHASE_BUILDER_ABILITY)
        self.assertTrue(self.engine.prepare_ai_turn_action())
        self.assertIsNotNone(self.engine.pending_ai_action)
        self.assertEqual(self.engine.pending_ai_action["kind"], "to_combat")
        self.engine.execute_prepared_ai_action()
        self.assertEqual(self.engine.phase, PHASE_DECLARE_ATTACKERS)


if __name__ == "__main__":
    unittest.main()
