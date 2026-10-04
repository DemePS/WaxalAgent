"""A stand-in listener for tests and the demo page: it does not hear anything."""


class FakeListener:
    """Returns the scripted texts in order, then `default`."""

    def __init__(self, *texts: str, default: str = "") -> None:
        self.texts = list(texts)
        self.default = default
        self.heard: list[int] = []  # the size of each recording received

    def transcribe(self, wav: bytes) -> str:
        self.heard.append(len(wav))
        return self.texts.pop(0) if self.texts else self.default
