"""Turn the policy into a plan: what covers what, what's missing, what to do next.

One idea, stated once: a rule is covered by a surface only when that surface CAN enforce
it, covers that kid, and has been VERIFIED recently. Everything else -- never touched,
applied but unconfirmed, or verified too long ago -- is a gap.

That single rule is what stops the page from showing a green tick you haven't earned.
"""
import datetime
import json
import pathlib

from plane import observe
from plane.model import carries

TODO, APPLIED, VERIFIED, STALE = "todo", "applied", "verified", "stale"
UNEXPRESSIBLE = "unexpressible"
FULL, PARTIAL = "full", "partial"
COVERED_STATES = (VERIFIED,)          # the whole safety property, in one line


def _today(today):
    if isinstance(today, datetime.date):
        return today
    return datetime.date.fromisoformat(str(today))


def applies(rule, surface):
    """Reaches the kid, handles the kind, governs the app. See model.carries."""
    return carries(rule, surface)


def depth(rule, surface):
    """-> (full|partial, honoured, dropped).

    A vendor that honours some of a rule's parameters but not all is not enforcing the
    rule as written. Roblox's daily limit applies to every day, so a weekday-only rule
    silently becomes an every-day one there. That is `partial`, and it is deliberately
    NOT counted as covered -- the parent asked for something the app cannot express.
    """
    accepts = set(surface.how[rule.kind].accepts)
    honoured = sorted(k for k in rule.params if k in accepts)
    dropped = sorted(k for k in rule.params if k not in accepts)
    return (PARTIAL if dropped else FULL), honoured, dropped


def pair_state(policy, rule, surface, today, observations=()):
    """-> (state, record, age_days, verdict). Absent record is todo, never a quiet pass.

    An OBSERVATION -- the extension having read the settings page -- outranks a
    self-attestation for the same pair, because "the page said 90" is a stronger claim
    than "I remember setting it". It is still subject to the same recheck clock: a read
    from three months ago is as stale as a memory from three months ago.
    """
    seen = observe.latest(observations, rule.id, surface.id)
    if seen:
        # The surface's `how` carries the vendor vocabulary the judge needs. Passing it
        # here keeps the judge free of any vendor knowledge of its own.
        verdict = observe.judge(rule, seen, surface.how.get(rule.kind))
        age = _age(seen.get("at"), today)
        if verdict["verdict"] == observe.UNEXPRESSIBLE:
            return UNEXPRESSIBLE, seen, age, verdict
        if not verdict["in_force"]:
            return APPLIED, seen, age, verdict
        if age is not None and age > surface.recheck_days:
            return STALE, seen, age, verdict
        return VERIFIED, seen, age, verdict

    record = policy.record(rule.id, surface.id)
    if record is None:
        return TODO, None, None, None
    age = (_today(today) - record.date).days
    if record.state == APPLIED:
        return APPLIED, record, age, None
    return (STALE if age > surface.recheck_days else VERIFIED), record, age, None


def _age(stamp, today):
    if not stamp:
        return None
    try:
        seen = datetime.date.fromisoformat(str(stamp)[:10])
    except ValueError:
        return None
    return (_today(today) - seen).days


def build(policy, today, observations=()):
    """-> plan dict. Pure: same policy and same `today` give the same plan every time."""
    today = _today(today)
    cells, rules_out, checklist = {}, [], []

    for rule in policy.rules:
        covered_by, partial_by, gaps = [], [], []
        for surface in policy.surfaces:
            if not applies(rule, surface):
                cells[(rule.id, surface.id)] = {"applicable": False, "state": None}
                continue
            state, record, age, verdict = pair_state(policy, rule, surface, today,
                                                     observations)
            how = surface.how[rule.kind]
            fit, honoured, dropped = depth(rule, surface)
            cells[(rule.id, surface.id)] = {
                "applicable": True, "state": state, "depth": fit,
                "honoured": honoured, "dropped": dropped, "recipe": how.recipe,
                "date": _stamp(record),
                "by": (record.by if hasattr(record, "by")
                       else "extension" if record else None),
                "age_days": age, "recheck_days": surface.recheck_days,
                "has_evidence": bool(getattr(record, "evidence", "")),
                "evidence": getattr(record, "evidence", ""),
                "observed": bool(verdict),
                "verdict": verdict["verdict"] if verdict else None,
                "why": verdict["why"] if verdict else None,
                # The vendor's OWN words, kept verbatim for display. The whole claim of
                # this product is that it reports what the vendor said, so the page shows
                # the raw string beside the verdict rather than asking anyone to take
                # the verdict on trust.
                "said": _said(record),
            }
            if state in COVERED_STATES and fit == FULL:
                covered_by.append(surface.id)
            elif state in COVERED_STATES:
                partial_by.append(surface.id)
                gaps.append({"surface": surface.id, "state": "partial",
                             "age_days": age, "dropped": dropped})
            else:
                gaps.append({"surface": surface.id, "state": state, "age_days": age})
                checklist.append({
                    "rule": rule.id, "surface": surface.id, "kid": rule.kid,
                    "kind": rule.kind, "say": rule.say, "state": state,
                    "name": surface.name, "link": surface.link,
                    "link_kind": surface.link_kind, "steps": list(how.steps),
                    "check": how.check, "options": how.options,
                    "recipe": how.recipe, "depth": fit,
                    "honoured": honoured, "dropped": dropped,
                    "params": dict(rule.params), "redact": surface.redact,
                    "why": _why(state, age, surface.recheck_days),
                })
        rules_out.append({
            "id": rule.id, "kid": rule.kid, "kind": rule.kind, "say": rule.say,
            "app": rule.app, "params": dict(rule.params),
            "covered_by": covered_by, "partial_by": partial_by, "gaps": gaps,
            "reachable": any(applies(rule, s) for s in policy.surfaces),
        })

    return {
        "family": policy.family,
        "verifiable": _verifiable(policy, cells),
        "generated": today.isoformat(),
        "kids": [{"id": k.id, "name": k.name} for k in policy.kids],
        "surfaces": [{
            "id": s.id, "name": s.name, "covers": list(s.covers), "can": list(s.can),
            "reach": s.reach, "blind": s.blind, "link": s.link,
            "link_kind": s.link_kind, "recheck_days": s.recheck_days,
            "catalog": [{"kind": k, "options": s.how[k].options,
                         "accepts": list(s.how[k].accepts), "recipe": s.how[k].recipe,
                         "used_by": sorted(r.id for r in policy.rules
                                           if r.kind == k and r.kid in s.covers)}
                        for k in sorted(s.how)],
        } for s in policy.surfaces],
        "rules": rules_out,
        "cells": cells,
        "checklist": sorted(checklist, key=lambda c: (c["surface"], c["rule"])),
        "summary": _summary(rules_out, cells),
    }


# rule param name -> the name the recipe's own schema uses. Recipes are written to a
# vendor's vocabulary; policies are written to ours. This is the seam between them.
_RECIPE_PARAMS = {"minutes_per_day": "minutesPerDay"}

# Generated from the recipe files by extension/test/schemas.gen.js. The plane cannot
# import a recipe -- recipes live in the extension by design -- so this is the contract
# between the halves, and it is checked at BUILD time. Before it existed, a param the
# plane failed to supply surfaced as BAD_PARAMS in the browser at click time.
_SCHEMAS = pathlib.Path(__file__).resolve().parent.parent / "extension" / "recipes" / "schemas.json"


def recipe_schemas():
    try:
        return json.loads(_SCHEMAS.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _verifiable(policy, cells):
    """-> the (rule, surface) pairs an extension recipe can actually read back.

    Params are resolved HERE, in the plane, and sent to the extension as values. The
    page never sends steps, selectors or a URL -- only a recipe id and parameters -- so
    a compromised page cannot make the extension do something a recipe does not already
    describe.
    """
    out, schemas = [], recipe_schemas()
    for rule in policy.rules:
        for surface in policy.surfaces:
            cell = cells.get((rule.id, surface.id)) or {}
            recipe = cell.get("recipe")
            if not cell.get("applicable") or not recipe:
                continue
            params = {_RECIPE_PARAMS[k]: v for k, v in rule.params.items()
                      if k in _RECIPE_PARAMS}
            # Which account identity this surface needs is declared on the surface.
            # Looking it up by `app` was wrong: a device-level surface has app "*", so
            # nothing ever resolved and the param was silently dropped -- which the
            # extension then rejected as BAD_PARAMS, in the browser, at click time.
            wants = surface.account or (surface.app if surface.app != "*" else "")
            account = policy.kid(rule.kid).accounts.get(wants) if wants else None
            if account:
                params["childUsername"] = account["username"]
                if "id" in account:
                    params["childUserId"] = account["id"]
            schema = schemas.get(recipe)
            if schema is None:
                # The policy names a recipe the extension does not ship. Offering the
                # button would fail at click time with "unknown recipe"; saying so here
                # is both earlier and clearer.
                out.append({"rule": rule.id, "surface": surface.id, "recipe": recipe,
                            "say": rule.say, "surface_name": surface.name, "params": {},
                            "blocked": ["<recipe missing>"],
                            "why_blocked": f"the extension ships no recipe called "
                                           f"'{recipe}'"})
                continue
            # Send exactly what the recipe declares and nothing else. validateParams
            # rejects unknown params, so an extra one fails the run just as surely as a
            # missing one -- and the plane knows things (a username) that a recipe routed
            # by id has no use for.
            known = set(schema.get("required", ())) | set(schema.get("optional", ()))
            if known:
                params = {k: v for k, v in params.items() if k in known}
            missing = sorted(set(schema.get("required", ())) - set(params))
            out.append({"rule": rule.id, "surface": surface.id, "recipe": recipe,
                        "say": rule.say, "surface_name": surface.name, "params": params,
                        "blocked": missing,
                        "why_blocked": (
                            f"cannot run: {recipe} needs {', '.join(missing)}, which this "
                            f"policy does not supply. Give {policy.kid(rule.kid).short} an "
                            f"account for '{surface.account or surface.app}', or the recipe "
                            f"should not require it." if missing else "")})
    return sorted(out, key=lambda v: (v["surface"], v["rule"]))


def _said(record):
    """-> the vendor's own words for this reading, or None."""
    if not record:
        return None
    readings = (record if isinstance(record, dict) else {}).get("readings") or {}
    for key in ("dailyLimitText", "maturityText"):
        if readings.get(key):
            return str(readings[key])
    return None


def _stamp(record):
    if record is None:
        return None
    if hasattr(record, "date"):
        return record.date.isoformat()
    return str(record.get("at", ""))[:10] or None


def _why(state, age, recheck):
    if state == UNEXPRESSIBLE:
        return "this app cannot express the value the rule asks for"
    if state == "partial":
        return "set here, but this app cannot express the whole rule"
    if state == TODO:
        return "never set up here"
    if state == APPLIED:
        return "changed, but never confirmed — go back and look at it"
    return f"last checked {age} days ago; this one wants re-checking every {recheck}"


def _summary(rules_out, cells):
    applicable = [c for c in cells.values() if c["applicable"]]
    covered = [c for c in applicable
               if c["state"] in COVERED_STATES and c["depth"] == FULL]
    return {
        "rules": len(rules_out),
        "rules_fully_uncovered": sum(1 for r in rules_out if not r["covered_by"]),
        "rules_with_no_surface": sum(1 for r in rules_out if not r["reachable"]),
        "pairs_applicable": len(applicable),
        "pairs_covered": len(covered),
        "pairs_stale": sum(1 for c in applicable if c["state"] == STALE),
        "pairs_applied_unconfirmed": sum(1 for c in applicable if c["state"] == APPLIED),
        "pairs_todo": sum(1 for c in applicable if c["state"] == TODO),
        "pairs_unexpressible": sum(1 for c in applicable if c["state"] == UNEXPRESSIBLE),
        "pairs_observed": sum(1 for c in applicable if c.get("observed")),
        "pairs_partial": sum(1 for c in applicable
                             if c["state"] in COVERED_STATES and c["depth"] == PARTIAL),
        "todo_count": sum(1 for c in applicable if c["state"] not in COVERED_STATES),
    }
