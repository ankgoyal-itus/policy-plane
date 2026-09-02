# Policy Plane

**Define once. Verified everywhere.**

> **What this repo is.** A working reference implementation, shipped with **simulated
> vendors only**. It runs end to end on two local fixture pages, so you can clone it and
> watch a rule be verified in about two minutes with no account anywhere.
>
> It deliberately ships **no recipe for any real vendor**. The private copy this was
> built from reads a real one; that half stays private, because publishing a real
> vendor's selectors means publishing something that rots the day they redesign, in a
> repo nobody is maintaining. The patterns are the point, and the patterns are all here.
>
> No real family data is in this repository, its history, or anything it generates.
> `scripts/leak_check.py` is the gate that enforces that, and it can prove it fails.

Parental controls are per-app by construction. Every app shows you a green tick for its
own slice, which reads as *protected* while three other routes stay wide open. Nothing
gives you one view, and settings drift quietly — an OS update resets a toggle, a kid
finds the browser instead of the app, and nobody notices for months.

policy-plane doesn't try to enforce anything. It can't: the enforcement points are sealed.
Apple's Family Controls prohibits one app reading another's restrictions, Family Link has
no public API, and Roblox, YouTube and Xbox are account settings only. Even NextDNS — the
one surface here with a real API — has no schedule field on it at all.

So it does the honest thing instead:

1. You write your rules once, in your own words, in `policy.yaml`
2. It works out which apps can carry each rule, and which can't
3. It translates each rule into **that app's own steps** — the bedtime rule becomes
   Screen Time's Downtime, Roblox's Screen Time and Xbox's Screen time, three different
   click-paths from one sentence you wrote
4. You record what you've confirmed, and when
5. It renders one page telling you the truth about what's covered

It also carries the thing you'd otherwise have to open each app to discover: **what each
app can actually control, and how deep it goes.** You can't find out what Xbox does for
parental controls without being inside Xbox. That catalog is written down here once, and
the page tells you which parts of it no rule of yours is using.

**Only a rule you have gone back and confirmed counts as covered.** Not "I changed it".
Not "I set that up in June". Those show as gaps, because nothing reads back from these
apps and an unconfirmed setting is a belief, not a fact.

## What it is not

It does not watch your kids. No usage, no activity, no messages, no location. The only
things it tracks are *your* settings and *your* confirmations. That boundary is enforced
by a test, not a promise in a README — `evals/test_3_page_cannot_lie.py` fails the build
if behavioural data ever reaches the page.

## See it work in two minutes

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python build.py --serve          # serves on localhost:8787
```

Load `extension/` at `chrome://extensions` with developer mode on, then open
<http://localhost:8787/docs/>. One rule — *Alex may use Roblox for at most 90 minutes a
day* — sits at the top with a **Verify** button per vendor. Press them.

Both simulated vendors are local pages, so nothing leaves your machine, and they answer
differently on purpose:

| Vendor | Shape | Says | Verdict |
|---|---|---|---|
| Vendor A | custom dropdown widget, worded durations | `1 hour 30 minutes` | **in force** — exactly as asked |
| Vendor B | native `<select>`, bare minutes, no drawer | `60`, offering 0/30/60/120 | **can't be expressed** — no 90 on the list |

That is the whole thesis in one screen: one sentence you wrote once, two vendors that
share no vocabulary and no page structure, read through the same engine with no
vendor-specific code in it, and two honest answers rather than two green ticks.

Then change something. Open a fixture, pick a different limit, save — the fixtures are
real little settings pages that remember what you set. The dashboard hears that a vendor
moved and **re-reads it**, rather than believing the message: the notification carries no
value at all, only the fact that something changed. Set Vendor A to 2 hours and the
verdict turns to *not in force*, because 120 is looser than the 90 you declared.

While each check runs, a bar appears at the top of the page being read — *Policy Plane
read this page. Nothing was changed.* — and the tab closes itself after three seconds. A
tab that **stays** open means the read failed, which is worth knowing at a glance.

There is a control panel at <http://localhost:8787/demo_dashboard> with a Reset that puts
the readings and the fixtures back to their starting state, for when you want to run
through it again.

```bash
.venv/bin/python build.py          # writes docs/index.html (gitignored)
```

Use `.venv/bin/python`, not `python3`. PyYAML is the only dependency, and a virtualenv
keeps it off a system Python — Homebrew's is externally managed and will refuse a plain
`pip install` anyway.

`--serve` is required for anything involving the Chrome extension: a `file://` page can
never message an extension, so the dashboard has to come off a real origin. It serves
even if the build fails, and says loudly when what you are looking at is stale.

Edit `policy.yaml` to add your kids, rules and apps. Edit `status.yaml` as you work
through the checklist. Re-run `build.py`.

To see what one rule turns into everywhere:

```bash
python3 build.py --explain alex-bedtime
```

```
  "No screens after 21:30 on school nights"
  schedule rule for Alex, 12

  TRANSLATES TO 3 TARGET(S)

  ── Screen Time — Alex's iPad   [verified]
       Settings → Screen Time → Family → Alex
       Downtime → turn on and set the window
     confirm: Downtime is ON and the window matches the rule

  ── Roblox — Alex's account   [todo]
       Settings → Parental Controls → Screen Time
     confirm: Screen Time shows the right limit and the PIN is set
  ...
  CANNOT CARRY IT — 3 app(s)
    NextDNS — home wifi     can't do schedule rules at all
```

**Keeping your real policy private:** the checked-in `policy.yaml` uses placeholder names.
Copy it to `policy.local.yaml` (and `status.local.yaml`) for the real thing — both are
gitignored and `build.py` prefers them automatically.

## The model, in full

- **Rule** — something you want, in plain language, with one of five kinds:
  `schedule`, `contact`, `content`, `time`, `purchase`
- **Surface** — an app or device: who it `covers`, what it `can` do, what it's `blind` to,
  and `how` to do each thing — steps, what to confirm, and what depth the app offers.
  A surface may not claim a control in `can` without a matching `how`. An unbacked claim
  fails the load rather than rendering as a confident empty promise.
- **Record** — you applied a rule on a surface, and later confirmed it, on a date
- A rule is **covered** by a surface only when the surface can do that kind, reaches that
  kid, and has been confirmed within its `recheck_days`

That's the whole thing. Everything on the page is derived from those three.

## Verifying automatically

A Chrome extension can open an app, read the setting back, and report what the page
actually said. It is **read-only** — the engine's entire action set is `waitFor`, `click`
and `read`, so a verify recipe cannot change a setting because there is no way for it to.

**The extension reads; the plane judges.** It returns the raw text the page showed;
Python re-parses that text and decides. A component that both reads a setting and rules
on whether it is right is grading its own homework, and that matters more, not less, once
a write path exists.

That produces a verdict the dashboard shows:

| verdict | meaning |
|---|---|
| `satisfied` | set to exactly what the rule asks |
| `stricter` | set tighter than asked — still in force |
| `not_satisfied` | set looser than asked |
| `unexpressible` | **the app does not offer that value at all** |
| `unknown` | the read did not complete, or the text was unreadable |

`unexpressible` is the one that earns its keep. "Roblox does not offer 90 minutes" and
"you never set it" produce the same empty cell and demand opposite actions — one sends
you to rewrite the rule, the other sends you to Roblox.

See `extension/README.md` to load it.

## Evals

Six suites, all mutation-tested — every guard has been checked against a deliberately
broken version to prove it can actually fail.

| Suite | Claim it defends |
|---|---|
| `test_1_honest_coverage` | Coverage is never overstated. Stale, unconfirmed and untouched all read as gaps. |
| `test_2_define_once` | Every instruction traces to exactly one rule; change the rule and the instructions follow. |
| `test_3_page_cannot_lie` | The page never shows a state the plan didn't produce, and never carries behavioural data. |
| `test_4_translation` | One rule reaches several targets and gets each target's own procedure — never a generic one. An app cannot claim a control without a click-path for it. |
| `test_5_parameters` | Params are typed and validated; the English is generated from them; a rule about one app is not routed at another; partial support is not coverage. |
| `test_6_judging` | The plane judges, not the reader. Unexpressible is not covered, a failed read is never satisfied, and an old read goes stale like any other claim. |

```bash
.venv/bin/python run_evals.py               # six suites
node --test extension/test/engine.test.js   # the engine, no browser needed
```

## Layout

```
policy.yaml       your rules and apps — the single source of truth
status.yaml       what you've applied and confirmed
plane/model.py    load and validate, fail-closed
plane/plan.py     rules × surfaces → coverage and a checklist
plane/render.py   → docs/index.html
build.py          one command
docs/index.html   the page — generated, gitignored, never committed
```

Python: standard library plus PyYAML, no framework. The extension is plain
JavaScript with no build step and no dependencies — the engine is two files you can read
in one sitting, which is the point when the thing you are being asked to trust is
something that opens tabs in your logged-in browser.
