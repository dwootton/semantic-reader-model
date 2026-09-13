# Lessons from two semantic zoom examples

These are findings from authoring and statically checking saved HTML, not empirical evidence of navigation benefit. The source examples are the EWH Google Cloud dashboard and the supplied New York Times homepage. Their underlying news and account statements were not independently verified.

## What the first example established

The dashboard projection preserves exact source identities and useful broad groupings, including groupings that cross layout columns. Its first viewer also exposes the main limitation of this approach: hierarchy quality and reader interaction quality are separate. Reading an amount from a summary is different from reaching its source element, and reaching that element is different from activating a working original control.

The first hierarchy requires five child edges to the original amount or project-ID element. The shallow alternative reduces those source-reference paths to three, and detailed charges from four to two. Those are structural counts, not evidence of less listening time or faster tasks; the first overview already includes some answers. The alternative keeps all 162 original source leaves.

## Changes suggested by the NYT capture

- **Recognize reading units.** A headline, teaser, author, reading duration, comments, and photo can share a story wrapper while having different roles. A photo credit is not an author. A reading duration is not a publication time. The proposed learner needs relationship labels as well as region types.
- **Preserve genre and scope.** Flattening into a headline index should retain Opinion, Analysis, section membership, and source qualifications. Semantic compression must not erase how to interpret the content.
- **Separate content identity from its occurrences.** Responsive menus repeat links; a story may also be intentionally repeated in Most Shared and another editorial section. Deduplicating every repeated destination would lose the latter context. The current projection preserves editorial occurrences and offers their section paths in the headline index.
- **Learn boundaries beyond literal tag names.** Many captured headline texts use paragraph markup. DOM tag classification alone misses their editorial role. Existing card/story structure and text relationships still provide useful candidate boundaries.
- **Treat absent content explicitly.** The Weather region contains a heading but no captured conditions. Five video teasers have no verified native activation target. Neither should produce fabricated weather or playback controls.
- **Retain source evidence beneath the reading view.** A person should be able to read a story or a field without traversing a DOM inspector. Captured image alt text belongs in optional image-description content, and raw identifiers/attributes belong in optional evidence inspection.
- **Observe the real browser before claiming live targeting.** The raw HTML includes duplicate IDs, inert/template content, modern picture markup, and parser-sensitive structure. Validating XPath and CSS against static parsers is useful evidence, but it cannot replace browser-issued node identities and computed accessibility data.

## What to train

The narrower target is still promising: recognize source-backed regions and reading units, attach their title/description/value/genre/action relationships, and propose short labels where source text is insufficient. Retain the source graph and let the reader offer more than one navigation view.

Candidate annotation fields include unit type, title source, descriptive text sources, primary destination, qualifiers, region membership, and whether grouping adds a useful decision. Exact output boundaries and the renderer's use of them remain experiment variables. A single ideal tree is not the only possible gold reference.

The labels needed for source roles and factual relationships are different from subjective decisions about which groups to show first. Evaluate these separately before scaling synthetic annotations. Do not use model agreement alone to settle the latter.

## What to test with blind readers

Compare native screen-reader heading/landmark/link navigation, the first semantic hierarchy, the shallow alternative, and a direct headline/destination index. Use familiar assistive technology and include both exploration and known-target tasks. Measure correct completion, time, listening/backtracking burden, information missed, incorrect activation, and recovery of reading position. Ask whether summaries preserve the qualifications readers actually need.

Test original control handoff, focus and reading-cursor continuity, and updates separately from static grouping. A model-produced reorganization should not interrupt a region being read. A more navigable tree cannot compensate for an unreliable action target.

The second viewer is an authored comparison with native disclosures and links to supplied destinations. It does not implement live original-button control or claim tested assistive-technology support. Source integrity, coverage, and script syntax have been checked; rendered behavior and user utility remain untested.

Related artifacts: [navigation review](semantic-zoom-navigation-review.md), [dashboard alternative](../../examples/ewh-dashboard/reader-alternative.md), [NYT hierarchy](../../examples/nyt-homepage/hierarchy.md).
