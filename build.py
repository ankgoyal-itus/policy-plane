#!/usr/bin/env python3
"""Validate the policy, build the plan, write the page. One command."""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


MISSING_YAML = """
PyYAML is not installed for this Python.

  this python : {exe}

Fix it with a virtualenv, which keeps it off your system Python:

  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python build.py --serve

Nothing else in policy-plane needs installing.
"""


def _imports():
    """Imported lazily so `--serve` still works when PyYAML is missing.

    The ping test does not parse any policy, and coupling it to a YAML dependency meant
    an unrelated missing package took down an unrelated test.
    """
    try:
        from plane import observe
        from plane.model import PolicyError, load
        from plane.plan import build
        from plane.render import render
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        print(MISSING_YAML.format(exe=sys.executable), file=sys.stderr)
        raise SystemExit(2)
    return PolicyError, load, build, render, observe


PORT = 8787   # baked into the extension manifest's externally_connectable allowlist

# The demo control panel, served at /demo_dashboard. Deliberately a plain string rather
# than a file: it exists to run takes, it is not part of the product, and it must never
# be mistaken for the dashboard the product actually renders.
DEMO_DASHBOARD = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Policy Plane — demo control</title>
<style>
 :root{--ink:#1c1c1a;--dim:#6b6b66;--line:#dcdcd6;--card:#fff;--bg:#fbfbfa;
       --ok:#1a7f4b;--okbg:#e6f4ec;--bad:#b3261e;--badbg:#fceceb}
 *{box-sizing:border-box}
 body{font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;
      margin:0;padding:44px 24px;background:var(--bg);color:var(--ink)}
 .wrap{max-width:620px;margin:0 auto}
 h1{font-size:23px;margin:0 0 2px}
 .sub{color:var(--dim);font-size:13.5px;margin:0 0 8px}
 .mode{font-size:13px;margin:0 0 26px}
 .ok{color:var(--ok)} .bad{color:var(--bad)}
 h2{font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
    margin:28px 0 10px;font-weight:700}
 .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:16px 18px;margin-bottom:10px}
 .card a{color:inherit;font-weight:600}
 .card p{margin:3px 0 0;font-size:13px;color:var(--dim)}
 button{font:inherit;padding:11px 20px;border-radius:9px;border:1px solid var(--ink);
        background:var(--ink);color:#fff;font-weight:600;cursor:pointer}
 button[disabled]{opacity:.35;cursor:default}
 #out{margin-top:14px;font-size:13.5px;border-radius:9px;padding:11px 13px}
 #out.good{background:var(--okbg);color:var(--ok)}
 #out.err{background:var(--badbg);color:var(--bad)}
 code{font-size:12.5px;background:rgba(128,128,128,.14);padding:1px 5px;border-radius:4px}
 ol{padding-left:20px;font-size:13.5px;color:var(--dim)} li{margin:5px 0}
</style>
<div class="wrap">
  <h1>Demo control</h1>
  <p class="sub">Everything you need for a take, without a terminal.</p>
  <p class="mode">{{MODE}}</p>

  <h2>Reset</h2>
  <div class="card">
    <button id="reset"{{DISABLED}}>Reset demo</button>
    <div id="out" hidden></div>
    <p>Clears the demo readings so all three rows read <b>Never checked</b> again, and
      puts the fixtures back to their default settings. Your real
      <code>observations.json</code> is never opened — the previous take's readings are
      rotated to <code>observations.demo.prev.json</code>, not deleted.</p>
  </div>

  <h2>Open</h2>
  <div class="card"><a href="/docs/" target="_blank">Dashboard</a>
    <p>The page you record. Hard-reload it after a reset.</p></div>
  <div class="card"><a href="/extension/test/fixtures/vendor-a.html" target="_blank">Vendor A fixture</a>
    <p>Change the daily limit and save. The dashboard re-reads it automatically.</p></div>
  <div class="card"><a href="/extension/test/fixtures/vendor-b.html" target="_blank">Vendor B fixture</a>
    <p>Offers 0/30/60/120 — no 90, which is where <i>can't be expressed</i> comes from.</p></div>

  <h2>Running order</h2>
  <ol>
    <li>Reset, then hard-reload the dashboard</li>
    <li>Check all three rows read <b>Never checked</b> and there is no orange banner</li>
    <li>Close devtools — the page carries an account id in an attribute</li>
    <li>Record</li>
  </ol>
</div>
<script>
(function () {
  var btn = document.getElementById("reset"), out = document.getElementById("out");
  if (!btn) return;
  btn.addEventListener("click", function () {
    btn.disabled = true; out.hidden = false; out.className = ""; out.textContent = "Resetting…";
    // The fixtures remember their saved setting in localStorage, same origin as this
    // page. Clearing observations alone would leave Vendor A showing whatever the last
    // take set it to, and the recording script asserts on its default.
    var wiped = 0;
    try {
      Object.keys(localStorage).forEach(function (k) {
        if (k.indexOf("pp-fixture-") === 0) { localStorage.removeItem(k); wiped++; }
      });
    } catch (err) { /* storage blocked: fixtures keep their value */ }
    fetch("/demo/reset", { method: "POST" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (!res.ok || !res.j.ok) {
          out.className = "err";
          out.textContent = res.j.error || "reset failed";
          return;
        }
        out.className = "good";
        out.textContent = "Reset. "
          + (res.j.cleared ? res.j.cleared + " reading(s) moved to " + res.j.rotated_to
                           : "no readings to clear")
          + ", " + wiped + " fixture setting(s) back to default. "
          + "Hard-reload the dashboard and any open fixture tabs.";
      })
      .catch(function (e) {
        btn.disabled = false; out.className = "err";
        out.textContent = "could not reach the server: " + e;
      });
  });
})();
</script>
"""



# Every read and write of observations goes through this one name. It used to be spelled
# out at three call sites, which is survivable -- but it also meant the only way to start
# a demo from a clean slate was to move the real file out of the way by hand, and a
# mistyped or wrong-directory `mv` looks exactly like a successful one.
OBSERVATIONS = HERE / "observations.json"


def use_demo_observations():
    """Point observations at a scratch file, so a demo can start empty.

    The real history is never opened -- not for reading, not for writing -- so there is
    no command in the demo path that can damage it. Any previous demo file is rotated
    rather than deleted: it is scratch data, but deleting something without saying so is
    how trust in a tool goes.
    """
    global OBSERVATIONS
    OBSERVATIONS = HERE / "observations.demo.json"
    if OBSERVATIONS.exists() and OBSERVATIONS.read_text(encoding="utf-8").strip() not in ("", "[]"):
        keep = HERE / "observations.demo.prev.json"
        OBSERVATIONS.replace(keep)
        print(f"demo mode: previous demo readings moved to {keep.name}")
    OBSERVATIONS.write_text("[]\n", encoding="utf-8")
    print(f"demo mode: recording to {OBSERVATIONS.name} — "
          f"{(HERE / 'observations.json').name} is untouched")


def serve(stale_reason=""):
    """Serve the repo over http so the page can reach the extension.

    A file:// page can never message an extension: chrome.runtime is only injected on
    origins matching externally_connectable, and that cannot match a file URL. So the
    dashboard has to come off a real origin, and that origin has to be the exact one in
    the manifest -- localhost entries need the port to match too.
    """
    import datetime
    import functools
    import html
    import http.server
    import json

    class Handler(http.server.SimpleHTTPRequestHandler):
        """Static files, plus one POST endpoint that records an observation.

        Bound to 127.0.0.1 only. It appends to observations.json and does nothing else --
        no shell, no eval, no path from the body to the filesystem beyond one known file.
        """

        def _json(self, code, payload):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_POST(self):                      # noqa: N802 (http.server's naming)
            if self.path.rstrip("/") == "/demo/reset":
                # REFUSES outside demo mode. Without this guard the button on a page
                # anyone can open would empty the real reading history, and it would do
                # it silently -- the single most damaging thing in this repo.
                if OBSERVATIONS.name != "observations.demo.json":
                    self._json(409, {
                        "ok": False,
                        "error": "not running in demo mode. Reset would clear "
                                 f"{OBSERVATIONS.name}, which is your real history. "
                                 "Restart with: build.py --serve --demo"})
                    return
                kept = 0
                try:
                    kept = len(json.loads(OBSERVATIONS.read_text(encoding="utf-8")) or [])
                except (OSError, json.JSONDecodeError):
                    kept = 0
                if kept:
                    OBSERVATIONS.replace(HERE / "observations.demo.prev.json")
                OBSERVATIONS.write_text("[]\n", encoding="utf-8")
                self._json(200, {"ok": True, "cleared": kept,
                                 "rotated_to": "observations.demo.prev.json" if kept else None})
                return
            if self.path.rstrip("/") != "/observations":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict) or not body.get("rule"):
                    raise ValueError("expected an object with at least a 'rule'")
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())
                return

            path = OBSERVATIONS
            existing = []
            if path.exists():
                try:
                    existing = json.loads(path.read_text()) or []
                except json.JSONDecodeError:
                    existing = []
            existing.append(body)
            path.write_text(json.dumps(existing, indent=2) + "\n")

            # Judge it here, and hand the verdict back. The page used to say "recorded,
            # reload to judge", which made the one interesting moment of the product
            # require a page refresh. The judging still happens in Python -- the page
            # renders a verdict it is given and never decides one, which is the whole
            # point of the split.
            payload = {"ok": True, "recorded": len(existing)}
            try:
                payload["judged"] = _judge_one(body)
            except Exception as exc:                  # noqa: BLE001
                # A judge that fails must not look like a verdict.
                payload["judged"] = None
                payload["judge_error"] = f"{type(exc).__name__}: {exc}"
            try:
                # The hero tiles, recomputed from the SAME plan the rows come from and
                # rendered by the same function the page used. The page writes these
                # strings in; it does not count anything itself. Before this, the tiles
                # were server-rendered once and never touched again, so a reading you
                # had just taken did not move the largest numbers on the page -- a
                # snapshot presented as if it were live.
                payload["stats"] = _stats_now()
            except Exception as exc:                  # noqa: BLE001
                payload["stats"] = None
                payload["stats_error"] = f"{type(exc).__name__}: {exc}"

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_GET(self):                       # noqa: N802
            """Rebuild the dashboard before serving it.

            The page is a static artifact baked from the policy, so editing
            policy.local.yaml did nothing until the server was restarted -- and the
            symptom was a Verify button quietly carrying the OLD parameters. A page that
            can silently disagree with the policy it claims to render is worse than no
            page. Rebuilding per request costs about 10ms.
            """
            if self.path.rstrip("/") in ("/demo_dashboard", "/demo"):
                self._demo_dashboard()
                return
            wants_dashboard = (self.path.rstrip("/") in ("/docs", "")
                               or self.path.startswith("/docs/index.html"))
            if wants_dashboard:
                try:
                    _build_page(datetime.date.today().isoformat(),
                                raise_on_error=True)
                except SystemExit:
                    pass                       # missing PyYAML: serve what is on disk
                except Exception as exc:       # noqa: BLE001
                    # Serving the last good page here would be the worst outcome: it
                    # looks fine, and quietly describes a policy that is no longer what
                    # the file says. Say so instead.
                    self._policy_broken(exc)
                    return
            super().do_GET()

        def _demo_dashboard(self):
            """A control panel for running the demo without a terminal."""
            demo = OBSERVATIONS.name == "observations.demo.json"
            body = DEMO_DASHBOARD.replace(
                "{{MODE}}",
                '<span class="ok">demo mode — writing to observations.demo.json</span>'
                if demo else
                '<span class="bad">NOT in demo mode — reset is disabled. '
                'Restart with <code>build.py --serve --demo</code></span>')
            body = body.replace("{{DISABLED}}", "" if demo else " disabled")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def _policy_broken(self, exc):
            body = (
                "<!doctype html><meta charset=utf-8>"
                "<title>policy-plane — policy is not valid</title>"
                "<style>:root{color-scheme:light dark}"
                "body{font:15px/1.6 ui-sans-serif,-apple-system,sans-serif;"
                "max-width:760px;margin:60px auto;padding:0 24px}"
                "h1{font-size:20px;color:#b4610a;margin:0 0 6px}"
                "pre{background:rgba(128,128,128,.14);padding:14px;border-radius:8px;"
                "white-space:pre-wrap;font-size:13px}</style>"
                "<h1>Your policy is not valid, so this page was not rebuilt.</h1>"
                "<p>The last good page is still on disk, but showing it would describe a "
                "policy that is no longer what the file says. Fix the error below and "
                "reload &mdash; nothing else needs restarting.</p>"
                f"<pre>{html.escape(str(exc))}</pre>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def guess_type(self, path):
            """Always declare utf-8 for text. SimpleHTTPRequestHandler sends bare
            'text/html', so the browser falls back to a legacy encoding and mangles
            every non-ASCII character."""
            base = super().guess_type(path)
            if base.startswith(("text/", "application/json")) and "charset" not in base:
                return base + "; charset=utf-8"
            return base

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    handler = functools.partial(Handler, directory=str(HERE))
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        if stale_reason:
            # Loud on purpose. Silently serving yesterday's page while the build is
            # broken is the failure that looks exactly like success.
            print("!" * 68)
            print("! DASHBOARD NOT REBUILT — you are looking at the last build on disk")
            print(f"! {stale_reason}")
            print("! The ping test is unaffected; it does not read any policy.")
            print("!" * 68)
        print(f"serving {HERE} on http://localhost:{PORT}")
        print(f"  dashboard   http://localhost:{PORT}/docs/")
        print(f"  ping test   http://localhost:{PORT}/extension/test/ping.html")
        print(f"  runner      http://localhost:{PORT}/extension/test/runner.html")
        print("ctrl-c to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


def explain(rule_id, today):
    """Print one rule and everything it turns into, target by target."""
    PolicyError, load, build, render, observe = _imports()
    policy_path, policy_overlay = _pick("policy")
    status_path, status_overlay = _pick("status")
    policy = load(policy_path, status_overlay or status_path, overlay_path=policy_overlay)
    plan = build(policy, today,
                 observe.load_observations(OBSERVATIONS))
    try:
        rule = policy.rule(rule_id)
    except StopIteration:
        print(f"no rule called '{rule_id}'. Rules are:", file=sys.stderr)
        for r in policy.rules:
            print(f"  {r.id:<18} {r.say}", file=sys.stderr)
        return 1

    print(f"\n  \"{rule.say}\"")
    print(f"  {rule.kind} rule for {policy.kid(rule.kid).name}\n")

    carries, cannot = [], []
    for surface in policy.surfaces:
        if plan["cells"][(rule.id, surface.id)]["applicable"]:
            carries.append(surface)
        else:
            why = ("doesn't reach this child" if rule.kid not in surface.covers
                   else f"can't do {rule.kind} rules at all")
            cannot.append((surface, why))

    print(f"  TRANSLATES TO {len(carries)} TARGET(S)")
    for surface in carries:
        how = surface.how[rule.kind]
        state = plan["cells"][(rule.id, surface.id)]["state"]
        print(f"\n  ── {surface.name}   [{state}]")
        for step in how.steps:
            print(f"       {step}")
        print(f"     confirm: {how.check}")
        if how.options:
            print(f"     offers:  {how.options}")

    if cannot:
        print(f"\n  CANNOT CARRY IT — {len(cannot)} app(s)")
        for surface, why in cannot:
            print(f"    {surface.name:<40} {why}")

    covered = [s for s in carries
               if plan["cells"][(rule.id, s.id)]["state"] == "verified"]
    print(f"\n  IN FORCE VIA: {', '.join(s.name for s in covered) or 'nothing — '
                                'no target is confirmed'}\n")
    return 0


def _judge_one(observation):
    """-> {verdict, why, said, declared} for one fresh observation, or None.

    Reloads the policy rather than trusting anything in the request: the page may be
    stale, and a rule id from the browser is an input, not a fact.
    """
    PolicyError, load, build_plan, render_page, observe = _imports()
    policy_path, policy_overlay = _pick("policy")
    status_path, status_overlay = _pick("status")
    policy = load(policy_path, status_overlay or status_path, overlay_path=policy_overlay)

    rule = next((r for r in policy.rules if r.id == observation.get("rule")), None)
    surface = next((s for s in policy.surfaces if s.id == observation.get("surface")), None)
    if rule is None or surface is None:
        return None
    how = surface.how.get(rule.kind)
    verdict = observe.judge(rule, observation, how)
    readings = observation.get("readings") or {}
    said = next((str(readings[k]) for k in ("dailyLimitText", "maturityText")
                 if readings.get(k)), None)
    return {"verdict": verdict["verdict"], "why": verdict["why"], "said": said,
            "in_force": verdict["in_force"]}


def _stats_now():
    """-> the hero tiles as they stand right now, straight from plane.render."""
    PolicyError, load, build_plan, render_page, observe = _imports()
    import datetime as _dt
    from plane.render import stat_tiles
    policy_path, policy_overlay = _pick("policy")
    status_path, status_overlay = _pick("status")
    policy = load(policy_path, status_overlay or status_path, overlay_path=policy_overlay)
    plan = build_plan(policy, _dt.date.today().isoformat(),
                      observe.load_observations(OBSERVATIONS))
    return stat_tiles(plan["summary"])


def _pick(stem):
    """-> (tracked file, overlay or None). The overlay is merged over the tracked file."""
    local = HERE / f"{stem}.local.yaml"
    return HERE / f"{stem}.yaml", (local if local.exists() else None)


def main(*args):
    import datetime
    args = list(args)

    # --demo is positional-agnostic: it is the kind of flag people type last, and
    # `--serve --demo` silently ignoring the second word would be its own bug.
    if "--demo" in args:
        args.remove("--demo")
        use_demo_observations()

    if args and args[0] == "--serve":
        # Try to rebuild, but serve either way. A missing dependency should not take
        # down a static page that has nothing to do with it.
        try:
            _build_page(datetime.date.today().isoformat())
            serve()
        except SystemExit:
            serve(stale_reason="PyYAML is missing, so the policy could not be read.")
        except Exception as exc:                      # noqa: BLE001
            serve(stale_reason=f"{type(exc).__name__}: {exc}")
        return 0

    if args and args[0] == "--explain":
        rule = args[1] if len(args) > 1 else ""
        today = args[2] if len(args) > 2 else datetime.date.today().isoformat()
        return explain(rule, today)
    return _build_page(args[0] if args else datetime.date.today().isoformat())


def _build_page(today, raise_on_error=False):
    PolicyError, load, build, render, observe = _imports()
    # A *.local.yaml is yours and gitignored; the checked-in files are the example.
    policy_path, policy_overlay = _pick("policy")
    status_path, status_overlay = _pick("status")
    try:
        policy = load(policy_path, status_overlay or status_path,
                      overlay_path=policy_overlay)
    except PolicyError as exc:
        print(f"policy is not valid, so nothing was written:\n  {exc}", file=sys.stderr)
        if raise_on_error:
            raise
        return 1
    seen = observe.load_observations(OBSERVATIONS)
    plan = build(policy, today, seen)
    if policy_overlay is not None:
        print(f"using {policy_overlay.name} (gitignored) as an overlay on policy.yaml")
    out = HERE / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(plan), encoding="utf-8")
    s = plan["summary"]
    print(f"wrote {out.relative_to(HERE)}  ·  {s['pairs_covered']} confirmed, "
          f"{s['todo_count']} need attention, "
          f"{s['rules_fully_uncovered']} rules with nothing in force"
          + (f", {s['pairs_observed']} read by the extension" if s["pairs_observed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
