# Optional benchmark environment

The default development path is local and credential-free. Browser benchmark runs are a separate, explicitly configured workflow.

1. Create a Python 3.12 environment and install the pinned benchmark dependencies from `benchmark-requirements.txt`.
2. Prepare the optimized WebArena Verified Shopping Admin container and Chromium runtime. The shell helpers target Ubuntu 24.04; inspect them before running as root. They install system packages and write under `/opt/semantic-reader`.
3. Copy `.lab-config.example.json` to `.lab-config.json` at the repository root, then specify the intended CLI configuration, account, and project. Configure and authenticate that account explicitly in `gcloud`. No account identity or credential is bundled in this repository.
4. The cloud client checks those identities before minting a short-lived token. `refresh_token.py` sends a verified envelope privately over SSH; `prepare_auth.py` provisions public benchmark credentials outside repository artifacts. Never add their output to Git.
5. Inspect `python3 -m harness.run --help` or `python3 -m harness.parallel_run --help`. Use explicit call/time budgets, isolated benchmark origins, and an automatic VM stop time. Model identifiers in the historical pilot must be checked for availability in your environment.

The historical deployment used an 8-vCPU, 32-GB VM with four independent localhost site/control port pairs. Each worker owns and resets its own benchmark container; model requests share one per-model pacing schedule and call budget.

When running the process pool as a regular user in a system service, SSH logout can remove its POSIX IPC objects under the systemd `RemoveIPC` policy. The dedicated pilot VM used `semantic-reader-logind.conf` under `/etc/systemd/logind.conf.d/` and restarted logind. This changes VM-wide login cleanup behavior: review it for your deployment rather than applying it to a shared machine without considering other users. `check_process_pool.py` verifies delayed two-to-four-process expansion after logout.

The pilot VM is stopped. Its account-specific operating notes remain in local-only `infra/README.md` and are deliberately excluded from the repository. No new cloud workload is started by this setup documentation.
