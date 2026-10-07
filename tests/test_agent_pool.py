import os
import threading
import time

from waxal_agent.agent_pool import AgentPool


def slow_worker(data, documents, tasks, control, results, **_):
    """A stand-in for the agent process: a turn takes 1 s, or until it is stopped."""
    stopped = threading.Event()

    def watch():
        while control.get() is not None:
            stopped.set()
    threading.Thread(target=watch, daemon=True).start()
    while (task := tasks.get()) is not None:
        number, user, text = task
        if text == "die":
            os._exit(1)
        stopped.clear()
        stopped.wait(1 if text != "long" else 30)
        results.put((number, (f"{user}:{text}:{os.getpid()}", ["stopped"] if stopped.is_set() else [], [{"url": "https://x"}]), None))


def run(pool, user, text, out):
    out[(user, text)] = pool.ask_full(user, text)


def test_different_people_run_in_parallel_and_the_same_person_in_turn(tmp_path):
    pool = AgentPool(2, tmp_path, target=slow_worker)
    pool.ask("warm", "up")  # starts the processes
    out = {}
    started = time.monotonic()
    threads = [threading.Thread(target=run, args=(pool, u, "hi", out)) for u in ("a", "b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert time.monotonic() - started < 1.8                                           # two turns, one second
    assert out[("a", "hi")][0].split(":")[2] != out[("b", "hi")][0].split(":")[2]     # two different processes
    started = time.monotonic()
    threads = [threading.Thread(target=run, args=(pool, "c", t, out)) for t in ("x", "y")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert time.monotonic() - started >= 1.9                                          # the same person: one after the other


def test_stop_reaches_only_that_persons_turn_and_a_dead_worker_gives_an_error(tmp_path):
    pool = AgentPool(2, tmp_path, target=slow_worker)
    out = {}
    long_turn = threading.Thread(target=run, args=(pool, "a", "long", out))
    long_turn.start()
    time.sleep(1.5)
    assert pool.stop("b") is False and pool.stop("a") is True
    long_turn.join(10)
    assert out[("a", "long")][1] == ["stopped"] and out[("a", "long")][2] == [{"url": "https://x"}]
    try:
        pool.ask("d", "die")
        raise AssertionError("expected an error")
    except RuntimeError as e:
        assert "stopped" in str(e)
    assert pool.ask("e", "ok")[0].startswith("e:ok")                                  # the pool still works
