"""
HTML Test Report Generator
=============================
Builds a single self-contained HTML report: run header, Total/Passed/
Failed summary cards, and a per-test table with expected vs actual
result, steps to reproduce, and click-to-enlarge screenshots on failure.
Screenshots are embedded as base64 data URIs so the report is a single
file you can share/host without also shipping a screenshots folder.

Place this file at: core/html_reporter.py
"""
import os
import base64
from datetime import datetime


def _format_steps(steps: list) -> list:
    lines = []
    for s in steps:
        action = s.get("action", "")
        target = s.get("target", "")
        value  = s.get("value", "")
        expect = s.get("expect", "")
        if action == "navigate":
            lines.append(f"Navigate to {target}")
        elif action == "fill":
            lines.append(f"Fill '{target}' with '{value}'")
        elif action == "click":
            lines.append(f"Click '{target}'")
        elif action == "select":
            lines.append(f"Select '{value}' in '{target}'")
        elif action == "press_key":
            lines.append(f"Press {value} on '{target}'" if target else f"Press {value}")
        elif action == "verify":
            lines.append(f"Assert {target} = {expect}")
        elif action == "verify_checkout_math":
            rate = s.get("tax_rate")
            lines.append("Assert item total + tax = total" + (f" (tax rate {rate})" if rate else ""))
        else:
            lines.append(f"{action}: {target}")
    return lines


def _screenshot_to_data_uri(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def _esc(text) -> str:
    return (str(text) if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export(platform: str, target: str, run_id: str, project_name: str,
           results: list, output_dir: str = "reports") -> str:
    os.makedirs(output_dir, exist_ok=True)

    total  = len(results)
    passed = len([r for r in results if r["status"] == "PASS"])
    failed = total - passed

    rows_html = []
    for r in results:
        status        = r.get("status", "FAIL")
        status_class  = "pass" if status == "PASS" else "fail"
        actual        = "Working" if status == "PASS" else (r.get("error") or "Failed")
        steps_html    = "<br>".join(_esc(s) for s in _format_steps(r.get("steps", [])))
        screenshot_uri = _screenshot_to_data_uri(r.get("screenshot", ""))

        remarks_cell = "-"
        if status != "PASS" and screenshot_uri:
            remarks_cell = (
                f'<a href="#" class="shot-link" data-img="{screenshot_uri}" '
                f'onclick="openModal(this); return false;">click to enlarge</a>'
            )

        rows_html.append(f"""
        <tr class="{status_class}">
          <td>{_esc(r.get('id',''))}</td>
          <td>{_esc(target)}</td>
          <td>{_esc(r.get('category','') or platform)}</td>
          <td>{_esc(r.get('type',''))}</td>
          <td>{_esc(r.get('name',''))}</td>
          <td>{_esc(r.get('expected','') or 'Should work as expected')}</td>
          <td>{_esc(actual)}</td>
          <td class="steps">{steps_html}</td>
          <td><span class="badge {status_class}">{status}</span></td>
          <td>{remarks_cell}</td>
        </tr>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>QA Report — {_esc(run_id)}</title>
<style>
  :root {{
    --pass: #1a9d5c; --fail: #d9363e; --bg: #f5f7fa; --card: #ffffff;
    --border: #e3e7ee; --text: #1f2937; --muted: #6b7280;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
          background: var(--bg); color: var(--text); margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
  .cards {{ display: flex; gap: 16px; margin-bottom: 24px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
           padding: 16px 24px; text-align: center; min-width: 100px; }}
  .card .num {{ font-size: 28px; font-weight: 700; }}
  .card.total .num {{ color: var(--text); }}
  .card.passed .num {{ color: var(--pass); }}
  .card.failed .num {{ color: var(--fail); }}
  .card .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card);
           border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 13px; }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
  th {{ background: #f0f2f6; font-size: 11px; text-transform: uppercase; color: var(--muted); }}
  tr.fail {{ background: #fff5f5; }}
  .badge {{ padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; color: #fff; }}
  .badge.pass {{ background: var(--pass); }}
  .badge.fail {{ background: var(--fail); }}
  .steps {{ max-width: 280px; font-size: 12px; color: var(--muted); }}
  a.shot-link {{ color: #2563eb; text-decoration: none; font-size: 12px; }}
  a.shot-link:hover {{ text-decoration: underline; }}
  footer {{ margin-top: 20px; text-align: center; color: var(--muted); font-size: 12px; }}
  #modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,.8);
            align-items: center; justify-content: center; z-index: 999; }}
  #modal img {{ max-width: 90%; max-height: 90%; border-radius: 8px; }}
  #modal .close {{ position: absolute; top: 20px; right: 30px; color: #fff; font-size: 28px; cursor: pointer; }}
</style>
</head>
<body>

<h1>{"&#9989;" if failed == 0 else "&#10060;"} QA Report — {_esc(platform)}</h1>
<div class="meta">Run: {_esc(run_id)} | Platform: {_esc(platform)} | Project: {_esc(project_name)}</div>

<div class="cards">
  <div class="card total"><div class="num">{total}</div><div class="label">Total</div></div>
  <div class="card passed"><div class="num">{passed}</div><div class="label">Passed</div></div>
  <div class="card failed"><div class="num">{failed}</div><div class="label">Failed</div></div>
</div>

<table>
<thead>
<tr>
  <th>Test ID</th><th>Target</th><th>Module</th><th>Type</th><th>Test Scenario</th>
  <th>Expected Result</th><th>Actual Result</th><th>Steps to Reproduce</th>
  <th>Status</th><th>Remarks / Screenshot</th>
</tr>
</thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>

<footer>QA Report &middot; {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</footer>

<div id="modal" onclick="this.style.display='none'">
  <span class="close">&times;</span>
  <img id="modal-img" src="">
</div>

<script>
function openModal(el) {{
  document.getElementById('modal-img').src = el.getAttribute('data-img');
  document.getElementById('modal').style.display = 'flex';
}}
</script>

</body>
</html>"""

    filename = f"{platform.lower()}_report_{run_id}.html"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  [REPORT] HTML report saved: {path}")
    return path