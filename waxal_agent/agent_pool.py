"""Agent turns of different people in parallel, in separate processes.

CodeAgent keeps its session in process-wide state, so one process can run one turn at a time. This pool starts WAXAL_WORKERS
(default 4) processes, each running AgentTurns, and gives every turn to a free one. A person's turns never overlap (their
conversation is one file), and a turn waits only when every worker is busy. The workers start on the first turn.
The person's own documents are refreshed here, before the turn, so that the workers only read files.
"""

from __future__ import annotations

import itertools
import logging
import multiprocessing
import queue
import threading
from concurrent.futures import Future

log = logging.getLogger("waxal.pool")


def _worker(data, documents, tasks, control, results, instructions=None, skills=None) -> None:
    """The child process: one AgentTurns, one turn at a time; a message on `control` stops the running turn."""
    from .agent import AgentTurns
    turns = AgentTurns(data, documents=documents, instructions=instructions, skills=skills)

    def watch() -> None:
        while control.get() is not None:
            turns.stop()
    threading.Thread(target=watch, daemon=True).start()
    while (task := tasks.get()) is not None:
        number, user_id, english = task
        try:
            results.put((number, turns.ask_full(user_id, english), None))
        except Exception as e:
            results.put((number, None, f"{type(e).__name__}: {e}"))


class AgentPool:
    def __init__(self, workers: int, data, documents=None, refresh=None, target=_worker, instructions=None, skills=None) -> None:
        self.target = target  # the child's function (tests bring a stand-in)
        self.instructions, self.skills = instructions, skills
        self.size, self.data, self.documents, self.refresh = max(1, workers), data, documents, refresh
        self._ctx = multiprocessing.get_context("spawn")  # CodeAgent's state and our threads: never fork
        self._cond = threading.Condition()
        self._workers: list[dict] = []
        self._user_locks: dict[str, threading.Lock] = {}
        self._numbers = itertools.count()
        self._futures: dict[int, Future] = {}
        self._results = None

    def _start(self) -> None:
        self._results = self._ctx.Queue()
        self._workers = [self._spawn() for _ in range(self.size)]
        threading.Thread(target=self._collect, daemon=True, name="agent-pool").start()

    def _spawn(self) -> dict:
        tasks, control = self._ctx.Queue(), self._ctx.Queue()
        process = self._ctx.Process(target=self.target, args=(self.data, self.documents, tasks, control, self._results),
                                   kwargs={"instructions": self.instructions, "skills": self.skills}, daemon=True)
        process.start()
        return {"process": process, "tasks": tasks, "control": control, "user": None}

    def _collect(self) -> None:
        """Hand each result to the turn waiting for it; a worker that died gives its turn an error and is replaced."""
        while True:
            try:
                number, answer, error = self._results.get(timeout=1)
            except queue.Empty:
                with self._cond:
                    for i, w in enumerate(self._workers):
                        if w["user"] is not None and not w["process"].is_alive():
                            log.error("An agent worker died during a turn; starting another")
                            self._workers[i] = self._spawn()
                            self._cond.notify_all()
                            for n, f in list(self._futures.items()):
                                if getattr(f, "worker", None) == i:
                                    self._futures.pop(n).set_exception(RuntimeError("the agent process stopped"))
                continue
            future = self._futures.pop(number, None)
            if future is not None:
                future.set_exception(RuntimeError(error)) if error else future.set_result(answer)

    def ask(self, user_id: str, english: str) -> tuple[str, list[str]]:
        reply, notes, _ = self.ask_full(user_id, english)
        return reply, notes

    def ask_full(self, user_id: str, english: str) -> tuple[str, list[str], list[dict]]:
        """(the reply, the notes, the links the agent shared), as AgentTurns.ask_full."""
        if self.refresh:
            self.refresh(user_id, self._personal(user_id))
        with self._cond:
            if not self._workers:
                self._start()
            user_lock = self._user_locks.setdefault(user_id, threading.Lock())
        with user_lock:  # one turn at a time per person
            with self._cond:
                while (index := next((i for i, w in enumerate(self._workers) if w["user"] is None), None)) is None:
                    self._cond.wait()
                worker = self._workers[index]
                worker["user"] = user_id
                number = next(self._numbers)
                future = self._futures[number] = Future()
                future.worker = index
                worker["tasks"].put((number, user_id, english))
            try:
                return future.result()
            finally:
                with self._cond:
                    self._workers[index]["user"] = None
                    self._cond.notify_all()

    def _personal(self, user_id: str):
        from pathlib import Path

        from .agent import user_folder
        return user_folder(Path(self.data), user_id) / "documents"

    def stop(self, user_id: str | None = None) -> bool:
        """Stop the running turn of one person (or of everybody). False when none is running."""
        stopped = False
        with self._cond:
            for w in self._workers:
                if w["user"] is not None and user_id in (None, w["user"]):
                    w["control"].put(True)
                    stopped = True
        return stopped
