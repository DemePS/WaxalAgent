import httpx
import pytest

from waxal_agent import soynade_api
from waxal_agent.soynade_api import SoynadeClient, SoynadeError
from waxal_agent.text import chunks


def make(handler, **options):
    return SoynadeClient("K", "https://api.example/v1", httpx.Client(transport=httpx.MockTransport(handler)), **options)


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(soynade_api.time, "sleep", waited.append)
    return waited


def ok():
    return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})


def test_a_429_waits_as_the_server_says_then_succeeds(sleeps):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "7"}, json={"title": "Too Many Requests"}) if len(calls) == 1 else ok()
    make(handler, min_interval=0).chat("m", [])
    assert len(calls) == 2 and 7 in sleeps


def test_without_retry_after_the_wait_grows_and_is_capped(sleeps):
    def handler(request):
        return httpx.Response(429, json={"title": "Too Many Requests"})
    with pytest.raises(SoynadeError) as raised:
        make(handler, retries=3, backoff=2, min_interval=0).chat("m", [])
    assert sleeps == [2, 4, 8]
    assert "rate limit of your Soynade plan" in str(raised.value) and raised.value.status == 429


def test_calls_are_spaced_by_the_minimum_interval(monkeypatch):
    now = [100.0]
    waited = []
    monkeypatch.setattr(soynade_api.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(soynade_api.time, "sleep", lambda s: (waited.append(s), now.__setitem__(0, now[0] + s)))
    c = make(lambda request: ok(), min_interval=0.5)
    c.chat("m", [])
    c.chat("m", [])
    assert waited and abs(waited[0] - 0.5) < 1e-6


def test_the_number_of_retries_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("SOYNADE_RETRIES", "1")
    monkeypatch.setenv("SOYNADE_MIN_INTERVAL", "0")
    c = make(lambda request: httpx.Response(503, json={}))
    assert c.retries == 1 and c.min_interval == 0


def test_sentences_are_packed_into_as_few_pieces_as_possible():
    text = "One two three. Four five six. Seven eight nine. Ten eleven twelve."
    assert chunks(text, 600) == [text]                               # one API call
    pieces = chunks(text, 32)
    assert all(len(p) <= 32 for p in pieces) and " ".join(pieces) == text and len(pieces) == 3
    assert chunks("", 100) == []
