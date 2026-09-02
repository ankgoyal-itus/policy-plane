# policy-plane recipe runner

A Manifest V3 Chrome extension that reads parental-control settings pages and reports
what they say. **Read-only** — it does not change any setting.

## Where this is

The engine, two fixture recipes and the Roblox recipe are in. Roblox's **selectors are
uncalibrated** — nobody has run them against a real logged-in page — so it is expected to
fail with `SELECTOR_NOT_FOUND` and a named step until a calibration pass replaces them.

Working today, against local fixtures: `vendor-a-verify` (custom dropdown, drawer, child
picker) and `vendor-b-verify` (native select, plain table, nothing like the first).

## Read-only by construction

The action set is `waitFor`, `click`, `read`. There is no `setValue`, `setChecked`,
`selectOption` or `commit` anywhere in the engine, so a verify recipe cannot write
because there is no way for it to — not because a flag says not to. A test asserts the
action list and that no shipped recipe declares a write step.

## The rule that shapes the design

The page sends a **recipe ID and parameters only** — never selectors, steps, URLs or
code. Recipes ship inside this extension. If a page could supply steps, any origin
allowed to message the extension would gain arbitrary DOM execution on whatever the
user is logged into.

Permissions are added step by step, not up front. Right now the manifest requests
**none** — `tabs`, `scripting` and the Roblox host permission arrive at Step 2, when
something actually needs them.

## Requirements

The extension itself needs nothing installed. The local server that hosts the test page
needs Python plus PyYAML:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

If PyYAML is missing, `build.py --serve` still serves — it just warns that the dashboard
was not rebuilt. The ping test works either way, because it parses no policy.

## Load it

1. `chrome://extensions` → turn on **Developer mode**
2. **Load unpacked** → select this `extension/` folder
3. Confirm the ID reads `jkbakiglogodnlakhcadollfnekeogpd`

The ID is pinned by the `key` field in `manifest.json`, so it survives reloads. If it
differs, the manifest was edited.

## Test the round trip

From the repo root:

```bash
.venv/bin/python build.py --serve
```

Open <http://localhost:8787/extension/test/ping.html> and press **Send PING**.

Then <http://localhost:8787/extension/test/runner.html> to run recipes by hand, or the
dashboard at <http://localhost:8787/docs/> for the Verify buttons.

Expected:

```json
{ "ok": true, "pong": true, "code": "OK", "version": "0.0.1", "recipes": [] }
```

The origin must be exactly `http://localhost:8787`. Opening the file directly with
`file://` will fail with "chrome.runtime is not available" — that is correct behaviour,
not a bug.
