from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402


class BuildStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="taira-status-")
        self.root = Path(self.temp.name)
        self.corpus = self.root / "corpus"
        self.corpus.mkdir()
        self.db = self.root / "index.sqlite3"
        self.log = self.root / "index.log"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def arguments(self, corpus: Path | None = None) -> list[str]:
        return [
            str(corpus or self.corpus),
            "--db",
            str(self.db),
            "--log",
            str(self.log),
            "--drive-csv",
            str(self.root / "drive.csv"),
            "--drive-jsonl",
            str(self.root / "drive.jsonl"),
        ]

    def run_build(self, corpus: Path | None = None) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = build_index.main(self.arguments(corpus))
        return code, stdout.getvalue(), stderr.getvalue()

    def metadata(self) -> dict[str, str]:
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            return dict(connection.execute("SELECT key, value FROM meta"))

    def test_success_without_license_metadata_has_zero_exit_code(self) -> None:
        (self.corpus / "document.txt").write_text(
            "Локальный документ без лицензионных metadata 清盛", encoding="utf-8"
        )
        (self.corpus / "unsupported.bin").write_bytes(b"ignored")

        code, stdout, stderr = self.run_build()
        meta = self.metadata()

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(meta["build_status"], "succeeded")
        self.assertEqual(meta["successful_files"], "1")
        self.assertEqual(meta["skipped_files"], "1")
        self.assertEqual(meta["problematic_files"], "0")
        self.assertIn("Статус сборки: succeeded", stdout)
        self.assertIn("Успешно обработано: 1", stdout)
        self.assertIn("Пропущено в этом запуске: 1", stdout)

    def test_file_error_is_completed_with_errors_and_nonzero(self) -> None:
        (self.corpus / "good.txt").write_text("Корректный документ 平維盛", encoding="utf-8")
        (self.corpus / "broken.json").write_text("{ broken", encoding="utf-8")

        code, stdout, stderr = self.run_build()
        meta = self.metadata()

        self.assertEqual(code, 1)
        self.assertEqual(meta["build_status"], "completed_with_errors")
        self.assertEqual(meta["successful_files"], "1")
        self.assertEqual(meta["problematic_files"], "1")
        self.assertEqual(meta["previous_versions_kept"], "0")
        self.assertIn("Статус сборки: completed_with_errors", stdout)
        self.assertIn("Проблемных файлов/путей: 1", stdout)
        self.assertIn("[FILE_ERROR] broken.json:", stdout)
        self.assertIn("завершена с ошибками отдельных файлов", stderr)

    def test_report_marks_preserved_previous_version(self) -> None:
        document = self.corpus / "document.json"
        document.write_text(
            json.dumps({"text": "Последняя корректная версия 清盛"}, ensure_ascii=False),
            encoding="utf-8",
        )
        first_code, _stdout, _stderr = self.run_build()
        self.assertEqual(first_code, 0)

        document.write_text("{ broken replacement", encoding="utf-8")
        code, stdout, _stderr = self.run_build()
        meta = self.metadata()

        self.assertEqual(code, 1)
        self.assertEqual(meta["build_status"], "completed_with_errors")
        self.assertEqual(meta["previous_versions_kept"], "1")
        self.assertIn("Сохранена предыдущая корректная версия: 1", stdout)
        self.assertIn("сохранена предыдущая корректная версия", stdout)

    def test_critical_error_is_failed_and_nonzero(self) -> None:
        missing = self.root / "missing-corpus"

        code, stdout, stderr = self.run_build(missing)

        self.assertEqual(code, 1)
        self.assertIn("Этап 1/3", stdout)
        self.assertIn("Статус сборки: failed", stderr)
        self.assertIn("папка корпуса недоступна", stderr)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
