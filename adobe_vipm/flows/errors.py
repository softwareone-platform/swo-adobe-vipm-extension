class MPTError(Exception):
    def __init__(self, payload):
        self.payload = payload
        self.status = payload["status"]
        self.title = payload["title"]
        self.details = payload["details"]

    def __str__(self):
        return f"{self.status} {self.title}: {self.details}"

    def __repr__(self):
        return str(self.payload)
