#!/usr/bin/env python3
"""Run the three suites. Non-zero exit if any fails."""
import sys
import unittest

SUITES = [("EVAL 1  coverage is never overstated", "evals.test_1_honest_coverage"),
          ("EVAL 2  define once", "evals.test_2_define_once"),
          ("EVAL 3  the page cannot lie", "evals.test_3_page_cannot_lie"),
          ("EVAL 4  one policy, many targets", "evals.test_4_translation"),
          ("EVAL 5  typed params, scoping, partial", "evals.test_5_parameters"),
          ("EVAL 6  the plane judges, the reader reads", "evals.test_6_judging")]

if __name__ == "__main__":
    failed = 0
    for label, mod in SUITES:
        print(f"\n=== {label} ===")
        result = unittest.TextTestRunner(verbosity=1).run(
            unittest.defaultTestLoader.loadTestsFromName(mod))
        failed += len(result.failures) + len(result.errors)
    print("\n" + ("all suites pass" if not failed else f"{failed} FAILING"))
    sys.exit(1 if failed else 0)
