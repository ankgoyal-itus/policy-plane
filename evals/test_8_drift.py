"""EVAL 8 — Drift: has reality changed, independent of whether it's stale.

`recheck_days` answers "is this reading old enough to stop trusting". That is a
different question from "did the setting actually change" -- a surface rechecked every
90 days can loosen on day 3 and nothing about staleness says so for another 87 days.
Drift compares a reading from at least DRIFT_WINDOW_DAYS ago against the latest one and
reports only when the IN-FORCE status flipped between them.

The trap this suite exists to catch: reporting "no drift" for a pair that was never
actually checked twice. Silence there would read as "confirmed unchanged" when it
really means "insufficient history" -- those are different facts and only one of them
is reassuring.

Bar: 100%.
"""
import unittest

from evals import harness
from plane.model import load
from plane.plan import DRIFT_WINDOW_DAYS, build
from plane.render import render

REAL = harness.REPO / "policy.yaml"
PAIR = ("alex-roblox-time", "roblox-alex")
OFFERED = ["No limit", "1 hour", "1 hour 30 minutes", "2 hours"]


def obs(daily, at):
    return {"rule": PAIR[0], "surface": PAIR[1], "recipe": "test", "at": at, "code": "OK",
            "readings": {"dailyLimitText": daily, "offeredText": list(OFFERED)}}


def drift_for(pair, observations, today=harness.TODAY):
    plan = build(load(REAL, None), today, observations)
    return next((d for d in plan["drift"]
                if (d["rule"], d["surface"]) == pair), None)


class DriftNeedsTwoRealReadings(unittest.TestCase):
    """No comparison exists with fewer than two readings straddling the window --
    reporting anything here would be a guess dressed up as a finding."""

    def test_a_single_recent_reading_reports_no_drift_entry(self):
        self.assertIsNone(drift_for(PAIR, [obs("1 hour 30 minutes", "2026-08-30T10:00:00Z")]))

    def test_a_single_old_reading_reports_no_drift_entry(self):
        """Old enough to be a valid 'then', but there is no 'now' to compare it to."""
        self.assertIsNone(drift_for(PAIR, [obs("No limit", "2026-08-20T10:00:00Z")]))

    def test_no_observations_at_all_reports_no_drift_entry(self):
        self.assertIsNone(drift_for(PAIR, []))


class DriftComparesInForceStatusOnly(unittest.TestCase):

    def test_no_drift_when_the_verdict_is_unchanged(self):
        readings = [obs("1 hour 30 minutes", "2026-08-24T10:00:00Z"),
                    obs("1 hour 30 minutes", "2026-08-30T10:00:00Z")]
        self.assertIsNone(drift_for(PAIR, readings))

    def test_a_stricter_reading_replacing_a_satisfied_one_is_not_drift(self):
        """Both are IN_FORCE -- getting stricter is not the flip this feature watches
        for, and flagging it would train a parent to ignore the alert."""
        readings = [obs("1 hour 30 minutes", "2026-08-24T10:00:00Z"),
                    obs("1 hour", "2026-08-30T10:00:00Z")]
        self.assertIsNone(drift_for(PAIR, readings))

    def test_going_from_held_to_not_held_is_loosened(self):
        readings = [obs("1 hour 30 minutes", "2026-08-24T10:00:00Z"),
                    obs("No limit", "2026-08-30T10:00:00Z")]
        found = drift_for(PAIR, readings)
        self.assertIsNotNone(found)
        self.assertEqual(found["direction"], "loosened")
        self.assertTrue(found["before"]["in_force"])
        self.assertFalse(found["after"]["in_force"])

    def test_going_from_not_held_to_held_is_tightened(self):
        readings = [obs("No limit", "2026-08-24T10:00:00Z"),
                    obs("1 hour", "2026-08-30T10:00:00Z")]
        found = drift_for(PAIR, readings)
        self.assertIsNotNone(found)
        self.assertEqual(found["direction"], "tightened")
        self.assertFalse(found["before"]["in_force"])
        self.assertTrue(found["after"]["in_force"])

    def test_the_vendors_own_words_are_carried_on_both_sides(self):
        """The reveal has to show what the page ACTUALLY said, before and after --
        not just a verdict name -- or a parent has to take the flip on faith."""
        readings = [obs("1 hour 30 minutes", "2026-08-24T10:00:00Z"),
                    obs("No limit", "2026-08-30T10:00:00Z")]
        found = drift_for(PAIR, readings)
        self.assertEqual(found["before"]["said"], "1 hour 30 minutes")
        self.assertEqual(found["after"]["said"], "No limit")


class DriftWindowIsFixedNotRecheckDays(unittest.TestCase):
    """The window is a constant, 7 days, deliberately decoupled from whatever
    recheck_days a surface happens to declare."""

    def test_the_window_is_seven_days(self):
        self.assertEqual(DRIFT_WINDOW_DAYS, 7)

    def test_a_reading_from_exactly_the_window_boundary_can_serve_as_then(self):
        readings = [obs("1 hour 30 minutes", "2026-08-25T10:00:00Z"),   # exactly 7d old
                    obs("No limit", "2026-08-31T10:00:00Z")]            # 1d old
        found = drift_for(PAIR, readings, today="2026-09-01")
        self.assertIsNotNone(found, "a reading exactly at the cutoff must still count")

    def test_a_now_reading_that_is_itself_a_week_old_does_not_count_as_now(self):
        """If nothing has been rechecked within the window, that is a staleness fact,
        not a drift verdict. The latest reading here (8 days old) is itself the most
        recent one at-or-before the cutoff too, so "then" collapses onto the same
        reading as "now" and the verdicts trivially agree -- there is nothing fresh
        enough to compare it against."""
        readings = [obs("1 hour 30 minutes", "2026-08-15T10:00:00Z"),
                    obs("No limit", "2026-08-24T10:00:00Z")]     # 8 days old at today
        self.assertIsNone(drift_for(PAIR, readings, today="2026-09-01"))

    def test_an_unparseable_timestamp_on_the_latest_reading_is_not_treated_as_now(self):
        """A reading we cannot date is a reading we cannot call 'recent' -- comparing it
        anyway would report drift (or its absence) on a guess about its own age."""
        readings = [obs("1 hour 30 minutes", "2026-08-24T10:00:00Z"),
                    obs("No limit", "not-a-real-timestamp")]
        self.assertIsNone(drift_for(PAIR, readings, today="2026-09-01"))


class DriftIsShownOnThePage(unittest.TestCase):
    """Computing it in `_drift` is only half the feature -- if the page never shows it,
    a parent has no way to learn their child's Roblox limit quietly got lifted."""

    def html_for(self, observations):
        policy = load(REAL, harness.REPO / "status.yaml")
        plan = build(policy, harness.TODAY, observations)
        return render(plan)

    def test_a_loosened_pair_appears_with_both_vendor_texts(self):
        html = self.html_for([obs("1 hour 30 minutes", "2026-08-24T10:00:00Z"),
                              obs("No limit", "2026-08-30T10:00:00Z")])
        self.assertIn("Changed in the last week", html)
        self.assertIn("1 hour 30 minutes", html)
        self.assertIn("No limit", html)
        self.assertIn("loosened", html)

    def test_no_drift_section_at_all_when_nothing_has_changed(self):
        """The section must not appear as an empty husk -- its presence is itself the
        signal that something changed."""
        html = self.html_for([])
        self.assertNotIn("Changed in the last week", html)


if __name__ == "__main__":
    unittest.main()
