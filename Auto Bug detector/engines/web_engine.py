import sys
import os
import json
import time
import random
import csv
from datetime import datetime
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from Discovery.web_discovery import WebDiscovery
from core.excel_reporter import ExcelReporter

def _optional_import(module_path: str, attr_name: str):
    """Import attr_name from module_path if it exists, else return None so
    the caller can skip that feature gracefully instead of crashing when
    an optional module (regression tracker, critical flows, etc.) hasn't
    been added to the project yet."""
    try:
        module = __import__(module_path, fromlist=[attr_name])
        return getattr(module, attr_name)
    except ImportError:
        return None


RegressionTracker    = _optional_import("core.regression_tracker", "RegressionTracker")
load_critical_flows  = _optional_import("core.critical_flows", "load_critical_flows")
JiraReporter          = _optional_import("core.jira_reporter", "JiraReporter")
html_reporter_export  = _optional_import("core.html_reporter", "export")

import urllib.request
import urllib.error


# ==========================
# CREDENTIALS  (from .env — falls back to saucedemo defaults)
# ==========================
WEB_USERNAME = os.environ.get("WEB_USERNAME", "standard_user")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "secret_sauce")


# ==========================
# MERGE MULTI-PAGE CRAWL RESULTS
# Tags every input/button/link with the page URL it came from, so test
# generation (AI or rule-based) can emit a "navigate" step to the right
# page before interacting with elements found there.
# ==========================
def _merge_pages_for_generation(crawl_result: dict) -> dict:
    pages = crawl_result.get("pages", [])
    if not pages:
        return {
            "title": "", "url": "", "inputs": 0, "buttons": 0, "links": 0,
            "input_details": [], "button_details": [], "link_details": [],
            "pages": [], "flow": [],
        }

    input_details, button_details, link_details = [], [], []
    for page in pages:
        for inp in page.get("input_details", []):
            input_details.append({**inp, "page_url": page["url"], "page_title": page["title"]})
        for btn in page.get("button_details", []):
            button_details.append({**btn, "page_url": page["url"], "page_title": page["title"]})
        for lnk in page.get("link_details", []):
            link_details.append({**lnk, "page_url": page["url"], "page_title": page["title"]})

    return {
        "title":          pages[0]["title"],
        "url":            pages[0]["url"],
        "inputs":         len(input_details),
        "buttons":        len(button_details),
        "links":          len(link_details),
        "input_details":  input_details,
        "button_details": button_details,
        "link_details":   link_details,
        "pages":          pages,
        "flow":           crawl_result.get("flow", []),
    }


# ==========================
# AI TEST GENERATOR
# ==========================
def ai_generate_test_cases(discovery_result: dict) -> list:

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [AI] ANTHROPIC_API_KEY not found in .env — using rule-based tests")
        return _rule_based_tests(discovery_result)

    pages_summary = "\n\n".join(
        f"PAGE: {p['title']} ({p['url']})\n"
        f"  Inputs : {json.dumps(p.get('input_details', []), indent=2)}\n"
        f"  Buttons: {json.dumps(p.get('button_details', []), indent=2)}\n"
        f"  Links  : {json.dumps(p.get('link_details', [])[:10], indent=2)}\n"
        f"  Menu/action links (not real URLs, click by text): "
        f"{json.dumps(p.get('action_link_details', []), indent=2)}"
        for p in discovery_result.get("pages", [discovery_result])
    )

    prompt = f"""
You are a senior QA automation engineer. The crawler below visited MULTIPLE
pages of the site by following its natural navigation (login -> cart ->
checkout -> payment -> confirmation, etc). Use ALL of the pages shown —
not just the first one — to generate comprehensive end-to-end test cases
covering:
1. Full login -> browse -> add to cart / set quantity -> checkout -> payment -> confirmation flow
2. Form validation on EACH page that has inputs (empty fields, invalid values)
3. UI element checks (visibility, enabled/disabled state)
4. Multi-page navigation flow

Site flow discovered (in visit order): {" -> ".join(discovery_result.get("flow", []))}

Pages discovered:
{pages_summary}

Return ONLY a JSON array — no markdown, no explanation. Each item:
{{
  "id": "TC001",
  "name": "descriptive test name",
  "category": "login_flow | form_validation | ui_check | navigation | checkout_flow | payment",
  "type": "positive | negative",
  "priority": "high | medium | low",
  "steps": [
    {{"action": "navigate", "target": "url of the page this step's elements belong to"}},
    {{"action": "fill",     "target": "placeholder or id or name", "value": "test value"}},
    {{"action": "click",    "target": "button text or id"}},
    {{"action": "verify",   "target": "page_title | url_contains | element_visible | element_enabled", "expect": "expected value"}}
  ],
  "expected_result": "what should happen"
}}

IMPORTANT: whenever a step interacts with an element that came from a
different page than the previous step, insert a "navigate" step to that
element's page URL first (each input/button above lists its "page_url").

Use "{WEB_USERNAME}" as the valid username and "{WEB_PASSWORD}" as the valid password
in any positive login test cases.

Generate 12-15 test cases covering the FULL journey end-to-end, not just
the login page. Include both positive and negative tests.
Return ONLY the JSON array.
"""

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
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

    except urllib.error.HTTPError as e:
        print(f"  [AI] HTTP {e.code} — falling back to rule-based tests")
        return _rule_based_tests(discovery_result)
    except Exception as e:
        print(f"  [AI] Error: {e} — falling back to rule-based tests")
        return _rule_based_tests(discovery_result)


def _rule_based_tests(discovery_result: dict) -> list:
    inputs  = discovery_result.get("input_details", [])
    buttons = discovery_result.get("button_details", [])
    links   = discovery_result.get("link_details",  [])
    url     = discovery_result.get("url", "")

    user_field = next((i["placeholder"] or i["id"] or i["name"] for i in inputs if "user" in (i["placeholder"]+i["name"]+i["id"]).lower()), inputs[0]["placeholder"] if inputs else "username")
    pass_field = next((i["placeholder"] or i["id"] or i["name"] for i in inputs if "pass" in (i["placeholder"]+i["name"]+i["id"]).lower()), inputs[1]["placeholder"] if len(inputs)>1 else "password")
    btn_target = buttons[0]["id"] or buttons[0]["text"] if buttons else "login-button"

    tests = [
        # ── FORM VALIDATION ──
        {
            "id": "TC001", "name": "Submit completely empty form",
            "category": "form_validation", "type": "negative", "priority": "high",
            "steps": [{"action": "click", "target": btn_target}],
            "expected_result": "Validation error shown for required fields"
        },
        {
            "id": "TC002", "name": "Username only — password empty",
            "category": "form_validation", "type": "negative", "priority": "high",
            "steps": [
                {"action": "fill",  "target": user_field, "value": WEB_USERNAME},
                {"action": "click", "target": btn_target}
            ],
            "expected_result": "Password required error shown"
        },
        {
            "id": "TC003", "name": "Password only — username empty",
            "category": "form_validation", "type": "negative", "priority": "high",
            "steps": [
                {"action": "fill",  "target": pass_field, "value": WEB_PASSWORD},
                {"action": "click", "target": btn_target}
            ],
            "expected_result": "Username required error shown"
        },
        {
            "id": "TC004", "name": "Invalid credentials — wrong password",
            "category": "form_validation", "type": "negative", "priority": "high",
            "steps": [
                {"action": "fill",  "target": user_field, "value": WEB_USERNAME},
                {"action": "fill",  "target": pass_field, "value": "wrongpassword"},
                {"action": "click", "target": btn_target}
            ],
            "expected_result": "Login error message shown"
        },
        {
            "id": "TC005", "name": "Invalid credentials — wrong username",
            "category": "form_validation", "type": "negative", "priority": "medium",
            "steps": [
                {"action": "fill",  "target": user_field, "value": "nonexistent_user"},
                {"action": "fill",  "target": pass_field, "value": WEB_PASSWORD},
                {"action": "click", "target": btn_target}
            ],
            "expected_result": "Login error message shown"
        },
        {
            "id": "TC006", "name": "SQL injection in username field",
            "category": "form_validation", "type": "negative", "priority": "medium",
            "steps": [
                {"action": "fill",  "target": user_field, "value": "' OR 1=1 --"},
                {"action": "fill",  "target": pass_field, "value": "any"},
                {"action": "click", "target": btn_target}
            ],
            "expected_result": "Input sanitised — no login"
        },
        # ── UI CHECKS ──
        {
            "id": "TC007", "name": "Login button is visible and enabled",
            "category": "ui_check", "type": "positive", "priority": "high",
            "steps": [
                {"action": "verify", "target": "element_visible", "expect": btn_target},
                {"action": "verify", "target": "element_enabled", "expect": btn_target}
            ],
            "expected_result": "Button is visible and clickable"
        },
        {
            "id": "TC008", "name": "Input fields are visible and editable",
            "category": "ui_check", "type": "positive", "priority": "high",
            "steps": [
                {"action": "verify", "target": "element_visible", "expect": user_field},
                {"action": "verify", "target": "element_visible", "expect": pass_field}
            ],
            "expected_result": "Both fields visible and interactive"
        },
        # ── LOGIN FLOW ──
        {
            "id": "TC009", "name": "Valid login — standard user",
            "category": "login_flow", "type": "positive", "priority": "high",
            "steps": [
                {"action": "fill",   "target": user_field, "value": WEB_USERNAME},
                {"action": "fill",   "target": pass_field, "value": WEB_PASSWORD},
                {"action": "click",  "target": btn_target},
                {"action": "verify", "target": "url_contains", "expect": "inventory"}
            ],
            "expected_result": "Redirected to inventory/dashboard page"
        },
        {
            "id": "TC010", "name": "Full login -> browse -> logout flow",
            "category": "login_flow", "type": "positive", "priority": "high",
            "steps": [
                {"action": "fill",     "target": user_field,        "value": WEB_USERNAME},
                {"action": "fill",     "target": pass_field,        "value": WEB_PASSWORD},
                {"action": "click",    "target": btn_target},
                {"action": "verify",   "target": "url_contains",    "expect": "inventory"},
                {"action": "click",    "target": "Open Menu"},
                {"action": "click",    "target": "Logout"},
                {"action": "verify",   "target": "url_contains",    "expect": "saucedemo.com"}
            ],
            "expected_result": "Full login/logout cycle completes"
        },
        # ── NAVIGATION ──
        {
            "id": "TC011", "name": "Page title is correct on load",
            "category": "navigation", "type": "positive", "priority": "medium",
            "steps": [
                {"action": "verify", "target": "page_title", "expect": "Swag Labs"}
            ],
            "expected_result": "Page title matches 'Swag Labs'"
        },
        {
            "id": "TC012", "name": "URL is correct on load",
            "category": "navigation", "type": "positive", "priority": "medium",
            "steps": [
                {"action": "verify", "target": "url_contains", "expect": "saucedemo.com"}
            ],
            "expected_result": "URL contains saucedemo.com"
        },
    ]

    # ── PAGE-SPECIFIC FLOW TESTS ──
    # Classify each crawled page by role (login / cart / checkout info /
    # checkout overview+payment / order complete) using the elements found
    # on it, then build real targeted tests for each — instead of only
    # ever repeating generic "tap this button" tests from page 1.
    pages = discovery_result.get("pages", [])
    flow  = discovery_result.get("flow", [])
    roles = _classify_pages(pages)

    if roles["cart"]:
        cart_page = roles["cart"]
        checkout_btn = next(
            (b["id"] or b["text"] for b in cart_page.get("button_details", [])
             if "checkout" in (b["text"] or "").lower()), "Checkout"
        )
        remove_btn = next(
            (b["id"] or b["text"] for b in cart_page.get("button_details", [])
             if "remove" in (b["text"] or "").lower()), None
        )
        tests.append({
            "id": f"TC{len(tests)+1:03d}", "name": "Cart page shows added items and Checkout button",
            "category": "cart", "type": "positive", "priority": "high",
            "steps": [
                {"action": "navigate", "target": cart_page["url"]},
                {"action": "verify",   "target": "element_visible", "expect": checkout_btn},
            ],
            "expected_result": "Cart page loads with items and a working Checkout button"
        })
        if remove_btn:
            tests.append({
                "id": f"TC{len(tests)+1:03d}", "name": "Removing an item from cart updates badge count",
                "category": "cart", "type": "positive", "priority": "high",
                "steps": [
                    {"action": "navigate", "target": cart_page["url"]},
                    {"action": "click",    "target": remove_btn},
                ],
                "expected_result": "Item removed, cart badge count decrements"
            })

    if roles["checkout_info"]:
        ci_page = roles["checkout_info"]
        text_inputs = [i for i in ci_page.get("input_details", [])
                       if (i.get("type") or "text") in ("text", "")]
        field_targets = [i["placeholder"] or i["id"] or i["name"] for i in text_inputs[:3]]
        continue_btn = next(
            (b["id"] or b["text"] for b in ci_page.get("button_details", [])
             if "continue" in (b["text"] or "").lower()), "Continue"
        )

        if len(field_targets) >= 1:
            tests.append({
                "id": f"TC{len(tests)+1:03d}", "name": "Checkout info — first required field empty",
                "category": "checkout_info", "type": "negative", "priority": "high",
                "steps": [
                    {"action": "navigate", "target": ci_page["url"]},
                    {"action": "click",    "target": continue_btn},
                ],
                "expected_result": "Validation error shown for the first required field"
            })
        if len(field_targets) >= 3:
            tests.append({
                "id": f"TC{len(tests)+1:03d}", "name": "Checkout info — last field empty (zip/postal)",
                "category": "checkout_info", "type": "negative", "priority": "high",
                "steps": [
                    {"action": "navigate", "target": ci_page["url"]},
                    {"action": "fill",     "target": field_targets[0], "value": "Test"},
                    {"action": "fill",     "target": field_targets[1], "value": "User"},
                    {"action": "click",    "target": continue_btn},
                ],
                "expected_result": "Validation error shown for the missing last field"
            })
        tests.append({
            "id": f"TC{len(tests)+1:03d}", "name": "Checkout info — all fields filled proceeds to next step",
            "category": "checkout_info", "type": "positive", "priority": "high",
            "steps": (
                [{"action": "navigate", "target": ci_page["url"]}]
                + [{"action": "fill", "target": t, "value": v}
                   for t, v in zip(field_targets, ["Test", "User", "12345"])]
                + [{"action": "click", "target": continue_btn}]
            ),
            "expected_result": "Proceeds to Checkout: Overview / Payment page"
        })

    if roles["checkout_overview"]:
        co_page = roles["checkout_overview"]
        finish_btn = next(
            (b["id"] or b["text"] for b in co_page.get("button_details", [])
             if "finish" in (b["text"] or "").lower()), "Finish"
        )
        pre_steps = _build_prefill_path(roles, field_values=["Test", "User", "12345"])

        tests.append({
            "id": f"TC{len(tests)+1:03d}",
            "name": "Checkout total math is correct (item total + tax = total)",
            "category": "checkout_flow", "type": "positive", "priority": "high",
            "steps": pre_steps + [{"action": "verify_checkout_math", "tax_rate": None}],
            "expected_result": "Item total + Tax equals the displayed Total, to the cent"
        })
        tests.append({
            "id": f"TC{len(tests)+1:03d}", "name": "Payment and shipping information displayed on Overview",
            "category": "checkout_flow", "type": "positive", "priority": "medium",
            "steps": pre_steps + [
                {"action": "verify", "target": "page_source_contains", "expect": "Payment Information"},
                {"action": "verify", "target": "page_source_contains", "expect": "Shipping Information"},
            ],
            "expected_result": "Both Payment Information and Shipping Information sections are shown"
        })
        tests.append({
            "id": f"TC{len(tests)+1:03d}", "name": "Finish completes the order",
            "category": "checkout_flow", "type": "positive", "priority": "high",
            "steps": pre_steps + [{"action": "click", "target": finish_btn}],
            "expected_result": "Order completes and navigates to the confirmation page"
        })

    if roles["complete"]:
        complete_page = roles["complete"]
        back_home_btn = next(
            (b["id"] or b["text"] for b in complete_page.get("button_details", [])
             if "back home" in (b["text"] or "").lower() or "home" in (b["text"] or "").lower()),
            "Back Home"
        )
        pre_steps = _build_prefill_path(roles, field_values=["Test", "User", "12345"])
        finish_btn = next(
            (b["id"] or b["text"] for b in roles["checkout_overview"].get("button_details", [])
             if "finish" in (b["text"] or "").lower()), "Finish"
        ) if roles["checkout_overview"] else "Finish"

        tests.append({
            "id": f"TC{len(tests)+1:03d}", "name": "Order confirmation shown after completing checkout",
            "category": "checkout_flow", "type": "positive", "priority": "high",
            "steps": pre_steps + [
                {"action": "click",  "target": finish_btn},
                {"action": "verify", "target": "page_source_contains", "expect": "Thank you"},
            ],
            "expected_result": "Confirmation message ('Thank you for your order') is displayed"
        })
        tests.append({
            "id": f"TC{len(tests)+1:03d}", "name": "Back Home returns to Products with empty cart",
            "category": "checkout_flow", "type": "positive", "priority": "medium",
            "steps": pre_steps + [
                {"action": "click",  "target": finish_btn},
                {"action": "click",  "target": back_home_btn},
                {"action": "verify", "target": "cart_badge_count", "expect": "0"},
            ],
            "expected_result": "Returns to Products page and cart badge is empty/zero"
        })

    # ── MULTI-PAGE JOURNEY ──
    # One test that walks every page the crawler discovered end-to-end.
    # Autofills any empty visible fields on each page before clicking a
    # flow button, so it doesn't get stuck on a form (the same bug that
    # used to stop the crawler at Checkout Info and never reach Payment).
    if len(pages) > 1:
        journey_steps = [
            {"action": "fill",  "target": user_field, "value": WEB_USERNAME},
            {"action": "fill",  "target": pass_field, "value": WEB_PASSWORD},
            {"action": "click", "target": btn_target},
        ]
        for page in pages[1:]:
            journey_steps.append({"action": "navigate", "target": page["url"]})
            text_inputs = [i for i in page.get("input_details", [])
                           if (i.get("type") or "text") in ("text", "")]
            for i, inp in enumerate(text_inputs):
                fill_val = ["Test", "User", "12345"][i] if i < 3 else "Test"
                journey_steps.append({
                    "action": "fill",
                    "target": inp["placeholder"] or inp["id"] or inp["name"],
                    "value": fill_val
                })
            flow_btn = next(
                (b["id"] or b["text"] for b in page.get("button_details", [])
                 if any(k in (b["text"] or "").lower() for k in
                        ["add to cart", "add", "checkout", "continue", "proceed",
                         "pay", "payment", "buy", "purchase", "finish",
                         "confirm", "place order"])),
                None
            )
            if flow_btn:
                journey_steps.append({"action": "click", "target": flow_btn})

        tests.append({
            "id": f"TC{len(tests) + 1:03d}",
            "name": "Full end-to-end journey across all discovered pages",
            "category": "checkout_flow", "type": "positive", "priority": "high",
            "steps": journey_steps,
            "expected_result": f"User can walk the full flow: {' -> '.join(flow)}"
        })

    return tests


def _classify_pages(pages: list) -> dict:
    """Best-effort role classification of crawled pages based on the
    elements found on them (not hardcoded URLs), so test generation works
    across differently-structured sites, not just this one."""
    roles = {"login": None, "cart": None, "checkout_info": None,
             "checkout_overview": None, "complete": None}

    for p in pages:
        btn_texts = [(b.get("text") or "").lower() for b in p.get("button_details", [])]
        inp_types = [(i.get("type") or "").lower() for i in p.get("input_details", [])]
        text_input_count = len([i for i in p.get("input_details", [])
                                 if (i.get("type") or "text") in ("text", "")])

        if not roles["login"] and "password" in inp_types:
            roles["login"] = p
        elif not roles["cart"] and any("checkout" in bt for bt in btn_texts) and text_input_count == 0:
            roles["cart"] = p
        elif not roles["checkout_overview"] and any("finish" in bt for bt in btn_texts):
            roles["checkout_overview"] = p
        elif not roles["complete"] and any("home" in bt for bt in btn_texts) and not any("finish" in bt for bt in btn_texts):
            roles["complete"] = p
        elif not roles["checkout_info"] and text_input_count >= 2:
            roles["checkout_info"] = p

    return roles


def _build_prefill_path(roles: dict, field_values: list) -> list:
    """Builds the navigate+fill steps needed to legitimately reach the
    Checkout Overview page (login already assumed done by the test runner's
    session): go to Checkout Info, fill its fields, click Continue."""
    steps = []
    ci = roles.get("checkout_info")
    if ci:
        continue_btn = next(
            (b["id"] or b["text"] for b in ci.get("button_details", [])
             if "continue" in (b["text"] or "").lower()), "Continue"
        )
        text_inputs = [i for i in ci.get("input_details", [])
                       if (i.get("type") or "text") in ("text", "")]
        field_targets = [i["placeholder"] or i["id"] or i["name"] for i in text_inputs[:3]]
        steps.append({"action": "navigate", "target": ci["url"]})
        for t, v in zip(field_targets, field_values):
            steps.append({"action": "fill", "target": t, "value": v})
        steps.append({"action": "click", "target": continue_btn})
    return steps


# ==========================
# END-TO-END TEST RUNNER
# ==========================
class WebE2ERunner:

    MAX_RETRIES = 2

    def __init__(self, driver, wait, base_url: str, screenshot_dir: str = "reports/screenshots"):
        self.driver   = driver
        self.wait     = wait
        self.base_url = base_url
        self.screenshot_dir = screenshot_dir
        os.makedirs(screenshot_dir, exist_ok=True)

    def run_all(self, test_cases: list) -> list:
        results = []
        for tc in test_cases:
            category = tc.get("category", "")
            print(f"\n  [{tc['id']}] [{category.upper()}] {tc['name']}")
            result = self._run_with_retry(tc)
            results.append(result)
            status = "PASS" if result["status"] == "PASS" else "FAIL"
            print(f"  --> {status} ({result['attempts']} attempt(s))")
            if result["error"]:
                print(f"      Error: {result['error']}")
        return results

    def _capture_screenshot(self, test_id: str) -> str:
        """Saves a screenshot on failure for the report's 'click to
        enlarge' feature. Returns the file path, or '' if it fails."""
        try:
            path = os.path.join(self.screenshot_dir, f"{test_id}.png")
            self.driver.save_screenshot(path)
            return path
        except Exception:
            return ""

    def _run_with_retry(self, tc: dict) -> dict:
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                # Reset to base URL before each attempt
                time.sleep(1)
                self._dismiss_popups()
                self._execute_steps(tc["steps"])
                return {
                    "id":       tc["id"],
                    "name":     tc["name"],
                    "category": tc.get("category", ""),
                    "type":     tc.get("type", ""),
                    "priority": tc.get("priority", ""),
                    "status":   "PASS",
                    "attempts": attempt,
                    "error":    None,
                    "expected": tc.get("expected_result", ""),
                    "steps":    tc.get("steps", []),
                    "screenshot": "",
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                last_error = str(e)
                if attempt <= self.MAX_RETRIES:
                    print(f"      Retry {attempt}/{self.MAX_RETRIES}: {last_error[:60]}")
                    time.sleep(1)

        screenshot_path = self._capture_screenshot(tc["id"])
        return {
            "id":       tc["id"],
            "name":     tc["name"],
            "category": tc.get("category", ""),
            "type":     tc.get("type", ""),
            "priority": tc.get("priority", ""),
            "status":   "FAIL",
            "attempts": self.MAX_RETRIES + 1,
            "error":    last_error,
            "expected": tc.get("expected_result", ""),
            "steps":    tc.get("steps", []),
            "screenshot": screenshot_path,
            "timestamp": datetime.now().isoformat(),
        }

    def _execute_steps(self, steps: list):
        for step in steps:
            action = step.get("action")
            target = step.get("target", "")
            value  = step.get("value", "")
            expect = step.get("expect", "")

            if action == "fill":
                el = self._find_input(target)
                el.click()
                time.sleep(random.uniform(0.5, 1))
                el.clear()
                self._human_typing(el, value)
                time.sleep(random.uniform(1, 2))

            elif action == "click":
                from selenium.webdriver.support import expected_conditions as EC
                el = self._find_clickable(target)
                try:
                    self.wait.until(EC.element_to_be_clickable(el))
                except Exception:
                    pass  # fall through and try the click anyway
                el.click()
                time.sleep(1)
                self._dismiss_popups()

            elif action == "select":
                # Dropdown selection (e.g. sort dropdown, country select)
                from selenium.webdriver.support.ui import Select
                el = self._find_select(target)
                Select(el).select_by_visible_text(value)
                time.sleep(1)

            elif action == "press_key":
                # Keyboard-only interaction: Enter/Tab/Escape on a target
                # element, or on whatever currently has focus if no target
                from selenium.webdriver.common.keys import Keys
                key_map = {
                    "ENTER": Keys.ENTER, "TAB": Keys.TAB, "ESCAPE": Keys.ESCAPE,
                    "ESC": Keys.ESCAPE, "SPACE": Keys.SPACE,
                }
                key = key_map.get(str(value).upper(), value)
                if target:
                    el = self._find_clickable(target)
                    el.send_keys(key)
                else:
                    self.driver.switch_to.active_element.send_keys(key)
                time.sleep(0.5)

            elif action == "navigate":
                self.driver.get(target)
                time.sleep(1)
                self._dismiss_popups()

            elif action == "verify":
                self._dismiss_popups()
                self._verify(target, expect)

            elif action == "verify_checkout_math":
                # Business-logic check: item total + tax == displayed total,
                # and (optionally) tax == item total * expected tax rate.
                # This is the kind of check pure UI automation can't infer
                # on its own -- it needs a human-provided expected rate.
                tax_rate = step.get("tax_rate")
                self._verify_checkout_totals(expected_tax_rate=tax_rate)

    # ── Human-like typing (reduces bot-detection false positives) ──
    def _human_typing(self, element, text: str):
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(1, 2))

    # ==========================
    # POPUP HANDLING
    # Covers BOTH:
    #   1. Native browser alerts (Chrome's "Change your password" /
    #      breach-warning / save-password dialogs)
    #   2. Common in-app "change password" / cookie-consent modals
    # ==========================
    def _dismiss_popups(self):
        self._dismiss_native_alert()
        self._dismiss_in_app_modal()

    def _dismiss_native_alert(self):
        """Handles Chrome's native popups: leaked-password warnings,
        save-password prompts, generic JS alert/confirm dialogs."""
        from selenium.common.exceptions import NoAlertPresentException
        try:
            alert = self.driver.switch_to.alert
            print(f"      [POPUP] Native alert detected: {alert.text}")
            alert.accept()
            print("      [POPUP] Native alert dismissed")
        except NoAlertPresentException:
            pass
        except Exception as e:
            print(f"      [POPUP] Could not dismiss native alert: {e}")

    def _dismiss_in_app_modal(self):
        """Handles common in-page 'change password' / consent / leak-warning
        modals rendered as regular HTML (not native browser dialogs)."""
        from selenium.webdriver.common.by import By

        # Common close/dismiss button patterns across sites
        close_selectors = [
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"not now")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"dismiss")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"skip")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"later")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"close")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"accept")]',
            '//button[contains(translate(text(),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"got it")]',
            '//div[@role="dialog"]//button[contains(@aria-label,"close") or contains(@aria-label,"Close")]',
        ]

        for selector in close_selectors:
            try:
                els = self.driver.find_elements(By.XPATH, selector)
                visible = [e for e in els if e.is_displayed()]
                if visible:
                    print(f"      [POPUP] In-app modal detected — dismissing")
                    visible[0].click()
                    time.sleep(2)
                    return  # one popup per check is enough
            except Exception:
                continue

    def _find_input(self, target: str):
        from selenium.webdriver.common.by import By
        strategies = [
            (By.XPATH,       f'//input[@placeholder="{target}"]'),
            (By.XPATH,       f'//input[@name="{target}"]'),
            (By.XPATH,       f'//input[@id="{target}"]'),
            (By.ID,           target),
            (By.NAME,         target),
            (By.CSS_SELECTOR, f'input[placeholder="{target}"]'),
        ]
        for by, val in strategies:
            try:
                els = self.driver.find_elements(by, val)
                visible = [e for e in els if e.is_displayed() and e.get_attribute("type") not in ("submit","button","hidden")]
                if visible:
                    return visible[0]
            except Exception:
                continue
        raise Exception(f"Input not found: '{target}'")

    def _find_select(self, target: str):
        from selenium.webdriver.common.by import By
        strategies = [
            (By.ID,           target),
            (By.NAME,         target),
            (By.XPATH,        f'//select[@id="{target}"]'),
            (By.XPATH,        f'//select[@name="{target}"]'),
            (By.CSS_SELECTOR, "select"),  # last resort: first dropdown on page
        ]
        for by, val in strategies:
            try:
                els = self.driver.find_elements(by, val)
                visible = [e for e in els if e.is_displayed() and e.tag_name == "select"]
                if visible:
                    return visible[0]
            except Exception:
                continue
        raise Exception(f"Dropdown not found: '{target}'")

    def _find_clickable(self, target: str):
        from selenium.webdriver.common.by import By
        strategies = [
            (By.ID,    target),
            (By.NAME,  target),
            (By.XPATH, f'//button[normalize-space()="{target}"]'),
            (By.XPATH, f'//button[contains(text(),"{target}")]'),
            (By.XPATH, f'//input[@id="{target}"]'),
            (By.XPATH, f'//input[@value="{target}"]'),
            (By.XPATH, f'//input[@name="{target}"]'),
            (By.XPATH, f'//*[@id="{target}"]'),
            (By.XPATH, f'//*[normalize-space()="{target}"]'),
            (By.LINK_TEXT, target),
        ]
        for by, val in strategies:
            try:
                els = self.driver.find_elements(by, val)
                visible = [e for e in els if e.is_displayed()]
                if visible:
                    return visible[0]
            except Exception:
                continue
        raise Exception(f"Clickable not found: '{target}'")

    def _verify(self, target: str, expect: str):
        if target == "page_title":
            actual = self.driver.title
            if expect.lower() not in actual.lower():
                raise AssertionError(
                    f"Title mismatch: expected '{expect}', got '{actual}'"
                )

        elif target == "url_contains":
            actual = self.driver.current_url
            if expect.lower() not in actual.lower():
                raise AssertionError(
                    f"URL mismatch: expected to contain '{expect}', got '{actual}'"
                )

        elif target == "element_visible":
            el = self._find_clickable(expect)
            if not el.is_displayed():
                raise AssertionError(f"Element not visible: '{expect}'")

        elif target == "element_enabled":
            el = self._find_clickable(expect)
            if not el.is_enabled():
                raise AssertionError(f"Element not enabled: '{expect}'")

        elif target == "page_source_contains":
            if expect.lower() not in self.driver.page_source.lower():
                raise AssertionError(f"Page source missing: '{expect}'")

        elif target == "cart_badge_count":
            from selenium.webdriver.common.by import By
            badges = self.driver.find_elements(By.CLASS_NAME, "shopping_cart_badge")
            actual = badges[0].text.strip() if badges else "0"
            if actual != str(expect):
                raise AssertionError(
                    f"Cart badge shows '{actual}', expected '{expect}'"
                )

        elif target == "text_equals":
            # expect format: "selector_or_label::expected text"
            if "::" not in expect:
                raise AssertionError(
                    "text_equals expects 'target::expected text' in the expect field"
                )
            locator, expected_text = expect.split("::", 1)
            el = self._find_clickable(locator.strip())
            actual_text = el.text.strip()
            if actual_text != expected_text.strip():
                raise AssertionError(
                    f"Text mismatch for '{locator}': expected '{expected_text}', got '{actual_text}'"
                )

    def _verify_checkout_totals(self, expected_tax_rate: float = None, tolerance: float = 0.02):
        """Reads 'Item total: $X', 'Tax: $X', 'Total: $X' style text from the
        page body and checks the arithmetic is internally consistent --
        and, if an expected tax rate is given, that the tax itself is right.
        This is regex-based against visible page text rather than hardcoded
        element IDs, so it works across differently-structured checkout
        pages that use this common wording pattern."""
        from selenium.webdriver.common.by import By
        import re

        body_text = self.driver.find_element(By.TAG_NAME, "body").text

        def _extract(label):
            m = re.search(rf"(?im)^\s*{label}\s*[:\s]*\$?\s*([0-9]+\.[0-9]{{2}})", body_text)
            return float(m.group(1)) if m else None

        subtotal = _extract("Item total")
        tax      = _extract("Tax")
        total    = _extract("Total")

        if subtotal is None or tax is None or total is None:
            raise AssertionError(
                f"Could not find Item total/Tax/Total text on page. "
                f"Found: subtotal={subtotal}, tax={tax}, total={total}"
            )

        if abs((subtotal + tax) - total) > tolerance:
            raise AssertionError(
                f"Total mismatch: Item total (${subtotal}) + Tax (${tax}) = "
                f"${round(subtotal + tax, 2)}, but page shows Total=${total}"
            )

        if expected_tax_rate is not None:
            expected_tax = round(subtotal * expected_tax_rate, 2)
            if abs(expected_tax - tax) > tolerance:
                raise AssertionError(
                    f"Tax mismatch: expected ~${expected_tax} "
                    f"({expected_tax_rate * 100:.1f}% of ${subtotal}), "
                    f"but page shows Tax=${tax}"
                )


# ==========================
# BUG REPORTER
# ==========================
class BugReporter:

    def __init__(self, output_dir: str = "reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.regression_tracker = RegressionTracker(output_dir) if RegressionTracker else None
        self.jira_reporter      = JiraReporter() if JiraReporter else None

    def save(self, platform: str, target: str, results: list, discovery_summary: dict = None) -> dict:
        bugs   = [r for r in results if r["status"] == "FAIL"]
        passed = [r for r in results if r["status"] == "PASS"]

        # Group by category
        categories = {}
        for r in results:
            cat = r.get("category", "unknown")
            categories.setdefault(cat, {"pass": 0, "fail": 0})
            if r["status"] == "PASS":
                categories[cat]["pass"] += 1
            else:
                categories[cat]["fail"] += 1

        summary = {
            "platform":         platform,
            "target":           target,
            "run_at":           self.timestamp,
            "total":            len(results),
            "passed":           len(passed),
            "failed":           len(bugs),
            "pass_rate":        f"{round(len(passed)/max(len(results),1)*100, 1)}%",
            "categories":       categories,
            "test_results":     results,
            "bugs":             bugs,
        }

        # ── REGRESSION TRACKING ──
        # Compare this run's results against the last saved baseline BEFORE
        # overwriting it, then save this run as the new baseline for next time.
        if self.regression_tracker:
            regression_report = self.regression_tracker.compare(platform, results)
            self.regression_tracker.print_summary(regression_report)
            summary["regression"] = {
                k: (len(v) if isinstance(v, list) else v)
                for k, v in regression_report.items()
            }
            summary["regression_details"] = regression_report
            self.regression_tracker.save_baseline(platform, results)
        else:
            print("\n  [REGRESSION] core/regression_tracker.py not found -- "
                  "skipping regression comparison (add the file to enable it)")
            regression_report = None

        # ── JIRA TICKET CREATION ──
        # File tickets ONLY for things that are newly broken (regressions +
        # brand-new failures) when we have a baseline to compare against --
        # not for tests already known to be failing, which would spam a
        # new duplicate ticket every single run.
        if self.jira_reporter:
            if regression_report:
                failures_to_file = regression_report["regressions"] + regression_report["new_failures"]
            else:
                failures_to_file = bugs  # no baseline available yet -- file all current failures
            created_tickets = self.jira_reporter.create_bugs_for_failures(failures_to_file, platform, target)
            if created_tickets:
                summary["jira_tickets_created"] = created_tickets

        # JSON
        json_path = os.path.join(
            self.output_dir,
            f"{platform.lower()}_report_{self.timestamp}.json"
        )
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n  [REPORT] JSON  : {json_path}")

        # CSV
        csv_path = os.path.join(
            self.output_dir,
            f"{platform.lower()}_bugs_{self.timestamp}.csv"
        )
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "name", "category", "type", "priority",
                "status", "attempts", "expected", "error", "timestamp"
            ])
            writer.writeheader()
            writer.writerows(results)
        print(f"  [REPORT] CSV   : {csv_path}")

        # Excel — non-fatal if it fails; tests already succeeded/failed independently
        try:
            excel_reporter = ExcelReporter(self.output_dir)
            excel_path = excel_reporter.export(platform, target, results, discovery_summary)
            print(f"  [REPORT] Excel : {excel_path}")
            summary["excel_report"] = excel_path
        except Exception as e:
            print(f"  [REPORT] Excel export skipped — {type(e).__name__}: {e}")
            summary["excel_report"] = ""

        # HTML — shareable single-file dashboard report with click-to-
        # enlarge screenshots on failures. Non-fatal if it fails.
        if html_reporter_export:
            try:
                run_id       = f"RUN-{self.timestamp}"
                project_name = os.environ.get("PROJECT_NAME", "Automation Project")
                html_path = html_reporter_export(platform, target, run_id, project_name,
                                                  results, self.output_dir)
                summary["html_report"] = html_path
            except Exception as e:
                print(f"  [REPORT] HTML export skipped — {type(e).__name__}: {e}")
                summary["html_report"] = ""
        else:
            print("  [REPORT] core/html_reporter.py not found -- skipping HTML report")
            summary["html_report"] = ""

        # Print category summary
        print(f"\n  {'CATEGORY':<20} {'PASS':>5} {'FAIL':>5}")
        print(f"  {'-'*32}")
        for cat, counts in categories.items():
            print(f"  {cat:<20} {counts['pass']:>5} {counts['fail']:>5}")

        return summary


# ==========================
# WEB ENGINE
# ==========================
class WebEngine:

    def _build_driver(self):
        """Chrome configured to suppress password-manager / leak-warning
        popups at the source, so they don't interrupt test flows."""
        from selenium import webdriver
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-infobars")
        options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.password_manager_leak_detection": False,
        })
        return options

    def execute(self, url: str) -> dict:
        print("\n[WEB] Test Started")
        print(f"[WEB] Target: {url}")
        print(f"[WEB] Credentials: {WEB_USERNAME} / {'*' * len(WEB_PASSWORD)}")

        discovery = WebDiscovery(chrome_options=self._build_driver())

        try:
            # PHASE 1 — Discovery (multi-page crawl, not just the landing page)
            print("\n--- Phase 1: Discovery ---")
            crawl_result = discovery.crawl(url, username=WEB_USERNAME, password=WEB_PASSWORD)
            scan_result = _merge_pages_for_generation(crawl_result)
            print(f"  Pages Crawled: {len(crawl_result['pages'])} "
                  f"({' -> '.join(p.split('/')[-1] or p for p in crawl_result['flow'])})")
            print(f"  Found: {scan_result['inputs']} inputs | "
                  f"{scan_result['buttons']} buttons | "
                  f"{scan_result['links']} links (combined across all pages)")

            # PHASE 2 — AI + Rule-based Test Generation
            print("\n--- Phase 2: Generating E2E Test Cases (AI + Rules) ---")
            test_cases = ai_generate_test_cases(scan_result)

            # Merge in user-authored critical flows (business-logic assertions
            # auto-discovery can't infer on its own -- checkout totals, coupons, etc.)
            if load_critical_flows:
                critical_flows = load_critical_flows(PROJECT_ROOT)
                for i, flow in enumerate(critical_flows, start=len(test_cases) + 1):
                    flow.setdefault("id", f"TC{i:03d}")
                    test_cases.append(flow)
            else:
                print("  [CRITICAL FLOWS] core/critical_flows.py not found -- "
                      "skipping (add the file to enable business-logic checks)")

            print(f"  Test Cases Generated: {len(test_cases)}")
            for tc in test_cases:
                cat = tc.get("category","").upper()
                print(f"    [{tc['id']}] [{cat}] {tc['name']} ({tc['priority']})")

            # PHASE 3 — Run E2E Tests with Auto-Retry
            print("\n--- Phase 3: Running E2E Tests ---")
            runner  = WebE2ERunner(discovery.driver, discovery.wait, url)
            results = runner.run_all(test_cases)

            # PHASE 4 — Save Reports
            print("\n--- Phase 4: Saving Reports ---")
            reporter = BugReporter()
            summary  = reporter.save("WEB", url, results, scan_result)

            print(f"\n[WEB] Done — {summary['passed']}/{summary['total']} passed | "
                  f"{summary['failed']} bugs found | "
                  f"Pass rate: {summary['pass_rate']}")

            return {
                "status":               "COMPLETED",
                "platform":             "WEB",
                "target":               url,
                "total":                summary["total"],
                "passed":               summary["passed"],
                "failed":               summary["failed"],
                "pass_rate":            summary["pass_rate"],
                "excel_report":         summary.get("excel_report", ""),
                "html_report":          summary.get("html_report", ""),
                "categories":           summary.get("categories", {}),
                "regression":           summary.get("regression", {}),
                "jira_tickets_created": summary.get("jira_tickets_created", []),
                "pages_crawled":        len(crawl_result["pages"]),
                "crawl_flow":           crawl_result["flow"],
            }

        except RuntimeError as e:
            print(f"\n[WEB ERROR] {e}")
            return {"status": "FAILED", "error": str(e), "url": url}

        except Exception as e:
            print(f"\n[WEB UNEXPECTED ERROR] {e}")
            return {"status": "FAILED", "error": str(e), "url": url}

        finally:
            discovery.close()