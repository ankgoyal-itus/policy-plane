"""EVAL 7 — Every attempt leaves a trace, and no value ever does.

observations.json only ever hears about a SUCCESSFUL read -- the page's verify script
posts to it after `if (!res.ok) { ...; return; }`, so a NEEDS_LOGIN or a TIMEOUT left no
trace anywhere once the tab closed. The audit log exists to close that gap without
becoming a second copy of the judge's input: it records every attempt, success or
failure, and it never keeps a raw param value -- only a hash of one. This suite guards
both halves: the shape of one audit record (`_audit_entry`), and that the rendered page
actually calls it from BOTH branches, not just the one that already had somewhere to
report.

Bar: 100%.
"""
import json
import re
import unittest

import build
from evals import harness
from plane.model import load
from plane.plan import build as build_plan
from plane.render import render

POST_AUDIT_CALL = re.compile(r"postAudit\(\{")  # a CALL passes an object; the
                                                 # definition `postAudit(fields)` does not


class AuditEntryShape(unittest.TestCase):
    """`_audit_entry` is the one function deciding what a record contains -- proving
    it here means no test anywhere has to re-derive the HTTP layer to check it."""

    def test_never_contains_a_raw_param_value(self):
        entry = build._audit_entry({
            "runId": "run-123", "rule": "r-schedule", "surface": "sim-family-console",
            "recipe": "family-console-schedule-verify", "code": "OK",
            "failingStep": None,
            "params": {"childUsername": "a-very-distinctive-name-9f3c"},
        })
        blob = json.dumps(entry)
        self.assertNotIn("a-very-distinctive-name-9f3c", blob)
        self.assertIn("paramsHash", entry)
        self.assertEqual(len(entry["paramsHash"]), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in entry["paramsHash"]))

    def test_records_a_failure_with_its_failing_step(self):
        entry = build._audit_entry({
            "runId": "run-1", "rule": "r1", "surface": "s1", "recipe": "rec1",
            "code": "NEEDS_LOGIN", "failingStep": "roster.section", "params": {},
        })
        self.assertEqual(entry["code"], "NEEDS_LOGIN")
        self.assertEqual(entry["failingStep"], "roster.section")

    def test_hash_is_order_independent(self):
        e1 = build._audit_entry({"params": {"a": 1, "b": 2}})
        e2 = build._audit_entry({"params": {"b": 2, "a": 1}})
        self.assertEqual(e1["paramsHash"], e2["paramsHash"])

    def test_hash_is_sensitive_to_the_value(self):
        e1 = build._audit_entry({"params": {"childUsername": "sam_example"}})
        e2 = build._audit_entry({"params": {"childUsername": "alex_example"}})
        self.assertNotEqual(e1["paramsHash"], e2["paramsHash"])

    def test_a_missing_field_becomes_none_not_a_crash(self):
        entry = build._audit_entry({"rule": "r1"})
        self.assertIsNone(entry["runId"])
        self.assertIsNone(entry["failingStep"])


class DemoModeRouting(unittest.TestCase):
    """Same discipline as observations.json: a demo never opens the real file, and
    stale demo data is rotated aside rather than silently deleted."""

    FILES = ["observations.demo.json", "observations.demo.prev.json",
             "audit.demo.json", "audit.demo.prev.json"]

    def setUp(self):
        for name in self.FILES:
            (build.HERE / name).unlink(missing_ok=True)
        self.addCleanup(self._clean)

    def _clean(self):
        for name in self.FILES:
            (build.HERE / name).unlink(missing_ok=True)
        build.OBSERVATIONS = build.HERE / "observations.json"
        build.AUDIT = build.HERE / "audit.json"

    def test_demo_mode_points_audit_at_a_scratch_file(self):
        build.use_demo_observations()
        self.assertEqual(build.AUDIT.name, "audit.demo.json")
        self.assertEqual(build.AUDIT.read_text().strip(), "[]")

    def test_demo_mode_never_touches_the_real_audit_file(self):
        real = build.HERE / "audit.json"
        real.write_text(json.dumps([{"rule": "should-survive"}]) + "\n")
        self.addCleanup(real.unlink, missing_ok=True)
        before = real.read_text()
        build.use_demo_observations()
        self.assertEqual(real.read_text(), before)

    def test_a_nonempty_previous_demo_audit_file_is_rotated_not_deleted(self):
        build.use_demo_observations()
        build.AUDIT.write_text(json.dumps([{"rule": "r1"}]) + "\n")
        build.use_demo_observations()
        prev = build.HERE / "audit.demo.prev.json"
        self.assertTrue(prev.exists(), "a nonempty demo audit file must be kept, not lost")
        self.assertEqual(json.loads(prev.read_text()), [{"rule": "r1"}])
        self.assertEqual(build.AUDIT.read_text().strip(), "[]")


class VerifyScriptCallsAudit(unittest.TestCase):
    """The gap this suite exists to close: a page that only reports success leaves a
    failed read invisible forever. This proves the rendered page's script calls
    postAudit from BOTH the `if (!res.ok)` branch and the success branch -- deleting
    either call, or leaving the helper defined but never wired to one of them, is
    exactly the historical bug class this project's other wiring tests guard against."""

    def setUp(self):
        plan = build_plan(load(harness.REPO / "policy.yaml",
                               harness.REPO / "status.yaml"), harness.TODAY)
        self.html = render(plan)

    def test_postAudit_is_defined_exactly_once(self):
        self.assertEqual(self.html.count("function postAudit("), 1)

    def test_postAudit_is_called_from_both_branches(self):
        """Two calls: one before the failure `return`, one on the success path. A
        script that only calls it once no longer proves both branches are covered."""
        self.assertEqual(len(POST_AUDIT_CALL.findall(self.html)), 2)

    def test_the_failure_branch_calls_postAudit_before_its_own_return(self):
        m = re.search(r"if \(!res\.ok\) \{(.*?)\n\s*return;\s*\n\s*\}",
                      self.html, re.S)
        self.assertIsNotNone(m, "could not find the failure branch at all")
        self.assertIn("postAudit(", m.group(1))

    def test_the_success_branch_calls_postAudit_before_posting_to_observations(self):
        m = re.search(r"if \(!res\.ok\) \{.*?\n\s*return;\s*\n\s*\}(.*?)"
                      r"fetch\(\"/observations\"", self.html, re.S)
        self.assertIsNotNone(m, "could not find the success branch before /observations")
        self.assertIn("postAudit(", m.group(1))

    def test_a_failed_reads_audit_call_never_carries_the_word_observations(self):
        """postAudit posts to /audit, never /observations -- a failed read has no
        verdict and must never be recorded as one."""
        m = re.search(r"if \(!res\.ok\) \{(.*?)\n\s*return;\s*\n\s*\}",
                      self.html, re.S)
        self.assertNotIn("/observations", m.group(1))


if __name__ == "__main__":
    unittest.main()
