"""EVAL 3 — The page cannot show something the plan does not say.

EVAL 1 guards the computation. This guards the last step, which is the one that actually
reaches a parent: a correct plan rendered wrongly is exactly as harmful as a wrong plan,
and it is the failure the other two suites cannot see.

Bar: 100%.
"""
import html as html_mod
import re
import sys
import unittest

from evals import harness
from plane.model import load
from plane.plan import build
from plane import observe, render as render_mod
from plane.render import COVERED_LOOK, GLYPH, render

CELL = re.compile(r'data-state="([a-z]+)"[^>]*data-pair="([^"|]+)\|([^"]+)"[^>]*>'
                  r'<i>([^<]*)</i>')


def page_cells(html):
    return {(m.group(2), m.group(3)): (m.group(1), m.group(4))
            for m in CELL.finditer(html)}


class PageMatchesPlan(unittest.TestCase):

    def setUp(self):
        self.plan = build(load(harness.REPO / "policy.yaml",
                               harness.REPO / "status.yaml"), harness.TODAY)
        self.html = render(self.plan)
        self.cells = page_cells(self.html)

    def test_every_pair_in_the_plan_appears_on_the_page(self):
        expected = {(r["id"], s["id"]) for r in self.plan["rules"]
                    for s in self.plan["surfaces"]}
        self.assertEqual(set(self.cells), expected)

    def test_every_cell_state_matches_the_plan_exactly(self):
        for (rule, surface), (shown, _) in self.cells.items():
            cell = self.plan["cells"][(rule, surface)]
            expected = cell["state"] if cell["applicable"] else "na"
            self.assertEqual(shown, expected, f"{rule} × {surface} renders as {shown}")

    def test_only_verified_pairs_get_the_covered_look(self):
        """The lie this suite exists to prevent: a green tick you have not earned."""
        for (rule, surface), (shown, glyph) in self.cells.items():
            if glyph == GLYPH["verified"] and glyph:
                self.assertIn(shown, COVERED_LOOK,
                              f"{rule} × {surface} shows the confirmed glyph while "
                              f"the plan says {shown}")

    def test_the_confirmed_count_on_the_page_matches_the_plan(self):
        shown = sum(1 for state, _ in self.cells.values() if state in COVERED_LOOK)
        self.assertEqual(shown, self.plan["summary"]["pairs_covered"])

    def test_a_stale_pair_is_not_drawn_as_confirmed(self):
        stale = [p for p, (s, _) in self.cells.items() if s == "stale"]
        self.assertTrue(stale, "fixture should contain a stale pair to be meaningful")
        for pair in stale:
            self.assertNotEqual(self.cells[pair][1], GLYPH["verified"])

    def test_every_section_the_renderer_defines_actually_reaches_the_page(self):
        """The guard that was missing.

        _catalog, _unused and _verify_section were all DEFINED and never CALLED for two
        commits -- a string replace whose target did not match, with nothing asserting
        it had. Every suite passed while a whole section of the page silently did not
        exist. Anything the renderer builds must show up here or the build fails.
        """
        for heading in ("Where each rule stands", "Rules", "What to do next",
                        "Verify against the vendors",
                        "What your apps can actually control",
                        "You could also ask for", "What each app reaches"):
            with self.subTest(heading):
                self.assertIn(heading, self.html, f"section '{heading}' is missing")

    def test_each_section_has_content_not_just_a_heading(self):
        """Headings and bodies are appended separately, so a heading proves nothing.

        Found by mutation testing after the first version of the guard above: deleting
        the catalog table still left its heading, and the test passed on an empty
        section. Every section is now checked by something only its body produces.
        """
        catalog_rows = sum(len(s["catalog"]) for s in self.plan["surfaces"])
        self.assertGreater(catalog_rows, 0, "fixture should have catalog entries")
        # Every catalog row renders its control kind in a pill and its depth note.
        for surf in self.plan["surfaces"]:
            for entry in surf["catalog"]:
                with self.subTest(f'{surf["id"]}.{entry["kind"]}'):
                    self.assertIn(html_mod.escape(entry["options"]), self.html,
                                  "a catalog row is missing from the page")

        unused = [(s["name"], e["kind"]) for s in self.plan["surfaces"]
                  for e in s["catalog"] if not e["used_by"]]
        for name, kind in unused:
            self.assertIn(html_mod.escape(name), self.html,
                          "an unused control is not shown")

        for v in self.plan["verifiable"]:
            self.assertIn(v["recipe"], self.html, "a verifiable pair has no recipe wired")

    def test_every_runnable_pair_gets_a_button_and_blocked_ones_do_not(self):
        runnable = [v for v in self.plan["verifiable"] if not v["blocked"]]
        self.assertEqual(self.html.count('class="vbtn"'), len(runnable),
                         "a runnable pair has no way to run it, or a blocked one is offered")
        for v in self.plan["verifiable"]:
            if v["blocked"]:
                self.assertIn(html_mod.escape(v["why_blocked"]), self.html,
                              "a blocked pair must explain itself on the page")

    def test_the_page_never_sends_selectors_or_steps_to_the_extension(self):
        """The security rule, checked on the artifact rather than trusted.

        The page may send a recipe id and parameters. If it could send steps or
        selectors, any origin allowed to message the extension would gain arbitrary DOM
        execution on whatever the user is logged into.
        """
        self.assertIn("RUN_RECIPE", self.html)
        for forbidden in ("selectors:", "steps:", '"selector"', "executeScript"):
            self.assertNotIn(forbidden, self.html,
                             f"the page appears to send {forbidden} to the extension")

    def test_the_page_declares_its_encoding_first(self):
        """Without a charset the browser guesses, and every em-dash in this page came
        out as "â€"" on a real screen. It has to be the first thing in the document,
        before any text a guesser could sniff."""
        self.assertIn('<meta charset="utf-8">', self.html)
        self.assertLess(self.html.index('<meta charset="utf-8">'),
                        self.html.index("<title>"),
                        "charset must precede any text")

    def test_the_page_survives_a_round_trip_through_utf8(self):
        encoded = self.html.encode("utf-8")
        self.assertEqual(encoded.decode("utf-8"), self.html)
        self.assertIn("—", self.html, "the fixture should exercise a non-ASCII character")

    def test_the_javascript_the_page_emits_actually_parses(self):
        """The guard that was missing, and the bug it would have caught.

        `_verify_script` was a plain Python triple-quoted string, so every \\n in the
        template became a REAL newline and landed inside a JS string literal. That is a
        syntax error, which stops the entire script -- so every Verify button silently
        did nothing, with no error visible on the page and every test still green.

        Rendering HTML is not the same as rendering working HTML. If the page emits
        script, the script has to parse.
        """
        import shutil
        import subprocess
        import tempfile

        node = shutil.which("node")
        if not node:
            self.skipTest("node not available to parse the emitted script")

        scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)
        self.assertTrue(scripts, "the page emits no script at all")
        for i, body in enumerate(scripts):
            with self.subTest(f"script {i}"):
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
                    fh.write(body)
                    path = fh.name
                got = subprocess.run([node, "--check", path],
                                     capture_output=True, text=True)
                self.assertEqual(got.returncode, 0,
                                 f"emitted script does not parse:\n{got.stderr}")

    def test_no_emitted_string_literal_spans_a_line(self):
        """A cheaper version of the check above that needs no node, so the guard still
        bites in an environment without it."""
        for body in re.findall(r"<script>(.*?)</script>", self.html, re.S):
            for lineno, line in enumerate(body.splitlines(), 1):
                # Count unescaped double quotes; an odd number means a literal ran off
                # the end of the line.
                quotes = len(re.findall(r'(?<!\\)"', line))
                self.assertEqual(quotes % 2, 0,
                                 f"line {lineno} leaves a string literal open: {line!r}")

    def test_evidence_images_are_never_embedded(self):
        """Screenshots stay local. docs/index.html is what goes to GitHub Pages, so an
        embedded image would publish a picture of a child's device settings."""
        self.assertNotIn("<img", self.html)
        self.assertNotIn("shots/", self.html)

    def test_the_plan_carries_no_behaviour_data(self):
        """Monitoring is a non-goal, enforced structurally rather than by word-search.

        A lexical check cannot tell a claim from a disclaimer -- this page says "crop the
        usage chart out" and "records no usage", and both are the promise being kept. So
        the guard is on the DATA instead: the plan may only carry configuration and the
        parent's own attestations. If anyone later threads a minutes-used or last-seen
        field through to the page, this fails.
        """
        # Extended deliberately when the parameter model landed. Every addition is
        # configuration or attestation; none of it describes what a child did.
        allowed = {"applicable", "state", "date", "by", "age_days", "recheck_days",
                   "has_evidence", "evidence",
                   "depth", "honoured", "dropped", "recipe",
                   # From an extension read. All of it describes a SETTING and when it
                   # was read -- none of it describes what a child did.
                   #
                   # `said` is the vendor's own words for the setting -- "1 Hour",
                   # "No limit", "Older Kids". It is on the page beside the verdict so
                   # the claim can be checked rather than believed. It is a control's
                   # value, never a record of use: nothing here says whether the child
                   # played, for how long, or when.
                   "observed", "verdict", "why", "said"}
        banned = ("usage", "activity", "minutes", "watched", "visited", "seen",
                  "duration", "session")
        for pair, cell in self.plan["cells"].items():
            self.assertLessEqual(set(cell), allowed, f"new field on cell {pair}")
            for key in cell:
                self.assertFalse(any(b in key.lower() for b in banned),
                                 f"{key} on {pair} looks like behaviour data")

    def test_the_page_states_the_boundary_out_loud(self):
        """The promise is only worth something if a reader can see it."""
        self.assertIn("tracks your settings, not your kids", self.html)

    def test_page_escapes_policy_text(self):
        plan = dict(self.plan, family='<script>alert(1)</script>')
        self.assertNotIn("<script>alert(1)</script>", render(plan))


if __name__ == "__main__":
    unittest.main()


class VerdictWording(unittest.TestCase):
    """The page turns a verdict into English exactly once, and never invents one.

    The wording table is duplicated into the inline script so a fresh run can render the
    same panel the server renders. Duplication is fine; drift is not, and a page that
    quietly renders an empty verdict cell would be the worst possible failure of a tool
    whose entire job is to say whether a rule is in force.
    """

    def setUp(self):
        self.html = render(build(load(harness.REPO / "policy.yaml",
                                      harness.REPO / "status.yaml"), harness.TODAY))

    def test_every_verdict_the_judge_can_return_has_wording(self):
        emitted = {observe.SATISFIED, observe.STRICTER, observe.NOT_SATISFIED,
                   observe.UNEXPRESSIBLE, observe.UNKNOWN}
        self.assertEqual(emitted, set(render_mod.VERDICT_WORDS),
                         "a verdict the judge can return has no wording on the page")

    def test_the_scripts_copy_of_the_table_matches_pythons(self):
        import json as json_mod
        blob = re.search(r"var WORDS = (\{.*?\});", self.html, re.S)
        self.assertIsNotNone(blob, "the script no longer carries a wording table")
        in_js = json_mod.loads(blob.group(1))
        self.assertEqual({k: list(v) for k, v in render_mod.VERDICT_WORDS.items()}, in_js,
                         "the page's wording table has drifted from Python's")

    def test_an_unknown_verdict_raises_rather_than_rendering_blank(self):
        with self.assertRaises(AssertionError):
            render_mod._verdict_words("probably_fine")

    def test_in_force_wording_is_reserved_for_verdicts_that_are_in_force(self):
        """`stricter` counts, `unexpressible` and `unknown` never do."""
        for verdict in (observe.SATISFIED, observe.STRICTER):
            self.assertEqual(render_mod.VERDICT_WORDS[verdict][1], "In force")
        for verdict in (observe.NOT_SATISFIED, observe.UNEXPRESSIBLE, observe.UNKNOWN):
            self.assertNotEqual(render_mod.VERDICT_WORDS[verdict][1], "In force",
                                f"{verdict} must never read as in force")


class PublishGate(unittest.TestCase):
    """The leak checker must be able to fail.

    A checker that cannot fail is worse than none: it manufactures confidence, and it is
    the version people stop reading. Its own self-test plants each kind of secret and
    asserts a finding, then plants clean material and asserts silence -- this runs that
    self-test so the guarantee is checked by the suite rather than by memory.
    """

    def test_the_leak_checker_self_test_passes(self):
        import subprocess
        script = harness.REPO / "scripts" / "leak_check.py"
        self.assertTrue(script.exists(), "the publish gate is missing")
        done = subprocess.run([sys.executable, str(script), "--self-test"],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0,
                         f"the leak checker cannot prove it fails:\n{done.stdout}\n{done.stderr}")
        self.assertIn("caught  a private token", done.stdout)


class MermaidDiagrams(unittest.TestCase):
    """Diagrams in markdown must survive GitHub's renderer.

    A malformed mermaid block renders on GitHub as a red "Unable to render rich display"
    box. That is worse than no diagram, and it is invisible from the markdown -- which is
    exactly how one shipped.

    The trap is that GitHub decodes HTML entities in the fenced block BEFORE handing it
    to mermaid. `&quot;` inside an already-quoted edge label arrives as a bare `"` and
    closes the label early. A checker that parses the raw text sees five harmless
    characters and passes, which is a false green rather than no check at all.
    """

    def _blocks(self):
        found = []
        for path in sorted(harness.REPO.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for block in re.findall(r"```mermaid\n(.*?)```", text, re.S):
                found.append((path.name, block))
        return found

    def test_no_html_entities_inside_a_mermaid_block(self):
        for name, block in self._blocks():
            with self.subTest(name):
                entity = re.search(r"&(?:quot|apos|lt|gt|amp|nbsp|#\d+);", block)
                self.assertIsNone(
                    entity,
                    f"{name}: mermaid block contains {entity.group(0) if entity else ''} — "
                    "GitHub decodes it before parsing, so it will not mean what it looks "
                    "like here. Write the character you want, or reword to avoid it.")

    def test_no_quote_inside_a_quoted_mermaid_label(self):
        """The specific failure: a nested quote closes the label early."""
        for name, block in self._blocks():
            for lineno, line in enumerate(block.splitlines(), 1):
                for label in re.findall(r'\|"([^|]*)"\|', line):
                    with self.subTest(f"{name}:{lineno}"):
                        self.assertNotIn('"', label,
                                         f'{name} line {lineno}: nested quote in an edge '
                                         f'label — mermaid ends the label at the first one')
