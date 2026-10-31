from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_five
import research_findings
import run_dedup_audit
from text_utils import sha256_text, stable_chunk_id


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "dedup-benchmark" / "cases.json"
RESEARCH_WORKFLOW = ROOT / "examples" / "codex" / "research-workflow.md"


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

    def test_near_identical_factual_changes_require_review_in_both_selectors(
        self,
    ) -> None:
        variants = {
            "number": "A clerk counted four amphorae after the storm.",
            "date": "In 1181 a clerk counted three amphorae after the storm.",
            "negation": "A clerk did not count three amphorae after the storm.",
            "outcome": "A clerk counted three amphorae, which were destroyed after the storm.",
        }
        original = "A clerk counted three amphorae after the storm."

        for label, changed in variants.items():
            with self.subTest(change=label):
                candidates = [
                    {
                        "chunk_id": f"{label}-first",
                        "retrieval_score": 2.0,
                        "relative_path": "ledger.txt",
                        "chunk_no": 2,
                        "person": [],
                        "topics": ["material-culture"],
                        "source_group": "Harbour Ledger",
                        "what_happened": original,
                    },
                    {
                        "chunk_id": f"{label}-second",
                        "retrieval_score": 1.0,
                        "relative_path": "ledger.txt",
                        "chunk_no": 3,
                        "person": [],
                        "topics": ["material-culture"],
                        "source_group": "Harbour Ledger",
                        "what_happened": changed,
                    },
                ]

                pair = daily_five.candidate_pair_check(*candidates)
                self.assertEqual(pair["action"], "review")
                self.assertEqual(len(daily_five._collapse_neighbours(candidates)), 2)
                self.assertEqual(
                    len(research_findings._collapse_candidates(candidates)), 2
                )

    def test_shared_labels_never_confirm_a_history_duplicate(self) -> None:
        payload = json.loads(CASES.read_text(encoding="utf-8"))
        case = next(
            item
            for item in payload["cases"]
            if item["id"] == "jp-04-same-person-theme-different-event"
        )

        result = daily_five.duplicate_check(case["candidate"], case["used"])

        self.assertEqual(result["status"], "duplicate_risk")
        self.assertFalse(result["auto_exclude"])
        self.assertTrue(result["requires_editorial_review"])
        self.assertEqual(result["python_disposition"], "needs_semantic_review")

    def test_cross_language_match_is_preserved_with_prior_context(self) -> None:
        payload = json.loads(CASES.read_text(encoding="utf-8"))
        case = next(
            item
            for item in payload["cases"]
            if item["id"] == "rome-02-paraphrase-across-languages"
        )

        result = daily_five.duplicate_check(case["candidate"], case["used"])

        self.assertEqual(result["status"], "duplicate_risk")
        self.assertEqual(len(result["review_matches"]), 1)
        self.assertEqual(
            result["review_matches"][0]["prior"]["description"],
            case["used"][0]["description"],
        )
        self.assertEqual(
            set(result["allowed_semantic_decisions"]),
            {
                "confirmed_repeat",
                "probable_repeat_review",
                "new_angle",
                "new_finding",
            },
        )

    def test_scholarship_match_is_flagged_as_a_possible_new_angle(self) -> None:
        payload = json.loads(CASES.read_text(encoding="utf-8"))
        case = next(
            item
            for item in payload["cases"]
            if item["id"] == "jp-05-new-interpretation-of-known-event"
        )

        result = daily_five.duplicate_check(case["candidate"], case["used"])

        self.assertEqual(result["status"], "duplicate_risk")
        self.assertTrue(result["review_matches"][0]["possible_new_angle"])
        self.assertEqual(
            result["review_matches"][0]["candidate_claim_type"], "interpretation"
        )

    def test_exact_chunk_and_claim_remain_a_confirmed_technical_repeat(self) -> None:
        candidate = {
            "chunk_id": "same-location",
            "what_happened": "A clerk counted three amphorae after the storm.",
            "person": [],
            "topics": ["material-culture"],
            "source_group": "Harbour Ledger",
        }
        used = [
            {
                "id": "same-location",
                "description": "A clerk counted three amphorae after the storm.",
                "persons": [],
                "topics": ["material-culture"],
                "source": "Harbour Ledger",
            }
        ]

        result = daily_five.duplicate_check(candidate, used)

        self.assertEqual(result["status"], "duplicate")
        self.assertTrue(result["auto_exclude"])
        self.assertFalse(result["requires_editorial_review"])

    def test_same_chunk_id_with_changed_claim_requires_review_in_both_selectors(
        self,
    ) -> None:
        candidate = {
            "chunk_id": "same-location",
            "retrieval_score": 2.0,
            "relative_path": "ledger.txt",
            "chunk_no": 4,
            "source": "Harbour Ledger",
            "source_group": "Harbour Ledger",
            "primary_topic": "material-culture",
            "person": [],
            "topics": ["material-culture"],
            "what_happened": "A porter opened the granary after the storm.",
        }
        used = [
            {
                "id": "same-location",
                "description": "A clerk closed the harbour gate before the storm.",
                "persons": [],
                "topics": ["material-culture"],
                "source": "Harbour Ledger",
            }
        ]

        result = daily_five.duplicate_check(candidate, used)
        candidate["duplicate_check"] = result
        daily_five.attach_semantic_reviews([candidate])

        self.assertEqual(result["status"], "duplicate_risk")
        self.assertFalse(result["auto_exclude"])
        self.assertTrue(result["requires_editorial_review"])
        self.assertTrue(
            result["review_matches"][0]["signals"][
                "positional_id_claim_changed"
            ]
        )
        self.assertEqual(
            candidate["semantic_review"]["history_matches"][0]["prior"][
                "description"
            ],
            used[0]["description"],
        )
        self.assertEqual(
            [item["chunk_id"] for item in daily_five._select_diverse([candidate], 1)],
            ["same-location"],
        )
        self.assertEqual(
            [
                item["chunk_id"]
                for item in research_findings._select_diverse(
                    [candidate],
                    1,
                    {"finding_preferences": {"avoid_person_repetition": False}},
                )
            ],
            ["same-location"],
        )

    def test_published_neighbour_is_sent_to_review_by_both_selectors(self) -> None:
        candidate = {
            "chunk_id": "new-target",
            "retrieval_score": 2.0,
            "relative_path": "journal.pdf",
            "chunk_no": 3,
            "source": "Theatre Studies",
            "source_group": "Theatre Studies",
            "primary_topic": "zeami",
            "person": ["Zeami"],
            "topics": ["zeami"],
            "what_happened": "The next section discusses transmission among pupils.",
            "verified_context": {
                "chunks": [
                    {
                        "chunk_id": "published-neighbour",
                        "chunk_no": 2,
                        "text": "The earlier section describes the formation of the treatise.",
                    },
                    {
                        "chunk_id": "new-target",
                        "chunk_no": 3,
                        "text": "The next section discusses transmission among pupils.",
                    },
                ]
            },
        }
        used = [
            {
                "id": "published-neighbour",
                "description": "A study of how the treatise took shape.",
                "persons": ["Zeami"],
                "topics": ["zeami"],
                "source": "Theatre Studies",
            }
        ]

        result = daily_five.duplicate_check(candidate, used)
        candidate["duplicate_check"] = result
        daily_five.attach_semantic_reviews([candidate])

        self.assertEqual(result["status"], "duplicate_risk")
        self.assertFalse(result["auto_exclude"])
        self.assertTrue(result["requires_editorial_review"])
        self.assertTrue(
            result["review_matches"][0]["signals"][
                "published_chunk_in_verified_context"
            ]
        )
        self.assertEqual(
            [item["chunk_id"] for item in daily_five._select_diverse([candidate], 1)],
            ["new-target"],
        )
        self.assertEqual(
            [
                item["chunk_id"]
                for item in research_findings._select_diverse(
                    [candidate],
                    1,
                    {"finding_preferences": {"avoid_person_repetition": False}},
                )
            ],
            ["new-target"],
        )

    def test_uncertain_history_match_remains_eligible_in_both_selectors(self) -> None:
        uncertain = {
            "chunk_id": "uncertain",
            "retrieval_score": 2.0,
            "source_group": "Chronicle",
            "primary_topic": "daily-life",
            "topics": ["daily-life"],
            "person": ["Lucius"],
            "duplicate_check": {
                "status": "duplicate_risk",
                "auto_exclude": False,
            },
        }
        confirmed = {
            **uncertain,
            "chunk_id": "confirmed",
            "retrieval_score": 3.0,
            "duplicate_check": {
                "status": "duplicate",
                "auto_exclude": True,
            },
        }

        daily_selected = daily_five._select_diverse([confirmed, uncertain], 2)
        research_selected = research_findings._select_diverse(
            [confirmed, uncertain],
            2,
            {"finding_preferences": {"avoid_person_repetition": False}},
        )

        self.assertEqual([item["chunk_id"] for item in daily_selected], ["uncertain"])
        self.assertEqual(
            [item["chunk_id"] for item in research_selected], ["uncertain"]
        )

    def test_semantic_review_packet_contains_comparison_evidence(self) -> None:
        candidates = [
            {
                "chunk_id": "first",
                "title": "Bath repair",
                "relative_path": "notes.txt",
                "chunk_no": 1,
                "source": "Notes",
                "source_group": "Notes",
                "person": [],
                "topics": ["daily-life"],
                "what_happened": "The bath pipe cracked.",
                "verified_context": {"chunks": [{"text": "The bath pipe cracked."}]},
                "duplicate_check": {
                    "requires_editorial_review": False,
                    "review_matches": [],
                },
            },
            {
                "chunk_id": "second",
                "title": "Bread ration",
                "relative_path": "notes.txt",
                "chunk_no": 2,
                "source": "Notes",
                "source_group": "Notes",
                "person": [],
                "topics": ["daily-life"],
                "what_happened": "Workers divided the remaining bread.",
                "verified_context": {"chunks": [{"text": "Workers divided bread."}]},
                "duplicate_check": {
                    "requires_editorial_review": False,
                    "review_matches": [],
                },
            },
        ]

        daily_five.attach_semantic_reviews(candidates)

        review = candidates[0]["semantic_review"]
        self.assertTrue(review["required"])
        self.assertEqual(review["decision_owner"], "codex")
        self.assertEqual(review["candidate_matches"][0]["matched_chunk_id"], "second")
        self.assertEqual(
            review["candidate_matches"][0]["candidate"]["what_happened"],
            candidates[1]["what_happened"],
        )

    def test_research_workflow_requires_all_four_semantic_classes(self) -> None:
        prompt = RESEARCH_WORKFLOW.read_text(encoding="utf-8")

        for decision in daily_five.SEMANTIC_DECISIONS:
            self.assertIn(f"`{decision}`", prompt)
        self.assertIn("semantic_review", prompt)
        self.assertIn("Shared people, topics, sources, dates", prompt)
        self.assertIn("positional `chunk_id`", prompt)
        self.assertIn("Do not publish confirmed repeats", prompt)
        self.assertIn("Keep unresolved probable repeats visible", prompt)

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

    def test_cli_reconfigures_a_legacy_windows_console_to_utf8(self) -> None:
        output = io.BytesIO()
        legacy_console = io.TextIOWrapper(
            output, encoding="cp1252", errors="strict", write_through=True
        )

        with patch.object(sys, "stdout", legacy_console):
            exit_code = run_dedup_audit.main(["--cases", str(CASES), "--check"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(legacy_console.encoding, "utf-8")
        self.assertIn("Киёмори", output.getvalue().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
