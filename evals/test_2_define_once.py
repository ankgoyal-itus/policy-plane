"""EVAL 2 — Define once.

The product's name for itself. Every instruction a parent sees must trace back to exactly
one rule they wrote; changing the rule must change everything derived from it; deleting
the rule must delete them. If an instruction can exist that no rule asked for, or a rule
can change without its instructions following, "define once" is just a slogan.

Bar: 100%.
"""
import unittest

import yaml

from evals import harness
from plane.model import load
from plane.plan import build

SCRATCH = harness.REPO / "evals" / "fixtures" / "_tmp-policy.yaml"


def plan_from(raw, today=harness.TODAY):
    SCRATCH.write_text(yaml.safe_dump(raw))
    try:
        return build(load(SCRATCH, None), today)
    finally:
        SCRATCH.unlink(missing_ok=True)


def base():
    return yaml.safe_load(harness.MINI.read_text())


class DefineOnce(unittest.TestCase):

    def setUp(self):
        self.plan = build(load(harness.MINI, None), harness.TODAY)

    def test_every_checklist_item_traces_to_a_declared_rule(self):
        declared = {r["id"] for r in self.plan["rules"]}
        for item in self.plan["checklist"]:
            self.assertIn(item["rule"], declared, "orphan instruction with no rule")

    def test_every_checklist_item_traces_to_a_declared_surface(self):
        declared = {s["id"] for s in self.plan["surfaces"]}
        for item in self.plan["checklist"]:
            self.assertIn(item["surface"], declared)

    def test_no_instruction_exists_for_a_pair_the_surface_cannot_do(self):
        """The orphan rule is `purchase`; the only surface does schedule and contact."""
        for item in self.plan["checklist"]:
            self.assertNotEqual(item["rule"], "r-orphan",
                                "generated an instruction no app can carry out")

    def test_changing_a_rule_changes_every_instruction_derived_from_it(self):
        raw = base()
        raw["rules"][0]["params"]["not_after"] = "19:15"
        after = plan_from(raw)
        derived = [i for i in after["checklist"] if i["rule"] == "r-schedule"]
        self.assertTrue(derived, "the rule should still produce instructions")
        for item in derived:
            self.assertIn("19:15", item["say"])
            self.assertEqual(item["params"]["not_after"], "19:15")

    def test_deleting_a_rule_deletes_its_instructions(self):
        raw = base()
        raw["rules"] = [r for r in raw["rules"] if r["id"] != "r-schedule"]
        after = plan_from(raw)
        self.assertEqual([i for i in after["checklist"] if i["rule"] == "r-schedule"], [])

    def test_adding_a_surface_extends_every_rule_it_can_carry(self):
        """Define once, apply everywhere: a new app inherits the existing rules without
        anyone rewriting them."""
        raw = base()
        raw["surfaces"].append({
            "id": "third", "name": "Third Surface", "covers": ["kid"],
            "can": ["schedule", "purchase"], "recheck_days": 30,
            "governs": "network", "app": "*",
            "how": {"schedule": {"steps": ["Third route"], "check": "Third check",
                                 "accepts": ["not_after", "days"]},
                    "purchase": {"steps": ["Buy screen"], "check": "Approvals are on",
                                 "accepts": ["require_approval"]}}})
        after = plan_from(raw)
        pairs = {(i["rule"], i["surface"]) for i in after["checklist"]}
        self.assertIn(("r-schedule", "third"), pairs)
        self.assertIn(("r-orphan", "third"), pairs, "the orphan rule is now reachable")

    def test_the_rule_text_is_never_restated_in_the_plan(self):
        """One source of truth: instructions carry the rule's own words, not a copy
        someone edited separately."""
        says = {r["id"]: r["say"] for r in self.plan["rules"]}
        for item in self.plan["checklist"]:
            self.assertEqual(item["say"], says[item["rule"]])

    def test_the_plan_is_the_same_every_time(self):
        again = build(load(harness.MINI, None), harness.TODAY)
        self.assertEqual(str(self.plan), str(again))


if __name__ == "__main__":
    unittest.main()
