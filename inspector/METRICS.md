# Structural reduction and modeled navigation

These are calculations over saved DOM and authored hierarchy data. They are not measured screen-reader keystrokes, reading-buffer sizes, task times, or blind-user results. A high structural reduction can reflect omitted/undetailed content as well as removal of implementation wrappers.

## Revised hierarchy by capture

All navigation columns within each row use exactly the same directly mapped source targets. The coverage column counts all eligible inferred headings, links, buttons, and form controls; an ancestor reference does not count as direct coverage.

| Capture | DOM → hierarchy nodes | Reduction | Direct target coverage | Hierarchy median steps | Quick-nav median keys | Target-scan median stops |
|---|---:|---:|---:|---:|---:|---:|
| allrecipes | 5,145 → 244 | 95.3% | 88/218 (40.4%) | 11.5 | 14 | 110.5 |
| apple | 3,109 → 246 | 92.1% | 118/283 (41.7%) | 14.5 | 12 | 90.5 |
| github | 1,617 → 244 | 84.9% | 132/241 (54.8%) | 12 | 17 | 149.5 |
| gov-uk | 382 → 113 | 70.4% | 75/77 (97.4%) | 14 | 13 | 40 |
| hacker-news | 806 → 323 | 59.9% | 228/229 (99.6%) | 23 | 114.5 | 115.5 |
| ikea | 3,086 → 130 | 95.8% | 67/372 (18%) | 11 | 11 | 48 |
| mdn | 1,076 → 126 | 88.3% | 63/342 (18.4%) | 12 | 10 | 127 |
| nasa | 2,459 → 136 | 94.5% | 94/109 (86.2%) | 12.5 | 19 | 54.5 |
| openstreetmap | 469 → 53 | 88.7% | 38/39 (97.4%) | 8 | 7 | 20.5 |
| smithsonian | 856 → 152 | 82.2% | 69/88 (78.4%) | 13 | 11 | 43 |
| w3c-survey | 458 → 108 | 76.4% | 31/66 (47%) | 9 | 6 | 23 |
| wikipedia | 3,633 → 302 | 91.7% | 404/716 (56.4%) | 16.5 | 24 | 252.5 |
| ewh-dashboard | 2,332 → 220 | 90.6% | 139/143 (97.2%) | 14 | 12 | 72 |
| nyt-homepage | 6,609 → 468 | 92.9% | 200/278 (71.9%) | 15 | 14 | 166.5 |

## Pooled revised results

32,037 DOM elements → 2,865 semantic nodes (91.1% reduction). 1,746 of 3,201 eligible source targets are directly mapped (54.5%).

For the same pooled mapped targets: median hierarchical traversal = 14 modeled steps; median optimistic quick navigation = 17 modeled keys; median linear target scan = 108 stops.

Revised variants only: each of the 14 captures counted once. Navigation pools the same directly mapped targets, equally weighted; not task-frequency weighted.

## Definitions and limits

- Structural reduction compares all captured DOM elements with all semantic nodes, including source leaves. It is not an accessibility-tree or screen-reader-buffer reduction.
- Targets are inferred native/ARIA headings, links, buttons, and fields. Known hidden, inert, aria-hidden ancestors, hidden inputs, and script/style/noscript/template subtrees are excluded; disabled, off-screen, and zero-sized elements remain. Capture visibility and role inference are incomplete, not a browser accessibility computation.
- Coverage requires a direct source reference from a semantic DOM leaf. Referencing an ancestor or group does not count. All navigation summaries use the same unique covered targets; uncovered targets remain in the coverage denominator.
- Semantic cost models an ideal hierarchical picker from its focused collapsed root: enter each branch costs one and skip each preceding sibling costs one (sum of sibling index plus one). Cheapest directly mapped leaf wins. This is not the inspector keyboard implementation or a guaranteed human route.
- Linear scan is the target ordinal in captured DOM preorder, starting before the first target. It counts selectable target stops, not screen-reader reading units or Tab order.
- Quick navigation optimistically selects the cheapest same-kind scan from document start or heading scan followed by same-kind commands strictly after that heading. It assumes the relevant screen reader/mode supports those commands; field routes scan the union of fields and buttons, while button routes use next-button. This remains an approximation of each screen reader’s control taxonomy. Oracle route selection excludes heading recognition/search cost, landmarks, rotors, text search, and remembered locations.
- Depth starts at zero. Median uses the middle value or pair; p90 is nearest rank. Empty statistics are null. Every matched target has equal weight; distributions are not a task-frequency model.
- All estimates exclude final activation, listening time, cognition, discovery, and errors. Multiple captured roots are concatenated in stored root order; this does not establish actual cross-frame navigation behavior. Real assistive-technology/user testing is required.

NVDA documents heading/link/button/form-field commands, an element-list filter, and text search. This model only approximates selected heading/type routes. It does not predict a reader’s choice, recognition cost, browser virtual-buffer order, active modal scope, tab order, or VoiceOver rotor use. [Official NVDA guide](https://download.nvaccess.org/releases/stable/documentation/en/userGuide.html#SingleLetterNavigation).

Every target-level estimate and all original/revised variants are in [metrics-report.json](qa/metrics-report.json). Use the inspector’s Statistics panel for the selected capture/variant; Show all targets reveals the complete destination list.

## Reproduce

```sh
node --test inspector/metrics.test.mjs
node inspector/build_metrics_report.mjs
```

A real evaluation still needs shared tasks, initial focus/reading position, a browser and assistive-technology combination, and observed completion time/errors. These figures are useful for prioritizing tests, not for claiming a percentage improvement in accessibility.
