import os
import re


class InputDetector:

    @staticmethod
    def detect(user_input):

        if not user_input:
            return {
                "status": False,
                "message": "Input empty"
            }

        # WEB
        url_pattern = r"^https?://"

        if re.match(url_pattern, user_input):

            return {
                "status": True,
                "platform": "WEB",
                "engine": "web_engine"
            }

        # ANDROID
        if user_input.lower().endswith(".apk"):

            if os.path.exists(user_input):

                return {
                    "status": True,
                    "platform": "ANDROID",
                    "engine": "android_engine"
                }

            return {
                "status": False,
                "message": "APK not found"
            }

        # IOS
        if user_input.lower().endswith(".ipa"):

            if os.path.exists(user_input):

                return {
                    "status": True,
                    "platform": "IOS",
                    "engine": "ios_engine"
                }

            return {
                "status": False,
                "message": "IPA not found"
            }

        return {
            "status": False,
            "message": "Unsupported input"
        }