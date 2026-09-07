// Pure engine logic. No DOM, no chrome APIs, no network -- so it runs under plain node
// and needs no browser to test.
//
// Everything that touches a page is injected as a callback (`probe`, `extract`), which
// is the seam that keeps this file testable and keeps the DOM shell thin enough to
// review by eye.

// Wrapped in an IIFE so re-injecting this file into a page is harmless. Without it,
// a second injection redeclares `const CODES` and throws SyntaxError, which kills
// the whole script -- and the readiness poll injects on every attempt.
(function () {
  const CODES = {
    OK: "OK",
    NEEDS_LOGIN: "NEEDS_LOGIN",
    NEEDS_REAUTH: "NEEDS_REAUTH",
    NOT_LINKED: "NOT_LINKED",
    WRONG_ACCOUNT: "WRONG_ACCOUNT",
    VALUE_NOT_AVAILABLE: "VALUE_NOT_AVAILABLE",
    SELECTOR_NOT_FOUND: "SELECTOR_NOT_FOUND",
    TIMEOUT: "TIMEOUT",
    VERIFY_FAILED: "VERIFY_FAILED",
    BLOCKED_BY_POLICY: "BLOCKED_BY_POLICY",
    BAD_PARAMS: "BAD_PARAMS",
    TAB_CLOSED: "TAB_CLOSED",
    UNKNOWN: "UNKNOWN",
  };

  // Read-only build. There is deliberately no setValue, setChecked, or commit action --
  // a verify recipe cannot write because the engine has no way to, not because a flag
  // says not to. Adding one is a visible change to this list.
  const ACTIONS = ["waitFor", "click", "read"];
  const WRITE_ACTIONS = ["setValue", "setChecked", "setRichText", "selectOption", "commit"];

  function isWriteAction(action) {
    return WRITE_ACTIONS.includes(action);
  }

  /** Validate params against a recipe's declared schema. Never coerces. */
  function validateParams(schema, params) {
    const out = {};
    const given = params || {};
    const unknown = Object.keys(given).filter((k) => !(k in schema));
    if (unknown.length) {
      return { ok: false, code: CODES.BAD_PARAMS, error: `unknown param(s): ${unknown.join(", ")}` };
    }
    for (const [name, spec] of Object.entries(schema)) {
      let value = given[name];
      if (value === undefined || value === null) {
        if (spec.required) {
          return { ok: false, code: CODES.BAD_PARAMS, error: `missing required param: ${name}` };
        }
        if ("default" in spec) value = spec.default;
        else continue;
      }
      if (spec.type === "integer") {
        if (typeof value !== "number" || !Number.isInteger(value)) {
          return { ok: false, code: CODES.BAD_PARAMS, error: `${name} must be a whole number` };
        }
        if (spec.min !== undefined && value < spec.min) {
          return { ok: false, code: CODES.BAD_PARAMS, error: `${name} below minimum ${spec.min}` };
        }
        if (spec.max !== undefined && value > spec.max) {
          return { ok: false, code: CODES.BAD_PARAMS, error: `${name} above maximum ${spec.max}` };
        }
      } else if (spec.type === "string") {
        if (typeof value !== "string") {
          return { ok: false, code: CODES.BAD_PARAMS, error: `${name} must be a string` };
        }
        if (spec.maxLength && value.length > spec.maxLength) {
          return { ok: false, code: CODES.BAD_PARAMS, error: `${name} is too long` };
        }
      } else if (spec.type === "boolean") {
        if (typeof value !== "boolean") {
          return { ok: false, code: CODES.BAD_PARAMS, error: `${name} must be true or false` };
        }
      }
      out[name] = value;
    }
    return { ok: true, params: out };
  }

  const _LOWER = "abcdefghijklmnopqrstuvwxyz";
  const _UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

  /**
   * Expand a "ci:some text" selector into a case-INSENSITIVE XPath text match.
   *
   * XPath 1.0's contains() is case-sensitive, which is how a readyAnchor looking for
   * "Parental Controls" timed out forever on a page that says "Parental controls".
   * translate() is the standard workaround and far too fiddly to retype per recipe.
   *
   * Pure string work, so it lives here and is testable without a DOM. Anything else that
   * resolves selectors must call this rather than reimplement it.
   */
  function expandSelector(selector) {
    if (!selector.startsWith("ci:")) return selector;
    const text = selector.slice(3).toLowerCase().replace(/'/g, "");
    // A bare contains() on normalize-space() matches every ANCESTOR of the real target
    // too, because normalize-space() reads an element's full descendant text, not just
    // its own. FIRST_ORDERED_NODE_TYPE walks the document in preorder, so the ancestor
    // -- <html>, most of the time -- comes before its own matching descendant and wins.
    // That was invisible for as long as "ci:" only ever answered "does this text exist
    // anywhere" (a readyAnchor or a preflight assert); it surfaced the first time a
    // "ci:" match became a CLICK TARGET, where clicking <html> does nothing. The
    // `not(.//*[...])` clause excludes any element that has a matching descendant, so
    // the innermost element carrying the text wins instead.
    const cond = "contains(translate(normalize-space(),'" + _UPPER + "','" + _LOWER
                 + "'),'" + text + "')";
    return "//*[" + cond + " and not(.//*[" + cond + "])]";
  }

  function isXPath(selector) {
    return selector.startsWith("//") || selector.startsWith("(//");
  }

  /**
   * Substitute {{param}} placeholders into a recipe's whole selector map, ONCE, before
   * anything is injected into the page.
   *
   * Scoped to "ci:" selectors only, and this is a security boundary, not a style choice.
   * A "ci:" selector's text is already concatenated into an XPath string, and quotes are
   * already stripped from it for exactly this reason -- a family-roster page needs to
   * search for a CHILD'S NAME, which is a runtime parameter, not something a recipe
   * author can hardcode, so the substituted value has to land inside that same protected
   * text. A raw hand-written XPath selector has no such stripping anywhere in it, so a
   * parameter value containing a stray quote could rewrite what the query matches --
   * this rejects that case at the door rather than trusting it silently.
   */
  function applySelectorParams(selectors, params) {
    const out = {};
    for (const [name, candidates] of Object.entries(selectors || {})) {
      const filled = [];
      for (const sel of candidates) {
        if (!sel.includes("{{")) { filled.push(sel); continue; }
        if (!sel.startsWith("ci:")) {
          return { ok: false, code: CODES.BAD_PARAMS,
                   error: `selector '${name}' templates a param outside a "ci:" `
                          + `selector, which is not allowed: ${sel}` };
        }
        let done = sel;
        for (const [key, value] of Object.entries(params || {})) {
          done = done.split(`{{${key}}}`).join(String(value));
        }
        if (done.includes("{{")) {
          return { ok: false, code: CODES.BAD_PARAMS,
                   error: `selector '${name}' still has an unfilled slot: ${done}` };
        }
        filled.push(done);
      }
      out[name] = filled;
    }
    return { ok: true, selectors: out };
  }

  /**
   * Try a selector's fallback list in order and report WHICH one matched.
   *
   * Reporting the winner is the point: when a vendor reshuffles its DOM you see the
   * matches drift down the list in the logs before anything actually breaks.
   */
  function pickSelector(candidates, probe) {
    const tried = [];
    for (const candidate of candidates) {
      tried.push(candidate);
      if (probe(candidate)) return { found: true, matched: candidate, tried };
    }
    return { found: false, matched: null, tried };
  }

  /** Parse "1 hour 30 minutes", "90 min", "1h", "None" into minutes. null if unreadable. */
  function parseMinutes(text) {
    if (text === null || text === undefined) return null;
    const s = String(text).trim().toLowerCase();
    if (!s) return null;
    if (/^(none|no limit|unlimited|off)$/.test(s)) return 0;
    let total = 0;
    let seen = false;
    const hours = s.match(/(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b/);
    if (hours) { total += parseFloat(hours[1]) * 60; seen = true; }
    const mins = s.match(/(\d+)\s*(?:m|min|mins|minute|minutes)\b/);
    if (mins) { total += parseInt(mins[1], 10); seen = true; }
    if (!seen) {
      const bare = s.match(/^(\d+)$/);
      if (!bare) return null;
      total = parseInt(bare[1], 10);
    }
    return Math.round(total);
  }

  // NOTE: there is deliberately no judgeValue here. The extension READS; the plane
  // JUDGES. Putting the verdict in the component that did the reading would let it grade
  // its own homework, and that separation is the only thing keeping verification honest
  // once a write path exists. `parseMinutes` stays because normalising "1 hour 30 minutes"
  // is part of reading -- but it is returned as ADVISORY, and Python re-parses the raw
  // text itself and uses its own answer.

  /**
   * Reduce a page's anchors to its ROUTE SHAPE, for selector authoring.
   *
   * This exists because Netflix's account page reports no <select>, no data-testid, and
   * no stable id -- every id but the mount point is a React useId value (":Rqekelalalal6:"),
   * generated from a component's position in the render tree. Those change on Netflix's
   * next deploy and contain colons that break CSS selectors, so building on them would
   * look like it worked and rot silently. What such a page does offer is links and text,
   * and the probe was blind to both.
   *
   * Same-origin only: off-origin anchors are navigation chrome and adverts, not route
   * structure. The query string and hash are KEPT -- Roblox's parental-controls page is
   * reached by hash route (#!/parental-controls/...), so a summariser that kept only
   * `pathname` would flatten every child's page to the same "/my/account" and report
   * that the deep link does not exist.
   */
  function summarizeLinks(raw, origin, cap) {
    const limit = cap || 80;
    const out = [];
    const seen = new Set();
    for (const a of raw || []) {
      const text = String((a && a.text) || "").replace(/\s+/g, " ").trim().slice(0, 80);
      const href = String((a && a.href) || "");
      if (!text || !href) continue;
      if (origin && href.indexOf(origin) !== 0) continue;
      const path = href.slice(origin ? origin.length : 0) || "/";
      const key = text + " " + path;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ text: text, path: path });
      if (out.length >= limit) break;
    }
    return out;
  }

  const PPPure = {
    CODES, ACTIONS, WRITE_ACTIONS, isWriteAction,
    validateParams, pickSelector, parseMinutes, expandSelector, isXPath,
    summarizeLinks, applySelectorParams,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = PPPure;
  if (typeof globalThis !== "undefined") globalThis.PPPure = PPPure;
})();
