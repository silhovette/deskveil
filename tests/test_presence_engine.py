import unittest
from detection.presence_engine import PresenceEngine, State, owner_candidate


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = PresenceEngine()

    def samples(self, present, start, end, step=.2):
        for i in range(round((end - start) / step) + 1):
            self.engine.update(present, round(start + i * step, 8))

    def cover(self):
        self.samples(False, 0, 2)
        self.assertEqual(self.engine.state, State.COVERED)

    def test_short_dropout(self):
        self.samples(False, 0, 1)
        self.engine.update(True, 1.2)
        self.assertEqual(self.engine.state, State.PRESENT)

    def test_two_seconds(self):
        self.samples(False, 0, 1.8)
        self.assertFalse(self.engine.covered)
        self.engine.update(False, 2)
        self.assertTrue(self.engine.covered)

    def test_return_at_1_9(self):
        self.samples(False, 0, 1.8)
        self.engine.update(True, 1.9)
        self.assertEqual(self.engine.state, State.PRESENT)

    def test_short_false_return(self):
        self.cover()
        self.samples(True, 2.2, 2.6)
        self.engine.update(False, 2.8)
        self.assertEqual(self.engine.state, State.COVERED)

    def test_stable_return(self):
        self.cover()
        self.samples(True, 2.2, 2.6)
        self.assertEqual(self.engine.state, State.PENDING_RETURN)
        self.assertTrue(self.engine.covered)
        self.engine.update(True, 2.69)
        self.assertEqual(self.engine.state, State.PENDING_RETURN)
        self.engine.update(True, 2.7)
        self.assertEqual(self.engine.state, State.PRESENT)

    def test_camera_failure_not_absence(self):
        self.samples(False, 0, 1.8)
        self.engine.update(None, 2)
        self.engine.update(False, 2.2)
        self.assertEqual(self.engine.state, State.PENDING_AWAY)
        self.assertFalse(self.engine.covered)

    def test_camera_failure_keeps_cover(self):
        self.cover()
        self.engine.update(True, 2.2)
        self.engine.update(None, 2.4)
        self.assertEqual(self.engine.state, State.COVERED)

    def test_inference_gap_restarts_absence(self):
        self.samples(False, 0, 1.8)
        self.engine.update(False, 30)
        self.assertFalse(self.engine.covered)
        self.samples(False, 30.2, 32)
        self.assertTrue(self.engine.covered)

    def test_gap_restarts_return(self):
        self.cover()
        self.engine.update(True, 2.2)
        self.engine.update(True, 10)
        self.assertTrue(self.engine.covered)

    def test_clock_cannot_cover(self):
        self.engine.update(False, 0)
        self.engine.tick(60)
        self.assertFalse(self.engine.covered)

    def test_snooze_and_fresh_restart(self):
        self.cover()
        self.engine.snooze(5, 600)
        self.samples(False, 5.2, 604.8)
        self.assertEqual(self.engine.state, State.SNOOZED)
        self.engine.update(False, 605)
        self.assertEqual(self.engine.state, State.PENDING_AWAY)
        self.samples(False, 605.2, 606.8)
        self.assertFalse(self.engine.covered)
        self.engine.update(False, 607)
        self.assertTrue(self.engine.covered)

    def test_cover_now_requires_departure(self):
        self.engine.cover_now()
        self.samples(True, 0, 10)
        self.assertTrue(self.engine.covered)
        self.engine.update(False, 10.2)
        self.samples(True, 10.4, 11)
        self.assertFalse(self.engine.covered)

    def test_unknown_cannot_arm_manual_return(self):
        self.engine.cover_now()
        self.engine.update(None, 0)
        self.samples(True, .2, 3)
        self.assertTrue(self.engine.covered)

    def test_reveal_without_snooze_starts_new_absence_confirmation(self):
        self.cover()
        self.engine.resume()
        self.assertEqual(self.engine.state, State.PRESENT)
        self.assertIsNone(self.engine.snoozed_until)
        self.samples(False, 2.2, 4)
        self.assertFalse(self.engine.covered)
        self.engine.update(False, 4.2)
        self.assertTrue(self.engine.covered)

    def test_position_heuristic(self):
        self.assertTrue(owner_candidate([(.35, .25, .65, .75)]))
        self.assertFalse(owner_candidate([(.49, .49, .51, .51)]))
        self.assertFalse(owner_candidate([(0, 0, .16, .16)]))
        self.assertFalse(owner_candidate([(float('nan'), 0, 1, 1)]))
        self.assertFalse(owner_candidate([(1, 1, 0, 0)]))
        self.assertTrue(owner_candidate([(.49, .49, .51, .51), (.35, .25, .65, .75)]))


if __name__ == "__main__":
    unittest.main()
