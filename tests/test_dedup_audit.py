from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import run_dedup_audit
from text_utils import sha256_text, stable_chunk_id


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "dedup-benchmark" / "cases.json"


class DedupAuditTests(unittest.TestCase):
    def test_fixture_covers_both_themes_and_all_decisions(self) -> None:
        report = run_dedup_audit.audit_cases(CASES)

        self.assertGreaterEqual(report["case_count"], 10)
        self.assertEqual(report["themes"], ["ancient_rome", "medieval_japan"])
        self.assertEqual(
            {item["expected_semantic_decision"] for item in report["results"]},
            {
                "confirmed_repeat",
                "probable_repeat_review",
                "new_angle",
                "new_finding",
            },
        )

    def test_current_0_2_baseline_is_reproducible(self) -> None:
        report = run_dedup_audit.audit_cases(CASES)

        self.assertEqual(report["baseline_mismatches"], [])
        self.assertEqual(
            report["summary"],
            {
                "correct": 4,
                "false_repeat": 4,
                "missed_repeat": 3,
                "new_angle_not_represented": 2,
            },
        )

    def test_false_repeats_are_visible_in_both_historical_themes(self) -> None:
        report = run_dedup_audit.audit_cases(CASES)
        themes = {
            item["theme"]
            for item in report["results"]
            if item["assessment"] == "false_repeat"
        }

        self.assertEqual(themes, {"ancient_rome", "medieval_japan"})

    def test_chunk_id_tracks_location_not_text_or_finding_identity(self) -> None:
        original_id = stable_chunk_id("Chronicle/book.txt", None, None, 4)
        same_location_after_ocr_fix = stable_chunk_id(
            "Chronicle/book.txt", None, None, 4
        )
        shifted_boundary_id = stable_chunk_id("Chronicle/book.txt", None, None, 5)

        self.assertEqual(original_id, same_location_after_ocr_fix)
        self.assertNotEqual(original_id, shifted_boundary_id)
        self.assertNotEqual(
            sha256_text("three amph0rae in the store"),
            sha256_text("three amphorae in the store"),
        )

    def test_cli_can_write_a_human_readable_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taira-dedup-audit-") as directory:
            output = Path(directory) / "baseline.md"
            exit_code = run_dedup_audit.main(
                ["--cases", str(CASES), "--check", "--output", str(output)]
            )

            self.assertEqual(exit_code, 0)
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("rome-01-distinct-neighbouring-events", rendered)
            self.assertIn("false_repeat", rendered)


if __name__ == "__main__":
    unittest.main()
