# Compact audit: forms, actions, and navigation

Audit date: 2026-09-12. Read-only examination of the saved `compact-10pct` run; no compactor changes or model calls.

## Scope and provenance

Compared original source and `structure`, `excerpt`, and `budget` HTML/source maps for GOV.UK, W3C Survey, and OpenStreetMap. References below are the compactor's snapshot-local base-36 `data-r` references, **not** inspector IDs or original HTML IDs. Original-source mappings were checked using the installed BeautifulSoup/lxml parser: source element count, tag order, and parent preorder all match the saved DOMParser ledger through every cited element. On all three documents, only the final injected `div` has a parser-dependent parent; it is not cited here.

| Capture | Detected controls/links: structure → excerpt → budget | Non-hidden-type input/select/textarea elements: structure → budget |
|---|---:|---:|
| GOV.UK | 107 → 71 → 3 | 4 → 0 |
| W3C Survey | 63 → 63 → 9 | 15 → 0 |
| OpenStreetMap | 91 → 84 → 17 | 25 → 0 |

These are HTML selector counts, not accessibility-tree or visible-control counts. They include controls in hidden regions and, for OpenStreetMap, duplicated layout variants. We should not restore every counted element indiscriminately.

## 1. Budget folding removes ordinary forms and the primary action

The W3C survey keeps form `30`, fieldsets `32`/`3p`/`a0`, and their legends (“Favorite Park,” “Greenest City,” “Free Newsletter (optional)”) but loses **all** form fields, field labels, and the submit control. Examples are radio `37` + label `38` (“None”), select `3t` (“cities of the world”), label `ac` + input `ae` (“eMail Address”), and submit `ak`. Their ledger disposition is `budget-fold`, represented by page container `1f`. All survive `structure` and `excerpt`.

GOV.UK similarly retains heading `6q` (“Apply online”) but removes its actual `role="button"` anchor `6s` (“Start now,” destination `www.passport.service.gov.uk/filter`). This is the page's application entry point. The feedback opener remains, so the surviving action inventory misrepresents the page's purpose.

Cause: the exception selector only protects checked/selected/current/invalid/alert nodes ([compact.js:30](../../experiments/dom-downsampling/compact.js#L30)); budget folding protects headings and those exceptions ([compact.js:215](../../experiments/dom-downsampling/compact.js#L215)). Giving a form a lower fold priority does not protect it from an ancestor being folded ([compact.js:225](../../experiments/dom-downsampling/compact.js#L225)).

Smallest add-back: a form skeleton containing every distinct field's source ref, type, label/legend relation, current state, and submit/cancel actions. Sample large choice collections inside the fields. Preserve primary action references under their nearest section heading. An unselected control is still a meaningful reading unit.

## 2. Text-only previews conceal non-text controls entirely

OpenStreetMap map container `c9` is reduced to a preview beginning `1 km3000 ft© OpenStreetMap contributors…`. It contains no evidence of Zoom In `dc`, Zoom Out `de`, Show My Location `dh`, Layers `dk`, Legend `dn`, Share `dq`, Add a note `dt`, or Query features `dw`. Their labels exist in `aria-label`, not descendant text, and all survive the lighter profiles. Directions form `5c` becomes an empty folded form: source fields `63`/`6a` have placeholders “From”/“To,” and `6b` has title “Reverse Directions,” but none of those descriptions reach the preview.

Cause: previews use `el.textContent` ([compact.js:233](../../experiments/dom-downsampling/compact.js#L233)), while pruning removes the controls carrying ARIA labels, titles, placeholders, and values. Consequently the marker announces omitted elements without identifying what useful choices were omitted.

Smallest add-back: retain a compact control inventory with source refs and names from explicit labels/ARIA/title/placeholder/value evidence. Preserve a short action/field list in a folded region even when its prose preview is empty. Exclude decorative icons and map-tile images. Exact accessible-name resolution would require a separately verified capture pipeline; this audit does not infer it from text alone.

## 3. Headings survive while their distinguishing instructions disappear

GOV.UK retains `6d` “How long it takes” and `6j` “Before you start,” but loses `6g` (urgent-service alternative), `6i` (“Do not book travel until you have a valid passport…”), `6k` (“You’ll need a debit or credit card…”), and informative note `6n`. The single main preview is spent on introductory text. The model can see headings but cannot determine the different prerequisites, alternatives, and cautions beneath them.

W3C loses form-level paragraph `31`, “Fields are required if not otherwise noted,” and questions `34`/`3r`. Keeping the “optional” newsletter legend preserves one exception while dropping the rule that makes the other sections required. There are no HTML `required` attributes to substitute for that text.

Cause: heading-only roots plus the same 140-character prefix preview; `role="note"` and ordinary instructional paragraphs are not protected ([compact.js:30](../../experiments/dom-downsampling/compact.js#L30), [compact.js:216](../../experiments/dom-downsampling/compact.js#L216)).

Smallest add-back: one short source-grounded content span per heading/fieldset, plus explicit form instructions and note/error/help relationships. Associate spans with their heading or field rather than one preview for the entire page. Preserve complete short qualifying sentences rather than relying exclusively on prefixes.

## 4. Local navigation edges are discarded even in structure mode

GOV.UK source `28` is `<a href="#content">Skip to main content</a>` but all profiles emit `data-destination="/"`, even though target `<main id="content" data-r="5w">` survives. W3C `b` similarly changes `href="#page"` to `/`; its content/navigation skip links receive the same destination summary in `structure`.

Cause: destination construction keeps hostname and pathname but drops the fragment ([compact.js:110](../../experiments/dom-downsampling/compact.js#L110)). The fragment's HTML target ID is retained during relation discovery, yet no source-ref edge replaces the dropped href. It is not reported by the IDREF deferred-relation check.

Smallest add-back: store local fragment targets as validated source-reference relationships, with explicit deferred markers if the target is absent. Preserve destination kind (local jump versus external navigation) without restoring tracking queries or long executable URLs.

## 5. Native select-group labels are removed, while their long contents escape sampling

W3C's city selector `3t` contains `optgroup label="A"` (`3v`) through `label="Z"`. Even `structure` removes the native `label` attribute; OpenStreetMap's `optgroup label="Directions services"` (`2k`/`5q`) is treated the same way. Separately, `excerpt` samples direct `option` children of `select` but does not sample `optgroup` children, leaving the long city list almost intact. A later broad budget fold removes the whole survey's details to achieve the target.

Cause: `label` is absent from the attribute allowlist ([compact.js:26](../../experiments/dom-downsampling/compact.js#L26)); list sampling handles `select` but not `optgroup` ([compact.js:188](../../experiments/dom-downsampling/compact.js#L188)).

Smallest add-back: retain native `optgroup`/`option` labels, and sample options *within* their groups while preserving group labels, counts, current selections, and the select's own field identity. This targets the actual volume without sacrificing the surrounding form.

## Recommended first change set

Prioritize field/action skeletons, per-heading context, and control-aware omission summaries. Add native select labels and local target relationships as small attribute/edge corrections. Reevaluate the regional model on those inputs before increasing training volume. These are evidence-loss findings, not a measured claim that any particular change will improve model accuracy or fit the original 10% element target.
