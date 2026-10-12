from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
import taira_search  # noqa: E402
from research_profile import load_research_profile  # noqa: E402


USED_HEADER = "id,type,persons,topics,short_description,source,date_used\n"


class ResearchProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        work_root = PROJECT / "work"
        work_root.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="research-profile-", dir=work_root)
        cls.root = Path(cls.temp.name)
        cls.expected = json.loads(
            (
                PROJECT
                / "examples"
                / "research-demo"
                / "expected_results.json"
            ).read_text(encoding="utf-8")
        )
        cls.databases: dict[str, Path] = {}
        for name, corpus in (
            ("japan", PROJECT / "sample_corpus"),
            ("rome", PROJECT / "sample_corpus_rome"),
        ):
            scenario = cls.root / name
            scenario.mkdir()
            database = scenario / "index.sqlite3"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = build_index.main(
                    [
                        str(corpus),
                        "--db",
                        str(database),
                        "--drive-csv",
                        str(scenario / "drive.csv"),
                        "--drive-jsonl",
                        str(scenario / "drive.jsonl"),
                        "--log",
                        str(scenario / "index.log"),
                        "--rebuild",
                    ]
                )
            if code:
                raise AssertionError(f"{name} demo index failed with exit code {code}")
            cls.databases[name] = database

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_profile(
        self,
        scenario: str,
        profile: Path,
        *,
        output_name: str,
        used_path: Path | None = None,
        count: int | None = None,
    ) -> dict:
        if used_path is None:
            used_path = self.root / f"{output_name}-used.csv"
            used_path.write_text(USED_HEADER, encoding="utf-8-sig")
        output = self.root / f"{output_name}.json"
        arguments = [
            "research-findings",
            "--db",
            str(self.databases[scenario]),
            "--profile",
            str(profile),
            "--used-finds",
            str(used_path),
            "--output",
            str(output),
            "--preview",
        ]
        if count is not None:
            arguments.extend(["--count", str(count)])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = taira_search.main(arguments)
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(output.read_text(encoding="utf-8"))

    def test_profiles_cover_different_research_areas(self) -> None:
        japan = load_research_profile(
            PROJECT / "examples" / "profiles" / "medieval-japan.json"
        )
        rome = load_research_profile(
            PROJECT / "examples" / "profiles" / "ancient-rome.json"
        )
        self.assertIn("Япония", japan["research_area"])
        self.assertIn("Рим", rome["research_area"])
        self.assertEqual(rome["focus_people"], [])

    def test_rome_works_without_known_people_or_japanese_rules(self) -> None:
        payload = self.run_profile(
            "rome",
            PROJECT / "examples" / "profiles" / "ancient-rome.json",
            output_name="rome",
        )
        self.assertEqual(len(payload["final"]), 3)
        self.assertTrue(all(not item["person"] for item in payload["final"]))
        self.assertTrue(
            all(
                item["relative_path"].startswith(
                    ("Articles/", "Baths/", "Market/", "Harbour/", "Workshop/")
                )
                for item in payload["final"]
            )
        )
        self.assertEqual(payload["coverage"]["focus_people_without_hits"], [])
        self.assertEqual(
            [
                {
                    "chunk_id": item["chunk_id"],
                    "relative_path": item["relative_path"],
                    "primary_topic": item["primary_topic"],
                }
                for item in payload["final"]
            ],
            self.expected["rome"],
        )

    def test_japan_profile_does_not_restrict_results_to_focus_people(self) -> None:
        profile_path = PROJECT / "examples" / "profiles" / "medieval-japan.json"
        profile = load_research_profile(profile_path)
        payload = self.run_profile("japan", profile_path, output_name="japan")
        focus = {item["name"] for item in profile["focus_people"]}
        returned = {name for item in payload["final"] for name in item["person"]}
        self.assertTrue(returned - focus)
        self.assertIn("Ёсицунэ", payload["coverage"]["focus_people_without_hits"])
        self.assertIn("Дзэами", payload["coverage"]["focus_people_without_hits"])
        self.assertEqual(
            [
                {
                    "chunk_id": item["chunk_id"],
                    "relative_path": item["relative_path"],
                    "primary_topic": item["primary_topic"],
                }
                for item in payload["final"]
            ],
            self.expected["japan"],
        )

    def test_saved_profile_is_reused_deterministically(self) -> None:
        profile_path = PROJECT / "examples" / "profiles" / "ancient-rome.json"
        before = profile_path.read_bytes()
        first = self.run_profile("rome", profile_path, output_name="reuse-one")
        second = self.run_profile("rome", profile_path, output_name="reuse-two")
        self.assertEqual(
            [item["chunk_id"] for item in first["final"]],
            [item["chunk_id"] for item in second["final"]],
        )
        self.assertEqual(profile_path.read_bytes(), before)

    def test_feedback_can_change_preferences_without_code_changes(self) -> None:
        source = json.loads(
            (PROJECT / "examples" / "profiles" / "ancient-rome.json").read_text(
                encoding="utf-8"
            )
        )
        source["name"] = "Только научные споры"
        source["max_results"] = 1
        source["interests"] = [source["interests"][2]]
        updated_profile = self.root / "updated-profile.json"
        updated_profile.write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        payload = self.run_profile(
            "rome", updated_profile, output_name="updated-preferences"
        )
        self.assertEqual(len(payload["final"]), 1)
        self.assertEqual(payload["final"][0]["source_type"], "scholarship")
        self.assertEqual(payload["final"][0]["primary_topic"], "research-debate")

    def test_missing_interest_is_reported_without_inventing_a_result(self) -> None:
        source = json.loads(
            (PROJECT / "examples" / "profiles" / "ancient-rome.json").read_text(
                encoding="utf-8"
            )
        )
        source["name"] = "Отсутствующая тема"
        source["interests"] = [
            {
                "id": "not-in-corpus",
                "label": "тема вне тестового корпуса",
                "terms": ["unfindable-synthetic-marker"],
                "weight": 1.0,
            }
        ]
        profile_path = self.root / "missing-interest.json"
        profile_path.write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        payload = self.run_profile(
            "rome", profile_path, output_name="missing-interest"
        )
        self.assertEqual(payload["final"], [])
        self.assertEqual(
            payload["coverage"]["interests_without_hits"], ["not-in-corpus"]
        )
        self.assertEqual(payload["coverage"]["search_hits"]["not-in-corpus"], 0)

    def test_preview_never_changes_publication_journal(self) -> None:
        used_path = self.root / "existing-used.csv"
        used_path.write_text(
            USED_HEADER
            + "existing,event,Someone,topic,Existing description,Source,2026-01-01\n",
            encoding="utf-8-sig",
        )
        before = used_path.read_bytes()
        payload = self.run_profile(
            "rome",
            PROJECT / "examples" / "profiles" / "ancient-rome.json",
            output_name="journal-preview",
            used_path=used_path,
            count=2,
        )
        self.assertTrue(payload["preview"])
        self.assertEqual(len(payload["final"]), 2)
        self.assertEqual(used_path.read_bytes(), before)

    def test_bilingual_onboarding_is_dialogue_first_and_safe(self) -> None:
        variants = (
            (
                PROJECT / "examples" / "codex" / "research-onboarding.md",
                PROJECT / "docs" / "research-onboarding.md",
                "short, natural conversation",
                "research_profile.json",
            ),
            (
                PROJECT / "examples" / "codex" / "research-onboarding.ru.md",
                PROJECT / "docs" / "research-onboarding.ru.md",
                "короткий естественный диалог",
                "research_profile.json",
            ),
        )
        for prompt_path, documentation_path, dialogue, profile_name in variants:
            with self.subTest(prompt=prompt_path.name):
                prompt = prompt_path.read_text(encoding="utf-8")
                documentation = documentation_path.read_text(encoding="utf-8")
                self.assertIn(dialogue, prompt)
                self.assertIn("--scan-only", prompt)
                self.assertIn("--preview", prompt)
                self.assertIn("daily-news-prompt.md", prompt)
                self.assertIn(profile_name, prompt)
                self.assertIn(profile_name, documentation)
                self.assertIn("research-findings", documentation)
                self.assertIn("used_finds.csv", documentation)

        ignore = (PROJECT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("research_profile.json", ignore)
        self.assertIn("/research_profiles/", ignore)


if __name__ == "__main__":
    unittest.main()
