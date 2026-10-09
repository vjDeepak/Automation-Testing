import time
import os
import sys
from datetime import datetime, timedelta

from urllib.parse import urlparse as url_parse
from pathlib import Path

# ==========================
# CONSOLE ENCODING SAFETY NET
# Windows terminals (PowerShell/cmd) default to cp1252 ("charmap"),
# which cannot print many Unicode characters (e.g. "→"). Any print()
# anywhere in the app that hits such a character used to crash the
# ENTIRE run mid-test. Force UTF-8 on stdout/stderr here, once, at
# the single entry point, so this class of crash can't happen again.
# ==========================
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        # Very old Python without reconfigure() — safe to ignore
        pass

# Project root — where app.py lives
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


# ==========================
# INPUT DETECTOR
# ==========================
class InputDetector:

    @staticmethod
    def detect(target: str) -> dict:

        target = target.strip()

        # -----------------------------
        # WEB URL
        # -----------------------------
        if target.startswith(("http://", "https://")):

            parsed = url_parse(target)

            if parsed.scheme and parsed.netloc:

                return {
                    "status": True,
                    "platform": "WEB",
                    "engine": "web_engine",
                    "target": target
                }

        # -----------------------------
        # ANDROID APK
        # -----------------------------
        if target.lower().endswith(".apk"):

            if Path(target).suffix.lower() == ".apk":

                return {
                    "status": True,
                    "platform": "ANDROID",
                    "engine": "android_engine",
                    "target": target
                }

        # -----------------------------
        # IOS IPA
        # -----------------------------
        if target.lower().endswith(".ipa"):

            if Path(target).suffix.lower() == ".ipa":

                return {
                    "status": True,
                    "platform": "IOS",
                    "engine": "ios_engine",
                    "target": target
                }

        # -----------------------------
        # INVALID INPUT
        # -----------------------------
        return {
            "status": False,
            "platform": None,
            "engine": None,
            "target": target,
            "message": (
                "\n[ERROR] Invalid target.\n"
                "Supported formats:\n"
                "  • Web URL  : https://example.com\n"
                "  • Android  : C:\\Apps\\sample.apk\n"
                "  • iOS      : C:\\Apps\\sample.ipa"
            )
        }


# ==========================
# UNIVERSAL QA  —  app.py is the single lead controller
# ==========================
class UniversalQA:
    """
    Whatever target the user provides (URL / .apk / .ipa),
    this class detects the platform and drives the matching engine.
    No platform pre-selection needed — the target IS the instruction.
    """

    def __init__(self, target: str):
        self.target     = target.strip()
        self.platform   = None
        self.start_time = None

    # ==========================
    # ENGINE ROUTER (lazy imports — only loads what's actually needed)
    # ==========================
    def execute_engine(self, platform: str, target: str) -> dict:

        if platform == "WEB":
            from engines.web_engine import WebEngine
            return WebEngine().execute(target)

        if platform == "ANDROID":
            from engines.android_engine import AndroidEngine
            return AndroidEngine().execute(target)

        if platform == "IOS":
            from engines.ios_engine import IOSEngine
            return IOSEngine().execute(target)

        raise ValueError(f"No engine found for platform: {platform}")

    # ==========================
    # REPORT
    # ==========================
    def show_report(self, result: dict) -> None:

        execution_time = round(time.time() - self.start_time, 2)

        print("\n" + "=" * 50)
        print("AUTOMATION REPORT")
        print("=" * 50)
        print(f"Platform      : {self.platform}")
        print(f"Target        : {self.target}")
        print(f"Executed Time : {execution_time} seconds")
        print(f"Completed At  : {datetime.now()}")
        print("-" * 50)

        # These are rendered specially below, not via the generic loop,
        # since they're dicts/lists that don't read well as raw key:value
        SPECIAL_FIELDS = {
            "excel_report", "html_report", "categories", "regression",
            "jira_tickets_created", "crawl_flow", "pages_crawled",
        }

        for key, value in result.items():
            if key.endswith("_details") or key == "path_details":
                continue
            if key in SPECIAL_FIELDS:
                continue
            print(f"{key:<15}: {value}")

        if result.get("pages_crawled"):
            print("-" * 50)
            print(f"Pages Crawled : {result['pages_crawled']}")
            flow = result.get("crawl_flow", [])
            if flow:
                print(f"Flow          : {' -> '.join(flow)}")

        categories = result.get("categories")
        if categories:
            print("-" * 50)
            print(f"{'Category':<22} {'Pass':>5} {'Fail':>5}")
            for cat, counts in categories.items():
                print(f"{cat:<22} {counts.get('pass', 0):>5} {counts.get('fail', 0):>5}")

        regression = result.get("regression")
        if regression:
            print("-" * 50)
            print("Regression Summary (vs previous run):")
            if regression.get("has_baseline"):
                print(f"  Regressions      : {regression.get('regressions', 0)}")
                print(f"  New Failures     : {regression.get('new_failures', 0)}")
                print(f"  Still Failing    : {regression.get('still_failing', 0)}")
                print(f"  Fixed            : {regression.get('fixed', 0)}")
                print(f"  Missing From Run : {regression.get('missing_from_run', 0)}")
            else:
                print("  No baseline yet — this run becomes the baseline for next time.")

        jira_tickets = result.get("jira_tickets_created")
        if jira_tickets:
            print("-" * 50)
            print(f"Jira Tickets Created: {', '.join(jira_tickets)}")

        if result.get("excel_report"):
            print("-" * 50)
            print(f"Excel Report  : {result['excel_report']}")

        if result.get("html_report"):
            print(f"HTML Report   : {result['html_report']}")

        print("=" * 50)

    # ==========================
    # MAIN EXECUTION
    # ==========================
    def run(self) -> None:

        try:
            self.start_time = time.time()

            print("\n" + "=" * 50)
            print("UNIVERSAL QA PLATFORM")
            print("=" * 50)

            print(f"\nTarget Received:\n  {self.target}")

            print("\nDetecting Platform...")
            detection = InputDetector.detect(self.target)

            if not detection["status"]:
                print(f"\n[ERROR] {detection['message']}")
                return

            self.platform = detection["platform"]
            print(f"Platform Detected -> {self.platform}")

            print("\nStarting Automation...")
            output = self.execute_engine(self.platform, self.target)

            self.show_report(output)

        except ValueError as e:
            print(f"\n[CONFIG ERROR] {e}")

        except Exception as e:
            import traceback
            print(f"\n[EXECUTION FAILED] {type(e).__name__}: {e}")
            print("\n--- Full Traceback (for debugging) ---")
            traceback.print_exc()


# ==========================
# ENTRY POINT
# ==========================
def get_target() -> str:
    """
    Supports BOTH:
      1. Command line:  python app.py web_url_or_app_path
      2. Interactive prompt if no argument given
    """
    if len(sys.argv) > 1:
        return sys.argv[1]

    print("\n" + "=" * 50)
    print("UNIVERSAL QA PLATFORM")
    print("=" * 50)
    print("\nEnter a target to test:")
    print("  - Web URL    e.g. https://www.saucedemo.com/")
    print("  - Android    e.g. C:\\Apps\\sample.apk")
    print("  - iOS        e.g. C:\\Apps\\sample.ipa")
    Target = input("\nTarget > ").strip()

    if not Target:
        print("\n[ERROR] No target provided. Exiting.")
        sys.exit(1)

    return Target


if __name__ == "__main__":

    Target = get_target()
    qa = UniversalQA(Target)
    qa.run()