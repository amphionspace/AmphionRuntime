#!/usr/bin/env python3
"""Validate the shape and honesty rules of the diarization E2E matrix.

The matrix deliberately does not infer a product verdict from one metric.  It
requires every case to name all pipeline stages, user-visible gates, evidence
binding, and unresolved blockers.  ``--check-evidence`` is an optional local
check because private device artifacts are not committed to this repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STATUSES = {"PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN"}
GATES = {"identityAccuracy", "realtime", "memory", "readability", "lifecycle", "offline", "identityStability", "honesty"}
DEFAULT_MATRIX = Path(__file__).with_name("diarization_acceptance_matrix.json")
REPO_ROOT = Path(__file__).resolve().parents[3]


class MatrixError(ValueError):
    """The acceptance matrix cannot be trusted as a delivery record."""


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise MatrixError(f"{context} is missing {key!r}")
    return mapping[key]


def _status(value: Any, context: str) -> str:
    if value not in STATUSES:
        raise MatrixError(f"{context} has invalid status {value!r}")
    return value


def _resolve_evidence(path: str, repo_root: Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else repo_root / candidate


def validate(matrix: dict[str, Any], *, repo_root: Path = REPO_ROOT,
             check_evidence: bool = False) -> dict[str, Any]:
    if _require(matrix, "schemaVersion", "matrix") != 1:
        raise MatrixError("matrix schemaVersion must be 1")
    matrix_id = _require(matrix, "matrixId", "matrix")
    if not isinstance(matrix_id, str) or not matrix_id:
        raise MatrixError("matrixId must be a non-empty string")

    baseline = _require(matrix, "baseline", "matrix")
    if not isinstance(baseline, dict):
        raise MatrixError("baseline must be an object")
    for key in ("commit", "device", "artifact", "input"):
        value = _require(baseline, key, "baseline")
        if not isinstance(value, str) or not value:
            raise MatrixError(f"baseline.{key} must be a non-empty string")
    if baseline.get("offlineRequired") is not True:
        raise MatrixError("baseline.offlineRequired must be true")

    stages = _require(matrix, "requiredStages", "matrix")
    if not isinstance(stages, list) or not stages or len(set(stages)) != len(stages):
        raise MatrixError("requiredStages must be a non-empty list of unique strings")
    if not all(isinstance(stage, str) and stage for stage in stages):
        raise MatrixError("requiredStages must contain non-empty strings")

    policy = _require(matrix, "thresholdPolicy", "matrix")
    if not isinstance(policy, dict) or not policy:
        raise MatrixError("thresholdPolicy must be a non-empty object")
    if any(not isinstance(value, str) or not value for value in policy.values()):
        raise MatrixError("thresholdPolicy values must be non-empty strings")

    cases = _require(matrix, "cases", "matrix")
    if not isinstance(cases, list) or not cases:
        raise MatrixError("cases must be a non-empty list")
    case_ids: set[str] = set()
    summary: dict[str, int] = {status: 0 for status in sorted(STATUSES)}
    checked_evidence = 0
    missing_evidence: list[str] = []

    for index, case in enumerate(cases):
        context = f"cases[{index}]"
        if not isinstance(case, dict):
            raise MatrixError(f"{context} must be an object")
        case_id = _require(case, "id", context)
        if not isinstance(case_id, str) or not case_id:
            raise MatrixError(f"{context}.id must be a non-empty string")
        if case_id in case_ids:
            raise MatrixError(f"duplicate case id {case_id!r}")
        case_ids.add(case_id)
        if not isinstance(_require(case, "description", context), str):
            raise MatrixError(f"{context}.description must be a string")
        case_status = _status(_require(case, "status", context), f"{context}.status")
        summary[case_status] += 1

        case_stages = _require(case, "requiredStages", context)
        if not isinstance(case_stages, list) or set(case_stages) != set(stages):
            raise MatrixError(f"{context}.requiredStages must cover matrix.requiredStages exactly")
        if len(case_stages) != len(stages):
            raise MatrixError(f"{context}.requiredStages contains duplicate stages")

        gates = _require(case, "gates", context)
        if not isinstance(gates, dict) or set(gates) != GATES:
            raise MatrixError(f"{context}.gates must contain exactly {sorted(GATES)}")
        for gate, value in gates.items():
            _status(value, f"{context}.gates.{gate}")
        if case_status == "PASS" and set(gates.values()) != {"PASS"}:
            raise MatrixError(f"{context} cannot be PASS while a gate is incomplete or FAIL")
        if case_status == "FAIL" and "FAIL" not in gates.values():
            raise MatrixError(f"{context} marked FAIL without a failed gate")

        evidence = _require(case, "evidence", context)
        if not isinstance(evidence, list) or not evidence:
            raise MatrixError(f"{context}.evidence must be a non-empty list")
        for evidence_index, item in enumerate(evidence):
            evidence_context = f"{context}.evidence[{evidence_index}]"
            if not isinstance(item, dict):
                raise MatrixError(f"{evidence_context} must be an object")
            for key in ("kind", "path", "binding", "reason"):
                value = _require(item, key, evidence_context)
                if not isinstance(value, str) or not value:
                    raise MatrixError(f"{evidence_context}.{key} must be non-empty")
            evidence_path = _resolve_evidence(item["path"], repo_root)
            if check_evidence:
                checked_evidence += 1
                if not evidence_path.is_file():
                    missing_evidence.append(str(evidence_path))

        blockers = _require(case, "blockingReasons", context)
        if not isinstance(blockers, list) or any(not isinstance(value, str) or not value for value in blockers):
            raise MatrixError(f"{context}.blockingReasons must be a list of non-empty strings")
        if case_status in {"FAIL", "INCONCLUSIVE", "NOT_RUN"} and not blockers:
            raise MatrixError(f"{context} needs a blocker explanation for status {case_status}")
        if case_status == "PASS" and blockers:
            raise MatrixError(f"{context} cannot have blockers while marked PASS")

    result = {
        "schemaVersion": 1,
        "matrixId": matrix_id,
        "caseCount": len(cases),
        "statusCounts": summary,
        "requiredStages": stages,
        "checkedEvidence": checked_evidence,
        "missingEvidence": missing_evidence,
        "validationStatus": "FAIL" if missing_evidence else "PASS",
        "matrixStatus": (
            "FAIL" if summary["FAIL"] else
            "INCONCLUSIVE" if summary["INCONCLUSIVE"] or summary["NOT_RUN"] else
            "PASS"
        ),
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--check-evidence", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    result = validate(matrix, check_evidence=args.check_evidence)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 1 if result["validationStatus"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
