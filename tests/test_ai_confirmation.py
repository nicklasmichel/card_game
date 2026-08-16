from __future__ import annotations

from threading import Event
from time import sleep
from types import SimpleNamespace
from unittest.mock import patch

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
        self.assertEqual(self.engine.current_prompt(), "Player 2 (AI) adds a resource.")
        self.assertEqual(get_action_panel_prompt(SimpleNamespace(engine=self.engine)), "AI adds a resource.")

        self.engine.handle_action("confirm_ai_action")

        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertEqual(len(self.engine.ai_player.resources), 1)
        self.assertEqual(self.engine.phase, PHASE_MAIN_1)

    def test_ai_thinking_state_shows_prompt_and_hides_buttons(self) -> None:
        self.engine.phase = PHASE_MAIN_1

        started = self.engine.start_ai_thinking()

        self.assertTrue(started)
        self.assertTrue(self.engine.is_ai_thinking())
        self.assertEqual(self.engine.current_prompt(), "AI is thinking...")
        self.assertEqual(get_action_panel_prompt(SimpleNamespace(engine=self.engine)), "AI is thinking...")
        self.assertEqual(self.engine.get_button_specs(), [])

        thread = self.engine.ai_think_thread
        self.assertIsNotNone(thread)
        thread.join(timeout=2.0)
        self.engine.poll_ai_thinking()

        self.assertFalse(self.engine.is_ai_thinking())
        self.assertTrue(self.engine.has_pending_ai_action())
        self.assertEqual(self.engine.pending_ai_action["kind"], "builder_add_resource")

    def test_cancel_ai_thinking_stops_cooperative_worker(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        entered = Event()
        stopped = Event()

        def wait_for_cancel(_engine, *, cancel_event=None):
            entered.set()
            while cancel_event is not None and not cancel_event.is_set():
                sleep(0.001)
            stopped.set()
            return None

        with patch("engine.interface._compute_prepared_ai_action", side_effect=wait_for_cancel):
            self.assertTrue(self.engine.start_ai_thinking())
            self.assertTrue(entered.wait(timeout=1.0))
            worker = self.engine.ai_think_thread
            cancel_event = self.engine.ai_think_cancel_event

            self.engine.cancel_ai_thinking()
            worker.join(timeout=1.0)

        self.assertTrue(cancel_event.is_set())
        self.assertTrue(stopped.is_set())
        self.assertFalse(worker.is_alive())
        self.assertFalse(self.engine.is_ai_thinking())
        self.assertFalse(self.engine.has_pending_ai_action())

    def test_ai_thinking_error_uses_fast_fallback(self) -> None:
        self.engine.phase = PHASE_MAIN_1
        with patch("engine.interface._compute_prepared_ai_action", side_effect=RuntimeError("test failure")):
            self.assertTrue(self.engine.start_ai_thinking())
            worker = self.engine.ai_think_thread
            worker.join(timeout=1.0)
            self.assertTrue(self.engine.poll_ai_thinking())

        self.assertEqual(self.engine.pending_ai_action["kind"], "builder_add_resource")
        self.assertIn("fast fallback", self.engine.pending_ai_action["description"])
        self.assertTrue(any("AI thinking failed" in line for line in self.engine.log_messages))

    def test_ai_attack_step_waits_for_confirmation(self) -> None:
        attacker = self.engine.create_builder_creature(self.engine.ai_player, aw=2, vw=1, sw=2, lw=1)
        assert attacker is not None
        attacker.tapped = False
        attacker.summoning_sick = False
        self.engine.phase = PHASE_DECLARE_ATTACKERS

        prepared = self.engine.prepare_ai_turn_action()

        self.assertTrue(prepared)
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_attackers")
        self.assertIn("Player 2 (AI) attacks with:", self.engine.pending_ai_action["description"])
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
        self.assertIn("block_assignments", self.engine.pending_ai_action)
        self.assertEqual(
            [(button.label, button.enabled, button.action) for button in self.engine.get_button_specs()],
            [("Next", True, "confirm_ai_action")],
        )

        with patch.object(self.engine, "ai_assign_blocks", wraps=self.engine.ai_assign_blocks) as assign_blocks:
            self.engine.handle_action("confirm_ai_action")

        assign_blocks.assert_not_called()
        self.assertFalse(self.engine.has_pending_ai_action())
        self.assertNotEqual(self.engine.phase, PHASE_DECLARE_BLOCKERS)

    def test_human_attack_leaves_ai_block_search_for_background_worker(self) -> None:
        self.engine.active_player_index = self.engine.human_player.player_id
        attacker = self.engine.create_builder_creature(self.engine.human_player, aw=2, vw=1, sw=2, lw=2)
        blocker = self.engine.create_builder_creature(self.engine.ai_player, aw=1, vw=2, sw=1, lw=2)
        assert attacker is not None and blocker is not None
        attacker.tapped = False
        attacker.summoning_sick = False
        blocker.tapped = False
        blocker.summoning_sick = False
        self.engine.selected_attackers = [attacker.unit_id]
        self.engine.phase = PHASE_DECLARE_ATTACKERS

        with patch.object(self.engine, "ai_assign_blocks", wraps=self.engine.ai_assign_blocks) as assign_blocks:
            self.engine.confirm_attackers()

        assign_blocks.assert_not_called()
        self.assertEqual(self.engine.phase, PHASE_DECLARE_BLOCKERS)
        self.assertEqual(self.engine.block_assignments, {attacker.unit_id: None})
        self.assertTrue(self.engine.start_ai_thinking())
        worker = self.engine.ai_think_thread
        worker.join(timeout=2.0)
        self.assertTrue(self.engine.poll_ai_thinking())
        self.assertEqual(self.engine.pending_ai_action["kind"], "declare_blocks")

    def test_human_can_confirm_blocks_while_ai_is_active_player(self) -> None:
        attacker = self.engine.create_builder_creature(self.engine.ai_player, aw=2, vw=1, sw=2, lw=2)
        blocker = self.engine.create_builder_creature(self.engine.human_player, aw=1, vw=2, sw=1, lw=2)
        assert attacker is not None and blocker is not None
        attacker.tapped = False
        attacker.summoning_sick = False
        blocker.tapped = False
        blocker.summoning_sick = False
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {attacker.unit_id: blocker.unit_id}

        self.engine.handle_action("confirm_blocks")

        self.assertNotEqual(self.engine.phase, PHASE_DECLARE_BLOCKERS)

    def test_human_can_clear_blocks_while_ai_is_active_player(self) -> None:
        attacker = self.engine.create_builder_creature(self.engine.ai_player, aw=2, vw=1, sw=2, lw=2)
        blocker = self.engine.create_builder_creature(self.engine.human_player, aw=1, vw=2, sw=1, lw=2)
        assert attacker is not None and blocker is not None
        attacker.tapped = False
        attacker.summoning_sick = False
        blocker.tapped = False
        blocker.summoning_sick = False
        self.engine.phase = PHASE_DECLARE_BLOCKERS
        self.engine.block_assignments = {attacker.unit_id: blocker.unit_id}

        self.engine.handle_action("clear_blocks")

        self.assertEqual(self.engine.phase, PHASE_DECLARE_BLOCKERS)
        self.assertEqual(self.engine.block_assignments, {attacker.unit_id: None})

    def test_pending_builder_ai_action_is_visible_in_action_panel_prompt(self) -> None:
        self.engine.pending_ai_action = {
            "kind": "builder_create_creature",
            "description": "Player 2 (AI) builds creature: Atk 0 / Def 3 / Dmg 1 / Life 1 / Haste.",
        }
        self.assertEqual(
            get_action_panel_prompt(SimpleNamespace(engine=self.engine)),
            "AI builds creature: Atk 0 / Def 3 / Dmg 1 / Life 1 / Haste.",
        )
