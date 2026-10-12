from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(PROJECT))

import make_release  # noqa: E402


class ReleaseSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="taira-release-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_manifest(self, *files: str) -> Path:
        manifest = self.root / "release_manifest.toml"
        entries = "\n".join(f'  "{name}",' for name in files)
        manifest.write_text(
            f"[release]\nversion = 1\nfiles = [\n{entries}\n]\n",
            encoding="utf-8",
        )
        return manifest

    def test_archive_contains_only_exact_allowlist(self) -> None:
        (self.root / "public.txt").write_text("public", encoding="utf-8")
        unicode_dir = self.root / "данные"
        unicode_dir.mkdir()
        (unicode_dir / "пример.txt").write_text("公開", encoding="utf-8")

        (self.root / "used_finds.csv").write_text("private", encoding="utf-8")
        (self.root / "private.sqlite3").write_bytes(b"private")
        private_dir = self.root / "new_sources"
        private_dir.mkdir()
        (private_dir / "article.pdf").write_bytes(b"private")
        venv_dir = self.root / ".venv"
        venv_dir.mkdir()
        (venv_dir / "secret.txt").write_text("private", encoding="utf-8")

        manifest = self.write_manifest("public.txt", "данные/пример.txt")
        archive_path = self.root / "release.zip"
        make_release.build_release(archive_path, self.root, manifest)

        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(
                set(archive.namelist()), {"public.txt", "данные/пример.txt"}
            )

    def test_unlisted_file_does_not_change_deterministic_archive(self) -> None:
        (self.root / "public.txt").write_text("public", encoding="utf-8")
        manifest = self.write_manifest("public.txt")
        first = self.root / "first.zip"
        second = self.root / "second.zip"
        make_release.build_release(first, self.root, manifest)
        first_hash = make_release.sha256_file(first)

        (self.root / "private-note.txt").write_text("not listed", encoding="utf-8")
        make_release.build_release(second, self.root, manifest)
        self.assertEqual(first_hash, make_release.sha256_file(second))

    def test_manifest_rejects_parent_traversal(self) -> None:
        secret = self.root.parent / "outside.txt"
        manifest = self.write_manifest("../outside.txt")
        with self.assertRaises(make_release.ReleaseError):
            make_release.release_entries(self.root, manifest)
        self.assertFalse(secret.exists())

    def test_manifest_rejects_private_filename(self) -> None:
        (self.root / "used_finds.csv").write_text("private", encoding="utf-8")
        manifest = self.write_manifest("used_finds.csv")
        with self.assertRaises(make_release.ReleaseError):
            make_release.build_release(self.root / "release.zip", self.root, manifest)

    def test_absolute_local_path_in_allowed_text_is_rejected(self) -> None:
        private_path = "C:" + "\\Users\\Private\\Documents\\corpus"
        (self.root / "public.txt").write_text(private_path, encoding="utf-8")
        manifest = self.write_manifest("public.txt")
        with self.assertRaises(make_release.ReleaseError):
            make_release.build_release(self.root / "release.zip", self.root, manifest)

    def test_secret_like_token_in_allowed_text_is_rejected(self) -> None:
        fake_token = "sk-" + ("example" * 4)
        (self.root / "public.txt").write_text(fake_token, encoding="utf-8")
        manifest = self.write_manifest("public.txt")
        with self.assertRaises(make_release.ReleaseError):
            make_release.build_release(self.root / "release.zip", self.root, manifest)

    def test_missing_manifest_file_is_rejected(self) -> None:
        manifest = self.write_manifest("missing.txt")
        with self.assertRaises(make_release.ReleaseError):
            make_release.release_entries(self.root, manifest)

    def test_project_release_passes_its_own_audit(self) -> None:
        archive_path = self.root / "TairaSearch.zip"
        make_release.build_release(archive_path, PROJECT)
        make_release.verify_release(archive_path, PROJECT)
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            self.assertIn(".github/workflows/ci.yml", names)
            self.assertIn("LICENSE", names)
            self.assertIn("README.ru.md", names)
            self.assertIn("build_index.py", names)
            self.assertIn("docs/ai-workflow.md", names)
            self.assertIn("docs/ai-demo.ru.md", names)
            self.assertIn("docs/daily-automation-proposal.md", names)
            self.assertIn("examples/demo/ai-output.en.md", names)
            self.assertIn("examples/demo/codex-request.ru.md", names)
            self.assertIn("examples/demo/codex-request-existing-input.md", names)
            self.assertIn(
                "examples/demo/codex-request-existing-input.ru.md", names
            )
            self.assertIn("sample_corpus/玉葉/772049_0000001.txt", names)
            self.assertNotIn("used_finds.csv", names)
            self.assertFalse(any(name.endswith(".sqlite3") for name in names))
            self.assertFalse(any(name.startswith("new_sources/") for name in names))

    def test_ci_runs_supported_release_checks_without_publishing(self) -> None:
        workflow = (PROJECT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        for required in (
            "ubuntu-latest",
            "windows-latest",
            'python-version: "3.11"',
            "python -m pip install -r requirements.txt",
            "python -m unittest discover -s tests -v",
            "python run_demo.py",
            "python make_release.py --output work/TairaSearch.zip",
        ):
            self.assertIn(required, workflow)
        lowered = workflow.casefold()
        self.assertNotIn("codex", lowered)
        self.assertNotIn("upload-artifact", lowered)
        used_actions = "\n".join(
            line
            for line in lowered.splitlines()
            if line.lstrip().startswith("uses:")
        )
        self.assertNotIn("release", used_actions)


if __name__ == "__main__":
    unittest.main()
