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
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
import taira_search  # noqa: E402
from search_schema import upsert_fts_chunk  # noqa: E402
from text_utils import normalize_text, split_text  # noqa: E402


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

    def test_plain_query_and_current_filters(self) -> None:
        result = self.run_cli(
            "search", "--query", "清盛", "--source-type", "historical", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row["source_type"] == "historical" for row in rows))

        result = self.run_cli(
            "search", "--query", "清盛", "--source", "Кириллица", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all("Кириллица" in row["relative_path"] for row in rows))

    def test_text_normalization_and_chunk_bounds(self) -> None:
        self.assertEqual(normalize_text("Ａ　 B\r\nC"), "A B C")
        chunks = split_text("文。" * 4000)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 3000 for chunk in chunks))

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

    def test_read_only_runtime_sees_committed_wal_updates(self) -> None:
        root = self.root / "wal-visibility"
        corpus = root / "corpus"
        corpus.mkdir(parents=True)
        (corpus / "base.txt").write_text("Base WAL document", encoding="utf-8")
        db = root / "index.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                build_index.main(
                    [
                        str(corpus),
                        "--db",
                        str(db),
                        "--log",
                        str(root / "errors.log"),
                    ]
                ),
                0,
            )

        writer = sqlite3.connect(db)
        writer.row_factory = sqlite3.Row
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            source = writer.execute("SELECT * FROM chunks LIMIT 1").fetchone()
            columns = [item[1] for item in writer.execute("PRAGMA table_info(chunks)")]
            copied_columns = [name for name in columns if name != "id"]
            values = {name: source[name] for name in copied_columns}
            values.update(
                {
                    "chunk_id": "ch_committed_only_in_wal",
                    "filename": "wal.txt",
                    "relative_path": "wal/wal.txt",
                    "original_text": "FreshWALMarker committed update",
                    "normalized_text": "FreshWALMarker committed update",
                    "preview": "FreshWALMarker committed update",
                    "text_hash": "wal-marker-hash",
                }
            )
            placeholders = ",".join("?" for _ in copied_columns)
            writer.execute(
                f"INSERT INTO chunks({','.join(copied_columns)}) VALUES({placeholders})",
                [values[name] for name in copied_columns],
            )
            upsert_fts_chunk(
                writer,
                values["chunk_id"],
                values["normalized_text"],
                values["preview"],
                values["aliases_json"],
                values["topics_json"],
            )
            writer.commit()
            wal_path = db.with_name(f"{db.name}-wal")
            self.assertTrue(wal_path.is_file())
            self.assertGreater(wal_path.stat().st_size, 0)

            args = taira_search.make_parser().parse_args(
                ["search", "--query", "FreshWALMarker", "--db", str(db)]
            )
            reader = taira_search.load_runtime(args)
            try:
                rows = taira_search.search_database(reader, args)
                self.assertEqual(rows[0]["chunk_id"], "ch_committed_only_in_wal")
                with self.assertRaises(sqlite3.OperationalError):
                    reader.execute("DELETE FROM chunks")
            finally:
                reader.close()
        finally:
            writer.close()

    def test_read_only_runtime_handles_checkpointed_database_without_sidecars(
        self,
    ) -> None:
        root = self.root / "wal-sidecars-absent"
        corpus = root / "corpus"
        corpus.mkdir(parents=True)
        (corpus / "base.txt").write_text("Checkpointed document", encoding="utf-8")
        db = root / "index.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                build_index.main(
                    [
                        str(corpus),
                        "--db",
                        str(db),
                        "--log",
                        str(root / "errors.log"),
                    ]
                ),
                0,
            )
        for suffix in ("-wal", "-shm"):
            db.with_name(f"{db.name}{suffix}").unlink(missing_ok=True)

        args = taira_search.make_parser().parse_args(
            ["search", "--query", "Checkpointed", "--db", str(db)]
        )
        connection = taira_search.load_runtime(args)
        try:
            self.assertGreater(
                connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 0
            )
        finally:
            connection.close()

    def test_read_only_runtime_reports_unavailable_wal_access(self) -> None:
        args = taira_search.make_parser().parse_args(
            ["search", "--query", "清盛", "--db", str(self.db)]
        )
        with mock.patch.object(
            taira_search.sqlite3,
            "connect",
            side_effect=sqlite3.OperationalError("unable to open database file"),
        ), self.assertRaisesRegex(RuntimeError, "WAL"):
            taira_search.load_runtime(args)

    def test_read_only_runtime_rejects_missing_database(self) -> None:
        missing = self.root / "missing-index.sqlite3"
        args = taira_search.make_parser().parse_args(
            ["search", "--query", "清盛", "--db", str(missing)]
        )
        with self.assertRaisesRegex(RuntimeError, "Индекс не найден"):
            taira_search.load_runtime(args)

    def test_read_only_runtime_rejects_legacy_schema_without_migration(self) -> None:
        root = self.root / "legacy-migration"
        root.mkdir()
        db = root / "legacy.sqlite3"
        with contextlib.closing(sqlite3.connect(db)) as connection:
            connection.executescript(
                """
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE chunks(
                    id INTEGER PRIMARY KEY,
                    chunk_id TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    chunk_no INTEGER NOT NULL,
                    original_text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    aliases_json TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    search_terms_json TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    is_duplicate INTEGER NOT NULL DEFAULT 0
                );
                CREATE VIRTUAL TABLE chunks_fts USING
                    fts5(chunk_id UNINDEXED, normalized_text, tokenize='trigram');
                INSERT INTO chunks VALUES(
                    1, 'legacy_chunk', 'Chronicle', 'legacy.txt',
                    'Chronicle/legacy.txt', NULL, NULL, 1,
                    'legacy text', 'legacy text', 'legacy text',
                    '[]', '[]', '[]', 'legacy-hash', 0
                );
                INSERT INTO chunks_fts VALUES('legacy_chunk', 'legacy text');
                """
            )
        before = db.read_bytes()
        args = taira_search.make_parser().parse_args(
            ["search", "--query", "legacy", "--db", str(db)]
        )

        with self.assertRaisesRegex(RuntimeError, "Устаревшая схема"):
            taira_search.load_runtime(args)

        self.assertEqual(db.read_bytes(), before)
        self.assertEqual(list(root.glob("legacy.sqlite3*.bak")), [])
        with contextlib.closing(sqlite3.connect(db)) as connection:
            columns = {
                item[1] for item in connection.execute("PRAGMA table_info(chunks)")
            }
            self.assertFalse(
                {"source_type", "people_json", "text_quality"} & columns
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0],
                1,
            )

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
