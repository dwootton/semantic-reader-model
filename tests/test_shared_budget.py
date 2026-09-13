from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from harness.shared_budget import BudgetExhausted, DeadlineExceeded, SharedBudget


def consume(path):
    budget = SharedBudget(path)
    calls = []
    while True:
        try:
            calls.append(budget.reserve("flash")["call"])
        except BudgetExhausted:
            return calls


class SharedBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "budget.sqlite")

    def test_processes_share_cap_and_unique_call_ids(self):
        budget = SharedBudget(self.path, max_calls=31, min_interval=0)
        with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as pool:
            calls = [call for group in pool.map(consume, [self.path] * 4) for call in group]
        self.assertEqual(sorted(calls), list(range(1, 32)))
        self.assertEqual(budget.usage()["reserved_calls"], 31)
        self.assertEqual(budget.usage()["per_model"]["flash"]["reserved_calls"], 31)

    def test_threads_observe_per_model_spacing(self):
        SharedBudget(self.path, max_calls=6, min_interval=0.04)

        def reserve(_):
            return SharedBudget(self.path).reserve("flash")["call"]

        # Only one start per 40 ms: three concurrent admissions require >=80 ms.
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = sorted(pool.map(reserve, range(3)))
        self.assertEqual(results, [1, 2, 3])
        self.assertGreaterEqual(time.monotonic() - started, 0.08)

    def test_deadline_rechecked_after_database_lock_wait(self):
        budget = SharedBudget(self.path, 1, 0)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(DeadlineExceeded):
                budget.reserve("flash", deadline=time.monotonic() + 0.01)
        finally:
            connection.rollback()
            connection.close()
        self.assertEqual(budget.usage()["reserved_calls"], 0)

    def test_models_have_independent_slots(self):
        budget = SharedBudget(self.path, max_calls=3, min_interval=10)
        budget.reserve("flash")
        # A global pacing gate would reject this one-second deadline.
        self.assertEqual(budget.reserve("pro", deadline=time.monotonic() + 1)["call"], 2)
        with self.assertRaises(DeadlineExceeded):
            budget.reserve("flash", deadline=time.monotonic() + 0.01)
        self.assertEqual(budget.usage()["reserved_calls"], 2)

    def test_expired_deadline_does_not_consume_call(self):
        budget = SharedBudget(self.path, max_calls=1, min_interval=0)
        with self.assertRaises(DeadlineExceeded):
            budget.reserve("flash", deadline=time.monotonic() - 1)
        self.assertEqual(budget.usage()["reserved_calls"], 0)

    def test_attach_and_reinitialize_preserve_usage_and_configuration(self):
        with self.assertRaises(ValueError):
            SharedBudget(self.path)
        original = SharedBudget(self.path, max_calls=2, min_interval=0.1)
        original.reserve("flash")
        self.assertEqual(SharedBudget(self.path).usage(), original.usage())
        self.assertEqual(SharedBudget(self.path, 2, 0.1).usage(), original.usage())
        with self.assertRaises(ValueError):
            SharedBudget(self.path, 100, 0)
        self.assertEqual(original.usage()["max_calls"], 2)

    def test_zero_budget_and_invalid_bounds(self):
        for max_calls, interval in [(-1, 0), (1.5, 0), (True, 0), (1, -1), (1, float("nan"))]:
            with self.assertRaises(ValueError):
                SharedBudget(self.path, max_calls, interval)
        budget = SharedBudget(self.path, 0, 0)
        with self.assertRaises(BudgetExhausted):
            budget.reserve("flash")


if __name__ == "__main__":
    unittest.main()
