#!/usr/bin/env node
// Drive both vendor fixtures through the REAL engine, in a real DOM.
//
// This is the check that caught the two bugs the demo actually hit: a tick inside an
// option's textContent, which made the engine read "1 hour 30 minutes✓" as the value on
// offer; and a fixture that forgot its saved setting, so the fresh tab the dashboard
// opens to re-read reported the OLD value while the page showed a save confirmation.
//
// Needs jsdom, which the repo otherwise does not depend on, so it stays a deliberate
// manual step rather than part of `node --test`:
//
//     npm install --no-save jsdom
//     node scripts/check-fixtures.mjs
//
// The zero-dependency half runs every time in extension/test/engine.test.js: options
// hold no child elements, the listbox holds only options, and every persisting fixture
// both reads and writes a pp-fixture-* key.
import fs from "node:fs";
import path from "node:path";
import { JSDOM, VirtualConsole } from "jsdom";

const repo = path.join(import.meta.dirname, "..");
const pure = fs.readFileSync(path.join(repo, "extension/engine/pure.js"), "utf8");
const dom = fs.readFileSync(path.join(repo, "extension/engine/dom.js"), "utf8");

function page(file, key, preset) {
  const html = fs.readFileSync(path.join(repo, "extension/test/fixtures", file), "utf8");
  return new JSDOM(html, {
    url: `http://localhost:8787/extension/test/fixtures/${file}`,
    runScripts: "dangerously", pretendToBeVisual: true,
    virtualConsole: new VirtualConsole(),
    beforeParse(w) {
      // beforeParse runs BEFORE the page's script. Seeding afterwards is too late -- the
      // script has already read storage, which made this harness report a working
      // restore as broken.
      if (preset) w.localStorage.setItem(key, preset);
      else w.localStorage.removeItem(key);
    },
  }).window;
}
function engine(window) {
  globalThis.window = window;
  globalThis.document = window.document;
  Object.defineProperty(globalThis, "navigator",
                        { value: window.navigator, configurable: true });
  globalThis.XPathResult = window.XPathResult;
  // Needed by run()'s final `location.href` -- harmless for vendor-a/b, which only ever
  // call extract()/query() directly and never reach that line, but required the first
  // time anything here calls the real run() end to end.
  Object.defineProperty(globalThis, "location", { value: window.location, configurable: true });
  globalThis.BroadcastChannel = window.BroadcastChannel || function () { this.postMessage = () => {}; };
  eval(pure);
  eval(dom);
  return globalThis.PPDom;
}

let bad = 0;
const ok = (name, cond, detail) => {
  console.log(`  ${cond ? "ok  " : "FAIL"}  ${name}${detail ? "  " + detail : ""}`);
  if (!cond) bad++;
};

// --- expandSelector: "ci:" must match the INNERMOST element, not an outer ancestor ---
//
// Isolated from the Family Console section below on purpose: that section proves the
// fix works end to end through run(), but a failure there could mean any of templating,
// preflight, the click, or the read. This pins down the exact XPath behaviour alone.
//
// contains() on normalize-space() reads an element's FULL DESCENDANT TEXT, so a bare
// contains() matches every ancestor of the real target too -- and FIRST_ORDERED_NODE_
// TYPE, walking the document in preorder, returns the ancestor (usually <html>) before
// it ever reaches the element that actually carries the text. Every existing use of
// "ci:" before Family Console only ever checked EXISTENCE (a readyAnchor, a preflight
// assert), where matching <html> is harmless -- this was invisible for the whole life
// of the project until a "ci:" match became a CLICK TARGET, where clicking <html> does
// nothing. This needs a real DOM (document.evaluate), which is why it lives here and
// not in engine.test.js, which promises zero dependencies.
console.log("expandSelector");
{
  engine(new JSDOM("<p>seed</p>").window);   // populate globalThis.PPPure
  const pure = globalThis.PPPure;

  const doc1 = new JSDOM('<div class="row"><span class="name">sam_example</span></div>').window;
  const xp = pure.expandSelector("ci:sam_example");
  const r1 = doc1.document.evaluate(xp, doc1.document, null,
                                    doc1.XPathResult.FIRST_ORDERED_NODE_TYPE, null);
  ok("matches the innermost element, not <html>",
     r1.singleNodeValue && r1.singleNodeValue.tagName === "SPAN"
     && r1.singleNodeValue.className === "name",
     r1.singleNodeValue && r1.singleNodeValue.tagName);

  const doc2 = new JSDOM('<div class="row">sam <b>example</b></div>').window;
  const r2 = doc2.document.evaluate(pure.expandSelector("ci:sam example"), doc2.document, null,
                                    doc2.XPathResult.FIRST_ORDERED_NODE_TYPE, null);
  ok("still finds text that only exists once children are combined",
     r2.singleNodeValue && r2.singleNodeValue.className === "row",
     "excluding it entirely would make a legitimate match vanish");
}

// --- Vendor A: custom widget, worded durations -------------------------------------
const A_KEY = "pp-fixture-vendor-a-daily-limit";
const A_OPTS = ["No limit", "30 minutes", "1 hour", "1 hour 30 minutes", "2 hours", "3 hours"];
console.log("Vendor A");
for (const [name, preset, expect] of [
  ["default", null, "1 hour 30 minutes"],
  ["saved value restored", "2 hours", "2 hours"],
  ["value not on offer ignored", "9 hours", "1 hour 30 minutes"],
  ["junk ignored", "<script>x</script>", "1 hour 30 minutes"],
]) {
  const w = page("vendor-a.html", A_KEY, preset), D = engine(w);
  const value = D.extract(w.document.querySelector('[data-testid="daily-limit-value"]'), "text");
  const opts = D.extract(w.document.querySelector('[data-testid="daily-limit-options"]'), "optionList");
  const sel = [...w.document.querySelectorAll('[role="option"]')]
    .filter((e) => e.getAttribute("aria-selected") === "true").map((e) => e.textContent.trim());
  ok(name, value === expect && opts.join("|") === A_OPTS.join("|")
           && sel.length === 1 && sel[0] === expect,
     `value=${JSON.stringify(value)} selected=${JSON.stringify(sel)}`);
}
{
  // A scripted Save must change nothing and must trip the tripwire. jsdom cannot forge
  // isTrusted, which is precisely why the engine can never take the human branch.
  const w = page("vendor-a.html", A_KEY, null), D = engine(w);
  const read = () => D.extract(w.document.querySelector('[data-testid="daily-limit-value"]'), "text");
  [...w.document.querySelectorAll('[role="option"]')]
    .find((e) => e.textContent.trim() === "2 hours")
    .dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  ok("selecting does not change the saved value", read() === "1 hour 30 minutes", read());
  w.document.querySelector('[data-testid="screentime-save"]')
    .dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  ok("a scripted Save changes nothing", read() === "1 hour 30 minutes");
  ok("a scripted Save trips the tripwire", /SAVED BY SCRIPT/.test(w.document.title));
}

// --- Vendor B: native select, bare minutes -----------------------------------------
const B_KEY = "pp-fixture-vendor-b-daily-allowance";
const B_OPTS = ["0", "30", "60", "120"];
console.log("Vendor B");
for (const [name, preset, expect] of [
  ["default", null, "60"],
  ["saved value restored", "120", "120"],
  ["value not on offer ignored", "90", "60"],
  ["junk ignored", "abc", "60"],
]) {
  const w = page("vendor-b.html", B_KEY, preset), D = engine(w);
  const value = D.extract(w.document.querySelector("#daily-allowance"), "text");
  const opts = D.extract(w.document.querySelector("#allowance-select"), "optionList");
  const sel = D.extract(w.document.querySelector("#allowance-select"), "selectedText");
  ok(name, value === expect && opts.join("|") === B_OPTS.join("|") && sel === expect,
     `value=${JSON.stringify(value)} selected=${JSON.stringify(sel)}`);
}
{
  const w = page("vendor-b.html", B_KEY, null), D = engine(w);
  const opts = D.extract(w.document.querySelector("#allowance-select"), "optionList");
  ok("90 is still not on offer", !opts.includes("90"),
     "the unexpressible verdict needs somewhere to happen");
}

// --- Family Console: several children, one page, no per-child URL --------------------
//
// The first fixture that needs run()'s actual CLICK step, not just extract()/query(). It
// found a real, previously-latent bug in expandSelector: "ci:" matched the OUTERMOST
// ancestor whose combined text contained the target (contains() on normalize-space()
// reads an element's full descendant text), not the element that actually carries it.
// Every earlier "ci:" use only checked existence -- a readyAnchor or a preflight assert
// -- where matching <html> is harmless. Clicking <html> is not.
console.log("Family Console");
{
  const w = page("family-console.html", null, null);
  // jsdom does no real layout, so the engine's visible() check (getClientRects().length,
  // offsetParent) is always empty/null, and scrollIntoView does not exist at all -- both
  // documented, permanent jsdom gaps, not product behaviour. A real browser computes
  // these correctly; these three lines exist only so this harness can drive a click.
  w.Element.prototype.getClientRects = function () { return [{ width: 1, height: 1 }]; };
  w.Element.prototype.scrollIntoView = function () {};
  Object.defineProperty(w.HTMLElement.prototype, "offsetParent",
                        { get() { return w.document.body; }, configurable: true });
  const D = engine(w);

  globalThis.PPRecipes = {};
  eval(fs.readFileSync(path.join(repo, "extension/recipes/family-console-schedule-verify.js"), "utf8"));
  const recipe = globalThis.PPRecipes["family-console-schedule-verify"];

  for (const [child, expectClock, expectSelected] of [
    ["sam_example", "8:00 PM", "sam_example"],     // 12-hour text
    ["alex_example", "21:30", "alex_example"],     // 24-hour text, same page
  ]) {
    const filled = globalThis.PPPure.applySelectorParams(recipe.selectors, { childUsername: child });
    ok(`${child}: selector templating fills the row selector`,
       filled.ok && filled.selectors["child.row"][0] === `ci:${child}`, JSON.stringify(filled));
    const result = await D.run(recipe, filled.selectors, { childUsername: child });
    ok(`${child}: preflight, click and read all succeed`, result.ok, JSON.stringify(result));
    ok(`${child}: reads its own cutoff (${expectClock})`,
       result.readings && result.readings.notAfterText === expectClock,
       JSON.stringify(result.readings));
    ok(`${child}: selectedChild confirms the right panel opened, not the other one`,
       result.readings && result.readings.selectedChild === expectSelected,
       result.readings && result.readings.selectedChild);
  }

  // The case this fixture exists to prove: a name that is not on the roster at all.
  const filled = globalThis.PPPure.applySelectorParams(recipe.selectors, { childUsername: "nobody_example" });
  const result = await D.run(recipe, filled.selectors, { childUsername: "nobody_example" });
  ok("an unlinked child fails NOT_LINKED, not a generic timeout",
     !result.ok && result.code === "NOT_LINKED", JSON.stringify(result));
}

console.log(bad ? `\n${bad} PROBLEM(S)` : "\nall fixtures read correctly through the engine");
process.exit(bad ? 1 : 0);
