from __future__ import annotations

import unittest
from unittest.mock import patch

import core.config as config
from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.ai.builder import (
    build_builder_snapshot,
    can_legally_be_forced_to_block,
    estimate_builder_combat,
    estimate_dice_win_probabilities,
    get_d6_sum_distribution,
    score_builder_creature_candidate,
)
from core.ai.builder.combat_eval import build_candidate_combatant_view
from core.ai.builder.types import BuilderCreatureCandidate
from core.game_logic import GameEngine
from core.models import Ability


class BuilderCombatEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(config, "GAME_MODE", "builder")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = GameEngine()
        self.engine.log_messages.clear()

    def make_builder_creature(
        self,
        owner_id: int,
        *,
        aw: int,
        vw: int,
        sw: int,
        lw: int,
        abilities: tuple[Ability, ...] = (),
        ready: bool = True,
        current_hp: int | None = None,
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
        creature.tapped = not ready
        creature.summoning_sick = not ready
        if current_hp is not None:
            creature.current_hp = current_hp
        return creature

    def test_distribution_for_one_d6_is_uniform(self) -> None:
        distribution = get_d6_sum_distribution(1)

        self.assertEqual(set(distribution.keys()), {1, 2, 3, 4, 5, 6})
        for probability in distribution.values():
            self.assertAlmostEqual(probability, 1 / 6, places=8)

    def test_dice_win_probabilities_are_symmetric_for_equal_pools(self) -> None:
        one_vs_one = estimate_dice_win_probabilities(1, 1)
        two_vs_two = estimate_dice_win_probabilities(2, 2)

        self.assertAlmostEqual(one_vs_one.attacker_win_probability, 0.5, places=8)
        self.assertAlmostEqual(one_vs_one.defender_win_probability, 0.5, places=8)
        self.assertAlmostEqual(one_vs_one.raw_tie_probability, 1 / 6, places=8)
        self.assertAlmostEqual(two_vs_two.attacker_win_probability, 0.5, places=8)
        self.assertAlmostEqual(two_vs_two.defender_win_probability, 0.5, places=8)

    def test_dice_win_probabilities_reflect_larger_and_smaller_pools(self) -> None:
        attacker_favored = estimate_dice_win_probabilities(3, 1)
        attacker_unfavored = estimate_dice_win_probabilities(1, 3)

        self.assertGreater(attacker_favored.attacker_win_probability, 0.5)
        self.assertLess(attacker_unfavored.attacker_win_probability, 0.5)

    def test_zero_dice_special_cases_are_explicit(self) -> None:
        attacker_zero = estimate_dice_win_probabilities(0, 2)
        defender_zero = estimate_dice_win_probabilities(2, 0)

        self.assertEqual(attacker_zero.attacker_win_probability, 0.0)
        self.assertEqual(attacker_zero.defender_win_probability, 1.0)
        self.assertEqual(defender_zero.attacker_win_probability, 1.0)
        self.assertEqual(defender_zero.defender_win_probability, 0.0)

    def test_combat_damage_and_death_probability_use_effective_damage(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=4, lw=4, abilities=frozenset(), cost=6),
            current_hp=4,
        )
        defender = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=1, sw=2, lw=3, abilities=frozenset(), cost=4),
            current_hp=3,
        )

        estimate = estimate_builder_combat(attacker, defender)

        self.assertAlmostEqual(
            estimate.expected_damage_to_defender,
            estimate.attacker_win_probability * 3,
            places=8,
        )
        self.assertAlmostEqual(estimate.defender_death_probability, estimate.attacker_win_probability, places=8)

    def test_trample_expected_player_damage_matches_overflow(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=5, lw=4, abilities=frozenset({Ability.TRAMPLE}), cost=8),
            current_hp=4,
        )
        defender = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=1, sw=1, lw=2, abilities=frozenset(), cost=2),
            current_hp=2,
        )

        estimate = estimate_builder_combat(attacker, defender)

        self.assertAlmostEqual(estimate.expected_player_damage, estimate.attacker_win_probability * 3, places=8)

    def test_lifesteal_uses_actual_damage_and_missing_hp(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=5, lw=6, abilities=frozenset({Ability.LIFE_STEAL}), cost=10),
            current_hp=3,
        )
        blocker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=1, sw=1, lw=2, abilities=frozenset(), cost=2),
            current_hp=2,
        )
        trample_attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=5, lw=6, abilities=frozenset({Ability.LIFE_STEAL, Ability.TRAMPLE}), cost=11),
            current_hp=3,
        )

        no_trample = estimate_builder_combat(attacker, blocker)
        with_trample = estimate_builder_combat(trample_attacker, blocker)

        self.assertAlmostEqual(no_trample.expected_attacker_heal, no_trample.attacker_win_probability * 2, places=8)
        self.assertAlmostEqual(with_trample.expected_attacker_heal, with_trample.attacker_win_probability * 3, places=8)

    def test_flying_scoring_is_higher_without_legal_flying_blockers(self) -> None:
        candidate = BuilderCreatureCandidate(aw=2, vw=1, sw=3, lw=2, abilities=frozenset({Ability.FLYING}), cost=7)
        no_flying_snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        no_flying_score = score_builder_creature_candidate(
            candidate,
            no_flying_snapshot,
            available_resources=7,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.make_builder_creature(0, aw=1, vw=1, sw=1, lw=2, abilities=(Ability.FLYING,), ready=True)
        flying_snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        flying_score = score_builder_creature_candidate(
            candidate,
            flying_snapshot,
            available_resources=7,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.assertGreater(no_flying_score.evasion, flying_score.evasion)
        if BUILDER_ABILITIES_ENABLED:
            self.assertGreater(no_flying_score.total, flying_score.total)

    def test_enraged_prefers_better_forced_matchup_and_respects_flying_legality(self) -> None:
        weak_ground = self.make_builder_creature(0, aw=1, vw=0, sw=1, lw=1, ready=True)
        strong_flier = self.make_builder_creature(0, aw=3, vw=3, sw=4, lw=5, abilities=(Ability.FLYING,), ready=True)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        enraged_flier = BuilderCreatureCandidate(
            aw=3,
            vw=1,
            sw=3,
            lw=3,
            abilities=frozenset({Ability.ENRAGED, Ability.FLYING}),
            cost=10,
        )
        estimate_score = score_builder_creature_candidate(
            enraged_flier,
            snapshot,
            available_resources=10,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.assertFalse(can_legally_be_forced_to_block(build_candidate_combatant_view(enraged_flier), weak_ground))
        self.assertTrue(can_legally_be_forced_to_block(build_candidate_combatant_view(enraged_flier), strong_flier))
        self.assertGreater(estimate_score.matchup_offense, 0)

    def test_trample_scoring_improves_against_low_hp_blockers(self) -> None:
        candidate = BuilderCreatureCandidate(aw=3, vw=1, sw=5, lw=3, abilities=frozenset({Ability.TRAMPLE}), cost=11)
        low_hp_blocker = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=2, ready=True)
        low_snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        low_score = score_builder_creature_candidate(
            candidate,
            low_snapshot,
            available_resources=11,
            enemy_creatures=[low_hp_blocker],
        )

        self.engine.human_player.battlefield.clear()
        high_hp_blocker = self.make_builder_creature(0, aw=1, vw=2, sw=1, lw=7, ready=True)
        high_snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        high_score = score_builder_creature_candidate(
            candidate,
            high_snapshot,
            available_resources=11,
            enemy_creatures=[high_hp_blocker],
        )

        self.assertGreater(low_score.expected_player_damage, high_score.expected_player_damage)
        self.assertGreater(low_score.total, high_score.total)

    def test_defensive_matchups_reward_tough_blockers(self) -> None:
        self.make_builder_creature(0, aw=3, vw=1, sw=4, lw=3, ready=True)
        self.make_builder_creature(0, aw=2, vw=1, sw=3, lw=2, ready=True)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        tough = BuilderCreatureCandidate(aw=1, vw=4, sw=1, lw=5, abilities=frozenset({Ability.VIGILANT}), cost=11)
        fragile = BuilderCreatureCandidate(aw=4, vw=0, sw=4, lw=1, abilities=frozenset(), cost=8)

        tough_score = score_builder_creature_candidate(
            tough,
            snapshot,
            available_resources=11,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )
        fragile_score = score_builder_creature_candidate(
            fragile,
            snapshot,
            available_resources=11,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.assertGreater(tough_score.matchup_defense, fragile_score.matchup_defense)

    def test_haste_immediate_pressure_spikes_with_open_lethal_line(self) -> None:
        self.engine.human_player.life = 4
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        with_haste = BuilderCreatureCandidate(aw=2, vw=1, sw=4, lw=2, abilities=frozenset({Ability.HASTE}), cost=8)
        without_haste = BuilderCreatureCandidate(aw=2, vw=1, sw=4, lw=2, abilities=frozenset(), cost=7)

        haste_score = score_builder_creature_candidate(with_haste, snapshot, available_resources=8, enemy_creatures=[])
        non_haste_score = score_builder_creature_candidate(without_haste, snapshot, available_resources=7, enemy_creatures=[])

        self.assertGreater(haste_score.immediate_pressure, non_haste_score.immediate_pressure)
        self.assertGreater(haste_score.total, non_haste_score.total)
