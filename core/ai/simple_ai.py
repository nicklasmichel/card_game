from __future__ import annotations

from dataclasses import replace
from random import Random

from core.ai.air.registry import get_air_card_handler, get_air_creature_handler
from core.ai.fire.assessment import build_fire_snapshot
from core.ai.fire.planning import build_fire_turn_candidates, build_fire_turn_plan_payload
from core.ai.fire.reactions import choose_fire_reaction_spell, choose_fire_spell_target_ref
from core.ai.assessment_component import AssessmentComponent
from core.ai.common import CommonAIMixin
from core.ai.effect_evaluator_component import EffectEvaluatorComponent
from core.ai.plan_manager import PlanManager
from core.ai.reaction_planner import ReactionPlanner
from core.ai.strategy_registry import StrategyRegistry
from core.ai.turn_planner import TurnPlanner
from core.models import Ability, BattlefieldCreature, CardInstance, CardType, PHASE_MAIN_1, PlayerState, SpellEffect


class HeuristicStrategicAI(CommonAIMixin):
    def __init__(self, rng: Random) -> None:
        self.rng = rng
        self.plan_manager = PlanManager()
        self.strategy_registry = StrategyRegistry()
        self.turn_planner = TurnPlanner()
        self.reaction_planner = ReactionPlanner()
        self.assessment = AssessmentComponent()
        self.effect_evaluator = EffectEvaluatorComponent()
        self._last_air_candidate_stats: dict[str, int] = {}

    @property
    def _last_turn_plan(self):
        return self.plan_manager.last_turn_plan

    def _get_air_card_handler(self, card):
        return get_air_card_handler(card.template.template_id)

    def _get_air_card_handler_by_template_id(self, template_id: str):
        return get_air_card_handler(template_id)

    def _get_air_creature_handler(self, card):
        return get_air_creature_handler(card.template.template_id)

    def _get_air_creature_handler_by_template_id(self, template_id: str):
        return get_air_creature_handler(template_id)

    def _current_strategy(self, player, engine):
        return self.strategy_registry.resolve(getattr(player, "summoner_key", ""))

    def prepare_next_action(self, player, engine):
        if getattr(player, "summoner_key", "") == "air":
            return self.turn_planner.build_turn_plan_payload(
                self,
                player,
                engine,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                phase=engine.phase,
            )
        if getattr(player, "summoner_key", "") == "fire":
            return build_fire_turn_plan_payload(
                self.turn_planner,
                self,
                player,
                engine,
                hand=list(player.hand),
                available_resources=player.available_resources(),
                total_resources=player.total_resources(),
                phase=engine.phase,
            )
        return None

    def notify_action_resolved(self, action_type: str, *, card_instance_id: int | None = None) -> None:
        self._mark_turn_plan_step_completed(action_type, card_instance_id=card_instance_id)

    def reset_for_turn(self) -> None:
        self.turn_planner.clear_active_turn_plan(self)

    def choose_attackers_for_player(self, player, engine, creatures):
        if getattr(player, "summoner_key", "") == "air":
            return self.turn_planner.choose_attackers_for_player(self, player, engine, creatures)
        if getattr(player, "summoner_key", "") == "fire":
            return self.turn_planner.choose_attackers_for_player(self, player, engine, creatures)
        return CommonAIMixin.choose_attackers_for_player(self, player, engine, creatures)

    def choose_resource_card_for_main_phase(self, player, engine, phase):
        if getattr(player, "summoner_key", "") == "air":
            return self.turn_planner.choose_resource_card_for_main_phase(self, player, engine, phase)
        if getattr(player, "summoner_key", "") == "fire":
            return self.turn_planner.choose_resource_card_for_main_phase(self, player, engine, phase)
        return CommonAIMixin.choose_resource_card_for_main_phase(self, player, engine, phase)

    def choose_resource_cards_to_play(self, player: PlayerState, engine) -> list[CardInstance]:
        if getattr(player, "summoner_key", "") != "air":
            chosen = self.choose_resource_card(player)
            return [] if chosen is None else [chosen]
        best_choice: list[CardInstance] = []
        best_score = float("-inf")
        max_count = min(2 - player.resources_played_this_turn, len(player.hand))
        for count in range(max_count + 1):
            selected = self.turn_planner.select_air_resource_cards(self, player, engine, count)
            score = self.turn_planner.score_air_resource_count_option(self, player, engine, selected)
            if score > best_score + 0.01 or (abs(score - best_score) <= 0.01 and len(selected) < len(best_choice)):
                best_score = score
                best_choice = selected
        return best_choice

    def choose_main_phase_card(self, player, engine):
        if getattr(player, "summoner_key", "") == "air":
            return self.turn_planner.choose_main_phase_card(self, player, engine)
        if getattr(player, "summoner_key", "") == "fire":
            return self.turn_planner.choose_main_phase_card(self, player, engine)
        return self.choose_ritual(player, engine) or self.choose_playable_creature(player)

    def choose_cards_to_discard(self, player: PlayerState, engine, count: int, source_card_name: str = ""):
        if count <= 0 or not player.hand:
            return []
        if getattr(player, "summoner_key", "") == "air":
            chosen: list[CardInstance] = []
            remaining_hand = list(player.hand)
            for _ in range(min(count, len(remaining_hand))):
                protected_ids = self.turn_planner.air_current_plan_protected_ids(
                    self,
                    player,
                    engine,
                    remaining_hand,
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                )
                duplicate_counts = self.turn_planner.template_counts(remaining_hand)
                scored_cards: list[tuple[tuple[float, int, int, int, int], CardInstance]] = []
                for card in remaining_hand:
                    keep_value = self.turn_planner.air_resource_keep_value(
                        self,
                        player,
                        engine,
                        card,
                        hand=remaining_hand,
                        projected_available_resources=player.available_resources(),
                        projected_total_resources=player.total_resources(),
                        duplicate_count=duplicate_counts.get(card.template.template_id, 1),
                        protected_ids=protected_ids,
                    )
                    tie_break = (
                        keep_value,
                        0 if duplicate_counts.get(card.template.template_id, 1) > 1 else 1,
                        0 if not self.turn_planner.air_card_has_live_use(self, player, engine, card, remaining_hand, player.available_resources(), player.total_resources()) else 1,
                        0 if self.turn_planner.air_card_role_is_redundant(card, remaining_hand) else 1,
                        0 if card.template.card_type != CardType.CREATURE else 1,
                    )
                    scored_cards.append((tie_break, card))
                scored_cards.sort(key=lambda item: item[0])
                selected = scored_cards[0][1]
                chosen.append(selected)
                remaining_hand = [card for card in remaining_hand if card.instance_id != selected.instance_id]
            return chosen
        return sorted(
            player.hand,
            key=lambda card: (
                card.template.cost.total_value,
                card.template.aw + card.template.vw,
                len(card.template.abilities),
            ),
        )[:count]

    def choose_playable_creature(self, player: PlayerState):
        playable = [
            card
            for card in player.hand
            if card.template.card_type == CardType.CREATURE and player.can_pay(card.template.cost)
        ]
        if not playable:
            return None
        return max(
            playable,
            key=lambda card: (
                card.template.aw + card.template.vw + len(card.template.abilities) * 2 - card.template.recycle_cost,
                -card.template.recycle_cost,
                card.template.resource_cost,
            ),
        )

    def choose_ritual(self, player: PlayerState, engine):
        candidates = [
            card
            for card in player.hand
            if card.template.card_type in {CardType.RITUAL, CardType.SPELL} and engine.can_play_card(player, card)
            and self.has_valid_spell_targets(player, engine, card)
        ]
        if not candidates:
            return None
        scored: list[tuple[tuple[int, int, int], CardInstance]] = []
        for card in candidates:
            score = (0, 0, -card.template.resource_cost)
            handler = self._get_air_card_handler(card)
            if handler is not None:
                specialized_score = handler.score_ritual(self, player, engine, card)
                if specialized_score is not None:
                    scored.append((specialized_score, card))
                    continue
            if card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE:
                killable = [creature for creature in engine.human_player.battlefield if creature.current_hp <= card.template.spell_amount]
                score = (2 if killable else 0, len(killable), -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER:
                lethal = 1 if engine.human_player.life <= card.template.spell_amount else 0
                threatening = max((creature.aw for creature in engine.human_player.battlefield), default=0)
                score = (3 if lethal else 1, threatening, engine.human_player.life)
            elif card.template.spell_effect == SpellEffect.DEAL_DAMAGE_TO_ALL_ENEMY_CREATURES:
                affected = len(engine.human_player.battlefield)
                score = (2 if affected >= 2 else 0, affected, 0)
            elif card.template.spell_effect == SpellEffect.SACRIFICE_FOR_DAMAGE:
                if not player.battlefield:
                    continue
                cheap = min((creature.aw + creature.current_hp for creature in player.battlefield), default=99)
                score = (1, -cheap, 0)
            elif card.template.spell_effect == SpellEffect.DRAW_AND_SELF_DAMAGE:
                score = (1 if player.life > 2 else -10, len(player.hand), 0)
            elif card.template.spell_effect == SpellEffect.REDUCE_CREATURE_COST_THIS_TURN:
                comparison = self._evaluate_air_cost_reduction_support_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                score = (2 if comparison["is_useful"] else -2, int(comparison["value"] * 10), -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
                valid_targets = engine.get_valid_discard_creature_target_refs(player)
                score = (2 if len(valid_targets) >= card.template.spell_amount else -10, len(valid_targets), -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW:
                score = (2 if len(player.deck) >= card.template.spell_draw_count and len(player.hand) <= 2 else -2, card.template.spell_draw_count - len(player.hand), -card.template.recycle_cost)
            elif card.template.spell_effect == SpellEffect.RETURN_CREATURES_TO_HAND:
                total_targets = len(player.battlefield) + len(engine.human_player.battlefield)
                score = (1 if total_targets >= card.template.spell_amount else -10, len(engine.human_player.battlefield), -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
                attacker_count = len(engine.get_current_attacker_creatures(player))
                score = (2 if attacker_count > 0 else -10, attacker_count * card.template.spell_amount, -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN:
                useful_targets = [creature for creature in player.battlefield if creature.current_hp > 0]
                score = (1 if useful_targets else -5, len(useful_targets), 0)
            elif card.template.spell_effect == SpellEffect.DRAW_TWO_THEN_DISCARD_ONE:
                score = (2 if len(player.deck) >= card.template.spell_draw_count else -10, len(player.hand), 0)
            elif card.template.spell_effect == SpellEffect.DISCARD_HAND_AND_DRAW_THREE:
                comparison = self._evaluate_air_sturmruf_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                score = (2 if comparison["is_useful"] else -2, int(comparison["value"] * 10), -card.template.resource_cost)
            elif card.template.spell_effect == SpellEffect.RETURN_TWO_CREATURES_TO_HAND:
                comparison = self._evaluate_air_himmelswende_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                    own_creature_count=len(player.battlefield),
                    ready_attacker_count=len([creature for creature in player.battlefield if creature.is_ready()]),
                    creature_discount=getattr(player, "creature_cost_reduction_this_turn", 0),
                )
                score = (
                    2 if comparison["is_useful"] else -2,
                    int(comparison["value"] * 10),
                    1 if any(
                        engine.get_unit_owner(target_id) == engine.human_player
                        for target_id in comparison.get("target_ids", [])
                        if engine.get_unit_by_id(target_id) is not None
                    ) else 0,
                )
            elif card.template.spell_effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
                battle = engine.pending_dice_battle
                threatened = 0
                if battle is not None:
                    own_unit = engine.get_unit_by_id(battle.attacker_id if battle.attacker_owner == player.player_id else battle.blocker_id)
                    threatened = 2 if own_unit is not None and own_unit.current_hp <= 1 else 1
                score = (threatened, 0, 0)
            elif card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_ATTACKER_THIS_COMBAT:
                comparison = self._evaluate_air_jagdwind_reaction_plan(player, engine, card)
                score = (2 if comparison["is_useful"] else 0, int(comparison["value"] * 10), 0)
            elif card.template.spell_effect == SpellEffect.DRAW_PER_DEATH_THIS_TURN:
                comparison = self._evaluate_air_orkanwende_plan(
                    player,
                    engine,
                    card,
                    hand=list(player.hand),
                    available_resources=player.available_resources(),
                    total_resources=player.total_resources(),
                )
                score = (2 if comparison["is_useful"] else 0, int(comparison["value"] * 10), 0)
            scored.append((score, card))
        return max(scored, key=lambda item: item[0])[1] if scored else None

    def choose_sacrifice_creature(self, player: PlayerState, engine, card: CardInstance):
        if not player.battlefield:
            return None
        return min(
            player.battlefield,
            key=lambda creature: (
                creature.current_hp,
                creature.aw + creature.vw,
                len(creature.abilities),
            ),
        )

    def choose_tailwind_ability(self, creature: BattlefieldCreature):
        if creature is not None and not creature.has_ability(Ability.FLYING):
            return Ability.FLYING
        return Ability.HASTE

    def choose_global_attack_bonus_mode(self, player: PlayerState, engine, card: CardInstance):
        if card.template.template_id == "air_spell_sturmjagd":
            comparison = self._evaluate_air_sturmjagd_reaction_plan(player, engine, card)
        else:
            comparison = self._evaluate_air_jagdwind_reaction_plan(player, engine, card)
        return comparison.get("selected_mode")

    def choose_spell(self, hand, engine):
        if getattr(engine.ai_player, "summoner_key", "") == "fire":
            return choose_fire_reaction_spell(self, hand, engine)
        return self.reaction_planner.choose_spell(self, hand, engine)

    def choose_spell_target_ref(self, player, engine, card, pending):
        if getattr(player, "summoner_key", "") == "fire":
            return choose_fire_spell_target_ref(self, player, engine, card, pending)
        return self.reaction_planner.choose_spell_target_ref(self, player, engine, card, pending)

    def _evaluate_fire_strategy(self, player, engine, *, hand=None, available_resources: int | None = None, total_resources: int | None = None, phase: str | None = None):
        return self.strategy_registry.resolve("fire").evaluate(
            self,
            player,
            engine,
            hand=list(player.hand) if hand is None else list(hand),
            available_resources=player.available_resources() if available_resources is None else available_resources,
            total_resources=player.total_resources() if total_resources is None else total_resources,
            phase=engine.phase if phase is None else phase,
        )

    def _build_fire_snapshot(self, player, engine, *, hand=None, available_resources: int | None = None, total_resources: int | None = None, phase: str | None = None):
        return build_fire_snapshot(
            self,
            player,
            engine,
            hand=list(player.hand) if hand is None else list(hand),
            available_resources=player.available_resources() if available_resources is None else available_resources,
            total_resources=player.total_resources() if total_resources is None else total_resources,
            phase=engine.phase if phase is None else phase,
        )

    def _air_template_is_generally_draw_worthy(self, player, engine, template, hand, *, available_resources: int, total_resources: int):
        return self.assessment.template_is_generally_draw_worthy(
            self, player, engine, template, hand, available_resources=available_resources, total_resources=total_resources
        )

    def _air_template_improves_weak_hand(self, player, engine, template, hand, *, available_resources: int, total_resources: int):
        return self.assessment.template_improves_weak_hand(
            self, player, engine, template, hand, available_resources=available_resources, total_resources=total_resources
        )

    def _air_reaction_hold_advantage(self, player, engine, hand, with_support, without_support):
        return self.assessment.reaction_hold_advantage(self, player, engine, hand, with_support, without_support)

    def _has_plausible_air_combat_reaction(self, player, engine, hand, available_resources: int):
        return self.assessment.has_plausible_combat_reaction(self, player, engine, hand, available_resources)

    def _estimate_best_air_attack_plan(self, player, enemy, hand, sequence, *, engine=None, attack_bonus_amount: int = 0):
        return self.assessment.estimate_best_attack_plan(
            self, player, enemy, hand, sequence, engine=engine, attack_bonus_amount=attack_bonus_amount
        )

    def _project_air_attackers(self, player: PlayerState, hand: list[CardInstance], sequence: list[int]) -> list[BattlefieldCreature]:
        attackers = [creature for creature in player.battlefield if creature.current_hp > 0 and creature.is_ready()]
        hand_by_id = {card.instance_id: card for card in hand}
        for card_id in sequence:
            card = hand_by_id.get(card_id)
            if card is None or card.template.card_type != CardType.CREATURE or not card.template.has_ability(Ability.HASTE):
                continue
            attackers.append(BattlefieldCreature.from_card(card))
        return attackers

    def _clone_attack_creature(self, creature: BattlefieldCreature, attack_bonus: int = 0) -> BattlefieldCreature:
        return replace(
            creature,
            aw=creature.aw + attack_bonus,
            temporary_aw_bonus=creature.temporary_aw_bonus + attack_bonus,
            temporary_abilities=set(creature.temporary_abilities),
        )

    def _get_probable_blockers(self, player: PlayerState) -> list[BattlefieldCreature]:
        return [
            creature
            for creature in player.battlefield
            if creature.current_hp > 0 and creature.is_ready() and not creature.cannot_block
        ]

    def _score_air_bounce_target(self, player: PlayerState, engine, creature: BattlefieldCreature) -> float:
        owner = engine.get_unit_owner(creature.unit_id)
        enemy = engine.players[1 - player.player_id]
        is_enemy = owner == enemy
        base_value = creature.cost.resources * 0.9 + creature.cost.recycle * 0.7 + creature.aw * 0.35 + creature.current_hp * 0.3
        if is_enemy:
            score = 2.0 + base_value
            current_attackers = {attacker.unit_id for attacker in engine.get_current_attacker_creatures(owner, getattr(engine, "reaction_context", None))}
            if creature.unit_id in current_attackers:
                score += 1.6
            attacker_pressure = sum(1 for blocker_id in engine.block_assignments.values() if blocker_id == creature.unit_id)
            if attacker_pressure > 0:
                score += 1.8 + attacker_pressure * 0.8
            if creature.has_ability(Ability.FLYING):
                score += 0.6
            return score
        score = -0.8 + creature.aw * 0.15 + creature.current_hp * 0.1
        if creature.current_hp < creature.lw:
            score += 2.0
        if creature.has_ability(Ability.HASTE):
            score += 0.7
        if creature.unit_id in engine.block_assignments:
            score += 1.2
        return score

    def _score_air_attack_subset(self, player, attackers, enemy, *, attack_bonus_target_id, attack_bonus_amount, hand=None, engine=None):
        return self.assessment.score_attack_subset(
            self,
            player,
            attackers,
            enemy,
            attack_bonus_target_id=attack_bonus_target_id,
            attack_bonus_amount=attack_bonus_amount,
            hand=hand,
            engine=engine,
        )

    def _estimate_enemy_counterattack(self, player, enemy, *, attacking_ids):
        return self.assessment.estimate_enemy_counterattack(self, player, enemy, attacking_ids=attacking_ids)

    def _count_probable_attackers(self, player, hand):
        return self.assessment.count_probable_attackers(self, player, hand)

    def _find_probable_unblocked_damage(self, player, enemy, hand):
        return self.assessment.find_probable_unblocked_damage(self, player, enemy, hand)

    def _count_unblockable_haste_attackers(self, player, enemy, hand):
        return self.assessment.count_unblockable_haste_attackers(self, player, enemy, hand)

    def _generic_air_creature_keep_adjustment(self, player, enemy, card, hand, *, projected_available_resources: int, projected_total_resources: int):
        return self.assessment.generic_creature_keep_adjustment(
            self,
            player,
            enemy,
            card,
            hand,
            projected_available_resources=projected_available_resources,
            projected_total_resources=projected_total_resources,
        )

    def _find_air_lethal_enabler(self, player, enemy, hand):
        return self.assessment.find_lethal_enabler(self, player, enemy, hand)

    def _find_air_only_answer_card(self, player, enemy, engine, hand):
        return self.assessment.find_only_answer_card(self, player, enemy, engine, hand)

    def _air_specific_creature_keep_adjustment(self, player, enemy, card, hand, *, projected_available_resources: int, projected_total_resources: int):
        return self.assessment.specific_creature_keep_adjustment(
            self,
            player,
            enemy,
            card,
            hand,
            projected_available_resources=projected_available_resources,
            projected_total_resources=projected_total_resources,
        )

    def _air_specific_spell_keep_adjustment(self, player, enemy, engine, card, hand, *, projected_available_resources: int, projected_total_resources: int):
        return self.assessment.specific_spell_keep_adjustment(
            self,
            player,
            enemy,
            engine,
            card,
            hand,
            projected_available_resources=projected_available_resources,
            projected_total_resources=projected_total_resources,
        )

    def _evaluate_air_cost_reduction_support_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_cost_reduction_support_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_attack_bonus_support_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_attack_bonus_support_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_jagdwind_reaction_plan(self, player, engine, card):
        return self.effect_evaluator.evaluate_jagdwind_reaction_plan(self, player, engine, card)

    def _evaluate_air_sturmjagd_reaction_plan(self, player, engine, card):
        return self.effect_evaluator.evaluate_sturmjagd_reaction_plan(self, player, engine, card)

    def _evaluate_air_orkanwende_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_orkanwende_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_windruf_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_windruf_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_sturmruf_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_sturmruf_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_himmelswende_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_himmelswende_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_bounce_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_bounce_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_verwehung_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_verwehung_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_hand_reset_plan(self, player, engine, card, **kwargs):
        return self.effect_evaluator.evaluate_hand_reset_plan(self, player, engine, card, **kwargs)

    def _evaluate_air_global_attack_bonus_reaction_plan(self, player, engine, card):
        return self.effect_evaluator.evaluate_global_attack_bonus_reaction_plan(self, player, engine, card)

    def _score_air_graveyard_creature_target(
        self,
        player,
        engine,
        discard_card,
        *,
        available_resources: int,
        total_resources: int,
        creature_discount: int = 0,
    ) -> float:
        template = discard_card.template
        resource_gap = max(0, template.resource_cost - creature_discount - available_resources)
        score = template.aw + template.vw * 0.8 + len(template.abilities) * 1.2
        if template.has_ability(Ability.HASTE):
            score += 2.2
        if template.has_ability(Ability.FLYING):
            score += 1.8
        if resource_gap == 0:
            score += 2.0
        else:
            score -= resource_gap * 1.1
        if total_resources + creature_discount < template.resource_cost:
            score -= 0.8
        return score

    def _evaluate_air_strategy(self, player, engine, *, hand=None, available_resources: int | None = None, total_resources: int | None = None, phase: str | None = None):
        return self.turn_planner.evaluate_strategy(
            self,
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
            phase=phase,
        )

    def _air_strategy_weights(self, player, engine, *, hand=None, available_resources: int | None = None, total_resources: int | None = None, phase: str | None = None):
        return self.turn_planner.strategy_weights(
            self,
            player,
            engine,
            hand=hand,
            available_resources=available_resources,
            total_resources=total_resources,
            phase=phase,
        )

    def clear_active_turn_plan(self) -> None:
        self.turn_planner.clear_active_turn_plan(self)

    def _get_active_turn_plan(self):
        return self.turn_planner.get_active_turn_plan(self)

    def _set_active_turn_plan(self, plan):
        self.turn_planner.set_active_turn_plan(self, plan)

    def _archive_and_clear_active_turn_plan(self, reason_codes: tuple[str, ...], *, status: str):
        self.turn_planner.archive_and_clear_active_turn_plan(self, reason_codes, status=status)

    def _get_planned_attacker_ids(self) -> tuple[int, ...]:
        return self.turn_planner.get_planned_attacker_ids(self)

    def _get_planned_step_for_card(self, card_instance_id: int):
        return self.turn_planner.get_planned_step_for_card(self, card_instance_id)

    def _get_planned_target_ids_for_card(self, card_instance_id: int) -> tuple[int, ...]:
        return self.turn_planner.get_planned_target_ids_for_card(self, card_instance_id)

    def _mark_turn_plan_step_completed(self, action_type: str, *, card_instance_id: int | None = None) -> None:
        self.turn_planner.mark_turn_plan_step_completed(self, action_type, card_instance_id=card_instance_id)

    def _get_expected_action_card_id(self, action_type: str) -> int | None:
        return self.turn_planner.get_expected_action_card_id(self, action_type)

    def _get_active_turn_plan_step(self, expected_action_types: tuple[str, ...] = ()):
        return self.turn_planner.get_active_turn_plan_step(self, expected_action_types)

    def _validate_active_air_plan(self, player, engine):
        return self.turn_planner.validate_active_air_plan(self, player, engine)

    def _ensure_valid_active_air_plan(self, player, engine):
        return self.turn_planner.ensure_valid_active_air_plan(self, player, engine)

    def _build_air_turn_plan_from_candidate(self, player, engine, candidate: dict):
        return self.turn_planner.build_air_turn_plan_from_candidate(self, player, engine, candidate)

StrategicAI = HeuristicStrategicAI
SimpleAI = HeuristicStrategicAI
