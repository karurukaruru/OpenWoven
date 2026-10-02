"""Process-local composer gate. No keyboard text leaves the Android composer."""
from __future__ import annotations

import threading
import time


class ComposerGate:
    def __init__(self):
        self.lock = threading.RLock()
        self.states: dict[str, tuple[float, bool, int]] = {}

    def note(self, conversation: str, has_draft: bool) -> None:
        with self.lock:
            revision = self.states.get(conversation, (0, False, 0))[2] + 1
            self.states[conversation] = (time.monotonic(), has_draft, revision)

    def revision(self, conversation: str) -> int:
        with self.lock:
            return self.states.get(conversation, (0, False, 0))[2]

    def idle(self, conversation: str, seconds: int) -> bool:
        with self.lock:
            touched, draft, _ = self.states.get(conversation, (0, False, 0))
            return not draft and time.monotonic() - touched >= seconds


composer_gate = ComposerGate()
