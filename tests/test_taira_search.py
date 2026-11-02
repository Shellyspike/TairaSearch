from __future__ import annotations

import contextlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
import taira_search  # noqa: E402


class TairaSearchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        work_root = PROJECT / "work"
        work_root.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="search-tests-", dir=work_root)
        cls.root = Path(cls.temp.name)
        cls.corpus = cls.root / "corpus"
        shutil.copytree(PROJECT / "sample_corpus", cls.corpus)
        cls.db = cls.root / "index.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = build_index.main(
                [
                    str(cls.corpus),
                    "--db",
                    str(cls.db),
                    "--log",
                    str(cls.root / "index.log"),
                    "--source-types",
                    str(PROJECT / "examples" / "source-types.medieval-japan.json"),
                ]
            )
        if code:
            raise AssertionError(f"test index failed with exit code {code}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_cli(self, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(PROJECT / "taira_search.py"),
                command,
                *arguments,
                "--db",
                str(self.db),
            ],
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def test_plain_query_and_source_filter(self) -> None:
        result = self.run_cli(
            "search", "--query", "清盛", "--source-type", "historical", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row["source_type"] == "historical" for row in rows))

    def test_context_returns_neighbouring_chunks(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            chunk_id = connection.execute(
                "SELECT chunk_id FROM chunks WHERE relative_path LIKE '%граница%' "
                "AND chunk_no=2"
            ).fetchone()[0]
        result = self.run_cli(
            "context", chunk_id, "--before", "1", "--after", "1", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row["chunk_no"] for row in rows], [1, 2])
        self.assertEqual(sum(bool(row["target"]) for row in rows), 1)

    def test_runtime_is_read_only_and_reads_current_schema(self) -> None:
        args = taira_search.make_parser().parse_args(
            ["search", "--query", "清盛", "--db", str(self.db)]
        )
        connection = taira_search.load_runtime(args)
        try:
            self.assertGreater(
                connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 0
            )
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM chunks")
        finally:
            connection.close()

    def test_new_index_has_no_dictionary_annotations(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            rows = connection.execute(
                "SELECT aliases_json, topics_json, people_json FROM chunks"
            ).fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(row == ("[]", "[]", "[]") for row in rows))

    def test_legacy_dictionary_options_and_commands_are_removed(self) -> None:
        for arguments in (
            ("search", "--query", "清盛", "--aliases", "missing.json"),
            ("search", "--person", "清盛"),
            ("search", "--topic", "illness"),
            ("events", "--query", "清盛"),
            ("daily-five",),
            ("mark-used", "chunk"),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(PROJECT / "taira_search.py"), *arguments],
                    cwd=PROJECT,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)

    def test_indexer_and_search_do_not_require_legacy_dictionary_files(self) -> None:
        for name in ("people.json", "aliases.json", "topics.json", "search_index.py"):
            self.assertFalse((PROJECT / name).exists())
        root = self.root / "dictionary-free"
        corpus = root / "corpus"
        corpus.mkdir(parents=True)
        (corpus / "story.txt").write_text(
            "A bronze bell revealed a hidden chamber in a complete historical story.",
            encoding="utf-8",
        )
        db = root / "index.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                build_index.main(
                    [str(corpus), "--db", str(db), "--log", str(root / "log.txt")]
                ),
                0,
            )
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "taira_search.py"),
                "search",
                "--db",
                str(db),
                "--query",
                "bronze bell",
                "--json",
            ],
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_missing_explicit_source_type_file_is_an_error(self) -> None:
        root = self.root / "missing-source-types"
        corpus = root / "corpus"
        corpus.mkdir(parents=True)
        (corpus / "story.txt").write_text("A complete story.", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(
            RuntimeError, "source_types.json"
        ):
            build_index.build_index(
                build_index.make_parser().parse_args(
                    [
                        str(corpus),
                        "--db",
                        str(root / "index.sqlite3"),
                        "--log",
                        str(root / "log.txt"),
                        "--source-types",
                        str(root / "missing.json"),
                    ]
                )
            )

    def test_research_findings_uses_profile_people_and_interests(self) -> None:
        root = self.root / "profile-driven"
        corpus = root / "corpus"
        corpus.mkdir(parents=True)
        (corpus / "story.txt").write_text(
            "Archivist Ada found a bronze bell beneath the floor. The complete "
            "account explains how the chamber was opened and recorded.",
            encoding="utf-8",
        )
        db = root / "index.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                build_index.main(
                    [str(corpus), "--db", str(db), "--log", str(root / "log.txt")]
                ),
                0,
            )
        profile = root / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "search_mode": "open",
                    "name": "Profile-only vocabulary",
                    "research_area": "Synthetic archive history",
                    "result_language": "en",
                    "max_results": 1,
                    "interests": [
                        {
                            "id": "bells",
                            "label": "Hidden bells",
                            "terms": ["bronze bell"],
                            "weight": 1.0,
                        }
                    ],
                    "focus_people": [
                        {"name": "Ada", "aliases": ["Archivist Ada"]}
                    ],
                    "material_types": ["other"],
                    "finding_preferences": {
                        "preferred_kinds": [],
                        "include_unlisted_people": True,
                        "avoid_person_repetition": True,
                        "notes": "",
                    },
                }
            ),
            encoding="utf-8",
        )
        output = root / "findings.json"
        used = root / "used.csv"
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "taira_search.py"),
                "research-findings",
                "--db",
                str(db),
                "--profile",
                str(profile),
                "--used-finds",
                str(used),
                "--output",
                str(output),
                "--preview",
            ],
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["final"][0]["person"], ["Ada"])
        self.assertEqual(payload["final"][0]["primary_topic"], "bells")
        self.assertFalse(used.exists())


if __name__ == "__main__":
    unittest.main()
