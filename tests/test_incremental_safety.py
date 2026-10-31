from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
from parsers import ParsedDocument, TextUnit  # noqa: E402


class IncrementalSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="taira-incremental-")
        self.root = Path(self.temp.name)
        self.corpus = self.root / "corpus"
        self.corpus.mkdir()
        self.db = self.root / "index.sqlite3"
        self.log = self.root / "index.log"
        self.drive_csv = self.root / "drive.csv"
        self.drive_jsonl = self.root / "drive.jsonl"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def arguments(self, *extra: str) -> list[str]:
        return [
            str(self.corpus),
            "--db",
            str(self.db),
            "--log",
            str(self.log),
            "--drive-csv",
            str(self.drive_csv),
            "--drive-jsonl",
            str(self.drive_jsonl),
            *extra,
        ]

    def build(self, *extra: str) -> tuple[dict[str, object], str]:
        args = build_index.make_parser().parse_args(self.arguments(*extra))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            stats = build_index.build_index(args)
        return stats, stdout.getvalue()

    def document_snapshot(self, relative_path: str) -> tuple[object, ...]:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            file_row = connection.execute(
                """
                SELECT relative_path, filename, extension, size, mtime_ns,
                       status, error, indexed_at
                FROM files WHERE relative_path=?
                """,
                (relative_path,),
            ).fetchone()
            chunks = connection.execute(
                """
                SELECT chunk_id, source, filename, relative_path, page_start,
                       page_end, chunk_no, original_text, normalized_text,
                       preview, aliases_json, topics_json, search_terms_json,
                       text_hash, is_duplicate, source_type, people_json,
                       text_quality
                FROM chunks WHERE relative_path=? ORDER BY chunk_no
                """,
                (relative_path,),
            ).fetchall()
            chunk_ids = [row[0] for row in chunks]
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                fts_rows = connection.execute(
                    f"""
                    SELECT chunk_id, search_text, preview, aliases, topics
                    FROM chunks_fts WHERE chunk_id IN ({placeholders})
                    ORDER BY chunk_id
                    """,
                    chunk_ids,
                ).fetchall()
            else:
                fts_rows = []
        return file_row, chunks, fts_rows

    def test_parse_error_keeps_last_good_chunks_and_fts(self) -> None:
        document = self.corpus / "document.json"
        document.write_text(
            json.dumps({"text": "Старая корректная версия 清盛"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.build()
        before = self.document_snapshot("document.json")

        document.write_text("{ повреждённый JSON", encoding="utf-8")
        stats, _ = self.build()

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(self.document_snapshot("document.json"), before)
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("[FILE_ERROR]", log)
        self.assertIn("[LAST_GOOD_KEPT]", log)

    def test_successful_update_replaces_chunks_and_fts_together(self) -> None:
        document = self.corpus / "document.txt"
        document.write_text("Старая версия с маркером OLD-MARKER", encoding="utf-8")
        self.build()
        before = self.document_snapshot("document.txt")

        document.write_text(
            "Новая проверенная версия с маркером NEW-MARKER и 清盛",
            encoding="utf-8",
        )
        stats, _ = self.build()
        after = self.document_snapshot("document.txt")

        self.assertEqual(stats["errors"], 0)
        self.assertNotEqual(after, before)
        self.assertIn("NEW-MARKER", after[1][0][7])
        self.assertNotIn("OLD-MARKER", after[1][0][7])
        self.assertNotEqual(after[2], before[2])

    def test_indexer_reads_russian_japanese_and_unicode_encodings(self) -> None:
        fixtures = {
            "russian.txt": ("Привет мир из Windows", "cp1251"),
            "japanese.txt": ("こんにちは世界の史料", "cp932"),
            "unicode.txt": ("Unicode source 清盛", "utf-8-sig"),
            "utf16.txt": ("UTF-16 source Привет", "utf-16"),
        }
        for filename, (text, encoding) in fixtures.items():
            (self.corpus / filename).write_bytes(text.encode(encoding))

        stats, _ = self.build()

        self.assertEqual(stats["errors"], 0)
        for filename, (expected, _encoding) in fixtures.items():
            chunks = self.document_snapshot(filename)[1]
            self.assertTrue(chunks, filename)
            self.assertIn(expected, chunks[0][7])

    def test_explicit_text_encoding_handles_bomless_utf16(self) -> None:
        document = self.corpus / "explicit.txt"
        document.write_bytes("Явная кодировка UTF-16".encode("utf-16-le"))

        stats, _ = self.build("--text-encoding", "utf-16-le")

        self.assertEqual(stats["errors"], 0)
        self.assertIn(
            "Явная кодировка UTF-16",
            self.document_snapshot("explicit.txt")[1][0][7],
        )

    def test_corrupt_control_characters_do_not_enter_index(self) -> None:
        document = self.corpus / "corrupt.txt"
        document.write_bytes(b"valid\x00text")

        stats, _ = self.build()

        self.assertEqual(stats["errors"], 1)
        file_row, chunks, fts_rows = self.document_snapshot("corrupt.txt")
        self.assertEqual(file_row[5], "error")
        self.assertIn("U+0000", file_row[6])
        self.assertEqual(chunks, [])
        self.assertEqual(fts_rows, [])
        self.assertIn("U+0000", self.log.read_text(encoding="utf-8"))

    def test_database_write_error_rolls_back_chunks_and_fts(self) -> None:
        document = self.corpus / "document.txt"
        document.write_text("Старая корректная версия 平維盛", encoding="utf-8")
        self.build()
        before = self.document_snapshot("document.txt")

        document.write_text(
            "NEW-VERSION должна быть полностью отменена при ошибке записи",
            encoding="utf-8",
        )

        def fail_after_partial_write(
            connection: sqlite3.Connection, chunk_id: str, *_values: str
        ) -> None:
            connection.execute(
                "DELETE FROM chunks_fts WHERE chunk_id=?", (chunk_id,)
            )
            raise sqlite3.OperationalError("injected write failure")

        with mock.patch.object(
            build_index, "upsert_fts_chunk", side_effect=fail_after_partial_write
        ):
            stats, _ = self.build()

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(self.document_snapshot("document.txt"), before)
        self.assertIn("injected write failure", self.log.read_text(encoding="utf-8"))

    def test_partial_pdf_cannot_replace_complete_version(self) -> None:
        document = self.corpus / "document.pdf"
        document.write_bytes(b"initial PDF fixture")
        complete = ParsedDocument(
            [TextUnit("Полная корректная версия PDF 清盛" * 2, 1, 2)],
            page_count=2,
        )
        with mock.patch.object(
            build_index, "ensure_pdf_support", return_value="test"
        ), mock.patch.object(build_index, "parse_file", return_value=complete):
            self.build()
        before = self.document_snapshot("document.pdf")

        document.write_bytes(b"changed PDF fixture with a broken second page")
        partial = ParsedDocument(
            [TextUnit("Только первая страница — неполная версия", 1, 1)],
            warnings=("Страница 2: injected extraction failure",),
            page_count=2,
        )
        with mock.patch.object(
            build_index, "ensure_pdf_support", return_value="test"
        ), mock.patch.object(build_index, "parse_file", return_value=partial):
            stats, _ = self.build()

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(self.document_snapshot("document.pdf"), before)
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("[PDF_PAGE_ERROR]", log)
        self.assertIn("[PDF_PARTIAL_READ]", log)
        self.assertIn("[LAST_GOOD_KEPT]", log)

    def test_missing_subtree_is_kept_even_during_rebuild(self) -> None:
        mounted = self.corpus / "mounted-library"
        mounted.mkdir()
        (mounted / "document.txt").write_text(
            "Документ на временно доступном диске 清盛", encoding="utf-8"
        )
        self.build()
        before = self.document_snapshot("mounted-library/document.txt")

        def inaccessible_subtree(root: Path, log_error):
            log_error(
                "WALK_ERROR", root / "mounted-library", "injected access failure"
            )
            return []

        with mock.patch.object(
            build_index, "discover_files", side_effect=inaccessible_subtree
        ):
            stats, stdout = self.build("--rebuild")

        self.assertEqual(stats["build_status"], "completed_with_errors")
        self.assertEqual(stats["problematic_files"], 1)
        self.assertEqual(stats["problems"][0]["kind"], "WALK_ERROR")
        self.assertEqual(stats["missing_kept"], 1)
        self.assertEqual(
            self.document_snapshot("mounted-library/document.txt"), before
        )
        self.assertIn("Автоматическое удаление отключено", stdout)
        self.assertIn("[MISSING_FILES_KEPT]", self.log.read_text(encoding="utf-8"))

    def test_unavailable_corpus_does_not_open_existing_index(self) -> None:
        (self.corpus / "document.txt").write_text(
            "Корректная версия перед отключением корпуса", encoding="utf-8"
        )
        self.build()
        database_before = self.db.read_bytes()
        snapshot_before = self.document_snapshot("document.txt")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            Path, "is_dir", return_value=False
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = build_index.main(self.arguments())

        self.assertEqual(code, 1)
        self.assertIn("папка корпуса недоступна", stderr.getvalue())
        self.assertEqual(self.db.read_bytes(), database_before)
        self.assertEqual(self.document_snapshot("document.txt"), snapshot_before)

    def test_colliding_log_path_is_rejected_before_database_change(self) -> None:
        (self.corpus / "document.txt").write_text(
            "Корректная версия перед проверкой путей", encoding="utf-8"
        )
        self.build()
        database_before = self.db.read_bytes()
        arguments = self.arguments()
        arguments[arguments.index("--log") + 1] = str(self.db)
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            code = build_index.main(arguments)

        self.assertEqual(code, 1)
        self.assertIn("совпадение входных и выходных путей", stderr.getvalue())
        self.assertEqual(self.db.read_bytes(), database_before)
        self.assertEqual(self.document_snapshot("document.txt")[0][5], "ok")

    def test_empty_same_stem_txt_does_not_suppress_json(self) -> None:
        (self.corpus / "document.txt").write_text("", encoding="utf-8")
        (self.corpus / "document.json").write_text(
            json.dumps({"text": "Полезное содержимое JSON 清盛"}, ensure_ascii=False),
            encoding="utf-8",
        )

        self.build()

        file_row, chunks, _fts_rows = self.document_snapshot("document.json")
        self.assertEqual(file_row[5], "ok")
        self.assertGreaterEqual(len(chunks), 1)
        self.assertIn("Полезное содержимое JSON", chunks[0][7])

    def test_existing_index_rejects_different_corpus_before_database_change(self) -> None:
        (self.corpus / "document.txt").write_text(
            "Library A marker 清盛", encoding="utf-8"
        )
        self.build()
        database_before = self.db.read_bytes()
        metadata_before = None
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            metadata_before = connection.execute(
                "SELECT key, value FROM meta ORDER BY key"
            ).fetchall()

        other = self.root / "corpus-b"
        other.mkdir()
        (other / "document.txt").write_text("Library B marker", encoding="utf-8")
        arguments = self.arguments()
        arguments[0] = str(other)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = build_index.main(arguments)

        self.assertEqual(code, 1)
        self.assertIn("Индекс уже привязан к другой библиотеке", stderr.getvalue())
        self.assertEqual(self.db.read_bytes(), database_before)
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(
                connection.execute("SELECT key, value FROM meta ORDER BY key").fetchall(),
                metadata_before,
            )
            text = connection.execute(
                "SELECT original_text FROM chunks WHERE relative_path='document.txt'"
            ).fetchone()[0]
        self.assertIn("Library A marker", text)
        self.assertNotIn("Library B marker", text)

    def test_legacy_index_without_corpus_root_is_rejected_when_nonempty(self) -> None:
        (self.corpus / "document.txt").write_text("Legacy index", encoding="utf-8")
        self.build()
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            connection.execute("DELETE FROM meta WHERE key='corpus_root'")
            connection.commit()
        database_before = self.db.read_bytes()

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = build_index.main(self.arguments())

        self.assertEqual(code, 1)
        self.assertIn("не содержит metadata corpus_root", stderr.getvalue())
        self.assertEqual(self.db.read_bytes(), database_before)

    def test_empty_legacy_database_can_be_bound_to_first_corpus(self) -> None:
        connection = sqlite3.connect(self.db)
        build_index.create_schema(connection)
        connection.execute("DELETE FROM meta WHERE key='corpus_root'")
        connection.commit()
        connection.close()
        (self.corpus / "document.txt").write_text("First safe binding", encoding="utf-8")

        stats, _ = self.build()

        self.assertEqual(stats["build_status"], "succeeded")
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            root = connection.execute(
                "SELECT value FROM meta WHERE key='corpus_root'"
            ).fetchone()[0]
        self.assertEqual(
            build_index.normalized_corpus_root(root),
            build_index.normalized_corpus_root(self.corpus),
        )


if __name__ == "__main__":
    unittest.main()
