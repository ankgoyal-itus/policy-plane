"""Shared fixture paths. No logic -- if this file ever computes coverage, the evals
stop being independent evidence and become a second copy of the bug."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
REPO = ROOT.parent
TODAY = "2026-09-01"
MINI = FIXTURES / "mini-policy.yaml"
