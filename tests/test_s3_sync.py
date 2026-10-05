import boto3
import pytest
from moto import mock_aws

from waxal_agent.agent import AgentTurns
from waxal_agent.s3_sync import S3Documents, mirror


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="bucket")
        yield client


def put(client, key, body=b"x"):
    client.put_object(Bucket="bucket", Key=key, Body=body)


def test_the_library_is_mirrored_changed_and_cleaned(s3, tmp_path):
    put(s3, "documents/a.pdf", b"one")
    put(s3, "documents/sub/b.txt", b"two")
    put(s3, "documents/.hidden", b"no")
    put(s3, "users/221/documents/mine.txt", b"mine")
    assert mirror(s3, "bucket", "documents/", tmp_path) == 2
    assert (tmp_path / "a.pdf").read_bytes() == b"one" and (tmp_path / "sub" / "b.txt").read_bytes() == b"two"
    assert not (tmp_path / ".hidden").exists() and not (tmp_path / "mine.txt").exists()
    assert mirror(s3, "bucket", "documents/", tmp_path) == 0                      # unchanged: nothing downloaded
    put(s3, "documents/a.pdf", b"three!")
    s3.delete_object(Bucket="bucket", Key="documents/sub/b.txt")
    assert mirror(s3, "bucket", "documents/", tmp_path) == 1
    assert (tmp_path / "a.pdf").read_bytes() == b"three!" and not (tmp_path / "sub").exists()


def test_a_persons_documents_are_fetched_on_demand_and_not_too_often(s3, tmp_path):
    put(s3, "users/221/documents/mine.txt", b"mine")
    docs = S3Documents(s3, "bucket", user_ttl=3600)
    docs.refresh_user("221", tmp_path / "221")
    assert (tmp_path / "221" / "mine.txt").read_bytes() == b"mine"
    put(s3, "users/221/documents/more.txt", b"m")
    docs.refresh_user("221", tmp_path / "221")                                  # within the TTL: no new call
    assert not (tmp_path / "221" / "more.txt").exists()
    docs.refresh_user("999", tmp_path / "999")
    assert not (tmp_path / "999").exists()


def test_an_s3_failure_changes_nothing(tmp_path):
    class Broken:
        def get_paginator(self, name):
            raise RuntimeError("down")
    (tmp_path / "kept.txt").write_text("k")
    S3Documents(Broken(), "b").sync_shared(tmp_path)
    S3Documents(Broken(), "b").refresh_user("1", tmp_path / "u")
    assert (tmp_path / "kept.txt").exists()


def test_the_agent_refreshes_a_persons_documents_before_a_turn(tmp_path, monkeypatch):
    calls = []
    turns = AgentTurns(tmp_path, refresh=lambda user, folder: calls.append((user, folder)))
    monkeypatch.setattr("waxal_agent.agent.session.open_project", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError):
        turns.ask("221", "hello")
    assert calls and calls[0][0] == "221" and calls[0][1].name == "documents"
