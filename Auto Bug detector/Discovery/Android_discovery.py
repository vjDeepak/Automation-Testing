from appium import webdriver as appium_driver
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


class AndroidDiscovery:

    APPIUM_SERVER  = "http://127.0.0.1:4723"
    ELEMENT_TIMEOUT = 10  # seconds

    def __init__(self, apk_path: str):

        if not apk_path.lower().endswith(".apk"):
            raise ValueError(
                f"Expected an .apk file, got: {apk_path}"
            )

        self.apk_path = apk_path
        self.driver   = None
        self.wait     = None

    # ==========================
    # CONNECT
    # ==========================
    def connect(self):

        options = UiAutomator2Options()
        options.platform_name        = "Android"
        options.automation_name      = "UiAutomator2"
        options.app                  = self.apk_path
        options.no_reset             = False
        options.full_reset           = False
        options.auto_grant_permissions = True

        try:
            self.driver = appium_driver.Remote(
                self.APPIUM_SERVER,
                options=options
            )
            self.wait = WebDriverWait(
                self.driver,
                self.ELEMENT_TIMEOUT
            )
            print(f"  Connected to Appium: {self.APPIUM_SERVER}")

        except WebDriverException as e:
            raise RuntimeError(
                f"Failed to connect to Appium server at "
                f"{self.APPIUM_SERVER}.\n"
                f"Make sure Appium is running.\nDetails: {e}"
            )

    # ==========================
    # SCAN
    # ==========================
    def scan(self) -> dict:

        try:
            print("\n[1/7] Launching Android App")
            self.connect()

            print("[2/7] Scanning App Info")
            package  = self.driver.current_package
            activity = self.driver.current_activity
            print(f"  Package : {package}")
            print(f"  Activity: {activity}")

            print("\n[3/7] Finding Input Fields")
            inputs = self.driver.find_elements(
                AppiumBy.CLASS_NAME,
                "android.widget.EditText"
            )
            input_details = [
                {
                    "text":        el.text or "",
                    "resource_id": el.get_attribute("resource-id") or "",
                    "hint":        el.get_attribute("hint") or "",
                    "enabled":     el.get_attribute("enabled") == "true",
                }
                for el in inputs
            ]
            print(f"  Input Fields Found: {len(inputs)}")

            print("\n[4/7] Finding Buttons")
            buttons = self.driver.find_elements(
                AppiumBy.CLASS_NAME,
                "android.widget.Button"
            )
            button_details = [
                {
                    "text":        btn.text or "(no text)",
                    "resource_id": btn.get_attribute("resource-id") or "",
                    "enabled":     btn.get_attribute("enabled") == "true",
                    "clickable":   btn.get_attribute("clickable") == "true",
                }
                for btn in buttons
            ]
            print(f"  Buttons Found: {len(buttons)}")

            print("\n[5/7] Finding Clickable Elements")
            clickables = self.driver.find_elements(
                AppiumBy.XPATH,
                '//*[@clickable="true"]'
            )
            clickable_details = [
                {
                    "class":       el.get_attribute("class") or "",
                    "text":        el.text or "(no text)",
                    "resource_id": el.get_attribute("resource-id") or "",
                }
                for el in clickables
            ]
            print(f"  Clickable Elements Found: {len(clickables)}")

            print("\n[6/7] Generating Test Paths")
            paths = self._generate_test_paths(
                input_details,
                button_details,
                clickable_details
            )
            print(f"  Test Paths Generated: {len(paths)}")
            for path in paths:
                print(f"    - {path}")

            print("\n[7/7] Scan Completed")

            return {
                "package":           package,
                "activity":          activity,
                "inputs":            len(inputs),
                "buttons":           len(buttons),
                "clickables":        len(clickables),
                "paths":             len(paths),
                "input_details":     input_details,
                "button_details":    button_details,
                "clickable_details": clickable_details,
                "path_details":      paths,
            }

        except TimeoutException:
            raise RuntimeError(
                f"App elements did not appear within "
                f"{self.ELEMENT_TIMEOUT}s."
            )

        except WebDriverException as e:
            raise RuntimeError(f"Appium error during scan: {e}")

    # ==========================
    # GENERATE TEST PATHS
    # ==========================
    def _generate_test_paths(
        self,
        inputs:     list,
        buttons:    list,
        clickables: list
    ) -> list:

        paths = []

        for i, btn in enumerate(buttons, start=1):
            label = btn["text"]
            paths.append(f"Button {i}: Tap '{label}'")

        for i, inp in enumerate(inputs, start=1):
            hint = inp["hint"] or inp["resource_id"] or f"Field {i}"
            paths.append(f"Input {i}: Enter text in '{hint}'")

        for i, el in enumerate(clickables, start=1):
            label = el["text"] or el["resource_id"] or el["class"]
            paths.append(f"Clickable {i}: Tap '{label}'")

        return paths

    # ==========================
    # CLOSE
    # ==========================
    def close(self):

        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass