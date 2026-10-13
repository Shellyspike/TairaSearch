from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import daily_five
import research_findings
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

    def test_historical_0_2_baseline_is_preserved(self) -> None:
        report = run_dedup_audit.audit_cases(CASES)

        self.assertEqual(
            report["baseline_summary"],
            {
                "correct": 4,
                "false_repeat": 4,
                "missed_repeat": 3,
                "new_angle_not_represented": 2,
            },
        )

    def test_current_improvements_match_reviewed_expectations(self) -> None:
        report = run_dedup_audit.audit_cases(CASES)

        self.assertEqual(report["improved_mismatches"], [])

    def test_false_repeats_are_visible_in_both_historical_themes(self) -> None:
        report = run_dedup_audit.audit_cases(CASES)
        themes = {
            item["theme"]
            for item in report["results"]
            if item["baseline_assessment"] == "false_repeat"
        }

        self.assertEqual(themes, {"ancient_rome", "medieval_japan"})

    def test_distinct_nearby_events_are_preserved_by_both_selectors(self) -> None:
        candidates = [
            {
                "chunk_id": "bath",
                "retrieval_score": 2.0,
                "relative_path": "miscellany.txt",
                "chunk_no": 5,
                "person": ["Lucius"],
                "topics": ["daily-life"],
                "source_group": "Municipal Notes",
                "what_happened": "A cracked bath pipe delayed the opening.",
            },
            {
                "chunk_id": "bread",
                "retrieval_score": 1.0,
                "relative_path": "miscellany.txt",
                "chunk_no": 6,
                "person": ["Lucius"],
                "topics": ["daily-life"],
                "source_group": "Municipal Notes",
                "what_happened": "Workers divided bread after the carts arrived late.",
            },
        ]

        self.assertEqual(len(daily_five._collapse_neighbours(candidates)), 2)
        self.assertEqual(len(research_findings._collapse_candidates(candidates)), 2)
        self.assertEqual(
            daily_five.candidate_pair_check(*candidates)["action"], "review"
        )

    def test_near_identical_evidence_can_still_be_collapsed(self) -> None:
        candidates = [
            {
                "chunk_id": "first",
                "retrieval_score": 2.0,
                "relative_path": "ledger.txt",
                "chunk_no": 2,
                "person": [],
                "topics": ["material-culture"],
                "source_group": "Harbour Ledger",
                "what_happened": "A clerk counted three amphorae after the storm.",
            },
            {
                "chunk_id": "second",
                "retrieval_score": 1.0,
                "relative_path": "ledger.txt",
                "chunk_no": 3,
                "person": [],
                "topics": ["material-culture"],
                "source_group": "Harbour Ledger",
                "what_happened": "A clerk counted three amphorae after the storm.",
            },
        ]

        self.assertEqual(len(daily_five._collapse_neighbours(candidates)), 1)
        self.assertEqual(len(research_findings._collapse_candidates(candidates)), 1)

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
