#!/usr/bin/env python3
"""Validate and compare Dingqiao customer-hotword capacity device runs.

The analyzer deliberately treats the profile sidecar as part of each report.  A
TSV without its matching sidecar is not accepted because the TSV does not carry
the selected customer-hotword count or ordered-prefix SHA-256.

Expected matrix:

* profiles: ``full`` and ``prune_ui28``;
* customer-hotword counts: 50, 100, 101 and 200;
* optional extra control count: 0;
* one immutable manifest and metadata file for every run.

Outputs are ``summary.json``, ``runs.tsv``, ``probes.tsv``,
``comparisons.tsv`` and ``capacity_101_to_200.tsv``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SUPPORTED_PROFILES = ("full", "prune_ui28")
SUPPORTED_COUNTS = frozenset({0, 50, 100, 101, 200})
REQUIRED_COUNTS = frozenset({50, 100, 101, 200})
EXPECTED_FULL_DOMAIN_COUNTS = {"terms": 355, "plate": 6, "station": 10}
EMPTY_ORDERED_LINES_SHA256 = hashlib.sha256(b"").hexdigest()
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")

MANIFEST_FIELDS = {
    "asset_file",
    "role",
    "customer_index",
    "expected_station",
    "reference_text",
    "source_file",
    "source_sha256",
    "sha256",
    "duration_s",
}
REPORT_FIELDS = {
    "run_id",
    "hotword_profile",
    "police_enhancement",
    "file",
    "duration_s",
    "status",
    "final_count",
    "text",
    "errors",
}
PROFILE_FIELDS = {
    "run_id",
    "hotword_profile",
    "police_enhancement",
    "customer_hotword_asset",
    "customer_hotword_available",
    "customer_hotword_count",
    "customer_hotword_sha256",
}
METADATA_FIELDS = {
    "schema_version",
    "full_effective_hotword_count",
    "full_domain_counts",
    "real_customer_hotword_count",
    "capacity_filler_count",
    "total_asset_hotword_count",
    "hotword_asset_sha256",
    "customer_hotword_prefix_sha256",
    "probe_count",
    "source_cases_sha256",
    "source_gazetteer_sha256",
    "source_full_hotwords_sha256",
    "manifest_sha256",
}


class ValidationError(ValueError):
    """Input evidence is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class ManifestCase:
    asset_file: str
    role: str
    customer_index: int | None
    expected_station: str
    reference_text: str


@dataclass(frozen=True)
class Run:
    run_id: str
    profile: str
    police_enhancement: bool
    customer_hotword_asset: str
    customer_hotword_available: int
    customer_hotword_count: int
    customer_hotword_sha256: str
    report_path: Path
    profile_path: Path
    report_sha256: str
    profile_sha256: str
    rows: Mapping[str, Mapping[str, str]]

    @property
    def key(self) -> tuple[str, int]:
        return self.profile, self.customer_hotword_count


def fail(message: str) -> None:
    raise ValidationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_nonnegative_int(raw: object, label: str) -> int:
    if isinstance(raw, bool):
        fail(f"{label} must be an integer, got boolean {raw!r}")
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        fail(f"{label} must be an integer, got {raw!r}")
    if value < 0:
        fail(f"{label} must be non-negative, got {value}")
    return value


def parse_bool(raw: object, label: str) -> bool:
    if raw == "true" or raw is True:
        return True
    if raw == "false" or raw is False:
        return False
    fail(f"{label} must be exactly true or false, got {raw!r}")


def validate_sha256(raw: object, label: str) -> str:
    value = str(raw).strip().lower()
    if not HEX_SHA256.fullmatch(value):
        fail(f"{label} must be a 64-character SHA-256, got {raw!r}")
    return value


def require_fields(actual: Iterable[str], required: set[str], label: str) -> None:
    missing = sorted(required - set(actual))
    if missing:
        fail(f"{label} is missing required fields: {', '.join(missing)}")


def read_tsv(path: Path, required_fields: set[str], label: str) -> list[dict[str, str]]:
    if not path.is_file():
        fail(f"{label} does not exist: {path}")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames is None:
            fail(f"{label} has no header: {path}")
        require_fields(reader.fieldnames, required_fields, label)
        rows = list(reader)
    if not rows:
        fail(f"{label} has no data rows: {path}")
    return rows


def read_profile(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"profile sidecar does not exist: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            fail(f"malformed sidecar line {path}:{line_number}: {raw_line!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            fail(f"empty sidecar key at {path}:{line_number}")
        if key in values:
            fail(f"duplicate sidecar key {key!r} in {path}")
        values[key] = value.strip()
    require_fields(values, PROFILE_FIELDS, f"profile sidecar {path}")
    return values


def load_metadata(path: Path) -> dict[str, object]:
    if not path.is_file():
        fail(f"metadata does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(f"invalid metadata JSON {path}: {error}")
    if not isinstance(value, dict):
        fail(f"metadata root must be an object: {path}")
    require_fields(value, METADATA_FIELDS, f"metadata {path}")

    schema_version = parse_nonnegative_int(value["schema_version"], "metadata.schema_version")
    if schema_version != 2:
        fail(f"metadata.schema_version must be 2, got {schema_version}")
    full_count = parse_nonnegative_int(
        value["full_effective_hotword_count"], "metadata.full_effective_hotword_count"
    )
    if full_count != 370:
        fail(f"metadata.full_effective_hotword_count must be 370, got {full_count}")
    domain_counts = value["full_domain_counts"]
    if not isinstance(domain_counts, dict):
        fail("metadata.full_domain_counts must be an object")
    if set(domain_counts) != set(EXPECTED_FULL_DOMAIN_COUNTS):
        fail(
            "metadata.full_domain_counts must contain exactly terms, plate and station, "
            f"got {sorted(domain_counts)}"
        )
    parsed_domain_counts = {
        domain: parse_nonnegative_int(raw_count, f"metadata.full_domain_counts.{domain}")
        for domain, raw_count in domain_counts.items()
    }
    if parsed_domain_counts != EXPECTED_FULL_DOMAIN_COUNTS:
        fail(
            f"metadata.full_domain_counts must be {EXPECTED_FULL_DOMAIN_COUNTS}, "
            f"got {parsed_domain_counts}"
        )
    real_count = parse_nonnegative_int(
        value["real_customer_hotword_count"], "metadata.real_customer_hotword_count"
    )
    if real_count != 101:
        fail(f"metadata.real_customer_hotword_count must be 101, got {real_count}")
    filler_count = parse_nonnegative_int(
        value["capacity_filler_count"], "metadata.capacity_filler_count"
    )
    total_count = parse_nonnegative_int(
        value["total_asset_hotword_count"], "metadata.total_asset_hotword_count"
    )
    if total_count != 200:
        fail(f"metadata.total_asset_hotword_count must be 200, got {total_count}")
    if real_count + filler_count != total_count:
        fail(
            "metadata customer/filler counts do not add up: "
            f"{real_count}+{filler_count}!={total_count}"
        )
    validate_sha256(value["hotword_asset_sha256"], "metadata.hotword_asset_sha256")
    parse_nonnegative_int(value["probe_count"], "metadata.probe_count")

    prefix_hashes = value["customer_hotword_prefix_sha256"]
    if not isinstance(prefix_hashes, dict):
        fail("metadata.customer_hotword_prefix_sha256 must be an object")
    prefix_counts = {
        parse_nonnegative_int(raw_count, "metadata prefix-hash count")
        for raw_count in prefix_hashes
    }
    if prefix_counts != REQUIRED_COUNTS:
        fail(
            "metadata.customer_hotword_prefix_sha256 must contain exactly "
            f"{sorted(REQUIRED_COUNTS)}, got {sorted(prefix_counts)}"
        )
    for raw_count, raw_hash in prefix_hashes.items():
        count = parse_nonnegative_int(raw_count, "metadata prefix-hash count")
        validate_sha256(raw_hash, f"metadata prefix SHA for count {count}")
    for field in (
        "source_cases_sha256",
        "source_gazetteer_sha256",
        "source_full_hotwords_sha256",
        "manifest_sha256",
    ):
        validate_sha256(value[field], f"metadata.{field}")
    return value


def load_manifest(path: Path, metadata: Mapping[str, object]) -> dict[str, ManifestCase]:
    expected_manifest_sha = validate_sha256(
        metadata["manifest_sha256"], "metadata.manifest_sha256"
    )
    actual_manifest_sha = sha256_file(path)
    if actual_manifest_sha != expected_manifest_sha:
        fail(
            f"manifest SHA-256 {actual_manifest_sha} != metadata.manifest_sha256 "
            f"{expected_manifest_sha}"
        )
    rows = read_tsv(path, MANIFEST_FIELDS, "capacity manifest")
    expected_probe_count = parse_nonnegative_int(metadata["probe_count"], "metadata.probe_count")
    if len(rows) != expected_probe_count:
        fail(f"manifest row count {len(rows)} != metadata.probe_count {expected_probe_count}")

    result: dict[str, ManifestCase] = {}
    customer_indices: set[int] = set()
    role_counts = {"customer": 0, "full_control": 0}
    real_count = parse_nonnegative_int(
        metadata["real_customer_hotword_count"], "metadata.real_customer_hotword_count"
    )
    for line_number, row in enumerate(rows, 2):
        asset = row["asset_file"].strip()
        if not asset:
            fail(f"manifest line {line_number} has an empty asset_file")
        if asset in result:
            fail(f"duplicate manifest asset_file {asset!r}")
        role = row["role"].strip()
        if role not in role_counts:
            fail(f"manifest line {line_number} has unsupported role {role!r}")
        expected_station = row["expected_station"].strip()
        reference_text = row["reference_text"].strip()
        if not expected_station or not reference_text:
            fail(f"manifest line {line_number} has empty expected_station/reference_text")
        if not row["source_file"].strip():
            fail(f"manifest line {line_number} has an empty source_file")
        validate_sha256(row["source_sha256"], f"manifest line {line_number} source sha256")
        validate_sha256(row["sha256"], f"manifest line {line_number} audio sha256")
        try:
            duration = float(row["duration_s"])
        except ValueError:
            fail(f"manifest line {line_number} has invalid duration_s {row['duration_s']!r}")
        if duration <= 0:
            fail(f"manifest line {line_number} duration_s must be positive")

        if role == "customer":
            index = parse_nonnegative_int(row["customer_index"], f"manifest line {line_number} customer_index")
            if not 1 <= index <= real_count:
                fail(f"manifest customer_index {index} is outside 1..{real_count}")
            if index in customer_indices:
                fail(f"duplicate manifest customer_index {index}")
            customer_indices.add(index)
        else:
            if row["customer_index"].strip():
                fail(f"full_control {asset!r} must not have customer_index")
            index = None
        role_counts[role] += 1
        result[asset] = ManifestCase(asset, role, index, expected_station, reference_text)

    if not role_counts["customer"] or not role_counts["full_control"]:
        fail("manifest must contain both customer probes and full_control probes")
    for boundary in (50, 100):
        if not any(index <= boundary for index in customer_indices):
            fail(f"manifest has no loaded customer probe at boundary {boundary}")
        if not any(index > boundary for index in customer_indices):
            fail(f"manifest has no unloaded customer probe at boundary {boundary}")
    if real_count not in customer_indices:
        fail(f"manifest must include the customer_index={real_count} boundary probe")
    return result


def load_run(
    report_path: Path,
    profile_path: Path,
    manifest: Mapping[str, ManifestCase],
    metadata: Mapping[str, object],
) -> Run:
    profile_data = read_profile(profile_path)
    run_id = profile_data["run_id"].strip()
    if not run_id:
        fail(f"empty run_id in {profile_path}")
    profile = profile_data["hotword_profile"]
    if profile not in SUPPORTED_PROFILES:
        fail(f"unsupported hotword_profile {profile!r} in {profile_path}")
    police_enhancement = parse_bool(
        profile_data["police_enhancement"], f"{profile_path}:police_enhancement"
    )
    customer_asset = profile_data["customer_hotword_asset"].strip()
    if not customer_asset:
        fail(f"customer_hotword_asset must be present even for count=0: {profile_path}")
    available = parse_nonnegative_int(
        profile_data["customer_hotword_available"], f"{profile_path}:customer_hotword_available"
    )
    expected_available = parse_nonnegative_int(
        metadata["total_asset_hotword_count"], "metadata.total_asset_hotword_count"
    )
    if available != expected_available:
        fail(
            f"{profile_path}: customer_hotword_available={available}, "
            f"expected metadata total {expected_available}"
        )
    count = parse_nonnegative_int(
        profile_data["customer_hotword_count"], f"{profile_path}:customer_hotword_count"
    )
    if count not in SUPPORTED_COUNTS:
        fail(f"{profile_path}: unsupported customer_hotword_count={count}")
    if count > available:
        fail(f"{profile_path}: customer_hotword_count={count} exceeds available={available}")
    hotword_sha = validate_sha256(
        profile_data["customer_hotword_sha256"], f"{profile_path}:customer_hotword_sha256"
    )
    if count == 0 and hotword_sha != EMPTY_ORDERED_LINES_SHA256:
        fail(f"{profile_path}: count=0 must have SHA-256 {EMPTY_ORDERED_LINES_SHA256}")
    if count == expected_available:
        full_asset_sha = validate_sha256(
            metadata["hotword_asset_sha256"], "metadata.hotword_asset_sha256"
        )
        if hotword_sha != full_asset_sha:
            fail(
                f"{profile_path}: selected count={count} SHA {hotword_sha} "
                f"!= metadata asset SHA {full_asset_sha}"
            )
    prefix_hashes = metadata.get("customer_hotword_prefix_sha256")
    if isinstance(prefix_hashes, dict) and str(count) in prefix_hashes:
        expected_prefix_sha = validate_sha256(
            prefix_hashes[str(count)], f"metadata prefix SHA for count {count}"
        )
        if hotword_sha != expected_prefix_sha:
            fail(
                f"{profile_path}: selected count={count} SHA {hotword_sha} "
                f"!= metadata prefix SHA {expected_prefix_sha}"
            )

    report_rows = read_tsv(report_path, REPORT_FIELDS, "Dingqiao report")
    keyed_rows: dict[str, Mapping[str, str]] = {}
    for line_number, row in enumerate(report_rows, 2):
        asset = row["file"].strip()
        if not asset:
            fail(f"{report_path}:{line_number} has an empty file")
        if asset in keyed_rows:
            fail(f"duplicate report file {asset!r} in {report_path}")
        if row["run_id"] != run_id:
            fail(
                f"{report_path}:{line_number} run_id={row['run_id']!r} "
                f"!= sidecar run_id={run_id!r}"
            )
        if row["hotword_profile"] != profile:
            fail(
                f"{report_path}:{line_number} profile={row['hotword_profile']!r} "
                f"!= sidecar profile={profile!r}"
            )
        row_enhancement = parse_bool(
            row["police_enhancement"], f"{report_path}:{line_number}:police_enhancement"
        )
        if row_enhancement != police_enhancement:
            fail(f"{report_path}:{line_number} police_enhancement does not match sidecar")
        try:
            duration = float(row["duration_s"])
        except ValueError:
            fail(f"{report_path}:{line_number} has invalid duration_s {row['duration_s']!r}")
        if duration <= 0:
            fail(f"{report_path}:{line_number} duration_s must be positive")
        parse_nonnegative_int(row["final_count"], f"{report_path}:{line_number}:final_count")
        if row["status"] not in {"OK", "EMPTY", "ERROR", "TIMEOUT"}:
            fail(f"{report_path}:{line_number} has unsupported status {row['status']!r}")
        keyed_rows[asset] = row
    if set(keyed_rows) != set(manifest):
        missing = sorted(set(manifest) - set(keyed_rows))
        extra = sorted(set(keyed_rows) - set(manifest))
        fail(f"{report_path}: manifest/report asset mismatch; missing={missing}, extra={extra}")

    return Run(
        run_id=run_id,
        profile=profile,
        police_enhancement=police_enhancement,
        customer_hotword_asset=customer_asset,
        customer_hotword_available=available,
        customer_hotword_count=count,
        customer_hotword_sha256=hotword_sha,
        report_path=report_path,
        profile_path=profile_path,
        report_sha256=sha256_file(report_path),
        profile_sha256=sha256_file(profile_path),
        rows=keyed_rows,
    )


def validate_matrix(runs: Sequence[Run]) -> dict[tuple[str, int], Run]:
    if not runs:
        fail("at least one --run REPORT.tsv PROFILE.txt pair is required")
    by_key: dict[tuple[str, int], Run] = {}
    run_ids: set[str] = set()
    for run in runs:
        if run.key in by_key:
            fail(f"duplicate profile/count run {run.key}")
        if run.run_id in run_ids:
            fail(f"run_id must be globally unique, duplicate {run.run_id!r}")
        by_key[run.key] = run
        run_ids.add(run.run_id)

    enhancement_values = {run.police_enhancement for run in runs}
    if len(enhancement_values) != 1:
        fail("all runs must use the same police_enhancement value")
    customer_assets = {run.customer_hotword_asset for run in runs}
    if len(customer_assets) != 1:
        fail(f"all runs must use the same customer hotword asset, got {sorted(customer_assets)}")

    counts_by_profile = {
        profile: {count for run_profile, count in by_key if run_profile == profile}
        for profile in SUPPORTED_PROFILES
    }
    for profile, counts in counts_by_profile.items():
        missing = sorted(REQUIRED_COUNTS - counts)
        if missing:
            fail(f"profile {profile} is missing required customer-hotword counts {missing}")
    if counts_by_profile[SUPPORTED_PROFILES[0]] != counts_by_profile[SUPPORTED_PROFILES[1]]:
        fail(f"profiles do not cover the same count matrix: {counts_by_profile}")

    hashes_by_count: dict[int, set[str]] = {}
    for run in runs:
        hashes_by_count.setdefault(run.customer_hotword_count, set()).add(run.customer_hotword_sha256)
    for count, hashes in sorted(hashes_by_count.items()):
        if len(hashes) != 1:
            fail(f"profile runs at count={count} have different selected-prefix hashes: {sorted(hashes)}")
    one_hash_per_count = {count: next(iter(hashes)) for count, hashes in hashes_by_count.items()}
    if len(set(one_hash_per_count.values())) != len(one_hash_per_count):
        fail(f"different customer-hotword counts unexpectedly share a SHA-256: {one_hash_per_count}")
    return by_key


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(character for character in normalized if character.isalnum())


def row_valid(row: Mapping[str, str]) -> bool:
    return (
        row["status"] == "OK"
        and parse_nonnegative_int(row["final_count"], "report final_count") >= 1
        and not row["errors"].strip()
    )


def station_hit(case: ManifestCase, row: Mapping[str, str]) -> bool:
    expected = normalize_text(case.expected_station)
    return bool(expected) and row_valid(row) and expected in normalize_text(row["text"])


def sentence_exact(case: ManifestCase, row: Mapping[str, str]) -> bool:
    return row_valid(row) and normalize_text(case.reference_text) == normalize_text(row["text"])


def load_state(case: ManifestCase, count: int) -> str:
    if case.role == "full_control":
        return "full_control"
    assert case.customer_index is not None
    return "loaded" if case.customer_index <= count else "unloaded"


def ratio(hits: int, total: int) -> float | None:
    return hits / total if total else None


def run_summary(run: Run, manifest: Mapping[str, ManifestCase]) -> dict[str, object]:
    summary: dict[str, object] = {
        "run_id": run.run_id,
        "hotword_profile": run.profile,
        "police_enhancement": run.police_enhancement,
        "customer_hotword_asset": run.customer_hotword_asset,
        "customer_hotword_available": run.customer_hotword_available,
        "customer_hotword_count": run.customer_hotword_count,
        "customer_hotword_sha256": run.customer_hotword_sha256,
        "report_path": str(run.report_path),
        "profile_path": str(run.profile_path),
        "report_sha256": run.report_sha256,
        "profile_sha256": run.profile_sha256,
        "total_cases": len(manifest),
    }
    buckets = ("all", "customer", "loaded", "unloaded", "full_control")
    totals = {bucket: 0 for bucket in buckets}
    hits = {bucket: 0 for bucket in buckets}
    valid_count = 0
    exact_count = 0
    hard_failures = 0
    empty_count = 0
    for asset, case in manifest.items():
        row = run.rows[asset]
        state = load_state(case, run.customer_hotword_count)
        is_hit = station_hit(case, row)
        is_valid = row_valid(row)
        valid_count += int(is_valid)
        exact_count += int(sentence_exact(case, row))
        hard_failures += int(row["status"] in {"ERROR", "TIMEOUT"})
        empty_count += int(row["status"] == "EMPTY")
        memberships = ["all", state]
        if case.role == "customer":
            memberships.append("customer")
        for bucket in memberships:
            totals[bucket] += 1
            hits[bucket] += int(is_hit)
    summary.update(
        {
            "valid_cases": valid_count,
            "hard_failures": hard_failures,
            "empty_cases": empty_count,
            "sentence_exact": exact_count,
        }
    )
    for bucket in buckets:
        summary[f"{bucket}_total"] = totals[bucket]
        summary[f"{bucket}_hits"] = hits[bucket]
        summary[f"{bucket}_hit_rate"] = ratio(hits[bucket], totals[bucket])
    return summary


def build_probe_rows(runs: Sequence[Run], manifest: Mapping[str, ManifestCase]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    profile_rank = {profile: index for index, profile in enumerate(SUPPORTED_PROFILES)}
    for run in sorted(runs, key=lambda item: (item.customer_hotword_count, profile_rank[item.profile])):
        for asset, case in sorted(manifest.items()):
            row = run.rows[asset]
            output.append(
                {
                    "run_id": run.run_id,
                    "hotword_profile": run.profile,
                    "customer_hotword_count": run.customer_hotword_count,
                    "customer_hotword_sha256": run.customer_hotword_sha256,
                    "asset_file": asset,
                    "role": case.role,
                    "customer_index": "" if case.customer_index is None else case.customer_index,
                    "load_state": load_state(case, run.customer_hotword_count),
                    "expected_station": case.expected_station,
                    "reference_text": case.reference_text,
                    "status": row["status"],
                    "final_count": row["final_count"],
                    "hypothesis": row["text"],
                    "errors": row["errors"],
                    "valid": str(row_valid(row)).lower(),
                    "station_hit": str(station_hit(case, row)).lower(),
                    "sentence_exact": str(sentence_exact(case, row)).lower(),
                }
            )
    return output


def compare_scope(
    before: Run,
    after: Run,
    manifest: Mapping[str, ManifestCase],
    scope: str,
    predicate,
    comparison_kind: str,
) -> dict[str, object]:
    assets = [asset for asset, case in manifest.items() if predicate(case)]
    before_hits = 0
    after_hits = 0
    regressed = 0
    corrected = 0
    changed = 0
    for asset in assets:
        case = manifest[asset]
        left = before.rows[asset]
        right = after.rows[asset]
        left_hit = station_hit(case, left)
        right_hit = station_hit(case, right)
        before_hits += int(left_hit)
        after_hits += int(right_hit)
        regressed += int(left_hit and not right_hit)
        corrected += int(not left_hit and right_hit)
        changed += int(
            (left["status"], left["final_count"], left["text"], left["errors"])
            != (right["status"], right["final_count"], right["text"], right["errors"])
        )
    return {
        "comparison_kind": comparison_kind,
        "from_run_id": before.run_id,
        "to_run_id": after.run_id,
        "from_profile": before.profile,
        "to_profile": after.profile,
        "from_count": before.customer_hotword_count,
        "to_count": after.customer_hotword_count,
        "scope": scope,
        "total": len(assets),
        "from_hits": before_hits,
        "to_hits": after_hits,
        "hit_delta": after_hits - before_hits,
        "regressed": regressed,
        "corrected": corrected,
        "changed_outputs": changed,
    }


def build_comparisons(
    by_key: Mapping[tuple[str, int], Run], manifest: Mapping[str, ManifestCase]
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    counts = sorted({count for _, count in by_key})
    for count in counts:
        before = by_key[("full", count)]
        after = by_key[("prune_ui28", count)]
        profile_scopes = [
            ("all", lambda case: True),
            ("customer", lambda case: case.role == "customer"),
            ("loaded", lambda case, limit=count: case.role == "customer" and case.customer_index <= limit),
            ("unloaded", lambda case, limit=count: case.role == "customer" and case.customer_index > limit),
            ("full_control", lambda case: case.role == "full_control"),
        ]
        for scope, predicate in profile_scopes:
            output.append(compare_scope(before, after, manifest, scope, predicate, "profile"))

    for profile in SUPPORTED_PROFILES:
        for from_count, to_count in zip(counts, counts[1:]):
            before = by_key[(profile, from_count)]
            after = by_key[(profile, to_count)]
            count_scopes = [
                ("all", lambda case: True),
                ("customer", lambda case: case.role == "customer"),
                ("full_control", lambda case: case.role == "full_control"),
                (
                    "loaded_in_both",
                    lambda case, limit=from_count: case.role == "customer" and case.customer_index <= limit,
                ),
                (
                    "newly_loaded",
                    lambda case, low=from_count, high=to_count: (
                        case.role == "customer" and low < case.customer_index <= high
                    ),
                ),
                (
                    "unloaded_in_both",
                    lambda case, limit=to_count: case.role == "customer" and case.customer_index > limit,
                ),
            ]
            for scope, predicate in count_scopes:
                output.append(compare_scope(before, after, manifest, scope, predicate, "count"))
    return output


def build_101_to_200(
    by_key: Mapping[tuple[str, int], Run], manifest: Mapping[str, ManifestCase]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    cases: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for profile in SUPPORTED_PROFILES:
        before = by_key[(profile, 101)]
        after = by_key[(profile, 200)]
        profile_rows: list[dict[str, object]] = []
        for asset, case in sorted(manifest.items()):
            left = before.rows[asset]
            right = after.rows[asset]
            left_hit = station_hit(case, left)
            right_hit = station_hit(case, right)
            changed = (
                (left["status"], left["final_count"], left["text"], left["errors"])
                != (right["status"], right["final_count"], right["text"], right["errors"])
            )
            category = (
                "regressed"
                if left_hit and not right_hit
                else "corrected"
                if not left_hit and right_hit
                else "changed_same_hit_state"
                if changed
                else "unchanged"
            )
            item = {
                "hotword_profile": profile,
                "asset_file": asset,
                "role": case.role,
                "customer_index": "" if case.customer_index is None else case.customer_index,
                "expected_station": case.expected_station,
                "count_101_status": left["status"],
                "count_101_text": left["text"],
                "count_101_hit": str(left_hit).lower(),
                "count_200_status": right["status"],
                "count_200_text": right["text"],
                "count_200_hit": str(right_hit).lower(),
                "category": category,
            }
            cases.append(item)
            profile_rows.append(item)
        customer_rows = [row for row in profile_rows if row["role"] == "customer"]
        control_rows = [row for row in profile_rows if row["role"] == "full_control"]
        summaries.append(
            {
                "hotword_profile": profile,
                "inactive_fillers_added": 99,
                "count_101_sha256": before.customer_hotword_sha256,
                "count_200_sha256": after.customer_hotword_sha256,
                "customer_probe_total": len(customer_rows),
                "customer_hits_101": sum(row["count_101_hit"] == "true" for row in customer_rows),
                "customer_hits_200": sum(row["count_200_hit"] == "true" for row in customer_rows),
                "full_control_total": len(control_rows),
                "full_control_hits_101": sum(row["count_101_hit"] == "true" for row in control_rows),
                "full_control_hits_200": sum(row["count_200_hit"] == "true" for row in control_rows),
                "regressed": sum(row["category"] == "regressed" for row in profile_rows),
                "corrected": sum(row["category"] == "corrected" for row in profile_rows),
                "changed_outputs": sum(row["category"] != "unchanged" for row in profile_rows),
            }
        )
    return cases, summaries


def write_tsv(path: Path, rows: Sequence[Mapping[str, object]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter="\t", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    targets = {
        "summary.json",
        "runs.tsv",
        "probes.tsv",
        "comparisons.tsv",
        "capacity_101_to_200.tsv",
    }
    existing = sorted(str(path / name) for name in targets if (path / name).exists())
    if existing and not overwrite:
        fail("output files already exist; use --overwrite to replace: " + ", ".join(existing))
    path.mkdir(parents=True, exist_ok=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strictly validate and compare Dingqiao customer-hotword capacity runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""example:
  python3 analyze_customer_hotword_capacity.py \\
    --manifest device-input/customer-capacity/manifest.tsv \\
    --metadata device-input/customer-capacity/metadata.json \\
    --run results/full-050.tsv results/full-050.profile.txt \\
    --run results/prune-050.tsv results/prune-050.profile.txt \\
    --run results/full-100.tsv results/full-100.profile.txt \\
    --run results/prune-100.tsv results/prune-100.profile.txt \\
    --run results/full-101.tsv results/full-101.profile.txt \\
    --run results/prune-101.tsv results/prune-101.profile.txt \\
    --run results/full-200.tsv results/full-200.profile.txt \\
    --run results/prune-200.tsv results/prune-200.profile.txt \\
    --output-dir results/capacity-analysis
""",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument(
        "--run",
        action="append",
        nargs=2,
        metavar=("REPORT_TSV", "PROFILE_SIDECAR"),
        type=Path,
        required=True,
        help="repeat once per device run",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        metadata = load_metadata(args.metadata)
        manifest = load_manifest(args.manifest, metadata)
        runs = [
            load_run(report_path, profile_path, manifest, metadata)
            for report_path, profile_path in args.run
        ]
        by_key = validate_matrix(runs)
        prepare_output_dir(args.output_dir, args.overwrite)

        run_summaries = [
            run_summary(run, manifest)
            for run in sorted(
                runs,
                key=lambda item: (
                    item.customer_hotword_count,
                    SUPPORTED_PROFILES.index(item.profile),
                ),
            )
        ]
        probe_rows = build_probe_rows(runs, manifest)
        comparisons = build_comparisons(by_key, manifest)
        capacity_cases, capacity_summaries = build_101_to_200(by_key, manifest)
        manifest_sha = sha256_file(args.manifest)
        metadata_sha = sha256_file(args.metadata)
        summary = {
            "schema_version": 1,
            "validation": {
                "status": "PASS",
                "profiles": list(SUPPORTED_PROFILES),
                "counts": sorted({run.customer_hotword_count for run in runs}),
                "police_enhancement": runs[0].police_enhancement,
                "customer_hotword_asset": runs[0].customer_hotword_asset,
                "manifest_path": str(args.manifest),
                "manifest_sha256": manifest_sha,
                "metadata_path": str(args.metadata),
                "metadata_sha256": metadata_sha,
                "probe_count": len(manifest),
                "run_count": len(runs),
            },
            "runs": run_summaries,
            "profile_and_count_comparisons": comparisons,
            "capacity_101_to_200": capacity_summaries,
        }

        write_tsv(args.output_dir / "runs.tsv", run_summaries, list(run_summaries[0]))
        write_tsv(args.output_dir / "probes.tsv", probe_rows, list(probe_rows[0]))
        write_tsv(args.output_dir / "comparisons.tsv", comparisons, list(comparisons[0]))
        write_tsv(
            args.output_dir / "capacity_101_to_200.tsv",
            capacity_cases,
            list(capacity_cases[0]),
        )
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except ValidationError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": "PASS",
                "output_dir": str(args.output_dir),
                "runs": len(runs),
                "counts": sorted({run.customer_hotword_count for run in runs}),
                "capacity_101_to_200": capacity_summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
