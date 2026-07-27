#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_manifest as validator  # noqa: E402


EXAMPLE_MANIFEST = Path(__file__).resolve().parent / "examples" / "manifest.example.jsonl"


def make_record(
    recording_id: str,
    *,
    split: str = "dev",
    purpose: str = "enrollment",
    target: str = "owner001",
    speakers: list[str] | None = None,
    target_present: bool = True,
    speech_mode: str = "separate",
    source: str | None = None,
    session: str | None = None,
    audio_hash: str | None = None,
) -> dict[str, object]:
    speakers = speakers or [target]
    duration_ms = 6000
    turns = [
        {
            "start_ms": 100 + index * 500,
            "end_ms": 5500,
            "speaker_id": speaker,
            "text": f"reference-{speaker}",
        }
        for index, speaker in enumerate(speakers)
    ]
    regions = [{"start_ms": 1000, "end_ms": 5000}] if speech_mode == "overlap" else []
    return {
        "schema_version": "1.0",
        "recording_id": recording_id,
        "source_recording_id": source or f"src-{recording_id}",
        "split": split,
        "domain": "office" if purpose == "enrollment" else "traffic",
        "purpose": purpose,
        "audio_path": f"audio/{recording_id}.wav",
        "audio_sha256": audio_hash or (f"{len(recording_id) % 16:x}" * 64),
        "session_id": session or f"session-{recording_id}",
        "site_id": "site-a",
        "recorded_date": "2026-07-01",
        "language": "zh-CN",
        "dialect": None,
        "content_mode": "scripted",
        "target_speaker_id": target,
        "speaker_ids": speakers,
        "target_present": target_present,
        "speech_mode": speech_mode,
        "audio": {
            "sample_rate_hz": 16000,
            "channels": 1,
            "sample_width_bits": 16,
            "duration_ms": duration_ms,
        },
        "capture": {
            "device_model": "device",
            "device_batch": "batch",
            "os_version": "os",
            "sdk_version": "sdk",
            "mic_placement": "chest",
            "distance_cm": 30,
            "scene": "scene",
            "snr_db": 10,
            "wind_level": "low",
            "traffic_level": "medium",
        },
        "turns": turns,
        "overlap_regions": regions,
    }


def make_protocol() -> dict[str, object]:
    return {
        "protocol_version": "1.0",
        "status": "frozen",
        "study_id": "unit-test-study",
        "use_case": "target-speaker-filter",
        "decision_unit": "utterance",
        "primary_domain": "traffic",
        "primary_metrics": ["far", "frr", "coverage"],
        "operating_point": {
            "target_prior_source": "unit-test",
            "false_accept_cost": "unit-test",
            "false_reject_cost": "unit-test",
            "abstain_policy": "retain-and-mark",
            "threshold_selection_split": "dev",
        },
        "confidence": {
            "method": "cluster_bootstrap",
            "level": 0.95,
            "cluster_keys": ["target_speaker_id", "session_id"],
        },
        "evidence_requirements": {
            "basis": "unit-test fixture, not a production sample plan",
            "totals": {
                "dev_owners": 1,
                "dev_separate_positive": 1,
                "dev_separate_negative": 1,
                "blind_owners": 1,
                "blind_separate_positive": 1,
                "blind_separate_negative": 1,
            },
            "per_target": {
                "dev": {"separate_positive": 1, "separate_negative": 1},
                "blind": {"separate_positive": 1, "separate_negative": 1},
            },
            "min_enrollment_sessions_per_target": {"dev": 1, "blind": 1},
            "min_probe_sessions_per_target": {"dev": 1, "blind": 1},
            "min_probe_dates_per_target": {"dev": 1, "blind": 1},
            "require_unseen_blind_site": False,
        },
        "blind_usage": "single_pass",
    }


class ValidateManifestTest(unittest.TestCase):
    def test_checked_in_example_is_structurally_valid(self) -> None:
        records, load_errors = validator.load_jsonl(EXAMPLE_MANIFEST)
        errors, warnings, summary = validator.validate_records(records)

        self.assertEqual(load_errors, [])
        self.assertEqual(errors, [])
        self.assertTrue(warnings)
        self.assertEqual(summary["dev_separate_positive"], 1)
        self.assertEqual(summary["dev_separate_negative"], 1)
        self.assertEqual(summary["dev_overlap"], 1)

    def test_target_present_must_match_annotated_speakers(self) -> None:
        record = make_record(
            "probe-negative",
            purpose="probe",
            speakers=["other001"],
            target_present=True,
        )

        errors = validator.validate_record(record, 1)

        self.assertTrue(any("target_present must exactly match" in error for error in errors))

    def test_subthreshold_audio_is_retained_for_quality_and_abstention_evaluation(self) -> None:
        record = make_record("short-probe", purpose="probe")
        record["audio"]["duration_ms"] = 1000
        record["turns"] = [
            {"start_ms": 50, "end_ms": 950, "speaker_id": "owner001", "text": "短句"}
        ]

        errors = validator.validate_record(record, 1)

        self.assertFalse(any("audio.duration_ms" in error for error in errors))

    def test_overlap_region_must_have_two_speakers_active(self) -> None:
        record = make_record(
            "probe-overlap",
            purpose="probe",
            speakers=["owner001", "other001"],
            speech_mode="overlap",
        )
        record["turns"] = [
            {"start_ms": 0, "end_ms": 900, "speaker_id": "owner001", "text": "甲"},
            {"start_ms": 5100, "end_ms": 5900, "speaker_id": "other001", "text": "乙"},
        ]

        errors = validator.validate_record(record, 1)

        self.assertTrue(any("no verified two-speaker intersection" in error for error in errors))

    def test_speaker_identity_cannot_cross_dev_and_blind(self) -> None:
        dev = make_record("dev-enroll", split="dev")
        blind = make_record("blind-enroll", split="blind")
        blind["audio_sha256"] = "a" * 64

        errors, _, _ = validator.validate_records([dev, blind])

        self.assertTrue(any("speaker_id 'owner001' crosses splits" in error for error in errors))

    def test_source_recording_cannot_cross_splits_even_with_different_clips(self) -> None:
        dev = make_record("dev-enroll", split="dev", source="shared-source")
        blind = make_record(
            "blind-enroll",
            split="blind",
            target="owner999",
            source="shared-source",
            audio_hash="b" * 64,
        )

        errors, _, _ = validator.validate_records([dev, blind])

        self.assertTrue(any("source_recording_id 'shared-source' crosses splits" in error for error in errors))

    def test_duplicate_audio_content_is_rejected(self) -> None:
        first = make_record("enroll-a", target="owner001", audio_hash="c" * 64)
        second = make_record("enroll-b", target="owner002", audio_hash="c" * 64)

        errors, _, _ = validator.validate_records([first, second])

        self.assertTrue(any("duplicate audio_sha256" in error for error in errors))

    def test_probe_target_requires_an_enrollment(self) -> None:
        probe = make_record("probe-one", purpose="probe")
        probe["audio_sha256"] = "d" * 64

        errors, _, _ = validator.validate_records([probe])

        self.assertTrue(any("has 0 enrollment sessions; require >= 1" in error for error in errors))

    def test_formal_mode_checks_required_metadata_and_configured_scale(self) -> None:
        record = make_record("enroll-only")
        del record["recorded_date"]
        protocol = make_protocol()
        protocol["evidence_requirements"]["totals"]["blind_owners"] = 2

        errors, _, summary = validator.validate_records(
            [record], acceptance=True, protocol=protocol
        )

        self.assertEqual(summary["records"], 1)
        self.assertTrue(any("requires recorded_date" in error for error in errors))
        self.assertTrue(any("blind_owners=0, require >= 2" in error for error in errors))

    def test_formal_mode_enforces_protocol_per_owner_quota(self) -> None:
        records = [
            make_record("enroll-0", session="enroll-session-0", audio_hash="1" * 64)
        ]
        probe = make_record("one-positive", purpose="probe")
        probe["audio_sha256"] = "e" * 64
        records.append(probe)
        protocol = make_protocol()
        protocol["evidence_requirements"]["per_target"]["dev"]["separate_positive"] = 2

        errors, _, _ = validator.validate_records(
            records, acceptance=True, protocol=protocol
        )

        self.assertTrue(
            any("target 'owner001' in split 'dev' has separate_positive=1; require >= 2" in error
                for error in errors)
        )

    def test_formal_mode_rejects_draft_protocol(self) -> None:
        protocol = make_protocol()
        protocol["status"] = "draft"

        errors, _, _ = validator.validate_records([], acceptance=True, protocol=protocol)

        self.assertIn("protocol: status must be 'frozen' before a formal gate", errors)

    def test_check_audio_files_verifies_pcm_properties_and_hash(self) -> None:
        record = make_record("audio-check")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / str(record["audio_path"])
            path.parent.mkdir(parents=True)
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\0\0" * 16000 * 6)
            import hashlib

            record["audio_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

            errors = validator.check_audio_files([record], root)

        self.assertEqual(errors, [])

    def test_invalid_jsonl_is_reported_without_aborting_later_rows(self) -> None:
        valid = make_record("valid-row")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.jsonl"
            path.write_text("{bad json}\n" + json.dumps(valid) + "\n", encoding="utf-8")

            records, errors = validator.load_jsonl(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
