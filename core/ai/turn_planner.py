from __future__ import annotations

from typing import List, Optional

from core.ai.candidates import AttackCandidate, EvaluationBreakdown, MainPhaseSequenceCandidate, PlanningState, TurnPlanCandidate
from core.ai.fire.planning import build_fire_turn_candidates, build_fire_turn_plan_payload
from core.ai.plans import (
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_DISCARDED,
    PLAN_STATUS_INVALID,
    VALIDATION_STATUS_COMPLETED,
    VALIDATION_STATUS_REPLAN,
    VALIDATION_STATUS_VALID,
    PlanStep,
    PlanValidationResult,
    PlannedAttack,
    ReactionIntent,
    ResourceReservation,
    TurnPlan,
)
from core.ai.strategies.base import StrategyWeights
from core.models import Ability, BattlefieldCreature, CardInstance, CardType, PHASE_MAIN_1, PHASE_MAIN_2, PHASE_REACTION, PHASE_SPELL_TARGETING, PlayerState, SpellEffect, SpellTiming

AIR_MAX_RESOURCE_VARIANTS = 6
AIR_MAX_ATTACK_VARIANTS = 6
AIR_MAX_TOTAL_TURN_CANDIDATES = 8
AIR_MAX_SUBSET_ATTACKERS = 6


class TurnPlanner:
    def evaluate_strategy(
        self,
        ai,
        player: PlayerState,
        engine,
        *,
        hand: list[CardInstance] | None = None,
        available_resources: int | None = None,
        total_resources: int | None = None,
        phase: str | None = None,
    ):
        actual_hand = list(player.hand) if hand is None else list(hand)
        return ai._current_strategy(player, engine).evaluate(
            ai,
            player,
            engine,
            hand=actual_hand,
            available_resources=player.available_resources() if available_resources is None else available_resources,
            total_resources=player.total_resources() if total_resources is None else total_resources,
            phase=engine.phase if phase is None else phase,
        )

    def strategy_weights(
        self,
        ai,
        player: PlayerState,
        engine,
        *,
        hand: list[CardInstance] | None = None,
        available_resources: int | None = None,
        total_resources: int | None = None,
        phase: str | None = None,
    ) -> StrategyWeights:
        return self.evaluate_strategy(
            ai,
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
            phase=phase,
        ).weights

    def clear_active_turn_plan(self, ai) -> None:
        ai.plan_manager.clear(reason_codes=(), status=PLAN_STATUS_DISCARDED)

    def get_active_turn_plan(self, ai) -> TurnPlan | None:
        return ai.plan_manager.active_turn_plan

    def set_active_turn_plan(self, ai, plan: TurnPlan) -> None:
        ai.plan_manager.activate(plan)

    def archive_and_clear_active_turn_plan(self, ai, reason_codes: tuple[str, ...], *, status: str) -> None:
        ai.plan_manager.clear(reason_codes=reason_codes, status=status)

    def get_planned_attacker_ids(self, ai) -> tuple[int, ...]:
        plan = self.get_active_turn_plan(ai)
        if plan is None:
            return ()
        return plan.attack.attacker_ids

    def get_planned_step_for_card(self, ai, card_instance_id: int) -> PlanStep | None:
        plan = self.get_active_turn_plan(ai)
        if plan is None:
            return None
        return plan.step_for_card(card_instance_id)

    def get_planned_target_ids_for_card(self, ai, card_instance_id: int) -> tuple[int, ...]:
        step = self.get_planned_step_for_card(ai, card_instance_id)
        if step is None:
            return ()
        return step.target_ids

    def mark_turn_plan_step_completed(self, ai, action_type: str, *, card_instance_id: int | None = None) -> None:
        ai.plan_manager.mark_completed(action_type, card_instance_id=card_instance_id)

    def get_expected_action_card_id(self, ai, action_type: str) -> int | None:
        plan = self.get_active_turn_plan(ai)
        if plan is None:
            return None
        step = plan.current_step()
        if step is None or step.action_type != action_type:
            return None
        return step.card_instance_id

    def get_active_turn_plan_step(self, ai, expected_action_types: tuple[str, ...] = ()) -> PlanStep | None:
        plan = self.get_active_turn_plan(ai)
        if plan is None:
            return None
        step = plan.current_step()
        if step is None:
            return None
        if expected_action_types and step.action_type not in expected_action_types:
            return None
        return step

    def validate_active_air_plan(self, ai, player: PlayerState, engine) -> PlanValidationResult:
        plan = self.get_active_turn_plan(ai)
        if plan is None:
            return PlanValidationResult(VALIDATION_STATUS_COMPLETED, ("plan_completed",))
        if plan.player_id != player.player_id:
            return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("wrong_active_player",))
        if plan.turn_number != engine.turn_number:
            return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("wrong_turn",))
        current_strategy = self.evaluate_strategy(ai, player, engine)
        if plan.strategy_mode and plan.strategy_mode != current_strategy.mode:
            return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("strategy_mode_changed",))
        current_step = plan.current_step()
        if current_step is None:
            return PlanValidationResult(VALIDATION_STATUS_COMPLETED, ("plan_completed",))
        if current_step.expected_phase is not None and engine.phase != current_step.expected_phase:
            allowed_transition = current_step.expected_phase == PHASE_MAIN_2 and engine.phase in {
                PHASE_MAIN_1,
                PHASE_REACTION,
                PHASE_SPELL_TARGETING,
            }
            if not allowed_transition:
                return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("unexpected_phase",), invalid_step_index=plan.next_step_index)
        if current_step.action_type in {"to_combat", "declare_attackers"}:
            missing_attackers = [
                attacker_id
                for attacker_id in plan.attack.attacker_ids
                if not any(creature.unit_id == attacker_id and creature.is_ready() for creature in player.battlefield)
            ]
            if missing_attackers:
                return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("attacker_no_longer_available",), invalid_step_index=plan.next_step_index)
        elif current_step.card_instance_id is not None:
            card_in_hand = next((card for card in player.hand if card.instance_id == current_step.card_instance_id), None)
            if card_in_hand is None:
                return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("card_not_available",), invalid_step_index=plan.next_step_index)
        if current_step.target_ids:
            if current_step.action_type == "cast_spell" and current_step.card_instance_id is not None:
                card = next((existing for existing in player.hand if existing.instance_id == current_step.card_instance_id), None)
                if card is not None and card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
                    discard_ids = {discard_card.instance_id for discard_card in player.discard_pile}
                    if any(target_id not in discard_ids for target_id in current_step.target_ids):
                        return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("graveyard_target_missing",), invalid_step_index=plan.next_step_index)
                else:
                    for target_id in current_step.target_ids:
                        if engine.get_unit_by_id(target_id) is None:
                            return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("target_no_longer_legal",), invalid_step_index=plan.next_step_index)
        if current_step.required_available_resources > player.available_resources():
            return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("insufficient_resources",), invalid_step_index=plan.next_step_index)
        reserved_total = sum(item.amount for item in plan.resource_reservations)
        if reserved_total > 0 and current_step.action_type in {"to_combat", "declare_attackers"} and player.available_resources() < reserved_total:
            return PlanValidationResult(VALIDATION_STATUS_REPLAN, ("reserved_resources_spent",), invalid_step_index=plan.next_step_index)
        return PlanValidationResult(VALIDATION_STATUS_VALID)

    def ensure_valid_active_air_plan(self, ai, player: PlayerState, engine) -> TurnPlan | None:
        plan = self.get_active_turn_plan(ai)
        if plan is None:
            return None
        validation = self.validate_active_air_plan(ai, player, engine)
        if validation.status == VALIDATION_STATUS_VALID:
            return plan
        if validation.status == VALIDATION_STATUS_COMPLETED:
            self.archive_and_clear_active_turn_plan(ai, validation.reason_codes, status=PLAN_STATUS_COMPLETED)
            return None
        self.archive_and_clear_active_turn_plan(ai, validation.reason_codes, status=PLAN_STATUS_INVALID)
        return None

    def build_air_turn_plan_from_candidate(self, ai, player: PlayerState, engine, candidate: dict) -> TurnPlan:
        plan_id, revision = ai.plan_manager.next_plan_identity()
        hand_by_id = {card.instance_id: card for card in player.hand}
        steps: list[PlanStep] = []
        for resource_card_id in candidate.get("main1_resource_card_ids", ()):
            steps.append(PlanStep(action_type="play_resource", card_instance_id=resource_card_id, expected_phase=PHASE_MAIN_1 if engine.phase == PHASE_MAIN_1 else PHASE_MAIN_2))
        for card_id in candidate.get("sequence", []):
            card = hand_by_id.get(card_id)
            if card is None:
                continue
            action_type = "play_creature" if card.template.card_type == CardType.CREATURE else "cast_spell"
            target_ids: tuple[int, ...] = ()
            if card_id == candidate.get("targeted_card_id") and candidate.get("target_ids"):
                target_ids = tuple(candidate.get("target_ids", ()))
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
                target_ids = tuple(candidate.get("graveyard_target_ids", ()))
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
                target_ids = tuple(candidate.get("bounce_target_ids", ()))
            elif card.template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW:
                target_ids = tuple(candidate.get("himmelswende_target_ids", ()))
            steps.append(
                PlanStep(
                    action_type=action_type,
                    card_instance_id=card_id,
                    target_ids=target_ids,
                    expected_phase=PHASE_MAIN_1 if engine.phase == PHASE_MAIN_1 else PHASE_MAIN_2,
                    required_available_resources=max(0, card.template.resource_cost),
                    expected_recycle_cost=card.template.recycle_cost,
                    reason_codes=tuple(candidate.get("reason_codes", ())),
                )
            )
        if engine.phase == PHASE_MAIN_1 and candidate.get("combat_started"):
            steps.append(PlanStep(action_type="to_combat", expected_phase=PHASE_MAIN_1))
            steps.append(PlanStep(action_type="declare_attackers", expected_phase=None))
        for resource_card_id in candidate.get("main2_resource_card_ids", ()):
            steps.append(PlanStep(action_type="play_resource", card_instance_id=resource_card_id, expected_phase=PHASE_MAIN_2))
        for card_id in candidate.get("main2_sequence", ()):
            card = hand_by_id.get(card_id)
            if card is None:
                continue
            action_type = "play_creature" if card.template.card_type == CardType.CREATURE else "cast_spell"
            target_ids: tuple[int, ...] = ()
            if card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
                target_ids = tuple(candidate.get("main2_graveyard_target_ids", ()))
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
                target_ids = tuple(candidate.get("main2_bounce_target_ids", ()))
            steps.append(
                PlanStep(
                    action_type=action_type,
                    card_instance_id=card_id,
                    target_ids=target_ids,
                    expected_phase=PHASE_MAIN_2,
                    required_available_resources=max(0, card.template.resource_cost),
                    expected_recycle_cost=card.template.recycle_cost,
                    reason_codes=tuple(candidate.get("reason_codes", ())),
                )
            )
        if engine.phase == PHASE_MAIN_2 or candidate.get("combat_started"):
            steps.append(PlanStep(action_type="end_turn", expected_phase=PHASE_MAIN_2))
        reserved_resources = int(candidate.get("reserved_resources", 0))
        reservations: list[ResourceReservation] = []
        if reserved_resources > 0:
            reservations.append(ResourceReservation(amount=reserved_resources, purpose_reason_code="reserves_combat_spell", expected_timing_window=PHASE_REACTION))
        attack = PlannedAttack(attacker_ids=tuple(candidate.get("attacker_ids", ())), expected_damage=candidate.get("expected_attack_damage"), reserved_resources=reserved_resources)
        reaction_intents = tuple(
            ReactionIntent(
                card_instance_id=int(intent["card_instance_id"]),
                allowed_triggers=tuple(intent.get("allowed_triggers", ())),
                condition_reason_code=str(intent.get("condition_reason_code", "")),
                reserved_resources=int(intent.get("reserved_resources", 0)),
                preferred_target_ids=tuple(intent.get("preferred_target_ids", ())),
            )
            for intent in candidate.get("reaction_intents", ())
        )
        return TurnPlan(
            plan_id=plan_id,
            revision=revision,
            player_id=player.player_id,
            turn_number=engine.turn_number,
            created_phase=engine.phase,
            steps=tuple(steps),
            attack=attack,
            reaction_intents=reaction_intents,
            resource_reservations=tuple(reservations),
            strategy_mode=str(candidate.get("strategy_mode", "")),
            primary_goal=str(candidate.get("primary_goal", "")),
            strategy_reason_codes=tuple(candidate.get("strategy_reason_codes", ())),
            strategy_weights=candidate.get("strategy_weights", StrategyWeights()),
            strategy_metrics=tuple(candidate.get("strategy_metrics", ())),
        )

    def choose_attackers_for_player(self, ai, player: PlayerState, engine, creatures: List) -> List:
        if getattr(player, "summoner_key", "") == "fire":
            self.ensure_valid_active_air_plan(ai, player, engine)
            planned_ids = set(self.get_planned_attacker_ids(ai))
            if planned_ids:
                planned = [creature for creature in creatures if creature.unit_id in planned_ids and creature.is_ready()]
                if planned:
                    return planned
            payload = build_fire_turn_plan_payload(
                self,
                ai,
                player,
                engine,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                phase=engine.phase,
            )
            attacker_ids = set(payload.get("attacker_ids", []))
            if attacker_ids:
                self.set_active_turn_plan(ai, self.build_air_turn_plan_from_candidate(ai, player, engine, payload))
                return [creature for creature in creatures if creature.unit_id in attacker_ids and creature.is_ready()]
            return []
        if getattr(player, "summoner_key", "") != "air":
            return ai.choose_attackers(creatures)
        self.ensure_valid_active_air_plan(ai, player, engine)
        planned_ids = set(self.get_planned_attacker_ids(ai))
        if planned_ids:
            planned = [creature for creature in creatures if creature.unit_id in planned_ids and creature.is_ready()]
            if planned:
                return planned
        enemy = engine.players[1 - player.player_id]
        best_plan = ai._estimate_best_air_attack_plan(player, enemy, list(player.hand), [], engine=engine)
        best_ids = set(best_plan.get("attacker_ids", []))
        if best_ids:
            chosen = [creature for creature in creatures if creature.unit_id in best_ids and creature.is_ready()]
            if chosen:
                if len(chosen) < 3:
                    base_score = best_plan.get("score", 0.0)
                    best_extension = None
                    for extra in creatures:
                        if not extra.is_ready() or extra.unit_id in best_ids:
                            continue
                        extended = chosen + [extra]
                        extended_plan = ai._score_air_attack_subset(
                            player,
                            extended,
                            enemy,
                            attack_bonus_target_id=None,
                            attack_bonus_amount=0,
                            hand=list(player.hand),
                            engine=engine,
                        )
                        if len(extended_plan["attacker_ids"]) < 3:
                            continue
                        if extended_plan["score"] < base_score - 0.75:
                            continue
                        if best_extension is None or extended_plan["score"] > best_extension[0]:
                            best_extension = (extended_plan["score"], extended)
                    if best_extension is not None:
                        return best_extension[1]
                return chosen
        return []

    def choose_resource_card_for_main_phase(self, ai, player: PlayerState, engine, phase: str) -> Optional[CardInstance]:
        if player.resources_played_this_turn >= 2 or not player.hand:
            return None
        if getattr(player, "summoner_key", "") == "fire":
            self.ensure_valid_active_air_plan(ai, player, engine)
            planned_step = self.get_active_turn_plan_step(ai, ("play_resource",))
            if planned_step is not None and planned_step.expected_phase == phase:
                return next((card for card in player.hand if card.instance_id == planned_step.card_instance_id), None)
            if self.get_active_turn_plan(ai) is not None:
                return None
            projected_plan = build_fire_turn_plan_payload(
                self,
                ai,
                player,
                engine,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                phase=phase,
            )
            resource_ids = projected_plan.get("main1_resource_card_ids", ()) if phase == PHASE_MAIN_1 else projected_plan.get("main2_resource_card_ids", ())
            if resource_ids:
                self.set_active_turn_plan(ai, self.build_air_turn_plan_from_candidate(ai, player, engine, projected_plan))
                return next((card for card in player.hand if card.instance_id == resource_ids[0]), None)
            return None
        self.ensure_valid_active_air_plan(ai, player, engine)
        planned_step = self.get_active_turn_plan_step(ai, ("play_resource",))
        if planned_step is not None and planned_step.expected_phase == phase:
            return next((card for card in player.hand if card.instance_id == planned_step.card_instance_id), None)
        if self.get_active_turn_plan(ai) is not None:
            return None
        projected_plan = self.build_turn_plan_payload(
            ai,
            player,
            engine,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            phase=phase,
        )
        resource_ids = projected_plan.get("main1_resource_card_ids", ()) if phase == PHASE_MAIN_1 else projected_plan.get("main2_resource_card_ids", ())
        if resource_ids:
            self.set_active_turn_plan(ai, self.build_air_turn_plan_from_candidate(ai, player, engine, projected_plan))
            return next((card for card in player.hand if card.instance_id == resource_ids[0]), None)
        if player.total_resources() == 0:
            emergency_pick = self.select_air_resource_cards(ai, player, engine, 1)
            if emergency_pick:
                return emergency_pick[0]
        return None

    def choose_main_phase_card(self, ai, player: PlayerState, engine) -> Optional[CardInstance]:
        if getattr(player, "summoner_key", "") == "fire":
            self.ensure_valid_active_air_plan(ai, player, engine)
            current_step = self.get_active_turn_plan_step(ai, ("play_creature", "cast_spell"))
            if current_step is not None:
                return next((card for card in player.hand if card.instance_id == current_step.card_instance_id), None)
            if self.get_active_turn_plan(ai) is not None:
                return None
            plan = build_fire_turn_plan_payload(
                self,
                ai,
                player,
                engine,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                phase=engine.phase,
            )
            has_steps = bool(plan["sequence"] or plan.get("main2_sequence") or plan.get("attacker_ids") or plan.get("main1_resource_card_ids"))
            if not has_steps:
                return None
            self.set_active_turn_plan(ai, self.build_air_turn_plan_from_candidate(ai, player, engine, plan))
            next_id = plan["sequence"][0] if plan["sequence"] else None
            return next((card for card in player.hand if card.instance_id == next_id), None)
        if getattr(player, "summoner_key", "") != "air":
            self.clear_active_turn_plan(ai)
            spell = ai.choose_ritual(player, engine)
            if spell is not None:
                return spell
            return ai.choose_playable_creature(player)
        self.ensure_valid_active_air_plan(ai, player, engine)
        current_step = self.get_active_turn_plan_step(ai, ("play_creature", "cast_spell"))
        if current_step is not None:
            return next((card for card in player.hand if card.instance_id == current_step.card_instance_id), None)
        if self.get_active_turn_plan(ai) is not None:
            return None
        plan = self.build_turn_plan_payload(
            ai,
            player,
            engine,
            hand=list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
            phase=engine.phase,
        )
        if not plan["sequence"]:
            if plan.get("attacker_ids"):
                self.set_active_turn_plan(ai, self.build_air_turn_plan_from_candidate(ai, player, engine, plan))
            return None
        self.set_active_turn_plan(ai, self.build_air_turn_plan_from_candidate(ai, player, engine, plan))
        next_id = plan["sequence"][0]
        return next((card for card in player.hand if card.instance_id == next_id), None)

    def get_air_resource_variants(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        phase: str,
    ) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
        max_new_resources = min(2 - player.resources_played_this_turn, len(hand))
        variants: list[tuple[tuple[int, ...], tuple[int, ...]]] = [((), ())]
        if max_new_resources <= 0:
            return variants
        selected_one = tuple(card.instance_id for card in self.select_air_resource_cards(ai, player, engine, 1))
        selected_two = tuple(card.instance_id for card in self.select_air_resource_cards(ai, player, engine, 2))
        if phase == PHASE_MAIN_2:
            if selected_one:
                variants.append(((), selected_one[:1]))
            if len(selected_two) >= 2 and max_new_resources >= 2:
                variants.append(((), selected_two[:2]))
            return variants[:AIR_MAX_RESOURCE_VARIANTS]
        if selected_one:
            variants.append((selected_one[:1], ()))
            variants.append(((), selected_one[:1]))
        if len(selected_two) >= 2 and max_new_resources >= 2:
            variants.append((selected_two[:2], ()))
            variants.append((selected_two[:1], selected_two[1:2]))
            variants.append(((), selected_two[:2]))
        deduped: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        seen: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()
        for variant in variants:
            if variant in seen:
                continue
            seen.add(variant)
            deduped.append(variant)
        return deduped[:AIR_MAX_RESOURCE_VARIANTS]

    def apply_air_resource_gain(
        self,
        *,
        current_resources_played: int,
        resource_count: int,
        available_resources: int,
        total_resources: int,
    ) -> tuple[int, int, bool, bool]:
        gain_available = 0
        first_ready = False
        second_tapped = False
        for offset in range(resource_count):
            if current_resources_played + offset == 0:
                gain_available += 1
                first_ready = True
            else:
                second_tapped = True
        return available_resources + gain_available, total_resources + resource_count, first_ready, second_tapped

    def generate_air_attack_candidates(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        sequence: list[int],
    ) -> list[AttackCandidate]:
        enemy = engine.players[1 - player.player_id]
        projected_attackers = ai._project_air_attackers(player, hand, sequence)
        if not projected_attackers:
            return [AttackCandidate(combat_started=False)]
        subsets: list[tuple[int, ...]] = [()]
        best = ai._estimate_best_air_attack_plan(player, enemy, hand, sequence, engine=engine)
        if best.get("attacker_ids"):
            subsets.append(tuple(best["attacker_ids"]))
        all_ids = tuple(creature.unit_id for creature in projected_attackers)
        subsets.append(all_ids)
        flying_ids = tuple(creature.unit_id for creature in projected_attackers if creature.has_ability(Ability.FLYING))
        if flying_ids:
            subsets.append(flying_ids)
        if len(projected_attackers) <= AIR_MAX_SUBSET_ATTACKERS:
            for mask in range(1, 1 << len(projected_attackers)):
                subset = tuple(
                    projected_attackers[index].unit_id
                    for index in range(len(projected_attackers))
                    if mask & (1 << index)
                )
                if len(subset) >= 3:
                    subsets.append(subset)
        unique_subsets: list[tuple[int, ...]] = []
        seen_subsets: set[tuple[int, ...]] = set()
        for subset in subsets:
            normalized = tuple(sorted(subset))
            if normalized in seen_subsets:
                continue
            seen_subsets.add(normalized)
            unique_subsets.append(subset)
        evaluated: list[AttackCandidate] = []
        for subset in unique_subsets:
            if not subset:
                evaluated.append(
                    AttackCandidate(
                        attacker_ids=(),
                        combat_started=True,
                        expected_counterattack_damage=ai._estimate_enemy_counterattack(player, enemy, attacking_ids=set())["damage"],
                        score=0.0,
                    )
                )
                continue
            chosen = [creature for creature in projected_attackers if creature.unit_id in subset]
            scored = ai._score_air_attack_subset(
                player,
                chosen,
                enemy,
                attack_bonus_target_id=None,
                attack_bonus_amount=0,
                hand=hand,
                engine=engine,
            )
            evaluated.append(
                AttackCandidate(
                    attacker_ids=tuple(scored["attacker_ids"]),
                    expected_damage=int(scored["direct_damage"]),
                    expected_own_losses=int(scored["own_losses"]),
                    expected_enemy_losses=int(scored["enemy_kills"]),
                    expected_counterattack_damage=ai._estimate_enemy_counterattack(
                        player,
                        enemy,
                        attacking_ids=set(scored["attacker_ids"]),
                    )["damage"],
                    combat_started=True,
                    expected_unblocked_attacker_ids=tuple(
                        attacker.unit_id
                        for attacker in chosen
                        if not ai.choose_blockers_for_attackers(chosen, ai._get_probable_blockers(enemy)).get(attacker.unit_id)
                    ),
                    score=float(scored["score"]),
                )
            )
        evaluated.sort(
            key=lambda item: (
                item.score,
                item.expected_damage,
                -item.expected_own_losses,
                len(item.attacker_ids),
                tuple(item.attacker_ids),
            ),
            reverse=True,
        )
        return evaluated[:AIR_MAX_ATTACK_VARIANTS]

    def estimate_air_candidate_counterattack(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        *,
        attack_candidate: AttackCandidate,
        main1_sequence_cards: list[CardInstance],
        main2_sequence_cards: list[CardInstance],
    ) -> int:
        blockers: list[BattlefieldCreature] = [
            creature
            for creature in player.battlefield
            if creature.current_hp > 0 and creature.unit_id not in set(attack_candidate.attacker_ids) and not creature.cannot_block
        ]
        for card in main1_sequence_cards + main2_sequence_cards:
            if card.template.card_type != CardType.CREATURE:
                continue
            created = BattlefieldCreature.from_card(card)
            created.tapped = False
            created.summoning_sick = True
            blockers.append(created)
        enemy_attackers = [creature for creature in enemy.battlefield if creature.current_hp > 0 and creature.is_ready()]
        if not enemy_attackers:
            return 0
        assignments = ai.choose_blockers_for_attackers(enemy_attackers, blockers)
        blockers_by_id = {blocker.unit_id: blocker for blocker in blockers}
        direct_damage = 0
        for attacker in enemy_attackers:
            blocker_id = assignments.get(attacker.unit_id)
            assigned = blockers_by_id.get(blocker_id) if blocker_id is not None else None
            if assigned is None:
                direct_damage += attacker.sw
        return direct_damage

    def evaluate_air_turn_candidate(
        self,
        ai,
        player: PlayerState,
        engine,
        strategy,
        planning_state: PlanningState,
        main1: MainPhaseSequenceCandidate,
        attack: AttackCandidate,
        main2: MainPhaseSequenceCandidate | None,
        *,
        main1_sequence_cards: list[CardInstance],
        main2_sequence_cards: list[CardInstance],
        remaining_end_hand_ids: tuple[int, ...],
        recycle_loss: int,
    ) -> EvaluationBreakdown:
        weights = strategy.weights
        player_damage_value = attack.expected_damage * weights.player_damage
        passive_value = weights.third_attacker if len(attack.attacker_ids) >= 3 else 0.0
        board_value = (len(main1_sequence_cards) + len(main2_sequence_cards)) * 0.45 * weights.board_width
        hand_value = len(remaining_end_hand_ids) * 0.2 * weights.future_playability
        recycle_penalty = recycle_loss * 0.35 * weights.recycle_penalty
        counterattack_penalty = attack.expected_counterattack_damage * 0.55 * weights.counterattack_risk
        total = (
            main1.score
            + attack.score
            + (0.0 if main2 is None else main2.score)
            + player_damage_value
            + passive_value
            + board_value
            + hand_value
            - recycle_penalty
            - counterattack_penalty
        )
        if strategy.mode == "LETHAL" and attack.expected_damage >= engine.players[1 - player.player_id].life:
            total += 12.0
        return EvaluationBreakdown(
            total_score=total,
            player_damage_value=player_damage_value,
            board_value=board_value,
            hand_value=hand_value,
            counterattack_penalty=counterattack_penalty,
            recycle_penalty=recycle_penalty,
            reason_codes=tuple(strategy.reason_codes),
        )

    def build_air_turn_candidate_from_variant(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
        phase: str,
        main1_resource_ids: tuple[int, ...],
        main2_resource_ids: tuple[int, ...],
    ) -> TurnPlanCandidate | None:
        strategy = self.evaluate_strategy(
            ai,
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
            phase=phase,
        )
        hand_by_id = {card.instance_id: card for card in hand}
        current_played = player.resources_played_this_turn
        main1_available, main1_total, first_ready, second_tapped = self.apply_air_resource_gain(
            current_resources_played=current_played,
            resource_count=len(main1_resource_ids),
            available_resources=available_resources,
            total_resources=total_resources,
        )
        main1_hand = [card for card in hand if card.instance_id not in set(main1_resource_ids)]
        main1_plan = self.best_air_main_phase_plan(
            ai,
            player,
            engine,
            main1_hand,
            available_resources=main1_available,
            total_resources=main1_total,
        )
        main1_sequence_ids = tuple(main1_plan["sequence"])
        main1_sequence_cards = [hand_by_id[card_id] for card_id in main1_sequence_ids if card_id in hand_by_id]
        attack_candidates = self.generate_air_attack_candidates(ai, player, engine, main1_hand, list(main1_sequence_ids))
        projected_attackers = ai._project_air_attackers(player, main1_hand, list(main1_sequence_ids))
        combat_started = phase == PHASE_MAIN_1 and bool(projected_attackers)
        main1_remaining_ids = tuple(card.instance_id for card in main1_hand if card.instance_id not in set(main1_sequence_ids))
        best_candidate: TurnPlanCandidate | None = None
        for attack in attack_candidates:
            actual_attack = AttackCandidate(
                attacker_ids=attack.attacker_ids,
                expected_damage=attack.expected_damage,
                expected_own_losses=attack.expected_own_losses,
                expected_enemy_losses=attack.expected_enemy_losses,
                expected_counterattack_damage=attack.expected_counterattack_damage,
                combat_started=combat_started,
                expected_unblocked_attacker_ids=attack.expected_unblocked_attacker_ids,
                reserved_resources=attack.reserved_resources,
                reaction_intent_card_ids=attack.reaction_intent_card_ids,
                score=attack.score,
            )
            main2_candidate: MainPhaseSequenceCandidate | None = None
            main2_sequence_cards: list[CardInstance] = []
            reaction_reserved, reaction_intents = self.build_air_plan_reservations(
                ai,
                player,
                engine,
                [hand_by_id[card_id] for card_id in main1_remaining_ids if card_id in hand_by_id],
                sequence=[],
                ending_available_resources=main1_plan["ending_available_resources"],
                phase=PHASE_MAIN_1 if combat_started else phase,
            )
            if combat_started:
                main2_available, main2_total, main2_first_ready, main2_second_tapped = self.apply_air_resource_gain(
                    current_resources_played=current_played + len(main1_resource_ids),
                    resource_count=len(main2_resource_ids),
                    available_resources=main1_plan["ending_available_resources"],
                    total_resources=main1_plan["ending_total_resources"],
                )
                main2_hand = [
                    hand_by_id[card_id]
                    for card_id in main1_remaining_ids
                    if card_id not in set(main2_resource_ids) and card_id in hand_by_id
                ]
                main2_plan = self.best_air_main_phase_plan(
                    ai,
                    player,
                    engine,
                    main2_hand,
                    available_resources=main2_available,
                    total_resources=main2_total,
                )
                main2_sequence_ids = tuple(main2_plan["sequence"])
                main2_sequence_cards = [hand_by_id[card_id] for card_id in main2_sequence_ids if card_id in hand_by_id]
                main2_remaining_ids = tuple(
                    card.instance_id
                    for card in main2_hand
                    if card.instance_id not in set(main2_sequence_ids)
                )
                main2_candidate = MainPhaseSequenceCandidate(
                    phase=PHASE_MAIN_2,
                    resource_card_ids=main2_resource_ids,
                    card_sequence_ids=main2_sequence_ids,
                    first_resource_ready=main2_first_ready,
                    second_resource_tapped=main2_second_tapped,
                    ending_available_resources=main2_plan["ending_available_resources"],
                    ending_total_resources=main2_plan["ending_total_resources"],
                    projected_hand_ids=main2_remaining_ids,
                    score=float(main2_plan["score"]),
                )
                end_hand_ids = main2_remaining_ids
                end_available = main2_plan["ending_available_resources"]
                end_total = main2_plan["ending_total_resources"]
            else:
                end_hand_ids = main1_remaining_ids
                end_available = main1_plan["ending_available_resources"]
                end_total = main1_plan["ending_total_resources"]
            actual_attack = AttackCandidate(
                attacker_ids=actual_attack.attacker_ids,
                expected_damage=actual_attack.expected_damage,
                expected_own_losses=actual_attack.expected_own_losses,
                expected_enemy_losses=actual_attack.expected_enemy_losses,
                expected_counterattack_damage=self.estimate_air_candidate_counterattack(
                    ai,
                    player,
                    engine.players[1 - player.player_id],
                    attack_candidate=actual_attack,
                    main1_sequence_cards=main1_sequence_cards,
                    main2_sequence_cards=main2_sequence_cards,
                ),
                combat_started=combat_started,
                expected_unblocked_attacker_ids=actual_attack.expected_unblocked_attacker_ids,
                reserved_resources=reaction_reserved,
                reaction_intent_card_ids=tuple(int(intent["card_instance_id"]) for intent in reaction_intents),
                score=actual_attack.score,
            )
            recycle_loss = sum(card.template.recycle_cost for card in main1_sequence_cards + main2_sequence_cards)
            planning_state = PlanningState(
                phase=phase,
                hand_ids=tuple(card.instance_id for card in hand),
                available_resources=available_resources,
                total_resources=total_resources,
                resources_played_this_turn=player.resources_played_this_turn,
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                reserved_resources=reaction_reserved,
                expected_attacker_ids=tuple(actual_attack.attacker_ids),
                expected_own_losses=actual_attack.expected_own_losses,
                expected_enemy_losses=actual_attack.expected_enemy_losses,
            )
            main1_candidate = MainPhaseSequenceCandidate(
                phase=phase,
                resource_card_ids=main1_resource_ids,
                card_sequence_ids=main1_sequence_ids,
                first_resource_ready=first_ready,
                second_resource_tapped=second_tapped,
                ending_available_resources=main1_plan["ending_available_resources"],
                ending_total_resources=main1_plan["ending_total_resources"],
                projected_hand_ids=main1_remaining_ids,
                score=float(main1_plan["score"]),
            )
            breakdown = self.evaluate_air_turn_candidate(
                ai,
                player,
                engine,
                strategy,
                planning_state,
                main1_candidate,
                actual_attack,
                main2_candidate,
                main1_sequence_cards=main1_sequence_cards,
                main2_sequence_cards=main2_sequence_cards,
                remaining_end_hand_ids=end_hand_ids,
                recycle_loss=recycle_loss,
            )
            dead_resource_bonus = self.air_dead_resource_card_bonus(
                ai,
                player,
                engine,
                [hand_by_id[card_id] for card_id in main1_resource_ids if card_id in hand_by_id],
                hand=hand,
            )
            if dead_resource_bonus > 0.0:
                breakdown = EvaluationBreakdown(
                    total_score=breakdown.total_score + dead_resource_bonus,
                    player_damage_value=breakdown.player_damage_value,
                    board_value=breakdown.board_value,
                    hand_value=breakdown.hand_value,
                    counterattack_penalty=breakdown.counterattack_penalty,
                    recycle_penalty=breakdown.recycle_penalty,
                    reason_codes=breakdown.reason_codes,
                )
            reason_codes = list(strategy.reason_codes)
            if len(actual_attack.attacker_ids) >= 3:
                reason_codes.append("enables_third_attacker")
            if reaction_reserved > 0:
                reason_codes.append("reserves_combat_spell")
            if main2_candidate is not None and main2_candidate.card_sequence_ids:
                reason_codes.append("uses_second_main")
            if dead_resource_bonus > 0.0:
                reason_codes.append("converts_dead_card_to_resource")
            candidate = TurnPlanCandidate(
                strategy_mode=strategy.mode,
                primary_goal=strategy.primary_goal,
                strategy_reason_codes=tuple(strategy.reason_codes),
                strategy_weights=strategy.weights,
                strategy_metrics=tuple(strategy.metrics),
                planning_state=planning_state,
                main_1=main1_candidate,
                attack=actual_attack,
                main_2=main2_candidate,
                breakdown=breakdown,
                reaction_intents=tuple(reaction_intents),
                reserved_resources=reaction_reserved,
                expected_end_hand_ids=end_hand_ids,
                expected_end_total_resources=end_total,
                expected_end_available_resources=end_available,
                expected_end_own_creatures=len(player.battlefield) + len([card for card in main1_sequence_cards + main2_sequence_cards if card.template.card_type == CardType.CREATURE]) - actual_attack.expected_own_losses,
                expected_end_enemy_creatures=max(0, len(engine.players[1 - player.player_id].battlefield) - actual_attack.expected_enemy_losses),
                expected_enemy_life=max(0, engine.players[1 - player.player_id].life - actual_attack.expected_damage),
                expected_own_life=player.life,
                recycle_loss=recycle_loss,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
            )
            if best_candidate is None or self.air_turn_candidate_sort_key(candidate) > self.air_turn_candidate_sort_key(best_candidate):
                best_candidate = candidate
        return best_candidate

    def air_turn_candidate_sort_key(self, candidate: TurnPlanCandidate) -> tuple:
        main2_length = 0 if candidate.main_2 is None else len(candidate.main_2.card_sequence_ids)
        cards_used = len(candidate.main_1.card_sequence_ids) + main2_length
        return (
            round(candidate.breakdown.total_score, 4),
            -cards_used,
            -candidate.recycle_loss,
            len(candidate.expected_end_hand_ids),
            candidate.expected_end_total_resources,
            -len(candidate.main_1.resource_card_ids),
            tuple(candidate.main_1.card_sequence_ids),
            tuple(candidate.attack.attacker_ids),
        )

    def candidate_dominates(self, left: TurnPlanCandidate, right: TurnPlanCandidate) -> bool:
        not_worse = (
            left.attack.expected_damage >= right.attack.expected_damage
            and left.expected_end_own_creatures >= right.expected_end_own_creatures
            and len(left.expected_end_hand_ids) >= len(right.expected_end_hand_ids)
            and left.expected_end_total_resources >= right.expected_end_total_resources
            and left.attack.expected_counterattack_damage <= right.attack.expected_counterattack_damage
        )
        strictly_better = (
            left.attack.expected_damage > right.attack.expected_damage
            or left.expected_end_own_creatures > right.expected_end_own_creatures
            or len(left.expected_end_hand_ids) > len(right.expected_end_hand_ids)
            or left.expected_end_total_resources > right.expected_end_total_resources
            or left.attack.expected_counterattack_damage < right.attack.expected_counterattack_damage
        )
        return not_worse and strictly_better

    def filter_air_turn_candidates(self, candidates: list[TurnPlanCandidate]) -> list[TurnPlanCandidate]:
        deduped: list[TurnPlanCandidate] = []
        seen: set[tuple] = set()
        for candidate in sorted(candidates, key=self.air_turn_candidate_sort_key, reverse=True):
            signature = (
                candidate.strategy_mode,
                candidate.main_1.resource_card_ids,
                candidate.main_1.card_sequence_ids,
                candidate.attack.attacker_ids,
                () if candidate.main_2 is None else candidate.main_2.resource_card_ids,
                () if candidate.main_2 is None else candidate.main_2.card_sequence_ids,
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(candidate)
        filtered: list[TurnPlanCandidate] = []
        for candidate in deduped:
            if any(self.candidate_dominates(existing, candidate) for existing in filtered):
                continue
            filtered = [existing for existing in filtered if not self.candidate_dominates(candidate, existing)]
            filtered.append(candidate)
        filtered.sort(key=self.air_turn_candidate_sort_key, reverse=True)
        return filtered[:AIR_MAX_TOTAL_TURN_CANDIDATES]

    def build_turn_candidates(self, ai, player, engine, *, hand, available_resources: int, total_resources: int, phase: str):
        if getattr(player, "summoner_key", "") == "fire":
            return build_fire_turn_candidates(
                self,
                ai,
                player,
                engine,
                hand=hand,
                available_resources=available_resources,
                total_resources=total_resources,
                phase=phase,
            )
        candidates: list[TurnPlanCandidate] = []
        variants = self.get_air_resource_variants(ai, player, engine, hand, phase=phase)
        for main1_resource_ids, main2_resource_ids in variants:
            candidate = self.build_air_turn_candidate_from_variant(
                ai,
                player,
                engine,
                hand,
                available_resources=available_resources,
                total_resources=total_resources,
                phase=phase,
                main1_resource_ids=main1_resource_ids,
                main2_resource_ids=main2_resource_ids,
            )
            if candidate is not None:
                candidates.append(candidate)
        filtered = self.filter_air_turn_candidates(candidates)
        ai._last_air_candidate_stats = {
            "generated": len(candidates),
            "after_filter": len(filtered),
            "variants": len(variants),
        }
        return filtered

    def turn_candidate_to_payload(self, candidate: TurnPlanCandidate) -> dict:
        return {
            "main1_resource_card_ids": list(candidate.main_1.resource_card_ids),
            "sequence": list(candidate.main_1.card_sequence_ids),
            "attacker_ids": list(candidate.attack.attacker_ids),
            "expected_attack_damage": candidate.attack.expected_damage,
            "graveyard_target_ids": [],
            "bounce_target_ids": [],
            "himmelswende_target_ids": [],
            "main2_resource_card_ids": [] if candidate.main_2 is None else list(candidate.main_2.resource_card_ids),
            "main2_sequence": [] if candidate.main_2 is None else list(candidate.main_2.card_sequence_ids),
            "main2_graveyard_target_ids": [],
            "main2_bounce_target_ids": [],
            "reason_codes": tuple(candidate.reason_codes),
            "strategy_mode": candidate.strategy_mode,
            "primary_goal": candidate.primary_goal,
            "strategy_reason_codes": candidate.strategy_reason_codes,
            "strategy_weights": candidate.strategy_weights,
            "strategy_metrics": candidate.strategy_metrics,
            "reserved_resources": candidate.reserved_resources,
            "reaction_intents": candidate.reaction_intents,
            "combat_started": candidate.attack.combat_started,
            "_plan_total": candidate.breakdown.total_score,
        }

    def build_turn_plan_payload(self, ai, player, engine, *, hand, available_resources: int, total_resources: int, phase: str) -> dict:
        if getattr(player, "summoner_key", "") == "fire":
            return build_fire_turn_plan_payload(
                self,
                ai,
                player,
                engine,
                hand=hand,
                available_resources=available_resources,
                total_resources=total_resources,
                phase=phase,
            )
        candidates = self.build_turn_candidates(
            ai,
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
            phase=phase,
        )
        if not candidates:
            strategy = self.evaluate_strategy(
                ai,
                player,
                engine,
                hand=hand,
                available_resources=available_resources,
                total_resources=total_resources,
                phase=phase,
            )
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
        payload = self.turn_candidate_to_payload(candidates[0])
        return self.annotate_air_plan_targets(
            ai,
            player,
            engine,
            hand,
            candidate=payload,
            available_resources=available_resources,
            total_resources=total_resources,
        )

    def build_air_plan_reservations(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        sequence: list[int],
        ending_available_resources: int,
        phase: str,
    ) -> tuple[int, tuple[dict, ...]]:
        if phase != PHASE_MAIN_1 or ending_available_resources <= 0:
            return 0, ()
        strategy = self.evaluate_strategy(
            ai,
            player,
            engine,
            hand=hand,
            available_resources=ending_available_resources,
            total_resources=player.total_resources(),
            phase=phase,
        )
        remaining_ids = set(sequence)
        remaining_hand = [card for card in hand if card.instance_id not in remaining_ids]
        intents: list[dict] = []
        reserved = 0
        for card in remaining_hand:
            effect = card.template.spell_effect
            if effect != SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
                continue
            if card.template.resource_cost > ending_available_resources:
                continue
            if strategy.mode == "STABILIZE":
                continue
            reserved = max(reserved, card.template.resource_cost)
            intents.append(
                {
                    "card_instance_id": card.instance_id,
                    "allowed_triggers": ("COMBAT_START",),
                    "condition_reason_code": "broad_attack_bonus",
                    "reserved_resources": card.template.resource_cost,
                    "preferred_target_ids": (),
                }
            )
        return reserved, tuple(intents)

    def annotate_air_plan_targets(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        candidate: dict,
        available_resources: int,
        total_resources: int,
    ) -> dict:
        if candidate.get("graveyard_target_ids") or candidate.get("bounce_target_ids") or candidate.get("target_ids"):
            return candidate
        hand_by_id = {card.instance_id: card for card in hand}
        for card_id in candidate.get("sequence", []):
            card = hand_by_id.get(card_id)
            if card is None:
                continue
            if card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
                comparison = ai._evaluate_air_bounce_plan(
                    player,
                    engine,
                    card,
                    hand=hand,
                    available_resources=available_resources,
                    total_resources=total_resources,
                )
                if comparison["is_useful"] and comparison.get("target_ids"):
                    candidate["bounce_target_ids"] = list(comparison["target_ids"])
                    candidate["targeted_card_id"] = card.instance_id
                break
        return candidate

    def best_air_main_phase_sequence(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
    ) -> tuple[float, int, int]:
        plan = self.best_air_main_phase_plan(
            ai,
            player,
            engine,
            hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        return plan["score"], plan["ending_total_resources"], len(plan["sequence"])

    def select_air_resource_cards(self, ai, player: PlayerState, engine, count: int) -> list[CardInstance]:
        if count <= 0 or not player.hand:
            return []
        chosen: list[CardInstance] = []
        remaining_hand = list(player.hand)
        projected_available = player.available_resources()
        projected_total = player.total_resources()
        for _ in range(min(count, len(remaining_hand))):
            protected_ids = self.air_current_plan_protected_ids(
                ai,
                player,
                engine,
                remaining_hand,
                available_resources=projected_available,
                total_resources=projected_total,
            )
            duplicate_counts = self.template_counts(remaining_hand)
            scored_cards: list[tuple[tuple[float, int, int, int, int], CardInstance]] = []
            for card in remaining_hand:
                keep_value = self.air_resource_keep_value(
                    ai,
                    player,
                    engine,
                    card,
                    hand=remaining_hand,
                    projected_available_resources=projected_available,
                    projected_total_resources=projected_total,
                    duplicate_count=duplicate_counts.get(card.template.template_id, 1),
                    protected_ids=protected_ids,
                )
                tie_break = (
                    keep_value,
                    0 if duplicate_counts.get(card.template.template_id, 1) > 1 else 1,
                    0 if not self.air_card_has_live_use(ai, player, engine, card, remaining_hand, projected_available, projected_total) else 1,
                    0 if self.air_card_role_is_redundant(card, remaining_hand) else 1,
                    0 if card.template.card_type != CardType.CREATURE else 1,
                )
                scored_cards.append((tie_break, card))
            scored_cards.sort(key=lambda item: item[0])
            unprotected = [item for item in scored_cards if item[1].instance_id not in protected_ids]
            if not unprotected:
                break
            selected = unprotected[0][1]
            chosen.append(selected)
            remaining_hand = [card for card in remaining_hand if card.instance_id != selected.instance_id]
            projected_total += 1
            if len(chosen) == 1 and player.resources_played_this_turn == 0:
                projected_available += 1
        return chosen

    def score_air_resource_count_option(self, ai, player: PlayerState, engine, selected: list[CardInstance]) -> float:
        selected_ids = {card.instance_id for card in selected}
        remaining_hand = [card for card in player.hand if card.instance_id not in selected_ids]
        protected_ids = self.air_current_plan_protected_ids(
            ai,
            player,
            engine,
            list(player.hand),
            available_resources=player.available_resources(),
            total_resources=player.total_resources(),
        )
        projected_available = player.available_resources() + (1 if selected and player.resources_played_this_turn == 0 else 0)
        projected_total = player.total_resources() + len(selected)
        plan = self.best_air_main_phase_plan(
            ai,
            player,
            engine,
            remaining_hand,
            available_resources=projected_available,
            total_resources=projected_total,
        )
        keep_penalty = 0.0
        for card in selected:
            duplicate_count = sum(1 for existing in player.hand if existing.template.template_id == card.template.template_id)
            keep_value = self.air_resource_keep_value(
                ai,
                player,
                engine,
                card,
                hand=list(player.hand),
                projected_available_resources=player.available_resources(),
                projected_total_resources=player.total_resources(),
                duplicate_count=duplicate_count,
                protected_ids=set(),
            )
            keep_penalty += max(
                0.0,
                keep_value,
            )
        score = plan["score"] - keep_penalty * 0.12
        score += self.air_dead_resource_card_bonus(
            ai,
            player,
            engine,
            selected,
            hand=list(player.hand),
        )
        if player.total_resources() == 0:
            if not selected:
                score -= 4.0
            else:
                score += 4.5 + len(selected) * 1.2
            if len(selected) == 2 and len(player.hand) >= 5:
                score += 0.8
        elif player.total_resources() <= 2:
            score += len(selected) * 0.45
        elif player.total_resources() >= 4:
            score -= len(selected) * 0.4
        if len(player.hand) - len(selected) <= 1:
            score -= 1.4
        elif len(player.hand) - len(selected) <= 2 and len(selected) >= 2:
            score -= 0.8
        if any(card.instance_id in protected_ids for card in selected):
            score -= 8.0
        return score

    def air_dead_resource_card_bonus(
        self,
        ai,
        player: PlayerState,
        engine,
        selected: list[CardInstance],
        *,
        hand: list[CardInstance],
    ) -> float:
        if player.total_resources() > 1 or not selected:
            return 0.0
        bonus = 0.0
        for card in selected:
            if card.template.card_type == CardType.CREATURE:
                continue
            duplicate_count = sum(1 for existing in hand if existing.template.template_id == card.template.template_id)
            keep_value = self.air_resource_keep_value(
                ai,
                player,
                engine,
                card,
                hand=hand,
                projected_available_resources=player.available_resources(),
                projected_total_resources=player.total_resources(),
                duplicate_count=duplicate_count,
                protected_ids=set(),
            )
            if keep_value >= 0.0:
                continue
            if self.air_card_has_live_use(
                ai,
                player,
                engine,
                card,
                hand,
                player.available_resources(),
                player.total_resources(),
            ):
                continue
            bonus += min(1.6, 0.6 + abs(keep_value) * 0.25)
        return bonus

    def best_air_main_phase_plan(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
        start_creature_discount: int | None = None,
        start_own_creature_count: int | None = None,
        start_ready_attacker_count: int | None = None,
    ) -> dict:
        enemy = engine.players[1 - player.player_id]

        def search(
            remaining_hand: list[CardInstance],
            remaining_available: int,
            remaining_total: int,
            creature_discount: int,
            own_creature_count: int,
            ready_attacker_count: int,
        ) -> tuple[float, int, int, tuple[int, ...]]:
            best = (0.0, remaining_available, remaining_total, ())
            for index, card in enumerate(remaining_hand):
                play = self.simulate_air_main_phase_play(
                    ai,
                    player,
                    enemy,
                    engine,
                    card,
                    remaining_hand,
                    remaining_available,
                    remaining_total,
                    creature_discount,
                    own_creature_count,
                    ready_attacker_count,
                )
                if play is None:
                    continue
                next_hand = remaining_hand[:index] + remaining_hand[index + 1 :]
                future_score, future_available, future_total, future_sequence = search(
                    next_hand,
                    play["available_resources"],
                    play["total_resources"],
                    play["creature_discount"],
                    play["own_creature_count"],
                    play["ready_attacker_count"],
                )
                total_score = play["value"] + future_score
                candidate_sequence = (card.instance_id,) + future_sequence
                candidate = (total_score, future_available, future_total, candidate_sequence)
                if candidate[0] > best[0] or (
                    candidate[0] == best[0]
                    and (len(candidate[3]), candidate[2], candidate[1]) > (len(best[3]), best[2], best[1])
                ):
                    best = candidate
            return best

        score, ending_available_resources, ending_total_resources, sequence = search(
            hand,
            available_resources,
            total_resources,
            getattr(player, "creature_cost_reduction_this_turn", 0) if start_creature_discount is None else start_creature_discount,
            len(player.battlefield) if start_own_creature_count is None else start_own_creature_count,
            len([creature for creature in player.battlefield if creature.is_ready()]) if start_ready_attacker_count is None else start_ready_attacker_count,
        )
        sequence_cards = [card for card in hand if card.instance_id in sequence]
        return {
            "score": score,
            "ending_available_resources": ending_available_resources,
            "ending_total_resources": ending_total_resources,
            "sequence": list(sequence),
            "cards_played": len(sequence),
            "creatures_played": sum(1 for card in sequence_cards if card.template.card_type == CardType.CREATURE),
            "creature_value": sum(self.air_creature_play_value(ai, card) for card in sequence_cards if card.template.card_type == CardType.CREATURE),
        }

    def simulate_air_main_phase_play(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        engine,
        card: CardInstance,
        hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        creature_discount: int,
        own_creature_count: int,
        ready_attacker_count: int,
    ) -> Optional[dict]:
        template = card.template
        if template.card_type == CardType.CREATURE:
            cost = max(0, template.resource_cost - creature_discount)
            if available_resources < cost or total_resources < template.recycle_cost:
                return None
            value = self.air_creature_play_value(ai, card)
            return {
                "value": value,
                "available_resources": available_resources - cost,
                "total_resources": total_resources - template.recycle_cost,
                "creature_discount": creature_discount,
                "own_creature_count": own_creature_count + 1,
                "ready_attacker_count": ready_attacker_count + (1 if template.has_ability(Ability.HASTE) else 0),
            }
        if template.card_type not in {CardType.RITUAL, CardType.SPELL}:
            return None
        if template.card_type == CardType.SPELL and getattr(template, "spell_timing", None) == SpellTiming.COMBAT:
            return None
        if available_resources < template.resource_cost or total_resources < template.recycle_cost:
            return None
        if not self.air_card_has_live_use(ai, player, engine, card, hand, available_resources, total_resources):
            return None
        remaining_hand = [existing for existing in hand if existing.instance_id != card.instance_id]
        next_available_resources = available_resources - template.resource_cost
        next_total_resources = total_resources - template.recycle_cost
        next_creature_discount = creature_discount
        value = self.air_spell_play_value(
            ai,
            player,
            enemy,
            engine,
            card,
            remaining_hand=remaining_hand,
            available_resources=next_available_resources,
            total_resources=next_total_resources,
            own_creature_count=own_creature_count,
            ready_attacker_count=ready_attacker_count,
            creature_discount=creature_discount,
        )
        if template.spell_effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            next_creature_discount += template.spell_amount
        if template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
            value += 0.8
        return {
            "value": value,
            "available_resources": next_available_resources,
            "total_resources": next_total_resources,
            "creature_discount": next_creature_discount,
            "own_creature_count": own_creature_count,
            "ready_attacker_count": ready_attacker_count,
        }

    def air_creature_play_value(self, ai, card: CardInstance) -> float:
        template = card.template
        value = template.aw * 1.7 + template.vw * 1.3
        if template.has_ability(Ability.HASTE):
            value += 1.4
        if template.has_ability(Ability.FLYING):
            value += 1.0
        if template.return_to_deck_end_of_turn:
            value += 0.7
        if template.cannot_block:
            value -= 0.8
        if template.recycle_cost > 0:
            value += 0.2
        if template.all_attackers_die_bonus > 0:
            value += 2.2
        if template.draw_on_play > 0:
            value += template.draw_on_play * 2.0
        if template.draw_on_attack > 0:
            value += template.draw_on_attack * 1.5
        if template.draw_on_death > 0:
            value += template.draw_on_death * 1.2
        if getattr(template, "draw_on_player_damage", 0) > 0:
            value += template.draw_on_player_damage * 1.8
        if getattr(template, "tap_enemy_creature_on_play", 0) > 0:
            value += template.tap_enemy_creature_on_play * 1.5
        if getattr(template, "return_other_own_haste_on_combat_death", False):
            value += 2.3
        if getattr(template, "own_flying_attack_aura", 0) > 0:
            value += template.own_flying_attack_aura * 2.6
        return value

    def air_spell_play_value(
        self,
        ai,
        player: PlayerState,
        enemy: PlayerState,
        engine,
        card: CardInstance,
        *,
        remaining_hand: list[CardInstance],
        available_resources: int,
        total_resources: int,
        own_creature_count: int,
        ready_attacker_count: int,
        creature_discount: int,
    ) -> float:
        effect = card.template.spell_effect
        handler = ai._get_air_card_handler(card)
        if handler is not None:
            specialized = handler.play_value(
                ai,
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            if specialized is not None:
                return specialized
        if effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            comparison = ai._evaluate_air_cost_reduction_support_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
            comparison = ai._evaluate_air_windruf_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.DISCARD_HAND_AND_DRAW:
            comparison = ai._evaluate_air_sturmruf_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
                own_creature_count=own_creature_count,
                ready_attacker_count=ready_attacker_count,
                creature_discount=creature_discount,
            )
            return comparison["value"]
        if effect == SpellEffect.RETURN_CREATURES_TO_HAND:
            comparison = ai._evaluate_air_bounce_plan(
                player,
                engine,
                card,
                hand=[card] + remaining_hand,
                available_resources=available_resources + card.template.resource_cost,
                total_resources=total_resources + card.template.recycle_cost,
            )
            return comparison["value"]
        if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
            return 0.0
        return 0.5

    def air_resource_keep_value(
        self,
        ai,
        player: PlayerState,
        engine,
        card: CardInstance,
        *,
        hand: list[CardInstance],
        projected_available_resources: int,
        projected_total_resources: int,
        duplicate_count: int,
        protected_ids: set[int],
    ) -> float:
        template = card.template
        enemy = engine.players[1 - player.player_id]
        value = 0.0
        next_turn_resources = projected_total_resources + 1
        if card.instance_id in protected_ids:
            value += 8.5
        if template.card_type == CardType.CREATURE:
            value += 3.2 + self.air_creature_play_value(ai, card)
            if projected_available_resources >= template.resource_cost and projected_total_resources >= template.recycle_cost:
                value += 2.8
            elif template.resource_cost == projected_total_resources + 1:
                value += 1.8
            elif template.resource_cost <= next_turn_resources:
                value += 1.2
            else:
                value -= 0.4 * max(0, template.resource_cost - next_turn_resources)
            projected_remaining_resources = projected_total_resources - template.recycle_cost
            if template.recycle_cost > 0:
                if projected_remaining_resources >= 3:
                    value += 0.8
                elif projected_remaining_resources == 2:
                    value += 0.2
                else:
                    value -= 1.3 + (2 - projected_remaining_resources) * 0.8
            creatures_in_hand = sum(1 for hand_card in hand if hand_card.template.card_type == CardType.CREATURE)
            if creatures_in_hand == 1:
                value += 4.0
            if not player.battlefield:
                value += 1.1
            if template.resource_cost >= 5 and template.recycle_cost > 0 and projected_total_resources >= 4:
                value += 2.8
            value += ai._air_specific_creature_keep_adjustment(
                player,
                enemy,
                card,
                hand,
                projected_available_resources=projected_available_resources,
                projected_total_resources=projected_total_resources,
            )
        else:
            has_live_use = self.air_card_has_live_use(
                ai,
                player,
                engine,
                card,
                hand,
                projected_available_resources,
                projected_total_resources,
            )
            if has_live_use:
                value += self.air_spell_play_value(
                    ai,
                    player,
                    enemy,
                    engine,
                    card,
                    remaining_hand=[hand_card for hand_card in hand if hand_card.instance_id != card.instance_id],
                    available_resources=projected_available_resources,
                    total_resources=projected_total_resources,
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                ) + 1.2
            else:
                value -= 2.0
            if projected_available_resources >= template.resource_cost and projected_total_resources >= template.recycle_cost:
                value += 0.9
            elif template.resource_cost <= next_turn_resources:
                value += 0.6
            if template.resource_cost == 0 and template.recycle_cost > 0:
                value += 1.4 if engine.creatures_died_this_turn > 0 else -0.6
            value += ai._air_specific_spell_keep_adjustment(
                player,
                enemy,
                engine,
                card,
                hand,
                projected_available_resources=projected_available_resources,
                projected_total_resources=projected_total_resources,
            )
        if duplicate_count > 1:
            value -= 1.2 * (duplicate_count - 1)
        if self.air_card_role_is_redundant(card, hand):
            value -= 0.7
        return value

    def template_counts(self, cards: list[CardInstance]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for card in cards:
            counts[card.template.template_id] = counts.get(card.template.template_id, 0) + 1
        return counts

    def air_current_plan_protected_ids(
        self,
        ai,
        player: PlayerState,
        engine,
        hand: list[CardInstance],
        *,
        available_resources: int,
        total_resources: int,
    ) -> set[int]:
        plan = self.best_air_main_phase_plan(
            ai,
            player,
            engine,
            hand,
            available_resources=available_resources,
            total_resources=total_resources,
        )
        protected_ids = set(plan["sequence"])
        enemy = engine.players[1 - player.player_id]
        if not player.battlefield:
            playable_creatures = [
                card for card in hand
                if card.template.card_type == CardType.CREATURE
                and available_resources >= card.template.resource_cost
                and total_resources >= card.template.recycle_cost
            ]
            if len(playable_creatures) == 1:
                protected_ids.add(playable_creatures[0].instance_id)
        lethal_card = ai._find_air_lethal_enabler(player, enemy, hand)
        if lethal_card is not None:
            protected_ids.add(lethal_card.instance_id)
        answer_card = ai._find_air_only_answer_card(player, enemy, engine, hand)
        if answer_card is not None:
            protected_ids.add(answer_card.instance_id)
        if engine.phase == PHASE_MAIN_1 and any(creature.is_ready() for creature in player.battlefield):
            for card in hand:
                if (
                    card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT
                    and available_resources >= card.template.resource_cost
                    and total_resources >= card.template.recycle_cost
                ):
                    protected_ids.add(card.instance_id)
        return protected_ids

    def air_card_has_live_use(
        self,
        ai,
        player: PlayerState,
        engine,
        card: CardInstance,
        hand: list[CardInstance],
        projected_available_resources: int,
        projected_total_resources: int,
    ) -> bool:
        template = card.template
        if template.card_type == CardType.CREATURE:
            return projected_available_resources >= template.resource_cost and projected_total_resources >= template.recycle_cost
        handler = ai._get_air_card_handler(card)
        if handler is not None:
            specialized = handler.has_live_use(
                ai,
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            if specialized is not None:
                return specialized
        if template.spell_effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
            comparison = ai._evaluate_air_cost_reduction_support_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
            comparison = ai._evaluate_air_windruf_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW:
            comparison = ai._evaluate_air_sturmruf_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
                own_creature_count=len(player.battlefield),
                ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
            )
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
            comparison = ai._evaluate_air_bounce_plan(
                player,
                engine,
                card,
                hand=hand,
                available_resources=projected_available_resources,
                total_resources=projected_total_resources,
            )
            return comparison["is_useful"]
        if template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
            return (
                projected_available_resources >= template.resource_cost
                and projected_total_resources >= template.recycle_cost
                and engine.phase == PHASE_MAIN_1
                and any(creature.is_ready() for creature in player.battlefield)
            )
        return ai.has_valid_spell_targets(player, engine, card)

    def air_card_role_is_redundant(self, card: CardInstance, hand: list[CardInstance]) -> bool:
        template = card.template
        if sum(1 for hand_card in hand if hand_card.template.template_id == template.template_id) > 1:
            return True
        if template.card_type == CardType.CREATURE:
            same_cost_creatures = [
                hand_card for hand_card in hand
                if hand_card.instance_id != card.instance_id
                and hand_card.template.card_type == CardType.CREATURE
                and hand_card.template.resource_cost == template.resource_cost
                and hand_card.template.aw + hand_card.template.vw >= template.aw + template.vw
            ]
            return bool(same_cost_creatures)
        return False

    def distance_to_reasonable_play(self, card: CardInstance, projected_total_resources: int) -> int:
        return max(0, card.template.resource_cost - projected_total_resources)

    def count_discounted_creature_lines(self, hand: list[CardInstance], available_resources: int, total_resources: int) -> int:
        count = 0
        creatures = [card for card in hand if card.template.card_type == CardType.CREATURE]
        for creature in creatures:
            reduced_cost = max(0, creature.template.resource_cost - 1)
            if available_resources >= reduced_cost and total_resources >= creature.template.recycle_cost:
                count += 1
        return count
