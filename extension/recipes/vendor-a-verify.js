// Fixture recipe, shape 1: custom dropdown widget, drawer, child picker.
// Proves the engine against the awkward shape without touching a real vendor.
globalThis.PPRecipes = globalThis.PPRecipes || {};
globalThis.PPRecipes["vendor-a-verify"] = {
  id: "vendor-a-verify",
  version: 1,
  mode: "verify",
  label: "Vendor A (fixture)",
  url: "http://localhost:8787/extension/test/fixtures/vendor-a.html",
  hostPermission: "http://localhost:8787/*",
  readyAnchor: "parental.section",
  params: {
    childUsername:  { type: "string",  required: true, maxLength: 50 },
    minutesPerDay:  { type: "integer", required: true, min: 0, max: 1440 },
  },
  preflight: [
    { assert: "parental.section", else: "NOT_LINKED",
      describe: "parental controls section is present" },
  ],
  steps: [
    { action: "click",   selector: "screentime.manage", describe: "open Screen time > Manage" },
    { action: "waitFor", selector: "screentime.panel",  describe: "screen time panel opens" },
  ],
  read: [
    // The child picker is READ, not set -- selecting one would be a write. The plane
    // compares it against the child the rule is about. "Exactly one child matched" is
    // an assertion, never an assumption.
    { as: "selectedChild", selector: "parental.childPicker", extract: "value",
      describe: "read which child is selected" },
    { as: "dailyLimitText", selector: "screentime.dailyLimit", extract: "text",
      describe: "read the daily limit" },
    { as: "offeredText",    selector: "screentime.dailyLimitOptions", extract: "optionList",
      describe: "read the options the app actually offers" },
  ],
  // Fallbacks in the brief's priority order: data-testid, then role/aria, then visible
  // text via XPath. Never a generated class name.
  selectors: {
    "parental.section": ['[data-testid="parental-section"]', "//h2[normalize-space()='Parental Controls']/.."],
    "parental.childPicker": ['[data-testid="child-picker"]'],
    "screentime.manage": ['[data-testid="screentime-manage"]', "//button[normalize-space()='Manage']"],
    "screentime.panel": ['[data-testid="screentime-panel"]'],
    "screentime.dailyLimit": ['[data-testid="daily-limit-value"]'],
    "screentime.dailyLimitOptions": ['[data-testid="daily-limit-options"]', '[role="listbox"]'],
  },
};
