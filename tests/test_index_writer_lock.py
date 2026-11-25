from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


PROJECT = Path(__file__).resolve().parents[1]
WORKER = """
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
import sys

module = import_module(sys.argv[1])
ready = Path(sys.argv[2])
real_lock = module.index_writer_lock

@contextmanager
def paused_lock(db):
    with real_lock(db):
        ready.touch()
        if not sys.stdin.readline():
            raise RuntimeError("Test did not release the writer")
        yield

module.index_writer_lock = paused_lock
raise SystemExit(module.main(sys.argv[3:]))
"""


class IndexWriterLockTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        corpus = root / "corpus"
        corpus.mkdir()
        old = corpus / "old.txt"
        old.write_text("An archivist recorded a bronze bell.", encoding="utf-8")
        (corpus / "kept.txt").write_text(
            "A traveller described a historic bridge.", encoding="utf-8"
        )
        self.db = root / "index.sqlite3"
        self.lock = root / "index.sqlite3.writer.lock"
        self.ready = root / "writer-ready"
        self.log = root / "index.log"
        self.index = [str(corpus), "--db", str(self.db), "--log", str(self.log)]
        self.prune = ["prune-missing-files", "--db", str(self.db)]
        self.assert_ok(self.run_command("build_index", self.index))
        old.unlink()
        self.assert_ok(self.run_command("taira_search", self.prune))
        self.confirm = [*self.prune, "--confirm-delete"]

    def run_command(self, module, args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", module, *args],
            cwd=PROJECT, capture_output=True, text=True, encoding="utf-8",
            timeout=15,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @contextlib.contextmanager
    def paused_writer(self, module, args):
        with subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", WORKER, module, str(self.ready), *args],
            cwd=PROJECT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        ) as process:
            try:
                deadline = time.monotonic() + 15
                while not self.ready.exists():
                    if process.poll() is not None:
                        self.fail(process.communicate()[0])
                    if time.monotonic() >= deadline:
                        self.fail("Writer did not acquire the index lock")
                    time.sleep(0.02)
                yield process
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=15)

    def assert_busy(self, module, args):
        db_before = self.db.read_bytes()
        log_before = self.log.read_bytes()
        result = self.run_command(module, args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Индекс занят другой операцией записи", result.stderr)
        self.assertEqual(self.db.read_bytes(), db_before)
        self.assertEqual(self.log.read_bytes(), log_before)

    def finish_writer(self, process):
        output, _ = process.communicate("continue\n", timeout=15)
        self.assertEqual(process.returncode, 0, output)

    def test_parallel_indexers_cover_regular_rebuild_and_targeted_modes(self):
        with self.paused_writer("build_index", self.index) as owner:
            for mode in ([], ["--rebuild"], ["--only-file", "kept.txt"]):
                with self.subTest(mode=mode):
                    self.assert_busy("build_index", [*self.index, *mode])
            self.assert_ok(self.run_command("build_index", [*self.index, "--scan-only"]))
            self.finish_writer(owner)

    def test_indexing_blocks_confirmed_cleanup(self):
        with self.paused_writer("build_index", [*self.index, "--rebuild"]) as owner:
            self.assert_busy("taira_search", self.confirm)
            self.finish_writer(owner)

    def test_cleanup_blocks_indexing_and_second_cleanup(self):
        with self.paused_writer("taira_search", self.confirm) as owner:
            self.assert_busy("taira_search", self.confirm)
            self.assert_busy("build_index", self.index)
            self.finish_writer(owner)

    def test_killed_writer_releases_lock_and_operations_run_sequentially(self):
        with self.paused_writer("build_index", self.index) as owner:
            self.assert_busy("taira_search", self.confirm)
            owner.kill()
            owner.communicate(timeout=15)
            self.assertNotEqual(owner.returncode, 0)
        self.assertTrue(self.lock.is_file())
        self.assert_ok(self.run_command("taira_search", self.confirm))
        self.assert_ok(self.run_command("build_index", [*self.index, "--only-file", "kept.txt"]))
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(
                connection.execute("SELECT relative_path FROM files").fetchall(),
                [("kept.txt",)],
            )
        self.assertTrue(self.lock.is_file())
