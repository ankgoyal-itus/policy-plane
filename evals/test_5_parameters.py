"""EVAL 5 — Typed parameters, app scoping, and partial support.

The parameter model is what makes this a policy point rather than a Roblox tool. Three
claims it has to hold up:

  - A rule means exactly one thing. Params are typed and validated; the English is
    GENERATED from them, so the sentence can never drift from what vendors are checked
    against.
  - A rule about one app does not get routed at another.
  - A vendor that honours only SOME of a rule's parameters is not enforcing the rule.
    Roblox's daily limit applies to every day, so a weekday-only rule quietly becomes an
    every-day one there. That is `partial`, and partial is not covered.

Bar: 100%.
"""
import unittest

import yaml

from evals import harness
from plane import params as P
from plane.model import PolicyError, load
from plane.plan import build

REAL = harness.REPO / "policy.yaml"


def plan_from(mutate=None):
    raw = yaml.safe_load(REAL.read_text())
    if mutate:
        mutate(raw)
    path = harness.FIXTURES / "_tmp-param.yaml"
    path.write_text(yaml.safe_dump(raw))
    try:
        return build(load(path, None), harness.TODAY)
    finally:
        path.unlink(missing_ok=True)


def rule_of(plan, rid):
    return next(r for r in plan["rules"] if r["id"] == rid)


class ParamsAreTyped(unittest.TestCase):

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaises(P.ParamError):
            P.validate("time", {"hours_per_day": 2}, "x")

    def test_out_of_range_is_rejected(self):
        with self.assertRaises(P.ParamError):
            P.validate("time", {"minutes_per_day": 5000}, "x")

    def test_a_rule_with_no_parameters_is_rejected(self):
        """A kind on its own says nothing. 'A time rule' is not a policy."""
        with self.assertRaises(P.ParamError):
            P.validate("time", {}, "x")

    def test_bad_clock_values_are_rejected(self):
        for bad in ("25:00", "9:99", "nine", "21-30"):
            with self.subTest(bad):
                with self.assertRaises(P.ParamError):
                    P.validate("schedule", {"not_after": bad}, "x")

    def test_days_are_canonicalised_not_rejected(self):
        got = P.validate("schedule", {"days": ["fri", "mon", "mon"]}, "x")
        self.assertEqual(got["days"], ("mon", "fri"))

    def test_a_bad_param_fails_the_whole_policy_load(self):
        def mutate(raw):
            raw["rules"][0]["params"]["minutes_per_day"] = -5
        with self.assertRaises(PolicyError):
            plan_from(mutate)


class EnglishIsGenerated(unittest.TestCase):

    def test_the_sentence_carries_the_parameter_values(self):
        plan = plan_from()
        say = rule_of(plan, "alex-roblox-time")["say"]
        self.assertIn("90", say)
        self.assertIn("Roblox", say)

    def test_changing_a_parameter_changes_the_sentence(self):
        """The sentence cannot drift from the params, because it is derived from them."""
        before = rule_of(plan_from(), "alex-roblox-time")["say"]
        after = rule_of(
            plan_from(lambda raw: raw["rules"][0]["params"].update(minutes_per_day=30)),
            "alex-roblox-time")["say"]
        self.assertNotEqual(before, after)
        self.assertIn("30", after)

    def test_the_policy_file_cannot_author_a_sentence(self):
        """`say` is not an input. Allowing one would let the words and the params
        disagree, which is the whole failure this design removes."""
        with self.assertRaises(PolicyError):
            plan_from(lambda raw: raw["rules"][0].update(say="whatever I like"))


class AppScoping(unittest.TestCase):

    def test_an_app_scoped_rule_does_not_reach_a_different_app(self):
        """Discriminating on APP, not on kind.

        Found by mutation testing: the first version of this checked a `time` rule
        against YouTube, which only does `content` -- so it was excluded on kind and
        passed happily with app scoping deleted entirely. The rule below is a `content`
        rule, and both Roblox and YouTube handle `content`, so only the app gate can
        separate them.
        """
        def scope_content_to_roblox(raw):
            rule = next(r for r in raw["rules"] if r["id"] == "alex-content")
            rule["app"] = "roblox"

        plan = plan_from(scope_content_to_roblox)
        self.assertTrue(plan["cells"][("alex-content", "roblox-alex")]["applicable"],
                        "should still reach the app it names")
        self.assertFalse(plan["cells"][("alex-content", "youtube-alex")]["applicable"],
                         "a Roblox rule must not be routed at YouTube")

    def test_an_unscoped_content_rule_reaches_both_apps(self):
        """The other half. Without this, 'reaches nothing' would pass the test above."""
        plan = plan_from()
        self.assertTrue(plan["cells"][("alex-content", "roblox-alex")]["applicable"])
        self.assertTrue(plan["cells"][("alex-content", "youtube-alex")]["applicable"])

    def test_a_roblox_rule_does_route_to_roblox(self):
        plan = plan_from()
        self.assertTrue(plan["cells"][("alex-roblox-time", "roblox-alex")]["applicable"])

    def test_a_roblox_rule_routes_to_device_level_surfaces(self):
        """A device-level surface (app: '*') governs everything running on it."""
        plan = plan_from()
        self.assertTrue(
            plan["cells"][("alex-roblox-time", "screentime-ipad")]["applicable"])

    def test_an_unscoped_rule_reaches_every_capable_surface(self):
        plan = plan_from()
        reached = [s["id"] for s in plan["surfaces"]
                   if plan["cells"][("alex-content", s["id"])]["applicable"]]
        self.assertGreaterEqual(len(reached), 4)


class PartialIsNotCovered(unittest.TestCase):

    def test_a_vendor_dropping_a_param_is_marked_partial(self):
        """Roblox cannot express 'weekdays only'; its limit applies every day."""
        plan = plan_from()
        cell = plan["cells"][("alex-bedtime", "roblox-alex")]
        self.assertEqual(cell["depth"], "partial")
        self.assertIn("days", cell["dropped"])

    def test_a_verified_partial_pair_is_still_not_covered(self):
        """The one that matters. Confirm a pair Roblox can only half-express, and it
        must land in partial_by -- never in covered_by. The parent went and set
        something; it still is not the rule they wrote."""
        status = harness.FIXTURES / "_tmp-status.yaml"
        status.write_text(yaml.safe_dump([{
            "rule": "alex-bedtime", "surface": "roblox-alex",
            "state": "verified", "date": harness.TODAY, "by": "tester"}]))
        try:
            plan = build(load(REAL, status), harness.TODAY)
        finally:
            status.unlink(missing_ok=True)

        cell = plan["cells"][("alex-bedtime", "roblox-alex")]
        self.assertEqual(cell["state"], "verified")
        self.assertEqual(cell["depth"], "partial")

        rule = rule_of(plan, "alex-bedtime")
        self.assertNotIn("roblox-alex", rule["covered_by"])
        self.assertIn("roblox-alex", rule["partial_by"])

    def test_nothing_verified_and_partial_leaks_into_covered_anywhere(self):
        plan = plan_from()
        for rule in plan["rules"]:
            for sid in rule["covered_by"]:
                self.assertEqual(plan["cells"][(rule["id"], sid)]["depth"], "full",
                                 f"{rule['id']} counts {sid} as covered while partial")

    def test_partial_is_reported_not_hidden(self):
        plan = plan_from()
        partials = [(r["id"], s["id"]) for r in plan["rules"] for s in plan["surfaces"]
                    if plan["cells"][(r["id"], s["id"])]["applicable"]
                    and plan["cells"][(r["id"], s["id"])]["depth"] == "partial"]
        self.assertTrue(partials, "the example should exercise at least one partial")
        for rid, sid in partials:
            self.assertTrue(plan["cells"][(rid, sid)]["dropped"],
                            "a partial must name which params it drops")

    def test_a_vendor_honouring_every_param_is_full(self):
        plan = plan_from()
        cell = plan["cells"][("alex-roblox-time", "roblox-alex")]
        self.assertEqual(cell["depth"], "full")
        self.assertEqual(cell["dropped"], [])


if __name__ == "__main__":
    unittest.main()
