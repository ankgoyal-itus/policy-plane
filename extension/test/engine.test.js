// Engine tests. Plain node, no browser, no dependency: run with
//   node --test extension/test/engine.test.js
// (the directory form is NOT equivalent -- node resolves a bare directory as a module
// and dies with MODULE_NOT_FOUND, which reads like a broken suite rather than a wrong
// command. This header said the directory form for two commits.)
//
// Everything that decides anything lives in pure.js, so this covers the logic. What it
// cannot cover is whether a selector matches a real vendor page -- that is the
// calibration pass, and it is a human checklist by design (the brief, §8).

const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const fs = require("node:fs");

const P = require("../engine/pure.js");

test("read-only by construction: the engine has no write actions", () => {
  assert.deepStrictEqual(P.ACTIONS, ["waitFor", "click", "read"]);
  for (const w of ["setValue", "setChecked", "selectOption", "commit"]) {
    assert.ok(P.isWriteAction(w), `${w} must be recognised as a write`);
    assert.ok(!P.ACTIONS.includes(w), `${w} must not be runnable`);
  }
});

test("no shipped recipe declares a write step or a commit", () => {
  const dir = path.join(__dirname, "..", "recipes");
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".js"))) {
    const src = fs.readFileSync(path.join(dir, file), "utf8");
    globalThis.PPRecipes = globalThis.PPRecipes || {};
    // eslint-disable-next-line no-eval
    eval(src);
  }
  for (const [id, r] of Object.entries(globalThis.PPRecipes)) {
    assert.ok(["verify", "probe"].includes(r.mode),
              `${id} has mode ${r.mode}; only verify and probe may ship`);
    assert.ok(!("commit" in r), `${id} declares a commit`);
    for (const step of r.steps || []) {
      assert.ok(!P.isWriteAction(step.action), `${id} has write step ${step.action}`);
    }
  }
});

test("every recipe selector has at least one candidate and no class-name selectors", () => {
  for (const [id, r] of Object.entries(globalThis.PPRecipes)) {
    for (const [name, candidates] of Object.entries(r.selectors)) {
      assert.ok(candidates.length >= 1, `${id}.${name} has no candidates`);
      for (const c of candidates) {
        // Generated class names churn. data-testid, role/aria, ids and XPath text only.
        assert.ok(!/^\.[A-Za-z0-9_-]+$/.test(c),
                  `${id}.${name} uses a bare class selector: ${c}`);
      }
    }
  }
});

test("every recipe's readyAnchor is a selector it actually defines", () => {
  for (const [id, r] of Object.entries(globalThis.PPRecipes)) {
    assert.ok(r.selectors[r.readyAnchor], `${id}.readyAnchor '${r.readyAnchor}' undefined`);
  }
});

test("every recipe step and read has a human-readable describe", () => {
  for (const [id, r] of Object.entries(globalThis.PPRecipes)) {
    for (const s of [...(r.preflight || []), ...(r.steps || []), ...(r.read || [])]) {
      assert.ok(s.describe, `${id} has a step with no describe`);
    }
  }
});

test("params are validated, never coerced", () => {
  const schema = { minutesPerDay: { type: "integer", required: true, min: 0, max: 1440 } };
  assert.strictEqual(P.validateParams(schema, { minutesPerDay: 90 }).ok, true);
  assert.strictEqual(P.validateParams(schema, {}).code, P.CODES.BAD_PARAMS);
  assert.strictEqual(P.validateParams(schema, { minutesPerDay: "90" }).code, P.CODES.BAD_PARAMS);
  assert.strictEqual(P.validateParams(schema, { minutesPerDay: 5000 }).code, P.CODES.BAD_PARAMS);
  assert.strictEqual(P.validateParams(schema, { minutesPerDay: 90, extra: 1 }).code,
                     P.CODES.BAD_PARAMS);
});

test("selector fallbacks are tried in order and the winner is reported", () => {
  const present = new Set(["#second"]);
  const got = P.pickSelector(["#first", "#second", "#third"], (s) => present.has(s));
  assert.strictEqual(got.found, true);
  assert.strictEqual(got.matched, "#second");
  assert.deepStrictEqual(got.tried, ["#first", "#second"]);
});

test("a selector that matches nothing reports everything it tried", () => {
  const got = P.pickSelector(["#a", "#b"], () => false);
  assert.strictEqual(got.found, false);
  assert.deepStrictEqual(got.tried, ["#a", "#b"]);
});

test("minutes parse out of the shapes vendors actually render", () => {
  const cases = [["90 minutes", 90], ["1 hour 30 minutes", 90], ["1h", 60],
                 ["2 hours", 120], ["None", 0], ["45", 45], ["banana", null], ["", null]];
  for (const [text, want] of cases) {
    assert.strictEqual(P.parseMinutes(text), want, `parsing ${JSON.stringify(text)}`);
  }
});




test("the extension does not judge -- no verdict logic ships in the engine", () => {
  assert.strictEqual(P.judgeValue, undefined,
    "judging belongs in the plane; the reader must not grade its own reading");
});

test("every script the extension ships parses", () => {
  const { execFileSync } = require("node:child_process");
  const roots = [path.join(__dirname, ".."), path.join(__dirname, "..", "engine"),
                 path.join(__dirname, "..", "recipes")];
  let checked = 0;
  for (const dir of roots) {
    for (const f of fs.readdirSync(dir)) {
      if (!f.endsWith(".js")) continue;
      const full = path.join(dir, f);
      if (fs.statSync(full).isDirectory()) continue;
      execFileSync(process.execPath, ["--check", full]);   // throws on a syntax error
      checked += 1;
    }
  }
  assert.ok(checked >= 5, `expected to check several files, checked ${checked}`);
});

test("every inline script in the extension's test pages parses", () => {
  const { execFileSync } = require("node:child_process");
  const os = require("node:os");
  const dir = __dirname;
  for (const f of fs.readdirSync(dir)) {
    if (!f.endsWith(".html")) continue;
    const html = fs.readFileSync(path.join(dir, f), "utf8");
    const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
    for (const [i, body] of blocks.entries()) {
      const tmp = path.join(os.tmpdir(), `pp-${f}-${i}.js`);
      fs.writeFileSync(tmp, body);
      execFileSync(process.execPath, ["--check", tmp]);
    }
  }
});

test("recipes/schemas.json matches the recipes it was generated from", () => {
  const { execFileSync } = require("node:child_process");
  execFileSync(process.execPath,
               [path.join(__dirname, "schemas.gen.js"), "--check"]);  // throws if stale
});

test("ci: expands to a case-insensitive XPath text match", () => {
  const got = P.expandSelector("ci:Parental controls");
  assert.ok(P.isXPath(got), "should produce an XPath");
  assert.match(got, /translate\(/);
  assert.match(got, /'parental controls'/);          // lowercased for comparison
  assert.strictEqual(P.expandSelector("#plain"), "#plain");
  assert.strictEqual(P.expandSelector("//h1"), "//h1");
});

test("ci: strips quotes that would break the XPath literal", () => {
  assert.ok(!P.expandSelector("ci:Alex's account").includes("Alex's"));
  assert.doesNotThrow(() => P.expandSelector("ci:it's a 'test'"));
});

test("only one place resolves selectors", () => {
  // The readiness poll in background.js used to carry its own simpler resolver, so
  // "ci:" worked in dom.js and silently did not work for readiness -- a two-minute
  // timeout with nothing to show for it. Selector resolution belongs to dom.js alone.
  const bg = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  for (const banned of ["document.querySelector", "document.evaluate"]) {
    assert.ok(!bg.includes(banned),
              `background.js resolves selectors itself (${banned}); use PPDom.query`);
  }
  assert.ok(bg.includes("PPDom.query"), "background.js should defer to the engine");
});

test("every engine file is wrapped so a second injection cannot redeclare anything", () => {
  // pure.js declared `const CODES` at top level while dom.js was IIFE-wrapped. Once the
  // readiness poll began injecting on every attempt, the second injection threw
  // "Identifier 'CODES' has already been declared" -- which kills the whole script on
  // the real page, every run.
  //
  // This is checked STRUCTURALLY, not by double-eval. eval() gives const and let their
  // own scope, so eval(src);eval(src) never collides -- it passed happily against an
  // unwrapped file. A content script is loaded as a script, where the collision is real.
  for (const f of ["pure.js", "dom.js"]) {
    const src = fs.readFileSync(path.join(__dirname, "..", "engine", f), "utf8");
    const code = src.split("\n")
      .filter((l) => l.trim() && !l.trim().startsWith("//"));
    assert.match(code[0].trim(), /^\(function\s*\(/,
                 `${f} must open with an IIFE; it starts: ${code[0].trim().slice(0, 50)}`);
    assert.match(code[code.length - 1].trim(), /^\}\)\(\);?$/,
                 `${f} must close its IIFE`);
  }
});

test("no recipe uses a step or preflight key the engine does not implement", () => {
  // `negate: true` was written into a preflight the engine has no support for. It would
  // have asserted the OPPOSITE of what it read as -- that a re-auth wall IS present --
  // and nothing caught it, because nobody checks recipes against the engine's vocabulary.
  const STEP_KEYS = new Set(["action", "selector", "describe", "timeout"]);
  const PRE_KEYS = new Set(["assert", "else", "describe", "timeout"]);
  const READ_KEYS = new Set(["as", "selector", "extract", "describe", "timeout"]);
  for (const [id, r] of Object.entries(globalThis.PPRecipes)) {
    for (const [list, allowed, what] of [[r.preflight, PRE_KEYS, "preflight"],
                                         [r.steps, STEP_KEYS, "step"],
                                         [r.read, READ_KEYS, "read"]]) {
      for (const item of list || []) {
        for (const key of Object.keys(item)) {
          assert.ok(allowed.has(key),
                    `${id}: ${what} uses unknown key '${key}' — the engine ignores it`);
        }
      }
    }
  }
});

// --- probe: route shape -------------------------------------------------------------
//
// These exist because the Netflix probe came back with no <select>, no data-testid and
// no stable id, and the probe reported nothing else -- so it looked like the page held
// no structure when in fact the whole structure was links the probe never looked at.

test("summarizeLinks keeps the hash route", () => {
  // Roblox's parental-controls page IS a hash route. A summariser that kept only
  // `pathname` would flatten every child's page to "/my/account" and report that the
  // deep link does not exist.
  const got = P.summarizeLinks(
    [{ text: "Screen time", href: "https://www.roblox.com/my/account#!/parental-controls/LinkedChildDetails-1/ScreentimeManagement" }],
    "https://www.roblox.com");
  assert.strictEqual(got.length, 1);
  assert.ok(got[0].path.includes("#!/parental-controls/"),
            `hash route was dropped: ${got[0].path}`);
});

test("summarizeLinks keeps the query string", () => {
  const got = P.summarizeLinks(
    [{ text: "Profile", href: "https://www.netflix.com/account/profiles?guid=ABC" }],
    "https://www.netflix.com");
  assert.strictEqual(got[0].path, "/account/profiles?guid=ABC");
});

test("summarizeLinks drops off-origin links", () => {
  const got = P.summarizeLinks([
    { text: "Help", href: "https://help.netflix.com/x" },
    { text: "Account", href: "https://www.netflix.com/account" },
  ], "https://www.netflix.com");
  assert.deepStrictEqual(got.map((l) => l.text), ["Account"]);
});

test("summarizeLinks drops links with no text and no label", () => {
  const got = P.summarizeLinks([
    { text: "   ", href: "https://www.netflix.com/a" },
    { text: "Real", href: "https://www.netflix.com/b" },
  ], "https://www.netflix.com");
  assert.deepStrictEqual(got.map((l) => l.text), ["Real"]);
});

test("summarizeLinks dedupes by text and path together", () => {
  const got = P.summarizeLinks([
    { text: "Profiles", href: "https://x.test/p" },
    { text: "Profiles", href: "https://x.test/p" },   // duplicate: drop
    { text: "Profiles", href: "https://x.test/q" },   // same text, other route: keep
    { text: "Manage", href: "https://x.test/p" },     // same route, other text: keep
  ], "https://x.test");
  assert.strictEqual(got.length, 3);
});

test("summarizeLinks collapses whitespace and truncates long text", () => {
  const got = P.summarizeLinks(
    [{ text: "  a\n\n  b  " + "x".repeat(200), href: "https://x.test/a" }],
    "https://x.test");
  assert.ok(got[0].text.startsWith("a b"), `whitespace not collapsed: ${got[0].text}`);
  assert.strictEqual(got[0].text.length, 80);
});

test("summarizeLinks caps how many links it returns", () => {
  const many = [];
  for (let i = 0; i < 500; i++) many.push({ text: "L" + i, href: "https://x.test/" + i });
  assert.strictEqual(P.summarizeLinks(many, "https://x.test").length, 80);
  assert.strictEqual(P.summarizeLinks(many, "https://x.test", 5).length, 5);
});

test("probe() reports links, using aria-label when an icon link has no text", () => {
  // A fake DOM, keyed by the exact selectors probe() asks for. This does not test CSS
  // matching -- that is the browser's job -- it tests what probe() does with what it
  // gets back, which is the part that was untested.
  const el = (props) => Object.assign({
    tagName: "A", textContent: "", id: "", name: "",
    getAttribute: function (k) { return this._attrs && k in this._attrs ? this._attrs[k] : null; },
    querySelectorAll: () => [],
  }, props);

  const bySelector = {
    "h1,h2,h3,h4,label,legend": [el({ tagName: "H1", textContent: "Account" })],
    "[data-testid]": [],
    "select": [],
    "[id]": [el({ id: "appMountPoint" })],
    "a[href]": [
      el({ textContent: "Profiles", href: "https://www.netflix.com/account/profiles" }),
      el({ textContent: "  ", href: "https://www.netflix.com/settings", _attrs: { "aria-label": "Settings" } }),
      el({ textContent: "Help", href: "https://help.netflix.com/support" }),
    ],
  };

  const saved = { d: globalThis.document, l: globalThis.location, p: globalThis.PPDom };
  globalThis.PPPure = P;
  globalThis.document = {
    title: "Account Settings - Netflix",
    querySelectorAll: (sel) => {
      assert.ok(sel in bySelector, `probe() asked for an unstubbed selector: ${sel}`);
      return bySelector[sel];
    },
  };
  globalThis.location = { href: "https://www.netflix.com/account",
                          origin: "https://www.netflix.com" };
  try {
    // eslint-disable-next-line no-eval
    eval(fs.readFileSync(path.join(__dirname, "..", "engine", "dom.js"), "utf8"));
    const shape = globalThis.PPDom.probe();
    assert.deepStrictEqual(shape.links, [
      { text: "Profiles", path: "/account/profiles" },
      { text: "Settings", path: "/settings" },   // aria-label rescued the icon link
    ], "probe() must report same-origin links, and must not report off-origin ones");
    assert.deepStrictEqual(shape.headings, [{ tag: "h1", text: "Account" }]);
  } finally {
    globalThis.document = saved.d;
    globalThis.location = saved.l;
    globalThis.PPDom = saved.p;
  }
});

// --- the manifest asks for exactly what the recipes use ---------------------------
//
// This repo is public and the extension is installed by hand, so its permission list is
// the whole of what a reader has to trust. Netflix was parked and its host permission
// outlived it by one commit -- an extension asking for a site it never visits is asking
// for trust it does not need, and nothing would have caught it.

function loadRecipes() {
  const dir = path.join(__dirname, "..", "recipes");
  globalThis.PPRecipes = {};
  for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".js"))) {
    // eslint-disable-next-line no-eval
    eval(fs.readFileSync(path.join(dir, f), "utf8"));
  }
  return globalThis.PPRecipes;
}

test("every host permission is used by a recipe, and every recipe's host is granted", () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "manifest.json"), "utf8"));
  const granted = new Set(manifest.host_permissions);
  const wanted = new Set();
  for (const r of Object.values(loadRecipes())) {
    if (r.hostPermission) wanted.add(r.hostPermission);
  }
  // localhost is the page->extension channel, not a vendor, so no recipe claims it.
  const infra = new Set(["http://localhost:8787/*"]);

  for (const h of wanted) {
    assert.ok(granted.has(h), `a recipe needs ${h} but the manifest does not ask for it`);
  }
  for (const h of granted) {
    if (infra.has(h)) continue;
    assert.ok(wanted.has(h),
              `the manifest asks for ${h} and no recipe uses it; drop the permission`);
  }
});

test("no recipe targets a vendor the shipped policy no longer carries", () => {
  // Parking a vendor means removing it everywhere. A recipe left behind still loads into
  // the service worker and still shows up as a button.
  const parked = ["netflix"];
  const ids = Object.keys(loadRecipes()).join(" ");
  for (const p of parked) {
    assert.ok(!ids.includes(p), `${p} was parked but a recipe for it still ships: ${ids}`);
  }
});

// --- a failed run keeps its tab -----------------------------------------------------
//
// Closing the tab after a successful read is tidiness. Closing it after a FAILED one
// would break the product: NEEDS_LOGIN means a human has to sign in on that exact tab,
// and closing it removes the only place they can. TIMEOUT and SELECTOR_NOT_FOUND mean
// the page was not what the recipe expected, and the page is the evidence.

test("the tab is closed only on a successful read", () => {
  const bg = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  const calls = bg.split("\n")
    .map((line, i) => [i + 1, line])
    .filter(([, line]) => /\bcloseTab\s*\(/.test(line) && !/^async function closeTab/.test(line.trim()));

  assert.ok(calls.length > 0, "nothing closes the tab; this guard is checking nothing");
  for (const [lineno, line] of calls) {
    assert.match(line, /result\s*&&\s*result\.ok|result\.ok\s*\?/,
                 `background.js:${lineno} closes the tab without checking result.ok — `
                 + `a failed read must keep its tab:\n  ${line.trim()}`);
  }
});

test("a probe never closes its tab", () => {
  // A probe exists to be looked at. Closing it would defeat the entire point.
  const bg = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  // Search for the verify call FROM the probe branch onwards. anchorPresent contains an
  // identical executeScript line earlier in the file, so an unanchored indexOf returned
  // a position before the start and sliced an empty string -- a guard examining nothing.
  const start = bg.indexOf('if (recipe.mode === "probe")');
  assert.ok(start > 0, "could not find the probe branch");
  const end = bg.indexOf("const [{ result }] = await chrome.scripting", start);
  assert.ok(end > start, "could not find the verify call after the probe branch");
  const probeBranch = bg.slice(start, end);
  assert.ok(probeBranch.length > 50, "could not locate the probe branch");
  assert.ok(!/\bcloseTab\s*\(/.test(probeBranch),
            "the probe branch closes its tab; a probe is there to be inspected");
});

// --- the one place the extension writes to a vendor page ----------------------------
//
// announceClose puts a banner on a tab that is about to close. That is the only DOM the
// extension ever creates on a vendor's page, and the point of these guards is that it
// stays that way: fixed content, no recipe input, success only, and nothing touched
// except the banner it makes itself.

function announceCloseSource() {
  const bg = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  const start = bg.indexOf("async function announceClose(");
  assert.ok(start > 0, "announceClose is gone; these guards check nothing");
  const end = bg.indexOf("async function closeTab(", start);
  assert.ok(end > start, "could not find the end of announceClose");
  return bg.slice(start, end);
}

test("the closing notice takes no input from a recipe or the page", () => {
  const src = announceCloseSource();
  for (const leak of ["recipe", "params", "message.", "checked."]) {
    assert.ok(!src.includes(leak),
              `announceClose references ${leak} — its content must be a constant, or a `
              + "recipe could put arbitrary markup on a vendor's page");
  }
  // The only argument it forwards into the page is the countdown.
  assert.match(src, /args:\s*\[seconds\]/,
               "announceClose forwards something other than the countdown into the page");
});

test("the closing notice never sets a value on the page", () => {
  const src = announceCloseSource();
  for (const write of [".value =", ".checked =", ".click()", "submit(", "dispatchEvent"]) {
    assert.ok(!src.includes(write),
              `announceClose contains ${write} — it may create its banner and nothing else`);
  }
});

test("the notice is only shown on the path that closes the tab", () => {
  const bg = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  const calls = bg.split("\n").map((l, i) => [i + 1, l])
    .filter(([, l]) => /\bannounceClose\s*\(/.test(l)
                       && !/^async function announceClose/.test(l.trim()));
  assert.strictEqual(calls.length, 1,
                     "announceClose should be called exactly once, from closeTab");
  const [lineno] = calls[0];
  const inCloseTab = bg.indexOf("async function closeTab(");
  const lineOffset = bg.split("\n").slice(0, lineno - 1).join("\n").length;
  assert.ok(lineOffset > inCloseTab,
            "announceClose is called outside closeTab, so it can fire without a close");
});

// --- fixture state must be resettable ----------------------------------------------
//
// The demo Reset clears browser storage by the "pp-fixture-" prefix. A fixture that
// stored its setting under any other name would keep it across a reset, and the next
// take would open on last take's value while every other signal said clean. Silent, and
// only visible on camera.

test("every fixture stores its state under the pp-fixture- prefix", () => {
  const dir = path.join(__dirname, "fixtures");
  let checked = 0;
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".html"))) {
    const src = fs.readFileSync(path.join(dir, file), "utf8");
    const keys = [...src.matchAll(/localStorage\.(?:get|set|remove)Item\(\s*([A-Za-z_$][\w$]*|"[^"]*")/g)]
      .map((m) => m[1]);
    if (!keys.length) continue;
    // Keys are held in a KEY constant; resolve it to the literal it is assigned.
    for (const ref of new Set(keys)) {
      const literal = ref.startsWith('"')
        ? ref.slice(1, -1)
        : (src.match(new RegExp(`var\\s+${ref}\\s*=\\s*"([^"]*)"`)) || [])[1];
      assert.ok(literal, `${file}: could not resolve the storage key ${ref}`);
      assert.ok(literal.startsWith("pp-fixture-"),
                `${file} stores state under "${literal}" — the demo Reset clears only `
                + `pp-fixture-* keys, so this would survive a reset unnoticed`);
      checked++;
    }
  }
  assert.ok(checked >= 2, `only ${checked} fixture storage key(s) found; both fixtures `
                          + "persist state, so this guard is not seeing one of them");
});

test("every persisting fixture both reads and writes its key", () => {
  // Counting keys is not enough: dropping the setItem leaves the getItem behind, so the
  // key still resolves and the prefix guard passes while the fixture silently stops
  // remembering anything. That mutation survived the first version of these tests.
  const dir = path.join(__dirname, "fixtures");
  let persisting = 0;
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".html"))) {
    const src = fs.readFileSync(path.join(dir, file), "utf8");
    if (!src.includes("localStorage")) continue;
    persisting++;
    assert.match(src, /localStorage\.getItem\(/,
                 `${file} writes state but never reads it back on load`);
    assert.match(src, /localStorage\.setItem\(/,
                 `${file} reads a saved value but never writes one — saving will not `
                 + "survive the fresh tab the dashboard opens to re-read");
  }
  assert.strictEqual(persisting, 3,
                     `${persisting} fixtures persist state; expected vendor-a, vendor-b `
                     + "and family-console, so one has stopped");
});

// --- selector param templating -------------------------------------------------------
//
// A family-roster page lists several children on ONE page; the extension needs to
// search for THIS child's name, and that name is a runtime parameter, not something a
// recipe author can hardcode. Scoped to "ci:" selectors only, deliberately: their text
// is already concatenated into an XPath string with quotes already stripped from it for
// exactly this reason, so a substituted parameter lands inside that same protection. A
// raw hand-written XPath has no such stripping anywhere in it.

test("a ci: selector's {{param}} is filled from the params object", () => {
  const out = P.applySelectorParams(
    { "child.row": ["ci:{{childUsername}}", "ci:fallback"] },
    { childUsername: "alex_example" });
  assert.strictEqual(out.ok, true);
  assert.deepStrictEqual(out.selectors["child.row"], ["ci:alex_example", "ci:fallback"]);
});

test("a selector with no {{}} in it passes through unchanged", () => {
  const out = P.applySelectorParams({ x: ["#static", "ci:literal text"] }, { a: "1" });
  assert.deepStrictEqual(out.selectors.x, ["#static", "ci:literal text"]);
});

test("templating outside a ci: selector is refused, not silently trusted", () => {
  const out = P.applySelectorParams(
    { risky: ["//div[@id='{{childUsername}}']"] }, { childUsername: "alex" });
  assert.strictEqual(out.ok, false);
  assert.strictEqual(out.code, "BAD_PARAMS");
  assert.match(out.error, /outside a "ci:" selector/);
});

test("a param not supplied leaves an unfilled slot, and that fails rather than shipping a literal {{...}}", () => {
  const out = P.applySelectorParams(
    { "child.row": ["ci:{{childUsername}}"] }, { somethingElse: "x" });
  assert.strictEqual(out.ok, false);
  assert.match(out.error, /unfilled slot/);
});

test("multiple params in one selector all get filled", () => {
  const out = P.applySelectorParams(
    { row: ["ci:{{first}} {{second}}"] }, { first: "a", second: "b" });
  assert.strictEqual(out.selectors.row[0], "ci:a b");
});

test("an unrelated recipe with no {{}} anywhere is untouched by the pass", () => {
  const selectors = { a: ["#x"], b: ["ci:Screen time", "//h2"] };
  const out = P.applySelectorParams(selectors, { childUsername: "alex" });
  assert.deepStrictEqual(out.selectors, selectors);
});

// --- the substitution is actually wired into the run, not just unit-tested in isolation
//
// A correctly-tested pure function that nothing calls is the exact shape of bug that
// shipped here before (_catalog/_unused went uncalled for two commits). This scans the
// real source for the wiring rather than trusting that writing the function was enough.

test("background.js substitutes selector params before readiness AND before the run", () => {
  const bg = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  assert.match(bg, /P\.applySelectorParams\(recipe\.selectors,\s*checked\.params\)/,
               "runRecipe never calls applySelectorParams");
  // Both waitForReady (readiness) and the run's executeScript call must receive the
  // SUBSTITUTED map, not the recipe's raw one -- a stray `recipe.selectors` anywhere
  // downstream of the substitution would silently un-fill every {{param}}.
  const afterSub = bg.slice(bg.indexOf("P.applySelectorParams("));
  assert.ok(!/waitForReady\(tab\.id,\s*recipe,\s*recipe\.selectors\)/.test(afterSub),
            "waitForReady is passed the unsubstituted selectors");
  assert.ok(!/args:\s*\[recipe,\s*recipe\.selectors,/.test(afterSub),
            "the run's executeScript is passed the unsubstituted selectors");
  assert.match(afterSub, /waitForReady\(tab\.id,\s*recipe,\s*selectors\)/);
  assert.match(afterSub, /args:\s*\[recipe,\s*selectors,/);
});
