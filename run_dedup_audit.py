"""Reproduce the documented 0.3 deduplication baseline.

This tool deliberately calls the existing 0.2 rules without changing them.  It
freezes their observable decisions on synthetic material so that a later,
small algorithm change can be measured against the same cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from daily_five import duplicate_check
from research_findings import _collapse_candidates


DEFAULT_CASES = Path("examples/dedup-benchmark/cases.json")


def _pool_reason(candidates: list[dict[str, Any]], collapsed: bool) -> str:
    if not collapsed:
        return "both candidates remain in the pool"
    first, second = sorted(candidates, key=lambda item: -item["retrieval_score"])
    nearby = (
        first["relative_path"] == second["relative_path"]
        and abs(first["chunk_no"] - second["chunk_no"]) <= 2
        and bool(set(first["topics"]) & set(second["topics"]))
    )
    if nearby:
        return "collapsed by same path, nearby chunk number, and shared topic"
    return "collapsed by source group, shared topic, and lexical similarity"


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    mode = case["mode"]
    if mode == "journal":
        decision = duplicate_check(case["candidate"], case["used"])
        actual = decision["status"]
        details = {
            "confidence": decision["confidence"],
            "reason": decision["reason"],
            "matched_id": decision["matched_id"],
        }
    elif mode == "candidate_pool":
        candidates = case["candidates"]
        retained = _collapse_candidates(candidates)
        actual = "collapsed" if len(retained) < len(candidates) else "kept"
        details = {
            "confidence": None,
            "reason": _pool_reason(candidates, actual == "collapsed"),
            "matched_id": None,
        }
    else:
        raise ValueError(f"{case['id']}: unsupported mode {mode!r}")

    return {
        "id": case["id"],
        "theme": case["theme"],
        "scenario": case["scenario"],
        "expected_semantic_decision": case["expected_semantic_decision"],
        "expected_current": case["expected_current"],
        "actual_current": actual,
        "baseline_matches": actual == case["expected_current"],
        **details,
    }


def _assessment(result: dict[str, Any]) -> str:
    desired = result["expected_semantic_decision"]
    actual = result["actual_current"]
    if desired == "confirmed_repeat":
        if actual in {"duplicate", "collapsed"}:
            return "correct"
        if actual == "duplicate_risk":
            return "underconfident_repeat"
        return "missed_repeat"
    if desired == "probable_repeat_review":
        if actual == "duplicate_risk":
            return "correct"
        if actual in {"duplicate", "collapsed"}:
            return "overconfident_repeat"
        return "missed_repeat"
    if desired == "new_angle":
        if actual in {"clear", "kept"}:
            return "new_angle_not_represented"
        return "false_repeat"
    if desired == "new_finding":
        return "correct" if actual in {"clear", "kept"} else "false_repeat"
    raise ValueError(f"unsupported semantic decision {desired!r}")


def audit_cases(path: Path = DEFAULT_CASES) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for case in payload["cases"]:
        result = run_case(case)
        result["assessment"] = _assessment(result)
        results.append(result)
    assessments = Counter(item["assessment"] for item in results)
    themes = sorted({item["theme"] for item in results})
    return {
        "schema_version": 1,
        "fixture": path.as_posix(),
        "case_count": len(results),
        "themes": themes,
        "summary": dict(sorted(assessments.items())),
        "baseline_mismatches": [
            item["id"] for item in results if not item["baseline_matches"]
        ],
        "results": results,
    }


def _escape(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Current deduplication baseline",
        "",
        "This is a measurement of the 0.2 rules, not a claim that every current decision is correct.",
        "",
        "| Case | Theme | Expected semantic decision | Current decision | Assessment | Current reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["results"]:
        lines.append(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    item["id"],
                    item["theme"],
                    item["expected_semantic_decision"],
                    item["actual_current"],
                    item["assessment"],
                    item["reason"],
                )
            )
            + " |"
        )
    lines.extend(["", "Summary:"])
    for key, value in report["summary"].items():
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
        help="fail only if the measured 0.2 baseline changed unexpectedly",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
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
    if args.check and report["baseline_mismatches"]:
        print(
            "Unexpected baseline changes: "
            + ", ".join(report["baseline_mismatches"]),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
