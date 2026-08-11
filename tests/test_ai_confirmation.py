from __future__ import annotations

from types import SimpleNamespace

from core.models import PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_MAIN_1
from tests.helpers import EngineTestCase
from ui.layout_sidepanel import get_action_panel_prompt


class AiConfirmationTests(EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.engine.initialize_builder_game()
        self.engine.active_player_index = self.engine.ai_player.player_id
        self.engine.reset_combat_state()
        self.engine.log_messages.clear()

    def test_ai_main_phase_prepares_with_confirmation_button_and_prompt(self) -> None:
        self.engine.phase = PHASE_MAIN_1

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertTrue(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.pending_ai_action["kind"], "builder_add_resource")
        self.assertEqual(
            [(button.label, button.enabled, button.action) for button in self.engine.get_button_specs()],
            [("Next", True, "confirm_ai_action")],
        )
        self.assertEqual(self.engine.current_prompt(), "Enemy will add a resource.")
        self.assertEqual(get_action_panel_prompt(SimpleNamespace(engine=self.engine)), "Enemy will add a resource.")

        self.engine.handle_action("confirm_ai_action")

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.resources), 1)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)

    def test_ai_attack_step_waits_for_confirmation(self) -> None:
        attacker = self.engine.create_builder_creature(self.engine.ai_player, aw=2, vw=1, sw=2, lw=1)
        assert attacker is not None
        attacker.tapped = False
        attacker.summoning_sick = False
        self.engine.phase = PHASE_DECLARE_ATTACKERS

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertIn("Enemy will", self.engine.pending_ai_action["description"])
        self.assertEqual(
            [(button.label, button.enabled, button.action) for button in self.engine.get_button_specs()],
            [("Next", True, "confirm_ai_action")],
        )

        self.engine.handle_action("confirm_ai_action")

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertIn(self.engine.phase, {PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE, PHASE_MAIN_1})

    def test_ai_block_step_waits_for_confirmation(self) -> None:
        self.engine.active_player_index = self.engine.human_player.player_id
        attacker = self.engine.create_builder_creature(self.engine.human_player, aw=2, vw=1, sw=1, lw=1)
        blocker = self.engine.create_builder_creature(self.engine.ai_player, aw=1, vw=2, sw=1, lw=1)
        assert attacker is not None and blocker is not None
        attacker.tapped = False
        attacker.summoning_sick = False
        blocker.tapped = False
        blocker.summoning_sick = False
        self.engine.selected_attackers = [attacker.unit_id]
        self.engine.phase = PHASE_DECLARE_BLOCKERS

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_blocks")
        self.assertEqual(
            [(button.label, button.enabled, button.action) for button in self.engine.get_button_specs()],
            [("Next", True, "confirm_ai_action")],
        )

        self.engine.handle_action("confirm_ai_action")

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertNotEqual(self.engine.phase, PHASE_DECLARE_BLOCKERS)

    def test_pending_builder_ai_action_is_visible_in_action_panel_prompt(self) -> None:
        self.engine.pending_ai_action = {
            "kind": "builder_create_creature",
            "description": "Enemy will build A 0 / D 3 / DMG 1 / Life 1.",
        }
        self.assertEqual(
            get_action_panel_prompt(SimpleNamespace(engine=self.engine)),
            "Enemy will build A 0 / D 3 / DMG 1 / Life 1.",
        )
