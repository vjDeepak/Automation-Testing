import os
import secrets
import json


class CredentialManager:

    FILE = "runtime_credentials.json"

    @classmethod
    def initialize(cls):

        if os.path.exists(cls.FILE):

            with open(
                cls.FILE,
                "r"
            ) as f:

                return json.load(f)

        credentials = {

            "platform_token":
            secrets.token_hex(32),

            "ai_enabled":
            False,

            "mode":
            "LOCAL"

        }

        with open(
            cls.FILE,
            "w"
        ) as f:

            json.dump(
                credentials,
                f,
                indent=4
            )

        return credentials