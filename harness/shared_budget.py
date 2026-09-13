"""Process-safe request admission for workers on one host during one run.

Deadlines and pacing use time.monotonic(), so a run's database must not be
reused after reboot. Authenticate before reserve(), then send the request
immediately; each retry must obtain its own admission.
"""

from contextlib import closing
import math
from pathlib import Path
import sqlite3
import time


class BudgetExhausted(RuntimeError):
    pass


class DeadlineExceeded(RuntimeError):
    pass


class SharedBudget:
    def __init__(self, path, max_calls=None, min_interval=10):
        self.path = Path(path)
        if max_calls is None:
            if not self.path.is_file():
                raise ValueError("Shared budget must be initialized by the controller")
            # Attaching workers read the persisted configuration, never reset it.
            self.usage()
            return
        if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 0:
            raise ValueError("max_calls must be a nonnegative integer")
        if not math.isfinite(min_interval) or min_interval < 0:
            raise ValueError("min_interval must be finite and nonnegative")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS budget "
                    "(id INTEGER PRIMARY KEY CHECK(id=1), max_calls INTEGER NOT NULL, "
                    "min_interval REAL NOT NULL, reserved_calls INTEGER NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS models "
                    "(model TEXT PRIMARY KEY, reserved_calls INTEGER NOT NULL, next_start REAL NOT NULL)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO budget VALUES (1, ?, ?, 0)",
                    (max_calls, min_interval),
                )
                config = connection.execute(
                    "SELECT max_calls, min_interval FROM budget WHERE id=1"
                ).fetchone()
                if config != (max_calls, min_interval):
                    raise ValueError("Existing shared budget configuration differs")

    def reserve(self, model, deadline=None):
        """Admit one attempt when its per-model start slot is available.

        Waiting workers do not consume calls or reserve future slots. A call ID
        is conservative accounting: if the caller crashes after admission, it
        remains counted rather than risking an overspend.
        """
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonempty string")
        if deadline is not None and not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        started = time.monotonic()
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise DeadlineExceeded("Shared request time budget exhausted")
            delay = 0.01
            with closing(sqlite3.connect(self.path, timeout=0.05)) as connection:
                try:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        now = time.monotonic()
                        if deadline is not None and now >= deadline:
                            raise DeadlineExceeded("Shared request time budget exhausted")
                        cap, interval, used = connection.execute(
                            "SELECT max_calls, min_interval, reserved_calls FROM budget WHERE id=1"
                        ).fetchone()
                        if used >= cap:
                            raise BudgetExhausted("Shared API request budget exhausted")
                        row = connection.execute(
                            "SELECT next_start FROM models WHERE model=?", (model,)
                        ).fetchone()
                        delay = max(0.0, row[0] - now) if row else 0.0
                        if delay == 0:
                            connection.execute(
                                "UPDATE budget SET reserved_calls=reserved_calls+1 WHERE id=1"
                            )
                            connection.execute(
                                "INSERT INTO models VALUES (?, 1, ?) "
                                "ON CONFLICT(model) DO UPDATE SET "
                                "reserved_calls=reserved_calls+1, next_start=excluded.next_start",
                                (model, now + interval),
                            )
                            result = {"call": used + 1, "pacing_seconds": now - started}
                        else:
                            result = None
                    if result is not None:
                        return result
                except sqlite3.OperationalError as error:
                    if "locked" not in str(error).lower():
                        raise
            # Recheck the cap periodically and never sleep while holding a lock.
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if delay >= remaining:
                    raise DeadlineExceeded("Shared request pacing exceeds time budget")
            time.sleep(min(delay, 0.1))

    def usage(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            # One read transaction keeps the global and model counts consistent.
            with connection:
                connection.execute("BEGIN")
                cap, interval, used = connection.execute(
                    "SELECT max_calls, min_interval, reserved_calls FROM budget WHERE id=1"
                ).fetchone()
                per_model = {
                    model: {"reserved_calls": count, "next_start": next_start}
                    for model, count, next_start in connection.execute(
                        "SELECT model, reserved_calls, next_start FROM models ORDER BY model"
                    )
                }
        return {
            "reserved_calls": used, "max_calls": cap,
            "min_interval": interval, "per_model": per_model,
        }
