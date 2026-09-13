# Semantic Reader Model — working vocabulary

Proposed language for discussing captured interfaces and simplified navigation views for people using assistive technology. The detailed presentation policy remains a design choice.

## Language

**Interface state**:
An interface as experienced at a particular moment, including its current content, open regions, selection, focus, and available interactions.
_Avoid_: Page, when different states of the same page matter.

**Capture**:
Recorded evidence about an interface state from one or more sources, such as its document structure, accessibility tree, or image.
_Avoid_: Ground truth, when the source can be incomplete or incorrect.

**Observed UI graph**:
A common representation of the elements and relationships reported by capture sources, including what is known, missing, or conflicting.
_Avoid_: Semantic hierarchy, when referring to source observations.

**Semantic group**:
A proposed collection of interface elements that share a user-relevant purpose, such as a search form, message, or product entry.
_Avoid_: Native accessibility role, when the group is inferred rather than reported by a source.

**Semantic projection**:
A navigable organization of an observed interface into semantic groups, with access to the original content and controls.
_Avoid_: Repaired accessibility tree, unless accessibility repair has actually been evaluated.

**Semantic zoom**:
Navigation between levels of meaning in a semantic projection: broad purpose and summaries above, specific regions and information below, ending at original interface elements.
_Avoid_: DOM depth, because semantic levels need not follow implementation nesting.

**Reading unit**:
A piece of information that should be understood together, such as a field and its value, or a headline with its teaser and destination. A reading unit may refer to several original interface elements.
_Avoid_: DOM leaf, when the meaning spans more than one source element.

**Presentation policy**:
The audience, purpose, and navigation rules under which a semantic projection is judged useful.
_Avoid_: Simplification, when the intended benefit and preservation rules are unspecified.

**Silver annotation**:
A candidate semantic projection generated or accepted by automated teachers, judges, and checks.
_Avoid_: Gold label, solely on the basis of agreement between models.

**Gold reference**:
An independently human-adjudicated annotation under a documented presentation policy, which can record several acceptable structures and unresolved ambiguity.
_Avoid_: Unique correct tree, unless the policy and evidence actually determine one.
