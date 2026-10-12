from __future__ import annotations

import contextlib
import csv
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
import make_release  # noqa: E402
import search_index  # noqa: E402
import taira_search  # noqa: E402
from parsers import parse_file  # noqa: E402
from text_utils import normalize_text, split_text  # noqa: E402


class TairaSearchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="Тайра-тест-")
        cls.root = Path(cls.temp.name)
        cls.corpus = cls.root / "Корпус с кириллицей"
        shutil.copytree(PROJECT / "sample_corpus", cls.corpus)

        long_dir = cls.corpus / "Длинный источник"
        long_dir.mkdir()
        paragraph = "平維盛は馬と船について記した。競馬の後に落馬の記事がある。\n\n"
        (long_dir / "много_фрагментов.md").write_text(paragraph * 260, encoding="utf-8")
        (cls.corpus / "Другой источник").mkdir()
        (cls.corpus / "Другой источник" / "единичный.txt").write_text(
            "別の史料にも落馬と馬の記事がある。", encoding="utf-8"
        )
        (cls.corpus / "Другой источник" / "сломанный.json").write_text(
            "{ это не JSON", encoding="utf-8"
        )
        (cls.corpus / "Другой источник" / "длинный_search_text.txt").write_text(
            ("前文" * 500) + " СКРЫТОЕСЛОВО находится после восьмисот символов.",
            encoding="utf-8",
        )
        (cls.corpus / "Статьи" / "garbled_locator.txt").write_text(
            "#U7389#U8449 清盛 GARBLEDLOCATOR", encoding="utf-8"
        )

        cls.db = cls.root / "индекс.sqlite3"
        cls.drive_csv = cls.root / "drive_index.csv"
        cls.drive_jsonl = cls.root / "drive_index.jsonl"
        cls.log = cls.root / "index_errors.log"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = build_index.main(
                [
                    str(cls.corpus),
                    "--db",
                    str(cls.db),
                    "--drive-csv",
                    str(cls.drive_csv),
                    "--drive-jsonl",
                    str(cls.drive_jsonl),
                    "--log",
                    str(cls.log),
                    "--rebuild",
                ]
            )
        if code != 1:
            raise RuntimeError(
                "Тестовый индекс с намеренно повреждённым JSON должен "
                "завершаться со статусом completed_with_errors"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PROJECT / "search_index.py"), *arguments, "--db", str(self.db)],
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def run_fts_cli(self, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
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

    def test_fts_query_koremori(self) -> None:
        result = self.run_fts_cli("search", "--query", "維盛")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("維盛", result.stdout)
        self.assertIn("score=", result.stdout)

    def test_fts_person_and_historical_intersection(self) -> None:
        result = self.run_fts_cli(
            "search", "--person", "維盛", "--source-type", "historical", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row["source_type"] == "historical" for row in rows))
        self.assertTrue(all("維盛" in row["people"] for row in rows))

    def test_fts_topic_illness(self) -> None:
        result = self.run_fts_cli("search", "--topic", "illness", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all("illness" in row["topics"] for row in rows))

    def test_fts_kiyomori_and_illness_intersection(self) -> None:
        result = self.run_fts_cli(
            "search", "--person", "清盛", "--topic", "illness", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(
            all("清盛" in row["people"] and "illness" in row["topics"] for row in rows)
        )

    def test_fts_horse_and_historical(self) -> None:
        result = self.run_fts_cli(
            "search", "--topic", "horse", "--source-type", "historical", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(
            all(row["source_type"] == "historical" and "horse" in row["topics"] for row in rows)
        )

    def test_fts_excludes_scholarship(self) -> None:
        result = self.run_fts_cli(
            "search", "--query", "船", "--exclude-source-type", "scholarship", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row["source_type"] != "scholarship" for row in rows))

    def test_fts_garbled_locator_is_searchable(self) -> None:
        result = self.run_fts_cli(
            "search", "--query", "GARBLEDLOCATOR", "--quality", "garbled", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text_quality"], "garbled")

    def test_fts_context_returns_neighbours(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            chunk_id = connection.execute(
                """
                SELECT chunk_id FROM chunks
                WHERE source='Длинный источник' AND chunk_no=2
                """
            ).fetchone()[0]
        result = self.run_fts_cli(
            "context", chunk_id, "--before", "1", "--after", "1", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row["chunk_no"] for row in rows], [1, 2, 3])
        self.assertEqual(sum(bool(row["target"]) for row in rows), 1)

    def test_fts_json_output_has_required_fields(self) -> None:
        result = self.run_fts_cli("search", "--query", "維盛", "--top", "1", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout.strip())
        required = {
            "chunk_id", "score", "source", "filename", "path", "page_start",
            "page_end", "chunk_no", "people", "topics", "text_quality", "snippet",
        }
        self.assertTrue(required.issubset(row))

    def test_current_index_runtime_is_read_only(self) -> None:
        args = taira_search.make_parser().parse_args(
            ["search", "--query", "維盛", "--db", str(self.db)]
        )
        connection, _topics, _people = taira_search.load_runtime(args)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0,
                True,
            )
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE should_not_be_created(id INTEGER)")
        finally:
            connection.close()

    def test_fts_incremental_new_txt_without_rebuild(self) -> None:
        root = self.root / "fts-incremental"
        corpus = root / "корпус"
        corpus.mkdir(parents=True)
        (corpus / "first.txt").write_text("平維盛と船", encoding="utf-8")
        db = root / "index.sqlite3"
        common = [
            str(corpus), "--db", str(db),
            "--drive-csv", str(root / "drive.csv"),
            "--drive-jsonl", str(root / "drive.jsonl"),
            "--log", str(root / "errors.log"),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_index.main(common), 0)
        (corpus / "second.txt").write_text(
            "増分更新だけに現れる新語 増分索引語", encoding="utf-8"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_index.main(common), 0)
        result = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "search",
                "--query", "増分索引語", "--db", str(db), "--json",
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["filename"], "second.txt")

    def test_fts_legacy_database_migrates_with_backup(self) -> None:
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
                    1, 'legacy_chunk', '玉葉', 'legacy.txt', '玉葉/legacy.txt',
                    NULL, NULL, 1, '平維盛は病む', '平維盛は病む', '平維盛は病む',
                    '[]', '[]', '[]', 'legacy-hash', 0
                );
                INSERT INTO chunks_fts VALUES('legacy_chunk', '平維盛は病む');
                """
            )
        result = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "search",
                "--query", "維盛", "--db", str(db), "--json",
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout.strip())
        self.assertEqual(row["people"], ["維盛"])
        self.assertEqual(row["source_type"], "historical")
        self.assertEqual(len(list(root.glob("legacy.sqlite3.pre-fts5-v2-*.bak"))), 1)
        with contextlib.closing(sqlite3.connect(db)) as connection:
            columns = {item[1] for item in connection.execute("PRAGMA table_info(chunks)")}
            self.assertTrue({"source_type", "people_json", "text_quality"}.issubset(columns))
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0], 1
            )

    def test_daily_five_dry_run_json_and_mark_used(self) -> None:
        root = self.root / "daily-five"
        corpus = root / "корпус"
        examples = {
            "玉葉/01.txt": "治承四年、平清盛は病気となった。医師が薬を調え療治した。",
            "吉記/02.txt": "平維盛は競馬に参加した後、馬から落馬した。",
            "山槐記/03.txt": "平重衡は琵琶を弾き、笛と琴の音を聴いた。",
            "吾妻鏡/04.txt": "平時忠は捕らえられ、獄に囚われた後に配流された。",
            "平家物語/05.txt": "平宗盛は酒宴を開き、人々と宴の酒を酌み交わした。",
            "源平盛衰記/06.txt": "平知盛は火事を知り、焼失した館から人を助けた。",
        }
        for relative, text in examples.items():
            path = corpus / Path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        db = root / "index.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                build_index.main(
                    [
                        str(corpus), "--db", str(db),
                        "--drive-csv", str(root / "drive.csv"),
                        "--drive-jsonl", str(root / "drive.jsonl"),
                        "--log", str(root / "errors.log"),
                    ]
                ),
                0,
            )
        used = root / "used.csv"
        used.write_text(
            "id,type,persons,topics,short_description,source,date_used\n",
            encoding="utf-8-sig",
        )
        dry = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--used-finds", str(used), "--dry-run", "--json",
                "--top-per-topic", "10", "--pool-size", "60",
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(dry.returncode, 0, dry.stderr)
        dry_payload = json.loads(dry.stdout)
        self.assertEqual(dry_payload["final"], [])
        self.assertGreaterEqual(dry_payload["stats"]["verified_candidates"], 5)

        output = root / "daily.json"
        daily = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--used-finds", str(used), "--json",
                "--top-per-topic", "10", "--pool-size", "60", "--output", str(output),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(daily.returncode, 0, daily.stderr)
        payload = json.loads(daily.stdout)
        self.assertEqual(len(payload["final"]), 5)
        self.assertTrue(output.is_file())
        self.assertTrue(
            all(
                event["index_source_type"] in {"historical", "literary"}
                and event["text_quality"] == "good"
                and event["verified_context"]["status"] == "ok"
                and event["title_ru"]
                and event["summary_ru"]
                and event["why_interesting_ru"]
                and event["source_quote"]
                and event["source_note"]
                and "title" in event
                and "what_happened" in event
                for event in payload["final"]
            )
        )
        self.assertTrue(
            all("chunks" in event["verified_context"] for event in payload["final"])
        )

        reformatted = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--from-json", str(output), "--json",
                "--output", str(output),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(reformatted.returncode, 0, reformatted.stderr)
        reformatted_payload = json.loads(reformatted.stdout)
        self.assertEqual(
            [event["chunk_id"] for event in reformatted_payload["final"]],
            [event["chunk_id"] for event in payload["final"]],
        )
        self.assertEqual(
            reformatted_payload["retrieval_final_chunk_ids"],
            payload["retrieval_final_chunk_ids"],
        )

        marked = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "mark-used",
                str(output), "--db", str(db), "--used-finds", str(used),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(marked.returncode, 0, marked.stderr)
        with used.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["type"] == "event" for row in rows))

        after_used = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--used-finds", str(used), "--dry-run", "--json",
                "--top-per-topic", "10", "--pool-size", "60",
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(after_used.returncode, 0, after_used.stderr)
        after_payload = json.loads(after_used.stdout)
        self.assertGreaterEqual(
            after_payload["stats"]["rejected"].get("used_duplicate", 0), 5
        )

        partial_output = root / "partial.json"
        partial = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--used-finds", str(used), "--json",
                "--top-per-topic", "10", "--pool-size", "60",
                "--output", str(partial_output),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(partial.returncode, 0, partial.stderr)
        partial_payload = json.loads(partial.stdout)
        self.assertGreaterEqual(len(partial_payload["final"]), 1)
        self.assertLessEqual(len(partial_payload["final"]), 4)
        self.assertEqual(
            partial_payload["stats"]["final_count"],
            len(partial_payload["final"]),
        )
        self.assertTrue(partial_output.is_file())

        partial_text = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--used-finds", str(used),
                "--top-per-topic", "10", "--pool-size", "60",
                "--output", str(root / "partial-text.json"),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(partial_text.returncode, 0, partial_text.stderr)
        self.assertIn("Найдено подходящих новых находок", partial_text.stdout)
        self.assertIn("не дополнен до пяти домыслами", partial_text.stdout)

        marked_partial = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "mark-used",
                str(partial_output), "--db", str(db), "--used-finds", str(used),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(marked_partial.returncode, 0, marked_partial.stderr)

        used_before_empty_run = used.read_bytes()
        empty_output = root / "empty.json"
        empty = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--used-finds", str(used), "--json",
                "--top-per-topic", "10", "--pool-size", "60",
                "--output", str(empty_output),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(empty.returncode, 0, empty.stderr)
        empty_payload = json.loads(empty.stdout)
        self.assertEqual(empty_payload["final"], [])
        self.assertEqual(empty_payload["stats"]["final_count"], 0)
        self.assertTrue(empty_output.is_file())
        self.assertEqual(used.read_bytes(), used_before_empty_run)

        empty_text = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(db), "--used-finds", str(used),
                "--top-per-topic", "10", "--pool-size", "60",
                "--output", str(root / "empty-text.json"),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(empty_text.returncode, 0, empty_text.stderr)
        self.assertIn(
            "По текущим фильтрам подходящих новых находок не найдено.",
            empty_text.stdout,
        )
        self.assertNotIn("###", empty_text.stdout)
        self.assertEqual(used.read_bytes(), used_before_empty_run)

        broken_db = root / "broken.sqlite3"
        broken_db.write_bytes(b"not a SQLite database")
        broken_output = root / "broken-result.json"
        broken = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "daily-five",
                "--db", str(broken_db), "--used-finds", str(used), "--json",
                "--output", str(broken_output),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn("Ошибка:", broken.stderr)
        self.assertFalse(broken_output.exists())
        self.assertEqual(used.read_bytes(), used_before_empty_run)

        marked_again = subprocess.run(
            [
                sys.executable, str(PROJECT / "taira_search.py"), "mark-used",
                str(output), "--db", str(db), "--used-finds", str(used),
            ],
            cwd=PROJECT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(marked_again.returncode, 0, marked_again.stderr)
        self.assertIn("Добавлено", marked_again.stdout)
        self.assertIn("0", marked_again.stdout)

    def test_normalization_and_chunk_sizes(self) -> None:
        self.assertEqual(normalize_text("Ａ　 B\r\nC"), "A B C")
        chunks = split_text("文。" * 4000)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 3000 for chunk in chunks))

    def test_japanese_word_search(self) -> None:
        result = self.run_cli("落馬")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("落馬", result.stdout)

    def test_alias_expansion_and_multiple_words(self) -> None:
        result = self.run_cli("維盛 船")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("平維盛", result.stdout)
        result = self.run_cli("病 清盛")
        self.assertIn("所労", result.stdout)

    def test_source_filter(self) -> None:
        result = self.run_cli("馬", "--source", "玉葉", "--limit", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("玉葉", result.stdout)
        self.assertNotIn("Другой источник", result.stdout)

    def test_topic_search(self) -> None:
        result = self.run_cli("--topic", "horses", "--limit", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("落馬", result.stdout)

    def test_deduplication_and_paired_json(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            duplicate_count = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE is_duplicate=1"
            ).fetchone()[0]
            paired = connection.execute(
                "SELECT COUNT(*) FROM files WHERE status='paired_json'"
            ).fetchone()[0]
        self.assertGreaterEqual(duplicate_count, 1)
        self.assertGreaterEqual(paired, 1)

    def test_diversify(self) -> None:
        aliases = search_index.load_mapping(PROJECT / "aliases.json")
        topics = search_index.load_mapping(PROJECT / "topics.json")
        groups, terms = search_index.build_groups("落馬", [], aliases, topics)
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            connection.row_factory = sqlite3.Row
            connection.create_function("py_casefold", 1, lambda value: str(value).casefold())
            results = search_index.search(
                connection,
                groups,
                terms,
                query="落馬",
                source=None,
                limit=5,
                diversify_results=True,
            )
        self.assertGreaterEqual(len({row["relative_path"] for row in results}), 2)

    def test_csv_and_jsonl_exports(self) -> None:
        out_csv = self.root / "результаты.csv"
        out_jsonl = self.root / "результаты.jsonl"
        first = self.run_cli("落馬", "--output", str(out_csv))
        second = self.run_cli("落馬", "--output", str(out_jsonl))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        with out_csv.open(encoding="utf-8-sig", newline="") as stream:
            self.assertGreater(len(list(csv.DictReader(stream))), 0)
        records = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines()]
        self.assertGreater(len(records), 0)
        self.assertTrue(self.drive_csv.is_file())
        self.assertTrue(self.drive_jsonl.is_file())

    def test_drive_search_text_keeps_text_after_preview(self) -> None:
        with self.drive_csv.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        row = next(
            item for item in rows if item["filename"] == "длинный_search_text.txt"
        )
        self.assertLessEqual(len(row["preview"]), 801)
        self.assertNotIn("СКРЫТОЕСЛОВО", row["preview"])
        self.assertIn("СКРЫТОЕСЛОВО", row["search_text"])
        self.assertLessEqual(len(row["search_text"]), 3000)

        records = [
            json.loads(line)
            for line in self.drive_jsonl.read_text(encoding="utf-8").splitlines()
        ]
        json_record = next(
            item for item in records if item["filename"] == "длинный_search_text.txt"
        )
        self.assertIn("СКРЫТОЕСЛОВО", json_record["search_text"])

    def test_cyrillic_path_and_stats(self) -> None:
        result = self.run_cli("不例")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Кириллица", result.stdout)
        stats = self.run_cli("--stats")
        self.assertEqual(stats.returncode, 0, stats.stderr)
        self.assertIn("Статистика TairaSearch", stats.stdout)

    def test_broken_file_does_not_stop_indexing(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            status = connection.execute(
                "SELECT status FROM files WHERE filename='сломанный.json'"
            ).fetchone()[0]
            good_chunks = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE is_duplicate=0"
            ).fetchone()[0]
        self.assertEqual(status, "error")
        self.assertGreater(good_chunks, 0)
        self.assertIn("FILE_ERROR", self.log.read_text(encoding="utf-8"))

    def test_pdf_text_and_scan_are_accounted_for(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            statuses = dict(connection.execute("SELECT filename, status FROM files"))
        self.assertEqual(statuses.get("текстовый.pdf"), "ok")
        self.assertEqual(statuses.get("скан_без_текста.pdf"), "pdf_no_text")
        self.assertIn("PDF_NO_TEXT", self.log.read_text(encoding="utf-8"))

    def test_large_pdf_reports_page_progress_in_steps(self) -> None:
        from pypdf import PdfWriter

        pdf_path = self.root / "многостраничный_скан.pdf"
        writer = PdfWriter()
        for _ in range(55):
            writer.add_blank_page(width=300, height=400)
        with pdf_path.open("wb") as stream:
            writer.write(stream)
        events: list[tuple[int, int]] = []
        parsed = parse_file(
            pdf_path, progress_callback=lambda page, total: events.append((page, total))
        )
        self.assertTrue(parsed.pdf_without_text)
        self.assertEqual(parsed.page_count, 55)
        self.assertEqual(events[0], (0, 55))
        self.assertIn((25, 55), events)
        self.assertIn((50, 55), events)
        self.assertEqual(events[-1], (55, 55))

    def test_substring_fallback_search(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            old_mode = connection.execute(
                "SELECT value FROM meta WHERE key='fts_mode'"
            ).fetchone()[0]
            connection.execute(
                "UPDATE meta SET value='substring_fallback' WHERE key='fts_mode'"
            )
            connection.commit()
        try:
            result = self.run_cli("落馬")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("落馬", result.stdout)
        finally:
            with contextlib.closing(sqlite3.connect(self.db)) as connection:
                connection.execute(
                    "UPDATE meta SET value=? WHERE key='fts_mode'", (old_mode,)
                )
                connection.commit()

    def test_used_finds_softly_downranks_but_does_not_exclude(self) -> None:
        aliases = search_index.load_mapping(PROJECT / "aliases.json")
        topics = search_index.load_mapping(PROJECT / "topics.json")
        groups, terms = search_index.build_groups("落馬", [], aliases, topics)
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            connection.row_factory = sqlite3.Row
            connection.create_function(
                "py_casefold", 1, lambda value: str(value).casefold()
            )
            baseline = search_index.search(
                connection,
                groups,
                terms,
                query="落馬",
                source=None,
                limit=100,
                diversify_results=False,
            )
            target = baseline[0]
            used_path = self.root / "used_finds_for_test.csv"
            with used_path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "id",
                        "type",
                        "persons",
                        "topics",
                        "short_description",
                        "source",
                        "date_used",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "id": target["chunk_id"],
                        "type": "event",
                        "persons": "平維盛",
                        "topics": "horses",
                        "short_description": "競馬の後の落馬",
                        "source": target["source"],
                        "date_used": "2026-09-22",
                    }
                )
            used = search_index.load_used_finds(used_path)
            reranked = search_index.search(
                connection,
                groups,
                terms,
                query="落馬",
                source=None,
                limit=100,
                diversify_results=False,
                used_finds=used,
            )
        ids = [row["chunk_id"] for row in reranked]
        self.assertIn(target["chunk_id"], ids)
        self.assertNotEqual(reranked[0]["chunk_id"], target["chunk_id"])
        penalized = next(row for row in reranked if row["chunk_id"] == target["chunk_id"])
        self.assertGreater(penalized["used_finds_penalty"], 0)

    def test_release_zip_preserves_unicode_names(self) -> None:
        archive_path = self.root / "TairaSearch-test.zip"
        make_release.build_release(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            self.assertIn("sample_corpus/玉葉/772049_0000001.txt", names)
            self.assertIn(
                "sample_corpus/Кириллица/заметка_о_Киёмори.txt", names
            )
            self.assertFalse(any("#U" in name for name in names))
            self.assertFalse(any(name.endswith(".bak") for name in names))
            self.assertNotIn("drive_index.csv", names)
            self.assertNotIn("drive_index.jsonl", names)
            self.assertIn("daily_five.py", names)
            self.assertIn("event_cards.json", names)
            self.assertIn("source_notes.json", names)
            unicode_infos = [info for info in archive.infolist() if not info.filename.isascii()]
            self.assertTrue(unicode_infos)
            self.assertTrue(all(info.flag_bits & 0x800 for info in unicode_infos))
            extract_root = self.root / "распакованный архив"
            archive.extractall(extract_root)
        self.assertTrue(
            (extract_root / "sample_corpus" / "玉葉" / "772049_0000001.txt").is_file()
        )
        self.assertTrue(
            (
                extract_root
                / "sample_corpus"
                / "Кириллица"
                / "заметка_о_Киёмори.txt"
            ).is_file()
        )

    def test_scan_only_does_not_create_or_read_index(self) -> None:
        root = self.root / "scan-only"
        corpus = root / "корпус"
        corpus.mkdir(parents=True)
        (corpus / "пример.txt").write_text("平維盛", encoding="utf-8")
        (corpus / "метаданные.json").write_text(
            '{"text": "清盛"}', encoding="utf-8"
        )
        db = root / "не_создавать.sqlite3"
        log = root / "не_создавать.log"
        output = io.StringIO()
        with mock.patch.object(
            build_index, "parse_file", side_effect=AssertionError("content read")
        ):
            with contextlib.redirect_stdout(output):
                code = build_index.main(
                    [
                        str(corpus),
                        "--scan-only",
                        "--db",
                        str(db),
                        "--log",
                        str(log),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertFalse(db.exists())
        self.assertFalse(log.exists())
        text = output.getvalue()
        self.assertIn("Этап 1/3: поиск файлов", text)
        self.assertIn("Найдено поддерживаемых файлов: 2", text)
        self.assertIn("TXT: 1", text)
        self.assertIn("JSON: 1", text)
        self.assertIn("содержимое файлов не читалось", text)

    def test_unavailable_corpus_has_clear_error_and_no_database(self) -> None:
        root = self.root / "missing-path"
        db = root / "не_создавать.sqlite3"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = build_index.main(
                [str(root / "нет такой папки"), "--db", str(db)]
            )
        self.assertEqual(code, 1)
        self.assertFalse(db.exists())
        self.assertIn("папка корпуса недоступна", stderr.getvalue())
        self.assertIn("Google Drive for Desktop", stderr.getvalue())

    def test_verbose_and_progress_every_output(self) -> None:
        root = self.root / "verbose-progress"
        corpus = root / "корпус"
        corpus.mkdir(parents=True)
        (corpus / "01.txt").write_text("平維盛と船", encoding="utf-8")
        (corpus / "02.txt").write_text("清盛の病", encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = build_index.main(
                [
                    str(corpus),
                    "--db",
                    str(root / "index.sqlite3"),
                    "--drive-csv",
                    str(root / "drive.csv"),
                    "--drive-jsonl",
                    str(root / "drive.jsonl"),
                    "--log",
                    str(root / "errors.log"),
                    "--verbose",
                    "--progress-every",
                    "1",
                ]
            )
        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("[1/2] 01.txt", text)
        self.assertIn("TXT; chunks: 1", text)
        self.assertIn("OK,", text)
        self.assertIn("[2/2] 100.0%", text)
        self.assertIn("Этап 3/3", text)

    def test_interrupt_commits_completed_files_and_resume_skips_them(self) -> None:
        root = self.root / "interrupt-resume"
        corpus = root / "корпус"
        corpus.mkdir(parents=True)
        for number in range(1, 7):
            (corpus / f"{number:02d}.txt").write_text(
                f"Уникальный текст {number} 平維盛", encoding="utf-8"
            )
        db = root / "index.sqlite3"
        drive_csv = root / "drive.csv"
        drive_jsonl = root / "drive.jsonl"
        log = root / "errors.log"
        arguments = [
            str(corpus),
            "--db",
            str(db),
            "--drive-csv",
            str(drive_csv),
            "--drive-jsonl",
            str(drive_jsonl),
            "--log",
            str(log),
            "--progress-every",
            "1",
        ]
        original_parse = build_index.parse_file
        calls = 0

        def interrupt_on_third(path: Path, progress_callback=None):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise KeyboardInterrupt
            return original_parse(path, progress_callback=progress_callback)

        first_output = io.StringIO()
        with mock.patch.object(build_index, "parse_file", side_effect=interrupt_on_third):
            with contextlib.redirect_stdout(first_output):
                first_code = build_index.main(arguments)
        self.assertEqual(first_code, 130)
        self.assertIn("Индексация остановлена пользователем", first_output.getvalue())
        self.assertIn("Полностью обработано: 2 / 6", first_output.getvalue())
        self.assertTrue(drive_csv.is_file())

        with contextlib.closing(sqlite3.connect(db)) as connection:
            completed_before_resume = connection.execute(
                "SELECT COUNT(*) FROM files WHERE status='ok'"
            ).fetchone()[0]
            interrupted_status = connection.execute(
                "SELECT value FROM meta WHERE key='build_status'"
            ).fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(completed_before_resume, 2)
        self.assertEqual(interrupted_status, "interrupted")
        self.assertEqual(integrity, "ok")

        second_output = io.StringIO()
        with contextlib.redirect_stdout(second_output):
            second_code = build_index.main(arguments)
        self.assertEqual(second_code, 0)
        self.assertIn("Без изменений: 2", second_output.getvalue())
        with contextlib.closing(sqlite3.connect(db)) as connection:
            completed_after_resume = connection.execute(
                "SELECT COUNT(*) FROM files WHERE status='ok'"
            ).fetchone()[0]
            chunks = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE is_duplicate=0"
            ).fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(completed_after_resume, 6)
        self.assertEqual(chunks, 6)
        self.assertEqual(integrity, "ok")


if __name__ == "__main__":
    unittest.main()
