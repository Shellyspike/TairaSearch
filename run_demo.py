#!/usr/bin/env python3
"""Run the small profile-driven TairaSearch smoke test."""

from __future__ import annotations

import argparse
from pathlib import Path

import build_index
from run_research_demo import run_scenario


PROJECT_DIR = Path(__file__).resolve().parent


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Построить демо-индекс и выполнить профильный preview"
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
    code = run_scenario("japan", work_dir)
    if code:
        return code
    print("\nДемо завершено: индекс, поиск и preview использовали временные данные.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
