"""
Jira Bug Reporter
===================
Automatically creates Jira issues for failing automated tests.

Wired (see web_engine.py's BugReporter) to fire ONLY for regressions and
brand-new failures -- not for tests that were already known to be failing
last run -- so it doesn't file a duplicate ticket every single run for the
same already-tracked issue. It also double-checks with a live JQL search
before creating anything, in case the regression baseline was reset.

Requires these in your .env:
  JIRA_BASE_URL       e.g. https://yourcompany.atlassian.net
  JIRA_EMAIL          Jira Cloud account email (Basic auth). Leave unset
                       for Jira Server/Data Center Personal Access Token auth.
  JIRA_API_TOKEN      Jira Cloud API token, OR a Server/DC Personal Access Token
  JIRA_PROJECT_KEY    e.g. QA
  JIRA_ISSUE_TYPE     optional, defaults to "Bug"
  JIRA_API_VERSION    optional, "3" (Cloud, default) or "2" (Server/Data Center)

If JIRA_BASE_URL / JIRA_API_TOKEN / JIRA_PROJECT_KEY aren't set, Jira
integration is skipped entirely -- the rest of the framework works fine
without it.

Place this file at: core/jira_reporter.py
"""
import os
import json
import base64
import urllib.request
import urllib.error
import urllib.parse


class JiraReporter:

    def __init__(self):
        self.base_url    = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
        self.email       = os.environ.get("JIRA_EMAIL", "")
        self.api_token   = os.environ.get("JIRA_API_TOKEN", "")
        self.project_key = os.environ.get("JIRA_PROJECT_KEY", "")
        self.issue_type  = os.environ.get("JIRA_ISSUE_TYPE", "Bug")
        self.api_version = os.environ.get("JIRA_API_VERSION", "3")
        self.enabled     = bool(self.base_url and self.api_token and self.project_key)

        if not self.enabled:
            print("  [JIRA] Not configured (missing JIRA_BASE_URL / "
                  "JIRA_API_TOKEN / JIRA_PROJECT_KEY in .env) -- "
                  "skipping Jira integration")

    # ==========================
    # AUTH / HTTP
    # ==========================
    def _auth_header(self) -> str:
        if self.email:
            # Jira Cloud: Basic auth with email:api_token
            token = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
            return f"Basic {token}"
        # Jira Server/Data Center: Bearer PAT
        return f"Bearer {self.api_token}"

    def _request(self, method: str, path: str, payload: dict = None):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": self._auth_header(),
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            print(f"  [JIRA] {method} {path} failed ({e.code}): {err_body[:300]}")
            return None
        except Exception as e:
            print(f"  [JIRA] {method} {path} failed: {e}")
            return None

    # ==========================
    # DUPLICATE PREVENTION
    # ==========================
    def _find_existing_open_ticket(self, test_name: str) -> str:
        """Searches for an already-open automation-created ticket for this
        exact test, so we don't file a duplicate."""
        safe_name = test_name.replace('"', '\\"')
        jql = (
            f'project = "{self.project_key}" '
            f'AND labels = "automation" '
            f'AND summary ~ "\\"{safe_name}\\"" '
            f'AND statusCategory != Done '
            f'ORDER BY created DESC'
        )
        result = self._request(
            "GET",
            f"/rest/api/{self.api_version}/search?jql={urllib.parse.quote(jql)}&maxResults=1"
        )
        if result and result.get("issues"):
            return result["issues"][0]["key"]
        return None

    # ==========================
    # CREATE
    # ==========================
    def create_bug(self, test_result: dict, platform: str, target: str) -> str:
        """Creates a Jira bug for one failing test. Returns the issue key
        (e.g. 'QA-123'), or None if skipped/failed."""
        if not self.enabled:
            return None

        test_name = test_result.get("name", "Unnamed test")

        existing = self._find_existing_open_ticket(test_name)
        if existing:
            print(f"  [JIRA] Skipping duplicate -- {existing} already open for: {test_name}")
            return existing

        summary = f"[AUTO][{platform}] {test_name} -- FAILED"
        description_text = (
            f"Automated test failure detected.\n\n"
            f"Platform: {platform}\n"
            f"Target: {target}\n"
            f"Test ID: {test_result.get('id')}\n"
            f"Category: {test_result.get('category', 'n/a')}\n"
            f"Priority: {test_result.get('priority', 'n/a')}\n"
            f"Attempts: {test_result.get('attempts')}\n"
            f"Timestamp: {test_result.get('timestamp')}\n\n"
            f"Error:\n{test_result.get('error')}\n\n"
            f"Filed automatically by the automation framework."
        )

        fields = {
            "project":   {"key": self.project_key},
            "summary":   summary,
            "issuetype": {"name": self.issue_type},
            "labels":    ["automation", platform.lower()],
        }

        if self.api_version == "2":
            # Jira Server / Data Center — plain text description
            fields["description"] = description_text
        else:
            # Jira Cloud v3 — Atlassian Document Format required
            fields["description"] = {
                "type": "doc", "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description_text}]
                }]
            }

        result = self._request("POST", f"/rest/api/{self.api_version}/issue", {"fields": fields})
        if result and result.get("key"):
            print(f"  [JIRA] Created {result['key']}: {summary}")
            return result["key"]
        return None

    def create_bugs_for_failures(self, failures: list, platform: str, target: str) -> list:
        """Files Jira bugs for the given failing test results. Intended to
        be called with ONLY regressions + new failures (see BugReporter),
        not every failure on every run."""
        if not self.enabled or not failures:
            return []

        created = []
        for f in failures:
            key = self.create_bug(f, platform, target)
            if key:
                created.append(key)
        return created