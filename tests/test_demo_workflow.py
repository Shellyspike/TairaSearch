from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
import run_demo  # noqa: E402
import taira_search  # noqa: E402


class DemoWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="taira-demo-test-")
        cls.root = Path(cls.temp.name)
        cls.database = cls.root / "index.sqlite3"
        cls.expected = json.loads(
            (PROJECT / "examples" / "demo" / "expected_results.json").read_text(
                encoding="utf-8"
            )
        )
        with contextlib.redirect_stdout(io.StringIO()):
            code = build_index.main(
                [
                    str(PROJECT / "sample_corpus"),
                    "--db",
                    str(cls.database),
                    "--drive-csv",
                    str(cls.root / "drive.csv"),
                    "--drive-jsonl",
                    str(cls.root / "drive.jsonl"),
                    "--log",
                    str(cls.root / "index.log"),
                    "--rebuild",
                ]
            )
        if code:
            raise AssertionError(f"demo corpus build failed with exit code {code}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def search(self, query: str, *, include_duplicates: bool = False) -> list[dict]:
        arguments = [
            "search",
            "--db",
            str(self.database),
            "--query",
            query,
            "--top",
            "20",
            "--json",
        ]
        if include_duplicates:
            arguments.append("--include-duplicates")
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = taira_search.main(arguments)
        self.assertEqual(code, 0, errors.getvalue())
        return [json.loads(line) for line in output.getvalue().splitlines() if line]

    def test_multilingual_queries_match_golden_results(self) -> None:
        for case in self.expected["queries"]:
            with self.subTest(language=case["language"]):
                results = self.search(case["query"])
                self.assertTrue(results)
                self.assertEqual(
                    results[0]["relative_path"], case["expected_first_path"]
                )

    def test_exact_duplicate_and_similar_events_are_both_represented(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" for _ in self.expected["exact_duplicate_paths"])
            rows = connection.execute(
                f"""
                SELECT relative_path, text_hash, is_duplicate
                FROM chunks WHERE relative_path IN ({placeholders})
                ORDER BY relative_path
                """,
                self.expected["exact_duplicate_paths"],
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["text_hash"] for row in rows}), 1)
        self.assertEqual(sum(row["is_duplicate"] for row in rows), 1)

        similar = self.search("Shigemori OR 平重盛", include_duplicates=True)
        paths = {row["relative_path"] for row in similar}
        self.assertTrue(set(self.expected["similar_event_paths"]).issubset(paths))

    def test_ambiguous_romanized_name_does_not_match_short_catalogue_label(self) -> None:
        expected = self.expected["ambiguous_names"]
        connection = sqlite3.connect(self.database)
        try:
            rows = dict(
                connection.execute(
                    "SELECT relative_path, people_json FROM chunks WHERE relative_path IN (?, ?)",
                    (expected["detected_path"], expected["non_person_path"]),
                )
            )
        finally:
            connection.close()
        self.assertEqual(json.loads(rows[expected["detected_path"]]), expected["detected_people"])
        self.assertEqual(json.loads(rows[expected["non_person_path"]]), [])

    def test_adjacent_context_recovers_both_sides_of_chunk_boundary(self) -> None:
        boundary = self.expected["chunk_boundary"]
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            rows = taira_search.context_rows(
                connection, boundary["right_chunk_id"], before=1, after=0
            )
        finally:
            connection.close()
        self.assertEqual([row["chunk_no"] for row in rows], [1, 2])
        self.assertIn(boundary["left_text"], rows[0]["text"])
        self.assertNotIn(boundary["right_text"], rows[0]["text"])
        self.assertNotIn(boundary["left_text"], rows[1]["text"])
        self.assertIn(boundary["right_text"], rows[1]["text"])

    def test_daily_five_matches_golden_candidates(self) -> None:
        output_path = self.root / "candidates.json"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = taira_search.main(
                [
                    "daily-five",
                    "--db",
                    str(self.database),
                    "--used-finds",
                    str(self.root / "empty-used-finds.csv"),
                    "--output",
                    str(output_path),
                    "--json",
                ]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        actual = [
            {
                "chunk_id": item["chunk_id"],
                "relative_path": item["relative_path"],
                "primary_topic": item["primary_topic"],
            }
            for item in payload["final"]
        ]
        self.assertEqual(actual, self.expected["daily_five"])
        self.assertTrue(all(item["verified_context"]["status"] == "ok" for item in payload["final"]))

    def test_one_command_demo_creates_only_local_outputs(self) -> None:
        demo_dir = self.root / "one-command"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run_demo.main(["--work-dir", str(demo_dir)])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertTrue((demo_dir / "index.sqlite3").is_file())
        self.assertTrue((demo_dir / "search.jsonl").is_file())
        payload = json.loads((demo_dir / "candidates.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["final"]), 5)
        self.assertEqual(
            [item["chunk_id"] for item in payload["final"]],
            [item["chunk_id"] for item in self.expected["daily_five"]],
        )
        generated_ai_input = json.loads(
            (demo_dir / "ai-input.json").read_text(encoding="utf-8")
        )
        committed_ai_input = json.loads(
            (PROJECT / "examples" / "demo" / "ai-input.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(generated_ai_input, committed_ai_input)
        serialized = json.dumps(generated_ai_input, ensure_ascii=False)
        self.assertNotIn(str(PROJECT), serialized)
        self.assertNotIn("generated_at_utc", serialized)
        self.assertTrue(
            all(
                item["material_status"]
                == "synthetic_demo_not_historical_evidence"
                for item in generated_ai_input["candidates"]
            )
        )

    def test_saved_ai_output_is_five_explicitly_synthetic_sourced_cards(self) -> None:
        ai_input = json.loads(
            (PROJECT / "examples" / "demo" / "ai-input.json").read_text(
                encoding="utf-8"
            )
        )
        output = (PROJECT / "examples" / "demo" / "ai-output.md").read_text(
            encoding="utf-8"
        )
        normalized_output = " ".join(output.split())
        self.assertIn("Codex app output", output)
        self.assertEqual(output.count("[ДЕМО]"), 5)
        self.assertEqual(
            output.count("вымышленный тестовый эпизод, не историческое сведение"),
            5,
        )
        for heading in (
            "**Что случилось.**",
            "**Почему это интересно.**",
            "**Фрагмент.**",
            "**Источник.**",
        ):
            self.assertEqual(output.count(heading), 5)
        for candidate in ai_input["candidates"]:
            self.assertIn(candidate["relative_path"], output)
            self.assertIn(candidate["chunk_id"], output)
            self.assertIn(candidate["source_type"], output)
            self.assertIn(" ".join(candidate["source_excerpt"].split()), normalized_output)
            if candidate["date"]:
                self.assertIn(candidate["date"], output)
            if candidate["place"]:
                self.assertIn(candidate["place"], output)
        windows_home_prefix = "C:" + "\\Users\\"
        self.assertNotIn(windows_home_prefix, output)

    def test_ai_demo_documentation_preserves_python_ai_boundary(self) -> None:
        documentation = (PROJECT / "docs" / "ai-demo.md").read_text(
            encoding="utf-8"
        )
        request = (PROJECT / "examples" / "demo" / "codex-request.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "run_demo.py",
            "python -m venv .venv",
            "Primary workflow: one Codex app request",
            "work/demo/ai-input.json",
            "examples/codex/daily-news-prompt.md",
            "codex exec --ephemeral --sandbox read-only",
            "work/demo/ai-cards.md",
            "examples/demo/ai-output.md",
            "What Python and AI each do",
        ):
            self.assertIn(required, documentation)
        self.assertNotIn("py -3.11 -m venv .venv", documentation)
        self.assertIn("only source evidence", request)
        self.assertIn("Do not browse the web", request)
        self.assertIn("exactly five", request)
        self.assertIn("publication journal", request)
        self.assertIn("work/demo/ai-cards.md", request)
        self.assertIn("Optional alternative: Codex CLI", documentation)
        self.assertIn("No nested", documentation)


if __name__ == "__main__":
    unittest.main()
