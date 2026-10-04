from waxal_agent.text import sentences, speakable


def test_speakable_drops_code_tables_links_and_markdown():
    text = "**Total** is 642.00 EUR.\n\n```python\nprint(1)\n```\n| a | b |\n|---|---|\n- see [the file](http://x.y/z) now\nhttp://evil.example/x"
    out = speakable(text)
    assert "print" not in out and "|" not in out and "http" not in out and "*" not in out
    assert "Total is 642.00 EUR." in out and "see the file now" in out


def test_sentences_split_and_long_ones_are_cut():
    assert sentences("One. Two! Three?\nFour.") == ["One.", "Two!", "Three?", "Four."]
    long = " ".join(["word"] * 100)
    parts = sentences(long, limit=50)
    assert all(len(p) <= 50 for p in parts) and " ".join(parts).split() == long.split()
