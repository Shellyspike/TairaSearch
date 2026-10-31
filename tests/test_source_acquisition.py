from __future__ import annotations

import functools
import http.server
import io
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(PROJECT))

import source_acquisition  # noqa: E402
import build_index  # noqa: E402
from parsers import TextDecodingError, decode_text_bytes  # noqa: E402


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


class SourceAcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = PROJECT / "work" / "tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(
            prefix="taira-acquisition-test-", dir=test_root
        )
        self.root = Path(self.temp.name)
        self.web = self.root / "web"
        self.web.mkdir()
        self.staging = self.root / "staging"
        self.journal = self.root / "downloads.json"
        self.profile = PROJECT / "examples" / "profiles" / "ancient-rome.json"

        (self.web / "source.txt").write_text(
            "A public historical source. " * 30, encoding="utf-8"
        )
        (self.web / "source.md").write_text(
            "# Public edition\n\nA machine-readable passage. " * 20,
            encoding="utf-8",
        )
        (self.web / "source.html").write_text(
            "<html><head><style>hidden</style></head><body><nav>menu</nav>"
            "<main><h1>Open article</h1><p>Historical evidence and analysis. "
            + ("A complete paragraph. " * 30)
            + "</p></main><script>secret()</script></body></html>",
            encoding="utf-8",
        )
        (self.web / "source.xml").write_text(
            "<TEI><text><body><p>" + ("TEI historical passage. " * 30) + "</p></body></text></TEI>",
            encoding="utf-8",
        )
        with zipfile.ZipFile(self.web / "source.epub", "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr(
                "OEBPS/chapter.xhtml",
                "<html><body><h1>Open book</h1><p>"
                + ("EPUB historical passage. " * 30)
                + "</p></body></html>",
            )
        shutil.copy2(
            PROJECT / "sample_corpus" / "Статьи" / "текстовый.pdf",
            self.web / "source.pdf",
        )

        handler = functools.partial(QuietHandler, directory=str(self.web))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def manifest(self, *formats: str, title_prefix: str = "Open source") -> Path:
        sources = []
        for number, source_format in enumerate(formats, start=1):
            extension = "xml" if source_format == "tei" else source_format
            sources.append(
                {
                    "id": f"source-{source_format}-{number}",
                    "title": f"{title_prefix} {source_format} {number}",
                    "author": "Public Repository",
                    "url": f"{self.base_url}/source.{extension}",
                    "format": source_format,
                    "filename": f"source.{extension}",
                    "access": "open",
                    "reuse_terms": "Public test fixture",
                    "interest_id": "daily-life",
                    "why_useful": "Exercises the acquisition workflow.",
                }
            )
        path = self.root / f"manifest-{len(list(self.root.glob('manifest-*.json')))}.json"
        path.write_text(
            json.dumps({"version": 1, "sources": sources}, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def run_cli(self, *arguments: str) -> int:
        return source_acquisition.main(
            list(arguments), allow_private_network_for_tests=True
        )

    def run_public_cli(self, *arguments: str) -> int:
        return source_acquisition.main(list(arguments))

    def test_stale_journal_lock_file_does_not_block_new_process(self) -> None:
        lock_path = self.journal.with_name(self.journal.name + ".lock")
        lock_path.write_text("12345\n", encoding="ascii")

        with source_acquisition.journal_lock(self.journal, timeout=0):
            self.assertTrue(lock_path.exists())

    def test_public_downloader_blocks_local_internal_and_service_targets(self) -> None:
        blocked = (
            "http://127.0.0.1/source.txt",
            "http://[::1]/source.txt",
            "http://localhost/source.txt",
            "http://10.0.0.1/source.txt",
            "http://169.254.169.254/latest/meta-data",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://service.internal/source.txt",
        )
        for url in blocked:
            with self.subTest(url=url), self.assertRaises(
                source_acquisition.AcquisitionError
            ):
                source_acquisition.validate_public_download_target(url)

    def test_public_downloader_rejects_dns_answer_containing_private_address(
        self,
    ) -> None:
        answers = [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.7", 443)),
        ]
        with mock.patch.object(
            source_acquisition.socket, "getaddrinfo", return_value=answers
        ):
            with self.assertRaises(source_acquisition.AcquisitionError):
                source_acquisition.validate_public_download_target(
                    "https://public.example/source.pdf"
                )

    def test_redirect_to_local_target_is_rejected_before_following(self) -> None:
        handler = source_acquisition.SafeRedirectHandler()
        request = urllib.request.Request("https://example.org/start")
        with self.assertRaises(source_acquisition.AcquisitionError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1/private",
            )

    def test_cli_has_no_private_network_bypass(self) -> None:
        manifest = self.manifest("txt")
        code = self.run_public_cli(
            "stage",
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--staging",
            str(self.staging),
            "--report",
            str(self.root / "blocked-local.json"),
            "--approve-downloads",
        )
        self.assertEqual(code, 1)
        payload = json.loads(
            (self.root / "blocked-local.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["summary"]["error"], 1)
        self.assertIn("запрещена", payload["items"][0]["reason"])
        self.assertFalse(self.journal.exists())

    def test_stage_requires_explicit_consent_and_downloads_nothing_on_refusal(self) -> None:
        manifest = self.manifest("txt")
        code = self.run_cli(
            "stage",
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--staging",
            str(self.staging),
            "--report",
            str(self.root / "refused-report.json"),
        )
        self.assertEqual(code, 1)
        self.assertFalse(self.staging.exists())
        self.assertFalse(self.journal.exists())

    def test_supported_formats_preserve_originals_and_extract_text(self) -> None:
        manifest = self.manifest("pdf", "html", "txt", "md", "xml", "epub")
        report = self.root / "stage-report.json"
        policy = self.root / "fixture-policy.json"
        policy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "automatic_downloads": False,
                    "max_files_per_run": 10,
                    "max_file_bytes": 1_000_000,
                    "max_total_bytes": 5_000_000,
                    "min_text_chars": 50,
                }
            ),
            encoding="utf-8",
        )
        code = self.run_cli(
            "stage",
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--staging",
            str(self.staging),
            "--report",
            str(report),
            "--policy",
            str(policy),
            "--approve-downloads",
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["summary"]["staged"], 6)
        for item in payload["items"]:
            self.assertEqual(item["status"], "staged")
            original = Path(item["original_file"])
            extracted = Path(item["extracted_file"])
            metadata = json.loads(Path(item["metadata_file"]).read_text(encoding="utf-8"))
            self.assertEqual(source_acquisition.sha256_bytes(original.read_bytes()), metadata["content_sha256"])
            self.assertGreater(metadata["quality"]["nonspace_chars"], 50)
            self.assertGreater(len(extracted.read_text(encoding="utf-8")), 50)
        html_item = next(item for item in payload["items"] if "html" in item["source_id"])
        html_text = Path(html_item["extracted_file"]).read_text(encoding="utf-8")
        self.assertIn("Historical evidence", html_text)
        self.assertNotIn("secret()", html_text)
        pdf_item = next(item for item in payload["items"] if "pdf" in item["source_id"])
        pdf_quality = pdf_item["quality"]
        self.assertEqual(set(pdf_quality["pdf_samples"]), {"beginning", "middle", "end"})

    def test_repeated_source_is_rejected_without_second_download(self) -> None:
        manifest = self.manifest("txt")
        first = self.root / "first.json"
        second = self.root / "second.json"
        common = (
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--staging",
            str(self.staging),
            "--approve-downloads",
        )
        self.assertEqual(self.run_cli("stage", *common, "--report", str(first)), 0)
        original = next(self.staging.glob("*/original-*"))
        before = original.read_bytes()
        self.assertEqual(self.run_cli("stage", *common, "--report", str(second)), 0)
        payload = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["duplicate"], 1)
        self.assertEqual(original.read_bytes(), before)
        journal = json.loads(self.journal.read_text(encoding="utf-8"))
        self.assertEqual(len(journal["entries"]), 1)

    def test_check_treats_existing_index_filename_as_potential_only(self) -> None:
        db = self.root / "existing.sqlite3"
        connection = sqlite3.connect(db)
        connection.execute(
            "CREATE TABLE files(relative_path TEXT PRIMARY KEY, filename TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO files(relative_path, filename) VALUES(?, ?)",
            ("existing/source.txt", "source.txt"),
        )
        connection.commit()
        connection.close()
        before = db.read_bytes()
        manifest = self.manifest("txt")
        report = self.root / "check.json"
        code = self.run_cli(
            "check",
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--db",
            str(db),
            "--report",
            str(report),
        )
        self.assertEqual(code, 0)
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["duplicates"], 0)
        self.assertEqual(payload["items"][0]["status"], "eligible")
        self.assertEqual(payload["items"][0]["duplicate_confidence"], "potential")
        self.assertIn("имя файла", payload["items"][0]["review_reason"])
        self.assertEqual(db.read_bytes(), before)

    def test_decoding_uses_bom_signatures_and_legacy_script_evidence(self) -> None:
        russian = "Привет мир"
        japanese = "こんにちは世界"
        self.assertEqual(decode_text_bytes(russian.encode("cp1251")), russian)
        self.assertEqual(decode_text_bytes(japanese.encode("cp932")), japanese)
        self.assertEqual(decode_text_bytes(japanese.encode("shift_jis")), japanese)
        self.assertEqual(decode_text_bytes(russian.encode("utf-8-sig")), russian)
        self.assertEqual(decode_text_bytes(russian.encode("utf-16")), russian)
        self.assertEqual(
            decode_text_bytes(b"\xfe\xff" + russian.encode("utf-16-be")), russian
        )
        self.assertEqual(
            decode_text_bytes(russian.encode("utf-16-le"), encoding="utf-16-le"),
            russian,
        )
        with self.assertRaisesRegex(TextDecodingError, "Укажите encoding явно"):
            decode_text_bytes(b"\x80")

    def test_bomless_utf16_is_detected_before_utf8(self) -> None:
        samples = (
            "ASCII historical source 12345",
            "Русский исторический источник",
        )
        for text in samples:
            for encoding in ("utf-16-le", "utf-16-be"):
                with self.subTest(text=text, encoding=encoding):
                    self.assertEqual(decode_text_bytes(text.encode(encoding)), text)

    def test_utf8_and_cp1251_are_not_misclassified_as_utf16(self) -> None:
        samples = (
            ("Ordinary UTF-8 source text", "utf-8"),
            ("Обычный русский текст UTF-8", "utf-8"),
            ("Обычный русский текст CP1251", "cp1251"),
        )
        for text, encoding in samples:
            with self.subTest(encoding=encoding, text=text):
                self.assertEqual(decode_text_bytes(text.encode(encoding)), text)

    def test_utf8_with_embedded_nul_is_rejected(self) -> None:
        with self.assertRaisesRegex(TextDecodingError, r"U\+0000"):
            decode_text_bytes(b"valid\x00text")

    def test_html_uses_declared_windows_1251_encoding(self) -> None:
        html = (
            '<html><head><meta charset="windows-1251"></head>'
            "<body><p>Привет мир</p></body></html>"
        ).encode("cp1251")
        self.assertIn("Привет мир", source_acquisition.extract_html(html))

    def test_download_budget_counts_failed_streams_and_stops_at_limit(self) -> None:
        class Response:
            def __init__(self, data: bytes, *, fail_after_first: bool = False) -> None:
                self.stream = io.BytesIO(data)
                self.headers = {"Content-Type": "text/plain"}
                self.fail_after_first = fail_after_first
                self.reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self) -> str:
                return "https://example.test/source.txt"

            def read(self, size: int) -> bytes:
                self.reads += 1
                if self.fail_after_first and self.reads > 1:
                    raise OSError("injected stream failure")
                return self.stream.read(min(size, 3))

        class Opener:
            def __init__(self, response: Response) -> None:
                self.response = response

            def open(self, *_args, **_kwargs):
                return self.response

        budget = source_acquisition.DownloadBudget(5)
        failed = Response(b"abcdef", fail_after_first=True)
        with mock.patch.object(
            source_acquisition, "validate_public_download_target", side_effect=lambda value, **_: value
        ), mock.patch.object(
            source_acquisition.urllib.request, "build_opener", return_value=Opener(failed)
        ):
            with self.assertRaisesRegex(source_acquisition.AcquisitionError, "ошибка загрузки"):
                source_acquisition.download_bytes(
                    "https://example.test/source.txt", 10, budget=budget
                )
        self.assertEqual(budget.consumed, 3)

        final = Response(b"xy")
        final.headers["Content-Length"] = "2"
        with mock.patch.object(
            source_acquisition, "validate_public_download_target", side_effect=lambda value, **_: value
        ), mock.patch.object(
            source_acquisition.urllib.request, "build_opener", return_value=Opener(final)
        ):
            data, _, _ = source_acquisition.download_bytes(
                "https://example.test/final.txt", 10, budget=budget
            )
        self.assertEqual(data, b"xy")
        self.assertEqual(budget.consumed, 5)

        with mock.patch.object(
            source_acquisition.urllib.request, "build_opener"
        ) as unopened:
            with self.assertRaisesRegex(source_acquisition.AcquisitionError, "уже исчерпан"):
                source_acquisition.download_bytes(
                    "https://example.test/not-requested.txt", 10, budget=budget
                )
            unopened.assert_not_called()

    def test_download_larger_than_remaining_budget_is_rejected_before_read(self) -> None:
        class Response:
            headers = {"Content-Type": "text/plain", "Content-Length": "4"}
            reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self) -> str:
                return "https://example.test/large.txt"

            def read(self, _size: int) -> bytes:
                self.reads += 1
                return b"data"

        response = Response()
        opener = mock.Mock()
        opener.open.return_value = response
        budget = source_acquisition.DownloadBudget(3)
        with mock.patch.object(
            source_acquisition, "validate_public_download_target", side_effect=lambda value, **_: value
        ), mock.patch.object(
            source_acquisition.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaisesRegex(
                source_acquisition.AcquisitionError, "оставшегося суммарного бюджета"
            ):
                source_acquisition.download_bytes(
                    "https://example.test/large.txt", 10, budget=budget
                )
        self.assertEqual(response.reads, 0)
        self.assertEqual(budget.consumed, 0)

    def test_unknown_length_stream_cannot_read_past_total_budget(self) -> None:
        class Response:
            headers = {"Content-Type": "text/plain"}

            def __init__(self) -> None:
                self.stream = io.BytesIO(b"abcdef")
                self.requested: list[int] = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self) -> str:
                return "https://example.test/chunked.txt"

            def read(self, size: int) -> bytes:
                self.requested.append(size)
                return self.stream.read(size)

        response = Response()
        opener = mock.Mock()
        opener.open.return_value = response
        budget = source_acquisition.DownloadBudget(5)
        with mock.patch.object(
            source_acquisition, "validate_public_download_target", side_effect=lambda value, **_: value
        ), mock.patch.object(
            source_acquisition.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaisesRegex(
                source_acquisition.AcquisitionError, "конец потока не подтверждён"
            ):
                source_acquisition.download_bytes(
                    "https://example.test/chunked.txt", 10, budget=budget
                )
        self.assertEqual(budget.consumed, 5)
        self.assertEqual(response.requested, [5])

    def test_stage_stops_after_failed_download_consumes_total_budget(self) -> None:
        candidates = []
        for number in (1, 2):
            candidates.append(
                {
                    "id": f"budget-{number}",
                    "title": f"Budget source {number}",
                    "author": "Budget Author",
                    "year": "",
                    "url": f"https://example.test/{number}.txt",
                    "doi": "",
                    "format": "txt",
                    "filename": f"{number}.txt",
                    "title_variants": [],
                    "language": "en",
                    "encoding": "",
                    "repository": "Test",
                    "access": "open",
                    "reuse_terms": "Test",
                    "interest_id": "daily-life",
                    "why_useful": "Budget regression",
                }
            )
        calls: list[str] = []

        def fail_after_receiving(url, _maximum, *, budget, **_kwargs):
            calls.append(url)
            budget.account(budget.remaining)
            raise source_acquisition.AcquisitionError("injected failed transfer")

        with mock.patch.object(
            source_acquisition, "download_bytes", side_effect=fail_after_receiving
        ):
            report = source_acquisition.stage_candidates(
                candidates,
                staging_root=self.staging,
                journal_path=self.journal,
                db_path=None,
                limits=source_acquisition.Limits(
                    max_files=2,
                    max_file_bytes=10,
                    max_total_bytes=5,
                    min_text_chars=1,
                ),
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["summary"]["network_bytes_received"], 5)
        self.assertEqual(report["summary"]["error"], 2)
        self.assertIn("загрузка не выполнялась", report["items"][1]["reason"])

    def test_distinct_sources_with_same_basename_are_both_staged(self) -> None:
        for folder, marker in (("a", "ALPHA"), ("b", "BETA")):
            directory = self.web / folder
            directory.mkdir()
            (directory / "download.txt").write_text(
                (f"{marker} independent scholarship. " * 30), encoding="utf-8"
            )
        sources = [
            {
                "id": f"same-name-{folder}",
                "title": f"Independent work {marker}",
                "author": f"Author {marker}",
                "url": f"{self.base_url}/{folder}/download.txt",
                "format": "txt",
                "filename": "download.txt",
                "access": "open",
                "interest_id": "daily-life",
            }
            for folder, marker in (("a", "ALPHA"), ("b", "BETA"))
        ]
        manifest = self.root / "same-basename.json"
        manifest.write_text(
            json.dumps({"version": 1, "sources": sources}), encoding="utf-8"
        )
        report = self.root / "same-basename-report.json"

        self.assertEqual(
            self.run_cli(
                "stage",
                "--manifest",
                str(manifest),
                "--profile",
                str(self.profile),
                "--journal",
                str(self.journal),
                "--staging",
                str(self.staging),
                "--report",
                str(report),
                "--approve-downloads",
            ),
            0,
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["staged"], 2)
        originals = sorted(self.staging.glob("same-name-*/original-download.txt"))
        self.assertEqual(len(originals), 2)
        self.assertNotEqual(originals[0].read_bytes(), originals[1].read_bytes())

    def test_identical_content_from_different_urls_is_confirmed_by_checksum(self) -> None:
        shared = "Identical source bytes with enough text. " * 30
        for folder, filename in (("a", "download.txt"), ("b", "article.txt")):
            directory = self.web / folder
            directory.mkdir()
            (directory / filename).write_text(shared, encoding="utf-8")
        sources = [
            {
                "id": "checksum-first",
                "title": "First catalogue record",
                "author": "Author One",
                "url": f"{self.base_url}/a/download.txt",
                "format": "txt",
                "filename": "download.txt",
                "access": "open",
                "interest_id": "daily-life",
            },
            {
                "id": "checksum-second",
                "title": "Unrelated catalogue wording",
                "author": "Author Two",
                "url": f"{self.base_url}/b/article.txt",
                "format": "txt",
                "filename": "article.txt",
                "access": "open",
                "interest_id": "daily-life",
            },
        ]
        manifest = self.root / "checksum-duplicate.json"
        manifest.write_text(
            json.dumps({"version": 1, "sources": sources}), encoding="utf-8"
        )
        report = self.root / "checksum-duplicate-report.json"

        self.assertEqual(
            self.run_cli(
                "stage",
                "--manifest",
                str(manifest),
                "--profile",
                str(self.profile),
                "--journal",
                str(self.journal),
                "--staging",
                str(self.staging),
                "--report",
                str(report),
                "--approve-downloads",
            ),
            0,
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["staged"], 1)
        self.assertEqual(payload["summary"]["duplicate"], 1)
        duplicate = next(item for item in payload["items"] if item["status"] == "duplicate")
        self.assertEqual(duplicate["duplicate_confidence"], "confirmed")
        self.assertIn("контрольная сумма", duplicate["reason"])
        journal = json.loads(self.journal.read_text(encoding="utf-8"))
        self.assertEqual(len(journal["entries"]), 1)

    def test_promote_index_rejects_database_bound_to_other_corpus_first(self) -> None:
        manifest = self.manifest("txt", title_prefix="Corpus guard")
        stage_report = self.root / "guard-stage.json"
        self.assertEqual(
            self.run_cli(
                "stage",
                "--manifest",
                str(manifest),
                "--profile",
                str(self.profile),
                "--journal",
                str(self.journal),
                "--staging",
                str(self.staging),
                "--report",
                str(stage_report),
                "--approve-downloads",
            ),
            0,
        )
        source_id = json.loads(stage_report.read_text(encoding="utf-8"))["items"][0][
            "source_id"
        ]
        corpus_a = self.root / "corpus-a"
        corpus_b = self.root / "corpus-b"
        corpus_a.mkdir()
        corpus_b.mkdir()
        db = self.root / "bound.sqlite3"
        arguments = build_index.make_parser().parse_args(
            [
                str(corpus_a),
                "--db",
                str(db),
                "--log",
                str(self.root / "guard-index.log"),
                "--drive-csv",
                str(self.root / "guard.csv"),
                "--drive-jsonl",
                str(self.root / "guard.jsonl"),
            ]
        )
        build_index.build_index(arguments)
        before = db.read_bytes()

        code = self.run_cli(
            "promote",
            "--source-id",
            source_id,
            "--staging",
            str(self.staging),
            "--corpus",
            str(corpus_b),
            "--journal",
            str(self.journal),
            "--db",
            str(db),
            "--report",
            str(self.root / "guard-promote.json"),
            "--approve",
            "--index",
        )
        self.assertEqual(code, 1)
        self.assertFalse((corpus_b / "acquired" / source_id).exists())
        self.assertEqual(db.read_bytes(), before)

    def test_report_cannot_overwrite_critical_input_after_normalization(self) -> None:
        manifest = self.manifest("txt")
        before = self.profile.read_bytes()
        alias = self.profile.parent / "profiles-that-do-not-exist" / ".." / self.profile.name
        code = self.run_cli(
            "check",
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--report",
            str(alias),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.profile.read_bytes(), before)
        self.assertFalse(self.journal.exists())

    def test_policy_allows_bounded_automatic_mode(self) -> None:
        policy = self.root / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "automatic_downloads": True,
                    "max_files_per_run": 1,
                    "max_file_bytes": 100_000,
                    "max_total_bytes": 100_000,
                    "min_text_chars": 100,
                }
            ),
            encoding="utf-8",
        )
        manifest = self.manifest("txt")
        code = self.run_cli(
            "stage",
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--staging",
            str(self.staging),
            "--report",
            str(self.root / "automatic.json"),
            "--policy",
            str(policy),
        )
        self.assertEqual(code, 0)
        self.assertFalse((self.root / "corpus").exists())
        self.assertFalse((self.root / "index.sqlite3").exists())

    def test_promotion_without_separate_consent_changes_nothing(self) -> None:
        manifest = self.manifest("txt", title_prefix="Promotion refusal")
        stage_report = self.root / "stage-before-refusal.json"
        self.assertEqual(
            self.run_cli(
                "stage",
                "--manifest",
                str(manifest),
                "--profile",
                str(self.profile),
                "--journal",
                str(self.journal),
                "--staging",
                str(self.staging),
                "--report",
                str(stage_report),
                "--approve-downloads",
            ),
            0,
        )
        source_id = json.loads(stage_report.read_text(encoding="utf-8"))["items"][0][
            "source_id"
        ]
        corpus = self.root / "corpus"
        corpus.mkdir()
        code = self.run_cli(
            "promote",
            "--source-id",
            source_id,
            "--staging",
            str(self.staging),
            "--corpus",
            str(corpus),
            "--journal",
            str(self.journal),
            "--db",
            str(self.root / "index.sqlite3"),
            "--report",
            str(self.root / "refused-promotion.json"),
            "--index",
        )
        self.assertEqual(code, 1)
        self.assertEqual(list(corpus.iterdir()), [])
        self.assertFalse((self.root / "index.sqlite3").exists())

    def test_approved_promotion_is_idempotent_and_can_increment_index(self) -> None:
        manifest = self.manifest("html")
        stage_report = self.root / "stage.json"
        self.assertEqual(
            self.run_cli(
                "stage",
                "--manifest",
                str(manifest),
                "--profile",
                str(self.profile),
                "--journal",
                str(self.journal),
                "--staging",
                str(self.staging),
                "--report",
                str(stage_report),
                "--approve-downloads",
            ),
            0,
        )
        source_id = json.loads(stage_report.read_text(encoding="utf-8"))["items"][0]["source_id"]
        corpus = self.root / "corpus"
        corpus.mkdir()
        db = self.root / "index.sqlite3"
        report = self.root / "promote.json"
        common = (
            "promote",
            "--source-id",
            source_id,
            "--staging",
            str(self.staging),
            "--corpus",
            str(corpus),
            "--journal",
            str(self.journal),
            "--db",
            str(db),
            "--approve",
        )
        self.assertEqual(self.run_cli(*common, "--report", str(report), "--index"), 0)
        destination = corpus / "acquired" / source_id
        self.assertTrue((destination / "extracted.txt").is_file())
        self.assertTrue((destination / "source-metadata").is_file())
        connection = sqlite3.connect(db)
        indexed = connection.execute(
            "SELECT COUNT(*) FROM files WHERE relative_path LIKE ?",
            (f"acquired/{source_id}/%",),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(indexed, 1)
        journal = source_acquisition.load_journal(self.journal)
        journal["entries"] = [
            entry
            for entry in journal["entries"]
            if not (
                entry.get("source_id") == source_id
                and entry.get("status") == "promoted"
            )
        ]
        source_acquisition.write_json_atomic(self.journal, journal)
        second = self.root / "promote-again.json"
        self.assertEqual(self.run_cli(*common, "--report", str(second)), 0)
        second_payload = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(second_payload["summary"]["already_promoted"], 1)
        promoted_entries = [
            entry
            for entry in source_acquisition.load_journal(self.journal)["entries"]
            if entry.get("source_id") == source_id
            and entry.get("status") == "promoted"
        ]
        self.assertEqual(len(promoted_entries), 1)
        third = self.root / "promote-third.json"
        self.assertEqual(self.run_cli(*common, "--report", str(third)), 0)
        promoted_entries = [
            entry
            for entry in source_acquisition.load_journal(self.journal)["entries"]
            if entry.get("source_id") == source_id
            and entry.get("status") == "promoted"
        ]
        self.assertEqual(len(promoted_entries), 1)

    def test_index_failure_is_reported_after_safe_promotion(self) -> None:
        manifest = self.manifest("txt", title_prefix="Index failure")
        stage_report = self.root / "stage-before-index-failure.json"
        self.assertEqual(
            self.run_cli(
                "stage",
                "--manifest",
                str(manifest),
                "--profile",
                str(self.profile),
                "--journal",
                str(self.journal),
                "--staging",
                str(self.staging),
                "--report",
                str(stage_report),
                "--approve-downloads",
            ),
            0,
        )
        source_id = json.loads(stage_report.read_text(encoding="utf-8"))["items"][0]["source_id"]
        corpus = self.root / "corpus-index-failure"
        corpus.mkdir()
        report = self.root / "index-failure-report.json"
        failed = mock.Mock(returncode=1)
        with mock.patch.object(source_acquisition.subprocess, "run", return_value=failed):
            code = self.run_cli(
                "promote",
                "--source-id",
                source_id,
                "--staging",
                str(self.staging),
                "--corpus",
                str(corpus),
                "--journal",
                str(self.journal),
                "--db",
                str(self.root / "failed-index.sqlite3"),
                "--approve",
                "--index",
                "--report",
                str(report),
            )
        self.assertEqual(code, 1)
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["index"]["status"], "failed")
        self.assertEqual(payload["summary"]["error"], 1)
        self.assertTrue((corpus / "acquired" / source_id).is_dir())
        self.assertTrue(self.journal.is_file())

    def test_failed_extraction_leaves_no_partial_source(self) -> None:
        (self.web / "broken.xml").write_text("<TEI><broken>", encoding="utf-8")
        manifest = self.root / "broken-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sources": [
                        {
                            "id": "broken-xml",
                            "title": "Broken XML",
                            "author": "Test",
                            "url": f"{self.base_url}/broken.xml",
                            "format": "xml",
                            "filename": "broken.xml",
                            "access": "open",
                            "interest_id": "daily-life",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        report = self.root / "broken-report.json"
        self.assertEqual(
            self.run_cli(
                "stage",
                "--manifest",
                str(manifest),
                "--profile",
                str(self.profile),
                "--journal",
                str(self.journal),
                "--staging",
                str(self.staging),
                "--report",
                str(report),
                "--approve-downloads",
            ),
            1,
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["error"], 1)
        self.assertFalse((self.staging / "broken-xml").exists())
        self.assertFalse(self.journal.exists())

    def test_partial_stage_failure_keeps_successful_source_for_review(self) -> None:
        (self.web / "broken.xml").write_text("<TEI><broken>", encoding="utf-8")
        manifest = self.root / "partial-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sources": [
                        {
                            "id": "valid-txt",
                            "title": "Valid public text",
                            "author": "Test",
                            "url": f"{self.base_url}/source.txt",
                            "format": "txt",
                            "filename": "valid-source.txt",
                            "access": "open",
                            "interest_id": "daily-life",
                        },
                        {
                            "id": "broken-xml",
                            "title": "Broken XML",
                            "author": "Test",
                            "url": f"{self.base_url}/broken.xml",
                            "format": "xml",
                            "filename": "broken.xml",
                            "access": "open",
                            "interest_id": "daily-life",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        report = self.root / "partial-report.json"
        code = self.run_cli(
            "stage",
            "--manifest",
            str(manifest),
            "--profile",
            str(self.profile),
            "--journal",
            str(self.journal),
            "--staging",
            str(self.staging),
            "--report",
            str(report),
            "--approve-downloads",
        )
        self.assertEqual(code, 1)
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["staged"], 1)
        self.assertEqual(payload["summary"]["error"], 1)
        self.assertTrue((self.staging / "valid-txt" / "metadata.json").is_file())
        self.assertFalse((self.staging / "broken-xml").exists())
        journal = json.loads(self.journal.read_text(encoding="utf-8"))
        self.assertEqual(
            [entry["source_id"] for entry in journal["entries"]], ["valid-txt"]
        )

    def test_onboarding_keeps_acquisition_and_findings_opt_in_and_separate(self) -> None:
        variants = (
            (
                PROJECT / "examples" / "codex" / "research-onboarding.ru.md",
                PROJECT / "examples" / "codex" / "source-acquisition-workflow.ru.md",
                "Без явного согласия ничего не создавай",
                "не создавай повторную автоматизацию",
                "Они независимы",
            ),
            (
                PROJECT / "examples" / "codex" / "research-onboarding.md",
                PROJECT / "examples" / "codex" / "source-acquisition-workflow.md",
                "Without explicit consent create nothing",
                "do not create a duplicate acquisition task",
                "They are independent",
            ),
        )
        for onboarding_path, workflow_path, consent, no_duplicate, independent in variants:
            with self.subTest(language=onboarding_path.name):
                onboarding = onboarding_path.read_text(encoding="utf-8")
                workflow = workflow_path.read_text(encoding="utf-8")
                normalized_onboarding = " ".join(onboarding.split())
                normalized_workflow = " ".join(workflow.split())
                self.assertIn("source-acquisition-workflow", onboarding)
                self.assertIn(consent, normalized_onboarding)
                self.assertIn("research-workflow", onboarding)
                self.assertIn("automatic_downloads", workflow)
                self.assertIn(no_duplicate, normalized_workflow)
                self.assertIn(independent, normalized_workflow)
                self.assertIn("used_finds.csv", workflow)
                self.assertIn("--approve-downloads", workflow)
                self.assertIn("--approve --index", workflow)
                self.assertIn("ready_for_review", workflow)
                self.assertIn("build_index.py", workflow)
                if onboarding_path.name.endswith("ru.md"):
                    self.assertIn("не запускай `promote`", workflow)
                    self.assertIn("отдельное явное согласие", workflow)
                else:
                    self.assertIn("do not run `promote`", workflow)
                    self.assertIn("separate explicit consent", workflow)

    def test_public_examples_are_safe_defaults(self) -> None:
        policy = json.loads(
            (PROJECT / "examples" / "acquisition" / "policy.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(policy["automatic_downloads"])
        manifest = source_acquisition.load_manifest(
            PROJECT / "examples" / "acquisition" / "candidates.example.json"
        )
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["access"], "public-domain")


if __name__ == "__main__":
    unittest.main()
