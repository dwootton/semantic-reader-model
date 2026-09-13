# Compaction audit: reading units and content relationships

Audit date: 2026-09-12. Scope: IKEA, NYT homepage, Allrecipes, and MDN saved artifacts in `runs/compression/compact-10pct/`. This is an audit of existing evidence, with no model calls or compactor changes.

References such as `up` are the artifact's `data-r` values, checked in its HTML and source-map ledger. They are **not** existing inspector/capture IDs. Raw HTML and Beautiful Soup inspection were used to find source text and containers; visibility or source-ID-to-capture-ID equivalence was not inferred. NYT's source has `sourceRoundTripStable: false`; its structure/excerpt artifacts fail encoding checks and are diagnostic evidence, not deployable baselines. Budget passes the emitted encoding checks, which do not establish semantic completeness.

## Overall finding

The 10% budget representation often preserves a table of contents while deleting the evidence needed to build the reading units under it. However, the earlier structure pass also removes useful card boundaries before any text is shortened. Restore boundaries and compact complete content records before increasing arbitrary text limits. Keeping all source HTML or CSS is unnecessary.

| Saved page | Structure: exposed text / source | Budget: exposed text / source | Controls/links: structure → budget |
|---|---:|---:|---:|
| IKEA | 12,082 / 12,082 | 3,120 / 12,082 | 434 → 73 |
| NYT | 28,368 / 28,586 | 3,538 / 28,586 | 1,154 → 173 |
| Allrecipes | 26,741 / 26,742 | 1,618 / 26,742 | 622 → 113 |
| MDN | 10,698 / 10,711 | 1,188 / 10,711 | 332 → 26 |

These report counts include content in saved DOM without computed visibility classification. They measure exposed evidence, not useful-group accuracy. NYT's structure count is additionally subject to the parse-stability failure above.

## 1. Generic-wrapper deletion erases useful product and story boundaries

**Responsible code:** `experiments/dom-downsampling/compact.js:92` removes class/style/data attributes; `:134` then collapses every div/span/font/center with neither surviving attributes nor direct text, irrespective of whether it groups several meaningful children.

IKEA raw source contains a `div.plp-price-module` whose contents are the CENTERHALV name, description, price, and three offer qualifiers. The compact structure puts the following directly under the product-list section `tw`, followed by the next product's controls and heading:

```html
<h3 data-r="up">…CENTERHALV… Office chair, black</h3>
<span data-r="v4">Price $ 199.99</span>
<div data-r="vc">In-store only price $149.99</div>
<div data-r="vd">Offer valid from Sep 8, 2026 until Dec 24, 2026</div>
<div data-r="ve">Exclusive IKEA family offer</div>
<button data-r="vg" aria-label='Add "CENTERHALV Office chair" to cart'>…</button>
…
<span data-r="vw">Available for delivery</span>
<span data-r="vz">In stock in Stoughton, MA</span>
<!-- Next product starts with its compare, image and save controls before its heading. -->
```

Raw NYT source likewise has a `div[data-tpl="slic"]` enclosing “Analysis”, the lead headline, teaser, and comments. The structure output makes those elements siblings under main `2p6`. This is an association loss even when every text character survives; a “take until next heading” heuristic would misassign controls appearing before the next product title, and NYT story titles are paragraphs rather than headings.

**Minimal add-back:** retain one existing parent boundary for a repeated record / multi-child reading unit. Collapse single-child layout chains readily; be conservative about multi-child containers containing a title-like link plus adjacent description, values, media or actions. Emit the boundary's source reference without shipping its full classes/styles. Where visual grouping is needed, compact measured group/row/column cues would be more useful than raw CSS; saved HTML alone does not establish those cues.

Evidence: `ikea--page.source.html`, `ikea--page--structure.html`, `nyt-homepage--nyt.source.html`, `nyt-homepage--nyt--structure.html`, and the corresponding structure source maps.

## 2. Heading-only protection is biased against the actual article titles

**Responsible code:** `compact.js:22` defines a native heading selector; `:211`–`:247` ranks regions by element savings and prunes everything except native headings, explicit state exceptions, and their ancestor paths.

NYT's real lead story is emitted by the structure/excerpt artifacts as:

```html
<p data-r="2py"><span data-r="2pz">Analysis</span></p>
<a data-r="2q1" data-destination="www.nytimes.com/2026/09/12/us/politics/trump-free-speech.html">
  <p data-r="2q3">How Trump Is Wielding Power to Stifle Speech</p>
</a>
<p data-r="2q5">President Trump has harnessed agencies across the government to curtail press freedoms, a sweeping campaign that free speech advocates say will have lasting effects.</p>
```

Budget folds `main[2p6]` in one operation, marked `data-deferred="950"`. All four refs become deferred to `2p6`. The output retains “New York Times - Top Stories” and headings such as “Opinion”, “Well”, and “Cooking”, plus a single 130-character main preview. It does not preserve a list of actual story titles or story boundaries. Meanwhile substantial repeated navigation text remains elsewhere in the saved DOM; this audit does not assert which navigation copies were visually open.

**Minimal add-back:** protect compact reading-unit records, including linked title paragraphs, ARIA heading roles, and explicit collection members. Require a minimum evidence floor per primary section. Prefer folding an individual record's body to folding an entire main/article container. Allocate by downstream semantic task and wire/token cost, rather than element savings alone.

## 3. Budget drops product and article evidence needed to label a group correctly

The IKEA budget retains title `up` and its product link `ur`, but defers the CENTERHALV price `v4`, local offer `vc`, dates `vd`, eligibility `ve`, cart `vg`, and stock/delivery `vw`/`vz` to `9s`. It leaves “More options” legends on other products while dropping their choices. Retaining a bare price alone would also be insufficient: `$149.99` is an in-store, time-bounded IKEA Family offer, not an unconditional second product price.

Allrecipes budget folds the entire main `zw` (`data-deferred="1585"`). It removes author `11a` (“Shelley Albeluhn”), updated date `11b`, ingredient list `1n9`, and ordered directions `1oc`; the six procedural steps survive the excerpt pass but disappear in budget. Article `zy` becomes a heading outline with protected selected video-setting controls and alerts. This proves evidence loss, not whether those saved controls were visible in the live page.

MDN's `section[bf]` keeps “Beginner's tutorials” but deletes all seven `dt`/`dd` title-description pairs in `dl[bk]`, including `bm` (“What is accessibility?”) and its description `bo`. Its 140-character prefix repeats the broad heading and module introduction, giving no inventory of those seven units.

**Minimal add-back:** preserve title + compact descriptor + important values/qualifiers + primary action references as a source-grounded record. For an article, retain author/date and a child-section/step inventory. For a resource collection, retain each `dt` title and destination plus a short associated `dd` descriptor, even if full descriptions are deferred. The model can organize these records without receiving every prose paragraph.

**Responsible code:** budget protection/pruning at `compact.js:216`–`:247`; one shared prefix generated at `:233`.

## 4. First/second/last sampling hides distinct categories and recipe members

**Responsible code:** `compact.js:188`–`:200` samples every qualifying ul/ol/tbody/select/datalist of seven or more children identically.

Allrecipes ingredient `ul[1n9]` contains seven short source items:

1. `1na`: 2 cups all-purpose flour
2. `1nf`: 1 teaspoon baking soda
3. `1nk`: ¼ teaspoon salt
4. `1np`: ¾ cup brown sugar
5. `1nu`: ½ cup butter
6. `1nz`: 2 large eggs, beaten
7. `1o4`: 2 ⅓ cups mashed overripe bananas

The excerpt emits only flour, baking soda, and bananas, with `data-omitted-items="4"`. The parallel explanatory ingredients list `1jx` is sampled the same way. The marker is honest, but the remaining items are not a representative semantic inventory of the recipe.

IKEA's filter-list `ad` is reduced from fourteen distinct filter categories to Sort, Price, Series (`data-omitted-items="11"`). MDN's sidebar `ol[fb]` becomes Accessibility, Guides, and Roles, dropping fourteen top-level entries; the nested roles list `ln` becomes alert, alertdialog, window, omitting 84 entries. This is enough to guess a collection's general type, but not organize or expose its actual contents.

**Minimal add-back:** preserve all short inventory titles and bounded labels for distinct categories, ingredients, options and ordered steps. Sample long repeated bodies only after retaining identity/count/order information for all members. For large collections expose a compact per-item title/ref manifest, with selected full examples for body shape. Seven is too small a universal threshold for content deletion.

## 5. Destination shortening deletes valuable in-page relationships

**Responsible code:** `compact.js:104`–`:116` builds a destination from hostname + pathname and removes fragments and every query parameter.

MDN's source TOC has `href="#beginners_tutorials"`, `#accessibility_guides`, `#references`, and `#see_also`. All become `data-destination="/"` (`b6`, `b8`, `ba`, `bc`). The headings' HTML IDs survive, but no explicit TOC-target edges survive. IKEA's “Skip to results” (`ab`) likewise becomes `/`. This occurs even in the structure profile.

**Minimal add-back:** emit a short target-source-reference for same-document fragment links before stripping URLs. Keep a small normalized destination identity/hash distinct from its human-readable description; preserve allowlisted semantic query keys only when they define meaningful destinations. Continue removing tracking and embedded payloads. This would also let the organizer pair a story's image and text links without relying on long URL strings.

## 6. Keep useful image text with its record; geometry can mostly stay out

`compact.js:26` correctly preserves image alt attributes in structure. For example IKEA image `ud` supplies “CENTERHALV black mesh office chair. Ergonomic with adjustable height, padded armrests, and caster brakes.” The product title alone contains much less evidence. Budget removes that image and almost all product images: IKEA falls from 110 image elements / 102 nonempty alts in structure to 3 / 1 in budget. Allrecipes falls from 49 / 32 to 1 / 0. These are HTML counts, not visible-image counts.

The SVG pass at `compact.js:124`–`:132` appropriately removes bulky icon geometry and preserves an `aria-label` or the first title/desc; the MDN logo remains labeled MDN. No meaningful chart SVG text was found among the four audited pages, so this audit does **not** claim an observed chart-data loss. The implementation would nevertheless delete SVG `text` and all but the first title/desc; that is a testable gap for future charts/diagrams.

**Minimal add-back:** carry one nonredundant descriptive alt/caption in a compact record alongside its title, with its source ref. Avoid duplicating title-equivalent alt text. Preserve SVG text/desc as bounded semantic text when present; continue excluding geometry and embedded assets. Do not restore image URLs to get semantic descriptions.

## 7. Prefix excerpts can cut the very qualification that differentiates an item

**Responsible code:** `compact.js:32` and `:167`–`:184` truncate each text node at a word boundary, independently of semantic clauses.

Allrecipes review `2r5` begins with ingredient tweaks, but later explains that the bread was still not cooked after 1h20m and recommends more flour or smaller pans. Excerpt stops during “This spice mix is subtle amount for a large loaf…”, before those outcome qualifications. Review `25l` loses the later mixer/wooden-spoon and oven-rack advice. The `data-excerpt` markers are useful and must stay; a generated label such as “successful flavor variation” would require more evidence than that prefix gives.

This is a smaller initial priority than region deletion: IKEA excerpt shortens only one text node by 18 characters, and NYT excerpt shortens zero text nodes, while losing much more text through list sampling. For ordinary section labeling a short intro may be adequate; for review, warning, eligibility or procedural decisions, it may not be.

**Minimal add-back:** retain compact units and their relationships first, then use sentence-bounded excerpts and preserve explicit nearby warnings/qualifiers. If only a prefix is exposed, scope the output to observed evidence or request expansion before labeling the whole review/passage. Do not blindly increase every prose limit.

## Suggested semantic preservation floor

Before training on budget outputs, require every intended regional example to expose (a) source-grounded unit boundaries, (b) all child-unit titles/refs, (c) nearby descriptive/value/action relationships needed for grouping, and (d) explicit evidence completeness. Preserve short unique inventory members; defer longer bodies. A hierarchy request over a whole folded main element should be an outline/expansion task until those regional floors are met.

The structure pass is a useful savings foundation, after boundary and fragment-edge corrections. The current budget output is a retrieval outline rather than sufficient evidence for complete reading hierarchies on these examples. All omitted source remains locally resolvable, but it is not model-visible until a sanitized, bounded expansion path actually delivers it.
