import sys
import os
import json
import time
import csv
from datetime import datetime

# Project root (engines/ -> root)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from Discovery.Android_discovery import AndroidDiscovery

import urllib.request


# ==========================
# AI TEST GENERATOR
# ==========================
def ai_generate_test_cases(discovery_result: dict) -> list:

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [AI] ANTHROPIC_API_KEY not found in .env — using rule-based tests")
        return _rule_based_tests(discovery_result)

    prompt = f"""
You are a mobile QA automation expert for Android apps.
Based on the scanned app elements below, generate test cases.

App Info:
- Package : {discovery_result.get('package')}
- Activity: {discovery_result.get('activity')}
- Inputs  : {json.dumps(discovery_result.get('input_details', []), indent=2)}
- Buttons : {json.dumps(discovery_result.get('button_details', []), indent=2)}
- Clickables: {json.dumps(discovery_result.get('clickable_details', [])[:10], indent=2)}

Return ONLY a JSON array. Each item must have:
{{
  "id": "TC001",
  "name": "short test name",
  "type": "input_validation | button_tap | navigation | form_submit | negative_test",
  "steps": [
    {{"action": "fill",   "target": "resource_id or hint", "value": "test value"}},
    {{"action": "tap",    "target": "resource_id or text"}},
    {{"action": "verify", "target": "element", "expect": "expected text or state"}}
  ],
  "priority": "high | medium | low"
}}

Generate up to 10 meaningful test cases. Return ONLY the JSON array.
"""

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw  = data["content"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
    except Exception as e:
        print(f"  [AI] Falling back to rule-based tests. Reason: {e}")
        return _rule_based_tests(discovery_result)


def _rule_based_tests(discovery_result: dict) -> list:
    tests   = []
    buttons = discovery_result.get("button_details", [])
    inputs  = discovery_result.get("input_details", [])

    if inputs and buttons:
        tests.append({
            "id": "TC001", "name": "Submit empty form", "type": "negative_test",
            "steps": [{"action": "tap", "target": buttons[0]["text"]}],
            "priority": "high"
        })
        steps = [
            {"action": "fill",
             "target": inp["resource_id"] or inp["hint"] or f"field_{i}",
             "value":  "testvalue"}
            for i, inp in enumerate(inputs)
        ]
        steps.append({"action": "tap", "target": buttons[0]["text"]})
        tests.append({
            "id": "TC002", "name": "Fill and submit form", "type": "form_submit",
            "steps": steps, "priority": "high"
        })

    for i, btn in enumerate(buttons[:5], start=3):
        tests.append({
            "id": f"TC{i:03d}", "name": f"Tap: {btn['text']}",
            "type": "button_tap",
            "steps": [{"action": "tap", "target": btn["text"]}],
            "priority": "medium"
        })
    return tests


# ==========================
# TEST RUNNER
# ==========================
class AndroidTestRunner:

    MAX_RETRIES = 2

    def __init__(self, driver):
        self.driver = driver

    def run_all(self, test_cases: list) -> list:
        results = []
        for tc in test_cases:
            print(f"\n  Running [{tc['id']}] {tc['name']} ...")
            result = self._run_with_retry(tc)
            results.append(result)
            print(f"  [{'PASS' if result['status'] == 'PASS' else 'FAIL'}] {tc['name']}")
        return results

    def _run_with_retry(self, tc: dict) -> dict:
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                self.driver.reset()
                time.sleep(1)
                self._execute_steps(tc["steps"])
                return {
                    "id": tc["id"], "name": tc["name"],
                    "type": tc["type"], "priority": tc["priority"],
                    "status": "PASS", "attempts": attempt,
                    "error": None, "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                last_error = str(e)
                if attempt <= self.MAX_RETRIES:
                    print(f"    Retry {attempt}/{self.MAX_RETRIES} ...")
                    time.sleep(1)

        return {
            "id": tc["id"], "name": tc["name"],
            "type": tc["type"], "priority": tc["priority"],
            "status": "FAIL", "attempts": self.MAX_RETRIES + 1,
            "error": last_error, "timestamp": datetime.now().isoformat(),
        }

    def _execute_steps(self, steps: list):
        from appium.webdriver.common.appiumby import AppiumBy

        for step in steps:
            action = step.get("action")
            target = step.get("target", "")
            value  = step.get("value", "")

            if action == "fill":
                el = self._find_element(target)
                el.clear()
                el.send_keys(value)
                time.sleep(0.3)

            elif action == "tap":
                el = self._find_element(target)
                el.click()
                time.sleep(0.5)

            elif action == "verify":
                expect = step.get("expect", "")
                source = self.driver.page_source
                if expect and expect.lower() not in source.lower():
                    raise AssertionError(f"Expected '{expect}' not found")

    def _find_element(self, target: str):
        from appium.webdriver.common.appiumby import AppiumBy
        for by, val in [
            (AppiumBy.ID,                target),
            (AppiumBy.ACCESSIBILITY_ID,  target),
            (AppiumBy.XPATH, f'//*[@text="{target}"]'),
            (AppiumBy.XPATH, f'//*[@content-desc="{target}"]'),
            (AppiumBy.XPATH, f'//*[@resource-id="{target}"]'),
            (AppiumBy.XPATH, f'//*[@hint="{target}"]'),
        ]:
            try:
                els = self.driver.find_elements(by, val)
                if els:
                    return els[0]
            except Exception:
                continue
        raise Exception(f"Element not found: {target}")


# ==========================
# BUG REPORTER
# ==========================
class BugReporter:

    def __init__(self, output_dir: str = "reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")

    def save(self, platform: str, target: str, test_results: list) -> dict:
        bugs   = [r for r in test_results if r["status"] == "FAIL"]
        passed = [r for r in test_results if r["status"] == "PASS"]

        summary = {
            "platform": platform, "target": target,
            "run_at":   self.timestamp,
            "total":    len(test_results),
            "passed":   len(passed),
            "failed":   len(bugs),
            "pass_rate": f"{round(len(passed)/max(len(test_results),1)*100,1)}%",
            "test_results": test_results,
            "bugs": bugs,
        }

        json_path = os.path.join(self.output_dir, f"{platform.lower()}_report_{self.timestamp}.json")
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n  [REPORT] JSON saved: {json_path}")

        csv_path = os.path.join(self.output_dir, f"{platform.lower()}_bugs_{self.timestamp}.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "name", "type", "priority", "status", "attempts", "error", "timestamp"
            ])
            writer.writeheader()
            writer.writerows(test_results)
        print(f"  [REPORT] CSV  saved: {csv_path}")

        return summary


# ==========================
# ANDROID ENGINE
# ==========================
class AndroidEngine:

    def execute(self, apk_path: str) -> dict:

        print("\n[ANDROID] Test Started")
        print(f"[ANDROID] Target: {apk_path}")

        discovery = AndroidDiscovery(apk_path)

        try:
            # PHASE 1 — Discovery
            print("\n--- Phase 1: Discovery ---")
            scan_result = discovery.scan()

            # PHASE 2 — AI Test Generation
            print("\n--- Phase 2: Generating Test Cases (AI + Rules) ---")
            test_cases = ai_generate_test_cases(scan_result)
            print(f"  Test Cases Generated: {len(test_cases)}")
            for tc in test_cases:
                print(f"    [{tc['id']}] {tc['name']} ({tc['priority']})")

            # PHASE 3 — Run Tests with Auto-Retry
            print("\n--- Phase 3: Running Tests (Auto-Retry on Failure) ---")
            runner  = AndroidTestRunner(discovery.driver)
            results = runner.run_all(test_cases)

            # PHASE 4 — Bug Report
            print("\n--- Phase 4: Saving Bug Report ---")
            reporter = BugReporter()
            summary  = reporter.save("ANDROID", apk_path, results)

            print(f"\n[ANDROID] Done — {summary['passed']}/{summary['total']} passed | "
                  f"{summary['failed']} bugs found")

            return {
                "status":    "COMPLETED",
                "platform":  "ANDROID",
                "target":    apk_path,
                "total":     summary["total"],
                "passed":    summary["passed"],
                "failed":    summary["failed"],
                "pass_rate": summary["pass_rate"],
            }

        except RuntimeError as e:
            print(f"\n[ANDROID ERROR] {e}")
            return {"status": "FAILED", "error": str(e), "apk": apk_path}

        except Exception as e:
            print(f"\n[ANDROID UNEXPECTED ERROR] {e}")
            return {"status": "FAILED", "error": str(e), "apk": apk_path}

        finally:
            discovery.close()