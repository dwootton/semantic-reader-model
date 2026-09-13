"""Exercise delayed process-pool expansion after the SSH session exits."""

from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import time


def identify(delay):
    time.sleep(delay)
    return os.getpid()


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as pool:
        initial = [pool.submit(identify, 1) for _ in range(2)]
        first = sorted({job.result() for job in initial})
        time.sleep(30)
        expanded = [pool.submit(identify, 2) for _ in range(4)]
        second = sorted({job.result() for job in expanded})
        result = {"initial_pids": first, "expanded_pids": second,
                  "passed": len(first) == 2 and len(second) == 4}
        Path("/tmp/semantic-reader-pool-check.json").write_text(json.dumps(result))
        print(json.dumps(result), flush=True)
        if not result["passed"]:
            raise SystemExit(1)
