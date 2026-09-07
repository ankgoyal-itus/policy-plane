// Fixture recipe, shape 3: several children on ONE page, no per-child URL, no
// single-selection dropdown. Roblox is routed by id in the URL; Vendor A/B pick one
// child from a <select>. This one has to search a roster for a name that is a runtime
// parameter, which is what selector templating (applySelectorParams, pure.js) exists
// for -- and it is the shape a real family-hub page is, not a shape invented to be easy.
//
// The read needs NO templating at all. Only one child's panel is ever open at a time
// (the fixture's own JS enforces that), so ".panel.open .current" already scopes to
// whichever child was just clicked -- templating only has to find and click the right
// row; after that, "the open one" is unambiguous on its own.
globalThis.PPRecipes = globalThis.PPRecipes || {};
globalThis.PPRecipes["family-console-schedule-verify"] = {
  id: "family-console-schedule-verify",
  version: 1,
  mode: "verify",
  label: "Family Console (fixture)",
  url: "http://localhost:8787/extension/test/fixtures/family-console.html",
  hostPermission: "http://localhost:8787/*",
  readyAnchor: "roster.section",
  params: {
    childUsername: { type: "string", required: true, maxLength: 50 },
  },
  preflight: [
    { assert: "roster.section", else: "NEEDS_LOGIN",
      describe: "the family roster is present" },
    // The one preflight this fixture exists to prove: a name that never appears on the
    // page -- wrong child, wrong family group, account not actually linked -- fails
    // here, distinctly from a page that never loaded at all.
    { assert: "child.row", else: "NOT_LINKED",
      describe: "this child appears in the family group" },
  ],
  steps: [
    { action: "click", selector: "child.row", describe: "open this child's panel" },
  ],
  read: [
    // Read back WHICH child's panel is actually open, the same discipline Roblox and
    // Vendor A use for their pickers. Clicking the right row is the plane's INTENT;
    // this is the confirmation that the page agrees, independent of that click --
    // exactly the gap a required-but-unread childUsername left open once before.
    { as: "selectedChild", selector: "panel.name", extract: "text",
      describe: "read which child's panel is open" },
    { as: "notAfterText", selector: "panel.value", extract: "text",
      describe: "read the bedtime cutoff from the open panel" },
  ],
  selectors: {
    "roster.section": ["#roster", '[data-testid="roster"]'],
    // Templated. Matches whichever row's visible NAME TEXT contains this child's
    // username -- filled from the params object once, in background.js, before
    // anything is injected. See pure.js: applySelectorParams.
    "child.row": ["ci:{{childUsername}}"],
    // NEITHER of these is templated, and neither needs to be: exactly one panel
    // carries .open at a time, so both always mean "the child we just clicked".
    "panel.name": ['.panel.open [data-role="viewing"]'],
    "panel.value": [".panel.open .current"],
  },
};
