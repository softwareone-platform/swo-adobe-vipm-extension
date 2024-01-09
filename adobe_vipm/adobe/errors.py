class AdobeError(Exception):
    INVALID_FIELDS = "1117"
    INVALID_ADDRESS = "1118"
    ACCOUNT_ALREADY_EXISTS = "1127"

    def __init__(self, payload):
        self.payload = payload
        self.code = payload["code"]
        self.message = payload["message"]
        self.details = payload.get("additionalDetails", [])

    def __str__(self):
        message = f"{self.code} - {self.message}"
        if self.details:
            message = f"{message}: {', '.join(self.details)}"
        return message

    def __repr__(self):
        return str(self.payload)
