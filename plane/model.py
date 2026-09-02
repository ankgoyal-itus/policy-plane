"""Load and validate policy.yaml and status.yaml.

Fail-closed: one bad record fails the whole load. There is no "skip it and carry on"
path, because a silently skipped rule is a rule you think is in force and isn't.
"""
import datetime
from dataclasses import dataclass, field

import yaml

from plane import params as P

KINDS = tuple(sorted(P.PARAMS))
STATES = ("applied", "verified")
LINK_KINDS = ("official", "unofficial")


class PolicyError(Exception):
    """policy.yaml or status.yaml is invalid. Load nothing rather than load half."""


@dataclass(frozen=True)
class Kid:
    id: str
    name: str
    accounts: dict = field(default_factory=dict)   # app -> username on that app

    @property
    def short(self):
        """First name only, for generated sentences. "Alex, 12" -> "Alex"."""
        return self.name.split(",")[0].strip()


@dataclass(frozen=True)
class Rule:
    id: str
    kid: str
    kind: str
    params: dict
    app: str = ""        # which app this is about; "" means every screen
    say: str = ""        # DERIVED from params at load time, never authored


@dataclass(frozen=True)
class How:
    """What to do on this surface for ONE kind of rule, and what it can actually offer.

    `options` is the depth the app really has -- the thing you can normally only find out
    by being inside that app. It is the catalog, written down once.
    """
    steps: tuple
    check: str
    options: str = ""
    accepts: tuple = ()   # which params of this kind the vendor can actually honour
    recipe: str = ""      # recipe id, where an automated read-back exists
    maps: dict = field(default_factory=dict)   # our vocabulary -> this vendor's words


@dataclass(frozen=True)
class Surface:
    id: str
    name: str
    covers: tuple
    can: tuple
    app: str = "*"        # the app it controls; "*" = device or network level
    account: str = ""     # which of the kid's accounts its recipe needs, if any
    how: dict = field(default_factory=dict)      # kind -> How
    reach: str = ""
    blind: str = ""
    link: str = ""
    link_kind: str = ""
    redact: str = ""
    recheck_days: int = 60


@dataclass(frozen=True)
class Record:
    rule: str
    surface: str
    state: str
    date: datetime.date
    by: str
    evidence: str = ""


@dataclass(frozen=True)
class Policy:
    family: str
    kids: tuple
    rules: tuple
    surfaces: tuple
    records: tuple = ()

    def rule(self, rid):
        return next(r for r in self.rules if r.id == rid)

    def surface(self, sid):
        return next(s for s in self.surfaces if s.id == sid)

    def kid(self, kid_id):
        return next(k for k in self.kids if k.id == kid_id)

    def record(self, rule_id, surface_id):
        for r in self.records:
            if r.rule == rule_id and r.surface == surface_id:
                return r
        return None


def _keys(d, allowed, where):
    if not isinstance(d, dict):
        raise PolicyError(f"{where}: expected a mapping")
    extra = sorted(set(d) - set(allowed))
    if extra:
        raise PolicyError(f"{where}: unknown key(s) {extra}")


def _req(d, key, where):
    if not d.get(key):
        raise PolicyError(f"{where}: missing required key '{key}'")
    return d[key]


def _one_of(value, allowed, where):
    if value not in allowed:
        raise PolicyError(f"{where}: {value!r} is not one of {list(allowed)}")
    return value


def _date(value, where):
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise PolicyError(f"{where}: expected YYYY-MM-DD ({exc})") from exc


def _merge(base, over):
    """Deep-merge `over` onto `base`. Dicts merge key by key; anything else replaces.

    Lists replace rather than concatenate, deliberately: a merged list of rules or
    surfaces would silently mean something nobody wrote, and this file's whole job is to
    refuse to guess.
    """
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base[k], v) if k in base else v
        return out
    return over


def load(policy_path, status_path=None, overlay_path=None):
    """-> Policy. Raises PolicyError on anything malformed or dangling.

    `overlay_path` is an optional gitignored file merged over the tracked one. It exists
    so the private file can hold ONLY what is private -- the real accounts -- instead of
    being a whole second copy of the policy. A copy drifts: it silently lost a vendor and
    two surfaces added to the tracked file, and the page was built from the stale one
    without saying so, which is the same failure as reading nothing and calling it zero.
    """
    raw = _read(policy_path)
    if overlay_path is not None:
        over = _read(overlay_path, allow_missing=True)
        if over is not None:
            if not isinstance(over, dict):
                raise PolicyError(f"{overlay_path}: an overlay must be a mapping")
            raw = _merge(raw, over)
    _keys(raw, {"version", "family", "kids", "rules", "surfaces"}, str(policy_path))
    if raw.get("version") != 1:
        raise PolicyError(f"{policy_path}: unsupported version {raw.get('version')!r}")

    kids = []
    for i, k in enumerate(_req(raw, "kids", str(policy_path))):
        w = f"kids[{i}]"
        _keys(k, {"id", "name", "accounts"}, w)
        accounts = {}
        for app, detail in (k.get("accounts") or {}).items():
            # A bare string is the username; a mapping may also carry the numeric id
            # some vendors route by. Roblox's screen-time page is addressed by id.
            if isinstance(detail, str):
                accounts[app] = {"username": detail}
            elif isinstance(detail, dict):
                _keys(detail, {"username", "id"}, f"{w}.accounts.{app}")
                accounts[app] = {"username": _req(detail, "username", f"{w}.accounts.{app}")}
                if "id" in detail:
                    if not isinstance(detail["id"], int) or isinstance(detail["id"], bool):
                        raise PolicyError(f"{w}.accounts.{app}.id: expected a whole number")
                    accounts[app]["id"] = detail["id"]
            else:
                raise PolicyError(f"{w}.accounts.{app}: expected a username or a mapping")
        kids.append(Kid(_req(k, "id", w), _req(k, "name", w), accounts))
    kid_ids = {k.id for k in kids}
    kid_by_id = {k.id: k for k in kids}
    _unique([k.id for k in kids], "kids")

    rules = []
    for i, r in enumerate(_req(raw, "rules", str(policy_path))):
        w = f"rules[{i}]"
        _keys(r, {"id", "kid", "kind", "app", "params"}, w)
        kid = _req(r, "kid", w)
        if kid not in kid_ids:
            raise PolicyError(f"{w}.kid: no kid called '{kid}'")
        kind = _one_of(_req(r, "kind", w), KINDS, f"{w}.kind")
        try:
            values = P.validate(kind, _req(r, "params", w), w)
        except P.ParamError as exc:
            raise PolicyError(str(exc)) from exc
        app = r.get("app", "")
        # The sentence is GENERATED, never authored, so it cannot drift from the
        # parameters the vendors are actually checked against.
        say = P.phrase(kind, values, kid_by_id[kid].short,
                       _app_label(app))
        rules.append(Rule(_req(r, "id", w), kid, kind, values, app, say))
    _unique([r.id for r in rules], "rules")

    surfaces = []
    for i, s in enumerate(_req(raw, "surfaces", str(policy_path))):
        w = f"surfaces[{i}]"
        _keys(s, {"id", "name", "covers", "can", "app", "account", "reach", "blind",
                  "link", "link_kind", "how", "redact", "recheck_days"}, w)
        for c in _req(s, "covers", w):
            if c not in kid_ids:
                raise PolicyError(f"{w}.covers: no kid called '{c}'")
        for c in _req(s, "can", w):
            _one_of(c, KINDS, f"{w}.can")
        link, link_kind = s.get("link", ""), s.get("link_kind", "")
        if link and not link_kind:
            raise PolicyError(
                f"{w}.link_kind: required whenever a link is given. There is no default, "
                "because the plausible default ('official') is the one that misleads.")
        if link_kind:
            _one_of(link_kind, LINK_KINDS, f"{w}.link_kind")
        how = _how(s, w)
        if link_kind == "unofficial" and not all(h.steps for h in how.values()):
            raise PolicyError(
                f"{w}: an unofficial link must never be the only route. Apple breaks "
                "these between releases; every `how` needs steps that stand alone.")
        surfaces.append(Surface(
            id=_req(s, "id", w), name=_req(s, "name", w),
            covers=tuple(s["covers"]), can=tuple(s["can"]),
            app=s.get("app", "*"), account=s.get("account", ""), how=how,
            reach=s.get("reach", ""), blind=s.get("blind", ""),
            link=link, link_kind=link_kind,
            redact=s.get("redact", ""), recheck_days=int(s.get("recheck_days", 60))))
    _unique([s.id for s in surfaces], "surfaces")

    records = _load_status(status_path, {r.id for r in rules},
                           {s.id for s in surfaces}) if status_path else ()
    return Policy(raw.get("family", "Family"), tuple(kids), tuple(rules),
                  tuple(surfaces), records)


def _load_status(path, rule_ids, surface_ids):
    try:
        raw = _read(path, allow_missing=True)
    except PolicyError:
        raise
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PolicyError(f"{path}: expected a list of records")
    out, seen = [], set()
    for i, rec in enumerate(raw):
        w = f"{path}[{i}]"
        _keys(rec, {"rule", "surface", "state", "date", "by", "evidence"}, w)
        rule, surface = _req(rec, "rule", w), _req(rec, "surface", w)
        if rule not in rule_ids:
            raise PolicyError(f"{w}.rule: no rule called '{rule}'")
        if surface not in surface_ids:
            raise PolicyError(f"{w}.surface: no surface called '{surface}'")
        if (rule, surface) in seen:
            raise PolicyError(f"{w}: duplicate record for {rule} × {surface}")
        seen.add((rule, surface))
        out.append(Record(rule, surface,
                          _one_of(_req(rec, "state", w), STATES, f"{w}.state"),
                          _date(_req(rec, "date", w), f"{w}.date"),
                          _req(rec, "by", w), rec.get("evidence", "")))
    return tuple(out)


def _app_label(app):
    """'' -> every screen; otherwise the app's own name, title-cased for the sentence."""
    return "screens" if not app else app.replace("-", " ").title()


def carries(rule, surface):
    """True when this surface is in scope for this rule.

    Three gates, all of which must hold: it reaches the child, it handles that kind of
    control, and it governs that app. The app gate is what stops a Roblox time limit
    from being routed at Netflix -- `*` means the surface works at the device or network
    level and governs everything on it.
    """
    return (rule.kid in surface.covers
            and rule.kind in surface.can
            and (not rule.app or surface.app in ("*", rule.app)))


def _how(raw, where):
    """-> {kind: How}. `can` and `how` must name exactly the same kinds.

    An app may not claim a capability without saying where the setting is. That rule is
    what keeps the catalog honest: every claim on the page is backed by a click-path
    somebody wrote down, and an unbacked claim fails the load rather than rendering as a
    confident empty promise.
    """
    blocks = raw.get("how") or {}
    if not isinstance(blocks, dict):
        raise PolicyError(f"{where}.how: expected a mapping of kind -> steps/check")
    claimed, described = set(raw.get("can") or ()), set(blocks)
    if claimed - described:
        raise PolicyError(
            f"{where}: claims {sorted(claimed - described)} in `can` but never says how. "
            "An app cannot claim a control without a click-path for it.")
    if described - claimed:
        raise PolicyError(
            f"{where}: has instructions for {sorted(described - claimed)} which is not "
            "in `can`. Add it to `can` or remove the instructions.")
    out = {}
    for kind, block in blocks.items():
        bw = f"{where}.how.{kind}"
        _one_of(kind, KINDS, bw)
        _keys(block, {"steps", "check", "options", "accepts", "recipe", "maps"}, bw)
        steps = _req(block, "steps", bw)
        if not isinstance(steps, list) or not steps:
            raise PolicyError(f"{bw}.steps: expected a non-empty list")
        accepts = tuple(block.get("accepts") or ())
        if not accepts:
            raise PolicyError(
                f"{bw}.accepts: required. An app cannot claim a '{kind}' control without "
                f"saying which of its parameters it can honour. Valid: "
                f"{sorted(P.PARAMS[kind])}")
        unknown = sorted(set(accepts) - set(P.PARAMS[kind]))
        if unknown:
            raise PolicyError(
                f"{bw}.accepts: {unknown} are not parameters of a '{kind}' rule. "
                f"Valid: {sorted(P.PARAMS[kind])}")
        # `maps` translates OUR vocabulary into this vendor's words, so the judge can
        # compare a page's label against a policy without knowing any vendor.
        maps = block.get("maps") or {}
        for ours in maps:
            for param, spec in P.PARAMS[kind].items():
                if spec["type"] == "enum" and ours not in spec["values"]:
                    raise PolicyError(
                        f"{bw}.maps: '{ours}' is not a value of {kind}.{param}. "
                        f"Valid: {list(spec['values'])}")
        out[kind] = How(tuple(steps), _req(block, "check", bw), block.get("options", ""),
                        accepts, block.get("recipe", ""), dict(maps))
    return out


def _read(path, allow_missing=False):
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise PolicyError(f"{path}: not found — refusing to assume an empty policy")
    except OSError as exc:
        raise PolicyError(f"cannot read {path}: {exc}") from exc
    try:
        return yaml.safe_load(blob.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise PolicyError(f"{path}: malformed — {exc}") from exc


def _unique(ids, label):
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise PolicyError(f"{label}: duplicate id(s) {dupes}")
