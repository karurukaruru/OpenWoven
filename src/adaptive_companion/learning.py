from __future__ import annotations

import threading
from typing import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from .aggregator import EvidenceAggregator
from .observer import Observer, RuleBasedObserver
from .storage import SQLiteStore


class LearningLoop:
    def __init__(
        self, store: SQLiteStore, observer: Observer | None = None,
        aggregator: EvidenceAggregator | None = None, workers: int = 4,
        on_completed: Callable | None = None,
    ):
        self.store = store
        self.observer = observer or RuleBasedObserver()
        self.aggregator = aggregator or EvidenceAggregator(store)
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="learning")
        self._futures: set[Future] = set()
        self._errors: list[BaseException] = []
        self._lock = threading.Lock()
        self.on_completed = on_completed

    def submit(self, message_id: str) -> Future:
        future = self.executor.submit(self.process, message_id)
        return self._track(future)

    def submit_background(self, callback: Callable) -> Future:
        return self._track(self.executor.submit(callback))

    def _track(self, future: Future) -> Future:
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard)
        return future

    def process(self, message_id: str):
        message = self.store.get_message(message_id)
        if not message or message.role != "user":
            return self.store.get_aul()
        self.store.update_learning_status(message_id, "processing")
        try:
            evidence = self.observer.observe(message)
            affected = self.store.replace_evidence_for_source(message_id, evidence)
            state = self.aggregator.aggregate(force_keys=affected)
            self.store.update_learning_status(message_id, "complete")
            if self.on_completed:
                try:
                    self.on_completed(message)
                except Exception as exc:
                    self.store.set_metadata('memory_maintenance_error', type(exc).__name__)
            return state
        except Exception:
            self.store.update_learning_status(message_id, "failed")
            raise

    def recover_pending(self, limit: int | None = None) -> int:
        messages = self.store.list_messages_for_learning(limit)
        for message in messages:
            self.submit(message.id)
        return len(messages)

    def wait(self, raise_errors: bool = True) -> None:
        while True:
            with self._lock:
                pending = list(self._futures)
            if not pending:
                with self._lock:
                    error = self._errors.pop(0) if raise_errors and self._errors else None
                    if not raise_errors:
                        self._errors.clear()
                if error:
                    raise RuntimeError("asynchronous learning failed") from error
                return
            for future in pending:
                try:
                    future.result()
                except Exception:
                    if raise_errors:
                        raise

    def _discard(self, future: Future) -> None:
        with self._lock:
            error = future.exception()
            if error is not None:
                self._errors.append(error)
            self._futures.discard(future)

    def close(self) -> None:
        try:
            self.wait()
        finally:
            self.executor.shutdown(wait=True)
