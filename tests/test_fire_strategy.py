from __future__ import annotations

from core.ai.fire.effects import evaluate_fire_board_wipe
from core.ai.fire.planning import build_fire_turn_plan_payload
from core.ai.strategies.fire import (
    FIRE_MODE_CONTROL,
    FIRE_MODE_DEPLOY_THREAT,
    FIRE_MODE_LETHAL,
    FIRE_MODE_RAMP,
    FIRE_MODE_REFUEL,
    FIRE_MODE_STABILIZE,
    FireStrategy,
)
from core.models import Ability, CardInstance, PHASE_DECLARE_ATTACKERS, PHASE_MAIN_1, PHASE_MAIN_2, PHASE_REACTION, PlayerState, ReactionContext, ReactionTrigger
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

    def test_fire_passive_draws_extra_card_below_five_life(self) -> None:
        self.engine.ai_player.life = 4
        self.engine.ai_player.turns_started = 1
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenhetzer"]),
        ]

        self.engine.start_turn()

        self.assertEqual(len(self.engine.ai_player.hand), 2)
        self.assertTrue(self.engine.ai_player.summoner_passive_draw_used_this_turn)
        self.assertIn("Gegner zieht 1 zusaetzliche Karte durch den Beschwoerer.", self.engine.log_messages)

    def test_fire_passive_does_not_draw_at_five_life(self) -> None:
        self.engine.ai_player.life = 5
        self.engine.ai_player.turns_started = 1
        self.engine.ai_player.deck = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenhetzer"]),
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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_gluthetzer"]),
        ]
        attacker_one = self.make_creature("air_creature_windschwinge", owner_id=0)
        attacker_two = self.make_creature("air_creature_windgeist", owner_id=0)
        attacker_three = self.make_creature("air_creature_windgeist", owner_id=0)
        self.engine.phase = PHASE_DECLARE_ATTACKERS
        self.engine.selected_attackers = [attacker_one.unit_id, attacker_two.unit_id, attacker_three.unit_id]

        self.engine.confirm_attackers()

        self.assertEqual(len(self.engine.human_player.hand), 1)
        self.assertTrue(self.engine.human_player.summoner_passive_draw_used_this_turn)

    def test_fire_strategy_detects_lethal_mode(self) -> None:
        self.make_creature("fire_creature_flammenbrecher", owner_id=1, ready=True)
        self.engine.human_player.life = 2
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
        threat = self.make_creature("air_creature_orkanschwinge", owner_id=0, ready=True)
        threat.sw = 4
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
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_creature_flammenhetzer"]),
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
        self.make_creature("air_creature_windgeist", owner_id=0, ready=True)
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
        self.engine.phase = PHASE_REACTION
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
            self.make_resource("earth_creature_steinwesen"),
        ]
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_verbrennen"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_verkohlen"]),
        ]
        target = self.make_creature("air_creature_windgeist", owner_id=0, ready=True)
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_START,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
                attacker_creature=target,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_2,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], self.engine.ai_player.hand[0].instance_id)

    def test_fire_ai_prioritizes_removal_over_ramp_when_under_pressure(self) -> None:
        self.engine.phase = PHASE_REACTION
        self.engine.ai_player.life = 3
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("water_creature_wassertropfen"),
        ]
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_kohlevorrat"]),
            CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_verbrennen"]),
        ]
        flyer = self.make_creature("air_creature_windgeist", owner_id=0, ready=True)
        flyer.sw = 4
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_START,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
                attacker_creature=flyer,
            ),
            first_responder_id=self.engine.ai_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_2,
        )

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "cast_spell")
        self.assertEqual(self.engine.pending_ai_action["card_id"], self.engine.ai_player.hand[1].instance_id)

    def test_fire_ai_prioritizes_hitzewelle_for_immediate_lethal(self) -> None:
        ritual = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_hitzewelle"])
        self.engine.ai_player.hand = [ritual]
        self.engine.ai_player.resources = [
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("fire_creature_gluthetzer"),
            self.make_resource("fire_creature_gluthetzer"),
        ]
        self.engine.ai_player.life = 5
        self.engine.human_player.life = 2

        payload = build_fire_turn_plan_payload(
            self.engine.ai.turn_planner,
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertEqual(payload["sequence"], [ritual.instance_id])

    def test_fire_ai_prioritizes_feuerwelle_for_immediate_lethal(self) -> None:
        ritual = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_feuerwelle"])
        self.engine.ai_player.hand = [ritual]
        self.engine.ai_player.resources = [self.make_resource("fire_creature_gluthetzer") for _ in range(5)]
        self.engine.ai_player.life = 6
        self.engine.human_player.life = 4

        payload = build_fire_turn_plan_payload(
            self.engine.ai.turn_planner,
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertEqual(payload["sequence"], [ritual.instance_id])

    def test_fire_ai_treats_double_death_ritual_as_draw_not_win(self) -> None:
        self.engine.ai_player.life = 2
        self.engine.human_player.life = 2

        result = evaluate_fire_board_wipe(self.engine.ai, self.engine.ai_player, self.engine.human_player, 2)

        self.assertTrue(result["is_draw"])
        self.assertFalse(result["is_lethal"])

    def test_fire_ai_does_not_play_ritual_that_only_kills_itself(self) -> None:
        ritual = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_hitzewelle"])
        self.engine.ai_player.hand = [ritual]
        self.engine.ai_player.resources = [self.make_resource("fire_creature_gluthetzer") for _ in range(3)]
        self.engine.ai_player.life = 2
        self.engine.human_player.life = 5

        payload = build_fire_turn_plan_payload(
            self.engine.ai.turn_planner,
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertEqual(payload["sequence"], [])

    def test_fire_ai_detects_ritual_plus_blocker_removal_combat_lethal(self) -> None:
        ritual = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_hitzewelle"])
        self.engine.ai_player.hand = [ritual]
        self.engine.ai_player.resources = [self.make_resource("fire_creature_gluthetzer") for _ in range(3)]
        attacker = self.make_creature("fire_creature_gluthetzer", owner_id=1, ready=True)
        attacker.sw = 3
        attacker.current_hp = 3
        blocker = self.make_creature("earth_creature_steinwesen", owner_id=0, ready=True)
        blocker.current_hp = 2
        self.engine.ai_player.life = 8
        self.engine.human_player.life = 5

        payload = build_fire_turn_plan_payload(
            self.engine.ai.turn_planner,
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertEqual(payload["sequence"], [ritual.instance_id])
        self.assertIn(attacker.unit_id, payload["attacker_ids"])
        self.assertGreaterEqual(payload["expected_attack_damage"], 3)

    def test_fire_ai_detects_trample_overflow_after_ritual_damage(self) -> None:
        ritual = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_ritual_hitzewelle"])
        self.engine.ai_player.hand = [ritual]
        self.engine.ai_player.resources = [self.make_resource("fire_creature_gluthetzer") for _ in range(3)]
        attacker = self.make_creature("fire_creature_gluthetzer", owner_id=1, ready=True)
        attacker.abilities = tuple(set(attacker.abilities) | {Ability.TRAMPLE})
        attacker.sw = 3
        attacker.current_hp = 3
        blocker = self.make_creature("earth_creature_felswesen", owner_id=0, ready=True)
        blocker.current_hp = 4
        self.engine.ai_player.life = 8
        self.engine.human_player.life = 3

        payload = build_fire_turn_plan_payload(
            self.engine.ai.turn_planner,
            self.engine.ai,
            self.engine.ai_player,
            self.engine,
            hand=list(self.engine.ai_player.hand),
            available_resources=self.engine.ai_player.available_resources(),
            total_resources=self.engine.ai_player.total_resources(),
            phase=PHASE_MAIN_1,
        )

        self.assertEqual(payload["sequence"], [ritual.instance_id])
        self.assertIn(attacker.unit_id, payload["attacker_ids"])
        self.assertGreaterEqual(payload["expected_attack_damage"], 1)

    def test_fire_ai_penalizes_ritual_that_opens_counter_lethal(self) -> None:
        self.engine.ai_player.life = 5
        self.engine.human_player.life = 8
        self.make_creature("earth_creature_steinwesen", owner_id=1, ready=True).current_hp = 2
        enemy_attacker = self.make_creature("fire_creature_gluthetzer", owner_id=0, ready=True)
        enemy_attacker.sw = 3
        enemy_attacker.current_hp = 3

        result = evaluate_fire_board_wipe(self.engine.ai, self.engine.ai_player, self.engine.human_player, 2)

        self.assertFalse(result["is_lethal"])
        self.assertLess(result["score"], 0.0)


