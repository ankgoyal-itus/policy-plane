#!/usr/bin/env python3
"""Refuse to publish anything carrying private material.

Run against a FRESH CLONE, never the working copy. A working-copy scan reads
policy.local.yaml and observations.json -- which are gitignored and would never have
been published -- and either trips on files that were never at risk or, worse, passes
because it happened to look in the wrong place. What matters is what a stranger gets
when they clone.

    python3 scripts/leak_check.py --clone .            # clone HEAD and scan the clone
    python3 scripts/leak_check.py <dir>                # scan a directory as-is
    python3 scripts/leak_check.py --self-test          # prove the checker can fail

Exit status is 0 only when nothing was found. Findings print with the secret redacted:
a leak report that quotes the secret is itself a leak, and these get pasted around.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

# Files that must NEVER appear in a published tree, whatever they contain. Each is
# gitignored; this is the belt to that braces, because .gitignore protects nothing once
# a file has been `git add -f`'d or committed before the rule existed.
FORBIDDEN_PATHS = (
    "policy.local.yaml",
    "status.local.yaml",
    "observations.json",
    "docs/index.html",          # the rendered page bakes real params into data attributes
    "extension-key.pem",
    "key.pem",
)

# Shapes that are private regardless of value.
PATTERNS = (
    ("an email address", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("a home directory path", re.compile(r"/Users/[A-Za-z0-9._-]+")),
    ("a private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an AWS-shaped key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a bearer-ish token", re.compile(r"\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}\b")),
)

# Reserved, un-routable domains. RFC 2606 and RFC 6761 set these aside exactly so
# documentation and fixtures can show an address that can never reach a real person.
DOC_DOMAINS = (".invalid", ".example", ".test", ".localhost",
               "@example.com", "@example.org", "@example.net")

# Emails that are meant to be public. The noreply alias exists precisely so commits can
# carry an address without carrying the personal one.
ALLOWED_EMAILS = {
    "192280574+ankgoyal-itus@users.noreply.github.com",
    "ankit@ankitskgoyal.com",           # the published contact address
    "noreply@anthropic.com",
}

# Paths under /Users that are not anyone's home directory leaking into a file.
ALLOWED_PATH_PREFIXES = ()

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".js", ".json", ".yaml", ".yml", ".html", ".md", ".txt",
                 ".css", ".sh", ".toml", ".cfg", ".gitignore", ""}


def private_tokens():
    """-> {token: label}, harvested from the gitignored files on THIS machine.

    The checker holds no secrets of its own. It learns them from the private files at
    run time, which means it stays correct when those values change and stays safe to
    publish alongside the thing it checks.
    """
    tokens = {}

    def add(value, label):
        text = str(value).strip()
        # Below five characters the token is not distinctive and every scan becomes
        # noise -- "sam" would match "same".
        if len(text) >= 5:
            tokens[text] = label

    # What is private is exactly what the overlay CHANGES. A value identical to the
    # published placeholder is not a secret -- the real Roblox username here IS
    # "alex_example", and treating it as private made every copy of the placeholder in
    # the example policy and the fixtures look like a leak. Noise on that scale is how a
    # checker gets ignored, which is the failure mode that matters most.
    def accounts(path):
        try:
            import yaml
            doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except Exception:                                        # noqa: BLE001
            return {}
        out = {}
        for kid in doc.get("kids") or []:
            for app, acct in (kid.get("accounts") or {}).items():
                acct = {"username": acct} if isinstance(acct, str) else (acct or {})
                for field, value in acct.items():
                    out[(kid.get("id"), app, field)] = str(value)
        return out

    public = accounts(HERE / "policy.yaml")
    for key, value in accounts(HERE / "policy.local.yaml").items():
        if public.get(key) != value:
            add(value, f"the real {key[1]} {key[2]}")
    placeholders = set(public.values())

    obs = HERE / "observations.json"
    if obs.exists():
        try:
            for record in json.loads(obs.read_text(encoding="utf-8")) or []:
                for key, value in (record.get("params") or {}).items():
                    if str(value) not in placeholders:
                        add(value, f"a recorded {key}")
                url = record.get("url")
                if url:
                    for run in re.findall(r"\d{7,}", str(url)):
                        if run not in placeholders:
                            add(run, "an id from a recorded page URL")
        except Exception:                                        # noqa: BLE001
            pass

    return tokens


def redact(token):
    text = str(token)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


def scan_tree(root, tokens):
    findings = []
    root = Path(root)

    for rel in FORBIDDEN_PATHS:
        if (root / rel).exists():
            findings.append((rel, 0, f"{rel} must never be published"))

    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(p in SKIP_DIRS for p in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.suffix != "":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root)
        for lineno, line in enumerate(text.splitlines(), 1):
            findings += _scan_line(str(rel), lineno, line, tokens)
    return findings


def scan_history(repo, tokens):
    """Every commit on every ref, not just the tip.

    A file deleted in the last commit is still in the clone, and `git log -p --all` is
    the only view that shows it.
    """
    try:
        blob = subprocess.run(["git", "-C", str(repo), "log", "-p", "--all"],
                              capture_output=True, text=True, timeout=180).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return [("<history>", 0, f"could not read history: {exc}")]
    # Tokens are passed in, not re-derived. Calling private_tokens() per line re-parsed
    # policy.local.yaml and observations.json once for every line of every commit, and
    # turned a two-second scan into one that ran past two minutes -- slow enough that
    # the temptation is to skip the history scan, which is the half that matters most.
    findings = []
    for lineno, line in enumerate(blob.splitlines(), 1):
        findings += _scan_line("<git history>", lineno, line, tokens)
    return findings


def _scan_line(where, lineno, line, tokens):
    found = []
    for token, label in tokens.items():
        if token in line:
            found.append((where, lineno, f"{label} ({redact(token)})"))
    for label, pattern in PATTERNS:
        for hit in pattern.findall(line):
            if label == "an email address" and (
                    hit in ALLOWED_EMAILS
                    or any(hit.lower().endswith(d) or d in hit.lower()
                           for d in DOC_DOMAINS)):
                continue
            if label == "a home directory path" and hit.startswith(ALLOWED_PATH_PREFIXES):
                continue
            found.append((where, lineno, f"{label} ({redact(hit)})"))
    return found


def self_test():
    """Plant each kind of secret and confirm the checker fails on it.

    A leak checker that cannot fail is worse than no leak checker, because it
    manufactures confidence. This is the mutation test, run as part of the tool.
    """
    # Every planted secret is ASSEMBLED at run time rather than written out, so this
    # file does not itself contain a routable address, a home path, or a private-key
    # header. The first version wrote them literally -- and used the REAL child id as
    # its example token, which committed that id to two repositories. The gate caught
    # its own author, in the file whose entire job is to prevent exactly that.
    fake_id = "4" + "2" * 9                        # not anyone's id
    at = chr(64)
    cases = {
        "a private token": ("note.txt", f"child id {fake_id} lives here",
                            {fake_id: "a planted id"}),
        # A routable address, deliberately: example.com is reserved for documentation
        # and is allowed, so planting one there would have tested nothing. The self-test
        # caught exactly that when the doc-domain allowance was added.
        "an email address": ("note.txt", "contact someone" + at + "gmail.com", {}),
        "a home directory path": ("note.txt", "/Users" + "/someone/secrets", {}),
        "a private key block": ("note.txt", "-----BEGIN " + "RSA PRIVATE KEY-----", {}),
        "a forbidden file": ("observations.json", "[]", {}),
    }
    ok = True
    for name, (filename, body, tokens) in cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / filename).write_text(body, encoding="utf-8")
            findings = scan_tree(tmp, tokens)
            if findings:
                print(f"  caught  {name}")
            else:
                print(f"  MISSED  {name}  <-- the checker is blind to this")
                ok = False

    # And the converse. A checker that fails on everything is as useless as one that
    # fails on nothing, and it is the version people learn to ignore.
    clean = {
        "a clean tree passes": "nothing private here",
        "a documentation address is allowed":
            "write to parent" + at + "example.invalid",
        "the noreply alias is allowed":
            "192280574+ankgoyal-itus" + at + "users.noreply.github.com",
    }
    for name, body in clean.items():
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ok.txt").write_text(body, encoding="utf-8")
            if scan_tree(tmp, {fake_id: "a planted id"}):
                print(f"  MISSED  {name} -- flagged when it should not be")
                ok = False
            else:
                print(f"  passes  {name}")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="directory to scan")
    ap.add_argument("--clone", metavar="REPO",
                    help="clone REPO to a temp dir and scan that instead")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the checker can fail, then exit")
    args = ap.parse_args(argv)

    if args.self_test:
        print("self-test — planting secrets to prove the checker can fail:")
        return 0 if self_test() else 1

    tmpdir = None
    try:
        if args.clone:
            tmpdir = tempfile.mkdtemp(prefix="leakcheck-")
            target = Path(tmpdir) / "clone"
            subprocess.run(["git", "clone", "--quiet", args.clone, str(target)],
                           check=True)
            print(f"scanning a fresh clone of {args.clone}")
        elif args.target:
            target = Path(args.target)
        else:
            ap.error("give a directory, or --clone REPO, or --self-test")

        tokens = private_tokens()
        print(f"{len(tokens)} private token(s) learned from this machine's "
              "gitignored files")
        if not tokens:
            print("  WARNING: no private tokens were found to look for. If "
                  "policy.local.yaml exists, this scan is weaker than it looks.")

        findings = scan_tree(target, tokens)
        if (target / ".git").exists():
            findings += scan_history(target, tokens)

        if not findings:
            print("\nclean — nothing private found in the tree or the history")
            return 0
        print(f"\n{len(findings)} finding(s) — DO NOT PUBLISH\n")
        for where, lineno, what in findings:
            print(f"  {where}:{lineno}  {what}")
        return 1
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
