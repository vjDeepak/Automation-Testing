import tempfile
import unittest
from pathlib import Path

from detector.input_detector import InputDetector


class InputDetectorTests(unittest.TestCase):
    def test_detects_http_and_https_urls(self):
        for url in ("https://example.com", "http://example.com"):
            with self.subTest(url=url):
                result = InputDetector.detect(url)
                self.assertTrue(result["status"])
                self.assertEqual(result["platform"], "WEB")
                self.assertEqual(result["engine"], "web_engine")

    def test_detects_existing_android_package(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "sample.apk"
            apk.touch()

            result = InputDetector.detect(str(apk))

        self.assertTrue(result["status"])
        self.assertEqual(result["platform"], "ANDROID")
        self.assertEqual(result["engine"], "android_engine")

    def test_detects_existing_ios_package(self):
        with tempfile.TemporaryDirectory() as directory:
            ipa = Path(directory) / "sample.ipa"
            ipa.touch()

            result = InputDetector.detect(str(ipa))

        self.assertTrue(result["status"])
        self.assertEqual(result["platform"], "IOS")
        self.assertEqual(result["engine"], "ios_engine")

    def test_rejects_missing_mobile_packages(self):
        for suffix, message in ((".apk", "APK not found"), (".ipa", "IPA not found")):
            with self.subTest(suffix=suffix):
                result = InputDetector.detect(f"missing{suffix}")
                self.assertFalse(result["status"])
                self.assertEqual(result["message"], message)

    def test_rejects_empty_and_unsupported_input(self):
        self.assertEqual(InputDetector.detect(None)["message"], "Input empty")
        self.assertEqual(InputDetector.detect("")["message"], "Input empty")
        self.assertEqual(
            InputDetector.detect("not-a-target")["message"],
            "Unsupported input",
        )


if __name__ == "__main__":
    unittest.main()
