import time

from waxal_agent import maintenance


def test_the_clean_up_runs_now_and_again_each_interval(monkeypatch):
    runs = []
    monkeypatch.setattr(maintenance, "run_once", lambda: runs.append(1))
    thread = maintenance.start(interval=0.05)
    time.sleep(0.4)
    thread.stop()
    thread.join(timeout=2)
    assert len(runs) >= 3 and not thread.is_alive()


def test_it_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("WAXAL_CLEANUP", "off")
    monkeypatch.setattr(maintenance, "run_once", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    assert maintenance.start() is None


def test_it_deletes_what_coding_agent_says_is_old_and_keeps_the_rest(tmp_path):
    import os

    from coding_agent import cleanup
    memory = tmp_path / "memory"
    old, fresh = memory / "alice-1", memory / "bob-2"
    for folder in (old, fresh):
        folder.mkdir(parents=True)
        (folder / "conversation.json").write_text("[]")
        (folder / "notes.md").write_text("notes")
    long_ago = time.time() - 100 * 86_400
    for file in old.iterdir():
        os.utime(file, (long_ago, long_ago))
    summary = cleanup.run(tmp_path / "backups", memory)          # the call that maintenance.run_once makes (with its defaults)
    assert not old.exists() and (fresh / "notes.md").exists() and "1 unused project memories" in summary


def test_run_once_logs_the_summary(monkeypatch, caplog):
    from coding_agent import cleanup
    monkeypatch.setattr(cleanup, "run", lambda: "Clean-up: nothing to delete")
    with caplog.at_level("INFO", logger="waxal.cleanup"):
        assert maintenance.run_once() == "Clean-up: nothing to delete"
    assert "nothing to delete" in caplog.text
