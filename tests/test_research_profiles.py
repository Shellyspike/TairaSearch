from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(PROJECT))

import build_index  # noqa: E402
import research_findings  # noqa: E402
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
        extra_arguments: tuple[str, ...] = (),
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
        arguments.extend(extra_arguments)
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

    def test_missing_default_profile_routes_user_to_codex_onboarding(self) -> None:
        parser = taira_search.make_parser()
        arguments = parser.parse_args(["research-findings"])
        self.assertEqual(
            Path(arguments.profile).resolve(),
            (PROJECT / "research_profile.json").resolve(),
        )
        with self.assertRaisesRegex(RuntimeError, "research-onboarding.ru.md"):
            load_research_profile(self.root / "missing-profile.json")

    def test_clean_onboarding_folder_path_scans_builds_and_previews(self) -> None:
        scenario = self.root / "clean-onboarding"
        corpus = scenario / "new-library"
        corpus.mkdir(parents=True)
        (corpus / "open-example.txt").write_text(
            "Synthetic onboarding material. The signal appears in a complete "
            "account with enough context to test a first research preview. "
            "This is not a historical claim.",
            encoding="utf-8",
        )
        database = scenario / "work" / "index.sqlite3"
        profile_path = scenario / "research_profile.json"
        used_path = scenario / "used.csv"
        output_path = scenario / "work" / "candidates.json"
        self.assertFalse(database.exists())
        self.assertFalse(profile_path.exists())

        scan_stdout = io.StringIO()
        with contextlib.redirect_stdout(scan_stdout), mock.patch.object(
            build_index,
            "parse_file",
            side_effect=AssertionError("scan-only read document contents"),
        ):
            scan_code = build_index.main(
                [str(corpus), "--scan-only", "--db", str(database)]
            )
        self.assertEqual(scan_code, 0)
        self.assertFalse(database.exists())
        self.assertIn("Найдено поддерживаемых файлов: 1", scan_stdout.getvalue())

        profile = {
            "schema_version": 1,
            "name": "Clean onboarding",
            "research_area": "Synthetic setup verification",
            "result_language": "en",
            "max_results": 1,
            "interests": [
                {
                    "id": "signal",
                    "label": "signal",
                    "terms": ["signal"],
                    "weight": 1.0,
                }
            ],
            "focus_people": [],
            "material_types": ["historical", "literary", "scholarship", "other"],
            "include_sources": [],
            "exclude_sources": [],
            "finding_preferences": {
                "preferred_kinds": ["clear source-supported finding"],
                "include_unlisted_people": True,
                "avoid_person_repetition": True,
                "notes": "Explain why the finding matters.",
            },
        }
        profile_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        database.parent.mkdir(parents=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            build_code = build_index.main(
                [
                    str(corpus),
                    "--db",
                    str(database),
                    "--drive-csv",
                    str(scenario / "work" / "drive.csv"),
                    "--drive-jsonl",
                    str(scenario / "work" / "drive.jsonl"),
                    "--log",
                    str(scenario / "work" / "index.log"),
                ]
            )
        self.assertEqual(build_code, 0)
        self.assertTrue(database.is_file())

        used_path.write_text(USED_HEADER, encoding="utf-8-sig")
        journal_before = used_path.read_bytes()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            preview_code = taira_search.main(
                [
                    "research-findings",
                    "--db",
                    str(database),
                    "--profile",
                    str(profile_path),
                    "--used-finds",
                    str(used_path),
                    "--output",
                    str(output_path),
                    "--preview",
                    "--count",
                    "1",
                ]
            )
        self.assertEqual(preview_code, 0, stderr.getvalue())
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["final"]), 1)
        self.assertTrue(payload["final"][0]["chunk_id"].startswith("ch_"))
        self.assertEqual(payload["final"][0]["relative_path"], "open-example.txt")
        self.assertEqual(used_path.read_bytes(), journal_before)

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
            "rome", profile_path, output_name="missing-interest-results"
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

    def test_codex_can_reject_first_batch_and_request_disjoint_next_batch(self) -> None:
        profile = PROJECT / "examples" / "profiles" / "ancient-rome.json"
        first = self.run_profile(
            "rome",
            profile,
            output_name="first-batch",
            count=1,
            extra_arguments=("--pool-size", "10", "--batch-size", "2"),
        )
        first_path = self.root / "first-batch.json"
        first_ids = {
            item["chunk_id"] for item in [*first["final"], *first["alternates"]]
        }
        self.assertTrue(first_ids)
        self.assertEqual(
            set(first["continuation"]["candidate_chunk_ids"]), first_ids
        )

        second = self.run_profile(
            "rome",
            profile,
            output_name="second-batch",
            count=1,
            extra_arguments=(
                "--pool-size",
                "10",
                "--batch-size",
                "2",
                "--continue-from",
                str(first_path),
            ),
        )
        second_ids = {
            item["chunk_id"] for item in [*second["final"], *second["alternates"]]
        }
        self.assertTrue(second_ids)
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertGreaterEqual(
            second["continuation"]["seen_before_count"], len(first_ids)
        )
        self.assertEqual(
            second["stats"]["excluded_from_previous_batches"], len(first_ids)
        )
        self.assertGreater(second["coverage"]["search_hits"]["daily-life"], 0)
        self.assertNotIn(
            "daily-life", second["coverage"]["interests_without_hits"]
        )

    def test_continuation_accepts_legacy_result_without_new_metadata(self) -> None:
        profile = PROJECT / "examples" / "profiles" / "ancient-rome.json"
        first = self.run_profile(
            "rome",
            profile,
            output_name="legacy-source",
            count=1,
            extra_arguments=("--pool-size", "10", "--batch-size", "2"),
        )
        first.pop("continuation")
        legacy_path = self.root / "legacy-result.json"
        legacy_path.write_text(
            json.dumps(first, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        first_ids = {
            item["chunk_id"] for item in [*first["final"], *first["alternates"]]
        }

        second = self.run_profile(
            "rome",
            profile,
            output_name="legacy-continuation",
            count=1,
            extra_arguments=(
                "--pool-size",
                "10",
                "--batch-size",
                "2",
                "--continue-from",
                str(legacy_path),
            ),
        )
        second_ids = {
            item["chunk_id"] for item in [*second["final"], *second["alternates"]]
        }
        self.assertTrue(second_ids)
        self.assertTrue(first_ids.isdisjoint(second_ids))

    def test_pre_editorial_rejects_remain_available_to_later_batches(self) -> None:
        used_path = self.root / "continuation-rejects-used.csv"
        used_path.write_text(USED_HEADER, encoding="utf-8-sig")
        profile = {
            "version": 1,
            "name": "Continuation regression",
            "research_area": "Synthetic",
            "result_language": "en",
            "max_results": 1,
            "interests": [
                {
                    "id": "signal",
                    "label": "signal",
                    "terms": ["signal"],
                    "weight": 1.0,
                }
            ],
            "focus_people": [],
            "material_types": ["primary"],
            "include_sources": [],
            "exclude_sources": [],
            "finding_preferences": {
                "include_unlisted_people": True,
                "avoid_person_repetition": False,
                "notes": "",
            },
        }
        rows = [
            {
                "chunk_id": "shown",
                "rank": 1,
                "score": 2.0,
                "relative_path": "source.txt",
            },
            {
                "chunk_id": "context-only",
                "rank": 2,
                "score": 1.0,
                "relative_path": "source.txt",
            },
        ]

        def fake_search(*args, **kwargs):
            return rows

        def fake_context(connection, chunk_id, before, after):
            text = (
                "The signal appears in a complete and readable account of a distinct event. "
                "Enough context is present for editorial review and source verification."
                if chunk_id == "shown"
                else "This neighbouring passage is readable but does not contain the query term."
            )
            return [
                {
                    "target": True,
                    "chunk_id": chunk_id,
                    "chunk_no": 1 if chunk_id == "shown" else 2,
                    "page_start": 1,
                    "page_end": 1,
                    "text": text,
                    "text_quality": "good",
                    "people": [],
                    "source": "Synthetic Source",
                    "source_type": "primary",
                    "filename": "source.txt",
                    "path": "source.txt",
                }
            ]

        result = research_findings.build_research_findings(
            None,
            {},
            {},
            profile,
            used_path,
            search_function=fake_search,
            context_function=fake_context,
            count=1,
            top_per_interest=5,
            pool_size=5,
            batch_size=1,
            preview=True,
        )

        continuation = result["continuation"]
        self.assertEqual(continuation["candidate_chunk_ids"], ["shown"])
        self.assertIn("context-only", continuation["python_rejected_chunk_ids"])
        self.assertNotIn("context-only", continuation["exclude_on_next_run"])
        self.assertIn("shown", continuation["exclude_on_next_run"])

        result_path = self.root / "continuation-rejects.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(
            research_findings.load_continuation_chunk_ids([result_path], profile),
            {"shown"},
        )

    def test_output_cannot_replace_any_critical_input_after_normalization(self) -> None:
        inputs = {
            "--db": self.databases["rome"],
            "--profile": self.root / "protected-profile.json",
            "--used-finds": self.root / "protected-used.csv",
            "--aliases": self.root / "protected-aliases.json",
            "--topics-config": self.root / "protected-topics.json",
            "--people-config": self.root / "protected-people.json",
            "--source-types-config": self.root / "protected-source-types.json",
            "--continue-from": self.root / "protected-continuation.json",
        }
        inputs["--profile"].write_bytes(
            (PROJECT / "examples" / "profiles" / "ancient-rome.json").read_bytes()
        )
        inputs["--used-finds"].write_text(USED_HEADER, encoding="utf-8-sig")
        inputs["--continue-from"].write_text("{}\n", encoding="utf-8")
        for option, source_name in (
            ("--aliases", "aliases.json"),
            ("--topics-config", "topics.json"),
            ("--people-config", "people.json"),
            ("--source-types-config", "source_types.json"),
        ):
            inputs[option].write_bytes((PROJECT / source_name).read_bytes())

        base_arguments = ["research-findings"]
        for option, path in inputs.items():
            base_arguments.extend([option, str(path)])

        for preview in (False, True):
            for protected_option, protected_path in inputs.items():
                with self.subTest(option=protected_option, preview=preview):
                    before = protected_path.read_bytes()
                    normalized_alias = (
                        protected_path.parent
                        / "directory-that-does-not-exist"
                        / ".."
                        / protected_path.name
                    )
                    arguments = [
                        *base_arguments,
                        "--output",
                        str(normalized_alias),
                    ]
                    if preview:
                        arguments.append("--preview")
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with mock.patch.object(taira_search, "load_runtime") as loader:
                        with contextlib.redirect_stdout(
                            stdout
                        ), contextlib.redirect_stderr(stderr):
                            code = taira_search.main(arguments)
                    self.assertEqual(code, 1)
                    loader.assert_not_called()
                    self.assertEqual(protected_path.read_bytes(), before)
                    self.assertIn("Небезопасный --output", stderr.getvalue())
                    self.assertIn(protected_option, stderr.getvalue())
                    self.assertIn("после нормализации", stderr.getvalue())

    def test_bilingual_onboarding_is_dialogue_first_and_safe(self) -> None:
        variants = (
            (
                PROJECT / "examples" / "codex" / "research-onboarding.md",
                PROJECT / "docs" / "research-onboarding.md",
                "short, natural conversation",
                "research_profile.json",
                "never store a preference that should change selection only there",
            ),
            (
                PROJECT / "examples" / "codex" / "research-onboarding.ru.md",
                PROJECT / "docs" / "research-onboarding.ru.md",
                "короткий естественный диалог",
                "research_profile.json",
                "нельзя сохранять только там пожелание, которое должно менять отбор",
            ),
        )
        for (
            prompt_path,
            documentation_path,
            dialogue,
            profile_name,
            effective_preference_rule,
        ) in variants:
            with self.subTest(prompt=prompt_path.name):
                prompt = prompt_path.read_text(encoding="utf-8")
                documentation = documentation_path.read_text(encoding="utf-8")
                normalized_prompt = " ".join(prompt.split())
                normalized_documentation = " ".join(documentation.split())
                self.assertIn(dialogue, prompt)
                self.assertIn("--scan-only", prompt)
                self.assertIn("--preview", prompt)
                self.assertIn("daily-news-prompt.md", prompt)
                self.assertIn(profile_name, prompt)
                self.assertIn("interests[].terms", prompt)
                self.assertIn("weight", prompt)
                self.assertIn(effective_preference_rule, normalized_prompt)
                self.assertIn("finding_preferences.notes", prompt)
                self.assertIn("--continue-from", prompt)
                self.assertIn("codex://automations", prompt)
                self.assertIn("source-acquisition-workflow", prompt)
                self.assertIn("library-staging", prompt)
                self.assertIn(profile_name, documentation)
                self.assertIn("research-findings", documentation)
                self.assertIn("used_finds.csv", documentation)
                self.assertIn("interests[].terms", documentation)
                self.assertIn("weight", documentation)
                self.assertIn("notes", normalized_documentation)
                self.assertIn("codex://automations", documentation)
                if prompt_path.name.endswith("ru.md"):
                    self.assertLess(
                        normalized_prompt.index("Сначала проведи короткое интервью"),
                        normalized_prompt.index(
                            "Только после подтверждения интересов выясни"
                        ),
                    )
                    self.assertIn("У меня есть папка документов", normalized_prompt)
                    self.assertIn("У меня есть готовый индекс", normalized_prompt)
                    self.assertIn("У меня пока ничего нет", normalized_prompt)
                    self.assertIn("только после явного выбора", normalized_prompt)
                    self.assertIn("Если веб-поиск", normalized_prompt)
                    self.assertIn("Без явного согласия", normalized_prompt)
                    self.assertIn("не создавай повторную автоматизацию", normalized_prompt)
                    self.assertIn("периодичность", normalized_prompt)
                    self.assertIn("часовой пояс", normalized_prompt)
                    self.assertIn("живой развёрнутый стиль", normalized_prompt)
                else:
                    self.assertLess(
                        normalized_prompt.index("First ask about the research area"),
                        normalized_prompt.index(
                            "Only after confirming my interests"
                        ),
                    )
                    self.assertIn("I have a folder of documents", normalized_prompt)
                    self.assertIn("I have a ready TairaSearch index", normalized_prompt)
                    self.assertIn("I have nothing yet", normalized_prompt)
                    self.assertIn("only after I select exact items", normalized_prompt)
                    self.assertIn("If web search or download tools", normalized_prompt)
                    self.assertIn("without my explicit agreement", normalized_prompt)
                    self.assertIn("do not create a duplicate acquisition task", normalized_prompt)
                    self.assertIn("cadence", normalized_prompt)
                    self.assertIn("time zone", normalized_prompt)
                    self.assertIn("vivid, expanded cards", normalized_prompt)

        ignore = (PROJECT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("research_profile.json", ignore)
        self.assertIn("/research_profiles/", ignore)

    def test_codex_workflow_owns_semantic_review_and_continuation(self) -> None:
        for path in (
            PROJECT / "examples" / "codex" / "research-workflow.md",
            PROJECT / "examples" / "codex" / "research-workflow.ru.md",
        ):
            with self.subTest(prompt=path.name):
                prompt = path.read_text(encoding="utf-8")
                self.assertIn("research-findings", prompt)
                self.assertIn("--continue-from", prompt)
                self.assertIn("`search`", prompt)
                self.assertIn("`context`", prompt)
                self.assertIn("semantic_review", prompt)
                self.assertIn("confirmed_repeat", prompt)
                self.assertIn("probable_repeat_review", prompt)
                self.assertIn("new_angle", prompt)
                self.assertIn("new_finding", prompt)
                self.assertIn("research-onboarding", prompt)
                self.assertIn("record-publication", prompt)
                self.assertIn("render-publication", prompt)
                self.assertIn(
                    "полный stdout"
                    if path.name.endswith("ru.md")
                    else "complete stdout",
                    prompt,
                )
                self.assertIn("daily-five", prompt)
                self.assertIn("used_finds.csv", prompt)
                self.assertIn("finding_preferences.notes", prompt)
                self.assertIn("*.editorial.json", prompt)
                self.assertIn("research-context", prompt)
                self.assertIn("--include-required-review", prompt)
                self.assertIn(
                    "Не вызывай `--help`"
                    if path.name.endswith("ru.md")
                    else "Do not call `--help`",
                    prompt,
                )
                if path.name.endswith("ru.md"):
                    self.assertIn("живой развёрнутой подачи", prompt)
                else:
                    self.assertIn("vivid, expanded cards", prompt)

    def test_editorial_packet_is_compact_and_full_result_keeps_context(self) -> None:
        full = self.run_profile(
            "japan",
            PROJECT / "examples" / "profiles" / "medieval-japan.json",
            output_name="compact-editorial-packet",
            count=3,
            extra_arguments=("--batch-size", "12"),
        )
        editorial_path = self.root / "compact-editorial-packet.editorial.json"
        editorial = json.loads(editorial_path.read_text(encoding="utf-8"))

        self.assertEqual(editorial["mode"], "research-findings-editorial")
        self.assertEqual(
            editorial["size"]["editorial_packet_bytes"],
            len(editorial_path.read_bytes()),
        )
        self.assertLess(
            len(editorial_path.read_bytes()),
            len((self.root / "compact-editorial-packet.json").read_bytes()),
        )
        self.assertGreater(editorial["size"]["reduction_percent"], 25)
        self.assertTrue(full["final"])
        self.assertIn("chunks", full["final"][0]["verified_context"])
        self.assertNotIn("verified_context", editorial["final"][0])
        for candidate in [*full["final"], *full["alternates"]]:
            for relation in candidate["semantic_review"]["candidate_matches"]:
                self.assertNotIn("verified_context", relation["candidate"])
                self.assertIn("context_ref", relation["candidate"])
                available = {
                    item["chunk_id"]
                    for item in [
                        *full["final"],
                        *full["alternates"],
                        *full["comparison_contexts"],
                    ]
                }
                self.assertIn(relation["matched_chunk_id"], available)

    def test_off_batch_semantic_match_has_one_reusable_full_context(self) -> None:
        real_attach = research_findings.attach_semantic_reviews

        def force_off_batch_link(candidates):
            real_attach(candidates)
            self.assertGreater(len(candidates), 1)
            for index, candidate in enumerate(candidates):
                other = candidates[(index + 1) % len(candidates)]
                candidate["semantic_review"]["required"] = True
                candidate["semantic_review"]["candidate_matches"] = [
                    {
                        "matched_chunk_id": other["chunk_id"],
                        "confidence": 0.75,
                        "reason": "forced off-batch regression relation",
                        "candidate": {
                            "chunk_id": other["chunk_id"],
                            "context_ref": {
                                "chunk_id": other["chunk_id"],
                                "field": "verified_context",
                            },
                        },
                    }
                ]
            return candidates

        with mock.patch.object(
            research_findings,
            "attach_semantic_reviews",
            side_effect=force_off_batch_link,
        ):
            result = self.run_profile(
                "rome",
                PROJECT / "examples" / "profiles" / "ancient-rome.json",
                output_name="off-batch-comparison-context",
                count=1,
                extra_arguments=("--pool-size", "10", "--batch-size", "1"),
            )

        visible = result["final"][0]
        hidden_id = visible["semantic_review"]["candidate_matches"][0][
            "matched_chunk_id"
        ]
        self.assertEqual(
            [item["chunk_id"] for item in result["comparison_contexts"]],
            [hidden_id],
        )
        self.assertNotIn("semantic_review", result["comparison_contexts"][0])

        packet = research_findings.build_research_context_packet(
            result, [visible["chunk_id"]]
        )

        self.assertEqual(
            [item["chunk_id"] for item in packet["candidates"]],
            [visible["chunk_id"], hidden_id],
        )
        hidden_evidence = packet["candidates"][1]["verified_context"]
        self.assertTrue(hidden_evidence["chunks"])
        canonical_rows = [
            item
            for section in ("final", "alternates", "comparison_contexts")
            for item in result.get(section, [])
            if item.get("chunk_id") == hidden_id and "verified_context" in item
        ]
        self.assertEqual(len(canonical_rows), 1)

    def test_consolidated_context_packet_reuses_saved_full_result(self) -> None:
        full = self.run_profile(
            "japan",
            PROJECT / "examples" / "profiles" / "medieval-japan.json",
            output_name="consolidated-context-source",
            count=2,
            extra_arguments=("--batch-size", "10"),
        )
        selected = full["final"][0]["chunk_id"]
        packet = research_findings.build_research_context_packet(
            full, [selected], include_required_review=True
        )
        included = {item["chunk_id"] for item in packet["candidates"]}
        self.assertIn(selected, included)
        for item in packet["candidates"]:
            self.assertIn("chunks", item["verified_context"])
        required = {
            item["chunk_id"]
            for item in [*full["final"], *full["alternates"]]
            if item["semantic_review"]["required"]
        }
        self.assertTrue(required.issubset(included))


if __name__ == "__main__":
    unittest.main()

