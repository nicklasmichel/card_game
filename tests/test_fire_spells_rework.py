from __future__ import annotations

from cards import DECK_DEFINITIONS
from core.models import PHASE_MAIN_1, ReactionContext, ReactionTrigger, SpellEffect, SpellTargetRef, SpellTiming
from tests.helpers import EngineTestCase


class FireSpellReworkTests(EngineTestCase):
    def give_card(self, template_id: str, owner_id: int = 0):
        card = self.engine.templates[template_id]
        instance = self.engine.make_instance_id()
        wrapped = __import__("core.models", fromlist=["CardInstance"]).CardInstance(instance, card)
        self.engine.players[owner_id].hand.append(wrapped)
        return wrapped

    def give_resources(self, owner_id: int, count: int, *, tapped: bool = False) -> None:
        pool = [
            "fire_creature_gluthetzer",
            "water_creature_wassertropfen",
            "earth_creature_steinkobold",
            "air_creature_windschwinge",
        ]
        resources = [self.make_resource(pool[index % len(pool)]) for index in range(count)]
        for resource in resources:
            resource.tapped = tapped
        self.engine.players[owner_id].resources = resources

    def open_attack_bonus_window(self, attacker) -> None:
        self.engine.active_player_index = 0
        self.engine.block_assignments = {attacker.unit_id: None}
        self.engine.begin_reaction_window(
            context=ReactionContext(
                trigger=ReactionTrigger.COMBAT_START,
                active_player=self.engine.human_player,
                source_player=self.engine.human_player,
                attacker_creature=attacker,
            ),
            first_responder_id=self.engine.human_player.player_id,
            base_stack_size=0,
            resume_phase=PHASE_MAIN_1,
        )

    def resolve_reaction_window(self) -> None:
        if self.engine.phase == self.engine.phase == "Reaktionsfenster":
            self.engine.pass_reaction()
            self.engine.pass_reaction()

    def test_fire_spell_cards_match_final_table(self) -> None:
        expected = {
            "fire_spell_wutanfall": ("Wutanfall", 0, 1, SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN, 1, 2, 2),
            "fire_spell_raserei": ("Raserei", 0, 2, SpellEffect.GRANT_ATTACK_BONUS_UNTIL_END_OF_TURN, 1, 4, 4),
            "fire_spell_versengen": ("Versengen", 1, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE, 1),
            "fire_spell_verbrennen": ("Verbrennen", 2, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE, 2),
            "fire_spell_verkohlen": ("Verkohlen", 3, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE, 3),
            "fire_spell_verzehren": ("Verzehren", 4, 0, SpellEffect.DEAL_DAMAGE_TO_CREATURE, 4),
        }
        for template_id, values in expected.items():
            template = self.engine.templates[template_id]
            if template_id in {"fire_spell_wutanfall", "fire_spell_raserei"}:
                name, resources, recycle, effect, amount, aw_bonus, sw_bonus = values
            else:
                name, resources, recycle, effect, amount = values
                aw_bonus = 0
                sw_bonus = 0
            self.assertEqual(template.name, name)
            self.assertEqual(template.cost.resources, resources)
            self.assertEqual(template.cost.recycle, recycle)
            self.assertEqual(template.spell_effect, effect)
            self.assertEqual(template.spell_amount, amount)
            self.assertEqual(template.spell_timing, SpellTiming.COMBAT)
            self.assertEqual(getattr(template, "combat_aw_bonus", 0), aw_bonus)
            self.assertEqual(getattr(template, "combat_sw_bonus", 0), sw_bonus)

    def test_wutanfall_targets_only_own_current_attacker(self) -> None:
        spell = self.give_card("fire_spell_wutanfall")
        self.give_resources(0, 1, tapped=True)
        attacker = self.make_creature("fire_creature_gluthetzer", owner_id=0)
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

    def test_wutanfall_adds_aw_and_sw_for_direct_damage(self) -> None:
        spell = self.give_card("fire_spell_wutanfall")
        self.give_resources(0, 1, tapped=True)
        attacker = self.make_creature("fire_creature_gluthetzer", owner_id=0)
        self.open_attack_bonus_window(attacker)

        self.assertTrue(self.engine.begin_spell_from_hand(spell.instance_id))
        self.engine.toggle_pending_spell_recycle_resource(self.engine.human_player.resources[0].resource_id)
        self.engine.select_spell_target_ref(SpellTargetRef("creature", creature_id=attacker.unit_id))
        self.assertTrue(self.engine.confirm_pending_spell_cast())
        self.engine.resolve_spell_stack_to(0, None)

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw + 2)
        self.assertEqual(self.engine.get_creature_damage_value(attacker), attacker.sw + 2)
        self.engine.ai_player.life = 20
        self.engine._apply_pending_direct_attack(
            type("Pending", (), {
                "attacker_id": attacker.unit_id,
                "attacker_owner": 0,
                "defending_player_id": 1,
                "base_damage": self.engine.get_creature_damage_value(attacker),
            })()
        )
        self.assertEqual(self.engine.ai_player.life, 20 - (attacker.sw + 2))

    def test_bonus_ends_after_turn(self) -> None:
        attacker = self.make_creature("fire_creature_gluthetzer", owner_id=0)
        attacker.temporary_combat_aw_bonus = 6
        attacker.temporary_combat_sw_bonus = 4

        self.engine.clear_combat_temporary_effects()

        self.assertEqual(self.engine.get_creature_attack_value(attacker), attacker.aw)
        self.assertEqual(self.engine.get_creature_damage_value(attacker), attacker.sw)

    def test_damage_spells_still_target_creatures(self) -> None:
        enemy = self.make_creature("earth_creature_felsensoldat", owner_id=1)
        self.engine.resolve_stack_item(
            __import__("core.models", fromlist=["StackItem"]).StackItem(
                source_card=self.give_card("fire_spell_verbrennen"),
                controller=self.engine.human_player,
                targets=[SpellTargetRef("creature", creature_id=enemy.unit_id)],
                effect=SpellEffect.DEAL_DAMAGE_TO_CREATURE,
                context=ReactionContext(
                    trigger=ReactionTrigger.COMBAT_START,
                    active_player=self.engine.human_player,
                    source_player=self.engine.human_player,
                ),
                amount=2,
            )
        )
        self.assertEqual(enemy.current_hp, enemy.lw - 2)

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

