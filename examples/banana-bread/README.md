# Banana bread demo

This is the reviewed public dataset that the GitHub Pages inspector opens by default; the [SFT-109 test cases](../sft109-cases/README.md) were added on 2026-09-14. Source: [Allrecipes, Banana Banana Bread](https://www.allrecipes.com/recipe/20144/banana-banana-bread/), captured September 12, 2026. The saved screenshot shows the public recipe and its generic recipe-promotion overlay; no entered form values or signed-in account details are visible. Image metadata checks found no EXIF or XMP metadata.

`allrecipes.json` contains a sanitized published view of 5,145 source nodes, with their original graph IDs and source references intact. The two hierarchy variants are the existing authored original and authored revised trees. They are not outputs of the comparison model run or an evaluation result.

Only display text, geometry, explicit accessibility attributes, and public Allrecipes links survive export. Input values, script and embedded content, event handlers, styles, tracking attributes, local paths, email addresses, credential-shaped text, URL queries, and private or unrelated URLs are omitted. The graph retains blank inert nodes so existing hierarchy references remain valid. This means the published view is not equivalent to the raw capture or suitable for reproducing evaluation measurements.

The viewport image and DOM were captured sequentially, so dynamic content and element geometry can differ. The screenshot shows only the first viewport. Source page text and image remain attributable to Allrecipes and their respective authors.

Build the artifact with `python3 scripts/build_pages_demo.py --destination /tmp/semantic-pages`. The destination must be empty. This copies only the six static inspector assets and the reviewed datasets listed in `scripts/build_pages_demo.py`, and generates their catalog; it does not publish other captures, logs, configuration, or model endpoints.
