from __future__ import annotations

import unittest
from unittest.mock import patch

from game_logic import GameEngine
from models import (
    BattlefieldCreature,
    CardInstance,
    CombatUnitSnapshot,
    DieResult,
    PHASE_FORCED_DISCARD,
    PHASE_RESOURCE,
    PHASE_RECYCLE_PAYMENT,
    PHASE_SUMMONING,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PendingComparison,
    PendingDiceBattle,
    PlayerState,
    ResourceCard,
)


class ElementalCombatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine()
        self.engine.players = [
            PlayerState(0, "Spieler", True),
            PlayerState(1, "Gegner", False),
        ]
        self.engine.active_player_index = 0
        self.engine.reset_combat_state()
        self.engine.log_messages.clear()

    def make_creature(self, template_id: str, owner_id: int, ready: bool = True) -> BattlefieldCreature:
        template = self.engine.templates[template_id]
        creature = BattlefieldCreature.from_card(CardInstance(self.engine.make_instance_id(), template))
        if ready:
            creature.tapped = False
            creature.summoning_sick = False
        self.engine.players[owner_id].battlefield.append(creature)
        return creature

    def snapshot(self, creature: BattlefieldCreature) -> CombatUnitSnapshot:
        return CombatUnitSnapshot(
            unit_id=creature.unit_id,
            template_id=getattr(creature, "template_id", None),
            name=creature.name,
            cost=creature.cost,
            aw=creature.aw,
            vw=creature.vw,
            current_hp=creature.current_hp,
            element=creature.element,
            abilities=creature.abilities,
            rules_text=getattr(creature, "rules_text", ""),
            tapped=creature.tapped,
        )

    def test_defender_can_block_two_attackers_in_same_combat_phase(self) -> None:
        attacker_one = self.make_creature("fire_funkenkobold", owner_id=1)
        attacker_two = self.make_creature("fire_flammenrekrut", owner_id=1)
        defender = self.make_creature("earth_schildwache", owner_id=0)

        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {
            attacker_one.unit_id: [],
            attacker_two.unit_id: [],
        }

        self.engine.selected_attack_target_id = attacker_one.unit_id
        self.engine.toggle_blocker_assignment(defender.unit_id)
        self.engine.selected_attack_target_id = attacker_two.unit_id
        self.engine.toggle_blocker_assignment(defender.unit_id)

        self.assertEqual(self.engine.block_assignments[attacker_one.unit_id], [defender.unit_id])
        self.assertEqual(self.engine.block_assignments[attacker_two.unit_id], [defender.unit_id])
        self.assertEqual(
            self.engine.blocker_to_attackers[defender.unit_id],
            [attacker_one.unit_id, attacker_two.unit_id],
        )

    def test_human_adaptation_creates_choice_and_can_reroll_comparison(self) -> None:
        attacker = self.make_creature("fire_lavakrieger", owner_id=1)
        blocker = self.make_creature("water_wellenformer", owner_id=0)
        attacker.current_hp = attacker.vw
        blocker.current_hp = blocker.vw

        self.engine.active_player_index = 1
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=1,
            blocker_owner=0,
            attacker_dice=[DieResult(10, attacker.aw)],
            blocker_dice=[DieResult(1, blocker.aw)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.choose_human_die(0)

        self.assertIsNotNone(self.engine.pending_dice_battle)
        self.assertIsNotNone(battle.pending_comparison)
        self.assertTrue(battle.pending_comparison.human_can_adapt)
        self.assertEqual(len(battle.history), 0)

        with patch.object(self.engine.rng, "randint", return_value=20):
            self.engine.resolve_pending_comparison(use_human_adaptation=True)

        self.assertTrue(battle.blocker_used_adaptation)
        self.assertEqual(len(battle.history), 1)
        self.assertLess(attacker.current_hp, attacker.vw)
        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertTrue(battle.resolution_complete)

    def test_trample_deals_player_damage_from_remaining_attack_dice_after_last_blocker(self) -> None:
        attacker = self.make_creature("fire_magmabestie", owner_id=0)
        blocker = self.make_creature("earth_felsensoldat", owner_id=1)
        blocker.current_hp = 0

        self.engine.active_player_index = 0
        self.engine.defending_player.life = 20
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[
                DieResult(18, attacker.aw, used=True),
                DieResult(17, attacker.aw, used=True),
                DieResult(16, attacker.aw, used=False),
                DieResult(15, attacker.aw, used=False),
                DieResult(14, attacker.aw, used=False),
            ],
            blocker_dice=[
                DieResult(5, blocker.aw, used=True),
                DieResult(4, blocker.aw, used=True),
                DieResult(3, blocker.aw, used=True),
            ],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.finalize_or_continue_dice_battle(battle, attacker, blocker)

        self.assertEqual(self.engine.ai_player.life, 17)
        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertTrue(battle.resolution_complete)

    def test_dice_battle_must_be_closed_manually_after_resolution(self) -> None:
        attacker = self.make_creature("fire_lavakrieger", owner_id=0)
        blocker = self.make_creature("earth_felsensoldat", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        self.engine.block_assignments = {attacker.unit_id: [blocker.unit_id]}
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=True)],
            blocker_dice=[DieResult(1, blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.finalize_or_continue_dice_battle(battle, attacker, blocker)

        self.assertTrue(battle.resolution_complete)
        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertIn("Kampf abschließen", [spec.label for spec in self.engine.get_button_specs()])

        self.engine.end_dice_battle()

        self.assertIsNone(self.engine.pending_dice_battle)

    def test_dice_battle_button_shows_next_combat_when_another_battle_remains(self) -> None:
        attacker_one = self.make_creature("fire_lavakrieger", owner_id=0)
        blocker_one = self.make_creature("earth_felsensoldat", owner_id=1)
        attacker_two = self.make_creature("fire_funkenkobold", owner_id=0)
        blocker_two = self.make_creature("earth_schildwache", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        self.engine.combat_queue = [attacker_one.unit_id, attacker_two.unit_id]
        self.engine.current_attack_index = 0
        self.engine.current_blocker_order = [blocker_one.unit_id]
        self.engine.current_blocker_index = 1
        self.engine.block_assignments = {
            attacker_one.unit_id: [blocker_one.unit_id],
            attacker_two.unit_id: [blocker_two.unit_id],
        }
        battle = PendingDiceBattle(
            attacker_id=attacker_one.unit_id,
            blocker_id=blocker_one.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker_one.aw, used=True)],
            blocker_dice=[DieResult(1, blocker_one.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker_one),
            blocker_snapshot=self.snapshot(blocker_one),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.finalize_or_continue_dice_battle(battle, attacker_one, blocker_one)

        self.assertTrue(battle.resolution_complete)
        self.assertIn("Nächster Kampf", [spec.label for spec in self.engine.get_button_specs()])

    def test_dice_battle_cannot_be_closed_early(self) -> None:
        attacker = self.make_creature("fire_lavakrieger", owner_id=0)
        blocker = self.make_creature("earth_felsensoldat", owner_id=1)

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=False)],
            blocker_dice=[DieResult(1, blocker.aw, used=False)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        self.engine.end_dice_battle()

        self.assertIs(self.engine.pending_dice_battle, battle)
        self.assertEqual(self.engine.log_messages, [])

    def test_battle_snapshot_keeps_last_hp_after_creature_removal(self) -> None:
        attacker = self.make_creature("fire_lavakrieger", owner_id=0)
        blocker = self.make_creature("earth_felsensoldat", owner_id=1)
        blocker.current_hp = 1

        self.engine.active_player_index = 0
        self.engine.phase = PHASE_DICE_BATTLE
        battle = PendingDiceBattle(
            attacker_id=attacker.unit_id,
            blocker_id=blocker.unit_id,
            attacker_owner=0,
            blocker_owner=1,
            attacker_dice=[DieResult(20, attacker.aw, used=True)],
            blocker_dice=[DieResult(1, blocker.aw, used=True)],
            attacker_snapshot=self.snapshot(attacker),
            blocker_snapshot=self.snapshot(blocker),
            ai_strategy_name="Test",
            ai_choose_die=lambda dice: dice[0],
        )
        self.engine.pending_dice_battle = battle

        comparison = PendingComparison(
            attacker_die=DieResult(20, attacker.aw, used=True),
            blocker_die=DieResult(1, blocker.aw, used=True),
            human_is_attacker=True,
        )
        self.engine.apply_comparison_result(battle, comparison)

        self.assertIsNone(self.engine.get_unit_by_id(blocker.unit_id))
        self.assertEqual(battle.blocker_snapshot.current_hp, 0)

    def test_mixed_cost_can_recycle_one_of_the_tapped_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_brandstifter"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
            self.make_resource("earth_steinkobold"),
        ]
        self.engine.phase = PHASE_SUMMONING

        started = self.engine.begin_recycle_payment(card.instance_id)

        self.assertTrue(started)
        self.assertEqual(self.engine.phase, PHASE_RECYCLE_PAYMENT)
        selected_resource_id = self.engine.human_player.resources[0].resource_id
        self.engine.toggle_recycle_resource_selection(selected_resource_id)
        self.engine.confirm_recycle_payment()

        self.assertEqual(self.engine.phase, PHASE_RESOURCE)
        self.assertEqual(self.engine.active_player.player_id, 1)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)
        self.assertEqual(len(self.engine.human_player.resources), 2)
        self.assertEqual(sum(1 for resource in self.engine.human_player.resources if resource.tapped), 1)
        self.assertEqual(len(self.engine.human_player.deck), 1)
        self.assertTrue(self.engine.human_player.deck[0].was_recycled)
        self.assertEqual(self.engine.statistics.player_stats[0].recycled_resources, 1)
        self.assertEqual(self.engine.statistics.player_stats[0].recycled_cards_played, 1)
        self.assertEqual(self.engine.statistics.player_stats[0].max_recycle_paid_once, 1)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "recycle_reveal")

    def test_recycle_play_requires_enough_total_resources(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_lavakrieger"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
        ]
        self.engine.phase = PHASE_SUMMONING

        started = self.engine.begin_recycle_payment(card.instance_id)

        self.assertFalse(started)
        self.assertEqual(self.engine.phase, PHASE_SUMMONING)

    def test_self_damage_creature_hurts_controller_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_bombenwicht"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [self.make_resource("fire_funkenkobold")]
        self.engine.human_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.human_player.life, 18)
        self.assertEqual(len(self.engine.human_player.battlefield), 1)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "player_damage")
        self.assertEqual(self.engine.pending_visual_events[-1]["target_player_id"], self.engine.human_player.player_id)

    def test_cannot_block_creature_is_excluded_from_available_blockers(self) -> None:
        defender = self.make_creature("fire_funkenwicht", owner_id=0)

        blockers = self.engine.available_blockers(self.engine.human_player)

        self.assertNotIn(defender, blockers)

    def test_flammenrekrut_deals_one_damage_to_opponent_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_flammenrekrut"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
            self.make_resource("earth_steinkobold"),
        ]
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.ai_player.life, 19)
        self.assertEqual(self.engine.pending_visual_events[-1]["type"], "player_damage")
        self.assertEqual(self.engine.pending_visual_events[-1]["target_player_id"], self.engine.ai_player.player_id)

    def test_lavakrieger_deals_three_damage_to_both_players_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_lavakrieger"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
            self.make_resource("earth_steinkobold"),
            self.make_resource("air_windgeist"),
        ]
        self.engine.human_player.life = 20
        self.engine.ai_player.life = 20
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.human_player.life, 17)
        self.assertEqual(self.engine.ai_player.life, 17)
        self.assertEqual(len(self.engine.pending_visual_events), 2)
        self.assertTrue(all(event["type"] == "player_damage" for event in self.engine.pending_visual_events[-2:]))

    def test_windgeist_forces_human_discard_selection_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_windgeist"])
        spare = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_funkenkobold"])
        self.engine.human_player.hand = [card, spare]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
        ]
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(self.engine.phase, PHASE_FORCED_DISCARD)
        self.assertIsNotNone(self.engine.pending_forced_discard)
        self.assertEqual(self.engine.pending_forced_discard.required_count, 1)

    def test_sturmfalke_forces_ai_to_discard_one_card_on_play(self) -> None:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates["air_sturmfalke"])
        self.engine.human_player.hand = [card]
        self.engine.human_player.resources = [
            self.make_resource("fire_funkenkobold"),
            self.make_resource("water_wassertropfen"),
            self.make_resource("earth_steinkobold"),
            self.make_resource("air_windgeist"),
        ]
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_funkenkobold"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["water_wassertropfen"]),
        ]
        self.engine.phase = PHASE_SUMMONING

        played = self.engine.resolve_creature_play(card)

        self.assertTrue(played)
        self.assertEqual(len(self.engine.ai_player.hand), 1)
        self.assertEqual(len(self.engine.ai_player.discard_pile), 1)

    def test_windhuscher_returns_to_deck_at_end_of_turn(self) -> None:
        creature = self.make_creature("air_windhuscher", owner_id=0)
        self.engine.human_player.deck = []

        self.engine.resolve_end_of_turn_returns(self.engine.human_player)

        self.assertEqual(len(self.engine.human_player.battlefield), 0)
        self.assertEqual(len(self.engine.human_player.deck), 1)
        self.assertEqual(self.engine.human_player.deck[0].template.template_id, "air_windhuscher")

    def test_human_can_play_two_resources_in_resource_phase(self) -> None:
        first = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_funkenkobold"])
        second = CardInstance(self.engine.make_instance_id(), self.engine.templates["water_wassertropfen"])
        third = CardInstance(self.engine.make_instance_id(), self.engine.templates["earth_steinkobold"])
        self.engine.human_player.hand = [first, second, third]
        self.engine.phase = PHASE_RESOURCE

        self.engine.play_hand_card_as_resource(first.instance_id)
        self.assertEqual(self.engine.phase, PHASE_RESOURCE)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 1)
        self.assertEqual(len(self.engine.human_player.resources), 1)

        self.engine.play_hand_card_as_resource(second.instance_id)
        self.assertEqual(self.engine.phase, PHASE_SUMMONING)
        self.assertEqual(self.engine.human_player.resources_played_this_turn, 2)
        self.assertEqual(len(self.engine.human_player.resources), 2)

        self.engine.phase = PHASE_RESOURCE
        self.engine.play_hand_card_as_resource(third.instance_id)
        self.assertEqual(len(self.engine.human_player.resources), 2)

    def test_summoner_can_tap_to_draw_once_per_turn(self) -> None:
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_funkenkobold"])
        ]
        self.engine.human_player.hand = []
        self.engine.human_player.summoner_tapped = False
        self.engine.phase = PHASE_RESOURCE

        activated = self.engine.activate_summoner_draw(self.engine.human_player)

        self.assertTrue(activated)
        self.assertTrue(self.engine.human_player.summoner_tapped)
        self.assertEqual(len(self.engine.human_player.hand), 1)

        second_activation = self.engine.activate_summoner_draw(self.engine.human_player)

        self.assertFalse(second_activation)
        self.assertEqual(len(self.engine.human_player.hand), 1)

    def make_resource(self, template_id: str) -> ResourceCard:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        return ResourceCard(template=card.template, resource_id=card.instance_id)


if __name__ == "__main__":
    unittest.main()
