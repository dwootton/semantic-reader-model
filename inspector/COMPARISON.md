# Try whole-page and region-composed hierarchies

For local inference, start Ollama in one terminal (the model is already downloaded on this Mac):

```sh
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve
```

Then start the comparison server from the project directory in another terminal:

```sh
python3 inspector/compare_server.py --port 8766 --backend ollama --model qwen3.5:2b --local-model qwen3.5:0.8b --num-ctx 131072 --input-mode compact-budget
```

The **Next run model** selector offers the configured local model and Gemini Flash. It keeps the same capture and model for both strategies within a run. Changing the selection only changes future runs; saved results keep their original model identity. The **Input for next run** selector switches between compact budget HTML and the original normalized DOM. Compact HTML is the default for new runs. To use the original lab configuration:

```sh
python3 inspector/compare_server.py --port 8766 --input-mode legacy
```

Open [the comparison](http://127.0.0.1:8766/compare.html). The existing inspector remains available at [index.html](http://127.0.0.1:8766/index.html) on the same server.

Choose a saved capture, then **Run whole page**, **Compose regions**, or **Run both**. Start with GOV.UK, whose capture is relatively small. Expand the resulting groups and select one to inspect its original source elements. Inspect the call records to see the exact evidence and output at each stage. Export the run JSON to retain the result or share it for review.

Within a run, both methods use the same input representation and model. Existing authored hierarchies are excluded from model inputs. Whole-page prediction receives the selected representation of a complete document. Regional prediction receives bounded partitions with surrounding context. Compact runs assemble the resulting local groups in code; legacy runs retain the separate model composition call. Region size is a maximum source-node count, not a model context-window setting.

Sibling groups and source leaves follow the earliest source position among their descendants. This shared presentation rule prevents composition insertion order from moving a footer ahead of the page content. The separate source fallback appears last. Reading-order prediction is not part of this initial model task. Both paths permit at most 46 model groups, plus the synthetic root and optional fallback; legacy regional calls share 38 groups and reserve eight for model composition. Compact regional calls share the 46-group budget and use no model composition call. Inputs larger than the regional call budget fail explicitly with a suggestion to increase region size, without blocking the whole-page method.

This test now supports **local Ollama inference** and the **Gemini lab teacher**. Qwen3.5 0.8B and 2B are installed as off-the-shelf checkpoints, without project fine-tuning. This helps inspect the proposed learning targets and their failure modes; it does not establish how well a trained student will learn either target. Override `--model` with another installed Ollama model when using `--backend ollama`, or a Vertex model ID when using `--backend lab`. Repeat `--local-model` to offer additional installed checkpoints.

Local inference uses only `127.0.0.1:11434`; the transport bypasses proxies, rejects redirects and cloud-backed models, and never downloads models or falls back to cloud. It checks the installed model, digest and supported context before generation, then verifies the actual loaded context and digest before accepting a response. Ollama receives an explicit context size and a JSON response schema. A conservative UTF-8 byte bound reserves space for output and rejects oversized prompts rather than truncating them. This can reject captures whose actual token count would fit; increase supported context or reduce region size when appropriate. Only the chosen local model needs to be installed. On this Mac, Ollama was repaired by upgrading Homebrew's existing package from 0.30.5 to 0.33.3; Qwen3.5 0.8B and 2B were downloaded once from the official Ollama library (approximately 1 GB and 2.7 GB).

When Gemini Flash is selected, model requests use the explicit account, project, and CLI configuration in local `.lab-config.json`, through the verified client. Authentication is checked on the first model request. The server never uses application-default credentials. It needs the existing gcloud login and network access; no new dependencies, model downloads, VM changes, or website actions are required. The selected saved source capture is sent to the lab model when a run starts.

Lab runs have a ten-minute budget, at most 40 request attempts, and at most two attempts per model call. The lab client retains its ten-second request spacing. Local runs have a thirty-minute budget and one attempt per model call, without artificial pacing. Local timing includes loading and inference; call records retain Ollama's prompt/decode/load timing, context and model digest. Lab timing includes pacing, authentication when needed, service latency and inference. In **Run both**, whole-page generation runs first, so model loading and cache reuse can affect the comparison. Use randomized repeated runs before drawing latency conclusions across strategies or backends.

Results and request records are saved under `runs/comparison/<run-id>/`. Completed results survive reloads and server restarts. If one approach fails, any completed result remains available. An interrupted in-progress run is marked failed after restart. No credentials are saved with the run. Only one job can run at a time, and the HTTP server accepts loopback requests with same-origin checks for model-triggering actions.

## Compact HTML input

This path uses the user's [COMPACT.md](../experiments/dom-downsampling/COMPACT.md) implementation and its existing audited budget artifacts in `runs/compression/compact-semantic/`. The loader verifies every selected document's audit, source snapshot, emitted HTML, source map, request, and compressor/runner hashes. Current source files must still match the recorded originals. Stale or failed inputs stop before inference. All 14 datasets are supported; EWH keeps its two documents separate. It does not modify the compactor or infer joins to the older inspector IDs.

Each call receives task instructions, a response schema and **one compact HTML representation**. Source maps, original snapshots, capture metadata, geometry, raw URLs and recovery artifacts stay outside model input. Source-reference marker values are namespaced per document, with the rewrite recorded locally. The source pane uses a separate emitted-HTML snapshot bound to the job's hash; `d0:1k` is never treated as an old inspector `eN` ID.

Regional partitioning preserves fitting subtrees, groups nearby siblings, and includes read-only ancestor/heading context. Nested heading text and inherited partial scope are preserved. Outputs may reference only schema-allowed exposed IDs; there are no literal source-ID placeholders. Assembly preserves local trees and adds only uniquely supported cross-region containment links, leaving other roots as siblings. It does not invent cross-region semantic groupings.

**The budget profile preserves a semantic evidence floor and may still be partial.** Ordinary controls and record boundaries now survive even when this exceeds the 10% element target. `needs_expansion` requests are preserved and shown, with no automatic expansion of raw HTML. Coverage measures assignments among exposed compact references, not original-page completeness. Full source recovery is not part of this model pass. Even zero expansion requests do not make deferred content observed; result warnings still mark the partial view.

Timings measure model calls and assembly over **verified precomputed compact inputs**. Artifact loading time is recorded separately as `preparation_seconds`; offline Chromium compression time is not included. System/user UTF-8 bytes and response-schema bytes are recorded separately. Token counts come from the actual inference backend. The corpus's 10% element target does not imply a 10% token budget or semantic completeness.

If source or compressor files change, regenerate the audited artifacts using the commands in COMPACT.md before rerunning. The UI preserves legacy runs and offers the original input mode for comparisons; input compression and deterministic assembly are separate changes, so do not attribute all latency differences to compression alone.

For a quick qualitative test, try locating the same information in each tree: a particular form field, a story and its byline, or a control with its explanatory text. Compare meaningful groups and missing associations as well as tree depth. Source fallback is accounted for separately from model grouping coverage. Access to the raw source alone does not mean the semantic grouping succeeded.

The inputs are saved DOM captures with available text, attributes, and geometry; they are not freshly computed browser accessibility trees. Screenshot evidence is not sent to the model. No model has been fine-tuned by this tool, and the saved page's original controls are not activated. A locally generated result may still fail ID, duplicate-membership or topology validation; these are recorded as model failures rather than silently repaired. Rejected requests, outputs and validation errors remain inspectable in the run records, even when no hierarchy was accepted.

Saved links include `?run=<run-id>`. A SHA-256 digest binds a run to its input capture. Reopening a run still shows generated hierarchies when source data has changed, but disables unverified source evidence. The model transport uses an optional [Vertex response schema](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1beta1/GenerationConfig) alongside local checks of IDs, membership, and parent relationships; existing harness callers keep their previous configuration.

Implementation files: `inspector/compact_input.py`, `compact_comparison.py`, `test_compact_input.py`, `test_compact_comparison.py`, `inspector/compare.html`, `compare.css`, `compare.mjs`, `compare_server.py`, `comparison.py`, `test_compare_server.py`, and `test_comparison.py`; documentation in this file and `inspector/README.md`; the optional schema transport and its regression in `harness/model.py` and `tests/test_model_input_limit.py`. The test reuses the existing capture catalog and lab client, with no new dependencies.

Local transport and regression tests live in `harness/ollama_model.py` and `tests/test_ollama_model.py`. They use the Python standard library and the installed Ollama runtime, without adding Python or JavaScript dependencies. API references: [Ollama chat](https://docs.ollama.com/api/chat), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs), and [context configuration](https://docs.ollama.com/context-length).

## Checks

```sh
python3 -m unittest discover -s inspector -p 'test_*.py' -v
python3 -m unittest discover -s tests -p test_ollama_model.py -v
ruff check inspector/comparison.py inspector/compare_server.py inspector/test_comparison.py inspector/test_compare_server.py
mypy --follow-imports=skip inspector/comparison.py inspector/compare_server.py
node --check inspector/compare.mjs
```

## Experimental candidate selection

Choose **Compact · select proposed groups** to retain the same compact HTML and partitions while changing the prediction task. Code proposes named source containers; the model returns selected candidate IDs and expansion requests. Titles, membership and nesting are derived locally. Both whole-page and regional buttons support this mode. Standard compact prediction remains the default.

This is a narrower task: arbitrary groups, cross-branch regrouping and generated labels are unsupported. Each container uses an explicit name or its first eligible heading, so labels can be overbroad or repeated. Candidate overflow is explicit, and sources remain in the unchanged HTML/fallback. The 88.3% exposed-reference coverage in the first GOV.UK run is not a semantic-quality score.

The first full warmed local 2B run took 8.51 seconds over five regions. See [measurements and limitations](../docs/research/regional-latency-options.md). The reusable probe tool is `experiments/regional-speed/benchmark.py`; its `standard`, `lean`, `anchors`, and `selection` modes preserve failed responses for diagnosis. Only selection is exposed as an additional UI mode. Shared source-label parsing and membership decoding live in the experimental modules; no dependencies were added.
