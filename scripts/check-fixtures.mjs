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
  eval(pure);
  eval(dom);
  return globalThis.PPDom;
}

let bad = 0;
const ok = (name, cond, detail) => {
  console.log(`  ${cond ? "ok  " : "FAIL"}  ${name}${detail ? "  " + detail : ""}`);
  if (!cond) bad++;
};

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

console.log(bad ? `\n${bad} PROBLEM(S)` : "\nboth fixtures read correctly through the engine");
process.exit(bad ? 1 : 0);
