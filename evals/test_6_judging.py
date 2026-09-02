"""EVAL 6 — The plane judges; the extension only reads.

An automated read is worth more than a memory, and worth less than it looks if the thing
that did the reading also rules on it. So the verdict is computed here, in Python, from
the RAW TEXT the page showed -- never from a number the extension worked out.

The verdict that matters most is `unexpressible`. "Roblox does not offer 90 minutes" and
"you never set it" produce the same empty cell and demand opposite actions: one sends you
to rewrite the rule, the other sends you to Roblox.

Bar: 100%.
"""
import unittest

from evals import harness
from plane import observe
from plane.model import load
from plane.plan import build

REAL = harness.REPO / "policy.yaml"
PAIR = ("alex-roblox-time", "roblox-alex")


def observation(daily, offered, code="OK", at="2026-09-01T10:00:00Z", **extra):
    return dict({"rule": PAIR[0], "surface": PAIR[1], "recipe": "test",
                 "at": at, "code": code,
                 "readings": {"dailyLimitText": daily, "offeredText": list(offered)}},
                **extra)


def cell(obs, today=harness.TODAY):
    plan = build(load(REAL, None), today, [obs] if obs else [])
    return plan["cells"][PAIR]


class ReadingIsNotJudging(unittest.TestCase):

    def test_the_judge_reparses_the_raw_text_itself(self):
        """It must not take the extension's word for what the page said."""
        got = observe.judge_time(90, "1 hour 30 minutes", ["1 hour 30 minutes"])
        self.assertEqual(got["observed_minutes"], 90)

    def test_a_disagreement_between_reader_and_judge_is_not_satisfied(self):
        """If the extension's own parse differs from ours, the reading is unreliable and
        the pair must not go green on it."""
        obs = observation("1 hour 30 minutes", ["1 hour 30 minutes"])
        obs["readings"]["advisoryMinutes"] = 60          # disagrees with our 90
        rule = load(REAL, None).rule(PAIR[0])
        got = observe.judge(rule, obs)
        self.assertEqual(got["verdict"], observe.UNKNOWN)
        self.assertFalse(got["in_force"])

    def test_a_failed_read_is_never_satisfied_even_with_plausible_readings(self):
        """The dangerous shape: a half-loaded page that errored but left readable text.

        Found by mutation testing. The first version passed empty readings, so deleting
        the error check entirely still produced UNKNOWN -- via the parser, not via the
        check. These readings would otherwise judge as a clean pass.
        """
        rule = load(REAL, None).rule(PAIR[0])
        for code in ("NEEDS_LOGIN", "NOT_LINKED", "SELECTOR_NOT_FOUND", "TIMEOUT",
                     "NEEDS_REAUTH", "WRONG_ACCOUNT"):
            with self.subTest(code):
                got = observe.judge(rule, observation(
                    "1 hour 30 minutes", ["1 hour 30 minutes"], code=code))
                self.assertEqual(got["verdict"], observe.UNKNOWN,
                                 f"{code} produced a verdict from an incomplete read")
                self.assertFalse(got["in_force"])

    def test_a_kind_with_no_automated_check_is_unknown_not_satisfied(self):
        rule = load(REAL, None).rule("alex-content")
        got = observe.judge(rule, observation("whatever", []))
        self.assertFalse(got["in_force"])


class Verdicts(unittest.TestCase):

    def test_exact_match_is_satisfied_and_covers(self):
        got = cell(observation("1 hour 30 minutes",
                               ["30 minutes", "1 hour", "1 hour 30 minutes"]))
        self.assertEqual(got["verdict"], "satisfied")
        self.assertEqual(got["state"], "verified")

    def test_stricter_than_asked_still_counts(self):
        """60 when you asked for 90 means the child is more protected, not less."""
        got = cell(observation("1 hour", ["1 hour", "1 hour 30 minutes"]))
        self.assertEqual(got["verdict"], "stricter")
        self.assertEqual(got["state"], "verified")

    def test_looser_than_asked_does_not_count(self):
        got = cell(observation("2 hours", ["1 hour 30 minutes", "2 hours"]))
        self.assertEqual(got["verdict"], "not_satisfied")
        self.assertNotEqual(got["state"], "verified")

    def test_unexpressible_is_not_in_force_at_the_contract_level(self):
        """Asserted directly on the judge, not only through the plan.

        Found by mutation testing: adding UNEXPRESSIBLE to IN_FORCE passed every suite,
        because the plan's state machine returns `unexpressible` before it ever consults
        `in_force`. The flag was untested and anyone reading it would have got a wrong
        answer.
        """
        got = observe.judge_time(90, "1 hour", ["30 minutes", "1 hour", "2 hours"])
        self.assertEqual(got["verdict"], observe.UNEXPRESSIBLE)
        self.assertFalse(got["in_force"])
        self.assertNotIn(observe.UNEXPRESSIBLE, observe.IN_FORCE)

    def test_only_satisfied_and_stricter_are_in_force(self):
        self.assertEqual(set(observe.IN_FORCE), {observe.SATISFIED, observe.STRICTER})

    def test_a_value_the_vendor_does_not_offer_is_unexpressible(self):
        got = cell(observation("1 hour", ["30 minutes", "1 hour", "2 hours"]))
        self.assertEqual(got["state"], "unexpressible")
        self.assertIn("not on the list", got["why"])

    def test_unexpressible_never_counts_as_covered(self):
        plan = build(load(REAL, None), harness.TODAY,
                     [observation("1 hour", ["30 minutes", "1 hour", "2 hours"])])
        rule = next(r for r in plan["rules"] if r["id"] == PAIR[0])
        self.assertNotIn(PAIR[1], rule["covered_by"])

    def test_unreadable_text_is_unknown_not_zero(self):
        """'we could not read it' and 'it is set to zero' are opposite facts."""
        self.assertIsNone(observe.parse_minutes("banana"))
        got = cell(observation("banana", ["1 hour 30 minutes"]))
        self.assertNotEqual(got["state"], "verified")

    def test_no_limit_is_unlimited_and_never_in_force(self):
        """CHANGED DELIBERATELY on 2026-09-02, and the reason matters.

        This test used to assert parse_minutes("None") == 0. Roblox's real dropdown leads
        with "No limit", and reading that as 0 minutes made a child with UNLIMITED Roblox
        judge as STRICTER than any rule -- so the cell went green. That is the exact
        over-report-coverage failure this repo exists to prevent, and it was live.

        "None" is now read the same way. The text alone cannot tell you whether a vendor
        means "no limit" or "none allowed", and fail-closed means assuming the less
        protective reading: a false negative costs a wasted check, a false positive costs
        a child with no limit and a tick beside it.
        """
        for text in ("No limit", "no limits", "None", "unlimited", "Off"):
            with self.subTest(text):
                self.assertEqual(observe.parse_minutes(text), observe.UNLIMITED)

        got = observe.judge_time(90, "No limit",
                                 ["No limit", "1 Hour", "1 Hour 30 minutes"])
        self.assertEqual(got["verdict"], observe.NOT_SATISFIED)
        self.assertFalse(got["in_force"])
        self.assertTrue(got["observed_unlimited"])
        self.assertIsNone(got["observed_minutes"])

    def test_roblox_real_option_text_parses(self):
        """The actual list, mixed capitalisation and all."""
        cases = {"No limit": observe.UNLIMITED, "15 minutes": 15, "45 minutes": 45,
                 "1 Hour": 60, "1 Hour 15 minutes": 75, "1 Hour 30 minutes": 90,
                 "2 hours": 120, "2 hours 45 minutes": 165, "10 hours 30 minutes": 630}
        for text, want in cases.items():
            with self.subTest(text):
                self.assertEqual(observe.parse_minutes(text), want)

    def test_an_old_observation_goes_stale_like_any_other_claim(self):
        """A read from three months ago is as stale as a memory from three months ago."""
        got = cell(observation("1 hour 30 minutes", ["1 hour 30 minutes"],
                               at="2026-01-05T10:00:00Z"))
        self.assertEqual(got["state"], "stale")

    def test_an_observation_outranks_a_self_attestation(self):
        """The page said it. That beats remembering setting it."""
        got = cell(observation("2 hours", ["1 hour 30 minutes", "2 hours"]))
        self.assertTrue(got["observed"])
        self.assertNotEqual(got["state"], "verified")


class TheContractWithTheExtension(unittest.TestCase):
    """The plane and the extension are separate halves and cannot import each other.

    recipes/schemas.json is the contract between them. Before it existed, the plane
    rendered a Verify button that omitted a param the recipe required, and the only
    place that surfaced was BAD_PARAMS in the browser at click time.
    """

    def setUp(self):
        from plane.plan import recipe_schemas
        self.schemas = recipe_schemas()
        self.plan = build(load(REAL, harness.REPO / "status.yaml"), harness.TODAY)

    def test_the_schema_file_exists_and_is_not_empty(self):
        self.assertTrue(self.schemas, "recipes/schemas.json missing — regenerate it")

    def test_every_offered_button_supplies_every_required_param(self):
        for v in self.plan["verifiable"]:
            with self.subTest(f'{v["surface"]}/{v["recipe"]}'):
                required = set(self.schemas.get(v["recipe"], {}).get("required", ()))
                self.assertEqual(required - set(v["params"]), set(),
                                 "this button would fail with BAD_PARAMS when clicked")
                self.assertEqual(v["blocked"], [])

    def test_a_pair_that_cannot_supply_a_param_is_blocked_with_a_reason(self):
        """Fail at build time and say why, rather than offering a button that cannot work."""
        import yaml
        raw = yaml.safe_load(REAL.read_text())
        for kid in raw["kids"]:
            kid.pop("accounts", None)              # nobody has a Roblox username now
        path = harness.FIXTURES / "_tmp-noacct.yaml"
        path.write_text(yaml.safe_dump(raw))
        try:
            plan = build(load(path, None), harness.TODAY)
        finally:
            path.unlink(missing_ok=True)
        blocked = [v for v in plan["verifiable"] if v["blocked"]]
        self.assertTrue(blocked, "a pair missing a required param must be blocked")
        for v in blocked:
            # Assert the BEHAVIOUR, not a specific field name. This test used to name
            # childUsername and broke the moment Roblox switched to routing by id --
            # which told us nothing about whether blocking still worked.
            required = set(self.schemas[v["recipe"]]["required"])
            self.assertTrue(set(v["blocked"]) <= required)
            self.assertTrue(set(v["blocked"]) & required, "blocked nothing that is required")
            self.assertTrue(v["why_blocked"], "a blocked pair must say why")

    def test_the_plane_sends_nothing_a_recipe_did_not_declare(self):
        """An UNKNOWN param fails a run exactly as hard as a missing one.

        The plane knows things a recipe has no use for -- Roblox routes by numeric id and
        has no need of a username -- so it must send precisely the declared set.
        """
        for v in self.plan["verifiable"]:
            with self.subTest(f'{v["surface"]}/{v["recipe"]}'):
                schema = self.schemas.get(v["recipe"], {})
                known = set(schema.get("required", ())) | set(schema.get("optional", ()))
                self.assertEqual(set(v["params"]) - known, set(),
                                 "this button sends a param the recipe would reject")

    def test_every_verify_recipe_reads_something(self):
        """A verify recipe that reads nothing verifies nothing.

        Probe recipes are exempt: they return a structural dump for selector authoring
        rather than named readings, and nothing judges their output.
        """
        for rid, schema in self.schemas.items():
            if schema["mode"] != "verify":
                continue
            with self.subTest(rid):
                self.assertTrue(schema["reads"], f"{rid} reads nothing")

    def test_only_verify_and_probe_recipes_ship(self):
        for rid, schema in self.schemas.items():
            with self.subTest(rid):
                self.assertIn(schema["mode"], ("verify", "probe"))

    def test_a_required_param_a_recipe_never_reads_or_uses_is_suspicious(self):
        """childUsername was required by two recipes and used by neither for a whole
        session, because removing selectOption left it dead. It is now READ back and
        asserted, so every required param has a job."""
        for rid, schema in self.schemas.items():
            with self.subTest(rid):
                if schema["mode"] != "verify":
                    continue
                if "childUsername" in schema["required"]:
                    self.assertIn("selectedChild", schema["reads"],
                                  f"{rid} requires childUsername but never checks it")


class TheChildBeingReadIsTheChildAskedFor(unittest.TestCase):

    def _judge(self, selected, expected="alex_example"):
        rule = load(REAL, None).rule(PAIR[0])
        obs = observation("1 hour 30 minutes", ["1 hour 30 minutes"])
        obs["params"] = {"childUsername": expected}
        obs["readings"]["selectedChild"] = selected
        return observe.judge(rule, obs)

    def test_the_right_child_reads_normally(self):
        self.assertEqual(self._judge("alex_example")["verdict"], observe.SATISFIED)

    def test_a_page_that_is_not_the_requested_child_is_never_in_force(self):
        # 424242424242 is invented. A real child id was used here briefly and reached a
        # commit; test data must never be real, however convenient the copy-paste.
        """For a recipe routed by id, the URL is the identity check -- free, and it
        cannot go missing the way a selector can."""
        rule = load(REAL, None).rule(PAIR[0])
        obs = observation("1 hour 30 minutes", ["1 hour 30 minutes"])
        obs["params"] = {"childUserId": 424242424242}
        obs["url"] = "https://www.roblox.com/login"
        got = observe.judge(rule, obs)
        self.assertEqual(got["verdict"], observe.UNKNOWN)
        self.assertFalse(got["in_force"])

    def test_the_right_child_url_reads_normally(self):
        rule = load(REAL, None).rule(PAIR[0])
        obs = observation("1 hour 30 minutes", ["1 hour 30 minutes"])
        obs["params"] = {"childUserId": 424242424242}
        obs["url"] = ("https://www.roblox.com/my/account#!/parental-controls/"
                      "LinkedChildDetails-424242424242/ScreentimeManagement")
        self.assertEqual(observe.judge(rule, obs)["verdict"], observe.SATISFIED)

    def test_the_wrong_child_is_never_in_force(self):
        """Everything read off a page showing another child describes another child."""
        got = self._judge("sam_example")
        self.assertEqual(got["verdict"], observe.UNKNOWN)
        self.assertFalse(got["in_force"])
        self.assertIn("wrong child", got["why"])


class ContentIsJudgedInTheVendorsOwnWords(unittest.TestCase):
    """The generalisation test: one judge, no vendor knowledge inside it.

    `maps` lives in the catalog and translates OUR vocabulary into a vendor's labels.
    Lower maturity is stricter, exactly as fewer minutes is stricter, so the verdicts mean
    the same thing across both kinds.

    These were written after mutation testing found that judge_content had NO tests at
    all -- deleting its unexpressible branch and its stricter branch both passed the whole
    suite, because a shell one-liner had stood in for a test.
    """

    # Netflix is no longer a shipped surface -- a maturity rating is set once and
    # never revisited, and there is no screen time or contact control behind it, so
    # automating it bought nothing. Its rating vocabulary stays here as TEST DATA:
    # the point of these tests is that the judge holds no vendor knowledge, and a
    # vocabulary the shipped catalog never mentions makes that harder to fake.
    NETFLIX = {"kids": "Little Kids", "preteen": "Older Kids",
               "teen": "Teens", "mature": "Adults"}
    ROBLOX = {"kids": "Minimal", "preteen": "Mild", "teen": "Moderate"}   # no "mature"

    def test_exact_match_is_satisfied(self):
        got = observe.judge_content("preteen", "Older Kids",
                                    self.NETFLIX.values(), self.NETFLIX)
        self.assertEqual(got["verdict"], observe.SATISFIED)
        self.assertTrue(got["in_force"])

    def test_a_stricter_level_still_counts(self):
        got = observe.judge_content("preteen", "Little Kids",
                                    self.NETFLIX.values(), self.NETFLIX)
        self.assertEqual(got["verdict"], observe.STRICTER)
        self.assertTrue(got["in_force"])

    def test_a_looser_level_does_not_count(self):
        got = observe.judge_content("preteen", "Adults",
                                    self.NETFLIX.values(), self.NETFLIX)
        self.assertEqual(got["verdict"], observe.NOT_SATISFIED)
        self.assertFalse(got["in_force"])

    def test_a_level_the_vendor_does_not_have_is_unexpressible(self):
        """Roblox tops out at Moderate. Asking it for 'mature' is not a setting you
        forgot -- it is a rule that app cannot express."""
        got = observe.judge_content("mature", "Moderate",
                                    self.ROBLOX.values(), self.ROBLOX)
        self.assertEqual(got["verdict"], observe.UNEXPRESSIBLE)
        self.assertFalse(got["in_force"])
        self.assertNotIn(observe.UNEXPRESSIBLE, observe.IN_FORCE)

    def test_an_unrecognised_label_is_unknown_not_satisfied(self):
        got = observe.judge_content("preteen", "Something Netflix Renamed",
                                    self.NETFLIX.values(), self.NETFLIX)
        self.assertEqual(got["verdict"], observe.UNKNOWN)
        self.assertFalse(got["in_force"])

    def test_no_vocabulary_map_means_unknown_never_satisfied(self):
        """A vendor whose words we have not written down cannot be compared with a rule."""
        got = observe.judge_content("preteen", "Older Kids", [], None)
        self.assertEqual(got["verdict"], observe.UNKNOWN)
        self.assertFalse(got["in_force"])

    def test_the_judge_holds_no_vendor_knowledge_of_its_own(self):
        """Same judge, two vendors, opposite vocabularies, correct both times."""
        self.assertEqual(
            observe.judge_content("teen", "Teens", self.NETFLIX.values(),
                                  self.NETFLIX)["verdict"], observe.SATISFIED)
        self.assertEqual(
            observe.judge_content("teen", "Moderate", self.ROBLOX.values(),
                                  self.ROBLOX)["verdict"], observe.SATISFIED)

    def test_the_judge_follows_the_map_even_when_the_map_is_wrong(self):
        """Proof there is no built-in vendor knowledge, done behaviourally.

        A grep for vendor words was the first version of this and it failed on a
        docstring example -- which is documentation, not knowledge in code. This is
        sharper: feed a deliberately INVERTED map, where Netflix's real "Adults" is
        declared to mean our "kids". A judge carrying any built-in idea of what those
        words mean would disagree with the map. It must not.
        """
        inverted = {"kids": "Adults", "mature": "Little Kids"}
        got = observe.judge_content("kids", "Adults", inverted.values(), inverted)
        self.assertEqual(got["verdict"], observe.SATISFIED,
                         "the judge second-guessed the catalog")

        got = observe.judge_content("kids", "Little Kids", inverted.values(), inverted)
        self.assertEqual(got["verdict"], observe.NOT_SATISFIED,
                         "the judge used Netflix's real meaning instead of the map")

    def test_the_catalog_maps_reach_the_judge(self):
        """End to end through the plan, not just the function."""
        plan = build(load(REAL, None), harness.TODAY, [{
            "rule": "alex-content", "surface": "roblox-alex", "recipe": "x",
            "at": "2026-09-02T10:00:00Z", "code": "OK",
            "readings": {"maturityText": "Mild"}}])
        cell = plan["cells"][("alex-content", "roblox-alex")]
        self.assertEqual(cell["verdict"], observe.SATISFIED)


class MissingObservations(unittest.TestCase):

    def test_no_observations_is_todo_not_a_pass(self):
        self.assertEqual(cell(None)["state"], "todo")

    def test_a_missing_observations_file_reads_as_nothing_observed(self):
        self.assertEqual(observe.load_observations(harness.REPO / "nope.json"), [])

    def test_an_unreadable_observations_file_raises_rather_than_reporting_zero(self):
        """Unreadable is not empty. Quietly reporting zero observations would look
        exactly like a clean slate."""
        bad = harness.FIXTURES / "_tmp-bad.json"
        bad.write_text("{ not json at all")
        try:
            with self.assertRaises(ValueError):
                observe.load_observations(bad)
        finally:
            bad.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
