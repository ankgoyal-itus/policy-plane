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

        def do_POST(self):                      # noqa: N802 (http.server's naming)
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

            path = HERE / "observations.json"
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
                 observe.load_observations(HERE / "observations.json"))
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


def _pick(stem):
    """-> (tracked file, overlay or None). The overlay is merged over the tracked file."""
    local = HERE / f"{stem}.local.yaml"
    return HERE / f"{stem}.yaml", (local if local.exists() else None)


def main(*args):
    import datetime
    args = list(args)

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
    seen = observe.load_observations(HERE / "observations.json")
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
