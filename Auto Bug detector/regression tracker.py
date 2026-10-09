"""
Regression Tracker
===================
Keeps a rolling "baseline" of the last run's test results per platform
and compares each new run against it, so failures are classified as:

  - REGRESSION      : passed last time, fails now   <- the important one
  - NEW_FAILURE      : test didn't exist last time, fails now
  - STILL_FAILING    : failed last time too, still fails (known issue)
  - FIXED            : failed last time, passes now
  - UNCHANGED_PASS   : passed both times

Tests are matched across runs by their NAME (normalized), not their ID.
AI-generated test IDs (TC001, TC002...) are not stable between runs since
the AI can regenerate a different test set each time; the test name is
the closest thing to a stable identity available.

Place this file at: core/regression_tracker.py
"""
import os
import json
import re
from datetime import datetime


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


class RegressionTracker:

    def __init__(self, output_dir: str = "reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def _baseline_path(self, platform: str) -> str:
        return os.path.join(self.output_dir, f"baseline_{platform.lower()}.json")

    def load_baseline(self, platform: str) -> dict:
        """Returns {normalized_test_name: status} from the last saved run,
        or {} if no baseline exists yet (e.g. this is the first ever run)."""
        path = self._baseline_path(platform)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return data.get("results", {})
        except Exception:
            return {}

    def compare(self, platform: str, current_results: list) -> dict:
        """Compares current_results against the saved baseline.
        Does NOT overwrite the baseline — call save_baseline() separately
        once this run should become the new reference point."""
        baseline = self.load_baseline(platform)

        regressions    = []
        new_failures   = []
        still_failing  = []
        fixed          = []
        unchanged_pass = []

        seen_names = set()
        for r in current_results:
            key = _normalize(r.get("name"))
            seen_names.add(key)
            prev_status = baseline.get(key)
            curr_status = r.get("status")

            if prev_status == "PASS" and curr_status == "FAIL":
                regressions.append(r)
            elif prev_status is None and curr_status == "FAIL":
                new_failures.append(r)
            elif prev_status == "FAIL" and curr_status == "FAIL":
                still_failing.append(r)
            elif prev_status == "FAIL" and curr_status == "PASS":
                fixed.append(r)
            elif prev_status == "PASS" and curr_status == "PASS":
                unchanged_pass.append(r)
            # prev_status is None and curr_status == "PASS" -> brand new
            # passing test; not flagged, nothing wrong with it

        # Tests present in the baseline but absent from this run — could
        # mean a page/feature disappeared, or the AI just generated a
        # different test set this time. Flagged so a human can check.
        missing = [name for name in baseline if name not in seen_names]

        return {
            "regressions":      regressions,
            "new_failures":     new_failures,
            "still_failing":    still_failing,
            "fixed":            fixed,
            "unchanged_pass":   unchanged_pass,
            "missing_from_run": missing,
            "has_baseline":     bool(baseline),
        }

    def save_baseline(self, platform: str, current_results: list):
        """Overwrites the baseline with this run's results, so the NEXT
        run compares against THIS one."""
        results_map = {
            _normalize(r.get("name")): r.get("status")
            for r in current_results
        }
        path = self._baseline_path(platform)
        with open(path, "w") as f:
            json.dump({
                "saved_at": datetime.now().isoformat(),
                "results":  results_map,
            }, f, indent=2)

    @staticmethod
    def print_summary(regression_report: dict):
        if not regression_report["has_baseline"]:
            print("\n  [REGRESSION] No baseline yet — this run becomes "
                  "the baseline for next time.")
            return

        print("\n  " + "=" * 46)
        print("  REGRESSION REPORT (vs previous run)")
        print("  " + "=" * 46)

        regs = regression_report["regressions"]
        if regs:
            print(f"  REGRESSIONS ({len(regs)}) -- worked before, broken now:")
            for r in regs:
                print(f"     - {r['name']}")
        else:
            print("  No regressions -- nothing that passed before is failing now.")

        if regression_report["new_failures"]:
            print(f"\n  NEW FAILURES ({len(regression_report['new_failures'])}):")
            for r in regression_report["new_failures"]:
                print(f"     - {r['name']}")

        if regression_report["fixed"]:
            print(f"\n  FIXED SINCE LAST RUN ({len(regression_report['fixed'])}):")
            for r in regression_report["fixed"]:
                print(f"     - {r['name']}")

        if regression_report["missing_from_run"]:
            print(f"\n  MISSING FROM THIS RUN ({len(regression_report['missing_from_run'])}) "
                  f"-- existed in baseline, not seen this time:")
            for name in regression_report["missing_from_run"]:
                print(f"     - {name}")

        print("  " + "=" * 46)