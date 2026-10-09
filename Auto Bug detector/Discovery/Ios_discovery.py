from appium import webdriver as appium_driver
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.ios import XCUITestOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


class IOSDiscovery:

    APPIUM_SERVER   = "http://127.0.0.1:4723"
    ELEMENT_TIMEOUT = 15  # iOS needs slightly more time

    def __init__(self, ipa_path: str):

        if not ipa_path.lower().endswith(".ipa"):
            raise ValueError(
                f"Expected an .ipa file, got: {ipa_path}"
            )

        self.ipa_path = ipa_path
        self.driver   = None
        self.wait     = None

    # ==========================
    # CONNECT
    # ==========================
    def connect(self):

        options = XCUITestOptions()
        options.platform_name    = "iOS"
        options.automation_name  = "XCUITest"
        options.app              = self.ipa_path
        options.no_reset         = False
        options.full_reset       = False

        # Update these to match your simulator / device
        options.device_name      = "iPhone 15"
        options.platform_version = "17.0"

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
                f"Make sure Appium is running with XCUITest driver.\n"
                f"Details: {e}"
            )

    # ==========================
    # SCAN
    # ==========================
    def scan(self) -> dict:

        try:
            print("\n[1/7] Launching iOS App")
            self.connect()

            print("[2/7] Scanning App Info")
            bundle_id = self.driver.capabilities.get(
                "bundleId", "unknown"
            )
            print(f"  Bundle ID: {bundle_id}")

            print("\n[3/7] Finding Text Fields")
            text_fields = self.driver.find_elements(
                AppiumBy.CLASS_NAME,
                "XCUIElementTypeTextField"
            )
            secure_fields = self.driver.find_elements(
                AppiumBy.CLASS_NAME,
                "XCUIElementTypeSecureTextField"
            )
            all_inputs = text_fields + secure_fields
            input_details = [
                {
                    "type":        "secure" if el in secure_fields else "text",
                    "value":       el.get_attribute("value") or "",
                    "label":       el.get_attribute("label") or "",
                    "placeholder": el.get_attribute("placeholderValue") or "",
                    "enabled":     el.get_attribute("enabled") == "true",
                }
                for el in all_inputs
            ]
            print(f"  Text Fields Found : {len(text_fields)}")
            print(f"  Secure Fields Found: {len(secure_fields)}")

            print("\n[4/7] Finding Buttons")
            buttons = self.driver.find_elements(
                AppiumBy.CLASS_NAME,
                "XCUIElementTypeButton"
            )
            button_details = [
                {
                    "label":   btn.get_attribute("label") or "(no label)",
                    "enabled": btn.get_attribute("enabled") == "true",
                    "visible": btn.get_attribute("visible") == "true",
                }
                for btn in buttons
            ]
            print(f"  Buttons Found: {len(buttons)}")

            print("\n[5/7] Finding Other Tappable Elements")
            cells = self.driver.find_elements(
                AppiumBy.CLASS_NAME,
                "XCUIElementTypeCell"
            )
            static_texts = self.driver.find_elements(
                AppiumBy.CLASS_NAME,
                "XCUIElementTypeStaticText"
            )
            tappable_details = [
                {
                    "type":  "Cell",
                    "label": el.get_attribute("label") or "(no label)",
                }
                for el in cells
            ] + [
                {
                    "type":  "StaticText",
                    "label": el.get_attribute("label") or "(no label)",
                }
                for el in static_texts
            ]
            print(f"  Cells Found      : {len(cells)}")
            print(f"  Static Texts Found: {len(static_texts)}")

            print("\n[6/7] Generating Test Paths")
            paths = self._generate_test_paths(
                input_details,
                button_details,
                tappable_details
            )
            print(f"  Test Paths Generated: {len(paths)}")
            for path in paths:
                print(f"    - {path}")

            print("\n[7/7] Scan Completed")

            return {
                "bundle_id":        bundle_id,
                "text_fields":      len(text_fields),
                "secure_fields":    len(secure_fields),
                "inputs":           len(all_inputs),
                "buttons":          len(buttons),
                "cells":            len(cells),
                "static_texts":     len(static_texts),
                "paths":            len(paths),
                "input_details":    input_details,
                "button_details":   button_details,
                "tappable_details": tappable_details,
                "path_details":     paths,
            }

        except TimeoutException:
            raise RuntimeError(
                f"App elements did not appear within "
                f"{self.ELEMENT_TIMEOUT}s."
            )

        except WebDriverException as e:
            raise RuntimeError(f"Appium error during iOS scan: {e}")

    # ==========================
    # GENERATE TEST PATHS
    # ==========================
    def _generate_test_paths(
        self,
        inputs:    list,
        buttons:   list,
        tappables: list
    ) -> list:

        paths = []

        for i, btn in enumerate(buttons, start=1):
            label = btn["label"]
            paths.append(f"Button {i}: Tap '{label}'")

        for i, inp in enumerate(inputs, start=1):
            hint = (
                inp["placeholder"]
                or inp["label"]
                or inp["type"]
                or f"Field {i}"
            )
            paths.append(f"Input {i}: Enter text in '{hint}'")

        for i, el in enumerate(tappables, start=1):
            paths.append(
                f"{el['type']} {i}: Tap '{el['label']}'"
            )

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