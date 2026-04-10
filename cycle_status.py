"""
Cycle status tracker: writes output/cycle_status.json for frontend polling.
Thread-safe for use with ThreadPoolExecutor.
"""

import json
import time
import os
import threading
import logging

logger = logging.getLogger(__name__)

STATUS_FILE = os.path.join("output", "cycle_status.json")


class CycleStatus:
    def __init__(self):
        self._lock = threading.Lock()
        self._total = 0
        self._completed = 0
        self._phase = ""

    def update(self, phase: str, progress: int):
        """Update status file with current phase and progress."""
        with self._lock:
            data = {
                "phase": phase,
                "progress": min(100, max(0, progress)),
                "updated_at": int(time.time() * 1000),
            }
            try:
                os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
                with open(STATUS_FILE, "w") as f:
                    json.dump(data, f)
            except IOError as e:
                logger.debug(f"Error writing cycle status: {e}")

    def start_phase(self, phase: str, total: int = 0):
        """Start a new phase with optional total for progress tracking."""
        self._phase = phase
        self._total = total
        self._completed = 0
        self.update(phase, 0)

    def tick(self):
        """Increment completed counter and update progress."""
        self._completed += 1
        if self._total > 0:
            progress = int(self._completed / self._total * 100)
        else:
            progress = 0
        self.update(self._phase, progress)

    def ready(self):
        """Mark cycle as complete."""
        self.update("Ready", 100)
