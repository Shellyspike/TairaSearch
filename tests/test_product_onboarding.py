from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (PROJECT / relative_path).read_text(encoding="utf-8")


class ProductPositioningTests(unittest.TestCase):
    def test_readmes_lead_with_user_value_and_one_request(self) -> None:
        cases = (
            (
                "README.ru.md",
                "Устал от новостей? Настрой свои!",
                "Установи TairaSearch из https://github.com/Shellyspike/TairaSearch",
                "не ищет обычные срочные новости",
            ),
            (
                "README.md",
                "Tired of the news? Make your own!",
                "Install TairaSearch from https://github.com/Shellyspike/TairaSearch",
                "not a breaking-news search engine",
            ),
        )
        for path, heading, request, boundary in cases:
            with self.subTest(path=path):
                text = read(path)
                self.assertIn(heading, text)
                self.assertIn(request, text)
                self.assertIn(boundary, text)
                first_screen = "\n".join(text.splitlines()[:35]).casefold()
                for implementation_detail in ("fts5", "bm25", "chunk"):
                    self.assertNotIn(implementation_detail, first_screen)

    def test_agent_guide_performs_safe_first_run(self) -> None:
        guide = read("AGENTS.md")
        for required in (
            "sys.prefix != sys.base_prefix",
            "python -m pip --version",
            "shorter writable path",
            "run_demo.py",
            "research_profile.json",
            "research-workflow.md",
            "source-acquisition-workflow.md",
            "work/library-staging/",
            "Never simulate",
            "No automation is created without explicit consent",
        ):
            self.assertIn(required, guide)

    def test_bilingual_onboarding_has_the_same_order(self) -> None:
        cases = (
            (
                "examples/codex/research-onboarding.ru.md",
                (
                    "## 1. Установка и проверка",
                    "## 2. Короткое интервью и профиль",
                    "## 3. Сначала предложи персональные выпуски",
                    "## 4. Откуда брать материалы",
                    "## 5. Отдельно предложи пополнение библиотеки",
                    "## 6. Пробный выпуск и окончание настройки",
                ),
            ),
            (
                "examples/codex/research-onboarding.md",
                (
                    "## 1. Install and verify",
                    "## 2. Interview and profile",
                    "## 3. Offer personal editions first",
                    "## 4. Choose the materials",
                    "## 5. Separately offer library acquisition",
                    "## 6. Preview and finish setup",
                ),
            ),
        )
        for path, markers in cases:
            with self.subTest(path=path):
                text = read(path)
                positions = [text.index(marker) for marker in markers]
                self.assertEqual(positions, sorted(positions))
                self.assertIn("--scan-only", text)
                self.assertIn("--preview", text)
                self.assertIn("--continue-from", text)
                self.assertIn("promote --index", text)
                self.assertIn("pip --version", text)

    def test_windows_incomplete_venv_has_non_system_recovery(self) -> None:
        guide = " ".join(read("AGENTS.md").split())
        self.assertIn("new copy in a shorter writable path", guide)
        self.assertIn("do not overwrite or delete the failed copy", guide)
        self.assertIn("do not install packages into the system Python", guide)

    def test_automation_stays_pending_until_preview_is_accepted(self) -> None:
        russian = read("examples/codex/research-onboarding.ru.md")
        english = read("examples/codex/research-onboarding.md")
        self.assertIn("пока не создавай и не запускай", russian)
        self.assertIn("Только после принятия пробной подборки", russian)
        self.assertIn("do not create or run the task yet", english)
        self.assertIn("Only after I accept the preview", english)

    def test_first_response_needs_no_technical_work_from_user(self) -> None:
        russian = read("examples/codex/research-onboarding.ru.md")
        english = read("examples/codex/research-onboarding.md")
        self.assertIn("Сам выполняй доступные технические действия", russian)
        self.assertIn("Не проси меня редактировать", russian)
        self.assertIn("Сначала проведи короткое интервью", russian)
        self.assertIn("Perform available technical actions yourself", english)
        self.assertIn("Do not ask me to", english)
        self.assertIn("First ask about the research area", english)

    def test_two_automations_are_separate_opt_in_decisions(self) -> None:
        guide = " ".join(read("AGENTS.md").split())
        self.assertIn("Offer a recurring personal-news edition", guide)
        self.assertIn("separately offer recurring source acquisition", guide)
        self.assertIn("independent from personal editions", guide)
        self.assertIn("No automation is created without explicit consent", guide)

    def test_public_allowlist_contains_first_run_material(self) -> None:
        manifest = tomllib.loads(read("release_manifest.toml"))
        files = set(manifest["release"]["files"])
        for expected in (
            "AGENTS.md",
            "docs/development.md",
            "docs/development.ru.md",
            "examples/codex/research-onboarding.md",
            "examples/codex/research-onboarding.ru.md",
            "tests/test_product_onboarding.py",
        ):
            self.assertIn(expected, files)


if __name__ == "__main__":
    unittest.main()
