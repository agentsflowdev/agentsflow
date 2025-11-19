from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class TemporalTestSettings:
    address: str
    namespace: str
    task_queue: str
    task_queue_static: bool

    @classmethod
    def from_env(cls) -> TemporalTestSettings | None:
        address = os.getenv("TEMPORAL_TEST_ADDRESS")
        if not address:
            return None
        namespace = os.getenv("TEMPORAL_TEST_NAMESPACE", "default")
        task_queue_env = os.getenv("TEMPORAL_TEST_TASK_QUEUE")
        task_queue = task_queue_env or "test-sdlc"
        return cls(
            address=address,
            namespace=namespace,
            task_queue=task_queue,
            task_queue_static=task_queue_env is not None,
        )
