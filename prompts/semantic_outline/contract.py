"""Strict, document-local validation for the rubric-v0 labeling contract."""

from .outline_tool import validate


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "page": {"type": "STRING"},
        "scope": {"type": "STRING"},
        "outline": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "depth": {"type": "INTEGER"},
                    "label": {"type": "STRING"},
                    "refs": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["depth", "label", "refs"],
            },
        },
        "needs_expansion": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"ref": {"type": "STRING"}, "reason": {"type": "STRING"}},
                "required": ["ref", "reason"],
            },
        },
    },
    "required": ["page", "scope", "outline", "needs_expansion"],
}


def validate_output(data, valid_refs):
    """Return (errors, warnings); valid_refs must come from this document only.

    The compact response schema intentionally contains no source-ID enumeration.
    This local check enforces references after generation instead.
    """
    errors = []
    if not isinstance(data, dict):
        return ["output must be an object"], []
    if set(data) != {"page", "scope", "outline", "needs_expansion"}:
        errors.append("output must contain exactly page, scope, outline, needs_expansion")
    for key in ("page", "scope"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key} must be a nonempty string")
    valid_refs = set(valid_refs)
    lines = data.get("outline")
    structure_ok = isinstance(lines, list) and bool(lines)
    if not structure_ok:
        errors.append("outline must be a nonempty array")
    else:
        for i, line in enumerate(lines):
            if not isinstance(line, dict):
                errors.append(f"line {i}: must be an object")
                structure_ok = False
                continue
            if set(line) != {"depth", "label", "refs"}:
                errors.append(f"line {i}: must contain exactly depth, label, refs")
            if type(line.get("depth")) is not int or line["depth"] < 0:
                errors.append(f"line {i}: depth must be a nonnegative integer")
                structure_ok = False
            if not isinstance(line.get("label"), str) or not line["label"].strip():
                errors.append(f"line {i}: label must be a nonempty string")
                structure_ok = False
            refs = line.get("refs")
            if not isinstance(refs, list) or any(not isinstance(r, str) or not r for r in refs):
                errors.append(f"line {i}: refs must be an array of nonempty strings")
                structure_ok = False
            elif len(refs) != len(set(refs)):
                errors.append(f"line {i}: duplicate refs within unit")
    warnings = []
    if structure_ok:
        outline_errors, warnings = validate(lines, valid_refs)
        errors.extend(outline_errors)
        if lines[0]["refs"]:
            errors.append("root must be a group with empty refs")
        for i, line in enumerate(lines[:-1]):
            if line["refs"] and lines[i + 1]["depth"] > line["depth"]:
                errors.append(f"line {i}: reading unit must be a leaf")
    expansions = data.get("needs_expansion")
    if not isinstance(expansions, list):
        errors.append("needs_expansion must be an array")
    else:
        for i, item in enumerate(expansions):
            if not isinstance(item, dict) or set(item) != {"ref", "reason"}:
                errors.append(f"needs_expansion {i}: must contain exactly ref, reason")
                continue
            ref = item["ref"]
            if not isinstance(ref, str) or ref not in valid_refs:
                errors.append(f"needs_expansion {i}: unknown ref {ref!r}")
            if not isinstance(item["reason"], str) or not item["reason"].strip():
                errors.append(f"needs_expansion {i}: reason must be a nonempty string")
    return errors, warnings
