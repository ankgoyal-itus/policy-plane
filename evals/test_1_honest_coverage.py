"""EVAL 1 — Coverage is never overstated.

The product's whole claim is that the page tells you the truth. The failure that matters
is the one direction: telling a parent a rule is in force when it isn't. Every state
except `verified` must read as a gap.

Bar: 100%. Any failure here means the page can lie.
"""
import sys
import html as html_mod
import unittest
import unittest.mock

from evals import harness

sys.path.insert(0, str(harness.REPO))
from plane import plan as plan_mod
from plane import render as render_mod
from plane.model import load
from plane.plan import build
from plane.render import render


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


class HeroTilesAgreeWithTheRows(unittest.TestCase):
    """The tiles must be derivable from the cells, and must move when a reading lands.

    They were server-rendered once and never touched again, so a verification updated its
    row and left the largest numbers on the page saying what they said before it — a
    snapshot presented as live, on a page whose claim is that only a reading you have
    actually taken counts.

    Two separate failures are guarded here. The counts must equal what the rows say (no
    second counting path), and a new observation must actually change the relevant tile.
    """

    def _plan(self, observations=()):
        policy = load(harness.REPO / "policy.yaml", harness.REPO / "status.yaml")
        return build(policy, harness.TODAY, observations)

    def _tiles(self, plan):
        return {t["key"]: t["value"] for t in render_mod.stat_tiles(plan["summary"])}

    def test_the_tiles_are_derived_from_the_cells_not_counted_separately(self):
        plan = self._plan()
        cells = [c for c in plan["cells"].values() if c["applicable"]]
        covered = [c for c in cells
                   if c["state"] in plan_mod.COVERED_STATES and c["depth"] == plan_mod.FULL]
        tiles = self._tiles(plan)

        self.assertEqual(tiles["attested"], str(sum(1 for c in covered if not c.get("observed"))))
        self.assertEqual(tiles["todo"],
                         str(sum(1 for c in cells if c["state"] not in plan_mod.COVERED_STATES)))
        self.assertEqual(tiles["stale"],
                         str(sum(1 for c in cells if c["state"] == plan_mod.STALE)))

    def test_need_attention_equals_the_checklist_the_page_shows(self):
        """One metric, two implementations. They agree today; nothing made them."""
        plan = self._plan()
        self.assertEqual(self._tiles(plan)["todo"], str(len(plan["checklist"])),
                         "the tile and the 'items a human must still do' row disagree")

    def test_nothing_read_shows_a_dash_not_a_zero(self):
        """"We have not looked" and "we looked and found none" are different claims."""
        self.assertEqual(self._tiles(self._plan())["read"], "—")

    def test_one_observation_moves_the_read_tile(self):
        before = self._tiles(self._plan())
        rule = next(r for r in self._plan()["rules"] if r["kind"] == "time")
        surface = next(s for s in self._plan()["surfaces"]
                       if (rule["id"], s["id"]) in self._plan()["cells"]
                       and self._plan()["cells"][(rule["id"], s["id"])]["applicable"]
                       and self._plan()["cells"][(rule["id"], s["id"])].get("recipe"))
        obs = [{
            "rule": rule["id"], "surface": surface["id"],
            "at": harness.TODAY + "T12:00:00Z", "code": "OK",
            "params": {"minutesPerDay": rule["params"]["minutes_per_day"]},
            "readings": {"dailyLimitText": str(rule["params"]["minutes_per_day"])},
        }]
        after = self._tiles(self._plan(obs))
        self.assertEqual(before["read"], "—", "fixture should start with nothing read")
        self.assertEqual(after["read"], "1",
                         "a reading that is in force did not move the read tile")
        self.assertNotEqual(before["todo"], after["todo"],
                            "a reading that covers a pair did not reduce need-attention")


class EveryDeviceAnsweredSeparately(unittest.TestCase):
    """For THIS child, on THIS device, does the rule hold?

    The matrix could never answer it: it pairs rules with surfaces, and a surface is not
    a device. A rule reaches a device only through a surface that both carries the rule
    and reaches that device — and a device reached by nothing is the finding rather than
    an omission.
    """

    def setUp(self):
        self.policy = load(harness.REPO / "policy.yaml", harness.REPO / "status.yaml")
        self.plan = build(self.policy, harness.TODAY)
        self.by_device = self.plan["by_device"]

    def test_every_kid_device_pairing_appears_exactly_once(self):
        seen = [(d["kid"], d["device"]) for d in self.by_device]
        expected = [(k.id, dev.id) for k in self.policy.kids
                    for dev in self.policy.devices_of(k.id)]
        self.assertEqual(sorted(seen), sorted(expected))
        self.assertEqual(len(seen), len(set(seen)), "a pairing was listed twice")

    def test_a_device_only_lists_rules_for_the_child_who_uses_it(self):
        for d in self.by_device:
            for r in d["rules"]:
                with self.subTest(f'{d["device"]}/{r["rule"]}'):
                    self.assertEqual(self.policy.rule(r["rule"]).kid, d["kid"])

    def test_account_surfaces_never_appear_in_the_device_fan_out(self):
        """An account follows the child, not the hardware. Listing Roblox under four
        devices would show one reading four times and read as four checks."""
        accounts = {s.id for s in self.policy.surfaces if s.governs == "account"}
        self.assertTrue(accounts, "fixture should have account surfaces")
        for d in self.by_device:
            for r in d["rules"]:
                with self.subTest(f'{d["device"]}/{r["rule"]}'):
                    self.assertFalse(set(r["via"]) & accounts,
                                     f'{r["via"]} includes an account surface')

    def test_a_network_surface_does_not_reach_a_device_off_the_network(self):
        """Sam's phone on cellular is outside the routers. That is a real hole."""
        networks = {s.id for s in self.policy.surfaces if s.governs == "network"}
        off = [d for d in self.by_device if not d["on_home_network"]]
        self.assertTrue(off, "fixture should have a device off the home network")
        for d in off:
            for r in d["rules"]:
                with self.subTest(f'{d["device"]}/{r["rule"]}'):
                    self.assertFalse(set(r["via"]) & networks,
                                     "a network surface reached a device that is not on it")

    def test_a_device_surface_only_reaches_the_device_it_names(self):
        by_id = {s.id: s for s in self.policy.surfaces}
        for d in self.by_device:
            for r in d["rules"]:
                for sid in r["via"]:
                    if by_id[sid].governs == "device":
                        with self.subTest(sid):
                            self.assertEqual(by_id[sid].device, d["device"])

    def test_a_rule_that_reaches_nothing_is_reported_not_dropped(self):
        stuck = [(d["device"], r["rule"]) for d in self.by_device
                 for r in d["rules"] if not r["reachable"]]
        self.assertTrue(stuck, "the shipped policy should have at least one real gap; "
                               "if it has none, this guard is watching nothing")
        for device, rule in stuck:
            with self.subTest(f"{device}/{rule}"):
                row = next(r for d in self.by_device if d["device"] == device
                           for r in d["rules"] if r["rule"] == rule)
                self.assertEqual(row["via"], [])
                self.assertIsNone(row["state"])

    def test_the_page_shows_the_per_device_answer(self):
        html = render(self.plan)
        self.assertIn("Every device, one by one", html)
        for d in self.by_device:
            with self.subTest(d["device"]):
                self.assertIn(html_mod.escape(d["device_name"]), html)
