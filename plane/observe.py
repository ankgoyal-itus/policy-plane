"""The judge: what the page said, versus what the policy asked for.

The extension reads. This decides. That split is the only thing keeping verification
honest -- a component that both changes a setting and rules on whether the change worked
is grading its own homework, and it matters more, not less, once a write path exists.

So this re-parses the RAW TEXT the page showed, rather than trusting any number the
extension computed. The extension's own parse comes back as `advisory` and a
disagreement between the two is itself reported.
"""
import datetime
import json
import re

SATISFIED = "satisfied"
STRICTER = "stricter"
NOT_SATISFIED = "not_satisfied"
UNEXPRESSIBLE = "unexpressible"
UNKNOWN = "unknown"

VERDICTS = (SATISFIED, STRICTER, NOT_SATISFIED, UNEXPRESSIBLE, UNKNOWN)
# Only these count as the rule being in force. `stricter` counts: the child is at least
# as protected as asked. `unexpressible` never does -- it means go and rewrite the rule.
IN_FORCE = (SATISFIED, STRICTER)

# A limit that is not a duration. Roblox's dropdown leads with "No limit", and reading
# that as 0 minutes would be catastrophic: a child with UNLIMITED Roblox would judge as
# stricter than any rule and the cell would go green. Infinity makes every comparison
# come out the right way round.
UNLIMITED = float("inf")

# `none` is deliberately in this list. On some vendors it means "no limit", on others
# "none allowed", and the text alone cannot tell you which. Fail-closed means assuming
# the LESS protective reading: a false "not in force" costs a wasted check, a false
# "in force" costs a child with no limit and a green tick.
_UNLIMITED_TEXT = re.compile(
    r"^(none|no limit|no limits|unlimited|off|never|not set|no restriction)$", re.I)
_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", re.I)
_MINS = re.compile(r"(\d+)\s*(?:m|min|mins|minute|minutes)\b", re.I)
_BARE = re.compile(r"^(\d+)$")


def parse_minutes(text):
    """-> int minutes, or None if the text cannot be read as a duration.

    None is a real answer and must never collapse to 0. "we could not read it" and
    "it is set to zero" are opposite facts about a child's device.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if _UNLIMITED_TEXT.match(s):
        return UNLIMITED
    total, seen = 0, False
    hours = _HOURS.search(s)
    if hours:
        total += float(hours.group(1)) * 60
        seen = True
    mins = _MINS.search(s)
    if mins:
        total += int(mins.group(1))
        seen = True
    if not seen:
        bare = _BARE.match(s)
        if not bare:
            return None
        total = int(bare.group(1))
    return round(total)


def _show(minutes):
    return "no limit at all" if minutes == UNLIMITED else f"{minutes} minutes"


def judge_time(requested_minutes, observed_text, offered_texts=()):
    """-> dict verdict for a `time` rule. Deterministic; reads no clock and no network."""
    observed = parse_minutes(observed_text)
    offered = [m for m in (parse_minutes(t) for t in offered_texts or ()) if m is not None]

    if offered and requested_minutes not in offered:
        return _v(UNEXPRESSIBLE, observed, offered,
                  f"this app offers {', '.join(str(o) for o in sorted(set(offered)))} "
                  f"minutes; {requested_minutes} is not on the list, so the rule cannot "
                  f"be set here as written")
    if observed is None:
        return _v(UNKNOWN, observed, offered,
                  f"could not read a duration from {observed_text!r}")
    # UNLIMITED needs no special case: infinity is never equal to and never less than
    # a requested number, so it falls through to `not_satisfied` on its own, and _show()
    # renders it as "no limit at all". A branch here would be dead code that merely
    # restated the general path -- mutation testing showed deleting it changed nothing.
    if observed == requested_minutes:
        return _v(SATISFIED, observed, offered, f"set to {observed} minutes, as asked")
    if observed < requested_minutes:
        return _v(STRICTER, observed, offered,
                  f"set to {observed} minutes, stricter than the {requested_minutes} asked for")
    return _v(NOT_SATISFIED, observed, offered,
              f"set to {_show(observed)}, looser than the {requested_minutes} asked for")


def _v(verdict, observed, offered, why):
    return {"verdict": verdict, "in_force": verdict in IN_FORCE,
            "observed_minutes": None if observed == UNLIMITED else observed,
            "observed_unlimited": observed == UNLIMITED,
            "offered_minutes": sorted(m for m in set(offered) if m != UNLIMITED),
            "why": why}


def judge_content(requested, observed_text, offered_texts=(), maps=None):
    """-> verdict for a `content` rule, using the vendor's own words.

    `maps` is the catalog's translation of OUR vocabulary into this vendor's labels
    ({"preteen": "Older Kids"}). Keeping it in the catalog is what lets one judge handle
    Netflix, Roblox and YouTube without knowing anything about any of them.

    Lower maturity is stricter, exactly as fewer minutes is stricter -- so the shape of
    the comparison is identical to judge_time and the two verdicts mean the same thing.
    """
    from plane.params import PARAMS
    scale = list(PARAMS["content"]["max_maturity"]["values"])
    maps = maps or {}
    if not maps:
        return _c(UNKNOWN, None, [], "this app has no vocabulary map, so its labels "
                                     "cannot be compared with the rule")
    if requested not in maps:
        return _c(UNEXPRESSIBLE, None, sorted(maps),
                  f"this app has no setting for '{requested}'; it offers "
                  f"{', '.join(sorted(maps))}")

    back = {str(label).strip().lower(): ours for ours, label in maps.items()}
    observed = back.get(str(observed_text or "").strip().lower())
    offered = sorted({back[str(t).strip().lower()] for t in (offered_texts or ())
                      if str(t).strip().lower() in back}, key=scale.index)
    if observed is None:
        return _c(UNKNOWN, None, offered,
                  f"could not match {observed_text!r} to any level this app declares")

    here, want = scale.index(observed), scale.index(requested)
    if here == want:
        return _c(SATISFIED, observed, offered, f"set to '{observed_text}', as asked")
    if here < want:
        return _c(STRICTER, observed, offered,
                  f"set to '{observed_text}', stricter than '{requested}'")
    return _c(NOT_SATISFIED, observed, offered,
              f"set to '{observed_text}', which allows more than '{requested}'")


def _c(verdict, observed, offered, why):
    return {"verdict": verdict, "in_force": verdict in IN_FORCE,
            "observed_level": observed, "offered_levels": list(offered),
            "observed_minutes": None, "observed_unlimited": False,
            "offered_minutes": [], "why": why}


def judge(rule, observation, how=None):
    """-> verdict dict for any rule kind. Unknown kinds are UNKNOWN, never satisfied."""
    readings = observation.get("readings") or {}
    if observation.get("code") and observation["code"] != "OK":
        return {"verdict": UNKNOWN, "in_force": False, "observed_minutes": None,
                "offered_minutes": [],
                "why": f"the read did not complete: {observation['code']}"
                       f"{' at ' + observation['failing_step'] if observation.get('failing_step') else ''}"}
    # For a recipe routed by id, the page's own URL is the identity check -- it costs no
    # selector and cannot go missing. A redirect to a login page or to another child
    # makes everything else read off it describe something else.
    wanted_id = (observation.get("params") or {}).get("childUserId")
    page_url = observation.get("url")
    if wanted_id and page_url and str(wanted_id) not in str(page_url):
        return {"verdict": UNKNOWN, "in_force": False, "observed_minutes": None,
                "observed_unlimited": False, "offered_minutes": [],
                "why": f"the page ended up at {page_url!r}, which is not child "
                       f"{wanted_id} — it may have redirected to a login or another child"}

    # Where a recipe DOES pick a child on the page, the picker is READ, never set.
    expected = (observation.get("params") or {}).get("childUsername")
    seen_child = readings.get("selectedChild")
    if expected and seen_child and str(seen_child) != str(expected):
        return {"verdict": UNKNOWN, "in_force": False, "observed_minutes": None,
                "offered_minutes": [],
                "why": f"the page was showing '{seen_child}', not '{expected}' — "
                       f"everything read from it is about the wrong child"}

    if rule.kind == "time":
        out = judge_time(rule.params["minutes_per_day"],
                         readings.get("dailyLimitText"),
                         readings.get("offeredText") or ())
        advisory = readings.get("advisoryMinutes")
        if advisory is not None and advisory != out["observed_minutes"]:
            out["why"] += (f" (the extension read {advisory}; this judge read "
                           f"{out['observed_minutes']} from the same text — "
                           f"treat the reading as unreliable)")
            out["verdict"], out["in_force"] = UNKNOWN, False
        return out
    if rule.kind == "content":
        return judge_content(rule.params["max_maturity"],
                             readings.get("maturityText"),
                             readings.get("offeredText") or (),
                             getattr(how, "maps", None))
    return {"verdict": UNKNOWN, "in_force": False, "observed_minutes": None,
            "observed_unlimited": False, "offered_minutes": [],
            "why": f"no automated check exists for '{rule.kind}' rules yet"}


def load_observations(path):
    """-> list. A missing file is 'nothing observed', never an error and never a pass."""
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError):
        # Unreadable is not empty. Refuse rather than quietly report zero observations.
        raise ValueError(f"{path} exists but could not be read as JSON")
    return raw if isinstance(raw, list) else []


def latest(observations, rule_id, surface_id):
    """-> the most recent observation for this pair, or None."""
    matching = [o for o in observations
                if o.get("rule") == rule_id and o.get("surface") == surface_id]
    if not matching:
        return None
    return max(matching, key=lambda o: o.get("at", ""))


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
