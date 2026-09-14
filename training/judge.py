"""Frozen, source-only rubric teacher; conservative preference/reward exports.

No model calls occur on import. Hosted scoring uses the existing verified lab
client. Offline packets and review calibration make every admission auditable.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

from prompts.semantic_outline.contract import validate_output


VERSION = "semantic-outline-teacher/0.2"
CRITERIA = ("coverage", "grounding", "grouping", "labels")
RUBRIC_PATH = Path(__file__).with_name("judge-rubric.md")
DEFAULT_MODEL = "gemini-3.1-pro-preview"


def strict_json(value):
    if not isinstance(value, str):
        return value

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = item
        return result

    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def read_jsonl(path):
    with Path(path).open() as stream:
        return [strict_json(line) for line in stream if line.strip()]


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def build_packet(row, prediction):
    """Reveal exactly the student input, never its reference completion."""
    _require(_text(row.get("id")) and row["id"] == prediction.get("id"), "ID mismatch")
    _require(_text(prediction.get("candidate_id")), "candidate_id is required")
    _require(row.get("split") in {"train", "dev", "test"}, "Unknown split")
    prompt = row.get("prompt")
    _require(isinstance(prompt, list) and bool(prompt), "Missing student prompt")
    _require(all(isinstance(m, dict) and set(m) == {"role", "content"}
                 and m["role"] in {"system", "user"} and _text(m["content"])
                 for m in prompt), "Prompt must contain only system/user text messages")
    source_input = None
    user_messages = [m for m in prompt if m["role"] == "user"]
    if len(user_messages) == 1:
        try:
            parsed = strict_json(user_messages[0]["content"])
            if isinstance(parsed, dict):
                source_input = parsed
        except (ValueError, RecursionError):
            pass  # Plain-text inputs remain directly citable through prompt.
    refs = row.get("valid_refs")
    _require(isinstance(refs, list) and all(_text(ref) for ref in refs),
             "valid_refs must come from this document's student input")
    try:
        candidate = strict_json(prediction.get("output"))
        errors, warnings = validate_output(candidate, refs)
    except (TypeError, ValueError, RecursionError) as error:
        candidate = prediction.get("output")
        errors, warnings = [f"Invalid candidate JSON: {error}"], []
    return {
        "rubric_version": VERSION, "id": row["id"],
        "candidate_id": prediction["candidate_id"], "domain": row.get("domain"),
        "split": row["split"], "prompt": prompt, "prompt_hash": digest(prompt),
        "source_input": source_input,
        "candidate": candidate, "valid_refs": sorted(set(refs)),
        "preflight": {"errors": errors, "warnings": warnings},
    }


def resolve_evidence(packet, evidence):
    _require(isinstance(evidence, dict)
             and set(evidence) == {"kind", "pointer", "quote"}, "Invalid evidence fields")
    _require(evidence["kind"] in {"source", "prompt", "candidate"}, "Invalid evidence kind")
    pointer = evidence["pointer"]
    _require(isinstance(pointer, str) and pointer.startswith("/"), "Evidence needs a JSON pointer")
    if evidence["kind"] == "prompt":
        parts = pointer.split("/")
        _require(len(parts) == 3 and parts[1].isdigit() and parts[2] == "content"
                 and int(parts[1]) < len(packet["prompt"])
                 and packet["prompt"][int(parts[1])]["role"] == "user",
                 "Source evidence must quote the student's user input, not system instructions")
    value = packet["source_input"] if evidence["kind"] == "source" else packet[evidence["kind"]]
    try:
        for raw in pointer[1:].split("/"):
            _require("~" not in raw.replace("~1", "").replace("~0", ""), "Invalid pointer escape")
            key = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                _require(key.isdigit() and str(int(key)) == key, "Invalid array pointer")
                value = value[int(key)]
            else:
                value = value[key]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Evidence pointer does not resolve") from error
    _require(isinstance(value, str) and _text(evidence["quote"])
             and evidence["quote"] in value, "Evidence quote must occur in the referenced string")
    return value


def _source_and_candidate_evidence(evidence):
    kinds = {e.get("kind") for e in evidence if isinstance(e, dict)}
    return "candidate" in kinds and bool(kinds & {"source", "prompt"})


def validate_judgment(packet, raw):
    result = strict_json(raw)
    fields = {"rubric_version", "id", "candidate_id", "complete_review", "source_sufficient",
              "criteria", "hard_errors"}
    _require(isinstance(result, dict) and set(result) == fields, "Invalid judgment fields")
    for key in ("rubric_version", "id", "candidate_id"):
        _require(result[key] == packet[key], f"Judgment {key} mismatch")
    for key in ("complete_review", "source_sufficient"):
        _require(type(result[key]) is bool, f"{key} must be boolean")
    _require(isinstance(result["criteria"], dict)
             and set(result["criteria"]) == set(CRITERIA), "Invalid criteria")
    for name, criterion in result["criteria"].items():
        _require(isinstance(criterion, dict)
                 and set(criterion) == {"status", "score", "reason", "evidence"}, "Invalid criterion fields")
        status, score = criterion["status"], criterion["score"]
        _require(status in {"assessed", "insufficient_evidence"}, "Invalid criterion status")
        _require((type(score) is int and 0 <= score <= 3) if status == "assessed"
                 else score is None, "Criterion status/score contradiction")
        _require(_text(criterion["reason"]) and isinstance(criterion["evidence"], list),
                 "Criterion requires reason and evidence list")
        if status == "assessed":
            _require(_source_and_candidate_evidence(criterion["evidence"]),
                     f"{name}: both source and candidate evidence required")
        for evidence in criterion["evidence"]:
            resolve_evidence(packet, evidence)
    _require(isinstance(result["hard_errors"], list), "hard_errors must be a list")
    for error in result["hard_errors"]:
        _require(isinstance(error, dict) and set(error) == {"criterion", "reason", "evidence"}
                 and error["criterion"] in {"coverage", "grounding"}
                 and _text(error["reason"]) and isinstance(error["evidence"], list), "Invalid hard error")
        _require(_source_and_candidate_evidence(error["evidence"]),
                 "Hard error requires source and candidate evidence")
        for evidence in error["evidence"]:
            resolve_evidence(packet, evidence)
        criterion = result["criteria"][error["criterion"]]
        _require(criterion["status"] == "assessed" and criterion["score"] == 0,
                 "Hard error contradicts its criterion")
    for name in ("coverage", "grounding"):
        if result["criteria"][name]["score"] == 0:
            _require(any(e["criterion"] == name for e in result["hard_errors"]),
                     f"{name}=0 requires a supported hard error")
    return result


def derive_decision(packet, result):
    if packet["preflight"]["errors"] or result["hard_errors"]:
        return "reject"
    if not result["complete_review"] or not result["source_sufficient"] or any(
            criterion["status"] != "assessed" for criterion in result["criteria"].values()):
        return "insufficient_evidence"
    return "accept" if all(c["score"] >= 2 for c in result["criteria"].values()) else "revise"


def score_packet(packet, raw=None, *, model=DEFAULT_MODEL, error=None):
    score = {"id": packet["id"], "candidate_id": packet["candidate_id"],
             "domain": packet["domain"], "split": packet["split"],
             "prompt_hash": packet["prompt_hash"], "packet_hash": digest(packet),
             "rubric_version": VERSION, "rubric_hash": digest(RUBRIC_PATH.read_text()),
             "model": model, "packet": packet, "result": None,
             "decision": "unjudged", "reward": None, "reward_eligible": False}
    if packet["preflight"]["errors"]:
        score["decision"] = "reject"
    elif error:
        score["error"] = error
    else:
        try:
            result = validate_judgment(packet, raw)
            score.update(result=result, decision=derive_decision(packet, result))
        except (TypeError, ValueError, KeyError, RecursionError) as error:
            score.update(decision="invalid_judgment", error=str(error))
    return score


def _validated_packet(score):
    packet = score["packet"]
    _require(packet["rubric_version"] == VERSION
             and score["rubric_hash"] == digest(RUBRIC_PATH.read_text()), "Stale rubric")
    _require(score["packet_hash"] == digest(packet), "Packet hash mismatch")
    rebuilt = build_packet({"id": packet["id"], "domain": packet["domain"],
                            "split": packet["split"], "prompt": packet["prompt"],
                            "valid_refs": packet["valid_refs"]},
                           {"id": packet["id"], "candidate_id": packet["candidate_id"],
                            "output": packet["candidate"]})
    _require(packet == rebuilt, "Packet preflight or prompt hash was changed")
    for field in ("id", "candidate_id", "domain", "split", "prompt_hash", "rubric_version"):
        _require(score[field] == packet[field], f"Score {field} mismatch")
    return packet


def validated_score(score):
    """Recompute admission; edited decisions cannot bypass deterministic gates."""
    packet = _validated_packet(score)
    _require(not packet["preflight"]["errors"], "Candidate fails structural guards")
    result = validate_judgment(packet, score["result"])
    _require(derive_decision(packet, result) == score["decision"], "Decision mismatch")
    _require(score["decision"] in {"accept", "revise"} and not result["hard_errors"],
             "Unknown or rejected candidate cannot supply a training preference")
    return result


def export_preferences(scores):
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for score in scores:
        try:
            validated_score(score)
        except (ValueError, TypeError, KeyError):
            continue
        if score["split"] == "train":
            groups.setdefault((score["id"], score["prompt_hash"], score["model"],
                               score["rubric_hash"]), []).append(score)
    for group in groups.values():
        for a, b in itertools.combinations(group, 2):
            if a["candidate_id"] == b["candidate_id"] or a["packet"]["candidate"] == b["packet"]["candidate"]:
                continue
            av = [a["result"]["criteria"][c]["score"] for c in CRITERIA]
            bv = [b["result"]["criteria"][c]["score"] for c in CRITERIA]
            if all(x <= y for x, y in zip(av, bv)):
                a, b, av, bv = b, a, bv, av
            if not all(x >= y for x, y in zip(av, bv)) or sum(av) - sum(bv) < 2:
                continue  # Ties, tradeoffs and weak margins abstain.
            yield {"id": a["id"], "domain": a["domain"], "split": "train",
                   "prompt": a["packet"]["prompt"], "prompt_hash": a["prompt_hash"],
                   "chosen": [{"role": "assistant", "content": json.dumps(a["packet"]["candidate"], ensure_ascii=False)}],
                   "rejected": [{"role": "assistant", "content": json.dumps(b["packet"]["candidate"], ensure_ascii=False)}],
                   "chosen_candidate_id": a["candidate_id"], "rejected_candidate_id": b["candidate_id"],
                   "score_hashes": [digest(a), digest(b)], "rubric_version": VERSION,
                   "status": "provisional_teacher_preference_requires_review"}


def export_accepted(scores):
    for score in scores:
        try:
            validated_score(score)
        except (ValueError, TypeError, KeyError):
            continue
        if score["split"] == "train" and score["decision"] == "accept":
            packet = score["packet"]
            yield {"id": score["id"], "candidate_id": score["candidate_id"],
                   "domain": score["domain"], "split": "train", "prompt": packet["prompt"],
                   "completion": [{"role": "assistant", "content": json.dumps(packet["candidate"], ensure_ascii=False)}],
                   "valid_refs": packet["valid_refs"], "score_hash": digest(score),
                   "supervision": "provisional_rejection_sft_requires_review"}


def _calibration_metrics(evidence):
    _require(isinstance(evidence, list), "Missing reviewed calibration evidence")
    seen, ids, domains, models = set(), set(), set(), set()
    for entry in evidence:
        review = entry.get("review", {})
        _require(review.get("human_reviewed") is True and review.get("synthetic") is False
                 and review.get("split") == "dev"
                 and review.get("decision") in {"accept", "reject"}
                 and entry.get("predicted") in {"accept", "reject"}
                 and all(_text(review.get(k)) for k in ("id", "candidate_id", "reviewer", "reviewed_at",
                                                        "evidence_uri", "score_hash")),
                 "Missing reviewed calibration evidence")
        key = (review["id"], review["candidate_id"])
        _require(key not in seen, "Duplicate reviewed candidate")
        seen.add(key)
        ids.add(review["id"])
        if _text(entry.get("domain")):
            domains.add(entry["domain"])
        _require(_text(entry.get("model")), "Missing frozen judge model")
        models.add(entry["model"])
    _require(len(models) == 1, "Calibration must use one frozen judge model")
    accepts = sum(e["review"]["decision"] == "accept" for e in evidence)
    rejects = len(evidence) - accepts
    metrics = {"n": len(evidence), "pages": len(ids), "domains": len(domains),
               "accepts": accepts, "rejects": rejects,
               "agreement": sum(e["predicted"] == e["review"]["decision"] for e in evidence) / max(1, len(evidence)),
               "false_accept_rate": sum(e["predicted"] == "accept" and e["review"]["decision"] == "reject"
                                        for e in evidence) / max(1, rejects)}
    return metrics, next(iter(models))


def _calibration_passes(metrics):
    return (metrics["n"] >= 20 and metrics["pages"] >= 10 and metrics["domains"] >= 3
            and metrics["accepts"] >= 5 and metrics["rejects"] >= 5
            and metrics["agreement"] >= .8 and metrics["false_accept_rate"] <= .1)


def calibrate(scores, reviews):
    """Use actual human development reviews; preserve the final test holdout."""
    indexed = {(s["id"], s["candidate_id"]): s for s in scores}
    _require(len(indexed) == len(scores), "Duplicate score identity")
    evidence, seen = [], set()
    for review in reviews:
        key = (review["id"], review["candidate_id"])
        _require(key not in seen, "Duplicate reviewed candidate")
        seen.add(key)
        _require(review.get("human_reviewed") is True and review.get("synthetic") is False
                 and all(_text(review.get(k)) for k in ("reviewer", "reviewed_at", "evidence_uri")),
                 "Calibration needs actual held-out human review provenance")
        _require(review.get("decision") in {"accept", "reject"}, "Review must accept or reject")
        score = indexed[key]
        _require(score["split"] == "dev" and review.get("split") == "dev",
                 "Calibration requires dev reviews held out from optimization; test stays untouched")
        _require(review.get("score_hash") == digest(score), "Review must bind exact score artifact")
        # Unknown predictions stop calibration; they are never silently dropped
        # or converted to true rejects to improve agreement.
        packet = _validated_packet(score)
        _require(score["decision"] in {"accept", "revise", "reject"},
                 "Unassessed results cannot calibrate reward")
        if score["result"] is not None:
            result = validate_judgment(packet, score["result"])
            _require(derive_decision(packet, result) == score["decision"], "Calibration decision mismatch")
        else:
            _require(bool(packet["preflight"]["errors"]) and score["decision"] == "reject",
                     "Unjudged results cannot calibrate reward")
        evidence.append({"review": review, "model": score["model"], "domain": score["domain"],
                         "predicted": "accept" if score["decision"] == "accept" else "reject"})
    metrics, model = _calibration_metrics(evidence)
    return {"rubric_version": VERSION, "rubric_hash": digest(RUBRIC_PATH.read_text()),
            "model": model, "status": "reviewed_pilot_gate_passed" if _calibration_passes(metrics) else "uncalibrated",
            "metrics": metrics,
            "review_evidence": evidence, "review_hash": digest(reviews),
            "limitations": "Small offline acceptance calibration only; not evidence of RL benefit or accessibility outcomes."}


def reward_for_score(score, calibration=None):
    """Fail closed until a provenance-backed development calibration is supplied."""
    _require(isinstance(calibration, dict)
             and calibration.get("status") == "reviewed_pilot_gate_passed", "Reward judge is uncalibrated")
    _require(calibration.get("rubric_version") == VERSION
             and calibration.get("rubric_hash") == score["rubric_hash"]
             and calibration.get("model") == score["model"], "Calibration does not match frozen judge")
    evidence = calibration.get("review_evidence", [])
    _require(len(evidence) >= 20, "Missing reviewed calibration evidence")
    metrics, model = _calibration_metrics(evidence)
    _require(_calibration_passes(metrics) and metrics == calibration.get("metrics")
             and model == score["model"]
             and calibration.get("review_hash") == digest([e["review"] for e in evidence]),
             "Reviewed calibration thresholds or provenance do not match")
    _require(score["split"] == "train", "Held-out examples cannot receive optimization rewards")
    result = validated_score(score)
    # Conservative ordinal proxy, not a measurement of human utility.
    return min(c["score"] for c in result["criteria"].values()) / 3.0


def _packets(args):
    rows = read_jsonl(args.data)
    indexed = {row["id"]: row for row in rows}
    _require(len(indexed) == len(rows), "Duplicate dataset IDs")
    seen = set()
    for prediction in read_jsonl(args.predictions):
        key = (prediction["id"], prediction["candidate_id"])
        _require(key not in seen, "Duplicate candidate ID for the same example")
        seen.add(key)
        yield build_packet(indexed[prediction["id"]], prediction)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("packets", "score"):
        command = commands.add_parser(name)
        command.add_argument("--data", required=True)
        command.add_argument("--predictions", required=True)
        command.add_argument("--output", required=True)
        if name == "score":
            command.add_argument("--judge-results", help="Offline JSONL: id,candidate_id,packet_hash,result")
            command.add_argument("--model", default=DEFAULT_MODEL)
            command.add_argument("--token-file", help="Private verified lab credential envelope")
            command.add_argument("--max-calls", type=int, default=12)
            command.add_argument("--request-interval", type=float, default=10)
    for name in ("preferences", "accepted", "calibrate"):
        command = commands.add_parser(name)
        command.add_argument("--scores", required=True)
        command.add_argument("--output", required=True)
        if name == "calibrate":
            command.add_argument("--reviews", required=True)
    args = parser.parse_args(argv)
    if args.command == "packets":
        write_jsonl(args.output, _packets(args))
    elif args.command in {"preferences", "accepted"}:
        export = export_preferences if args.command == "preferences" else export_accepted
        write_jsonl(args.output, export(read_jsonl(args.scores)))
    elif args.command == "calibrate":
        calibration = calibrate(read_jsonl(args.scores), read_jsonl(args.reviews))
        Path(args.output).write_text(json.dumps(calibration, indent=2) + "\n")
    else:
        _require(args.max_calls >= 0, "max-calls must be nonnegative")
        packets = list(_packets(args))
        offline, client = {}, None
        if args.judge_results:
            results = read_jsonl(args.judge_results)
            offline = {(r["id"], r["candidate_id"]): r for r in results}
            _require(len(offline) == len(results), "Duplicate offline judgment")
        else:
            from harness.model import LabClient
            client = LabClient(Path(args.output).with_suffix(".calls"), token_file=args.token_file,
                               max_calls=args.max_calls, min_interval=args.request_interval)

        def run():
            for packet in packets:
                raw, error, metadata = None, None, None
                if packet["preflight"]["errors"]:
                    pass
                elif args.judge_results:
                    supplied = offline.get((packet["id"], packet["candidate_id"]))
                    if supplied is None or supplied.get("packet_hash") != digest(packet):
                        error = "Missing offline judgment or packet hash mismatch"
                    else:
                        raw = supplied.get("result")
                elif client is None:
                    raise RuntimeError("Hosted scoring requires an initialized lab client")
                elif client.calls >= args.max_calls:
                    error = "Model call budget exhausted; candidate left unjudged"
                else:
                    try:
                        raw, metadata = client.generate(args.model, RUBRIC_PATH.read_text(),
                                                        json.dumps(packet, ensure_ascii=False),
                                                        purpose="training-rubric-judge", max_tokens=8192)
                    except (RuntimeError, ValueError, OSError) as exception:
                        error = f"Judge call failed ({type(exception).__name__}); see private call logs"
                observed_model = metadata.get("model_version", args.model) if metadata else args.model
                score = score_packet(packet, raw, model=observed_model, error=error)
                score["requested_model"] = args.model
                score["metadata"] = metadata
                score["judgment_source"] = "offline" if args.judge_results else "hosted"
                yield score

        write_jsonl(args.output, run())


if __name__ == "__main__":
    main()
