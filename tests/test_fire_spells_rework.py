from __future__ import annotations

from dataclasses import dataclass

from cards import DECK_DEFINITIONS
from core.models import CardInstance, PHASE_GAME_OVER, PHASE_MAIN_1, PHASE_REACTION, ReactionContext, ReactionTrigger, SpellEffect, SpellTargetRef, StackItem
from tests.helpers import EngineTestCase


@dataclass
class _PendingDirectAttackStub:
    attacker_id: int
    base_damage: int
    damage_multiplier: int


class FireSpellReworkTests(EngineTestCase):
    def give_card(self, template_id: str, owner_id: int = 0) -> CardInstance:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        self.engine.players[owner_id].hand.append(card)
        return card

    def give_resources(self, owner_id: int, count: int, *, tapped: bool = False) -> None:
        pool = [
            "fire_creature_glutbestie",
            "water_creature_wassertropfen",
            "earth_creature_steinkobold",
            "air_creature_wolkenschwinge",
        ]
        resources = [self.make_resource(pool[index % len(pool)]) for index in range(count)]
        for resource in resources:
            resource.tapped = tapped
        self.engine.players[owner_id].resources = resources

    def resolve_reaction_window(self) -> None:
        if self.engine.phase == PHASE_REACTION:
            self.engine.pass_reaction()
            self.engine.pass_reaction()

    def open_attack_bonus_window(self, attacker, blockers: list | None = None, trigger: ReactionTrigger = ReactionTrigger.AFTER_ATTACKERS_DECLARED) -> None:
        self.engine.active_player_index = 0
        self.engine.block_assignments = {
            attacker.unit_id: [blocker.unit_id for blocker in (blockers or [])],
        }
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=trigger,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
                attacker_creature=attacker,
                pending_damage_attacker_id=attacker.unit_id if trigger == ReactionTrigger.BEFORE_DIRECT_ATTACK_DAMAGE else None,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

    def cast_damage_spell(self, template_id: str, target: SpellTargetRef, owner_id: int = 0) -> None:
        card = self.give_card(template_id, owner_id=owner_id)
        self.give_resources(owner_id, self.engine.templates[template_id].cost.resources)
        self.engine.active_player_index = owner_id
        self.engine.phase = PHASE_MAIN_1
        self.assertTrue(self.engine.begin_spell_cast(card.instance_id))
        self.engine.select_spell_target_ref(target)
        self.assertTrue(self.engine.confirm_pending_spell_cast())
        self.resolve_reaction_window()

    def prepare_bonus_spell(self, template_id: str, attacker) -> None:
        card = next(
            (existing for existing in self.engine.human_player.hand if existing.template.template_id == template_id),
            None,
        )
        if card is None:
            card = self.give_card(template_id)
        self.assertTrue(self.engine.begin_spell_from_hand(card.instance_id))
        recycle_cost = self.engine.get_card_from_pending_spell().template.recycle_cost
        for resource in list(self.engine.human_player.resources[:recycle_cost]):
            self.engine.toggle_pending_spell_recycle_resource(resource.resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker.unit_id))
        self.assertTrue(self.engine.confirm_pending_spell_cast())
        self.resolve_reaction_window()

    def test_fire_spell_cards_match_final_table(self) -> None:
        expected = {
            "fire_spell_wutanfall": ("Wutanfall", 0, 1, SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN, 3),
            "fire_spell_raserei": ("Raserei", 0, 2, SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN, 6),
            "fire_spell_versengen": ("Versengen", 1, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER, 1),
            "fire_spell_verbrennen": ("Verbrennen", 2, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER, 2),
            "fire_spell_verkohlen": ("Verkohlen", 3, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER, 3),
            "fire_spell_verzehren": ("Verzehren", 4, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER, 4),
        }
        for template_id, (name, resources, recycle, effect, amount) in expected.items():
            template = self.engine.templates[template_id]
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost.resources, resources)
            self.assertEqual(template.cost.recycle, recycle)
            self.assertEqual(template.spell_effect, effect)
            self.assertEqual(template.spell_amount, amount)

    def test_wutanfall_targets_only_own_active_attacker(self) -> None:
        spell = self.give_card("fire_spell_wutanfall")
        self.give_resources(0, 1, tapped=True)
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        own_non_attacker = self.make_creature("fire_creature_glutbrecher", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.open_attack_bonus_window(attacker)

        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))
        self.engine.toggle_pending_spell_recycle_resource(self.engine.human_player.resources[0].resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=own_non_attacker.unit_id))
        self.assertEqual(self.engine.pending_spell_cast.selected_targets, [])
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.assertEqual(self.engine.pending_spell_cast.selected_targets, [])
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker.unit_id))
        self.assertEqual(len(self.engine.pending_spell_cast.selected_targets), 1)

    def test_recycle_for_bonus_spells_uses_tapped_resources_and_removes_them(self) -> None:
        self.give_card("fire_spell_wutanfall")
        self.give_resources(0, 1, tapped=True)
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        self.open_attack_bonus_window(attacker)

        self.prepare_bonus_spell("fire_spell_wutanfall", attacker)

        self.assertEqual(len(self.engine.human_player.resources), 0)
        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 3)

    def test_bonus_spells_stack_and_end_at_end_of_turn(self) -> None:
        self.give_card("fire_spell_wutanfall")
        self.give_card("fire_spell_raserei")
        self.give_resources(0, 3, tapped=True)
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        self.open_attack_bonus_window(attacker)

        self.prepare_bonus_spell("fire_spell_wutanfall", attacker)
        self.open_attack_bonus_window(attacker)
        self.prepare_bonus_spell("fire_spell_raserei", attacker)

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 9)
        self.engine.end_turn()
        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw)

    def test_bonus_applies_across_multiple_blockers(self) -> None:
        self.give_card("fire_spell_wutanfall")
        self.give_resources(0, 1, tapped=True)
        attacker = self.make_creature("fire_creature_flammenbestie", owner_id=0)
        blocker_one = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        blocker_two = self.make_creature("earth_creature_steinkobold", owner_id=1)
        self.open_attack_bonus_window(attacker, blockers=[blocker_one, blocker_two], trigger=ReactionTrigger.AFTER_BLOCKERS_DECLARED)

        self.prepare_bonus_spell("fire_spell_wutanfall", attacker)

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 3)
        self.engine.current_blocker_order = [blocker_one.unit_id, blocker_two.unit_id]
        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 3)

    def test_bonus_applies_to_direct_attack_damage(self) -> None:
        self.give_card("fire_spell_raserei")
        self.give_resources(0, 2, tapped=True)
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        self.engine.ai_player.life = 20
        self.open_attack_bonus_window(attacker, trigger=ReactionTrigger.BEFORE_DIRECT_ATTACK_DAMAGE)

        self.prepare_bonus_spell("fire_spell_raserei", attacker)
        self.engine.pending_direct_attack = _PendingDirectAttackStub(attacker.unit_id, attacker.aw, 1)
        self.engine.resolve_pending_direct_attack_after_reaction()

        self.assertEqual(self.engine.ai_player.life, 20 - (attacker.aw + 6))

    def test_bonus_ends_when_creature_leaves_battlefield(self) -> None:
        self.give_card("fire_spell_wutanfall")
        self.give_resources(0, 1, tapped=True)
        attacker = self.make_creature("fire_creature_glutbestie", owner_id=0)
        self.open_attack_bonus_window(attacker)

        self.prepare_bonus_spell("fire_spell_wutanfall", attacker)
        self.engine.destroy_creature_immediately(self.engine.human_player, attacker, "Test")

        self.assertIsNone(self.engine.get_unit_by_id(attacker.unit_id))

    def test_damage_spells_target_own_and_enemy_creatures_and_players(self) -> None:
        own = self.make_creature("fire_creature_glutbestie", owner_id=0)
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.human_player.life = 10
        self.engine.ai_player.life = 10

        self.cast_damage_spell("fire_spell_versengen", SpellTargetRef("creature", creature_id=own.unit_id))
        self.assertEqual(own.current_hp, own.vw - 1)
        self.cast_damage_spell("fire_spell_verbrennen", SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.assertEqual(enemy.current_hp, enemy.vw - 2)
        self.cast_damage_spell("fire_spell_verkohlen", SpellTargetRef("player", player_id=self.engine.human_player.player_id))
        self.assertEqual(self.engine.human_player.life, 7)
        self.cast_damage_spell("fire_spell_verzehren", SpellTargetRef("player", player_id=self.engine.ai_player.player_id))
        self.assertEqual(self.engine.ai_player.life, 6)

    def test_damage_spell_kills_creature_and_invalid_target_fizzles(self) -> None:
        enemy = self.make_creature("earth_creature_steinkobold", owner_id=1)
        self.cast_damage_spell("fire_spell_verkohlen", SpellTargetRef("creature", creature_id=enemy.unit_id))
        self.assertIsNone(self.engine.get_unit_by_id(enemy.unit_id))

        target = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.destroy_creature_immediately(self.engine.ai_player, target, "Test")
        spell = CardInstance(self.engine.make_instance_id(), self.engine.templates["fire_spell_versengen"])
        self.engine.resolve_stack_item(
            StackItem(
                source_card=spell,
                controller=self.engine.human_player,
                targets=[SpellTargetRef("creature", creature_id=target.unit_id)],
                effect=SpellEffect.DEAL_DAMAGE_TO_CREATURE_OR_PLAYER,
                context=None,
                amount=1,
            )
        )

        self.assertTrue(any("verpufft" in message for message in self.engine.log_messages))

    def test_damage_spell_causes_game_over(self) -> None:
        self.engine.ai_player.life = 4
        self.cast_damage_spell("fire_spell_verzehren", SpellTargetRef("player", player_id=self.engine.ai_player.player_id))
        self.assertEqual(self.engine.phase, PHASE_GAME_OVER)

    def test_new_fire_spells_are_registered_and_old_ones_removed(self) -> None:
        new_ids = {
            "fire_spell_wutanfall",
            "fire_spell_raserei",
            "fire_spell_versengen",
            "fire_spell_verbrennen",
            "fire_spell_verkohlen",
            "fire_spell_verzehren",
        }
        old_ids = {
            "fire_spell_hitzeschub",
            "fire_spell_letzter_funke",
            "fire_spell_brandzeichen",
            "fire_spell_gegenfeuer",
            "fire_spell_flammenzorn",
        }
        self.assertTrue(new_ids.issubset(self.engine.templates.keys()))
        self.assertTrue(old_ids.isdisjoint(self.engine.templates.keys()))

    def test_fire_deck_contains_each_new_spell_twice_and_has_40_cards(self) -> None:
        decklist = dict(DECK_DEFINITIONS["fire"])
        for template_id in (
            "fire_spell_wutanfall",
            "fire_spell_raserei",
            "fire_spell_versengen",
            "fire_spell_verbrennen",
            "fire_spell_verkohlen",
            "fire_spell_verzehren",
        ):
            self.assertEqual(decklist.get(template_id), 2)
        self.assertEqual(sum(decklist.values()), 40)
