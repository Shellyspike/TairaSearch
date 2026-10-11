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
    print(f"\nГотово: {len(payload['final'])} кандидатов сохранены в {candidates_output}")
    print("AI-анализ не запускался; candidates.json предназначен для следующего этапа Codex.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
