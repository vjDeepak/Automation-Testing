"""
Critical Flow Loader
=====================
Auto-discovery (crawling + AI) can tell you a page loaded, a button was
clickable, a field accepted text. It CANNOT tell you whether a discount
calculated correctly, a cart total is right, or a coupon applied the
correct amount off -- that requires an oracle: a human-provided expected
result.

This loader reads a JSON config of exactly that: flows you write by hand,
each with a concrete expected outcome. They run on every cycle alongside
the auto-generated tests, and feed into the same regression tracking.

Place this file at: core/critical_flows.py
Config file lives at: <project_root>/config/critical_flows.json
(auto-created with an example template the first time this runs)
"""
import os
import json


TEMPLATE = {
    "critical_flows": [
        {
            "name": "EXAMPLE -- cart total updates correctly for quantity",
            "category": "critical_flow",
            "priority": "high",
            "type": "positive",
            "steps": [
                {"action": "navigate", "target": "https://your-site.com/product/123"},
                {"action": "fill",     "target": "quantity", "value": "3"},
                {"action": "click",    "target": "Add to Cart"},
                {"action": "navigate", "target": "https://your-site.com/cart"},
                {"action": "verify",   "target": "page_source_contains", "expect": "29.97"}
            ],
            "expected_result": "Cart total = unit price * 3"
        }
    ],
    "_readme": (
        "Replace the EXAMPLE entry above with your own business-critical "
        "flows -- checkout math, coupon codes, tax calculation, shipping "
        "cost rules, anything where correctness depends on YOUR business "
        "rules rather than generic UI behavior. "
        "Each step supports action: navigate / fill / click / verify. "
        "For 'verify', target can be: page_title, url_contains, "
        "element_visible, element_enabled, page_source_contains. "
        "Entries whose name starts with 'EXAMPLE' are ignored at runtime, "
        "so delete that prefix once you've filled in a real flow."
    )
}


def load_critical_flows(project_root: str) -> list:
    config_path = os.path.join(project_root, "config", "critical_flows.json")

    if not os.path.exists(config_path):
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(TEMPLATE, f, indent=2)
        print(f"  [CRITICAL FLOWS] No config found -- created a starter "
              f"template at:\n    {config_path}\n"
              f"  Edit it with your real business-critical flows, then re-run.")
        return []

    try:
        with open(config_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [CRITICAL FLOWS] Could not read {config_path}: {e} -- skipping")
        return []

    flows = data.get("critical_flows", [])
    flows = [f for f in flows if not f.get("name", "").startswith("EXAMPLE")]

    if flows:
        print(f"  [CRITICAL FLOWS] Loaded {len(flows)} critical flow(s) from config")
    else:
        print(f"  [CRITICAL FLOWS] Config exists but has no real flows yet "
              f"(only the EXAMPLE placeholder) -- edit {config_path}")

    return flows