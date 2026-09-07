// Service worker. Owns the recipe registry, validates everything the page sends, opens
// the tab, injects the engine, and returns a typed result.
//
// The security rule, by construction rather than by validation: the page sends a recipe
// ID and parameters. It cannot send selectors, steps, URLs or code, because there is no
// field here that would accept them. Recipes live in this extension.

import "./engine/pure.js";
import "./recipes/vendor-a-verify.js";
import "./recipes/vendor-b-verify.js";
import "./recipes/family-console-schedule-verify.js";

const P = globalThis.PPPure;
const RECIPES = globalThis.PPRecipes;
const ALLOWED_ORIGINS = new Set(["http://localhost:8787"]);

const MAX_READY_MS = 120000;   // generous: a human may be logging in during this
const CLOSE_DELAY_MS = 3000;  // long enough to read the page and the notice
const POLL_MS = 500;

function fail(code, error, extra) {
  return Object.assign({ ok: false, code, error }, extra || {});
}

async function inject(tabId) {
  const [{ result: already }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => !!(globalThis.PPDom && globalThis.PPPure),
  });
  if (already) return;
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["engine/pure.js", "engine/dom.js"],
  });
}

async function anchorPresent(tabId, recipe, selectors) {
  const candidates = selectors[recipe.readyAnchor] || [];
  try {
    // Inject the engine and use ITS resolver. This used to be a second, simpler
    // selector implementation living here, which is how the "ci:" case-insensitive
    // prefix worked in dom.js and silently did not work for the readiness poll --
    // querySelector("ci:...") throws, the catch swallowed it, and the run timed out
    // after two minutes with nothing to show for it. One resolver, one behaviour.
    await inject(tabId);
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      args: [candidates],
      // Return WHICH candidate matched, not merely that one did. A readiness list is
      // a list of guesses; without this the run reports "the page was ready" and never
      // says which guess was right, so a stale first candidate and a working fallback
      // are indistinguishable in the output.
      func: (sels) => {
        for (const s of sels) {
          try { if (globalThis.PPDom.query(s)) return s; } catch (e) { /* next */ }
        }
        return null;
      },
    });
    return { present: !!result, matched: result || null, gone: false };
  } catch (e) {
    // The tab was closed, or navigated somewhere we have no host permission for.
    return { present: false, gone: true, why: String(e && e.message) };
  }
}

/**
 * Wait for the page to be genuinely usable.
 *
 * `status: complete` is not enough for an SPA -- it fires before the app renders, and
 * on a login redirect it fires on the login page. Readiness is "the recipe's anchor
 * selector exists", polled. That also makes the login case free: while the human signs
 * in, the anchor simply is not there yet, and we keep waiting.
 */
async function waitForReady(tabId, recipe, selectors) {
  const deadline = Date.now() + MAX_READY_MS;
  let sawTab = false;
  while (Date.now() < deadline) {
    const got = await anchorPresent(tabId, recipe, selectors);
    if (got.present) {
      return { ready: true, matched: got.matched,
               waitedMs: MAX_READY_MS - (deadline - Date.now()) };
    }
    if (got.gone) {
      if (sawTab) return { ready: false, code: P.CODES.TAB_CLOSED };
    } else {
      sawTab = true;
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  return { ready: false, code: P.CODES.TIMEOUT };
}

/**
 * Put a fixed notice at the top of a tab we are about to close.
 *
 * This is the ONE place the extension writes to a vendor page, and the boundaries are
 * deliberate: the content is a constant in this file, it takes no argument from a recipe
 * or from the dashboard, it runs only after a successful read, and it touches nothing but
 * a banner element it creates itself. Recipes still have no verb for writing -- the
 * action set is waitFor, click, read -- so nothing about what a recipe can do has
 * changed. What has changed is that a tab no longer vanishes without saying why.
 */
async function announceClose(tabId, seconds) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      args: [seconds],
      func: (secs) => {
        const ID = "policy-plane-closing";
        document.getElementById(ID)?.remove();
        const bar = document.createElement("div");
        bar.id = ID;
        bar.setAttribute("role", "status");
        bar.style.cssText = [
          "position:fixed", "top:0", "left:0", "right:0", "z-index:2147483647",
          "background:#1a7f4b", "color:#fff", "padding:11px 16px",
          "font:600 14px/1.4 ui-sans-serif,-apple-system,'Segoe UI',Roboto,sans-serif",
          "text-align:center", "box-shadow:0 1px 6px rgba(0,0,0,.25)",
        ].join(";");
        const say = (n) => {
          bar.textContent = "Policy Plane read this page. Nothing was changed. "
            + "Closing in " + n + "…";
        };
        say(secs);
        document.documentElement.appendChild(bar);
        let left = secs;
        const t = setInterval(() => {
          left -= 1;
          if (left <= 0) { clearInterval(t); bar.textContent =
            "Policy Plane read this page. Nothing was changed. Closing…"; return; }
          say(left);
        }, 1000);
      },
    });
    return true;
  } catch (e) {
    return false;                 // the page blocks injection, or the tab is gone
  }
}


/** Close a tab we opened. Never throws: a failure here must not lose a good reading. */
async function closeTab(tabId) {
  // Say what is about to happen, then wait. A tab that opens, does something invisible
  // and disappears is unsettling on a page that holds a child's settings -- especially
  // when the whole claim is that nothing was written.
  await announceClose(tabId, Math.round(CLOSE_DELAY_MS / 1000));
  await new Promise((r) => setTimeout(r, CLOSE_DELAY_MS));
  try {
    await chrome.tabs.remove(tabId);
    return true;
  } catch (e) {
    return false;                 // already closed by the human, or gone
  }
}


async function runRecipe(message) {
  const recipe = RECIPES[message.recipeId];
  if (!recipe) {
    return fail(P.CODES.BAD_PARAMS, `unknown recipe: ${message.recipeId}`,
                { known: Object.keys(RECIPES) });
  }
  if (recipe.mode !== "verify" && recipe.mode !== "probe") {
    return fail(P.CODES.BLOCKED_BY_POLICY, "this build runs verify and probe recipes only");
  }

  const checked = P.validateParams(recipe.params, message.params);
  if (!checked.ok) return checked;

  const filled = P.applySelectorParams(recipe.selectors, checked.params);
  if (!filled.ok) return filled;
  const selectors = filled.selectors;

  // The recipe owns the URL TEMPLATE; the page supplies only values, and only values
  // the recipe's schema already validated. childUserId is an integer, so it cannot
  // contain a path separator or a scheme. The origin is re-checked afterwards anyway.
  let url = recipe.url;
  for (const [key, value] of Object.entries(checked.params)) {
    url = url.split(`{{${key}}}`).join(String(value));
  }
  if (url.includes("{{")) {
    return fail(P.CODES.BAD_PARAMS, `recipe url still has unfilled slots: ${url}`);
  }
  if (recipe.origin && !url.startsWith(recipe.origin)) {
    return fail(P.CODES.BLOCKED_BY_POLICY,
                `resolved url left the recipe's declared origin ${recipe.origin}`);
  }

  const runId = crypto.randomUUID();
  const tab = await chrome.tabs.create({ url, active: true });

  const ready = await waitForReady(tab.id, recipe, selectors);
  if (!ready.ready) {
    return fail(ready.code,
                ready.code === P.CODES.TIMEOUT
                  ? `the page never showed '${recipe.readyAnchor}'. If a login was needed, `
                    + "finish signing in and run it again."
                  : "the tab was closed before the page was ready",
                { runId, recipeId: recipe.id, tabId: tab.id });
  }

  try {
    await inject(tab.id);
    if (recipe.mode === "probe") {
      const [{ result: shape }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => globalThis.PPDom.probe(),
      });
      return { ok: true, code: P.CODES.OK, runId, recipeId: recipe.id,
               calibrated: true, tabId: tab.id,
               readyAnchor: { name: recipe.readyAnchor, matched: ready.matched },
               probe: shape };
    }
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      args: [recipe, selectors, checked.params],
      func: (r, sels, params) => globalThis.PPDom.run(r, sels, params),
    });

    // Tidy up after a SUCCESSFUL read only.
    //
    // A failed run leaves its tab open on purpose, and that is not politeness -- it is
    // how the login case works. NEEDS_LOGIN means "a human has to sign in here"; closing
    // the tab would take away the only place they can do it. TIMEOUT and
    // SELECTOR_NOT_FOUND mean the page was not what the recipe expected, and the page
    // is the evidence. Probe tabs stay open too: a probe exists to be looked at.
    const closed = result && result.ok ? await closeTab(tab.id) : false;

    return Object.assign({ runId, recipeId: recipe.id, recipeVersion: recipe.version,
                           calibrated: recipe.calibrated !== false, tabId: tab.id,
                           tabClosed: closed,
                           readyAnchor: { name: recipe.readyAnchor, matched: ready.matched } },
                         result);
  } catch (e) {
    return fail(P.CODES.UNKNOWN, String(e && e.message), { runId, recipeId: recipe.id });
  }
}

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  // The manifest already filters by origin; re-checked because a manifest edit is one
  // careless commit away and this is the only gate in front of everything above.
  if (!ALLOWED_ORIGINS.has(sender.origin)) {
    sendResponse(fail(P.CODES.BLOCKED_BY_POLICY, "origin not allowed"));
    return false;
  }

  if (message && message.type === "PING") {
    sendResponse({
      ok: true, pong: true, code: P.CODES.OK,
      version: chrome.runtime.getManifest().version,
      recipes: Object.values(RECIPES).map((r) => ({
        id: r.id, label: r.label, version: r.version, mode: r.mode,
        calibrated: r.calibrated !== false,
        // The param schema, so a caller renders the right fields instead of guessing.
        // Guessing is how the runner sent minutesPerDay to a recipe that wanted
        // childUserId and got BAD_PARAMS.
        params: r.params,
      })),
    });
    return false;
  }

  if (message && message.type === "RUN_RECIPE") {
    runRecipe(message).then(sendResponse).catch((e) =>
      sendResponse(fail(P.CODES.UNKNOWN, String(e && e.message))));
    return true;                       // async response
  }

  sendResponse(fail(P.CODES.BAD_PARAMS, `unknown message type: ${message && message.type}`));
  return false;
});
