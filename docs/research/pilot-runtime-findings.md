# Pilot runtime diagnosis — 12 September 2026

Timing snapshot from run E, about 14.3 minutes after its 19:38:46 UTC start. This is an execution profile, not a hierarchy-quality score.

| Component | Recorded seconds |
|---|---:|
| Time inside API requests, including rejected attempts | 347.5 |
| Deliberate request pacing | 171.9 |
| Scheduled retry backoff | 165.0 |
| Three full website resets | 79.3 |
| Remaining capture/local work and snapshot timing difference | approximately 96.1 |

The ledger contains 45 requests, including seven HTTP 429 capacity/rate-limit responses. Successful navigation responses have a median of 2.59 seconds; hierarchy generation 9.13 seconds; the two annotation passes about 4.5–5.2 seconds each. Rejected requests also contribute to API time, so that bucket is not pure model inference time.

Three new episodes had reached terminal states; two earlier episodes were retained. Projection reuse occurred on four of nine generated-projection captures. One larger customer capture requires 221,086 input tokens because the current generator receives the full normalized AX graph.

Avoidable design overhead:

- All trials execute serially, including two annotation passes before the next trial.
- A ten-second minimum request-start interval was added as conservative recovery after HTTP 429s. It is not ten seconds added after every response.
- Every trial recreates the website container, even for these read-only task intentions, to isolate possible agent side effects and server state.
- Navigation history includes full prior observation/result records and engineering metadata.
- Hierarchies can hand off to several low-level source containers, each requiring another inference.

Earlier provisioning, implementation bugs, debugging, and restarts account for additional elapsed project time; they are not a fundamental requirement of the experiment.

A faster execution schedule should separate annotation work from browser trials, use isolated site replicas for safe parallel trials, and use measured adaptive throttling with a shared budget. Compact generator inputs and navigator history are promising, but change what the models see and should be versioned and tested. Skipping source wrappers or batching navigation moves also changes the measured navigation protocol.

Blindly removing pacing or increasing concurrency could worsen the still-present HTTP 429 errors. This diagnosis did not interrupt or alter the running comparison.
