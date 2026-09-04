"""Render the plan to one static HTML page. No framework, no server, no JavaScript.

The page is where a wrong claim would actually reach you, so the mapping from state to
what you see is deliberately mechanical: one dict, no branching. `data-state` on every
cell carries the plan's verdict verbatim so a test can check the page against the plan.
"""
import html
import json

GLYPH = {"verified": "✓", "stale": "!", "applied": "~", "todo": "·",
         "unexpressible": "✗", None: ""}
LABEL = {"verified": "verified", "stale": "needs re-checking", "applied": "not confirmed",
         "todo": "not set up", "unexpressible": "this app can't express it",
         None: "can't do this one"}
EXTENSION_ID = "jkbakiglogodnlakhcadollfnekeogpd"


def _manifest_version():
    """-> the version in extension/manifest.json, or "" if it cannot be read.

    Baked into the page so the page can compare it with the version the LOADED extension
    reports. background.js is a service worker: Chrome keeps running the old one until
    the extension is reloaded, so editing it and not reloading leaves you testing the
    previous build while every file on disk says otherwise. That has cost a debugging
    round already, and it looks exactly like a bug in the new code.
    """
    import json as _json
    import pathlib as _pathlib
    try:
        here = _pathlib.Path(__file__).resolve().parent.parent
        blob = (here / "extension" / "manifest.json").read_text(encoding="utf-8")
        return str(_json.loads(blob).get("version") or "")
    except Exception:                                     # noqa: BLE001
        return ""
# The safety property, as data: exactly one state reads as covered.
COVERED_LOOK = {"verified"}

CSS = """
:root{--bg:#fbfbfa;--fg:#1c1c1a;--dim:#6b6b66;--line:#e2e2dd;--card:#fff;
--ok:#1a7f4b;--okbg:#e6f4ec;--warn:#b4610a;--warnbg:#fdf0e2;--soft:#8a8a84;--softbg:#f2f2ef;
--bad:#b3261e;--badbg:#fceceb;--real:#3b4cca;--realbg:#eef0ff}
@media(prefers-color-scheme:dark){:root{--bg:#161614;--fg:#eceae4;--dim:#9a978e;
--line:#2f2d29;--card:#1e1d1a;--ok:#5fd394;--okbg:#173026;--warn:#f0a259;--warnbg:#33240f;
--soft:#7d7a72;--softbg:#232220;
--bad:#f2867c;--badbg:#331715;--real:#8f9bff;--realbg:#20223f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,
-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:40px 24px 80px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
margin:44px 0 14px;font-weight:600}
.sub{color:var(--dim);margin:0 0 28px;font-size:14px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:8px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 16px;min-width:112px}
.stat b{display:block;font-size:24px;font-weight:600;letter-spacing:-.02em}
.stat span{font-size:12px;color:var(--dim)}
.stat.good b{color:var(--ok)} .stat.warn b{color:var(--warn)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
thead th{font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
color:var(--dim);white-space:nowrap}
tbody th{font-weight:500;min-width:250px}
tbody th small{display:block;color:var(--dim);font-weight:400;font-size:12px}
.kidrow td{background:var(--softbg);font-weight:600;font-size:12px;
text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
.cell{text-align:center;font-size:15px;width:96px}
.cell i{font-style:normal;display:inline-flex;width:24px;height:24px;border-radius:6px;
align-items:center;justify-content:center;font-size:13px}
.s-verified i{background:var(--okbg);color:var(--ok)}
.s-stale i,.s-applied i{background:var(--warnbg);color:var(--warn)}
.s-todo i{background:var(--softbg);color:var(--soft)}
.na{color:var(--line)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin-bottom:10px}
.card h3{margin:0 0 2px;font-size:15px;font-weight:600}
.card p{margin:4px 0;font-size:13px;color:var(--dim)}
.pill{display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;
background:var(--softbg);color:var(--dim);margin-right:5px}
.pill.ok{background:var(--okbg);color:var(--ok)}
.pill.warn{background:var(--warnbg);color:var(--warn)}
ol{margin:8px 0 0;padding-left:20px;font-size:13px} li{margin:3px 0}
a{color:inherit} code{font-size:12px;background:var(--softbg);padding:1px 5px;border-radius:4px}
.check{border-left:2px solid var(--line);padding-left:10px;margin-top:10px;font-size:13px}
.task{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}
.tasktitle{margin:0 0 2px!important;color:var(--fg)!important;font-weight:500;font-size:14px}
.tasktitle .pill{margin-left:6px}
.opt{font-size:12px;color:var(--dim);margin:6px 0 0}
.s-unexpressible i{background:var(--warnbg);color:var(--warn)}
.vrow{display:flex;gap:12px;align-items:flex-start;padding:12px 0;
border-top:1px solid var(--line)}
.vrow:first-of-type{border-top:0}
.vrow .grow{flex:1;min-width:0}
.vbtn{font:inherit;font-size:13px;padding:6px 14px;border-radius:7px;cursor:pointer;
border:1px solid var(--ok);background:transparent;color:var(--ok);white-space:nowrap}
.vbtn[disabled]{opacity:.5;cursor:default}
.vout{font-size:12.5px;color:var(--dim);margin-top:5px;white-space:pre-wrap}
.vout.bad{color:var(--warn)}
.banner{background:var(--warnbg);color:var(--warn);padding:10px 14px;border-radius:8px;
font-size:13px;margin-bottom:14px}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);
color:var(--dim);font-size:12px}
.tag{color:var(--dim);font-size:14px;margin:0 0 3px}
.meta{color:var(--soft);font-size:12.5px;margin:0 0 24px}
.rule{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:0;margin-bottom:14px;overflow:hidden}
.rulehead{padding:15px 18px 13px;border-bottom:1px solid var(--line)}
.rulesay{font-size:17px;font-weight:600;letter-spacing:-.01em;margin:0 0 5px}
.rulemeta{font-size:12.5px;color:var(--dim);margin:0}
.vr{display:flex;align-items:flex-start;gap:14px;padding:14px 18px;
border-bottom:1px solid var(--line)}
.vr:last-child{border-bottom:0}
.vr .grow{flex:1;min-width:0}
.vname{font-size:14px;font-weight:600;margin:0 0 2px}
.vsub{font-size:12.5px;color:var(--dim);margin:0}
.chip{display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;
background:var(--softbg);color:var(--dim);margin-right:5px;vertical-align:1px}
.chip.ok{background:var(--okbg);color:var(--ok)}
.chip.warn{background:var(--warnbg);color:var(--warn)}
.chip.bad{background:var(--badbg);color:var(--bad)}
.chip.real{background:var(--realbg);color:var(--real)}
.reveal{display:grid;grid-template-columns:1fr 1fr 1.1fr;gap:1px;background:var(--line);
border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-top:12px}
.rcell{background:var(--card);padding:11px 13px;min-width:0}
.rlab{font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--soft);
margin:0 0 4px;font-weight:700}
.rval{font-size:15px;font-weight:600;margin:0;word-break:break-word}
.rval small{display:block;font-size:12px;font-weight:400;color:var(--dim);margin-top:2px}
.rcell.v-ok{background:var(--okbg)} .rcell.v-ok .rval{color:var(--ok)}
.rcell.v-bad{background:var(--badbg)} .rcell.v-bad .rval{color:var(--bad)}
.rcell.v-warn{background:var(--warnbg)} .rcell.v-warn .rval{color:var(--warn)}
.stamp{font-size:12px;color:var(--soft);margin:8px 2px 0}
.running{display:flex;align-items:center;gap:9px;margin-top:12px;font-size:13px;
color:var(--dim);background:var(--softbg);border-radius:8px;padding:10px 13px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--real);flex:none}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 16px;margin-bottom:8px}
details[open]{padding-bottom:18px}
summary{cursor:pointer;font-size:14px;font-weight:600;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"\25b8  ";color:var(--dim)}
details[open] summary::before{content:"\25be  "}
summary span{float:right;color:var(--dim);font-weight:400;font-size:13px}
@media(max-width:640px){.reveal{grid-template-columns:1fr}}
"""


def _e(text):
    return html.escape(str(text or ""))


def render(plan):
    s, out = plan["summary"], []
    # First line, before any text. Without it a browser guesses the encoding and every
    # em-dash in this page renders as "â€"".
    out.append('<meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    out.append(f"<title>{_e(plan['family'])} — policy plane</title>")
    out.append(f"<style>{CSS}</style>")
    out.append('<div class="wrap">')
    out.append("<h1>Policy Plane</h1>")
    out.append('<p class="tag">Define once. Verified everywhere.</p>')
    out.append(f'<p class="meta">{_e(plan["family"])} · built {_e(plan["generated"])} · '
               'only a reading you have actually taken counts as in force</p>')

    out.append('<div class="stats">')
    for tile in stat_tiles(s):
        out.append(_stat(tile))
    out.append("</div>")

    # The verification panel leads. It is the only part of this page that establishes
    # anything by itself -- everything below it is a checklist a human still has to work
    # through, and burying the one automated thing under six tables made the product look
    # like a spreadsheet.
    if plan.get("verifiable"):
        out.append(_hero(plan))

    out.append("<h2>The rest of the plane</h2>")

    legend = ('<p class="sub" style="margin:10px 0 0">'
              + LEGEND + "</p>")
    out.append(_fold("Where each rule stands", f"{len(plan['surfaces'])} surfaces",
                     _matrix(plan) + legend))

    devices = plan.get("by_device") or []
    if devices:
        gaps = sum(d["unreachable"] for d in devices)
        out.append(_fold(
            "Every device, one by one",
            f"{len(devices)} pairings · {gaps} rules with nowhere to land",
            _device_section(devices)))

    out.append(_fold("Rules", f"{len(plan['rules'])} written",
                     "".join(_rule_card(r, plan) for r in plan["rules"])))

    if plan["checklist"]:
        cards = []
        for surface_id in dict.fromkeys(c["surface"] for c in plan["checklist"]):
            items = [c for c in plan["checklist"] if c["surface"] == surface_id]
            cards.append(_checklist_card(surface_id, items, plan))
        out.append(_fold("What to do next",
                         f"{len(plan['checklist'])} items a human must still do",
                         "".join(cards)))

    out.append(_fold("What your apps can actually control", "catalog",
                     '<p class="sub">The catalog you would otherwise have to open each '
                     'app to discover. A tick means some rule of yours uses it.</p>'
                     + _catalog(plan)))

    unused = _unused(plan)
    if unused:
        cards = "".join(f'<div class="card"><h3>{_e(name)} · '
                        f'<span class="pill">{_e(kind)}</span></h3>'
                        f'<p class="opt">{_e(options)}</p></div>'
                        for name, kind, options in unused)
        out.append(_fold("You could also ask for", f"{len(unused)} unused controls",
                         '<p class="sub">Your apps can do these and no rule of yours '
                         'mentions them. Not a problem — just things you may not have '
                         'known were there.</p>' + cards))

    reach = "".join(
        f'<div class="card"><h3>{_e(surf["name"])}</h3>'
        f'<p><strong>Reaches:</strong> {_e(surf["reach"])}</p>'
        + (f'<p><strong>Blind to:</strong> {_e(surf["blind"])}</p>'
           if surf["blind"] else "")
        + f'<p>Handles {", ".join(_e(c) for c in surf["can"])} · '
          f're-check every {surf["recheck_days"]} days</p></div>'
        for surf in plan["surfaces"])
    out.append(_fold("What each app reaches, and can\'t", "blind spots", reach))


    out.append('<footer>Generated by policy-plane from <code>policy.yaml</code> and '
               '<code>status.yaml</code>. This page tracks your settings, not your kids '
               '— it records no activity, no usage and no messages.</footer>')
    out.append("</div>")
    return "\n".join(out)


LEGEND = ("\u2713 confirmed · ~ changed but not confirmed · ! needs re-checking · "
          "· not set up · blank means this app can't do that kind of rule.")

# How each verdict reads on the page. The judge's vocabulary is deliberately small and
# this is the ONLY place it becomes English, so a new verdict cannot quietly render as
# blank -- _verdict_words raises on one it does not know.
VERDICT_WORDS = {
    "satisfied":      ("v-ok",   "In force",           "exactly as you asked"),
    "stricter":       ("v-ok",   "In force",           "stricter than you asked"),
    "not_satisfied":  ("v-bad",  "Not in force",       "the app allows more than your rule"),
    "unexpressible":  ("v-warn", "Can't be expressed", "this app has no such setting"),
    "unknown":        ("v-warn", "Couldn't read",      "nothing was established"),
}


def _verdict_words(verdict):
    try:
        return VERDICT_WORDS[verdict]
    except KeyError:                                  # pragma: no cover - guard
        raise AssertionError(
            f"no wording for verdict {verdict!r}; add it to VERDICT_WORDS rather than "
            "letting the page render an empty cell") from None


def _fold(title, note, inner):
    """A collapsed section. Everything below the hero is depth, not the headline."""
    return (f"<details><summary>{_e(title)}<span>{_e(note)}</span></summary>"
            f"{inner}</details>")


def _declared(rule):
    """-> the rule's ask, short enough for a table cell."""
    params = rule["params"]
    if rule["kind"] == "time":
        return f"\u2264 {params['minutes_per_day']} min/day"
    if rule["kind"] == "content":
        return f"\u2264 {params['max_maturity']}"
    return ", ".join(f"{k}: {v}" for k, v in params.items())


def _reveal(rule, cell, surface_name):
    """The three-column result: what you asked, what the vendor said, the verdict.

    Rendered server-side when a reading already exists, and rebuilt by the same shape in
    JS after a fresh run. The vendor's words are shown verbatim beside the verdict --
    the product's whole claim is that it reports what the vendor said, so it has to show
    it rather than ask to be believed.
    """
    css, head, sub = _verdict_words(cell["verdict"])
    said = cell.get("said")
    return (
        '<div class="reveal">'
        f'<div class="rcell"><p class="rlab">You declared</p>'
        f'<p class="rval">{_e(_declared(rule))}</p></div>'
        f'<div class="rcell"><p class="rlab">{_e(surface_name.split(" \u2014 ")[0])} says</p>'
        f'<p class="rval">{("\u201c" + _e(said) + "\u201d") if said else "\u2014"}'
        f'<small>{_e(cell.get("why") or "")}</small></p></div>'
        f'<div class="rcell {css}"><p class="rlab">Verdict</p>'
        f'<p class="rval">{_e(head)}<small>{_e(sub)}</small></p></div>'
        "</div>"
        f'<p class="stamp">read {_e(cell.get("date") or "")}'
        f' · recipe {_e(cell.get("recipe") or "")}</p>')


def _hero(plan):
    """One rule, every surface that can be checked automatically."""
    rules = {r["id"]: r for r in plan["rules"]}
    by_rule = {}
    for v in plan["verifiable"]:
        by_rule.setdefault(v["rule"], []).append(v)

    bits = ['<h2>Verify against the vendors</h2>',
            '<p class="sub">Each check opens the app in a new tab and reads the setting '
            'back. Read-only \u2014 this build has no way to change anything. If a login '
            'is needed, sign in and it keeps waiting.</p>',
            '<div id="ext-missing" class="banner" hidden></div>',
            '<div id="ext-stale" class="banner" hidden></div>']

    for rule_id, pairs in by_rule.items():
        rule = rules[rule_id]
        bits.append('<div class="rule">')
        bits.append(f'<div class="rulehead"><p class="rulesay">{_e(rule["say"])}</p>'
                    f'<p class="rulemeta"><span class="chip">{_e(rule["kind"])}</span>'
                    f'<span class="chip">{_e(_declared(rule))}</span>'
                    f'written once \u00b7 routed to {len(pairs)} '
                    f'{"vendor" if len(pairs) == 1 else "vendors"} that can be read '
                    f'automatically</p></div>')
        for v in pairs:
            cell = plan["cells"][(v["rule"], v["surface"])]
            sim = v["surface"].startswith("sim-")
            chip = ('<span class="chip">simulated</span>' if sim
                    else '<span class="chip real">real vendor</span>')
            body = (_reveal(rule, cell, v["surface_name"]) if cell.get("verdict")
                    else '<p class="vsub">Never checked.</p>')
            bits.append(
                f'<div class="vr" data-pair="{_e(v["rule"])}|{_e(v["surface"])}">'
                f'<div class="grow"><p class="vname">{_e(v["surface_name"])} {chip}</p>'
                f'<div class="vout" id="out-{_e(v["rule"])}-{_e(v["surface"])}">'
                f'{body}</div></div>'
                + (f'<button class="vbtn" data-recipe="{_e(v["recipe"])}" '
                   f'data-rule="{_e(v["rule"])}" data-surface="{_e(v["surface"])}" '
                   f'data-declared="{_e(_declared(rule))}" '
                   f'data-vendor="{_e(v["surface_name"].split(" \u2014 ")[0])}" '
                   f"data-params='{json.dumps(v['params'])}'>Verify</button></div>"
                   if not v["blocked"] else
                   f'<span class="chip warn">{_e(v["why_blocked"])}</span></div>'))
        bits.append("</div>")

    bits.append(_verify_script())
    return "".join(bits)


def _verify_script():
    # RAW string. Without the r-prefix Python turns every \n in this template into a
    # real newline, which lands inside a JS string literal and breaks the whole script --
    # silently, because a syntax error stops the page's JS without any visible sign.
    return r"""
<script>
(function () {
  var EXT_ID = "%s";
  // The SAME wording table the server uses. Duplicated deliberately and asserted equal
  // by a test: the alternative is the page inventing English for a verdict, which is one
  // short step from the page deciding the verdict.
  var WORDS = %s;

  function esc(t) {
    var d = document.createElement("div"); d.textContent = t == null ? "" : String(t);
    return d.innerHTML;
  }
  function reveal(declared, vendor, said, judged, stamp) {
    var w = WORDS[judged.verdict];
    if (!w) {
      return problemHtml("read, but the page has no wording for verdict "
                         + esc(judged.verdict) + ", and will not guess one");
    }
    return '<div class="reveal">'
      + '<div class="rcell"><p class="rlab">You declared</p><p class="rval">'
      + esc(declared) + '</p></div>'
      + '<div class="rcell"><p class="rlab">' + esc(vendor) + ' says</p><p class="rval">'
      + (said ? '“' + esc(said) + '”' : '—')
      + '<small>' + esc(judged.why || "") + '</small></p></div>'
      + '<div class="rcell ' + w[0] + '"><p class="rlab">Verdict</p><p class="rval">'
      + esc(w[1]) + '<small>' + esc(w[2]) + '</small></p></div>'
      + '</div><p class="stamp">' + esc(stamp) + '</p>';
  }
  function paintStats(stats) {
    if (!Array.isArray(stats)) return;          // no stats: leave what is on screen
    stats.forEach(function (t) {
      var el = document.querySelector('.stat[data-stat="' + t.key + '"]');
      if (!el) return;
      el.className = "stat " + (t.cls || "");
      el.querySelector("b").textContent = t.value;
    });
  }

  function problemHtml(text) {
    return '<p class="vsub"><span class="chip warn">Not checked</span> '
           + esc(text) + '</p>';
  }
  function problem(out, text) { out.innerHTML = problemHtml(text); }

  function have() {
    return typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage;
  }
  if (!have()) {
    var b = document.getElementById("ext-missing");
    b.hidden = false;
    b.textContent = "The extension is not reachable from this page. Load it at "
      + "chrome://extensions, and open this dashboard from http://localhost:8787/docs/ "
      + "— a file:// page can never message an extension.";
    document.querySelectorAll(".vbtn").forEach(function (x) { x.disabled = true; });
    return;
  }

  // Is the RUNNING extension the one on disk? Chrome keeps the old service worker until
  // the extension is reloaded, so an edit you did not reload leaves you testing the
  // previous build while every file says otherwise -- and it presents as the new code
  // not working.
  var ON_DISK = "%s";
  chrome.runtime.sendMessage(EXT_ID, { type: "PING" }, function (res) {
    if (chrome.runtime.lastError || !res || !res.version || !ON_DISK) return;
    if (res.version === ON_DISK) return;
    var b = document.getElementById("ext-stale");
    b.hidden = false;
    b.textContent = "The loaded extension is v" + res.version + " but extension/ on disk "
      + "is v" + ON_DISK + ". Chrome is still running the old service worker — reload the "
      + "extension at chrome://extensions, then reload this page. Until you do, you are "
      + "testing the previous build.";
  });
  // A fixture can tell us a human changed something on it. We respond by RE-READING --
  // never by believing the message. It carries no value, only the fact that a vendor
  // moved, so nothing outside this page can put a number on it. A real vendor's page
  // cannot send this at all, which is correct: the only way to learn what a real vendor
  // says is to go and read it.
  try {
    new BroadcastChannel("policy-plane").addEventListener("message", function (ev) {
      var d = ev.data || {};
      if (d.type !== "VENDOR_CHANGED" || !d.surface) return;
      document.querySelectorAll(".vbtn").forEach(function (b) {
        if (b.dataset.surface === d.surface && !b.disabled) b.click();
      });
    });
  } catch (err) { /* no BroadcastChannel: verification stays manual, which is fine */ }

  document.querySelectorAll(".vbtn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var rule = btn.dataset.rule, surface = btn.dataset.surface;
      var out = document.getElementById("out-" + rule + "-" + surface);
      var declared = btn.dataset.declared, vendor = btn.dataset.vendor;
      btn.disabled = true;
      btn.textContent = "Checking…";
      out.innerHTML = '<div class="running"><span class="dot"></span>'
        + 'A tab is open. If it asks you to sign in, do — this keeps waiting.</div>';

      function done() { btn.disabled = false; btn.textContent = "Verify"; }

      chrome.runtime.sendMessage(EXT_ID, {
        type: "RUN_RECIPE", recipeId: btn.dataset.recipe,
        params: JSON.parse(btn.dataset.params)
      }, function (res) {
        done();
        if (chrome.runtime.lastError || !res) {
          problem(out, "no response from the extension: "
            + (chrome.runtime.lastError && chrome.runtime.lastError.message));
          return;
        }
        if (!res.ok) {
          // A failed read is NOT a verdict. It never degrades into "not in force" --
          // "we could not look" and "it is not set" are different facts.
          problem(out, res.code + (res.failingStep ? " at: " + res.failingStep : "")
                       + (res.error ? " — " + res.error : ""));
          return;
        }
        fetch("/observations", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            rule: rule, surface: surface, recipe: btn.dataset.recipe,
            at: new Date().toISOString(), code: res.code, url: res.url || null,
            params: JSON.parse(btn.dataset.params), readings: res.readings || {}
          })
        }).then(function (r) { return r.json(); }).then(function (saved) {
          if (!saved || !saved.judged) {
            problem(out, "read fine, but the plane could not judge it"
                         + (saved && saved.judge_error ? ": " + saved.judge_error : ""));
            return;
          }
          var r = res.readings || {};
          var offered = Array.isArray(r.offeredText) ? r.offeredText.length : 0;
          var stamp = "read just now · recipe " + btn.dataset.recipe
                    + (offered ? " · " + offered + " values on offer" : "");
          out.innerHTML = reveal(declared, vendor, saved.judged.said, saved.judged, stamp);
          // The hero tiles, recomputed by the server from the same plan this row came
          // from. The page writes the strings in and counts nothing itself -- a second
          // counting path here is exactly how the tiles and the checklist became two
          // implementations of one number.
          paintStats(saved.stats);
        }).catch(function (e) {
          problem(out, "read fine, but could not record it: " + e
                       + ". Is build.py --serve running?");
        });
      });
    });
  });
})();
</script>
""" % (EXTENSION_ID, json.dumps(VERDICT_WORDS), _manifest_version())


def stat_tiles(summary):
    """-> [{key, value, label, cls}] for the hero tiles.

    THE one place a tile number is decided. The server-rendered page and the live update
    after a reading both come through here, so they cannot disagree -- and there is no
    counting logic in JavaScript to drift away from the counting logic in Python. That
    drift is exactly what let `todo_count` and `len(checklist)` become two independent
    implementations of the same number.
    """
    s = summary
    read = s["pairs_covered_read"]
    return [
        # Nothing read yet is not the same claim as "zero of what we read is in force".
        # A dash says we have not looked; a 0 says we looked and found none.
        {"key": "read", "label": "in force, read",
         "value": "—" if not s["pairs_observed"] else str(read),
         "cls": "good" if read else ""},
        {"key": "attested", "label": "in force, attested by you",
         "value": str(s["pairs_covered_attested"]), "cls": ""},
        {"key": "todo", "label": "need attention",
         "value": str(s["todo_count"]), "cls": "warn" if s["todo_count"] else ""},
        {"key": "uncovered", "label": "rules with nothing in force",
         "value": str(s["rules_fully_uncovered"]),
         "cls": "warn" if s["rules_fully_uncovered"] else ""},
        {"key": "stale", "label": "gone stale",
         "value": str(s["pairs_stale"]), "cls": "warn" if s["pairs_stale"] else ""},
    ]


def _stat(tile):
    return (f'<div class="stat {tile["cls"]}" data-stat="{_e(tile["key"])}">'
            f'<b>{_e(tile["value"])}</b><span>{_e(tile["label"])}</span></div>')


def _device_section(devices):
    """One block per child-and-device: what holds there, and what cannot reach it.

    Account surfaces are absent on purpose. Roblox follows Alex rather than the iPad, so
    listing it under four devices would show one reading four times and read as four
    checks. It is answered above, once.
    """
    bits = ['<p class="sub">A rule reaches a device only through a surface that both '
            'carries the rule and reaches that device. A rule with nowhere to land here '
            'is a real gap, not a missing tick.</p>']
    for d in devices:
        off = ("" if d["on_home_network"] else
               '<span class="chip warn">not on the home wifi</span>')
        bits.append(
            f'<div class="card"><h3>{_e(d["device_name"])} '
            f'<span class="chip">{_e(d["kind"])}</span>'
            f'<span class="chip">{_e(d["kid_name"])}</span>{off}</h3>')
        stuck = [r for r in d["rules"] if not r["reachable"]]
        bits.append(f'<p class="opt">{d["held"]} of {len(d["rules"])} rules in force here'
                    + (f' · {len(stuck)} cannot reach it at all' if stuck else '') + '</p>')
        for r in d["rules"]:
            if r["reachable"]:
                mark = "ok" if r["state"] in COVERED_LOOK else "warn"
                where = ", ".join(r["via"])
                bits.append(f'<p class="opt"><span class="pill {mark}">{_e(r["kind"])}'
                            f'</span> {_e(r["say"])} <em>via {_e(where)}</em></p>')
            else:
                bits.append(f'<p class="opt"><span class="pill warn">nowhere</span> '
                            f'{_e(r["say"])}</p>')
        bits.append("</div>")
    return "".join(bits)


def _matrix(plan):
    rows = ['<div class="scroll"><table><thead><tr><th>Rule</th>']
    for surf in plan["surfaces"]:
        rows.append(f'<th class="cell">{_e(surf["name"].split(" — ")[0])}</th>')
    rows.append("</tr></thead><tbody>")
    for kid in plan["kids"]:
        rows.append(f'<tr class="kidrow"><td colspan="{len(plan["surfaces"]) + 1}">'
                    f'{_e(kid["name"])}</td></tr>')
        for rule in [r for r in plan["rules"] if r["kid"] == kid["id"]]:
            rows.append(f'<tr><th>{_e(rule["say"])}<small>{_e(rule["kind"])}</small></th>')
            for surf in plan["surfaces"]:
                cell = plan["cells"][(rule["id"], surf["id"])]
                state = cell["state"] if cell["applicable"] else None
                cls = f"s-{state}" if state else "na"
                rows.append(
                    f'<td class="cell {cls}" data-state="{state or "na"}" '
                    f'data-pair="{_e(rule["id"])}|{_e(surf["id"])}" '
                    f'title="{_e(LABEL[state])}"><i>{GLYPH[state]}</i></td>')
            rows.append("</tr>")
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _rule_card(rule, plan):
    names = {s["id"]: s["name"] for s in plan["surfaces"]}
    bits = [f'<div class="card"><h3>{_e(rule["say"])}</h3>']
    if rule["covered_by"]:
        pills = "".join(f'<span class="pill ok">✓ {_e(names[s])}</span>'
                        for s in rule["covered_by"])
        bits.append(f"<p>In force via {pills}</p>")
    elif not rule["reachable"]:
        bits.append('<p><span class="pill warn">nothing here can enforce this</span> '
                    'No app in your list handles this kind of rule.</p>')
    else:
        bits.append('<p><span class="pill warn">not in force anywhere</span> '
                    'Every app that could do this is unconfirmed or overdue.</p>')
    if rule["gaps"]:
        pills = "".join(f'<span class="pill">{_e(names[g["surface"]])}: '
                        f'{_e(LABEL[g["state"]])}</span>' for g in rule["gaps"])
        bits.append(f"<p>{pills}</p>")
    bits.append("</div>")
    return "".join(bits)


def _checklist_card(surface_id, items, plan):
    """One card per app, then ONE BLOCK PER RULE inside it.

    The steps come from how[rule.kind], so a content rule gets the content click-path and
    a bedtime rule gets the bedtime one. Sharing a single set of steps across every rule
    on an app is how you end up confirming Downtime and calling a content rule done.
    """
    surf = next(s for s in plan["surfaces"] if s["id"] == surface_id)
    bits = [f'<div class="card"><h3>{_e(surf["name"])}</h3>']
    if surf["link"]:
        note = (" — unofficial shortcut; if it doesn't open, the steps stand alone"
                if surf["link_kind"] == "unofficial" else "")
        bits.append(f'<p><a href="{_e(surf["link"])}">{_e(surf["link"])}</a>{_e(note)}</p>')
    for item in items:
        bits.append(f'<div class="task"><p class="tasktitle">{_e(item["say"])}'
                    f'<span class="pill">{_e(item["kind"])}</span>'
                    f'<span class="pill warn">{_e(item["why"])}</span></p>')
        bits.append("<ol>" + "".join(f"<li>{_e(x)}</li>" for x in item["steps"]) + "</ol>")
        bits.append(f'<div class="check"><strong>Confirm you can see:</strong> '
                    f'{_e(item["check"])}</div>')
        if item["options"]:
            bits.append(f'<p class="opt">This app offers: {_e(item["options"])}</p>')
        bits.append("</div>")
    if surf.get("redact") or any(i["redact"] for i in items):
        bits.append(f'<div class="check">📎 {_e(items[0]["redact"])}</div>')
    bits.append("</div>")
    return "".join(bits)


def _catalog(plan):
    """What every app can actually control -- and whether any rule uses it.

    This is the half you normally cannot see: to find out what Xbox can do you have to be
    inside Xbox. Written down once, it also answers the reverse question -- what could you
    be asking for that you never thought to?
    """
    rows = ['<div class="scroll"><table><thead><tr><th>App</th><th>Control</th>'
            '<th>What it actually offers</th><th class="cell">In use</th>'
            '</tr></thead><tbody>']
    for surf in plan["surfaces"]:
        for i, entry in enumerate(surf["catalog"]):
            used = bool(entry["used_by"])
            rows.append("<tr>")
            rows.append(f'<th>{_e(surf["name"]) if i == 0 else ""}</th>')
            rows.append(f'<td><span class="pill">{_e(entry["kind"])}</span></td>')
            rows.append(f'<td class="opt">{_e(entry["options"])}</td>')
            rows.append(f'<td class="cell {"s-verified" if used else "s-todo"}">'
                        f'<i>{"✓" if used else "—"}</i></td>')
            rows.append("</tr>")
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _unused(plan):
    out = []
    for surf in plan["surfaces"]:
        for entry in surf["catalog"]:
            if not entry["used_by"]:
                out.append((surf["name"], entry["kind"], entry["options"]))
    return out
