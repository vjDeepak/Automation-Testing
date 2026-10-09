import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
from urllib.parse import urlparse as url_parse


class WebDiscovery:

    PAGE_LOAD_TIMEOUT = 10

    def __init__(self, chrome_options=None):
        """
        chrome_options: optional pre-built webdriver.ChromeOptions().
        If not provided, sensible defaults are used (including
        suppressing Chrome's password-manager/leak-warning popups).
        """
        if chrome_options is None:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_experimental_option("prefs", {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.password_manager_leak_detection": False,
            })

        try:
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
            self.wait = WebDriverWait(self.driver, self.PAGE_LOAD_TIMEOUT)
        except WebDriverException as e:
            raise RuntimeError(f"Failed to launch Chrome: {e}")

    # ==========================
    # SCAN (single page)
    # ==========================
    def scan(self, url: str) -> dict:
        try:
            print("\n[1/7] Opening Application")
            self.driver.get(url)
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(2)
            return self._scan_current_page()
        except TimeoutException:
            raise RuntimeError(f"Page did not load within {self.PAGE_LOAD_TIMEOUT}s")
        except WebDriverException as e:
            raise RuntimeError(f"WebDriver error: {e}")

    # ==========================
    # SCAN whatever page the driver is currently sitting on
    # (shared by scan() and crawl() so both use identical logic)
    # ==========================
    def _scan_current_page(self) -> dict:
        print("[2/7] Scanning Page")
        title       = self.driver.title
        current_url = self.driver.current_url
        print(f"  Title      : {title}")
        print(f"  Current URL: {current_url}")

        print("\n[3/7] Finding Inputs")
        all_inputs = self.driver.find_elements(By.TAG_NAME, "input")
        inputs = [
            el for el in all_inputs
            if el.get_attribute("type") not in ("submit", "button", "hidden", "reset")
        ]
        input_details = [
            {
                "type":        el.get_attribute("type") or "text",
                "name":        el.get_attribute("name") or "",
                "placeholder": el.get_attribute("placeholder") or "",
                "id":          el.get_attribute("id") or "",
            }
            for el in inputs
        ]
        print(f"  Inputs Found: {len(inputs)}")

        print("\n[4/7] Finding Buttons")
        btn_tags    = self.driver.find_elements(By.TAG_NAME, "button")
        btn_inputs  = self.driver.find_elements(
            By.XPATH,
            '//input[@type="submit" or @type="button"]'
        )
        button_details = []
        for btn in btn_tags:
            button_details.append({
                "text":    btn.text.strip() or btn.get_attribute("value") or "(no text)",
                "id":      btn.get_attribute("id") or "",
                "name":    btn.get_attribute("name") or "",
                "enabled": btn.is_enabled(),
                "source":  "button",
            })
        for btn in btn_inputs:
            button_details.append({
                "text":    btn.get_attribute("value") or "(no text)",
                "id":      btn.get_attribute("id") or "",
                "name":    btn.get_attribute("name") or "",
                "enabled": btn.is_enabled(),
                "source":  "input_submit",
            })
        print(f"  Buttons Found: {len(button_details)}")

        print("\n[+] Finding Dropdowns")
        select_details = []
        for sel in self.driver.find_elements(By.TAG_NAME, "select"):
            select_details.append({
                "id":      sel.get_attribute("id") or "",
                "name":    sel.get_attribute("name") or "",
                "options": [
                    o.text.strip()
                    for o in sel.find_elements(By.TAG_NAME, "option")
                ],
            })
        print(f"  Dropdowns Found: {len(select_details)}")

        print("\n[5/7] Finding Links")
        links = self.driver.find_elements(By.TAG_NAME, "a")
        link_details = [
            {
                "text": lnk.text.strip() or "(no text)",
                "href": lnk.get_attribute("href") or "",
            }
            for lnk in links if lnk.get_attribute("href")
        ]
        # Menu items and similar JS-driven action links (href="#" or empty)
        # are real, clickable, meaningful elements (e.g. "Logout",
        # "Reset App State") but aren't real navigable URLs, so the crawler
        # can't queue them as pages to visit. Capture them separately so
        # test generation still knows they exist.
        action_link_details = [
            {"text": lnk.text.strip() or "(no text)"}
            for lnk in links
            if lnk.text.strip() and (lnk.get_attribute("href") or "").rstrip("#") in ("", self.driver.current_url.rstrip("#"))
        ]
        print(f"  Links Found: {len(link_details)} (+ {len(action_link_details)} in-page action links)")

        print("\n[6/7] Generating Test Paths")
        paths = self._generate_test_paths(input_details, button_details, link_details)
        print(f"  Test Paths Generated: {len(paths)}")
        for p in paths:
            print(f"    - {p}")

        print("[7/7] Scan Completed")

        return {
            "title":              title,
            "url":                current_url,
            "inputs":             len(inputs),
            "buttons":            len(button_details),
            "selects":            len(select_details),
            "links":              len(link_details),
            "paths":              len(paths),
            "input_details":      input_details,
            "button_details":     button_details,
            "select_details":     select_details,
            "link_details":       link_details,
            "action_link_details": action_link_details,
            "path_details":       paths,
        }

    # ==========================
    # CRAWL (multi-page) — follows internal links AND flow-relevant
    # buttons (Login, Add to Cart, Checkout, Continue, Pay, Finish, ...)
    # so pages like cart/quantity/checkout/payment actually get scanned
    # instead of only the single landing page.
    # ==========================
    # Never auto-click these during discovery — they're destructive/
    # irreversible and would corrupt the state we're trying to explore
    # (e.g. clicking "Remove" mid-crawl would empty a cart another
    # branch of the crawl still needs to see).
    DANGER_KEYWORDS = [
        "logout", "log out", "sign out", "delete", "remove",
        "cancel order", "delete account", "deactivate", "unsubscribe",
        "clear cart", "empty cart", "close account",
    ]

    def crawl(self, start_url: str, username: str = None, password: str = None,
              max_pages: int = 8, max_actions_per_page: int = 15) -> dict:

        from urllib.parse import urlparse

        domain    = urlparse(start_url).netloc
        visited   = set()
        pages     = []
        flow      = []
        queue     = [start_url]

        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                print(f"\n[CRAWL] Visiting: {url}")
                self.driver.get(url)
                self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2)
            except Exception as e:
                print(f"  [CRAWL] Skipped (couldn't load): {e}")
                continue

            # If this looks like a login form and credentials were given,
            # log in now so the crawl can proceed past the auth wall.
            if username and password:
                self._try_auto_login(username, password)

            page_result = self._scan_current_page()
            pages.append(page_result)
            flow.append(page_result["url"])

            # Queue same-domain links for later
            for link in page_result["link_details"]:
                href = link["href"]
                if href and urlparse(href).netloc == domain and href not in visited:
                    queue.append(href)

            # Fill any empty visible text fields BEFORE trying buttons. Many
            # "Continue"/"Submit" buttons are blocked by client-side
            # validation until required fields have a value — without this,
            # the crawl gets stuck on forms (e.g. a shipping/billing info
            # page) and never reaches what's beyond them (payment, order
            # summary, confirmation).
            self._autofill_visible_inputs()

            # Follow every clickable button on this page (not just ones
            # matching a keyword list) so quantity steppers, filters,
            # "add to cart" on every product, checkout, payment, etc. all
            # get discovered — skip only the destructive deny-list above,
            # and cap total clicks per page so this can't run away.
            actions_taken = 0
            for btn in page_result["button_details"]:
                if actions_taken >= max_actions_per_page:
                    print(f"  [CRAWL] Reached max_actions_per_page "
                          f"({max_actions_per_page}) — skipping remaining buttons")
                    break

                label = (btn["text"] or "").lower()
                if any(k in label for k in self.DANGER_KEYWORDS):
                    continue

                try:
                    el = self._find_button_element(btn)
                    if not el or not el.is_enabled() or not el.is_displayed():
                        continue
                    before_url = self.driver.current_url
                    el.click()
                    actions_taken += 1
                    time.sleep(2)
                    after_url = self.driver.current_url
                    if after_url != before_url and after_url not in visited:
                        queue.append(after_url)
                        # Return to this page's original state so the next
                        # button is explored independently (discovery only —
                        # not a cumulative user session).
                        self.driver.get(url)
                        time.sleep(1)
                        self._autofill_visible_inputs()
                except Exception as e:
                    print(f"  [CRAWL] Could not follow button '{btn['text']}': {e}")

        print(f"\n[CRAWL] Done — {len(pages)} page(s) discovered: {' -> '.join(flow)}")
        return {"pages": pages, "flow": flow}

    def _try_auto_login(self, username: str, password: str):
        """Best-effort: if the current page has a password field, fill
        username/password and submit. Silently does nothing if no such
        form is present."""
        try:
            pw_fields = [
                el for el in self.driver.find_elements(By.TAG_NAME, "input")
                if el.get_attribute("type") == "password"
            ]
            if not pw_fields:
                return

            user_fields = [
                el for el in self.driver.find_elements(By.TAG_NAME, "input")
                if el.get_attribute("type") in (None, "text", "email")
                and el.is_displayed()
            ]
            if not user_fields:
                return

            print("  [CRAWL] Login form detected — attempting auto-login")
            user_fields[0].clear()
            user_fields[0].send_keys(username)
            pw_fields[0].clear()
            pw_fields[0].send_keys(password)

            submit = self.driver.find_elements(
                By.XPATH,
                '//button[@type="submit"] | //input[@type="submit"] | //button'
            )
            visible_submit = [b for b in submit if b.is_displayed() and b.is_enabled()]
            if visible_submit:
                visible_submit[0].click()
                time.sleep(2)
        except Exception as e:
            print(f"  [CRAWL] Auto-login attempt failed (continuing anyway): {e}")

    def _autofill_visible_inputs(self):
        """Fill any empty, visible text-like inputs with plausible dummy
        data so a 'Continue'/'Submit' click has a chance of passing
        client-side validation during discovery. Best-effort guess based
        on the field's name/id/placeholder — not a substitute for real
        test data, just enough to get the crawl past a form."""
        guesses = {
            "first": "Test", "fname": "Test", "given": "Test",
            "last": "User", "lname": "User", "surname": "User", "family": "User",
            "zip": "12345", "postal": "12345", "pincode": "12345",
            "email": "test@example.com", "phone": "5551234567", "tel": "5551234567",
            "address": "123 Test St", "city": "Testville", "state": "CA",
            "country": "US", "card": "4111111111111111", "cvv": "123",
            "name": "Test User",
        }

        for el in self.driver.find_elements(By.TAG_NAME, "input"):
            try:
                if not el.is_displayed():
                    continue
                input_type = (el.get_attribute("type") or "text").lower()
                if input_type in ("submit", "button", "hidden", "checkbox", "radio", "file"):
                    continue
                if el.get_attribute("value"):
                    continue  # already has something in it

                hint = " ".join([
                    el.get_attribute("name") or "",
                    el.get_attribute("id") or "",
                    el.get_attribute("placeholder") or "",
                ]).lower()

                fill_value = "Test"
                for key, val in guesses.items():
                    if key in hint:
                        fill_value = val
                        break

                el.clear()
                el.send_keys(fill_value)
            except Exception:
                continue

    def _find_button_element(self, btn_detail: dict):
        """Re-locate a live element from the dict captured during scanning
        (Selenium element references go stale between scans)."""
        bid  = btn_detail.get("id")
        name = btn_detail.get("name")
        text = btn_detail.get("text")

        if bid:
            els = self.driver.find_elements(By.ID, bid)
            if els:
                return els[0]
        if name:
            els = self.driver.find_elements(By.NAME, name)
            if els:
                return els[0]
        if text and text != "(no text)":
            els = self.driver.find_elements(
                By.XPATH, f'//button[normalize-space()="{text}"] | //input[@value="{text}"]'
            )
            if els:
                return els[0]
        return None

    # ==========================
    # GENERATE TEST PATHS
    # ==========================
    def _generate_test_paths(self, inputs, buttons, links) -> list:
        paths = []
        for i, btn in enumerate(buttons, 1):
            paths.append(f"Button {i}: Click '{btn['text']}'")
        for i, inp in enumerate(inputs, 1):
            field = inp["placeholder"] or inp["name"] or inp["type"] or f"Input {i}"
            paths.append(f"Input {i}: Fill '{field}'")
        for i, lnk in enumerate(links, 1):
            label = lnk["text"] or lnk["href"]
            paths.append(f"Link {i}: Navigate '{label}'")
        return paths

    # ==========================
    # CLOSE
    # ==========================
    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass