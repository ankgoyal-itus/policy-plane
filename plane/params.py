"""The parameter vocabulary — the part that keeps this a policy point, not a Roblox tool.

A rule is a KIND plus typed PARAMS. The kind says what sort of control it is; the params
say what you actually want. Vendors declare which params they can honour, so "not every
app supports this" becomes computed rather than prose.

English is the OUTPUT, not the input. You fill fields; `phrase()` renders the sentence.
Nothing parses natural language, so a policy always means exactly one thing.
"""

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")
WEEKEND = ("sat", "sun")

# kind -> param name -> spec. `type` drives validation; nothing here is vendor-specific.
PARAMS = {
    "time": {
        "minutes_per_day": {"type": "int", "min": 0, "max": 1440},
    },
    "schedule": {
        "not_after":  {"type": "clock"},
        "not_before":  {"type": "clock"},
        "not_between": {"type": "window"},
        "days":        {"type": "days"},
    },
    "contact": {
        "who": {"type": "enum",
                "values": ("nobody", "family_only", "known_only", "anyone")},
    },
    "content": {
        "max_maturity": {"type": "enum",
                         "values": ("kids", "preteen", "teen", "mature")},
    },
    "purchase": {
        "require_approval": {"type": "bool"},
        "monthly_limit":    {"type": "int", "min": 0, "max": 1000000},
    },
}

_MATURITY = {"kids": "kids", "preteen": "pre-teen", "teen": "teen", "mature": "mature"}
_WHO = {"nobody": "nobody", "family_only": "family only",
        "known_only": "people they already know", "anyone": "anyone"}


class ParamError(Exception):
    """A param is unknown, mistyped, or out of range. Never coerced, never ignored."""


def validate(kind, params, where):
    """-> dict of validated params. Raises ParamError; there is no lenient path."""
    if kind not in PARAMS:
        raise ParamError(f"{where}: unknown rule kind '{kind}'")
    known = PARAMS[kind]
    unknown = sorted(set(params) - set(known))
    if unknown:
        raise ParamError(
            f"{where}: {unknown} are not parameters of a '{kind}' rule. "
            f"Valid: {sorted(known)}")
    if not params:
        raise ParamError(f"{where}: a '{kind}' rule needs at least one parameter")
    out = {}
    for name, value in params.items():
        out[name] = _one(known[name], value, f"{where}.{name}")
    return out


def _one(spec, value, where):
    kind = spec["type"]
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParamError(f"{where}: expected a whole number, got {value!r}")
        if not spec["min"] <= value <= spec["max"]:
            raise ParamError(f"{where}: {value} is outside {spec['min']}–{spec['max']}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise ParamError(f"{where}: expected true or false, got {value!r}")
        return value
    if kind == "enum":
        if value not in spec["values"]:
            raise ParamError(f"{where}: {value!r} not one of {list(spec['values'])}")
        return value
    if kind == "clock":
        text = str(value)
        parts = text.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ParamError(f"{where}: expected HH:MM, got {value!r}")
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ParamError(f"{where}: {value!r} is not a real time of day")
        return f"{hh:02d}:{mm:02d}"
    if kind == "window":
        if not isinstance(value, list) or len(value) != 2:
            raise ParamError(f"{where}: expected two 'HH:MM' values")
        return tuple(_one({"type": "clock"}, v, f"{where}[{i}]")
                     for i, v in enumerate(value))
    if kind == "days":
        if not isinstance(value, list) or not value:
            raise ParamError(f"{where}: expected a non-empty list of days")
        for day in value:
            if day not in DAYS:
                raise ParamError(f"{where}: '{day}' is not a day, expected {list(DAYS)}")
        return tuple(d for d in DAYS if d in value)     # canonical order, deduped
    raise ParamError(f"{where}: unhandled parameter type {kind!r}")


def _days_phrase(days):
    if not days or set(days) == set(DAYS):
        return "every day"
    if tuple(days) == WEEKDAYS:
        return "on weekdays"
    if tuple(days) == WEEKEND:
        return "at weekends"
    return "on " + ", ".join(d.capitalize() for d in days)


def phrase(kind, params, kid_name, app_label):
    """-> the rule as an English sentence, generated from the fields.

    Generated rather than authored so the sentence can never drift from the parameters
    the vendors are actually checked against.
    """
    p = dict(params)
    if kind == "time":
        return (f"{kid_name} may use {app_label} for at most "
                f"{p['minutes_per_day']} minutes a day")
    if kind == "schedule":
        bits = []
        if p.get("not_after"):
            bits.append(f"after {p['not_after']}")
        if p.get("not_before"):
            bits.append(f"before {p['not_before']}")
        if p.get("not_between"):
            bits.append(f"between {p['not_between'][0]} and {p['not_between'][1]}")
        when = " or ".join(bits) if bits else "at restricted times"
        return f"{kid_name} may not use {app_label} {when} {_days_phrase(p.get('days'))}"
    if kind == "contact":
        return (f"{kid_name} may be contacted on {app_label} by "
                f"{_WHO[p['who']]}")
    if kind == "content":
        return (f"{kid_name} sees {_MATURITY[p['max_maturity']]} content at most "
                f"on {app_label}")
    if kind == "purchase":
        bits = []
        if p.get("require_approval"):
            bits.append("needs approval to buy anything")
        if p.get("monthly_limit") is not None:
            limit = p["monthly_limit"]
            bits.append("may not spend at all" if limit == 0
                        else f"may spend at most {limit} a month")
        return f"{kid_name} " + " and ".join(bits) + f", on {app_label}"
    raise ParamError(f"no phrasing for kind {kind!r}")
