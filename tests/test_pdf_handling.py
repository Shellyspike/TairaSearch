from __future__ import annotations

import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
from parsers import (  # noqa: E402
    PdfDependencyError,
    PdfReadError,
    ensure_pdf_support,
    parse_pdf,
)


class PdfHandlingTests(unittest.TestCase):
    def test_text_pdf_is_extracted(self) -> None:
        parsed = parse_pdf(PROJECT / "sample_corpus" / "Статьи" / "текстовый.pdf")

        self.assertFalse(parsed.pdf_without_text)
        self.assertGreater(parsed.page_count or 0, 0)
        self.assertTrue(parsed.units)
        self.assertGreater(sum(len(unit.text) for unit in parsed.units), 20)

    def test_blank_pdf_is_reported_without_text(self) -> None:
        parsed = parse_pdf(
            PROJECT / "sample_corpus" / "Статьи" / "скан_без_текста.pdf"
        )

        self.assertTrue(parsed.pdf_without_text)
        self.assertEqual(parsed.units, [])
        self.assertGreater(parsed.page_count or 0, 0)

    def test_corrupt_pdf_has_a_specific_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taira-pdf-corrupt-") as temp:
            path = Path(temp) / "повреждённый.pdf"
            path.write_bytes(b"this is not a PDF")

            with self.assertRaises(PdfReadError) as raised:
                parse_pdf(path)

        self.assertEqual(raised.exception.error_code, "PDF_READ_ERROR")
        self.assertIn(path.name, str(raised.exception))

    def test_missing_pypdf_has_an_actionable_diagnostic(self) -> None:
        missing = ModuleNotFoundError("No module named 'pypdf'", name="pypdf")
        with mock.patch("parsers.import_module", side_effect=missing):
            with self.assertRaises(PdfDependencyError) as raised:
                ensure_pdf_support()

        self.assertEqual(raised.exception.error_code, "PDF_DEPENDENCY_ERROR")
        self.assertIn("requirements.txt", str(raised.exception))

    def test_missing_pypdf_preflight_does_not_touch_index_or_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taira-pdf-preflight-") as temp:
            root = Path(temp)
            corpus = root / "corpus"
            corpus.mkdir()
            (corpus / "document.pdf").write_bytes(b"%PDF-1.4\n")

            db = root / "existing.sqlite3"
            with contextlib.closing(sqlite3.connect(db)) as connection:
                connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
                connection.execute("INSERT INTO marker VALUES ('unchanged')")
                connection.commit()
            original_database = db.read_bytes()

            log = root / "index.log"
            drive_csv = root / "drive.csv"
            drive_jsonl = root / "drive.jsonl"
            stdout = io.StringIO()
            stderr = io.StringIO()
            error = PdfDependencyError("pypdf is unavailable")

            with mock.patch.object(
                build_index, "ensure_pdf_support", side_effect=error
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = build_index.main(
                    [
                        str(corpus),
                        "--db",
                        str(db),
                        "--log",
                        str(log),
                        "--drive-csv",
                        str(drive_csv),
                        "--drive-jsonl",
                        str(drive_jsonl),
                    ]
                )

            self.assertEqual(code, 1)
            self.assertIn("pypdf is unavailable", stderr.getvalue())
            self.assertEqual(db.read_bytes(), original_database)
            with contextlib.closing(sqlite3.connect(db)) as connection:
                marker = connection.execute("SELECT value FROM marker").fetchone()[0]
            self.assertEqual(marker, "unchanged")
            self.assertFalse(log.exists())
            self.assertFalse(drive_csv.exists())
            self.assertFalse(drive_jsonl.exists())


if __name__ == "__main__":
    unittest.main()
