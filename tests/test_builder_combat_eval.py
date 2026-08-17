from __future__ import annotations

import unittest
from core.builder_rules import BUILDER_ABILITIES_ENABLED
from core.ai.builder import (
    build_builder_snapshot,
    can_legally_be_forced_to_block,
    estimate_builder_combat,
    estimate_builder_combat_sequence,
    estimate_dice_win_probabilities,
    get_d6_sum_distribution,
    project_builder_combat_outcome,
    score_builder_creature_candidate,
)
from core.ai.builder.combat_eval import build_candidate_combatant_view, summarize_builder_combat_matchup
from core.ai.builder.turn_policy import extract_candidate_future_value
from core.ai.builder.types import BuilderCreatureCandidate
from core.game_logic import GameEngine
from core.models import Ability


class BuilderCombatEvalTests(unittest.TestCase):
    def setUp(self) -> None:
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

        self.assertAlmostEqual(
            one_vs_one.attacker_win_probability - one_vs_one.defender_win_probability,
            one_vs_one.raw_tie_probability,
            places=8,
        )
        self.assertAlmostEqual(one_vs_one.raw_tie_probability, 1 / 6, places=8)
        self.assertGreater(one_vs_one.attacker_win_probability, one_vs_one.defender_win_probability)
        self.assertAlmostEqual(one_vs_one.attacker_win_probability + one_vs_one.defender_win_probability, 1.0, places=8)
        self.assertAlmostEqual(
            two_vs_two.attacker_win_probability - two_vs_two.defender_win_probability,
            two_vs_two.raw_tie_probability,
            places=8,
        )
        self.assertGreater(two_vs_two.attacker_win_probability, two_vs_two.defender_win_probability)
        self.assertAlmostEqual(two_vs_two.attacker_win_probability + two_vs_two.defender_win_probability, 1.0, places=8)

    def test_dice_win_probabilities_reflect_larger_and_smaller_pools(self) -> None:
        attacker_favored = estimate_dice_win_probabilities(3, 1)
        attacker_unfavored = estimate_dice_win_probabilities(1, 3)

        self.assertGreater(attacker_favored.attacker_win_probability, 0.5)
        self.assertLess(attacker_unfavored.attacker_win_probability, 0.5)

    def test_exact_block_probabilities_match_documented_d6_values(self) -> None:
        d1_vs_a2 = estimate_dice_win_probabilities(2, 1)
        d1_vs_a3 = estimate_dice_win_probabilities(3, 1)
        d3_vs_a2 = estimate_dice_win_probabilities(2, 3)
        d3_vs_a3 = estimate_dice_win_probabilities(3, 3)

        self.assertAlmostEqual(d1_vs_a2.defender_win_probability, 20 / 216, places=8)
        self.assertAlmostEqual(d1_vs_a3.defender_win_probability, 15 / 1296, places=8)
        self.assertAlmostEqual(d3_vs_a2.defender_win_probability, 0.7785493827, places=8)
        self.assertAlmostEqual(d3_vs_a3.defender_win_probability, 0.4535751029, places=8)

    def test_combat_probability_cache_does_not_mix_attacker_and_blocker_roles(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=3, lw=2, abilities=frozenset(), cost=5),
            current_hp=2,
        )
        blocker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=3, sw=1, lw=4, abilities=frozenset(), cost=6),
            current_hp=4,
        )

        attack_estimate = estimate_builder_combat(attacker, blocker)
        reverse_estimate = estimate_builder_combat(blocker, attacker)

        self.assertNotAlmostEqual(attack_estimate.attacker_win_probability, reverse_estimate.attacker_win_probability, places=8)
        self.assertNotAlmostEqual(attack_estimate.expected_damage_to_defender, reverse_estimate.expected_damage_to_defender, places=8)

    def test_future_projection_uses_one_legal_combat_branch(self) -> None:
        favored_attacker = self.make_builder_creature(1, aw=3, vw=1, sw=3, lw=2, ready=True)
        blocker = self.make_builder_creature(0, aw=1, vw=1, sw=3, lw=2, ready=True)

        outcome = project_builder_combat_outcome(favored_attacker, blocker)

        self.assertTrue(outcome.attacker_wins)
        self.assertTrue(outcome.attacker_survives)
        self.assertFalse(outcome.defender_survives)
        self.assertEqual(outcome.attacker_remaining_hp, favored_attacker.current_hp)
        self.assertEqual(outcome.defender_remaining_hp, 0)

    def test_future_projection_selects_defender_branch_when_more_likely(self) -> None:
        attacker = self.make_builder_creature(1, aw=1, vw=1, sw=3, lw=2, ready=True)
        favored_blocker = self.make_builder_creature(0, aw=1, vw=3, sw=3, lw=2, ready=True)

        outcome = project_builder_combat_outcome(attacker, favored_blocker)

        self.assertFalse(outcome.attacker_wins)
        self.assertFalse(outcome.attacker_survives)
        self.assertTrue(outcome.defender_survives)
        self.assertEqual(outcome.attacker_remaining_hp, 0)
        self.assertEqual(outcome.defender_remaining_hp, favored_blocker.current_hp)

    def test_matchup_cache_preserves_roles_and_attacker_favored_ties(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=1, lw=2, abilities=frozenset(), cost=3),
            current_hp=2,
        )
        blocker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=2, sw=3, lw=2, abilities=frozenset(), cost=4),
            current_hp=2,
        )

        matchup = summarize_builder_combat_matchup(attacker, blocker)
        reverse = summarize_builder_combat_matchup(blocker, attacker)

        self.assertAlmostEqual(matchup.attacker_favored_tie_probability, matchup.raw_tie_probability, places=8)
        self.assertNotAlmostEqual(matchup.block_win_probability, reverse.block_win_probability, places=8)
        self.assertNotAlmostEqual(matchup.attacker_kill_probability, reverse.attacker_kill_probability, places=8)

    def test_zero_dice_special_cases_are_explicit(self) -> None:
        attacker_zero = estimate_dice_win_probabilities(0, 2)
        defender_zero = estimate_dice_win_probabilities(2, 0)
        zero_vs_zero = estimate_dice_win_probabilities(0, 0)

        self.assertEqual(attacker_zero.attacker_win_probability, 0.0)
        self.assertEqual(attacker_zero.defender_win_probability, 1.0)
        self.assertEqual(defender_zero.attacker_win_probability, 1.0)
        self.assertEqual(defender_zero.defender_win_probability, 0.0)
        self.assertEqual(zero_vs_zero.attacker_win_probability, 1.0)
        self.assertEqual(zero_vs_zero.defender_win_probability, 0.0)
        self.assertEqual(zero_vs_zero.raw_tie_probability, 1.0)

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

    def test_repeated_combat_carries_lost_life_into_the_next_encounter(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=1, sw=2, lw=2, abilities=frozenset(), cost=2)
        )
        defender = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=1, vw=0, sw=1, lw=5, abilities=frozenset(), cost=4)
        )

        sequence = estimate_builder_combat_sequence(attacker, defender, max_combats=4)

        self.assertEqual(sequence.attacker_kill_probability, 1.0)
        self.assertEqual(sequence.expected_encounters, 3.0)
        self.assertEqual(sequence.expected_damage_to_defender, 5.0)

    def test_repeated_combat_distinguishes_defense_from_a_life_sponge(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=6, vw=1, sw=5, lw=2, abilities=frozenset(), cost=10)
        )
        contesting_blocker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=7, sw=1, lw=1, abilities=frozenset(), cost=7)
        )
        life_sponge = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=1, vw=2, sw=1, lw=7, abilities=frozenset(), cost=7)
        )

        contest = estimate_builder_combat_sequence(attacker, contesting_blocker, max_combats=4)
        sponge = estimate_builder_combat_sequence(attacker, life_sponge, max_combats=4)

        self.assertGreater(contest.defender_survival_probability, sponge.defender_survival_probability)
        self.assertGreater(contest.defender_kill_probability, sponge.defender_kill_probability)
        self.assertGreater(contest.expected_damage_to_attacker, sponge.expected_damage_to_attacker)

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

    def test_redundant_blocker_gets_less_defensive_value(self) -> None:
        enemy = self.make_builder_creature(0, aw=0, vw=1, sw=2, lw=1, ready=True)
        candidate = BuilderCreatureCandidate(
            aw=0,
            vw=2,
            sw=1,
            lw=2,
            abilities=frozenset({Ability.HASTE}),
            cost=4,
        )
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        first_score = score_builder_creature_candidate(
            candidate,
            snapshot,
            available_resources=4,
            enemy_creatures=[enemy],
            own_creatures=[],
        )
        existing = self.make_builder_creature(1, aw=0, vw=2, sw=1, lw=2, ready=True)
        redundant_score = score_builder_creature_candidate(
            candidate,
            build_builder_snapshot(self.engine.ai_player, self.engine),
            available_resources=4,
            enemy_creatures=[enemy],
            own_creatures=[existing],
        )

        self.assertGreater(first_score.matchup_defense, redundant_score.matchup_defense)

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

    def test_missing_defense_breakpoint_beats_a_redundant_hybrid_in_future_value(self) -> None:
        self.make_builder_creature(1, aw=1, vw=3, sw=1, lw=3, ready=True)
        for _ in range(2):
            self.make_builder_creature(1, aw=2, vw=4, sw=2, lw=1, ready=True)
        for aw, vw, sw, lw in ((2, 2, 2, 2), (3, 1, 3, 2), (5, 1, 1, 3)):
            self.make_builder_creature(0, aw=aw, vw=vw, sw=sw, lw=lw, ready=True)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        redundant_hybrid = BuilderCreatureCandidate(aw=2, vw=4, sw=2, lw=1, abilities=frozenset(), cost=5)
        breakpoint_blocker = BuilderCreatureCandidate(aw=1, vw=6, sw=1, lw=1, abilities=frozenset(), cost=5)

        hybrid_score = score_builder_creature_candidate(
            redundant_hybrid,
            snapshot,
            available_resources=5,
            enemy_creatures=list(self.engine.human_player.battlefield),
            own_creatures=list(self.engine.ai_player.battlefield),
        )
        breakpoint_score = score_builder_creature_candidate(
            breakpoint_blocker,
            snapshot,
            available_resources=5,
            enemy_creatures=list(self.engine.human_player.battlefield),
            own_creatures=list(self.engine.ai_player.battlefield),
        )

        self.assertGreater(breakpoint_score.board_fit, hybrid_score.board_fit)
        self.assertGreater(
            extract_candidate_future_value(breakpoint_score, breakpoint_blocker, snapshot),
            extract_candidate_future_value(hybrid_score, redundant_hybrid, snapshot),
        )

    def test_blocker_damage_above_enemy_life_does_not_change_attacker_kill_probability(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=3, lw=1, abilities=frozenset({Ability.HASTE}), cost=5),
            current_hp=1,
        )
        dmg_one = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=3, sw=1, lw=1, abilities=frozenset({Ability.HASTE}), cost=4),
            current_hp=1,
        )
        dmg_two = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=3, sw=2, lw=1, abilities=frozenset({Ability.HASTE}), cost=5),
            current_hp=1,
        )

        one_estimate = estimate_builder_combat(attacker, dmg_one)
        two_estimate = estimate_builder_combat(attacker, dmg_two)

        self.assertAlmostEqual(one_estimate.attacker_death_probability, two_estimate.attacker_death_probability, places=8)

    def test_life_breakpoint_only_changes_survival_when_hit_damage_is_crossed(self) -> None:
        attacker = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=2, vw=0, sw=3, lw=1, abilities=frozenset({Ability.HASTE}), cost=5),
            current_hp=1,
        )
        life_two = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=3, sw=1, lw=2, abilities=frozenset({Ability.HASTE}), cost=4),
            current_hp=2,
        )
        life_three = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=3, sw=1, lw=3, abilities=frozenset({Ability.HASTE}), cost=5),
            current_hp=3,
        )
        life_four = build_candidate_combatant_view(
            BuilderCreatureCandidate(aw=0, vw=3, sw=1, lw=4, abilities=frozenset({Ability.HASTE}), cost=6),
            current_hp=4,
        )

        two_estimate = estimate_builder_combat(attacker, life_two)
        three_estimate = estimate_builder_combat(attacker, life_three)
        four_estimate = estimate_builder_combat(attacker, life_four)

        self.assertAlmostEqual(two_estimate.defender_survival_probability, three_estimate.defender_survival_probability, places=8)
        self.assertGreater(four_estimate.defender_survival_probability, three_estimate.defender_survival_probability)

    def test_haste_immediate_pressure_spikes_with_open_lethal_line(self) -> None:
        self.engine.human_player.life = 4
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        with_haste = BuilderCreatureCandidate(aw=2, vw=1, sw=4, lw=2, abilities=frozenset({Ability.HASTE}), cost=8)
        without_haste = BuilderCreatureCandidate(aw=2, vw=1, sw=4, lw=2, abilities=frozenset(), cost=7)

        haste_score = score_builder_creature_candidate(with_haste, snapshot, available_resources=8, enemy_creatures=[])
        non_haste_score = score_builder_creature_candidate(without_haste, snapshot, available_resources=7, enemy_creatures=[])

        self.assertGreater(haste_score.immediate_pressure, non_haste_score.immediate_pressure)
        self.assertGreater(haste_score.total, non_haste_score.total)

    def test_extra_damage_is_discounted_when_damage_one_already_kills_life_one_attacker(self) -> None:
        attacker = self.make_builder_creature(0, aw=2, vw=0, sw=3, lw=1, ready=True, abilities=(Ability.HASTE,))
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        low_damage = BuilderCreatureCandidate(aw=0, vw=3, sw=1, lw=1, abilities=frozenset({Ability.HASTE}), cost=4)
        high_damage = BuilderCreatureCandidate(aw=0, vw=3, sw=2, lw=1, abilities=frozenset({Ability.HASTE}), cost=5)

        low_score = score_builder_creature_candidate(low_damage, snapshot, available_resources=4, enemy_creatures=[attacker])
        high_score = score_builder_creature_candidate(high_damage, snapshot, available_resources=5, enemy_creatures=[attacker])

        self.assertAlmostEqual(low_score.attacker_kill_probability, high_score.attacker_kill_probability, places=8)
        self.assertGreaterEqual(low_score.blocker_survival_probability, high_score.blocker_survival_probability)

    def test_ground_damage_is_marked_stranded_when_a_legal_blocker_stops_delivery(self) -> None:
        self.make_builder_creature(0, aw=0, vw=3, sw=1, lw=3, ready=True)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)
        ground_shell = BuilderCreatureCandidate(aw=0, vw=0, sw=2, lw=1, abilities=frozenset({Ability.HASTE}), cost=2)

        score = score_builder_creature_candidate(
            ground_shell,
            snapshot,
            available_resources=2,
            enemy_creatures=list(self.engine.human_player.battlefield),
        )

        self.assertGreater(score.stranded_damage, 0.0)
        self.assertLess(score.damage_delivery_probability, 0.5)

    def test_low_attack_flying_keeps_positive_delivery_probability(self) -> None:
        flying = BuilderCreatureCandidate(aw=0, vw=1, sw=2, lw=1, abilities=frozenset({Ability.FLYING}), cost=3)
        snapshot = build_builder_snapshot(self.engine.ai_player, self.engine)

        score = score_builder_creature_candidate(flying, snapshot, available_resources=3, enemy_creatures=list(self.engine.human_player.battlefield))

        self.assertGreater(score.damage_delivery_probability, 0.5)
        self.assertGreater(score.evasion, 0.0)
