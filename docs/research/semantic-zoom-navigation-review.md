# Semantic zoom as navigation: review of the EWH example

Date: 2026-09-12. Scope: static review of `examples/ewh-dashboard/hierarchy.json`, `hierarchy.md`, `semantic-rationale.md`, and the existing EWH viewer's JavaScript. This is a design assessment, not a usability result. No blind participants or screen reader/browser combinations were tested in this review.

## Assessment

The hierarchy is a promising orientation aid. It names meaningful regions, combines cards across layout columns, preserves the Cloud Shell failure, and provides source-grounded summaries. Those properties can help someone form an overview without traversing layout wrappers.

Its usefulness for completing tasks is still unproven. The current viewer is an evidence inspector: activating every terminal item opens captured DOM text, attributes, and a locator. A source link, button, chart, and text value all become an “Inspect DOM element” button in the viewer. There is no implemented handoff to the live original control. Valid source references establish traceability; they do not establish usable action navigation.

The correct baseline is the original page with a screen reader's existing heading, landmark, link, and form-control navigation. The dashboard already has named card headings. W3C describes headings and regions as mechanisms for understanding structure and navigating within a page. The proposed hierarchy must improve a task relative to those mechanisms, not merely relative to a raw DOM dump. [W3C headings](https://www.w3.org/WAI/tutorials/page-structure/headings/), [W3C page regions](https://www.w3.org/WAI/tutorials/page-structure/regions/).

## Four concrete task walkthroughs

The counts below are child activations from the viewer root to its source inspector, calculated from the JSON. They exclude sibling traversal, listening time, and returning upward. They are not measured task times. Summaries can answer questions earlier than terminal source inspection.

| Task | Current behavior | Proposed change |
|---|---|---|
| Find the billing estimate and period; open detailed charges | The dashboard preview already says USD $0.00 at the root. Entering Costs exposes the Billing preview with the period. The amount's source inspector requires five activations: Dashboard → Costs → Billing → Estimated charges → USD $0.00. Detailed charges requires four. | Make “Billing — estimated USD $0.00, Sep 1–12, 2026” a directly discoverable card. Read the estimate and period together; present its original detailed-charges link alongside them. Costs is currently a redundant single-child wrapper. |
| Find the project ID | After three activations, Project info shows a Project ID row and its value summary. Inspecting the value's source requires five: Dashboard → Project and resources → Project info → Project ID → value. | Present “Project ID: example-project” as a single readable fact inside Project info. Keep both source references behind optional evidence inspection. Do not force a separate label node, value node, and evidence step. |
| Understand and close the Cloud Shell failure | The root already exposes “Cloud Shell — unavailable” and the captured failure summary. Inspecting Close requires three activations through two nearly synonymous groups. No close action is executed by the viewer. | Put the failure message, documentation link, and original Close button immediately inside Cloud Shell. Preserve panel resize and activation controls as secondary controls. In a live version, announce a newly occurring failure without forcing the user to leave their current reading position. |
| Read dashboard news | Headlines appear after Dashboard → Learning and updates → News; an article's source inspector requires a fourth activation. “Learning and updates” is a plausible but invented category. | Keep News directly findable by its source heading or an all-links index. Show each headline, relative publication age, and actual link together. The saved dashboard contains links and previews, not the article bodies. |

The root billing preview drops the period even though a lower summary preserves it. This is a small example of a larger issue: compression can preserve the number while losing the qualification that makes it meaningful. At every level that states the estimate, retain enough context to distinguish an estimated period-specific charge from a final bill or balance.

## A shallower alternative to test

Use familiar card names as the default destination list. Give each card a compact preview before expansion. A stable page overview can still collect those cards into broad regions, but it should not require users to traverse every region to reach a known card.

```text
Google Cloud — East West 72h Hack-508
  Cloud Shell — could not be loaded
    Failure message; Documentation [link]; Close [original button]

  Dashboard cards [direct heading/card index]
    Project info
      Project name: East West 72h Hack-508
      Project number: 440367173014
      Project ID: example-project
      Add people [button, disabled]; Project settings [link]; More options [button]
    Billing — estimated USD $0.00, Sep 1–12, 2026
      Estimated charges [original linked panel]
      View detailed charges [link]; Billing tour [link]; More options [button]
    Resources — six product shortcuts
      Existing product links and descriptions
    APIs — no data for the selected time frame
      Chart description; APIs overview [link]; More options [button]
    Google Cloud Platform status — all services normal
      Status dashboard [link]; More options [button]
    Monitoring
      Existing dashboard, alerting, and uptime-check actions
    Error Reporting — no sign of errors; setup status not established
      Captured message; Setup help [link]; More options [button]
    Getting Started
      Existing task/tutorial links
    News — three headlines
      Headline + relative age [link], repeated for each story
      All news [link]; Release notes [link]
    Documentation
      Existing product documentation links

  Console tools and products
    Project selection; Search; Product navigation; Account and assistance
  Dashboard views and customization
    Dashboard [selected tab]; Activity; Recommendations; Customize
  Dashboard retirement notice
    Captured notice; Cloud Hub [link]; Learn more [link]; Dismiss [button]
```

This outline proposes information order, not validated action behavior. Its links/buttons refer to captured original controls; a live adapter would perform the handoff. Any altered accessible name should remain visibly identified as generated in evidence, and preserve the original name in the IR.

Keep “Health and usage” and “Learning and updates” available as an optional overview, or as an alternative lens over the same card IDs. A person seeking a named destination should also have an all-cards/all-actions index and search. Those routes must retain context for duplicate destinations: “Billing: view detailed charges” and “Product navigation: Billing” are different entries.

In the normal reading view, each meaningful fact or original control is the bottom level. Source markup, separate text-bearing elements, and locators remain available as a further inspection mode. This satisfies source reachability without making implementation detail a required navigation stop.

## Interaction changes matter as much as grouping

The present viewer does explicitly restore focus to the previously opened child on return. On descent, however, it focuses Back. That provides a stable escape route but makes the destination secondary. Its live status announces the destination label, depth, and number of parts; child summaries are plain adjacent paragraphs rather than programmatically associated button descriptions. Whether those previews are encountered depends on navigation mode.

A candidate improvement is to focus the new region heading when the user chooses to enter it, then restore the invoking item on return. Another is an inline disclosure that retains focus on its trigger while showing children. W3C describes both focus-at-destination and focus-in-navigation approaches; choosing one depends on whether users intend to enter a destination or compare several destinations. This should be tested, not decided by visual appearance. [W3C navigation example](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/examples/treeview-navigation/).

A hierarchy in the data model does not require an ARIA `tree` widget. For an ordinary page with expandable groups, disclosure buttons and native headings/lists are a simpler candidate; tree widgets introduce additional keyboard, focus, and position semantics. If a tree widget is chosen, implement the complete pattern and test actual assistive technology support. [W3C disclosure pattern](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/), [W3C tree pattern](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/).

For a live system, retain reading position, expansion state, and source identity across regrouping. A delayed model result should not silently replace the branch currently being read. Source status/error events need an independent announcement path; waiting for semantic regrouping would couple time-sensitive information to inference latency. W3C calls for relevant status messages to be available without taking focus, and stresses predictable, persistent keyboard focus. [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html), [W3C keyboard interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/).

## What this changes about the research problem

1. **Optimize useful stops, not minimum node count.** A branch is useful if it offers a choice, an informative preview, or a meaningful scope boundary. One-child wrappers and repeated “Card heading and options” groups add navigation without adding much meaning. The source heading can name the card; overflow controls can stay in context.
2. **Semantic depth is variable.** Project identity is a fact; a news collection contains stories; a chart may require several explanatory levels. Equal path depth across branches is not a goal.
3. **A summary is a learned decision too.** Evaluate preservation of units, time periods, negation, uncertainty, and action availability. “No data” must not become “zero requests.” “All services normal” is a platform message, not proof that this project is healthy.
4. **Relationships matter below the group level.** Label/value, headline/date/link, and error/help/action bundles should be readable as units while preserving individual source identities. This is a more concrete labeling target than arbitrary prose generation.
5. **Multiple useful projections can share one observation graph.** Source/card order, broad orientation groups, and a direct destination index need not be competing gold trees. Annotate card identity and relationships once; make navigation policy a separately evaluated layer.
6. **Task quality needs human evidence.** Compare original screen reader navigation, the first hierarchy, and the shallow alternative with blind participants using their familiar tools. Measure task success, incorrect activation, time, backtracking, information missed, orientation after return, and preferences. Include both an unfamiliar-page browse and a repeated known-destination task. Test across changing interface states as well as static captures.

The strongest lesson is that grouping and interaction should be evaluated together. A tidy hierarchy can improve orientation while increasing the work of reaching an already-known destination. The next useful result would be evidence about which users and tasks benefit from each projection, rather than a declaration that one authored tree is the gold standard.
