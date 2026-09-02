// Service worker. Owns the recipe registry, validates everything the page sends, opens
// the tab, injects the engine, and returns a typed result.
//
// The security rule, by construction rather than by validation: the page sends a recipe
// ID and parameters. It cannot send selectors, steps, URLs or code, because there is no
// field here that would accept them. Recipes live in this extension.

import "./engine/pure.js";
import "./recipes/vendor-a-verify.js";
import "./recipes/vendor-b-verify.js";

const P = globalThis.PPPure;
const RECIPES = globalThis.PPRecipes;
const ALLOWED_ORIGINS = new Set(["http://localhost:8787"]);

const MAX_READY_MS = 120000;   // generous: a human may be logging in during this
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

async function anchorPresent(tabId, recipe) {
  const candidates = recipe.selectors[recipe.readyAnchor] || [];
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
async function waitForReady(tabId, recipe) {
  const deadline = Date.now() + MAX_READY_MS;
  let sawTab = false;
  while (Date.now() < deadline) {
    const got = await anchorPresent(tabId, recipe);
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

  const ready = await waitForReady(tab.id, recipe);
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
      args: [recipe, recipe.selectors, checked.params],
      func: (r, sels, params) => globalThis.PPDom.run(r, sels, params),
    });
    return Object.assign({ runId, recipeId: recipe.id, recipeVersion: recipe.version,
                           calibrated: recipe.calibrated !== false, tabId: tab.id,
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
