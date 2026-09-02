// Fixture recipe, shape 2: the genericity proof.
//
// Native <select>, a plain table, no drawer, no child picker, bare-minutes values, and a
// completely different vocabulary. It reads through the SAME engine with zero engine
// changes. If it ever needs one, the abstraction has gone vendor-shaped.
globalThis.PPRecipes = globalThis.PPRecipes || {};
globalThis.PPRecipes["vendor-b-verify"] = {
  id: "vendor-b-verify",
  version: 1,
  mode: "verify",
  label: "Vendor B (fixture)",
  url: "http://localhost:8787/extension/test/fixtures/vendor-b.html",
  hostPermission: "http://localhost:8787/*",
  readyAnchor: "limits.section",
  params: {
    minutesPerDay: { type: "integer", required: true, min: 0, max: 1440 },
  },
  preflight: [
    { assert: "limits.section", else: "WRONG_ACCOUNT", describe: "usage limits are present" },
  ],
  steps: [],                       // no navigation needed -- a different shape entirely
  read: [
    { as: "dailyLimitText", selector: "limits.daily", extract: "text",
      describe: "read the daily allowance" },
    { as: "offeredText",    selector: "limits.options", extract: "optionList",
      describe: "read the allowances on offer" },
  ],
  selectors: {
    "limits.section": ["#limits", "//h2[normalize-space()='Usage limits']/.."],
    "limits.daily": ["#daily-allowance", "//th[normalize-space()='Daily allowance']/following-sibling::td"],
    "limits.options": ["#allowance-select"],
  },
};
