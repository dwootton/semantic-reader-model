# Compare full and compressed DOMs

Open [the local comparison](http://127.0.0.1:8768/compression.html). Start it with:

```sh
python3 inspector/serve.py --port 8768
```

The page includes all 15 saved documents (14 datasets, including the dashboard's separate embedded frame). Choose an example and a compression profile. Full and compressed trees are independently searchable and scrollable.

- Click either tree to expand the counterpart's ancestor path and reveal it. Exact mappings are highlighted in teal.
- An omitted source node has no exact counterpart. When available, its containing compressed group is shown in amber and explicitly labeled representative. Excluded nodes clear the opposite selection.
- Partial/excerpt badges identify shortened content. The detail panels show full direct text, attributes, and the compression reasons. Large values are initially shortened for display and can be expanded.
- Use arrow keys to navigate, Left/Right to collapse/expand, and Enter/Space to select. Search includes tags, source IDs, direct text and attributes. Selecting a counterpart clears the opposite search so it can be revealed.
- Source parse instability and failed candidate audits remain visible as warnings. A displayed partial tree is not proof of unchanged meaning or organization quality.

The server binds only to loopback. Captured sites are exported as inert JSON and rendered using textContent; scripts, source markup, styles, resources and links are not executed. The full source shown here is the browser-parsed element tree, including template contents, not the historical inspector's truncated text records. Node counts measure elements; text appears on its owning element. Each document loads on demand.

To refresh from the compact experiment artifacts:

```sh
python3 inspector/build_compression_data.py
```

The exporter checks source/artifact hashes and source reference inventories before generating inspector/data/compression. Native html/head nodes missing a wire marker are mapped only after verifying their identities. Ambiguous mappings are never silently treated as exact.

Verification:

```sh
node --test inspector/compression-model.test.mjs
python3 -m unittest inspector.test_compression_data -v
python3 inspector/test_compression_ui.py
```

The browser check requires the loopback server. It tests both selection directions on every document, representative/absent cases, search, profile switching, warnings, and mobile overflow. Screenshots and verification records are in inspector/qa/compression. Static checks cover the Python exporter/browser tests and JavaScript modules. No model calls are made.
