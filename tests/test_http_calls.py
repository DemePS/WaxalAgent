"""The shared call policy: it is not tied to Soynade or ElevenLabs, so it is tested with a made-up service."""

import httpx
import pytest

from waxal_agent import http_calls
from waxal_agent.http_calls import CallPolicy


class ServiceError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(http_calls.time, "sleep", waited.append)
    return waited


def policy(**options):
    options.setdefault("detail", lambda response: response.text)
    options.setdefault("backoff", 2.0)
    return CallPolicy("Some API call", ServiceError, **options)


def send_from(statuses, calls=None, headers=None):
    answers = iter(statuses)

    def send():
        if calls is not None:
            calls.append(1)
        status = next(answers)
        if isinstance(status, Exception):
            raise status
        return httpx.Response(status, text=f"answer {status}", headers=headers or {})
    return send


def test_a_rate_limit_is_waited_out_as_the_server_says_then_the_call_succeeds(sleeps):
    send = send_from([429, 200], headers={"retry-after": "7"})
    assert policy().run(send, "https://x/y").status_code == 200 and sleeps == [7.0]


def test_without_retry_after_the_waits_grow_and_a_final_limit_starts_a_cooldown(sleeps):
    calls = []
    p = policy(retries=2, limit_hint="Check your plan.")
    with pytest.raises(ServiceError, match=r"Some API call failed \(https://x/y\): HTTP 429: answer 429\. Check your plan\.") as raised:
        p.run(send_from([429, 429, 429], calls), "https://x/y")
    assert sleeps == [2.0, 4.0] and len(calls) == 3 and raised.value.status == 429
    with pytest.raises(ServiceError, match="not calling again") as refused:       # no call at all during the cooldown
        p.run(send_from([200], calls), "https://x/y")
    assert len(calls) == 3 and refused.value.status == 429


def test_waits_never_exceed_thirty_seconds(sleeps):
    send = send_from([429, 200], headers={"retry-after": "600"})
    policy().run(send, "https://x/y")
    assert sleeps == [30.0]


def test_a_server_error_is_retried_a_little_and_then_fails_with_its_status(sleeps):
    calls = []
    with pytest.raises(ServiceError, match="HTTP 502: answer 502") as raised:
        policy(server_retries=1).run(send_from([502, 502], calls), "https://x/y")
    assert len(calls) == 2 and raised.value.status == 502
    assert policy(server_retries=1).run(send_from([503, 200]), "https://x/y").status_code == 200


def test_a_network_error_is_retried_and_then_reported(sleeps):
    calls = []
    down = httpx.ConnectError("no route")
    with pytest.raises(ServiceError, match="network error: ConnectError: no route"):
        policy(network_retries=1).run(send_from([down, down], calls), "https://x/y")
    assert len(calls) == 2
    assert policy(network_retries=1).run(send_from([down, 200]), "https://x/y").status_code == 200


def test_other_client_errors_fail_at_once_and_a_quota_refusal_starts_the_cooldown(sleeps):
    calls = []
    p = policy()
    with pytest.raises(ServiceError, match="HTTP 422") as raised:
        p.run(send_from([422], calls), "https://x/y")
    assert len(calls) == 1 and raised.value.status == 422 and sleeps == []
    p.run(send_from([200]), "https://x/y")                                     # a 422 is not a limit: no cooldown
    with pytest.raises(ServiceError, match="HTTP 402"):
        p.run(send_from([402], calls), "https://x/y")
    with pytest.raises(ServiceError, match="not calling again"):
        p.run(send_from([200], calls), "https://x/y")
    assert len(calls) == 2


def test_calls_are_spaced_by_the_minimum_interval(monkeypatch):
    now, waited = [100.0], []
    monkeypatch.setattr(http_calls.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(http_calls.time, "sleep", lambda s: (waited.append(s), now.__setitem__(0, now[0] + s)))
    p = policy(min_interval=0.5)
    p.run(send_from([200]), "https://x/y")
    now[0] += 0.2                                   # the second call comes 0.2 s after the first
    p.run(send_from([200]), "https://x/y")
    assert waited == [pytest.approx(0.3)]
