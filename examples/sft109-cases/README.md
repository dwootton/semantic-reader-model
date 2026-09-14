# SFT-109 qualitative test cases

Three held-out test pages for the [Qwen3.5-9B SFT-109 LoRA adapter](https://huggingface.co/Dwootton/semantic-reader-qwen3.5-9b-sft-109), published in the GitHub Pages inspector on 2026-09-14 at the maintainer's decision so the model's actual outputs can be inspected beside their sources.

| Dataset | Source page | Captured |
|---|---|---|
| `sft109-ergo` | [Ergo IRC Server](https://ergo.chat/) | 2026-09-14 |
| `sft109-scribblers` | [Scribble.rs](https://scribblers.fly.dev/) | 2026-09-13 |
| `sft109-debops` | [DebOps: Custom services and their default ports](https://docs.debops.org/en/stable-3.3/admin-guide/service-ports.html) | 2026-09-14 |

Each dataset carries three hierarchies:

- **Qwen3.5-9B SFT-109 output**: the adapter's greedy BF16 generation as downloaded from the model repository's `results/qualitative/` files, with each `n…` alias resolved to a captured element through the recorded alias packet and compact source map. Labels and grouping are unchanged.
- **Silver reference (Gemini teacher)**: the automated teacher outline the adapter was trained to imitate. Human review is pending; it is not gold.
- **Gold standard (authored, review pending)**: a candidate authored on 2026-09-14 from the full captured DOM following the labeler rubric. It is AI-authored and awaits human review; the inspector hides it until the Gold standard setting is switched on.

The captures were media-suppressed, so no pixel screenshot exists. The screenshot pane shows a wireframe drawn from captured element geometry and saved DOM text; highlight boxes use the captured geometry.

The JSON files are sanitized views produced by `python3 scripts/build_pages_demo.py --prepare sft109-ergo sft109-scribblers sft109-debops` from the local inspector export. Only display text, geometry, explicit accessibility attributes and public links to each page's own reviewed hosts survive; form values, script and embedded content, styles, tracking attributes, local paths, email addresses, credential-shaped text and URL queries are omitted. Page text remains attributable to the source sites and their authors. The local build inputs (`runs/sft-109-qualitative/`) and the model repository files are not published here.
