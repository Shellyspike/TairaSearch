#!/usr/bin/env python3
"""Build and exercise the self-contained public TairaSearch demonstration."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import build_index
import taira_search


PROJECT_DIR = Path(__file__).resolve().parent
SAMPLE_CORPUS = PROJECT_DIR / "sample_corpus"
WHY_INTERESTING_EN = {
    "music": "A small performance reveals courtly etiquette through silence, objects, and the order of conversation.",
    "feast": "The scene turns hospitality into a literary test of how status and care are distributed.",
    "captivity": "A list of separated attendants gives an administrative act a personal and social scale.",
    "fire": "Gates, a well, buckets, and letters make the material risks of an urban fire visible.",
    "illness": "An unexplained absence shows how illness could disrupt messengers and ceremonial planning without revealing a diagnosis.",
}


def find_related_scholarship(
    item: dict,
    connection,
    topics: dict,
    people: dict,
) -> list[dict]:
    """Find one deterministic synthetic research note for a demo candidate."""
    args = argparse.Namespace(
        query=None,
        topic=[item["primary_topic"]],
        person=list(item["person"]),
        source_type=["scholarship"],
        exclude_source_type=[],
        source=[],
        exclude_source=[],
        quality=["good"],
        top=1,
        offset=0,
        json=False,
        include_duplicates=False,
    )
    matches = taira_search.search_database(
        connection, args, topics, people, events_only=False
    )
    if not matches:
        return []
    match = matches[0]
    context = taira_search.context_rows(
        connection, match["chunk_id"], before=0, after=0
    )
    excerpt = context[0]["text"] if context else match["snippet"]
    return [
        {
            "material_status": "synthetic_demo_not_historical_evidence",
            "relative_path": match["relative_path"],
            "chunk_id": match["chunk_id"],
            "source": match["source"],
            "index_source_type": match["source_type"],
            "source_excerpt": excerpt,
        }
    ]


def make_ai_input(payload: dict, connection, topics: dict, people: dict) -> dict:
    """Return a stable, path-safe handoff containing only verified demo evidence."""

    final = payload.get("final", [])
    if not isinstance(final, list) or len(final) != 5:
        raise ValueError("AI demo requires exactly five selected candidates")
    candidates = []
    for ordinal, item in enumerate(final, start=1):
        verified = item.get("verified_context", {})
        candidates.append(
            {
                "ordinal": ordinal,
                "material_status": "synthetic_demo_not_historical_evidence",
                "chunk_id": item["chunk_id"],
                "relative_path": item["relative_path"],
                "source": item["source"],
                "source_group": item["source_group"],
                "source_type": item["source_type"],
                "index_source_type": item["index_source_type"],
                "people": item["person"],
                "primary_topic": item["primary_topic"],
                "topics": item["topics"],
                "date": item.get("date"),
                "place": item.get("place"),
                "source_excerpt": item.get("source_quote") or item["what_happened"],
                "why_interesting_hint": item["why_interesting"],
                "why_interesting_hint_en": WHY_INTERESTING_EN.get(
                    item["primary_topic"],
                    "The episode connects a named person to a concrete social practice.",
                ),
                "related_scholarship": find_related_scholarship(
                    item, connection, topics, people
                ),
                "verification": {
                    "status": verified.get("status"),
                    "evidence_terms": verified.get("evidence_terms", []),
                    "max_term_gap_chars": verified.get("max_term_gap_chars"),
                    "context_chunks": verified.get("chunks", []),
                },
                "duplicate_check": item["duplicate_check"],
            }
        )
    return {
        "schema_version": 2,
        "demo": True,
        "material_status": "synthetic_demo_not_historical_evidence",
        "notice_ru": (
            "Все тексты и события вымышлены для демонстрации TairaSearch; "
            "их нельзя представлять как реальные исторические сведения."
        ),
        "notice_en": (
            "All texts and events are fictional TairaSearch demonstration "
            "materials and must not be presented as historical claims."
        ),
        "source_note_ru": (
            "Названия папок имитируют типы источников только для проверки "
            "классификации и не означают, что фрагменты взяты из этих произведений."
        ),
        "source_note_en": (
            "Historical-looking folder names test classification only; they "
            "do not claim that excerpts come from the named works."
        ),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Построить демо-индекс, выполнить поиск и выбрать пять кандидатов"
    )
    parser.add_argument(
        "--work-dir",
        default=str(PROJECT_DIR / "work" / "demo"),
        help="Каталог только для создаваемых демо-файлов",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    build_index.configure_console()
    args = make_parser().parse_args(argv)
    work_dir = Path(args.work_dir).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    database = work_dir / "index.sqlite3"
    search_output = work_dir / "search.jsonl"
    candidates_output = work_dir / "candidates.json"
    ai_input_output = work_dir / "ai-input.json"
    used_finds = work_dir / "demo_used_finds.csv"
    used_finds.write_text(
        "id,type,persons,topics,short_description,source,date_used\n",
        encoding="utf-8-sig",
    )

    print("\n[1/3] Построение чистого индекса из sample_corpus")
    build_code = build_index.main(
        [
            str(SAMPLE_CORPUS),
            "--db",
            str(database),
            "--drive-csv",
            str(work_dir / "drive.csv"),
            "--drive-jsonl",
            str(work_dir / "drive.jsonl"),
            "--log",
            str(work_dir / "index.log"),
            "--rebuild",
        ]
    )
    if build_code:
        return build_code

    print("\n[2/3] Пример многоязычного FTS5-поиска")
    search_stdout = io.StringIO()
    with contextlib.redirect_stdout(search_stdout):
        search_code = taira_search.main(
            [
                "search",
                "--db",
                str(database),
                "--query",
                "Русская запись",
                "--top",
                "5",
                "--json",
            ]
        )
    if search_code:
        return search_code
    search_text = search_stdout.getvalue()
    search_output.write_text(search_text, encoding="utf-8")
    search_rows = [json.loads(line) for line in search_text.splitlines() if line]
    print(f"Найдено: {len(search_rows)}; JSON Lines: {search_output}")
    if search_rows:
        print(
            "Первый результат: "
            f"{search_rows[0]['relative_path']} ({search_rows[0]['chunk_id']})"
        )

    print("\n[3/3] Детерминированный отбор пяти кандидатов")
    daily_code = taira_search.main(
        [
            "daily-five",
            "--db",
            str(database),
            "--used-finds",
            str(used_finds),
            "--top-per-topic",
            "20",
            "--pool-size",
            "120",
            "--output",
            str(candidates_output),
        ]
    )
    if daily_code:
        return daily_code

    payload = json.loads(candidates_output.read_text(encoding="utf-8"))
    runtime_args = taira_search.make_parser().parse_args(
        ["search", "--db", str(database), "--query", "demo"]
    )
    connection, topics, people = taira_search.load_runtime(runtime_args)
    try:
        ai_input = make_ai_input(payload, connection, topics, people)
    finally:
        connection.close()
    ai_input_output.write_text(
        json.dumps(ai_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nГотово: {len(payload['final'])} кандидатов сохранены в {candidates_output}")
    print(f"Безопасный вход для Codex: {ai_input_output}")
    print("AI-анализ не запускался; следующий шаг описан в docs/ai-demo.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
