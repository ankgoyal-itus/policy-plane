// The DOM shell. Deliberately thin: every decision lives in pure.js, so what remains
// here is only "how do I ask the page a question".
//
// Injected into the target tab by the service worker. Runs in the page's world with no
// access to extension APIs, which is the point -- it can read the page and nothing else.

(function () {
  const P = globalThis.PPPure;

  function query(selector) {
    // Expansion is pure string work and lives in pure.js so it can be tested without a
    // DOM -- and so there is exactly one implementation of it.
    selector = P.expandSelector(selector);
    if (P.isXPath(selector)) {
      const r = document.evaluate(selector, document, null,
                                 XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      return r.singleNodeValue;
    }
    return document.querySelector(selector);
  }

  function visible(el) {
    if (!el) return false;
    if (el.hidden) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    return el.getClientRects().length > 0 || el.offsetParent !== null
           || style.position === "fixed";
  }

  /** Resolve a named selector from the recipe's selector map, trying fallbacks in order. */
  function resolve(selectors, name, { mustBeVisible = false } = {}) {
    const candidates = selectors[name];
    if (!candidates) {
      return { found: false, error: `no selector named '${name}' in this recipe` };
    }
    const probe = (sel) => {
      const el = query(sel);
      return !!el && (!mustBeVisible || visible(el));
    };
    const picked = P.pickSelector(candidates, probe);
    return picked.found
      ? { found: true, el: query(picked.matched), matched: picked.matched, tried: picked.tried }
      : { found: false, tried: picked.tried };
  }

  function waitFor(selectors, name, timeoutMs, opts) {
    return new Promise((resolve_) => {
      const deadline = Date.now() + timeoutMs;
      const tick = () => {
        const got = resolve(selectors, name, opts);
        if (got.found) return resolve_(got);
        // Wait on STATE, never on a clock. Sleep-driven sequencing is what makes
        // these break on a slow network.
        if (Date.now() > deadline) return resolve_({ found: false, timedOut: true, tried: got.tried });
        setTimeout(tick, 80);
      };
      tick();
    });
  }

  function extract(el, how) {
    if (!el) return null;
    if (how === "optionList") {
      const kids = el.tagName === "SELECT"
        ? Array.from(el.querySelectorAll("option"))
        : Array.from(el.querySelectorAll('[role="option"], li, div'));
      return kids.map((k) => (k.textContent || "").trim()).filter(Boolean);
    }
    if (how === "selectedText") {
      // For a native <select> the useful reading is the option TEXT ("1 Hour"), not the
      // value attribute, which is often an opaque id.
      if (el.tagName === "SELECT") {
        var opt = el.selectedOptions && el.selectedOptions[0];
        return opt ? (opt.textContent || "").trim() : "";
      }
      return (el.textContent || "").trim();
    }
    if (how === "value") return "value" in el ? String(el.value) : (el.textContent || "").trim();
    return (el.textContent || "").trim();
  }

  /** Run a recipe's read-only steps, then its reads. Returns a typed result. */
  async function run(recipe, selectors, params) {
    const trace = [];
    const note = (step, outcome, extra) =>
      trace.push(Object.assign({ step, outcome }, extra || {}));

    for (const check of recipe.preflight || []) {
      const got = await waitFor(selectors, check.assert, check.timeout || 4000);
      note(check.describe || `preflight ${check.assert}`, got.found ? "ok" : "fail",
           { matched: got.matched, tried: got.tried });
      if (!got.found) {
        return { ok: false, code: check.else || P.CODES.SELECTOR_NOT_FOUND,
                 failingStep: check.describe || check.assert, trace };
      }
    }

    for (const step of recipe.steps || []) {
      if (P.isWriteAction(step.action)) {
        // Cannot happen with the current action set; asserted anyway so that adding a
        // write action later fails loudly here instead of quietly changing a setting.
        return { ok: false, code: P.CODES.BLOCKED_BY_POLICY,
                 failingStep: step.describe, error: `write action '${step.action}' in a verify recipe`, trace };
      }
      const timeout = step.timeout || 8000;
      if (step.action === "waitFor" || step.action === "click") {
        const got = await waitFor(selectors, step.selector, timeout,
                                  { mustBeVisible: step.action === "click" });
        note(step.describe, got.found ? "ok" : (got.timedOut ? "timeout" : "not found"),
             { matched: got.matched, tried: got.tried });
        if (!got.found) {
          return { ok: false, code: got.timedOut ? P.CODES.TIMEOUT : P.CODES.SELECTOR_NOT_FOUND,
                   failingStep: step.describe, trace };
        }
        if (step.action === "click") {
          got.el.scrollIntoView({ block: "center" });
          got.el.click();
        }
      }
    }

    const readings = {};
    for (const read of recipe.read || []) {
      const got = await waitFor(selectors, read.selector, read.timeout || 8000);
      note(read.describe || `read ${read.as}`, got.found ? "ok" : "not found",
           { matched: got.matched, tried: got.tried });
      if (!got.found) {
        return { ok: false, code: P.CODES.SELECTOR_NOT_FOUND,
                 failingStep: read.describe || `read ${read.as}`, trace };
      }
      readings[read.as] = extract(got.el, read.extract || "text");
    }

    // `url` costs no selector and cannot go missing. It is the identity check for any
    // recipe routed by id: if the page redirected elsewhere, everything read off it
    // describes something else.
    return { ok: true, code: P.CODES.OK, readings, url: location.href, trace };
  }

  /**
   * Structural reconnaissance, for authoring selectors against a page nobody can see.
   *
   * Returns SHAPE, not content: tag names, ids, data-testids, headings, the option
   * lists of any <select>, and the page's same-origin links. It turns selector
   * calibration from guesswork into one round trip. Deliberately does not return
   * arbitrary page text.
   *
   * One caveat worth stating out loud: a link path can carry an account identifier --
   * a Netflix profile GUID, a Roblox child id. Probe output is therefore as sensitive
   * as policy.local.yaml and belongs nowhere near a tracked file.
   */
  function probe() {
    const headings = Array.from(document.querySelectorAll("h1,h2,h3,h4,label,legend"))
      .map((el) => ({ tag: el.tagName.toLowerCase(),
                      text: (el.textContent || "").trim().slice(0, 80) }))
      .filter((h) => h.text).slice(0, 60);
    const testids = Array.from(document.querySelectorAll("[data-testid]"))
      .map((el) => el.getAttribute("data-testid")).slice(0, 120);
    const selects = Array.from(document.querySelectorAll("select")).map((el) => ({
      id: el.id || null,
      name: el.name || null,
      testid: el.getAttribute("data-testid"),
      ariaLabel: el.getAttribute("aria-label"),
      selectedText: el.selectedOptions && el.selectedOptions[0]
        ? (el.selectedOptions[0].textContent || "").trim() : null,
      optionCount: el.options ? el.options.length : 0,
      firstOptions: Array.from(el.querySelectorAll("option")).slice(0, 8)
        .map((o) => (o.textContent || "").trim()),
    }));
    const ids = Array.from(document.querySelectorAll("[id]"))
      .map((el) => el.id).filter(Boolean).slice(0, 120);
    // Links are the route shape. On a page with no <select>, no data-testid and no
    // stable id, they are the only structure there is to author selectors against.
    // aria-label is the fallback because an icon link carries its meaning there.
    const links = P.summarizeLinks(
      Array.from(document.querySelectorAll("a[href]")).map((a) => ({
        text: (a.textContent || "").trim() || a.getAttribute("aria-label") || "",
        href: a.href,
      })),
      location.origin);
    return { url: location.href, title: document.title, headings, testids, selects, ids, links };
  }

  globalThis.PPDom = { run, resolve, waitFor, extract, query, visible, probe };
})();
