"""Unit tests for srs.py (Anki SM-2 with default deck options). Run from this directory:

    python3 -m unittest test_schedule -v
"""
import unittest
from datetime import datetime, timedelta, timezone

import srs
from srs import AGAIN, GOOD, HARD, TZ, grade_from, schedule

UTC = timezone.utc


def et(y, mo, d, h, mi=0):
    """A New York wall-clock time, as UTC."""
    return datetime(y, mo, d, h, mi, tzinfo=TZ).astimezone(UTC)


class GradeFrom(unittest.TestCase):
    def test_struggle_face_is_again_even_when_the_reply_is_perfect(self):
        self.assertEqual(grade_from({"fluent": True, "meaningful_usage": True}, True), AGAIN)

    def test_misused_target_word_is_again(self):
        self.assertEqual(grade_from({"fluent": True, "meaningful_usage": False}, False), AGAIN)

    def test_grammar_slip_with_the_word_right_is_hard(self):
        self.assertEqual(grade_from({"fluent": False, "meaningful_usage": True}, False), HARD)

    def test_both_right_is_good(self):
        self.assertEqual(grade_from({"fluent": True, "meaningful_usage": True}, False), GOOD)


class Learning(unittest.TestCase):
    now = et(2026, 10, 27, 7, 0)

    def test_new_word_good_comes_back_in_10_minutes(self):
        card, due = schedule(srs.new_card(), GOOD, self.now, None)
        self.assertEqual(due - self.now, timedelta(minutes=10))
        self.assertEqual((card["state"], card["step"]), ("learning", 1))

    def test_new_word_again_comes_back_in_1_minute(self):
        card, due = schedule(srs.new_card(), AGAIN, self.now, None)
        self.assertEqual(due - self.now, timedelta(minutes=1))
        self.assertEqual((card["state"], card["step"]), ("learning", 0))

    def test_new_word_hard_waits_the_average_of_the_first_two_steps(self):
        _, due = schedule(srs.new_card(), HARD, self.now, None)
        self.assertEqual(due - self.now, timedelta(minutes=5.5))

    def test_good_on_the_last_step_graduates_to_tomorrow_4am(self):
        card, _ = schedule(srs.new_card(), GOOD, self.now, None)
        later = self.now + timedelta(minutes=10)
        card, due = schedule(card, GOOD, later, None)
        self.assertEqual((card["state"], card["ivl"]), ("review", 1))
        self.assertEqual(due, et(2026, 10, 28, 4))

    def test_graduating_at_9pm_is_due_at_4am_next_morning(self):
        card = {**srs.new_card(), "state": "learning", "step": 1}
        _, due = schedule(card, GOOD, et(2026, 10, 27, 21), None)
        self.assertEqual(due, et(2026, 10, 28, 4))

    def test_graduating_at_2am_counts_as_the_previous_day(self):
        card = {**srs.new_card(), "state": "learning", "step": 1}
        _, due = schedule(card, GOOD, et(2026, 10, 28, 2), None)
        self.assertEqual(due, et(2026, 10, 28, 4))

    def test_reps_and_last_review_are_recorded(self):
        card, _ = schedule(srs.new_card(), GOOD, self.now, None)
        self.assertEqual((card["reps"], card["last"]), (1, self.now))


class Review(unittest.TestCase):
    def review(self, ivl, ease=srs.STARTING_EASE):
        return {**srs.new_card(), "state": "review", "ivl": ivl, "ease": ease}

    def test_on_time_good_grows_1_3_8_20_50(self):
        card, due = self.review(1), et(2026, 10, 28, 4)
        seen = []
        for _ in range(4):
            card, due = schedule(card, GOOD, due, due)  # answered the moment it falls due
            seen.append(card["ivl"])
        self.assertEqual(seen, [3, 8, 20, 50])

    def test_review_due_lands_on_4am_of_the_due_day(self):
        _, due = schedule(self.review(1), GOOD, et(2026, 10, 28, 19, 30), et(2026, 10, 28, 4))
        self.assertEqual(due, et(2026, 10, 31, 4))

    def test_hard_adds_20_percent_and_drops_ease(self):
        card, _ = schedule(self.review(3), HARD, et(2026, 10, 28, 9), et(2026, 10, 28, 4))
        self.assertEqual((card["ivl"], card["ease"]), (4, 2.35))

    def test_again_relearns_in_10_minutes_then_returns_tomorrow(self):
        now = et(2026, 10, 28, 9)
        card, due = schedule(self.review(20), AGAIN, now, et(2026, 10, 28, 4))
        self.assertEqual(due - now, timedelta(minutes=10))
        self.assertEqual((card["state"], card["ease"], card["lapses"], card["ivl"]),
                         ("relearning", 2.3, 1, 1))
        card, due = schedule(card, GOOD, now + timedelta(minutes=10), due)
        self.assertEqual((card["state"], card["ivl"]), ("review", 1))
        self.assertEqual(due, et(2026, 10, 29, 4))

    def test_late_review_earns_half_the_lateness(self):
        # ivl 3, answered 4 days late: Good = (3 + 4/2) * 2.5 = 12.5 -> 13 days.
        card, _ = schedule(self.review(3), GOOD, et(2026, 11, 2, 9), et(2026, 10, 29, 4))
        self.assertEqual(card["ivl"], 13)

    def test_ease_never_drops_below_the_floor(self):
        card, _ = schedule(self.review(5, ease=1.4), AGAIN, et(2026, 10, 28, 9), None)
        self.assertEqual(card["ease"], srs.EASE_FLOOR)


class Legacy(unittest.TestCase):
    def test_legacy_word_268_days_overdue_gets_3_days_not_hundreds(self):
        now = et(2026, 10, 27, 7)
        card, due = schedule(srs.legacy_card(), GOOD, now, now - timedelta(days=268))
        self.assertEqual(card["ivl"], 3)
        self.assertNotIn("legacy", card)
        self.assertEqual(due, et(2026, 10, 30, 4))

    def test_learning_card_restarts_at_step_0_and_keeps_history(self):
        card = srs.learning_card({**srs.legacy_card(), "ease": 2.1, "lapses": 2, "reps": 7})
        self.assertEqual((card["state"], card["step"], card["ease"], card["lapses"], card["reps"]),
                         ("learning", 0, 2.1, 2, 7))
        self.assertNotIn("legacy", card)


class DaylightSaving(unittest.TestCase):
    # US clocks fall back at 2 AM on Sunday 2026-11-01, so 4 AM moves from 08:00 to 09:00 UTC.
    def test_due_day_after_the_switch_starts_at_4am_est(self):
        card = {**srs.new_card(), "state": "learning", "step": 1}
        _, due = schedule(card, GOOD, et(2026, 10, 31, 21), None)
        self.assertEqual(due, datetime(2026, 11, 1, 9, 0, tzinfo=UTC))

    def test_due_day_before_the_switch_starts_at_4am_edt(self):
        card = {**srs.new_card(), "state": "learning", "step": 1}
        _, due = schedule(card, GOOD, et(2026, 10, 30, 21), None)
        self.assertEqual(due, datetime(2026, 10, 31, 8, 0, tzinfo=UTC))


class Validation(unittest.TestCase):
    def test_unknown_grade_raises(self):
        with self.assertRaises(ValueError):
            schedule(srs.new_card(), "easy", et(2026, 10, 27, 7), None)


if __name__ == "__main__":
    unittest.main()
