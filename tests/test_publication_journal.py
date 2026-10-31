from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import daily_five  # noqa: E402
import taira_search  # noqa: E402


class PublicationJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        work_root = PROJECT / "work"
        work_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(
            prefix="taira-publication-test-", dir=work_root
        )
        self.root = Path(self.temp.name)
        self.used_path = self.root / "used_finds.csv"
        self.manifest_path = self.root / "ready-cards.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_existing_history(self, count: int = 70) -> list[dict[str, str]]:
        rows = [
            {
                "id": f"ch_existing_{index:014d}",
                "type": "event" if index < 28 else "interpretation",
                "persons": f"Персонаж {index}",
                "topics": "история; источник",
                "short_description": f"Существующая находка {index}, без изменений.",
                "source": f"Источник {index}",
                "date_used": "2026-10-01",
            }
            for index in range(count)
        ]
        with self.used_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=daily_five.USED_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return rows

    def write_manifest(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "publication_id": "2026-10-12-test-batch",
            "cards": [
                {
                    "id": "ch_selected_event_000001",
                    "type": "event",
                    "persons": ["平清盛"],
                    "topics": ["история", "болезнь"],
                    "short_description": "Выбранное событие из тестового источника.",
                    "source": "Тестовая хроника",
                    "card_markdown": "### Карточка события\n\nТочный готовый текст.",
                },
                {
                    "id": "ch_selected_study_000002",
                    "type": "interpretation",
                    "persons": ["平清盛"],
                    "topics": ["исследование"],
                    "short_description": "Выбранный вывод исследователя.",
                    "source": "Тестовая научная статья",
                    "card_markdown": "### Вывод исследователя\n\nТочный готовый текст.",
                },
            ],
        }
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    def write_single_card_manifest(self, path: Path, finding_id: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "publication_id": f"publication-{finding_id}",
                    "cards": [
                        {
                            "id": finding_id,
                            "type": "event",
                            "persons": ["平清盛"],
                            "topics": ["история"],
                            "short_description": f"Параллельная запись {finding_id}",
                            "source": "Тестовый источник",
                            "card_markdown": f"### Карточка {finding_id}",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def write_five_card_manifest(self) -> dict[str, object]:
        cards = [
            {
                "id": f"ch_delivery_{index}",
                "type": "event" if index % 2 else "interpretation",
                "persons": [f"Персонаж {index}"],
                "topics": ["история"],
                "short_description": f"Служебная аннотация {index}",
                "source": f"Источник {index}",
                "card_markdown": (
                    f"### {index}. Полная карточка {index}\n\n"
                    f"Исторические подробности карточки {index}.\n\n"
                    f"Источник: полный источник {index}."
                ),
            }
            for index in range(1, 6)
        ]
        payload: dict[str, object] = {
            "publication_id": "2026-10-18-delivery-regression",
            "cards": cards,
        }
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    def read_history(self) -> list[dict[str, str]]:
        with self.used_path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_preserves_70_rows_records_both_types_and_is_idempotent(self) -> None:
        original_rows = self.write_existing_history()
        payload = self.write_manifest()
        manifest_before = self.manifest_path.read_bytes()

        publication_id, added, skipped = daily_five.record_publication_from_json(
            self.manifest_path, self.used_path
        )

        self.assertEqual(publication_id, payload["publication_id"])
        self.assertEqual((added, skipped), (2, 0))
        rows = self.read_history()
        self.assertEqual(rows[:70], original_rows)
        self.assertEqual(len(rows), 72)
        self.assertEqual([row["type"] for row in rows[-2:]], ["event", "interpretation"])
        self.assertEqual(self.manifest_path.read_bytes(), manifest_before)
        history_after_first_write = self.used_path.read_bytes()

        publication_id, added, skipped = daily_five.record_publication_from_json(
            self.manifest_path, self.used_path
        )
        self.assertEqual(publication_id, payload["publication_id"])
        self.assertEqual((added, skipped), (0, 2))
        self.assertEqual(self.read_history(), rows)
        self.assertEqual(self.used_path.read_bytes(), history_after_first_write)

    def test_atomic_replace_failure_keeps_history_and_recovery_json(self) -> None:
        self.write_existing_history()
        payload = self.write_manifest()
        history_before = self.used_path.read_bytes()
        manifest_before = self.manifest_path.read_bytes()

        with mock.patch.object(
            daily_five.os, "replace", side_effect=OSError("simulated replace failure")
        ):
            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                daily_five.record_publication_from_json(
                    self.manifest_path, self.used_path
                )

        self.assertEqual(self.used_path.read_bytes(), history_before)
        self.assertEqual(self.manifest_path.read_bytes(), manifest_before)
        self.assertEqual(
            json.loads(self.manifest_path.read_text(encoding="utf-8")), payload
        )
        self.assertEqual(list(self.root.glob(".used_finds.csv.*.tmp")), [])

        publication_id, added, skipped = daily_five.record_publication_from_json(
            self.manifest_path, self.used_path
        )
        self.assertEqual(publication_id, payload["publication_id"])
        self.assertEqual((added, skipped), (2, 0))

    def test_two_processes_preserve_both_publications(self) -> None:
        original_rows = self.write_existing_history(70)
        manifests = [self.root / "publication-a.json", self.root / "publication-b.json"]
        finding_ids = ["ch_parallel_a", "ch_parallel_b"]
        ready_paths = [self.root / "ready-a", self.root / "ready-b"]
        start_path = self.root / "start"
        for manifest, finding_id in zip(manifests, finding_ids):
            self.write_single_card_manifest(manifest, finding_id)

        worker = r'''
import pathlib
import sys
import time

sys.path.insert(0, sys.argv[1])
import daily_five

manifest = pathlib.Path(sys.argv[2])
used = pathlib.Path(sys.argv[3])
ready = pathlib.Path(sys.argv[4])
start = pathlib.Path(sys.argv[5])
original_write = daily_five._atomic_write_used_rows

def delayed_write(rows, path):
    time.sleep(0.35)
    original_write(rows, path)

daily_five._atomic_write_used_rows = delayed_write
ready.write_text("ready", encoding="utf-8")
while not start.exists():
    time.sleep(0.01)
daily_five.record_publication_from_json(manifest, used)
'''
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    worker,
                    str(PROJECT),
                    str(manifest),
                    str(self.used_path),
                    str(ready),
                    str(start_path),
                ],
                cwd=PROJECT,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for manifest, ready in zip(manifests, ready_paths)
        ]
        deadline = time.monotonic() + 10
        while not all(path.exists() for path in ready_paths):
            if time.monotonic() >= deadline:
                self.fail("parallel publication workers did not become ready")
            time.sleep(0.02)
        start_path.write_text("start", encoding="utf-8")
        results = [process.communicate(timeout=15) for process in processes]
        for process, (stdout, stderr) in zip(processes, results):
            self.assertEqual(process.returncode, 0, stdout + stderr)

        rows = self.read_history()
        self.assertEqual(rows[:70], original_rows)
        self.assertEqual(len(rows), 72)
        self.assertEqual({row["id"] for row in rows[-2:]}, set(finding_ids))

    def test_invalid_card_does_not_change_history(self) -> None:
        self.write_existing_history()
        payload = self.write_manifest()
        cards = payload["cards"]
        assert isinstance(cards, list)
        assert isinstance(cards[1], dict)
        cards[1]["type"] = "variant"
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        history_before = self.used_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "event или interpretation"):
            daily_five.record_publication_from_json(
                self.manifest_path, self.used_path
            )

        self.assertEqual(self.used_path.read_bytes(), history_before)
        self.assertTrue(self.manifest_path.is_file())

    def test_cli_records_manifest_without_sqlite_database(self) -> None:
        self.write_existing_history(2)
        payload = self.write_manifest()

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "taira_search.py"),
                "record-publication",
                str(self.manifest_path),
                "--used-finds",
                str(self.used_path),
            ],
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(payload["publication_id"]), result.stdout)
        self.assertIn(str(self.manifest_path), result.stdout)
        self.assertIn("доставка карточек в чат", result.stdout)
        self.assertEqual(len(self.read_history()), 4)

    def test_five_registered_cards_render_in_full(self) -> None:
        payload = self.write_five_card_manifest()
        daily_five.record_publication_from_json(self.manifest_path, self.used_path)

        publication_id, markdown = (
            daily_five.render_registered_publication_from_json(
                self.manifest_path, self.used_path
            )
        )

        self.assertEqual(publication_id, payload["publication_id"])
        cards = payload["cards"]
        assert isinstance(cards, list)
        self.assertEqual(
            markdown,
            "\n\n".join(str(card["card_markdown"]) for card in cards),
        )
        for card in cards:
            self.assertIn(str(card["card_markdown"]), markdown)
            self.assertNotIn(str(card["short_description"]), markdown)
        self.assertNotIn("Журнал зарегистрирован", markdown)

    def test_registration_failure_prevents_publication_render(self) -> None:
        self.write_five_card_manifest()
        with mock.patch.object(
            daily_five.os, "replace", side_effect=OSError("simulated write failure")
        ):
            with self.assertRaisesRegex(OSError, "simulated write failure"):
                daily_five.record_publication_from_json(
                    self.manifest_path, self.used_path
                )

        with self.assertRaisesRegex(ValueError, "не полностью зарегистрирован"):
            daily_five.render_registered_publication_from_json(
                self.manifest_path, self.used_path
            )

    def test_registered_but_undelivered_state_keeps_recovery_output(self) -> None:
        payload = self.write_five_card_manifest()
        daily_five.record_publication_from_json(self.manifest_path, self.used_path)
        journal_before = self.used_path.read_bytes()

        status = daily_five.publication_status_from_json(
            self.manifest_path, self.used_path
        )
        first = daily_five.render_registered_publication_from_json(
            self.manifest_path, self.used_path
        )
        second = daily_five.render_registered_publication_from_json(
            self.manifest_path, self.used_path
        )

        self.assertTrue(status["prepared"])
        self.assertTrue(status["registered"])
        self.assertEqual(status["delivery"], "unconfirmed")
        self.assertEqual(first, second)
        cards = payload["cards"]
        assert isinstance(cards, list)
        self.assertEqual(first[1].count("### "), 5)
        self.assertEqual(self.used_path.read_bytes(), journal_before)

    def test_cli_recovers_exact_markdown_without_reregistering(self) -> None:
        payload = self.write_five_card_manifest()
        daily_five.record_publication_from_json(self.manifest_path, self.used_path)
        journal_before = self.used_path.read_bytes()
        cards = payload["cards"]
        assert isinstance(cards, list)
        expected = "\n\n".join(str(card["card_markdown"]) for card in cards)

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "taira_search.py"),
                "render-publication",
                str(self.manifest_path),
                "--used-finds",
                str(self.used_path),
            ],
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.rstrip("\n"), expected)
        self.assertEqual(self.used_path.read_bytes(), journal_before)

    def test_same_manifest_registration_remains_idempotent_after_recovery(self) -> None:
        self.write_five_card_manifest()
        first = daily_five.record_publication_from_json(
            self.manifest_path, self.used_path
        )
        daily_five.render_registered_publication_from_json(
            self.manifest_path, self.used_path
        )
        second = daily_five.record_publication_from_json(
            self.manifest_path, self.used_path
        )

        self.assertEqual(first[1:], (5, 0))
        self.assertEqual(second[1:], (0, 5))
        self.assertEqual(len(self.read_history()), 5)

    def test_same_chunk_with_different_finding_is_not_registered(self) -> None:
        payload = self.write_manifest()
        daily_five.record_publication_from_json(self.manifest_path, self.used_path)
        history_before = self.used_path.read_bytes()
        cards = payload["cards"]
        assert isinstance(cards, list)
        assert isinstance(cards[0], dict)
        conflicting_id = str(cards[0]["id"])
        cards[0]["short_description"] = "Другой сюжет из того же фрагмента."
        cards[0]["card_markdown"] = "### Совершенно другая карточка"
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        status = daily_five.publication_status_from_json(
            self.manifest_path, self.used_path
        )

        self.assertFalse(status["registered"])
        self.assertEqual(status["conflicting_registration_ids"], [conflicting_id])
        with self.assertRaisesRegex(ValueError, "другим содержанием"):
            daily_five.render_registered_publication_from_json(
                self.manifest_path, self.used_path
            )
        with self.assertRaisesRegex(ValueError, "другим содержанием"):
            daily_five.record_publication_from_json(
                self.manifest_path, self.used_path
            )
        self.assertEqual(self.used_path.read_bytes(), history_before)

    def test_publication_access_check_does_not_touch_journal_or_lock(self) -> None:
        self.write_existing_history(2)
        database = self.root / "index.sqlite3"
        import sqlite3

        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE probe(value INTEGER)")
            connection.commit()
        finally:
            connection.close()
        journal_before = self.used_path.read_bytes()
        lock_path = self.root / ".used_finds.csv.lock"
        lock_path.write_bytes(b"existing-lock-sentinel")
        lock_before = lock_path.read_bytes()

        with mock.patch.object(
            taira_search,
            "_open_existing_lock_read_write",
            wraps=taira_search._open_existing_lock_read_write,
        ) as open_lock:
            report = taira_search.check_publication_access(database, self.used_path)

        self.assertEqual(report["status"], "ok")
        open_lock.assert_called_once_with(lock_path)
        self.assertIn("opened read-write", report["lock_write_check"])
        self.assertTrue(report["journal_and_lock_unchanged"])
        self.assertEqual(self.used_path.read_bytes(), journal_before)
        self.assertEqual(lock_path.read_bytes(), lock_before)
        self.assertEqual(list(self.root.glob(".taira-*-check.*.tmp")), [])

    def test_publication_access_check_does_not_create_missing_lock(self) -> None:
        self.write_existing_history(1)
        database = self.root / "index.sqlite3"
        import sqlite3

        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE probe(value INTEGER)")
            connection.commit()
        finally:
            connection.close()
        lock_path = self.root / ".used_finds.csv.lock"

        report = taira_search.check_publication_access(database, self.used_path)

        self.assertFalse(lock_path.exists())
        self.assertIn("absent", report["lock_write_check"])

    def test_publication_access_check_rejects_unwritable_existing_lock(self) -> None:
        self.write_existing_history(1)
        database = self.root / "index.sqlite3"
        import sqlite3

        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE probe(value INTEGER)")
            connection.commit()
        finally:
            connection.close()
        lock_path = self.root / ".used_finds.csv.lock"
        lock_path.write_bytes(b"must-stay-unchanged")

        with mock.patch.object(
            taira_search,
            "_open_existing_lock_read_write",
            side_effect=PermissionError("simulated lock denial"),
        ):
            with self.assertRaisesRegex(RuntimeError, "lock-файл"):
                taira_search.check_publication_access(database, self.used_path)

        self.assertEqual(lock_path.read_bytes(), b"must-stay-unchanged")

    def test_publication_access_check_reports_effective_writable_roots(self) -> None:
        database = self.root / "index.sqlite3"
        import sqlite3

        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE probe(value INTEGER)")
            connection.commit()
        finally:
            connection.close()
        with mock.patch.object(
            taira_search.tempfile,
            "mkstemp",
            side_effect=PermissionError("simulated sandbox denial"),
        ):
            with self.assertRaisesRegex(RuntimeError, "writable roots"):
                taira_search.check_publication_access(database, self.used_path)
        self.assertFalse(self.used_path.exists())
        self.assertFalse((self.root / ".used_finds.csv.lock").exists())


if __name__ == "__main__":
    unittest.main()

