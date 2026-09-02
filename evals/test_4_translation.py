"""EVAL 4 — One policy, translated to each target in that target's own terms.

This is the claim the product is named for, and none of the first three suites test it.
EVAL 2 proves an instruction TRACES to a rule. It does not prove the instruction is the
right one: before this suite existed, a content rule on Screen Time rendered "Downtime →
set the window / confirm: Downtime is ON", because steps lived on the surface rather than
on the (rule, target) pair. 18 of 21 pairs were wrong that way.

That is a coverage lie with extra steps — you follow the instruction, confirm the wrong
setting, and mark the rule verified.

Bar: 100%.
"""
import unittest

import yaml

from evals import harness
from plane.model import PolicyError, load
from plane.plan import build


def real():
    return build(load(harness.REPO / "policy.yaml", harness.REPO / "status.yaml"),
                 harness.TODAY)


def broken(mutate):
    raw = yaml.safe_load((harness.REPO / "policy.yaml").read_text())
    mutate(raw)
    path = harness.FIXTURES / "_tmp-policy.yaml"
    path.write_text(yaml.safe_dump(raw))
    try:
        return load(path, None)
    finally:
        path.unlink(missing_ok=True)


class OnePolicyManyTargets(unittest.TestCase):

    def setUp(self):
        self.plan = real()
        self.policy = load(harness.REPO / "policy.yaml", None)

    def test_some_rules_reach_at_least_two_targets(self):
        """The premise. If every rule had one target there would be nothing to translate."""
        multi = [r for r in self.plan["rules"]
                 if sum(1 for s in self.plan["surfaces"]
                        if self.plan["cells"][(r["id"], s["id"])]["applicable"]) >= 2]
        self.assertGreaterEqual(len(multi), 4,
                                "most rules should fan out to two or more targets")

    def test_each_instruction_is_written_for_its_own_rule_kind(self):
        """The defect this suite was built for."""
        for item in self.plan["checklist"]:
            surface = self.policy.surface(item["surface"])
            rule = self.policy.rule(item["rule"])
            self.assertIn(rule.kind, surface.how,
                          f"{surface.id} carries a {rule.kind} rule with no {rule.kind} "
                          "instructions")
            self.assertEqual(list(item["steps"]), list(surface.how[rule.kind].steps))
            self.assertEqual(item["check"], surface.how[rule.kind].check)

    def test_different_kinds_on_one_target_get_different_procedures(self):
        """Screen Time's bedtime path and its content path are different screens."""
        for surface in self.policy.surfaces:
            procedures = {k: (h.steps, h.check) for k, h in surface.how.items()}
            self.assertEqual(len(set(procedures.values())), len(procedures),
                             f"{surface.id} reuses one procedure for two different kinds")

    def test_one_rule_on_two_targets_gets_two_different_procedures(self):
        """The translation claim, stated directly."""
        by_rule = {}
        for item in self.plan["checklist"]:
            by_rule.setdefault(item["rule"], []).append(item)
        checked = 0
        for rule_id, items in by_rule.items():
            if len(items) < 2:
                continue
            checked += 1
            shapes = {(tuple(i["steps"]), i["check"]) for i in items}
            self.assertEqual(len(shapes), len(items),
                             f"{rule_id} produces the same words on two different apps")
        self.assertGreaterEqual(checked, 3, "too few multi-target rules to be meaningful")

    def test_the_confirm_text_differs_per_target(self):
        """What you look at to prove it worked is target-specific, or it proves nothing."""
        by_rule = {}
        for item in self.plan["checklist"]:
            by_rule.setdefault(item["rule"], []).append(item["check"])
        for rule_id, checks in by_rule.items():
            self.assertEqual(len(set(checks)), len(checks),
                             f"{rule_id} asks you to confirm the same thing twice")


class TheCatalogIsHonest(unittest.TestCase):
    """`can` is a claim about a product. It has to be backed by a click-path."""

    def setUp(self):
        self.policy = load(harness.REPO / "policy.yaml", None)
        self.plan = real()

    def test_claiming_a_control_without_saying_how_fails_the_load(self):
        def mutate(raw):
            thin = next(s for s in raw["surfaces"] if len(s["can"]) == 1)
            thin["can"].append("schedule")        # claimed, with no click-path
        with self.assertRaises(PolicyError):
            broken(mutate)

    def test_claiming_a_control_without_saying_which_params_fails_the_load(self):
        """Same rule one level down: you cannot claim a control and stay vague about
        which of its parameters you can actually honour."""
        def mutate(raw):
            for surf in raw["surfaces"]:
                for block in surf["how"].values():
                    block.pop("accepts", None)
        with self.assertRaises(PolicyError):
            broken(mutate)

    def test_instructions_for_an_unclaimed_control_fail_the_load(self):
        def mutate(raw):
            raw["surfaces"][2]["how"]["schedule"] = {"steps": ["x"], "check": "y"}
        with self.assertRaises(PolicyError):
            broken(mutate)

    def test_every_claimed_control_has_real_steps_and_a_check(self):
        for surface in self.policy.surfaces:
            for kind, how in surface.how.items():
                self.assertTrue(how.steps, f"{surface.id}.{kind} has no steps")
                self.assertTrue(how.check.strip(), f"{surface.id}.{kind} has no check")

    def test_every_claimed_control_records_what_depth_it_offers(self):
        """The catalog half: what you'd otherwise have to open the app to discover."""
        for surface in self.policy.surfaces:
            for kind, how in surface.how.items():
                self.assertTrue(how.options.strip(),
                                f"{surface.id}.{kind} does not say what the app offers")

    def test_the_catalog_matches_what_each_surface_claims(self):
        for surf in self.plan["surfaces"]:
            self.assertEqual(sorted(e["kind"] for e in surf["catalog"]),
                             sorted(surf["can"]))

    def test_unused_controls_are_surfaced_not_hidden(self):
        """A control an app offers that no rule asks for is worth knowing about."""
        unused = [(s["id"], e["kind"]) for s in self.plan["surfaces"]
                  for e in s["catalog"] if not e["used_by"]]
        self.assertTrue(unused, "fixture should have at least one unused control")


if __name__ == "__main__":
    unittest.main()
