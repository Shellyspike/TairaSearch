"""Compare the frozen 0.2 baseline with the current 0.3 implementation.

The fixture keeps the measured 0.2 result as historical data and separately
states the expected result of reviewed improvements.  ``--check`` never
rewrites either expectation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from daily_five import candidate_pair_check, duplicate_check
from research_findings import _collapse_candidates


DEFAULT_CASES = Path("examples/dedup-benchmark/cases.json")


def configure_console() -> None:
    """Keep the multilingual report printable on Windows CI consoles."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    mode = case["mode"]
    if mode == "journal":
        decision = duplicate_check(case["candidate"], case["used"])
        actual = (
            "kept_for_review"
            if decision.get("requires_editorial_review")
            and not decision.get("auto_exclude")
            else decision["status"]
        )
        details = {
            "confidence": decision["confidence"],
            "reason": decision["reason"],
            "matched_id": decision["matched_id"],
        }
    elif mode == "candidate_pool":
        candidates = case["candidates"]
        retained = _collapse_candidates(candidates)
        pair = candidate_pair_check(*candidates)
        actual = (
            "collapsed"
            if len(retained) < len(candidates)
            else "kept_for_review"
            if pair["action"] == "review"
            else "kept"
        )
        details = {
            "confidence": pair["confidence"],
            "reason": pair["reason"],
            "matched_id": None,
        }
    else:
        raise ValueError(f"{case['id']}: unsupported mode {mode!r}")

    return {
        "id": case["id"],
        "theme": case["theme"],
        "scenario": case["scenario"],
        "expected_semantic_decision": case["expected_semantic_decision"],
        "baseline_0_2": case["baseline_0_2"],
        "expected_improved": case["expected_improved"],
        "actual_improved": actual,
        "improved_matches": actual == case["expected_improved"],
        **details,
    }


def _assessment(desired: str, actual: str) -> str:
    if desired == "confirmed_repeat":
        if actual in {"duplicate", "collapsed"}:
            return "correct"
        if actual in {"duplicate_risk", "kept_for_review"}:
            return "underconfident_repeat"
        return "missed_repeat"
    if desired == "probable_repeat_review":
        if actual in {"duplicate_risk", "kept_for_review"}:
            return "correct"
        if actual in {"duplicate", "collapsed"}:
            return "overconfident_repeat"
        return "missed_repeat"
    if desired == "new_angle":
        if actual in {"clear", "kept"}:
            return "new_angle_not_represented"
        if actual == "kept_for_review":
            return "new_angle_pending_review"
        return "false_repeat"
    if desired == "new_finding":
        if actual in {"clear", "kept"}:
            return "correct"
        if actual == "kept_for_review":
            return "preserved_for_review"
        return "false_repeat"
    raise ValueError(f"unsupported semantic decision {desired!r}")


def audit_cases(path: Path = DEFAULT_CASES) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for case in payload["cases"]:
        result = run_case(case)
        desired = result["expected_semantic_decision"]
        result["baseline_assessment"] = _assessment(desired, result["baseline_0_2"])
        result["improved_assessment"] = _assessment(desired, result["actual_improved"])
        results.append(result)
    baseline_assessments = Counter(item["baseline_assessment"] for item in results)
    improved_assessments = Counter(item["improved_assessment"] for item in results)
    themes = sorted({item["theme"] for item in results})
    return {
        "schema_version": 1,
        "fixture": path.as_posix(),
        "case_count": len(results),
        "themes": themes,
        "baseline_summary": dict(sorted(baseline_assessments.items())),
        "improved_summary": dict(sorted(improved_assessments.items())),
        "improved_mismatches": [
            item["id"] for item in results if not item["improved_matches"]
        ],
        "results": results,
    }


def _escape(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Deduplication benchmark: 0.2 baseline vs current branch",
        "",
        "The baseline is frozen historical data. Current decisions are measured from code.",
        "",
        "| Case | Expected semantic decision | 0.2 baseline | Current branch | Current assessment | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["results"]:
        lines.append(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    item["id"],
                    item["expected_semantic_decision"],
                    item["baseline_0_2"],
                    item["actual_improved"],
                    item["improved_assessment"],
                    item["reason"],
                )
            )
            + " |"
        )
    lines.extend(["", "0.2 baseline summary:"])
    for key, value in report["baseline_summary"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "Current branch summary:"])
    for key, value in report["improved_summary"].items():
        lines.append(f"- `{key}`: {value}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if current code differs from the reviewed improved expectations",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    args = build_parser().parse_args(argv)
    report = audit_cases(args.cases)
    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.check and report["improved_mismatches"]:
        print(
            "Unexpected improved-result changes: "
            + ", ".join(report["improved_mismatches"]),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
