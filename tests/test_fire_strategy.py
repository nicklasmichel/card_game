from __future__ import annotations

from core.ai.strategies.fire import (
    FIRE_MODE_CONTROL,
    FIRE_MODE_DEPLOY_THREAT,
    FIRE_MODE_LETHAL,
    FIRE_MODE_RAMP,
    FIRE_MODE_REFUEL,
    FIRE_MODE_STABILIZE,
    FireStrategy,
)
from core.models import CardInstance, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1, PHASE_MAIN_2, PlayerState
from tests.helpers import EngineTestCase


class FireStrategyTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.ai_player.summoner_key = "fire"
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.phase = PHASE_MAIN_1

    def test_fire_strategy_is_loaded_from_registry(self) -> None:
        strategy = self.engine.ai.strategy_registry.resolve("fire")
        self.assertIsInstance(strategy, FireStrategy)

    def test_fire_passive_draws_extra_card_below_ten_life(self) -> None:
        self.engine.ai_player.life = 9
        self.engine.ai_player.turns_started = 1
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenbestie"]),
        ]

        self.engine.start_turn()

        self.assertEqual(len(self.engine.ai_player.hand), 2)
        self.assertTrue(self.engine.ai_player.summoner_passive_draw_used_this_turn)
        self.assertIn("Gegner zieht 1 zusaetzliche Karte durch den Beschwoerer.", self.engine.log_messages)

    def test_fire_passive_does_not_draw_at_ten_life(self) -> None:
        self.engine.ai_player.life = 10
        self.engine.ai_player.turns_started = 1
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenbestie"]),
        ]

        self.engine.start_turn()

        self.assertEqual(len(self.engine.ai_player.hand), 1)
        self.assertFalse(self.engine.ai_player.summoner_passive_draw_used_this_turn)

    def test_air_passive_still_triggers_on_three_attackers(self) -> None:
        self.engine.players = [
            PlayerState(0, "Spieler", True),
            PlayerState(1, "Gegner", False),
        ]
        self.engine.human_player.summoner_key = "air"
        self.engine.active_player_index = 0
        self.engine.human_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_glutbestie"]),
        ]
        attacker_one = self.make_creature("air_creature_wolkenschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_wolkengeist", owner_id=0)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_fire_strategy_detects_lethal_mode(self) -> None:
        self.make_creature("fire_creature_flammenbrecher", owner_id=1, ready=True)
        self.engine.human_player.life = 6
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_verbrennen"]),
        ]
        decision = self.engine.ai._evaluate_fire_strategy(
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=2,
            total_resources=2,
            phase=PHASE_MAIN_1,
        )
        self.assertEqual(decision.mode, FIRE_MODE_LETHAL)

    def test_fire_strategy_detects_stabilize_mode(self) -> None:
        self.engine.ai_player.life = 4
        threat = self.make_creature("air_creature_himmelsschwinge", owner_id=0, ready=True)
        threat.aw = 5
        decision = self.engine.ai._evaluate_fire_strategy(
            self.engine.ai_player,
            self.engine,
            hand=[],
            available_resources=2,
            total_resources=2,
            phase=PHASE_MAIN_1,
        )
        self.assertEqual(decision.mode, FIRE_MODE_STABILIZE)

    def test_fire_strategy_detects_ramp_mode(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_holzvorrat"]),
        ]
        decision = self.engine.ai._evaluate_fire_strategy(
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=1,
            total_resources=1,
            phase=PHASE_MAIN_1,
        )
        self.assertEqual(decision.mode, FIRE_MODE_RAMP)

    def test_fire_strategy_detects_deploy_threat_mode(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenbestie"]),
        ]
        decision = self.engine.ai._evaluate_fire_strategy(
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=4,
            total_resources=4,
            phase=PHASE_MAIN_1,
        )
        self.assertEqual(decision.mode, FIRE_MODE_DEPLOY_THREAT)

    def test_fire_strategy_detects_refuel_mode(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_glutvision"]),
        ]
        decision = self.engine.ai._evaluate_fire_strategy(
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=2,
            total_resources=2,
            phase=PHASE_MAIN_1,
        )
        self.assertEqual(decision.mode, FIRE_MODE_REFUEL)

    def test_fire_strategy_defaults_to_control(self) -> None:
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_versengen"]),
        ]
        self.make_creature("air_creature_wolkengeist", owner_id=0, ready=True)
        decision = self.engine.ai._evaluate_fire_strategy(
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=1,
            total_resources=1,
            phase=PHASE_MAIN_1,
        )
        self.assertEqual(decision.mode, FIRE_MODE_CONTROL)

    def test_fire_ai_prefers_smallest_sufficient_burn_spell(self) -> None:
        self.engine.phase = PHASE_MAIN_2
        self.engine.ai_player.resources_played_this_turn = 2
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_glutbestie"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinkobold"),
        ]
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_verbrennen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_verkohlen"]),
        ]
        self.make_creature("air_creature_windgeist", owner_id=0, ready=True)

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], self.engine.ai_player.hand[0].instance_id)

    def test_fire_ai_prioritizes_removal_over_ramp_when_under_pressure(self) -> None:
        self.engine.phase = PHASE_MAIN_2
        self.engine.ai_player.life = 3
        self.engine.ai_player.resources_played_this_turn = 2
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_glutbestie"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_kohlevorrat"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_verbrennen"]),
        ]
        flyer = self.make_creature("air_creature_windgeist", owner_id=0, ready=True)
        flyer.aw = 4

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], self.engine.ai_player.hand[1].instance_id)
