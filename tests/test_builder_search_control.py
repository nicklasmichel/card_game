from __future__ import annotations

from time import monotonic
import unittest

from core.ai.builder.search_control import builder_search_scope, builder_search_should_stop


class BuilderSearchControlTests(unittest.TestCase):
    def test_local_deadline_does_not_exhaust_whole_turn(self) -> None:
        with builder_search_scope(deadline=monotonic() + 10.0) as control:
            self.assertTrue(builder_search_should_stop(monotonic() - 1.0))
            self.assertFalse(builder_search_should_stop())
            self.assertEqual(control.stop_reason, "")

    def test_turn_deadline_remains_sticky(self) -> None:
        with builder_search_scope(deadline=monotonic() - 1.0) as control:
            self.assertTrue(builder_search_should_stop())
            self.assertEqual(control.stop_reason, "deadline")
            self.assertTrue(builder_search_should_stop(monotonic() + 10.0))


if __name__ == "__main__":
    unittest.main()
