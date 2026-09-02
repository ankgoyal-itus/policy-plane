"""EVAL 1 — Coverage is never overstated.

The product's whole claim is that the page tells you the truth. The failure that matters
is the one direction: telling a parent a rule is in force when it isn't. Every state
except `verified` must read as a gap.

Bar: 100%. Any failure here means the page can lie.
"""
import sys
import unittest
import unittest.mock

from evals import harness

sys.path.insert(0, str(harness.REPO))
from plane.model import load
from plane.plan import build


def plan_for(status, today=harness.TODAY):
    path = harness.FIXTURES / status if status else None
    return build(load(harness.MINI, path), today)


def cell(plan, rule, surface="only"):
    return plan["cells"][(rule, surface)]


def rule_of(plan, rid):
    return next(r for r in plan["rules"] if r["id"] == rid)


class OnlyVerifiedCounts(unittest.TestCase):

    def test_verified_and_fresh_is_covered(self):
        """The precision half. A checker that never says 'covered' passes every other
        test in this file, so one case must genuinely go green."""
        plan = plan_for("status-verified.yaml")
        self.assertEqual(cell(plan, "r-schedule")["state"], "verified")
        self.assertEqual(rule_of(plan, "r-schedule")["covered_by"], ["only"])
        self.assertEqual(plan["summary"]["pairs_covered"], 1)

    def test_stale_is_a_gap_not_coverage(self):
        plan = plan_for("status-stale.yaml")
        self.assertEqual(cell(plan, "r-schedule")["state"], "stale")
        self.assertEqual(rule_of(plan, "r-schedule")["covered_by"], [])
        self.assertEqual(plan["summary"]["pairs_covered"], 0)

    def test_applied_but_unconfirmed_is_a_gap(self):
        """'I changed it' is not 'I checked it'. Nothing reads back from these apps."""
        plan = plan_for("status-applied.yaml")
        self.assertEqual(cell(plan, "r-schedule")["state"], "applied")
        self.assertEqual(rule_of(plan, "r-schedule")["covered_by"], [])

    def test_no_record_at_all_is_a_gap(self):
        plan = plan_for(None)
        self.assertEqual(cell(plan, "r-schedule")["state"], "todo")
        self.assertEqual(plan["summary"]["pairs_covered"], 0)

    def test_missing_status_file_does_not_mean_everything_is_fine(self):
        """An absent status file must read as 'nothing done', never as an empty pass."""
        plan = build(load(harness.MINI, harness.FIXTURES / "no-such-file.yaml"),
                     harness.TODAY)
        self.assertEqual(plan["summary"]["pairs_covered"], 0)
        self.assertEqual(plan["summary"]["todo_count"],
                         plan["summary"]["pairs_applicable"])

    def test_a_rule_no_surface_can_enforce_is_reported_not_hidden(self):
        """The quiet failure: a rule that simply vanishes because nothing handles it."""
        plan = plan_for("status-verified.yaml")
        orphan = rule_of(plan, "r-orphan")
        self.assertFalse(orphan["reachable"])
        self.assertEqual(orphan["covered_by"], [])
        self.assertEqual(plan["summary"]["rules_with_no_surface"], 1)

    def test_staleness_moves_with_the_date_not_the_clock(self):
        """Same file, different day, different verdict — and no clock read inside."""
        fresh = plan_for("status-stale.yaml", "2026-06-15")
        old = plan_for("status-stale.yaml", "2026-09-01")
        self.assertEqual(cell(fresh, "r-schedule")["state"], "verified")
        self.assertEqual(cell(old, "r-schedule")["state"], "stale")

    def test_a_surface_that_cannot_do_a_kind_never_covers_it(self):
        """`only` handles schedule and contact. It must not cover a purchase rule even
        if someone writes a status record claiming it does."""
        plan = plan_for("status-verified.yaml")
        self.assertFalse(plan["cells"][("r-orphan", "only")]["applicable"])


class ABrokenPolicyIsNeverServedSilently(unittest.TestCase):
    """A stale page that looks fine is worse than an error page.

    build.py --serve rebuilds the dashboard per request. When the rebuild fails it must
    raise, so the server can say so, rather than falling back to the last good file --
    which would quietly describe a policy that is no longer what the file says. That
    exact failure wasted a debugging round: a malformed local policy served a page from
    an earlier build with the old parameters baked in.
    """

    def test_an_invalid_policy_raises_rather_than_returning_quietly(self):
        import build as build_module
        broken = harness.FIXTURES / "_tmp-broken.yaml"
        broken.write_text("version: 1\nkids: [{id: k, name: K}]\nrules: []\n")
        try:
            with unittest.mock.patch.object(build_module, "_pick",
                                            side_effect=lambda stem: (broken, None)):
                with self.assertRaises(Exception):
                    build_module._build_page("2026-09-02", raise_on_error=True)
        finally:
            broken.unlink(missing_ok=True)

    def test_the_quiet_path_still_exists_for_the_cli(self):
        """Without raise_on_error the CLI keeps its non-zero exit rather than a traceback."""
        import build as build_module
        broken = harness.FIXTURES / "_tmp-broken2.yaml"
        broken.write_text("version: 1\nkids: [{id: k, name: K}]\nrules: []\n")
        try:
            with unittest.mock.patch.object(build_module, "_pick",
                                            side_effect=lambda stem: (broken, None)):
                self.assertEqual(build_module._build_page("2026-09-02"), 1)
        finally:
            broken.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
