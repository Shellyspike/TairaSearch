#!/usr/bin/env python3
"""Build two small indexes and run profile-driven preview selections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_index
import taira_search


PROJECT_DIR = Path(__file__).resolve().parent
SCENARIOS = {
    "japan": {
        "corpus": PROJECT_DIR / "sample_corpus",
        "profile": PROJECT_DIR / "examples" / "profiles" / "medieval-japan.json",
    },
    "rome": {
        "corpus": PROJECT_DIR / "sample_corpus_rome",
        "profile": PROJECT_DIR / "examples" / "profiles" / "ancient-rome.json",
    },
}
USED_HEADER = "id,type,persons,topics,short_description,source,date_used\n"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the universal research preview for Japan and/or Rome"
    )
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    parser.add_argument(
        "--work-dir",
        default=str(PROJECT_DIR / "work" / "research-demo"),
        help="Directory used only for generated demo files",
    )
    return parser


def run_scenario(name: str, work_root: Path) -> int:
    config = SCENARIOS[name]
    scenario_dir = work_root / name
    scenario_dir.mkdir(parents=True, exist_ok=True)
    database = scenario_dir / "index.sqlite3"
    used_finds = scenario_dir / "used_finds.csv"
    output = scenario_dir / "candidates.json"
    used_finds.write_text(USED_HEADER, encoding="utf-8-sig")

    print(f"\n=== {name.upper()}: build synthetic index ===")
    build_code = build_index.main(
        [
            str(config["corpus"]),
            "--db",
            str(database),
            "--drive-csv",
            str(scenario_dir / "drive.csv"),
            "--drive-jsonl",
            str(scenario_dir / "drive.jsonl"),
            "--log",
            str(scenario_dir / "index.log"),
            "--rebuild",
        ]
    )
    if build_code:
        return build_code

    print(f"\n=== {name.upper()}: profile preview ===")
    search_code = taira_search.main(
        [
            "research-findings",
            "--db",
            str(database),
            "--profile",
            str(config["profile"]),
            "--used-finds",
            str(used_finds),
            "--output",
            str(output),
            "--preview",
        ]
    )
    if search_code:
        return search_code
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        f"{name}: {len(payload['final'])} result(s); "
        f"profile={payload['profile']['name']!r}; output={output}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    build_index.configure_console()
    args = make_parser().parse_args(argv)
    work_root = Path(args.work_dir).expanduser().resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    names = SCENARIOS if args.scenario == "all" else (args.scenario,)
    for name in names:
        code = run_scenario(name, work_root)
        if code:
            return code
    print("\nResearch previews are local-only. No publication journal was updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
