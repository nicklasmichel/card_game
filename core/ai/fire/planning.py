from __future__ import annotations

from dataclasses import replace

from core.ai.candidates import AttackCandidate, EvaluationBreakdown, MainPhaseSequenceCandidate, PlanningState, TurnPlanCandidate
from core.ai.fire.assessment import build_fire_snapshot
from core.ai.fire.effects import choose_best_damage_target, evaluate_fire_board_wipe, evaluate_fire_draw_spell, evaluate_fire_ramp_spell
from core.models import Ability, CardType, PHASE_MAIN_1, PHASE_MAIN_2, PlayerState, SpellEffect


def _resource_options(player, hand):
    max_count = min(2 - player.resources_played_this_turn, len(hand))
    return list(range(max_count + 1))


def _resource_candidates(ai, player, hand, count: int):
    if count <= 0:
        return []
    scored = sorted(
        hand,
        key=lambda card: (
            1 if card.template.card_type == CardType.CREATURE and card.template.resource_cost >= 4 else 0,
            1 if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE else 0,
            card.template.resource_cost + card.template.recycle_cost,
            card.template.aw + card.template.vw,
        ),
    )
    return scored[:count]


def _apply_resource_gain(player, available_resources: int, total_resources: int, resource_count: int) -> tuple[int, int]:
    gain_available = 1 if resource_count > 0 and player.resources_played_this_turn == 0 else 0
    return available_resources + gain_available, total_resources + resource_count


def _score_fire_creature(card, snapshot) -> float:
    template = card.template
    value = template.sw * 2.2 + template.lw * 1.35 + template.aw * 0.65 + template.vw * 0.45
    if template.has_ability(Ability.TRAMPLE):
        value += 1.8 + snapshot.enemy_creatures * 0.35
    if template.has_ability(Ability.ENRAGED):
        value += 1.2 + snapshot.enemy_creatures * 0.2
        if template.has_ability(Ability.TRAMPLE):
            value += 1.0
    if template.resource_cost >= 4:
        value += 1.6
    if snapshot.enemy_flyers > 0 and template.vw >= 3:
        value += 1.1
    return value


def _score_fire_main_phase_card(player, enemy, engine, card, snapshot, phase: str) -> float:
    template = card.template
    if template.card_type == CardType.CREATURE:
        if snapshot.available_resources < template.resource_cost or snapshot.total_resources < template.recycle_cost:
            return -999.0
        return _score_fire_creature(card, snapshot) + (1.2 if snapshot.can_deploy_threat else 0.0)
    if template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
        target = choose_best_damage_target(engine, player, template.spell_amount)
        if target is None:
            return -999.0
        creature = engine.get_unit_by_id(target.creature_id or -1)
        if creature is None:
            return -999.0
        base = 7.0 if creature.current_hp <= template.spell_amount else 1.0
        if creature.has_ability(Ability.FLYING):
            base += 2.5
        if snapshot.opponent_lethal_threat:
            base += creature.aw * 1.6
        return base - template.resource_cost * 0.3
    if template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_ALL_CREATURES:
        result = evaluate_fire_board_wipe(player, enemy, template.spell_amount)
        return result["score"] + (2.2 if snapshot.opponent_lethal_threat else 0.0)
    if template.spell_effect == SpellEffect.DECK_TO_TAPPED_RESOURCES:
        phase_penalty = -0.5 if phase == PHASE_MAIN_1 else 0.7
        return evaluate_fire_ramp_spell(player, card, snapshot.next_resource_goal) + phase_penalty
    if template.spell_effect == SpellEffect.DRAW_CARDS:
        phase_bonus = 0.8 if phase == PHASE_MAIN_2 else -0.5
        return evaluate_fire_draw_spell(player, card) + phase_bonus
    return -999.0


def _choose_fire_sequence(ai, player, enemy, engine, hand, available_resources: int, total_resources: int, phase: str):
    snapshot = build_fire_snapshot(ai, player, engine, hand=hand, available_resources=available_resources, total_resources=total_resources, phase=phase)
    augmented = replace(snapshot, available_resources=available_resources, total_resources=total_resources)
    playable = [
        card for card in hand
        if available_resources >= card.template.resource_cost
        and total_resources >= card.template.recycle_cost
        and engine.can_play_card(player, card)
    ]
    if not playable:
        return [], available_resources, total_resources, 0.0
    best = max(playable, key=lambda card: _score_fire_main_phase_card(player, enemy, engine, card, augmented, phase))
    best_score = _score_fire_main_phase_card(player, enemy, engine, best, augmented, phase)
    if best_score < 1.0:
        return [], available_resources, total_resources, 0.0
    return [best.instance_id], available_resources - best.template.resource_cost, total_resources - best.template.recycle_cost, best_score


def _choose_attackers(ai, player, enemy, engine):
    ready = [creature for creature in player.battlefield if creature.is_ready() and creature.current_hp > 0]
    if not ready:
        return []
    chosen = []
    blockers = [creature for creature in enemy.battlefield if creature.current_hp > 0 and creature.is_ready() and not creature.cannot_block]
    for creature in ready:
        if not blockers:
            chosen.append(creature)
            continue
        if creature.has_ability(Ability.ENRAGED):
            chosen.append(creature)
            continue
        if creature.has_ability(Ability.TRAMPLE) and creature.sw >= min((blocker.current_hp for blocker in blockers), default=99):
            chosen.append(creature)
            continue
        if creature.sw >= max((blocker.current_hp for blocker in blockers), default=0) and player.life > 6:
            chosen.append(creature)
    return chosen


def _build_attack_candidate(ai, player, enemy, engine, reserved_resources: int):
    attackers = _choose_attackers(ai, player, enemy, engine)
    if not attackers:
        return AttackCandidate()
    direct_damage = 0
    enemy_losses = 0
    blockers = [creature for creature in enemy.battlefield if creature.current_hp > 0 and creature.is_ready() and not creature.cannot_block]
    for creature in attackers:
        if not blockers:
            direct_damage += engine.get_creature_damage_value(creature)
            continue
        if creature.has_ability(Ability.TRAMPLE):
            direct_damage += max((max(0, engine.get_creature_damage_value(creature) - blocker.current_hp) for blocker in blockers), default=0)
        enemy_losses += sum(1 for blocker in blockers if blocker.current_hp <= engine.get_creature_damage_value(creature))
    counter = ai.assessment.estimate_enemy_counterattack(ai, player, enemy, attacking_ids={creature.unit_id for creature in attackers})
    return AttackCandidate(
        attacker_ids=tuple(creature.unit_id for creature in attackers),
        expected_damage=direct_damage,
        expected_enemy_losses=enemy_losses,
        expected_counterattack_damage=int(counter["damage"]),
        combat_started=bool(attackers),
        expected_unblocked_attacker_ids=tuple(creature.unit_id for creature in attackers if not blockers),
        reserved_resources=reserved_resources,
        score=direct_damage * 1.1 + enemy_losses * 1.4 - counter["damage"] * 0.6,
    )


def _build_candidate(ai, player: PlayerState, engine, hand, available_resources: int, total_resources: int, phase: str, main1_resource_count: int, main2_resource_count: int):
    strategy = ai._evaluate_fire_strategy(player, engine, hand=hand, available_resources=available_resources, total_resources=total_resources, phase=phase)
    hand_after_resources = [card for card in hand if card.instance_id not in {card.instance_id for card in _resource_candidates(ai, player, hand, main1_resource_count)}]
    main1_resource_cards = _resource_candidates(ai, player, hand, main1_resource_count)
    main1_available, main1_total = _apply_resource_gain(player, available_resources, total_resources, len(main1_resource_cards))
    enemy = engine.players[1 - player.player_id]
    main1_sequence_ids, end_available, end_total, main1_score = _choose_fire_sequence(
        ai, player, enemy, engine, hand_after_resources, main1_available, main1_total, PHASE_MAIN_1 if phase == PHASE_MAIN_1 else phase
    )
    remaining_after_main1 = [card for card in hand_after_resources if card.instance_id not in set(main1_sequence_ids)]
    reserved_resources = 0
    if any(card.template.template_id == "fire_spell_wutanfall" for card in remaining_after_main1):
        reserved_resources = max(reserved_resources, 0)
    if any(card.template.template_id == "fire_spell_raserei" for card in remaining_after_main1):
        reserved_resources = max(reserved_resources, 0)
    if any(card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE for card in remaining_after_main1):
        reserved_resources = max(reserved_resources, 1)
    attack = _build_attack_candidate(ai, player, enemy, engine, reserved_resources)
    main2 = None
    if phase == PHASE_MAIN_1 and attack.combat_started:
        main2_resource_cards = _resource_candidates(ai, player, remaining_after_main1, main2_resource_count)
        main2_hand = [card for card in remaining_after_main1 if card.instance_id not in {card.instance_id for card in main2_resource_cards}]
        main2_available, main2_total = _apply_resource_gain(
            player,
            max(0, end_available - reserved_resources),
            end_total,
            len(main2_resource_cards),
        )
        main2_sequence_ids, main2_end_available, main2_end_total, main2_score = _choose_fire_sequence(
            ai, player, enemy, engine, main2_hand, main2_available, main2_total, PHASE_MAIN_2
        )
        main2 = MainPhaseSequenceCandidate(
            phase=PHASE_MAIN_2,
            resource_card_ids=tuple(card.instance_id for card in main2_resource_cards),
            card_sequence_ids=tuple(main2_sequence_ids),
            ending_available_resources=main2_end_available,
            ending_total_resources=main2_end_total,
            projected_hand_ids=tuple(card.instance_id for card in main2_hand if card.instance_id not in set(main2_sequence_ids)),
            score=main2_score,
        )
    main1 = MainPhaseSequenceCandidate(
        phase=phase,
        resource_card_ids=tuple(card.instance_id for card in main1_resource_cards),
        card_sequence_ids=tuple(main1_sequence_ids),
        first_resource_ready=bool(main1_resource_cards and player.resources_played_this_turn == 0),
        second_resource_tapped=main1_resource_count >= 2 or (main1_resource_count >= 1 and player.resources_played_this_turn >= 1),
        ending_available_resources=end_available,
        ending_total_resources=end_total,
        projected_hand_ids=tuple(card.instance_id for card in remaining_after_main1),
        score=main1_score,
    )
    planning_state = PlanningState(
        phase=phase,
        hand_ids=tuple(card.instance_id for card in hand),
        available_resources=available_resources,
        total_resources=total_resources,
        resources_played_this_turn=player.resources_played_this_turn,
        reserved_resources=reserved_resources,
        expected_attacker_ids=attack.attacker_ids,
        expected_enemy_losses=attack.expected_enemy_losses,
    )
    end_hand_ids = main2.projected_hand_ids if main2 is not None else main1.projected_hand_ids
    total_score = main1.score + attack.score + (0.0 if main2 is None else main2.score)
    if strategy.mode == "LETHAL" and attack.expected_damage + build_fire_snapshot(ai, player, engine, hand=remaining_after_main1, available_resources=end_available, total_resources=end_total, phase=phase).total_direct_spell_damage >= enemy.life:
        total_score += 12.0
    breakdown = EvaluationBreakdown(
        total_score=total_score,
        player_damage_value=float(attack.expected_damage),
        board_value=float(attack.expected_enemy_losses - attack.expected_own_losses),
        hand_value=len(end_hand_ids) * 0.25,
        counterattack_penalty=attack.expected_counterattack_damage * 0.6,
        recycle_penalty=0.0,
        reason_codes=tuple(strategy.reason_codes),
    )
    return TurnPlanCandidate(
        strategy_mode=strategy.mode,
        primary_goal=strategy.primary_goal,
        strategy_reason_codes=tuple(strategy.reason_codes),
        strategy_weights=strategy.weights,
        strategy_metrics=tuple(strategy.metrics),
        planning_state=planning_state,
        main_1=main1,
        attack=attack,
        main_2=main2,
        breakdown=breakdown,
        reaction_intents=tuple(),
        reserved_resources=reserved_resources,
        expected_end_hand_ids=end_hand_ids,
        expected_end_total_resources=main2.ending_total_resources if main2 is not None else main1.ending_total_resources,
        expected_end_available_resources=main2.ending_available_resources if main2 is not None else main1.ending_available_resources,
        expected_end_own_creatures=len(player.battlefield),
        expected_end_enemy_creatures=max(0, len(enemy.battlefield) - attack.expected_enemy_losses),
        expected_enemy_life=max(0, enemy.life - attack.expected_damage),
        expected_own_life=max(0, player.life - attack.expected_counterattack_damage),
        recycle_loss=0,
        reason_codes=tuple(strategy.reason_codes),
    )


def build_fire_turn_candidates(planner, ai, player, engine, *, hand, available_resources: int, total_resources: int, phase: str):
    candidates = []
    for main1_count in _resource_options(player, hand):
        for main2_count in range(0, min(2 - player.resources_played_this_turn - main1_count, max(0, len(hand) - main1_count)) + 1):
            candidate = _build_candidate(ai, player, engine, hand, available_resources, total_resources, phase, main1_count, main2_count)
            candidates.append(candidate)
    candidates.sort(key=lambda candidate: candidate.breakdown.total_score, reverse=True)
    return candidates[:8]


def build_fire_turn_plan_payload(planner, ai, player, engine, *, hand, available_resources: int, total_resources: int, phase: str) -> dict:
    candidates = build_fire_turn_candidates(
        planner,
        ai,
        player,
        engine,
        hand=hand,
        available_resources=available_resources,
        total_resources=total_resources,
        phase=phase,
    )
    if not candidates:
        strategy = ai._evaluate_fire_strategy(player, engine, hand=hand, available_resources=available_resources, total_resources=total_resources, phase=phase)
        return {
            "main1_resource_card_ids": [],
            "sequence": [],
            "attacker_ids": [],
            "expected_attack_damage": 0,
            "graveyard_target_ids": [],
            "bounce_target_ids": [],
            "himmelswende_target_ids": [],
            "main2_resource_card_ids": [],
            "main2_sequence": [],
            "main2_graveyard_target_ids": [],
            "main2_bounce_target_ids": [],
            "reason_codes": tuple(strategy.reason_codes),
            "strategy_mode": strategy.mode,
            "primary_goal": strategy.primary_goal,
            "strategy_reason_codes": tuple(strategy.reason_codes),
            "strategy_weights": strategy.weights,
            "strategy_metrics": tuple(strategy.metrics),
            "reserved_resources": 0,
            "reaction_intents": (),
            "combat_started": False,
            "_plan_total": 0.0,
        }
    best = candidates[0]
    return {
        "main1_resource_card_ids": list(best.main_1.resource_card_ids),
        "sequence": list(best.main_1.card_sequence_ids),
        "attacker_ids": list(best.attack.attacker_ids),
        "expected_attack_damage": best.attack.expected_damage,
        "graveyard_target_ids": [],
        "bounce_target_ids": [],
        "himmelswende_target_ids": [],
        "main2_resource_card_ids": [] if best.main_2 is None else list(best.main_2.resource_card_ids),
        "main2_sequence": [] if best.main_2 is None else list(best.main_2.card_sequence_ids),
        "main2_graveyard_target_ids": [],
        "main2_bounce_target_ids": [],
        "reason_codes": tuple(best.reason_codes),
        "strategy_mode": best.strategy_mode,
        "primary_goal": best.primary_goal,
        "strategy_reason_codes": best.strategy_reason_codes,
        "strategy_weights": best.strategy_weights,
        "strategy_metrics": best.strategy_metrics,
        "reserved_resources": best.reserved_resources,
        "reaction_intents": best.reaction_intents,
        "combat_started": best.attack.combat_started,
        "_plan_total": best.breakdown.total_score,
    }
