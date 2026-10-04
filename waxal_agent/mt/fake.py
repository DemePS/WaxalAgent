"""A stand-in translator: a small table, else the text tagged with its target language."""


class FakeTranslator:
    def __init__(self, table: dict[tuple[str, str, str], str] | None = None) -> None:
        self.table = table or {}
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append((text, source, target))
        return self.table.get((text, source, target), f"[{target}] {text}")
